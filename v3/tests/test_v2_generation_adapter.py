from __future__ import annotations

import json
from pathlib import Path
from threading import Event
from time import monotonic, sleep

import pytest

from anima_prompt_studio.domain.execution_models import (
    GenerationRun,
    GenerationRunState,
    RemoteArtifact,
    RemoteCredentials,
    RemoteProfile,
    WorkflowBinding,
    WorkflowProfile,
)
from anima_prompt_studio.services.remote.execution_coordinator import RemoteExecutionCoordinator
from anima_prompt_studio.services.remote.result_organizer import ResultOrganizer
from anima_prompt_studio.repositories.sqlite_repository import SQLiteRepository

from anima_prompt_studio_v3.adapters.v2 import (
    BRIDGE_SCHEMA,
    CandidateToV2PromptJobAdapter,
    GenerationRunActionError,
    V2GenerationSettings,
    V2GenerationQueueService,
    V2GenerationTarget,
    build_v2_generation_queue,
)
from anima_prompt_studio_v3.domain import (
    CandidateArtist,
    CandidateLane,
    CandidateTag,
    CandidateTagState,
    CandidateVersions,
    ConstraintGraph,
    ElementProvenance,
    IntentDocument,
    IntentElement,
    IntentElementType,
    IntentState,
    PromptCandidate,
    ProvenanceKind,
    TagSource,
)


def sample_intent() -> IntentDocument:
    return IntentDocument(
        source_text="女仆、双马尾，不要金发",
        source_language="zh",
        graph=ConstraintGraph(
            elements=[
                IntentElement(
                    id="e_maid",
                    original_text="女仆",
                    canonical_tag="maid",
                    type=IntentElementType.CLOTHING,
                    state=IntentState.LOCKED,
                    confidence=1,
                    provenance=ElementProvenance(kind=ProvenanceKind.USER),
                ),
                IntentElement(
                    id="e_excluded",
                    original_text="金发",
                    canonical_tag="blonde_hair",
                    type=IntentElementType.APPEARANCE,
                    state=IntentState.EXCLUDED,
                    confidence=1,
                    provenance=ElementProvenance(kind=ProvenanceKind.USER),
                ),
            ]
        ),
    )


def sample_candidate() -> PromptCandidate:
    return PromptCandidate(
        id="candidate_artist",
        lane=CandidateLane.ARTIST,
        title="单画师风格",
        positive_prompt="score_7, maid, @motizou",
        negative_prompt="worst quality, blonde hair",
        tags=[
            CandidateTag(
                name="maid",
                rendered="maid",
                state=CandidateTagState.LOCKED,
                source=TagSource.EXACT,
                source_element_ids=["e_maid"],
                reason="精确匹配",
                data_pack_id="pack-r1",
                algorithm_version="literal-v1",
                removable=False,
            )
        ],
        artists=[
            CandidateArtist(
                name="motizou",
                rendered="@motizou",
                source_element_ids=["e_maid"],
                reason="匹配 maid",
                raw_score=.8,
                display_score=1,
                data_pack_id="pack-r1",
                algorithm_version="artist-v1",
            )
        ],
        preserved_element_ids=["e_maid"],
        versions=CandidateVersions(
            data_pack="pack-r1",
            algorithm="artist-v1",
            templates="anima-renderer-v1",
            model_profile="anima_base_v1",
        ),
    )


def test_adapter_preserves_candidate_prompt_versions_and_generation_defaults() -> None:
    prepared = CandidateToV2PromptJobAdapter().prepare(
        sample_candidate(),
        sample_intent(),
        project_name="V3 女仆",
        settings=V2GenerationSettings(seed=42, batch_size=2),
        workspace_id="workspace_1",
        workspace_revision=3,
    )
    job = prepared.job

    assert job.positive_prompt == "score_7, maid, @motizou"
    assert job.negative_prompt == "worst quality, blonde hair"
    assert job.compiled_prompt_state.value == "locked"
    assert job.excluded_tags == ["blonde_hair"]
    assert job.locked_tags == ["maid"]
    assert job.artist_selection == ["motizou"]
    assert (job.generation_params.steps, job.generation_params.cfg) == (35, 4.5)
    assert (job.generation_params.seed, job.generation_params.batch_size) == (42, 2)
    assert prepared.checkpoint_logical_name == "anima_base_v1"
    assert job.integration_metadata["schema"] == BRIDGE_SCHEMA
    assert job.integration_metadata["candidate"]["versions"]["data_pack"] == "pack-r1"
    assert job.task_package()["integration_metadata"]["workspace"] == {"id": "workspace_1", "revision": 3}


