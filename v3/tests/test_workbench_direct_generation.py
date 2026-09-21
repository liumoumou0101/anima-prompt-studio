"""Visible prompt submission remains explicit, revision-bound and resource-checked."""
from copy import deepcopy
from types import SimpleNamespace
import asyncio
import json

import pytest
from pydantic import ValidationError

from anima_prompt_studio_v3.api.models import DirectPromptSubmitRequest
from anima_prompt_studio_v3.api.workspace_store import WorkspaceRevisionConflictError
from anima_prompt_studio_v3.core.lora_resolution import ResourceUnavailable
from anima_prompt_studio_v3.core.requirements import WorkbenchError, digest
from anima_prompt_studio_v3.runtime.submissions import payload_digest
from anima_prompt_studio_v3.storage.generation_submissions import IdempotencyConflict
from test_generation_submissions import harness, payload, submit, workspace_payload
from test_api import reference_db


def current_prompt_request(store, *, first_manual=False):
    if first_manual:
        record = store.create("首次手写", {"model_profile": "anima_base_v1"})
        changes = {}
    else:
        record, _ = workspace_payload(store)
        requirements = deepcopy(record["draft"]["requirements"])
        requirements["layers"]["subject"]["text"] = "穿红外套的人"
        changes = {"requirements_edit": {"layers": requirements["layers"], "loras": []}}
    record = store.update(record["id"], expected_revision=record["revision"], title=record["title"],
        draft={**changes, "model_profile": "anima_base_v1",
               "prompt_edit": {"positive": "woman, red coat", "negative": "blurry"}})
    assert record["draft"]["compile_state"] == "stale"
    request = DirectPromptSubmitRequest(**{**payload().model_dump(exclude_unset=True), "submission_kind": "conversational",
        "workspace_id": record["id"], "workspace_revision": record["revision"],
        "compiled_token": record["draft"]["compiled"]["compiled_token"],
        "positive_prompt": "woman, red coat", "negative_prompt": "blurry", "use_current_prompt": True})
    return record, request


@pytest.mark.parametrize("first_manual", [False, True])
def test_explicit_current_prompt_accepts_saved_text_without_llm_and_keeps_receipt(harness, first_manual):
    store, start, _, executed, _, _ = harness
    _, service = start()
    before, request = current_prompt_request(store, first_manual=first_manual)
    response = submit(service, request)
    saved = store.get(before["id"])
    assert saved["revision"] == before["revision"] + 1
    assert saved["draft"]["compile_state"] == "fresh"
    assert saved["draft"]["compiled"]["source"] == "user"
    assert saved["draft"]["compiled"]["positive"] == request.positive_prompt
    assert saved["draft"]["compiled"]["negative"] == request.negative_prompt
    assert response["compiled_token"] != request.compiled_token
    snapshot = service.store.lookup("key")["snapshot"]
    assert snapshot["provenance"]["positive"] == request.positive_prompt
    assert snapshot["provenance"]["negative"] == request.negative_prompt
    assert snapshot["provenance"]["workspace_revision"] == saved["revision"]
    assert snapshot["resources"] == []
    assert submit(service, request, prepare=lambda: pytest.fail("accepted retry cannot prepare again")) == response
    assert not executed


@pytest.mark.parametrize("bad", ["token", "revision"])
def test_current_prompt_does_not_accept_obsolete_workspace_credentials(harness, bad):
    store, start, _, executed, _, _ = harness
    _, service = start()
    before, request = current_prompt_request(store)
    request = request.model_copy(update={"compiled_token": "cmp_" + "0" * 32} if bad == "token"
                                 else {"workspace_revision": before["revision"] - 1})
    with pytest.raises((WorkbenchError, WorkspaceRevisionConflictError)):
        submit(service, request)
    assert store.get(before["id"]) == before
    assert service.store.list() == [] and not executed


def test_current_prompt_rechecks_revision_after_resource_resolution(harness):
    store, start, _, executed, _, plan = harness
    before, request = current_prompt_request(store)
    def concurrent_plan(*args):
        store.rename(before["id"], expected_revision=before["revision"], title="另一个窗口修改")
        return plan(*args)
    _, service = start(plan_resolver=concurrent_plan)
    with pytest.raises(WorkspaceRevisionConflictError):
        submit(service, request)
    assert service.store.list() == [] and not executed
    assert store.get(before["id"])["draft"]["compile_state"] == "stale"


