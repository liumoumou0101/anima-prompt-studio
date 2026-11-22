from __future__ import annotations

from pathlib import Path
from threading import Event, Thread

from anima_prompt_studio.domain.execution_models import GenerationRun, GenerationRunState, RemoteCredentials
from anima_prompt_studio_v3.adapters.v2 import (
    CandidateToV2PromptJobAdapter,
    V2GenerationQueueService,
    V2GenerationSettings,
    V2GenerationTarget,
)
from anima_prompt_studio_v3.runtime.generation_queue import GenerationQueueError

from test_v2_generation_adapter import remote_profile, sample_candidate, sample_intent, workflow_profile


def _blocked_old_target(tmp_path: Path, captured: Event, release: Event):
    old = V2GenerationTarget(
        remote_profile=remote_profile(),
        workflow_profile=workflow_profile(),
        credentials=RemoteCredentials(),
        output_root=tmp_path,
    )

    def resolve(*_args):
        captured.set()
        assert release.wait(timeout=2)
        return old

    return resolve


def test_submit_does_not_publish_old_target_after_profile_deletion(tmp_path: Path) -> None:
    captured, release = Event(), Event()
    queue = V2GenerationQueueService(_blocked_old_target(tmp_path, captured, release))
    prepared = CandidateToV2PromptJobAdapter().prepare(
        sample_candidate(),
        sample_intent(),
        settings=V2GenerationSettings(seed=42),
    )
    errors: list[Exception] = []

    def submit() -> None:
        try:
            queue.submit(
                prepared,
                remote_profile_id="remote-1",
                workflow_profile_id="anima_base_api_v1",
                idempotency_key="delete-race-submit",
            )
        except Exception as exc:
            errors.append(exc)

    thread = Thread(target=submit)
    thread.start()
    try:
        assert captured.wait(timeout=2)
        queue.with_profile_deletion("remote-1", lambda: None)
        release.set()
        thread.join(timeout=2)

        assert not thread.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], GenerationQueueError)
        assert queue.list() == []
    finally:
        release.set()
        thread.join(timeout=2)
        queue.shutdown()


def test_resume_does_not_publish_old_target_after_profile_deletion(tmp_path: Path) -> None:
    captured, release = Event(), Event()
    existing = GenerationRun(
        prompt_job_id="job-existing",
        remote_profile_id="remote-1",
        workflow_profile_id="anima_base_api_v1",
        remote_prompt_id="remote-prompt",
        state=GenerationRunState.FAILED,
    )
    queue = V2GenerationQueueService(
        lambda *_args: None,
        recovery_resolver=_blocked_old_target(tmp_path, captured, release),
        existing_runs=[existing],
    )
    errors: list[Exception] = []

    def resume() -> None:
        try:
            queue.resume(existing.id)
        except Exception as exc:
            errors.append(exc)

    thread = Thread(target=resume)
    thread.start()
    try:
        assert captured.wait(timeout=2)
        queue.with_profile_deletion("remote-1", lambda: None)
        release.set()
        thread.join(timeout=2)

        assert not thread.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], GenerationQueueError)
        assert queue.get(existing.id).state == GenerationRunState.FAILED
        assert queue.available_actions(existing.id) == ["retry_check"]
    finally:
        release.set()
        thread.join(timeout=2)
        queue.shutdown()