def test_adapter_prefers_explicit_v3_advanced_parameters_over_legacy_preset() -> None:
    prepared = CandidateToV2PromptJobAdapter().prepare(
        sample_candidate(),
        sample_intent(),
        settings=V2GenerationSettings(
            preset_id="balanced",
            width=1216,
            height=832,
            steps=44,
            cfg=3.7,
            sampler="dpmpp_2m_sde",
            scheduler="karras",
            seed=7,
            batch_size=3,
        ),
    )

    params = prepared.job.generation_params
    assert (params.width, params.height) == (1216, 832)
    assert (params.steps, params.cfg) == (44, 3.7)
    assert (params.sampler, params.scheduler) == ("dpmpp_2m_sde", "karras")
    assert (params.seed, params.batch_size) == (7, 3)


def test_prepared_v3_candidate_runs_through_unchanged_v2_remote_coordinator(tmp_path: Path) -> None:
    prepared = CandidateToV2PromptJobAdapter().prepare(sample_candidate(), sample_intent())
    coordinator = RemoteExecutionCoordinator(
        organizer=ResultOrganizer(tmp_path),
        tunnel_factory=FakeTunnel,
        client_factory=lambda _url: FakeClient(),
        poll_interval=0,
    )

    result = coordinator.execute(
        prepared.job,
        remote_profile(),
        workflow_profile(),
        prepared.checkpoint_logical_name,
    )

    assert result.run.state == GenerationRunState.COMPLETED
    manifest = json.loads((Path(result.run.output_dir) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["prompt_job"]["positive_prompt"] == "score_7, maid, @motizou"
    assert manifest["prompt_job"]["integration_metadata"]["schema"] == BRIDGE_SCHEMA
    assert manifest["prompt_job"]["integration_metadata"]["candidate"]["id"] == "candidate_artist"


def test_ui_independent_queue_is_fifo_idempotent_and_cancels_waiting_job(tmp_path: Path) -> None:
    prepared = CandidateToV2PromptJobAdapter().prepare(sample_candidate(), sample_intent())
    client = BlockingFakeClient()
    saved_states: list[tuple[str, GenerationRunState]] = []

    def resolve(_remote_id: str, _workflow_id: str) -> V2GenerationTarget:
        return V2GenerationTarget(
            remote_profile=remote_profile(),
            workflow_profile=workflow_profile(),
            credentials=RemoteCredentials(),
            output_root=tmp_path,
        )

    def coordinator_factory(output_root: Path, on_update):
        return RemoteExecutionCoordinator(
            organizer=ResultOrganizer(output_root),
            tunnel_factory=FakeTunnel,
            client_factory=lambda _url: client,
            on_update=on_update,
            poll_interval=0,
        )

    queue = V2GenerationQueueService(
        resolve,
        coordinator_factory=coordinator_factory,
        on_run_saved=lambda run: saved_states.append((run.id, run.state)),
        max_pending=1,
    )
    try:
        first = queue.submit(
            prepared,
            remote_profile_id="remote-1",
            workflow_profile_id="anima_base_api_v1",
            idempotency_key="first",
        )
        assert client.started.wait(2)
        duplicate = queue.submit(
            prepared,
            remote_profile_id="remote-1",
            workflow_profile_id="anima_base_api_v1",
            idempotency_key="first",
        )
        assert duplicate.id == first.id

        second = queue.submit(
            prepared,
            remote_profile_id="remote-1",
            workflow_profile_id="anima_base_api_v1",
            idempotency_key="second",
        )
        canceled = queue.cancel_queued(second.id)
        assert canceled.state == GenerationRunState.CANCELED
        with pytest.raises(GenerationRunActionError):
            queue.cancel_queued(first.id)

        client.release.set()
        completed = wait_for_state(queue, first.id, GenerationRunState.COMPLETED)
        assert completed.request_json["prompt_job"]["integration_metadata"]["candidate"]["id"] == "candidate_artist"
        assert len(queue.artifacts(first.id)) == 1
        assert (first.id, GenerationRunState.RUNNING) in saved_states
    finally:
        client.release.set()
        queue.shutdown(timeout=2)


def test_v2_database_queue_factory_reuses_profiles_and_persists_results(tmp_path: Path) -> None:
    database = tmp_path / "v2.db"
    repository = SQLiteRepository(database)
    repository.save_remote_profile(remote_profile())
    repository.save_workflow_profile(workflow_profile())
    repository.set_setting("generation_output_root", str(tmp_path / "outputs"))
    repository.close()

    def coordinator_factory(output_root: Path, on_update):
        return RemoteExecutionCoordinator(
            organizer=ResultOrganizer(output_root),
            tunnel_factory=FakeTunnel,
            client_factory=lambda _url: FakeClient(),
            on_update=on_update,
            poll_interval=0,
        )

    queue = build_v2_generation_queue(database, coordinator_factory=coordinator_factory)
    try:
        prepared = CandidateToV2PromptJobAdapter().prepare(sample_candidate(), sample_intent())
        submitted = queue.submit(
            prepared,
            remote_profile_id="remote-1",
            workflow_profile_id="anima_base_api_v1",
            idempotency_key="persisted-run",
        )
        wait_for_state(queue, submitted.id, GenerationRunState.COMPLETED)
    finally:
        queue.shutdown(timeout=2)

    reopened = SQLiteRepository(database)
    try:
        persisted = reopened.get_generation_run(submitted.id)
        assert persisted.state == GenerationRunState.COMPLETED
        assert reopened.load_job(prepared.job.id).integration_metadata["schema"] == BRIDGE_SCHEMA
        assert len(reopened.list_generation_artifacts(submitted.id)) == 1
    finally:
        reopened.close()

    restarted = build_v2_generation_queue(database, coordinator_factory=coordinator_factory)
    try:
        duplicate = restarted.submit(
            prepared,
            remote_profile_id="remote-1",
            workflow_profile_id="anima_base_api_v1",
            idempotency_key="persisted-run",
        )
        assert duplicate.id == submitted.id
        assert duplicate.state == GenerationRunState.COMPLETED
    finally:
        restarted.shutdown(timeout=2)


def test_database_queue_uses_private_key_passphrase_only_from_process_memory(tmp_path: Path) -> None:
    database = tmp_path / "v2-passphrase.db"
    repository = SQLiteRepository(database)
    repository.save_remote_profile(remote_profile())
    repository.save_workflow_profile(workflow_profile())
    repository.set_setting("generation_output_root", str(tmp_path / "outputs"))
    repository.close()
    opened_with: list[str] = []

    class CapturingTunnel(FakeTunnel):
        def open(self, credentials):
            opened_with.append(credentials.passphrase)
            return self

    def coordinator_factory(output_root: Path, on_update):
        return RemoteExecutionCoordinator(
            organizer=ResultOrganizer(output_root),
            tunnel_factory=CapturingTunnel,
            client_factory=lambda _url: FakeClient(),
            on_update=on_update,
            poll_interval=0,
        )

    secret = "memory-only-secret"
    queue = build_v2_generation_queue(database, coordinator_factory=coordinator_factory)
    try:
        assert queue.targets()[0]["private_key_passphrase_configured"] is False
        queue.set_private_key_passphrase("remote-1", secret)
        assert queue.targets()[0]["private_key_passphrase_configured"] is True
        prepared = CandidateToV2PromptJobAdapter().prepare(sample_candidate(), sample_intent())
        run = queue.submit(
            prepared,
            remote_profile_id="remote-1",
            workflow_profile_id="anima_base_api_v1",
            idempotency_key="passphrase-run",
        )
        wait_for_state(queue, run.id, GenerationRunState.COMPLETED)
    finally:
        queue.shutdown(timeout=2)

    assert opened_with == [secret]
    assert secret.encode() not in database.read_bytes()

    restarted = build_v2_generation_queue(database, coordinator_factory=coordinator_factory)
    try:
        assert restarted.targets()[0]["private_key_passphrase_configured"] is False
    finally:
        restarted.shutdown(timeout=2)


def test_queue_resumes_persisted_remote_run_without_resubmitting(tmp_path: Path) -> None:
    prepared = CandidateToV2PromptJobAdapter().prepare(sample_candidate(), sample_intent())
    existing = GenerationRun(
        prompt_job_id=prepared.job.id,
        remote_profile_id="remote-1",
        workflow_profile_id="anima_base_api_v1",
        remote_prompt_id="already-remote",
        state=GenerationRunState.RUNNING,
        progress=0.5,
        request_json={"prompt_job": prepared.job.model_dump(mode="json")},
    )

    def resolve(_remote_id: str, _workflow_id: str) -> V2GenerationTarget:
        return V2GenerationTarget(
            remote_profile=remote_profile(),
            workflow_profile=workflow_profile(),
            credentials=RemoteCredentials(),
            output_root=tmp_path,
        )

    def coordinator_factory(output_root: Path, on_update):
        return RemoteExecutionCoordinator(
            organizer=ResultOrganizer(output_root),
            tunnel_factory=FakeTunnel,
            client_factory=lambda _url: FakeClient(),
            on_update=on_update,
            poll_interval=0,
        )

    queue = V2GenerationQueueService(
        resolve,
        coordinator_factory=coordinator_factory,
        existing_runs=[existing],
        target_lister=lambda: [{"remote_profile_id": "remote-1"}],
    )
    try:
        assert queue.available_actions(existing.id) == ["retry_check"]
        resumed = queue.resume(existing.id)
        assert resumed.id == existing.id
        with pytest.raises(GenerationRunActionError):
            queue.resume(existing.id)
        completed = wait_for_state(queue, existing.id, GenerationRunState.COMPLETED)
        assert completed.remote_prompt_id == "already-remote"
        assert len(queue.artifacts(existing.id)) == 1
        assert queue.targets() == [{"remote_profile_id": "remote-1"}]
    finally:
        queue.shutdown(timeout=2)


def workflow_profile() -> WorkflowProfile:
    workflow = {
        "3": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 10, "cfg": 1, "sampler_name": "euler", "scheduler": "normal"}},
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "old.safetensors"}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old positive"}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "old negative"}},
        "8": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ComfyUI"}},
    }
    raw = {
        "positive_prompt": ("6", "text"), "negative_prompt": ("7", "text"),
        "checkpoint": ("4", "ckpt_name"), "seed": ("3", "seed"), "steps": ("3", "steps"),
        "cfg": ("3", "cfg"), "sampler": ("3", "sampler_name"), "scheduler": ("3", "scheduler"),
        "width": ("5", "width"), "height": ("5", "height"), "batch_size": ("5", "batch_size"),
        "filename_prefix": ("8", "filename_prefix"),
    }
    return WorkflowProfile(
        id="anima_base_api_v1",
        display_name="ANIMA Base",
        api_workflow=workflow,
        bindings={key: WorkflowBinding(node_id=node, input=input_name) for key, (node, input_name) in raw.items()},
        workflow_kind="txt2img_basic",
        compatible_model_profiles=["anima_base_v1"],
    )