def test_current_prompt_cannot_bypass_resource_resolution(harness):
    store, start, _, executed, _, _ = harness
    before, request = current_prompt_request(store)
    def unavailable(*args):
        raise ResourceUnavailable("missing_lora", "缺少当前要求中的 LoRA")
    _, service = start(plan_resolver=unavailable)
    with pytest.raises(ResourceUnavailable):
        submit(service, request)
    assert store.get(before["id"]) == before
    assert service.store.list() == [] and not executed


def test_current_prompt_flag_is_part_of_idempotency_identity(harness):
    store, start, _, _, _, _ = harness
    _, service = start()
    _, request = current_prompt_request(store)
    submit(service, request)
    with pytest.raises(IdempotencyConflict):
        submit(service, request.model_copy(update={"use_current_prompt": False}))


def test_legacy_direct_receipt_digest_is_unchanged_by_opt_in_field():
    request = payload()
    legacy = request.model_dump(mode="json", by_alias=True)
    legacy.pop("use_current_prompt", None)
    assert payload_digest(request, "direct") == digest({"endpoint": "direct", "payload": legacy})


def test_current_prompt_requires_a_conversational_workspace():
    with pytest.raises(ValidationError):
        payload(use_current_prompt=True)


@pytest.mark.parametrize("changed", ["remote_profile_id", "workflow_profile_id", "model_profile_id"])
def test_current_prompt_snapshot_is_bound_to_original_target_and_model(harness, monkeypatch, changed):
    from test_v2_generation_adapter import workflow_profile
    store, start, _, executed, _, _ = harness
    before, request = current_prompt_request(store)
    queue, service = start()
    source = {"remote_profile_id": request.remote_profile_id, "workflow_profile_id": request.workflow_profile_id,
              "model_profile_id": request.model_profile}
    source[changed] = "different"
    old_get = queue.get
    monkeypatch.setattr(queue, "get", lambda run_id: SimpleNamespace(
        remote_profile_id=source["remote_profile_id"], workflow_profile_id=source["workflow_profile_id"],
        request_json={"workflow_snapshot": workflow_profile().model_dump(mode="json"),
                      "prompt_job": {"model_profile_id": source["model_profile_id"]}})
        if run_id == "source-run" else old_get(run_id))
    request = request.model_copy(update={"workflow_snapshot_run_id": "source-run"})
    with pytest.raises(WorkbenchError) as caught:
        submit(service, request)
    assert caught.value.code == "incompatible_workflow"
    assert store.get(before["id"]) == before
    assert service.store.list() == [] and not executed


def test_current_prompt_can_use_verified_snapshot_without_persistent_generation_source(harness, monkeypatch):
    from test_v2_generation_adapter import workflow_profile
    store, start, _, executed, _, base_plan = harness
    before, request = current_prompt_request(store)
    frozen = workflow_profile().model_dump(mode="json")
    def plan(prepared, remote, workflow, resources, source):
        assert source == frozen
        return base_plan(prepared, remote, workflow, resources, source)
    queue, service = start(plan_resolver=plan)
    old_get = queue.get
    monkeypatch.setattr(queue, "get", lambda run_id: SimpleNamespace(
        remote_profile_id=request.remote_profile_id, workflow_profile_id=request.workflow_profile_id,
        request_json={"workflow_snapshot": frozen, "prompt_job": {"model_profile_id": request.model_profile}})
        if run_id == "source-run" else old_get(run_id))
    request = request.model_copy(update={"workflow_snapshot_run_id": "source-run"})
    response = submit(service, request)
    assert service.store.lookup("key")["snapshot"]["workflow"] == frozen
    assert response["workspace_id"] == before["id"] and not executed


