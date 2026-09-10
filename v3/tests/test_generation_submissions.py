from threading import Event

import pytest
from pydantic import ValidationError
from anima_prompt_studio.domain.execution_models import GenerationRunState, RemoteCredentials, WorkflowProfile
from anima_prompt_studio_v3.api.models import DirectPromptSubmitRequest, WorkspaceDraft
from anima_prompt_studio_v3.api.workspace_store import WorkspaceStore, WorkspaceRevisionConflictError
from anima_prompt_studio_v3.core.requirements import PromptEdit, compile_prompt
from anima_prompt_studio_v3.remote.execution_coordinator import ExecutionResult
from anima_prompt_studio_v3.runtime.generation import CandidateToPromptJobAdapter
from anima_prompt_studio_v3.runtime.generation_queue import GenerationQueueService, GenerationTarget, GenerationQueueFullError
from anima_prompt_studio_v3.runtime.submissions import SubmissionService
from anima_prompt_studio_v3.runtime.workflow_catalog import fingerprint
from anima_prompt_studio_v3.storage.generation_submissions import IdempotencyConflict
from test_conversation import edit
from test_v2_generation_adapter import workflow_profile, remote_profile
from test_api import reference_db


@pytest.fixture
def harness(tmp_path):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    saved, executed, queues, services = {}, [], [], []
    finished = Event()
    target = GenerationTarget(remote_profile(), workflow_profile(), RemoteCredentials(), tmp_path)

    def plan(prepared, remote, workflow, resources, frozen):
        graph = WorkflowProfile.model_validate(frozen) if frozen else target.workflow_profile.model_copy(deep=True)
        return prepared, GenerationTarget(target.remote_profile, graph, target.credentials, target.output_root), {
            "bindings": [], "availability": "ready", "remote_fingerprint": fingerprint(target.remote_profile)}

    class Coordinator:
        def execute(self, job, *args, run):
            executed.append((job.model_copy(deep=True), run.id))
            run.update_state(GenerationRunState.COMPLETED, "done", 1)
            finished.set()
            return ExecutionResult(run=run, artifacts=[])

    def start(**kwargs):
        queue = GenerationQueueService(lambda *_: target, coordinator_factory=kwargs.pop("coordinator_factory", lambda *_: Coordinator()),
            plan_resolver=kwargs.pop("plan_resolver", plan),
            on_run_saved=lambda run: saved.update({run.id: run.model_copy(deep=True)}),
            durable_run_loader=lambda run_id: saved.get(run_id), **kwargs)
        queues.append(queue)
        service = SubmissionService(store, queue, lambda run: {"id": run.id}, start=False)
        services.append(service)
        return queue, service

    yield store, start, saved, executed, finished, plan
    for service in services:
        service.close()
    for queue in queues:
        queue.shutdown()


def payload(**changes):
    return DirectPromptSubmitRequest(positive_prompt="cat", model_profile="anima_base_v1",
        remote_profile_id="remote-1", workflow_profile_id="anima_base_api_v1", **changes)


def submit(service, request=None, key="key", prepare=None):
    request = request or payload()
    return service.submit(request, key, "direct", prepare or (lambda: CandidateToPromptJobAdapter().prepare_direct(
        positive_prompt=request.positive_prompt, negative_prompt=request.negative_prompt, model_profile_id=request.model_profile)))


def workspace_payload(store):
    workspace = store.create("test", WorkspaceDraft(model_profile="anima_base_v1", requirements_edit=edit()).persistence_payload())
    def compile(draft):
        draft["compiled"] = compile_prompt(draft, PromptEdit(positive="original", negative=""), source="llm")
        return draft
    workspace = store.transform(workspace["id"], expected_revision=workspace["revision"], operation=compile)
    return workspace, payload(submission_kind="conversational", workspace_id=workspace["id"],
        workspace_revision=workspace["revision"], compiled_token=workspace["draft"]["compiled"]["compiled_token"])


def test_acceptance_atomically_saves_manual_prompt_and_retry_precedes_stale_check(harness):
    store, start, saved, executed, finished, _ = harness
    queue, service = start()
    workspace, request = workspace_payload(store)
    response = submit(service, request)
    updated = store.get(workspace["id"])
    assert updated["revision"] == workspace["revision"] + 1
    assert updated["draft"]["compiled"]["source"] == "user"
    assert updated["draft"]["compiled"]["positive"] == "cat"
    assert response["compiled_token"] == updated["draft"]["compiled"]["compiled_token"]
    assert submit(service, request, prepare=lambda: pytest.fail("retry must not prepare")) == response
    entry = service.store.lookup("key")
    assert entry["snapshot"]["provenance"]["requirements"] == updated["draft"]["requirements"]
    assert entry["snapshot"]["job"]["generation_params"]["seed"] >= 0
    assert not executed and not saved
    assert queue.available_actions(response["id"]) == ["cancel_queued"]
    service.dispatch_pending()
    assert finished.wait(2)
    assert executed[0][0].generation_params.seed == entry["snapshot"]["job"]["generation_params"]["seed"]
    assert submit(service, request) == response
    assert len(executed) == 1