def remote_profile() -> RemoteProfile:
    return RemoteProfile(
        id="remote-1",
        provider_preset_id="custom",
        display_name="测试云主机",
        ssh_host="example.invalid",
        ssh_user="root",
        known_host_fingerprint="SHA256:test",
        model_aliases={"anima_base_v1": "anima-base.safetensors"},
    )


class FakeTunnel:
    base_url = "http://127.0.0.1:18188"

    def __init__(self, _profile):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def open(self, _credentials):
        return self


class FakeClient:
    def validate_environment(self):
        return None

    def validate_workflow_nodes(self, _workflow):
        return []

    def submit(self, _workflow, _client_id, _requested_prompt_id):
        return "remote-prompt"

    def wait_for_completion(self, _prompt_id, on_state, **_kwargs):
        on_state("running", "运行中")
        return {"outputs": {"8": {"images": [{"filename": "result.png", "type": "output"}]}}}

    def list_output_artifacts(self, _history):
        return [RemoteArtifact(node_id="8", filename="result.png")]

    def download_artifact(self, _artifact):
        return b"generated", "image/png"

    def cancel_pending(self, _prompt_id):
        return None


class BlockingFakeClient(FakeClient):
    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()

    def wait_for_completion(self, prompt_id, on_state, **kwargs):
        self.started.set()
        if not self.release.wait(2):
            raise RuntimeError("test did not release fake generation")
        return super().wait_for_completion(prompt_id, on_state, **kwargs)


def wait_for_state(
    queue: V2GenerationQueueService,
    run_id: str,
    expected: GenerationRunState,
):
    deadline = monotonic() + 2
    while monotonic() < deadline:
        run = queue.get(run_id)
        if run.state == expected:
            return run
        sleep(0.01)
    raise AssertionError(f"run {run_id} did not reach {expected}: {queue.get(run_id).state}")