def test_rewrite_marks_visible_prompt_as_authoritative_over_older_unlocked_context(tmp_path, monkeypatch):
    from anima_prompt_studio_v3.api.conversation import ConversationService, TurnRequest
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    from test_conversation_reliability import prepared
    store, record = prepared(tmp_path)  # Older Chinese memory says blue coat.
    record = store.update(record["id"], expected_revision=record["revision"], title=record["title"],
        draft={"prompt_edit": {"positive": "detective, red coat", "negative": "blurry"}})
    requests = []
    async def complete(**kwargs):
        requests.append(json.loads(kwargs["messages"][-1]["content"]))
        return {"text": json.dumps({"touched_layers": ["subject", "lighting"],
            "layer_updates": {"subject": {"text": "红外套侦探"}, "lighting": {"text": "暖色光照"}},
            "positive": "detective, red coat, warm lighting", "negative": "blurry", "warnings": []})}
    monkeypatch.setattr(LLMService, "complete", complete)
    result = asyncio.run(ConversationService(store).turn(TurnRequest(
        workspace_id=record["id"], revision=record["revision"], preview=False,
        compiled={"positive": "detective, red coat", "negative": "blurry"},
        delta={"text": "只增强暖色光照，人物保持不变"})))
    assert len(requests) == 1
    assert requests[0]["prompt_authority"] == "visible_prompt"
    assert requests[0]["compiled"] == {"positive": "detective, red coat", "negative": "blurry"}
    assert requests[0]["requirements"]["layers"]["subject"]["text"] == "蓝外套侦探"
    assert result["draft"]["compiled"]["positive"] == "detective, red coat, warm lighting"
    assert result["draft"]["requirements"]["layers"]["subject"]["text"] == "红外套侦探"
    assert store.get_proposal(record["id"]) is None


def test_changing_model_then_generating_reuses_visible_prompt(harness):
    store, start, _, executed, _, _ = harness
    _, service = start()
    before, request = current_prompt_request(store)
    changed = store.update(before["id"], expected_revision=before["revision"], title=before["title"],
        draft={"model_profile": "anima_turbo_v1_1"})
    request = request.model_copy(update={"model_profile": "anima_turbo_v1_1", "workspace_revision": changed["revision"]})
    submit(service, request)
    job = service.store.lookup("key")["snapshot"]["job"]
    assert job["model_profile_id"] == "anima_turbo_v1_1"
    assert job["positive_prompt"] == "woman, red coat" and job["negative_prompt"] == "blurry"
    assert not executed


def test_current_prompt_still_rejects_request_model_different_from_saved_model(harness):
    store, start, _, executed, _, _ = harness
    _, service = start()
    before, request = current_prompt_request(store)
    with pytest.raises(WorkbenchError) as caught:
        submit(service, request.model_copy(update={"model_profile": "anima_turbo_v1_1"}))
    assert caught.value.code == "stale_compiled_prompt"
    assert store.get(before["id"]) == before
    assert service.store.list() == [] and not executed


def test_current_prompt_still_enforces_literal_prompt_locks(harness):
    store, start, _, executed, _, _ = harness
    _, service = start()
    before, request = current_prompt_request(store)
    requirements = deepcopy(before["draft"]["requirements"])
    requirements["prompt_locks"] = [{"target": "positive", "text": "red coat"}]
    locked = store.update(before["id"], expected_revision=before["revision"], title=before["title"],
        draft={"model_profile": "anima_base_v1", "requirements_edit": {
            "layers": requirements["layers"], "loras": [], "prompt_locks": requirements["prompt_locks"]}})
    request = request.model_copy(update={"workspace_revision": locked["revision"], "positive_prompt": "woman, blue coat"})
    with pytest.raises(WorkbenchError) as caught:
        submit(service, request)
    assert caught.value.code == "protected_prompt_changed"
    assert store.get(before["id"]) == locked
    assert service.store.list() == [] and not executed


def test_direct_api_accepts_first_manual_prompt_with_explicit_flag(harness, reference_db):
    from fastapi.testclient import TestClient
    from anima_prompt_studio_v3.api import create_api_runtime
    store, start, _, executed, _, _ = harness
    before, request = current_prompt_request(store, first_manual=True)
    queue, _ = start()
    runtime = create_api_runtime(reference_db, workspace_db=store.path, generation_queue=queue)
    runtime.app.state.submission_service.close()
    with TestClient(runtime.app, base_url="http://127.0.0.1") as client:
        client.headers["Origin"] = "http://127.0.0.1"
        exchange = client.post("/api/v3/session/exchange", json={"bootstrap_token": runtime.bootstrap_token})
        client.headers["X-Anima-Session"] = exchange.json()["session_token"]
        response = client.post("/api/v3/direct-prompt/runs", json=request.model_dump(exclude_unset=True),
            headers={"Idempotency-Key": "manual"})
        assert response.status_code == 202, response.text
        assert response.json()["workspace_id"] == before["id"]
        run = client.get("/api/v3/generation-runs/" + response.json()["id"]).json()
        assert run["source"]["positive_prompt"] == "woman, red coat"
        assert run["source"]["negative_prompt"] == "blurry"
        assert not executed