def reference_source():
    from anima_prompt_studio_v3.core.requirements import Requirements
    return {"id": "ex_abc", "source_version": "2", "requirements_valid": True,
        "requirements": Requirements(**edit()).model_dump(mode="json", by_alias=True),
        "compat": {"model_profiles": ["anima_base_v1"], "workflow_kinds": [], "workflow_snapshot_ref": None},
        "notes": {"external_prompt": "private notes must not enter the run"}}


def test_reference_submit_freezes_source_and_retry_survives_source_deletion(harness):
    _, start, _, executed, finished, _ = harness
    _, service = start()
    source = reference_source()
    def get(example_id, version):
        assert (example_id, version) == ("ex_abc", "2")
        return source
    service.reference_get = get
    request = payload(submission_kind="reference", reference_preset_id="ex_abc", source_version="2")
    accepted = submit(service, request)
    snapshot = service.store.lookup("key")["snapshot"]
    assert snapshot["reference"]["source_snapshot"]["requirements"] == source["requirements"]
    assert "notes" not in snapshot["reference"] and "workspace_id" not in snapshot
    source["requirements"]["layers"]["subject"]["text"] = "edited after acceptance"
    service.reference_get = lambda *_: pytest.fail("accepted retry must not reload deleted source")
    assert submit(service, request) == accepted
    service.dispatch_pending()
    assert finished.wait(2) and len(executed) == 1
    assert service.store.lookup("key")["snapshot"] == snapshot


def test_reference_compatibility_and_version_checked_before_acceptance(harness):
    from anima_prompt_studio_v3.core.requirements import WorkbenchError
    _, start, _, _, _, _ = harness
    _, service = start()
    source = reference_source()
    def get(example_id, version):
        if version != source["source_version"]:
            raise WorkbenchError("reference_version_conflict", "changed")
        return source
    service.reference_get = get
    request = payload(submission_kind="reference", reference_preset_id="ex_abc", source_version="1")
    with pytest.raises(WorkbenchError) as caught:
        submit(service, request)
    assert caught.value.code == "reference_version_conflict"
    source["compat"]["model_profiles"] = ["other_model"]
    with pytest.raises(WorkbenchError) as caught:
        submit(service, request.model_copy(update={"source_version": "2"}))
    assert caught.value.code == "reference_preset_unavailable"
    assert service.store.list() == []


def test_reference_explicit_empty_resources_stays_empty(harness):
    _, start, _, _, _, _ = harness
    _, service = start()
    source = reference_source()
    source["requirements"]["loras"] = [{"logical_id": "style", "file_name": "style.safetensors", "weight": 1,
        "trigger_words": [], "required": True, "source": {"kind": "user", "model_version_id": None}}]
    service.reference_get = lambda *_: source
    submit(service, payload(submission_kind="reference", reference_preset_id="ex_abc", source_version="2", lora_selection=[]))
    snapshot = service.store.lookup("key")["snapshot"]
    assert snapshot["resources"] == snapshot["requirements"]["loras"] == []
    assert snapshot["reference"]["source_snapshot"]["requirements"]["loras"] == source["requirements"]["loras"]


def test_deleted_workspace_lora_requires_recompile_and_never_reaches_dispatch(harness):
    from anima_prompt_studio_v3.core.requirements import WorkbenchError
    store, start, _, executed, finished, plan = harness
    planned_resources = []

    def captured_plan(prepared, remote, workflow, resources, frozen):
        planned_resources.append(list(resources))
        return plan(prepared, remote, workflow, resources, frozen)

    _, service = start(plan_resolver=captured_plan)
    initial = edit(loras=[{"logical_id":"test_style","file_name":"test_style.safetensors",
                           "weight":0.8,"trigger_words":[],"required":True}])
    w = store.create("delete resource", WorkspaceDraft(model_profile="anima_base_v1", requirements_edit=initial).persistence_payload())

    def compiled(draft):
        draft["compiled"] = compile_prompt(draft, PromptEdit(positive="cat", negative=""), source="llm")
        return draft

    w = store.transform(w["id"], expected_revision=w["revision"], operation=compiled)
    old_token = w["draft"]["compiled"]["compiled_token"]
    edited = {"layers": w["draft"]["requirements"]["layers"], "loras": []}
    w = store.update(w["id"], expected_revision=w["revision"], title="deleted",
                     draft={"model_profile":"anima_base_v1", "requirements_edit":edited})
    assert w["draft"]["compile_state"] == "stale"
    request = payload(submission_kind="conversational", workspace_id=w["id"],
                      workspace_revision=w["revision"], compiled_token=old_token)
    with pytest.raises(WorkbenchError) as caught:
        submit(service, request)
    assert caught.value.code == "stale_compiled_prompt"
    assert not planned_resources and not service.store.list()
    w = store.transform(w["id"], expected_revision=w["revision"], operation=compiled)
    assert w["draft"]["compiled"]["compiled_token"] != old_token
    submit(service, request.model_copy(update={"workspace_revision":w["revision"],
        "compiled_token":w["draft"]["compiled"]["compiled_token"]}))
    snapshot = service.store.lookup("key")["snapshot"]
    assert snapshot["resources"] == snapshot["provenance"]["requirements"]["loras"] == []
    service.dispatch_pending()
    assert finished.wait(2)
    assert len(planned_resources) >= 2 and all(resources == [] for resources in planned_resources)
    assert len(executed) == 1


def test_payload_conflict_and_capacity_share_legacy_queue(harness):
    _, start, _, _, _, _ = harness
    queue, service = start(max_pending=1)
    submit(service)
    with pytest.raises(IdempotencyConflict):
        submit(service, payload(project_name="different"))
    submit(service, key="second")
    with pytest.raises(GenerationQueueFullError):
        submit(service, key="third")
    prepared = CandidateToPromptJobAdapter().prepare_direct(positive_prompt="legacy", model_profile_id="anima_base_v1")
    with pytest.raises(GenerationQueueFullError):
        queue.submit(prepared, remote_profile_id="remote-1", workflow_profile_id="anima_base_api_v1", idempotency_key="legacy")
    assert service.store.lookup("third") is None


def test_workspace_edit_during_resolution_rejects_without_accepting(harness):
    store, start, _, _, _, original_plan = harness
    workspace, request = workspace_payload(store)
    def concurrent_plan(*args):
        store.update(workspace["id"], expected_revision=workspace["revision"], title="edited", draft={})
        return original_plan(*args)
    _, service = start(plan_resolver=concurrent_plan)
    with pytest.raises(WorkspaceRevisionConflictError):
        submit(service, request)
    assert service.store.lookup("key") is None
    assert store.get(workspace["id"])["draft"]["compiled"]["positive"] == "original"


@pytest.mark.parametrize("persisted", [False, True])
def test_restart_before_delivery_reuses_run_once(harness, persisted):
    _, start, saved, executed, finished, _ = harness
    queue, service = start()
    response = submit(service)
    if persisted:
        saved[response["id"]] = queue.get(response["id"])
    service.close()
    queue.shutdown()
    next_queue, next_service = start()
    assert submit(next_service) == response
    next_service.dispatch_pending()
    assert finished.wait(2)
    next_service.dispatch_pending()
    assert [run_id for _, run_id in executed] == [response["id"]]


@pytest.mark.parametrize("state", ["canceled", "uncertain", "missing_enqueued"])
def test_restart_never_resubmits_canceled_or_uncertain_run(harness, state):
    _, start, saved, executed, _, _ = harness
    queue, service = start()
    response = submit(service)
    if state == "canceled":
        queue.cancel_queued(response["id"])
    elif state == "uncertain":
        run = queue.get(response["id"])
        run.request_json["dispatch_started"] = True
        saved[run.id] = run
    else:
        service.store.mark(response["submission_id"], "enqueued")
    service.close()
    queue.shutdown()
    next_queue, next_service = start()
    next_service.dispatch_pending()
    assert not executed
    assert next_queue.available_actions(response["id"]) == []
    if state != "canceled":
        assert next_queue.get(response["id"]).error_code == "generation_execution_uncertain"


def test_execution_revalidates_frozen_resources(harness):
    _, start, _, executed, _, original_plan = harness
    checked = Event()
    calls = []
    def changing_plan(*args):
        calls.append(1)
        result = original_plan(*args)
        if len(calls) == 3:
            result[1].workflow_profile.api_workflow["6"]["inputs"]["text"] = "tampered"
            checked.set()
        return result
    queue, service = start(plan_resolver=changing_plan)
    response = submit(service)
    service.dispatch_pending()
    assert checked.wait(2)
    queue.shutdown()
    assert not executed
    assert queue.get(response["id"]).state == GenerationRunState.FAILED


@pytest.mark.parametrize("extra", [
    {"submission_kind": "conversational"},
    {"compiled_token": "unexpected"},
    {"submission_kind": "reference", "reference_preset_id": "x"},
    {"submission_kind": "conversational", "workspace_id": "workspace_1", "workspace_revision": 1,
     "compiled_token": "x", "lora_selection": []},
])
def test_submission_modes_reject_ambiguous_fields(extra):
    with pytest.raises(ValidationError):
        payload(**extra)


def test_unchanged_prompt_keeps_compile_token_and_revision(harness):
    store, start, _, _, _, _ = harness
    _, service = start()
    workspace, request = workspace_payload(store)
    request.positive_prompt = "original"
    response = submit(service, request)
    assert response["workspace_revision"] == workspace["revision"]
    assert response["compiled_token"] == request.compiled_token
    assert store.get(workspace["id"])["draft"]["compiled"]["source"] == "llm"


def test_failed_acceptance_rolls_back_prompt_and_capacity(harness):
    store, start, _, _, _, _ = harness
    queue, service = start()
    workspace, request = workspace_payload(store)
    service.response_factory = lambda run: {"unserializable": object()}
    with pytest.raises(TypeError):
        submit(service, request)
    assert store.get(workspace["id"]) == workspace
    assert service.store.lookup("key") is None
    assert queue.reserved_ids() == []


def test_concurrent_retry_allocates_one_run(harness):
    from concurrent.futures import ThreadPoolExecutor
    _, start, _, _, _, _ = harness
    queue, service = start()
    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(executor.map(lambda _: submit(service), range(8)))
    assert all(response == responses[0] for response in responses)
    assert len(queue.reserved_ids()) == len(service.store.list()) == 1


def test_api_durable_submission_and_global_conflict(harness, reference_db):
    from fastapi.testclient import TestClient
    from anima_prompt_studio_v3.api import create_api_runtime
    store, start, _, _, _, _ = harness
    queue, service = start()
    workspace, request = workspace_payload(store)
    runtime = create_api_runtime(reference_db, workspace_db=store.path, generation_queue=queue)
    runtime.app.state.submission_service.close()
    with TestClient(runtime.app, base_url="http://127.0.0.1") as client:
        client.headers["Origin"] = "http://127.0.0.1"
        exchange = client.post("/api/v3/session/exchange", json={"bootstrap_token": runtime.bootstrap_token})
        client.headers["X-Anima-Session"] = exchange.json()["session_token"]
        data = request.model_dump(exclude_unset=True)
        first = client.post("/api/v3/direct-prompt/runs", json=data, headers={"Idempotency-Key": "http"})
        assert first.status_code == 202, first.text
        second = client.post("/api/v3/direct-prompt/runs", json=data, headers={"Idempotency-Key": "http"})
        assert second.json() == first.json()
        data["positive_prompt"] = "different"
        conflict = client.post("/api/v3/direct-prompt/runs", json=data, headers={"Idempotency-Key": "http"})
        assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "idempotency_conflict"
        availability = client.get("/api/v3/workbench/availability", params={"workspace_id": workspace["id"],
            "revision": first.json()["workspace_revision"], "remote_profile_id": request.remote_profile_id,
            "workflow_profile_id": request.workflow_profile_id})
        assert availability.status_code == 200, availability.text
        assert availability.json()["availability"] == "ready"
        runs = client.get(f"/api/v3/workspaces/{workspace['id']}/runs")
        assert runs.status_code == 200 and runs.json()["items"][0]["id"] == first.json()["id"]
        assert client.get(f"/api/v3/generation-runs/{first.json()['id']}/artifacts").json() == {"items": []}
        assert client.get("/api/v3/generation-runs/missing/artifacts").status_code == 404


def test_lost_remote_ack_is_uncertain_and_has_no_resampling_action(harness, tmp_path):
    from anima_prompt_studio_v3.remote.execution_coordinator import RemoteExecutionCoordinator
    from anima_prompt_studio_v3.remote.result_organizer import ResultOrganizer
    from test_v2_generation_adapter import FakeClient, FakeTunnel
    _, start, _, _, _, _ = harness
    submitted = Event()
    class LostAckClient(FakeClient):
        def submit(self, *_):
            submitted.set()
            raise TimeoutError("private connection details")
    queue, service = start(coordinator_factory=lambda path, update: RemoteExecutionCoordinator(
        organizer=ResultOrganizer(path), tunnel_factory=FakeTunnel,
        client_factory=lambda _: LostAckClient(), on_update=update))
    response = submit(service)
    service.dispatch_pending()
    assert submitted.wait(2)
    queue.shutdown()
    run = queue.get(response["id"])
    assert run.state == GenerationRunState.FAILED
    assert run.error_code == "generation_execution_uncertain"
    assert "private" not in run.error_message
    assert queue.available_actions(run.id) == []
    assert submit(service) == response
