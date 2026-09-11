from __future__ import annotations

from collections import deque
from copy import deepcopy
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Condition, Lock, Thread
from typing import Protocol

from anima_prompt_studio.domain.execution_models import (
    GenerationArtifact,
    GenerationRun,
    GenerationRunState,
    RemoteCredentials,
    RemoteAuthType,
    RemoteProfile,
    SUPPORTED_GENERATION_WORKFLOW_KINDS,
    WorkflowProfile,
)
from anima_prompt_studio_v3.remote.execution_coordinator import (
    ExecutionResult,
    RemoteExecutionCoordinator,
    RemoteExecutionError,
)
from anima_prompt_studio_v3.remote.result_organizer import ResultOrganizer
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
from anima_prompt_studio_v3.remote.credential_store import CredentialStore
from anima_prompt_studio_v3.runtime.workflow_compatibility import infer_workflow_model_profiles
from anima_prompt_studio.domain.models import PromptJob, LoRASelection

from .generation import PreparedGeneration
from ..core.generation_recipes import build_workflow_recipe_contract, validate_job_recipe
from ..core.workflow_compiler import V3WorkflowCompiler
from .workflow_catalog import WorkflowCatalog, catalog
from .packaged_workflows import workflow_revision
from .lora_catalog import LoraCatalog
from ..core.requirements import RequirementLora, digest


class GenerationQueueError(RuntimeError):
    pass


class GenerationQueueFullError(GenerationQueueError):
    pass


class GenerationRunNotFoundError(GenerationQueueError):
    pass


class GenerationRunActionError(GenerationQueueError):
    pass


class EphemeralPassphraseVault:
    """Process-memory-only private-key passphrases, keyed by remote profile."""

    def __init__(self) -> None:
        self._values: dict[str, bytearray] = {}
        self._lock = Lock()

    def set(self, remote_profile_id: str, passphrase: str) -> None:
        if not remote_profile_id.strip():
            raise ValueError("云主机配置 ID 不能为空。")
        encoded = bytearray(passphrase.encode("utf-8"))
        with self._lock:
            previous = self._values.pop(remote_profile_id, None)
            if previous is not None:
                previous[:] = b"\x00" * len(previous)
            if encoded:
                self._values[remote_profile_id] = encoded

    def get(self, remote_profile_id: str) -> str:
        with self._lock:
            value = self._values.get(remote_profile_id)
            return bytes(value).decode("utf-8") if value is not None else ""

    def has(self, remote_profile_id: str) -> bool:
        with self._lock:
            return bool(self._values.get(remote_profile_id))

    def clear(self) -> None:
        with self._lock:
            for value in self._values.values():
                value[:] = b"\x00" * len(value)
            self._values.clear()


@dataclass(frozen=True)
class GenerationTarget:
    remote_profile: RemoteProfile
    workflow_profile: WorkflowProfile
    credentials: RemoteCredentials
    output_root: Path


class GenerationTargetResolver(Protocol):
    def __call__(self, remote_profile_id: str, workflow_profile_id: str) -> GenerationTarget: ...


class CoordinatorFactory(Protocol):
    def __call__(
        self,
        output_root: Path,
        on_update: Callable[[GenerationRun], None],
    ) -> RemoteExecutionCoordinator: ...


class GenerationTargetLister(Protocol):
    def __call__(self) -> list[dict[str, object]]: ...


@dataclass(frozen=True)
class _QueuedGeneration:
    prepared: PreparedGeneration | None
    target: GenerationTarget
    run_id: str


class GenerationQueueService:
    """Single-worker, UI-independent queue around the V3 execution coordinator."""

    def __init__(
        self,
        target_resolver: GenerationTargetResolver,
        *,
        coordinator_factory: CoordinatorFactory | None = None,
        on_run_saved: Callable[[GenerationRun], None] | None = None,
        on_artifact_saved: Callable[[GenerationArtifact], None] | None = None,
        on_job_saved: Callable[[PromptJob], None] | None = None,
        max_pending: int = 20,
        existing_runs: list[GenerationRun] | None = None,
        existing_artifacts: dict[str, list[GenerationArtifact]] | None = None,
        target_lister: GenerationTargetLister | None = None,
        passphrase_vault: EphemeralPassphraseVault | None = None,
        recovery_resolver: Callable[[GenerationRun], GenerationTarget] | None = None,
        plan_resolver=None,
        durable_run_loader=None,
    ) -> None:
        if max_pending < 1:
            raise ValueError("max_pending 必须至少为 1。")
        self._target_resolver = target_resolver
        self._target_lister = target_lister
        self._passphrase_vault = passphrase_vault
        self._recovery_resolver = recovery_resolver
        self._plan_resolver = plan_resolver
        self._durable_run_loader = durable_run_loader
        self._reserved: set[str] = set()
        self.on_durable_cancel = None
        self._coordinator_factory = coordinator_factory or self._default_coordinator
        self._on_run_saved = on_run_saved
        self._on_artifact_saved = on_artifact_saved
        self._on_job_saved = on_job_saved
        self._max_pending = max_pending
        self._condition = Condition()
        self._pending: deque[_QueuedGeneration] = deque()
        self._runs = {run.id: run.model_copy(deep=True) for run in (existing_runs or [])}
        self._artifacts = {
            run_id: [item.model_copy(deep=True) for item in items]
            for run_id, items in (existing_artifacts or {}).items()
        }
        for run_id in self._runs:
            self._artifacts.setdefault(run_id, [])
        self._idempotency: dict[str, str] = {}
        for run in self._runs.values():
            local_queue = run.request_json.get("local_queue", {})
            key = local_queue.get("idempotency_key") if isinstance(local_queue, dict) else None
            if isinstance(key, str) and key:
                self._idempotency[key] = run.id
        self._active_run_id: str | None = None
        self._active_coordinator: RemoteExecutionCoordinator | None = None
        self._scheduled_run_ids: set[str] = set()
        self._stopping = False
        self._worker = Thread(target=self._work_loop, name="anima-v3-generation-queue", daemon=True)
        self._worker.start()

    @staticmethod
    def _default_coordinator(
        output_root: Path,
        on_update: Callable[[GenerationRun], None],
    ) -> RemoteExecutionCoordinator:
        return RemoteExecutionCoordinator(
            renderer=V3WorkflowCompiler(),
            organizer=ResultOrganizer(output_root),
            on_update=on_update,
        )

    def submit(
        self,
        prepared: PreparedGeneration,
        *,
        remote_profile_id: str,
        workflow_profile_id: str,
        idempotency_key: str,
        payload_hash: str | None = None,
    ) -> GenerationRun:
        if not idempotency_key.strip():
            raise ValueError("缺少 Idempotency-Key。")
        with self._condition:
            existing_id = self._idempotency.get(idempotency_key)
            if existing_id is not None:
                self._check_payload(self._runs[existing_id], payload_hash)
                return self._runs[existing_id].model_copy(deep=True)
            if self._stopping:
                raise GenerationQueueError("生成队列正在停止。")
            capacity = self._max_pending if self._active_run_id is not None else self._max_pending + 1
            if len(self._pending) + len(self._reserved) >= capacity:
                raise GenerationQueueFullError(f"文生图等待队列已达到 {self._max_pending} 项。")

        target = self._target_resolver(remote_profile_id, workflow_profile_id)
        self._validate_target(prepared, target)
        job = prepared.job.model_copy(deep=True)
        target_snapshot = GenerationTarget(
            remote_profile=target.remote_profile.model_copy(deep=True),
            workflow_profile=target.workflow_profile.model_copy(deep=True),
            credentials=target.credentials.model_copy(deep=True),
            output_root=Path(target.output_root).expanduser().resolve(),
        )
        run = GenerationRun(
            prompt_job_id=job.id,
            remote_profile_id=target_snapshot.remote_profile.id,
            workflow_profile_id=target_snapshot.workflow_profile.id,
            status_message="等待本地生成队列",
            request_json={
                "prompt_job": job.model_dump(mode="json"),
                "local_queue": {"idempotency_key": idempotency_key, "payload_hash": payload_hash},
                "workflow_snapshot": target_snapshot.workflow_profile.model_dump(mode="json"),
                "workflow_revision": workflow_revision(target_snapshot.workflow_profile),
            },
        )
        request = _QueuedGeneration(
            prepared=PreparedGeneration(job=job, checkpoint_logical_name=prepared.checkpoint_logical_name),
            target=target_snapshot,
            run_id=run.id,
        )
        with self._condition:
            # A second submission may have completed target resolution concurrently.
            existing_id = self._idempotency.get(idempotency_key)
            if existing_id is not None:
                self._check_payload(self._runs[existing_id], payload_hash)
                return self._runs[existing_id].model_copy(deep=True)
            if self._stopping:
                raise GenerationQueueError("生成队列正在停止。")
            capacity = self._max_pending if self._active_run_id is not None else self._max_pending + 1
            if len(self._pending) + len(self._reserved) >= capacity:
                raise GenerationQueueFullError(f"文生图等待队列已达到 {self._max_pending} 项。")
            self._runs[run.id] = run
            self._artifacts[run.id] = []
            self._idempotency[idempotency_key] = run.id
            self._pending.append(request)
            self._scheduled_run_ids.add(run.id)
            if self._on_job_saved:
                self._on_job_saved(job.model_copy(deep=True))
            self._save_run(run)
            self._condition.notify()
            return run.model_copy(deep=True)

    @staticmethod
    def _check_payload(run, payload_hash):
        from ..storage.generation_submissions import IdempotencyConflict
        old_hash = run.request_json.get("local_queue", {}).get("payload_hash")
        if payload_hash is not None and old_hash is not None and old_hash != payload_hash:
            raise IdempotencyConflict("同一幂等键不能用于不同请求。")

    def plan(self, prepared, remote_id, workflow_id, resources, frozen=None):
        if self._plan_resolver is None:
            raise GenerationQueueError("当前队列尚未配置资源快照解析器。")
        return self._plan_resolver(deepcopy(prepared), remote_id, workflow_id, deepcopy(resources), deepcopy(frozen))

    def existing_request(self, key, payload_hash=None):
        with self._condition:
            run_id = self._idempotency.get(key)
            if run_id is None:
                return None
            run = self._runs[run_id]
            self._check_payload(run, payload_hash)
            return run.model_copy(deep=True)

    def is_reserved(self, run_id):
        with self._condition:
            return run_id in self._reserved

    def reserved_ids(self):
        with self._condition:
            return list(self._reserved)

    def accept_durable(self, key, payload_hash, builder):
        from ..storage.generation_submissions import IdempotencyConflict
        with self._condition:
            if key in self._idempotency:
                raise IdempotencyConflict("该幂等键已有任务，请查询原提交。")
            if self._stopping:
                raise GenerationQueueError("生成队列正在停止。")
            capacity = self._max_pending if self._active_run_id else self._max_pending + 1
            if len(self._pending) + len(self._reserved) >= capacity:
                raise GenerationQueueFullError("生成队列已满，未接受新任务。")
            entry = builder()  # Short workspace transaction; no network IO.
            self._register_durable(entry)
            return entry

    def _register_durable(self, entry):
        run_id = entry["run_id"]
        if run_id not in self._runs:
            existing = self._durable_run_loader(run_id) if self._durable_run_loader else None
            run = existing or GenerationRun.model_validate(entry["snapshot"]["run"])
            if existing is None and entry["dispatch_state"] == "enqueued":
                run.error_code = "generation_execution_uncertain"
                run.update_state(GenerationRunState.FAILED, "执行记录缺失，请确认远端状态。", 0)
            self._runs[run_id] = run
        run = self._runs[run_id]
        self._idempotency[entry["idempotency_key"]] = run_id
        self._artifacts.setdefault(run_id, [])
        if entry["dispatch_state"] == "canceled":
            run.update_state(GenerationRunState.CANCELED, "已取消", 0)
        elif entry["dispatch_state"] == "failed" and run.state == GenerationRunState.DRAFT:
            run.error_code = entry["error_code"]
            run.update_state(GenerationRunState.FAILED, "已接受的任务执行准备失败。", 0)
        if run.state == GenerationRunState.DRAFT and not run.request_json.get("dispatch_started") and not run.remote_prompt_id:
            self._reserved.add(run_id)
        elif run.state not in {GenerationRunState.COMPLETED, GenerationRunState.CANCELED, GenerationRunState.FAILED} and not run.remote_prompt_id:
            run.error_code = "generation_execution_uncertain"
            run.update_state(GenerationRunState.FAILED, "执行结果待确认；不会自动重复出图。", run.progress)
            self._save_run(run)

    def restore_durable(self, entry):
        with self._condition:
            self._register_durable(entry)

    def deliver_durable(self, entry, prepared, target):
        with self._condition:
            run_id = entry["run_id"]
            if self._stopping or run_id not in self._reserved:
                return False
            run = self._runs[run_id]
            # Persist before publishing any executable work. A crash here is safe
            # to retry: dispatch_started is still false and run_id is stable.
            run.request_json["generation_snapshot"] = entry["snapshot"]["provenance"]
            run.request_json["resource_snapshot"] = {key: entry["snapshot"][key] for key in
                                                      ("resources", "resolution", "remote_fingerprint", "workflow")}
            if self._on_job_saved:
                self._on_job_saved(prepared.job.model_copy(deep=True))
            self._save_run(run)
            self._reserved.remove(run_id)
            self._scheduled_run_ids.add(run_id)
            self._pending.append(_QueuedGeneration(prepared=prepared, target=target, run_id=run_id))
            self._condition.notify_all()
            return True

    def fail_durable(self, entry, code):
        with self._condition:
            run = self._runs[entry["run_id"]]
            if run.id not in self._reserved:
                return
            run.error_code = code
            run.error_message = "已接受的任务暂不可执行，请检查资源或连接；未重复提交远端。"
            run.update_state(GenerationRunState.FAILED, run.error_message, 0)
            self._save_run(run)
            self._reserved.discard(run.id)

    def list(self, *, limit: int = 100) -> list[GenerationRun]:
        if limit < 1:
            return []
        with self._condition:
            ordered = sorted(self._runs.values(), key=lambda item: item.updated_at, reverse=True)
            return [item.model_copy(deep=True) for item in ordered[:limit]]

    def targets(self) -> list[dict[str, object]]:
        if self._target_lister is None:
            return []
        return self._target_lister()

    def set_private_key_passphrase(self, remote_profile_id: str, passphrase: str) -> None:
        if self._passphrase_vault is None:
            raise GenerationQueueError("当前生成队列不支持私钥口令输入。")
        self._passphrase_vault.set(remote_profile_id, passphrase)

    def resume(self, run_id: str) -> GenerationRun:
        with self._condition:
            if self._stopping:
                raise GenerationQueueError("生成队列正在停止。")
            run = self._runs.get(run_id)
            if run is None:
                raise GenerationRunNotFoundError(run_id)
            if run_id in self._scheduled_run_ids or self._active_run_id == run_id:
                raise GenerationRunActionError("任务已在本地执行或恢复队列中。")
            if not run.remote_prompt_id:
                raise GenerationRunActionError("任务尚未提交到 ComfyUI，无法恢复。")
            if run.state in {GenerationRunState.COMPLETED, GenerationRunState.CANCELED}:
                raise GenerationRunActionError("已完成或已取消的任务无需恢复。")
            capacity = self._max_pending if self._active_run_id is not None else self._max_pending + 1
            if len(self._pending) + len(self._reserved) >= capacity:
                raise GenerationQueueFullError(f"文生图等待队列已达到 {self._max_pending} 项。")
            remote_profile_id = run.remote_profile_id
            workflow_profile_id = run.workflow_profile_id

        target = self._recovery_resolver(run) if self._recovery_resolver else self._target_resolver(remote_profile_id, workflow_profile_id)
        self._validate_remote_target(target)
        target_snapshot = GenerationTarget(
            remote_profile=target.remote_profile.model_copy(deep=True),
            workflow_profile=target.workflow_profile.model_copy(deep=True),
            credentials=target.credentials.model_copy(deep=True),
            output_root=Path(target.output_root).expanduser().resolve(),
        )
        with self._condition:
            if run_id in self._scheduled_run_ids or self._active_run_id == run_id:
                raise GenerationRunActionError("任务已在本地执行或恢复队列中。")
            if self._stopping:
                raise GenerationQueueError("生成队列正在停止。")
            capacity = self._max_pending if self._active_run_id is not None else self._max_pending + 1
            if len(self._pending) + len(self._reserved) >= capacity:
                raise GenerationQueueFullError(f"文生图等待队列已达到 {self._max_pending} 项。")
            run = self._runs[run_id]
            run.update_state(run.state, "等待恢复远程任务", run.progress)
            self._pending.append(_QueuedGeneration(prepared=None, target=target_snapshot, run_id=run_id))
            self._scheduled_run_ids.add(run_id)
            self._save_run(run)
            self._condition.notify()
            return run.model_copy(deep=True)

    def get(self, run_id: str) -> GenerationRun:
        with self._condition:
            try:
                return self._runs[run_id].model_copy(deep=True)
            except KeyError as exc:
                raise GenerationRunNotFoundError(run_id) from exc

    def artifacts(self, run_id: str) -> list[GenerationArtifact]:
        with self._condition:
            if run_id not in self._runs:
                raise GenerationRunNotFoundError(run_id)
            return [item.model_copy(deep=True) for item in self._artifacts[run_id]]

    def available_actions(self, run_id: str) -> list[str]:
        with self._condition:
            run = self._runs.get(run_id)
            if run is None:
                raise GenerationRunNotFoundError(run_id)
            if run_id in self._reserved:
                return ["cancel_queued"]
            if run_id in self._scheduled_run_ids:
                if run.state == GenerationRunState.DRAFT and self._active_run_id != run_id:
                    return ["cancel_queued"]
                return []
            if run.remote_prompt_id and run.state not in {
                GenerationRunState.COMPLETED,
                GenerationRunState.CANCELED,
            }:
                return ["continue_download"] if run.state == GenerationRunState.DOWNLOADING else ["retry_check"]
            return []

    def cancel_queued(self, run_id: str) -> GenerationRun:
        with self._condition:
            run = self._runs.get(run_id)
            if run is None:
                raise GenerationRunNotFoundError(run_id)
            if self._active_run_id == run_id or run.state != GenerationRunState.DRAFT:
                raise GenerationRunActionError("只能取消尚未开始的排队任务。")
            if run_id in self._reserved:
                if self.on_durable_cancel:
                    self.on_durable_cancel(run.request_json["submission_id"])
                self._reserved.remove(run_id)
                run.update_state(GenerationRunState.CANCELED, "已在交付队列前取消", 0)
                self._save_run(run)
                return run.model_copy(deep=True)
            match = next((item for item in self._pending if item.run_id == run_id), None)
            if match is None:
                raise GenerationRunActionError("任务已不在等待队列。")
            self._pending.remove(match)
            self._scheduled_run_ids.discard(run_id)
            run.update_state(GenerationRunState.CANCELED, "已在提交远程前取消", 0.0)
            self._save_run(run)
            return run.model_copy(deep=True)

    def shutdown(self, *, cancel_active: bool = False, timeout: float = 5.0) -> None:
        with self._condition:
            self._stopping = True
            while self._pending:
                request = self._pending.popleft()
                run = self._runs[request.run_id]
                self._scheduled_run_ids.discard(request.run_id)
                if request.prepared is None:
                    run.update_state(run.state, "恢复尚未开始，本地服务已停止", run.progress)
                elif run.request_json.get("submission_id"):
                    run.update_state(GenerationRunState.DRAFT, "服务已停止，等待下次恢复", 0.0)
                else:
                    run.update_state(GenerationRunState.CANCELED, "本地服务已停止", 0.0)
                self._save_run(run)
            if cancel_active and self._active_coordinator is not None:
                self._active_coordinator.cancel()
            self._condition.notify_all()
        if self._passphrase_vault is not None:
            self._passphrase_vault.clear()
        self._worker.join(timeout=max(0.0, timeout))
        if self._worker.is_alive():
            raise RuntimeError("生成队列未能在超时前安全停止。")

    def _work_loop(self) -> None:
        while True:
            with self._condition:
                while not self._pending and not self._stopping:
                    self._condition.wait()
                if self._stopping and not self._pending:
                    return
                request = self._pending.popleft()
                self._active_run_id = request.run_id
                run = self._runs[request.run_id].model_copy(deep=True)
            try:
                target = request.target
                if request.prepared is not None and run.request_json.get("submission_id"):
                    frozen = run.request_json["resource_snapshot"]
                    _, target, resolution = self.plan(request.prepared, run.remote_profile_id,
                        run.workflow_profile_id, [RequirementLora.model_validate(r) for r in frozen["resources"]],
                        frozen["workflow"])
                    if (resolution["remote_fingerprint"] != frozen["remote_fingerprint"]
                            or resolution["bindings"] != frozen["resolution"]["bindings"]
                            or digest(target.workflow_profile.model_dump(mode="json")) != digest(frozen["workflow"])):
                        raise ValueError("已接受任务的目标或资源发生变化，请重新确认。")
                coordinator = self._coordinator_factory(target.output_root, self._record_update)
                with self._condition:
                    self._active_coordinator = coordinator
                if request.prepared is not None and run.request_json.get("submission_id"):
                    # Durable marker precedes any remote operation. A crash after
                    # this point is uncertainty, never permission to sample again.
                    run.request_json["dispatch_started"] = True
                    self._record_update(run)
                if request.prepared is None:
                    result = coordinator.resume(
                        run,
                        target.remote_profile,
                        target.workflow_profile,
                        target.credentials,
                    )
                else:
                    result = coordinator.execute(
                        request.prepared.job,
                        target.remote_profile,
                        target.workflow_profile,
                        request.prepared.checkpoint_logical_name,
                        target.credentials,
                        run=run,
                    )
                self._record_result(result)
            except RemoteExecutionError as exc:
                if (exc.run.request_json.get("submission_attempted") and not exc.run.remote_prompt_id):
                    exc.run.error_code = "generation_execution_uncertain"
                    exc.run.error_message = "执行结果待确认；不会自动重复出图，请检查远端队列。"
                    exc.run.update_state(GenerationRunState.FAILED, exc.run.error_message, exc.run.progress)
                self._record_update(exc.run)
            except Exception as exc:
                run.error_code = type(exc).__name__
                run.error_message = "任务执行失败，请检查资源和连接。" if run.request_json.get("submission_id") else str(exc)
                run.update_state(GenerationRunState.FAILED, run.error_message, run.progress)
                self._record_update(run)
            finally:
                with self._condition:
                    self._active_run_id = None
                    self._active_coordinator = None
                    self._scheduled_run_ids.discard(request.run_id)
                    self._condition.notify_all()

    def _record_update(self, run: GenerationRun) -> None:
        # The coordinator emits COMPLETED before returning its artifact list.
        # Publish completion only after artifacts have been persisted together.
        if run.state == GenerationRunState.COMPLETED:
            return
        snapshot = run.model_copy(deep=True)
        with self._condition:
            self._runs[run.id] = snapshot
            self._save_run(snapshot)

    def _record_result(self, result: ExecutionResult) -> None:
        with self._condition:
            if self._on_artifact_saved:
                for artifact in result.artifacts:
                    self._on_artifact_saved(artifact.model_copy(deep=True))
            self._save_run(result.run)
            self._artifacts[result.run.id] = [item.model_copy(deep=True) for item in result.artifacts]
            self._runs[result.run.id] = result.run.model_copy(deep=True)

    def _save_run(self, run: GenerationRun) -> None:
        if self._on_run_saved:
            self._on_run_saved(run.model_copy(deep=True))

    @staticmethod
    def _validate_target(prepared: PreparedGeneration, target: GenerationTarget) -> None:
        GenerationQueueService._validate_remote_target(target)
        workflow = target.workflow_profile
        compatible = _compatible_models(workflow)
        if not compatible:
            raise ValueError("工作流尚未声明兼容模型，不能安全提交。")
        from ..core.model_versions import model_matches_workflow
        if not model_matches_workflow(prepared.job.model_profile_id, workflow):
            raise ValueError("工作流与当前模型配置不兼容。")
        validate_job_recipe(prepared.job, workflow)

    @staticmethod
    def _validate_remote_target(target: GenerationTarget) -> None:
        profile = target.remote_profile
        workflow = target.workflow_profile
        if not profile.enabled:
            raise ValueError("所选云主机配置已停用。")
        if not profile.connection_ready:
            raise ValueError("请先在设置中测试连接并确认 SSH 主机指纹。")
        if workflow.workflow_kind not in SUPPORTED_GENERATION_WORKFLOW_KINDS:
            raise ValueError("当前工作流不在受支持的执行范围内。")


def build_generation_queue(
    v2_database: Path,
    *,
    credential_store: CredentialStore | None = None,
    coordinator_factory: CoordinatorFactory | None = None,
    max_pending: int = 20,
) -> GenerationQueueService:
    """Build the V3 queue from schema-compatible profiles and secure credentials."""

    database = Path(v2_database).expanduser().resolve()
    workflows_manager = WorkflowCatalog(database)
    secrets = credential_store or CredentialStore()
    passphrases = EphemeralPassphraseVault()
    repository = SQLiteRepository(database)
    try:
        existing_runs = repository.list_generation_runs(limit=10_000)
        existing_artifacts = {
            run.id: repository.list_generation_artifacts(run.id)
            for run in existing_runs
        }
    finally:
        repository.close()

    def target_resolver(remote_profile_id: str, workflow_profile_id: str, frozen=None) -> GenerationTarget:
        repository = SQLiteRepository(database)
        try:
            profile = repository.get_remote_profile(remote_profile_id)
            output_root = Path(repository.get_setting(
                "generation_output_root",
                str(Path.home() / "Pictures" / "AnimaPromptStudio"),
            ))
        finally:
            repository.close()
        password = secrets.read_password(profile.id) if profile.connection_type == "ssh" and profile.auth_type == RemoteAuthType.PASSWORD else ""
        if profile.connection_type == "ssh" and profile.auth_type == RemoteAuthType.PASSWORD and not password:
            raise ValueError("当前云主机没有可用的安全存储密码。")
        passphrase = passphrases.get(profile.id) if profile.auth_type == RemoteAuthType.PRIVATE_KEY else ""
        credentials = RemoteCredentials(password=password, passphrase=passphrase)
        workflow = WorkflowProfile.model_validate(frozen) if frozen else workflows_manager.resolve_for_submission(remote_profile_id, workflow_profile_id, credentials)
        if workflows_manager.remote(remote_profile_id) != profile:
            raise ValueError("检测期间连接配置已更改，请重新提交。")
        return GenerationTarget(
            remote_profile=profile,
            workflow_profile=workflow,
            credentials=credentials,
            output_root=output_root,
        )

    def target_lister() -> list[dict[str, object]]:
        repository = SQLiteRepository(database)
        try:
            profiles = repository.list_remote_profiles(enabled_only=True)
            workflows = [p for p, _ in catalog(database)]
        finally:
            repository.close()
        reports = {profile.id: {i["workflow_id"]: i for i in workflows_manager.report(profile.id)["items"]} for profile in profiles}
        return [
            {
                "remote_profile_id": profile.id,
                "remote_display_name": profile.display_name,
                "connection_type": profile.connection_type,
                "remote_ssh_host": profile.ssh_host,
                "remote_ssh_port": profile.ssh_port,
                "workflow_profile_id": workflow.id,
                "workflow_display_name": workflow.display_name,
                "workflow_kind": workflow.workflow_kind,
                "workflow_notes": workflow.notes,
                "compatible_model_profiles": reports[profile.id][workflow.id]["model_profiles"],
                "host_fingerprint_ready": profile.connection_ready,
                "auth_type": profile.auth_type.value,
                "private_key_passphrase_configured": passphrases.has(profile.id),
                "availability": reports[profile.id][workflow.id]["state"],
                "availability_errors": reports[profile.id][workflow.id]["errors"],
                "experimental": reports[profile.id][workflow.id]["experimental"],
                "template_revision": reports[profile.id][workflow.id]["revision"],
                **build_workflow_recipe_contract(workflow),
            }
            for profile in profiles
            for workflow in workflows
            if workflow.workflow_kind in SUPPORTED_GENERATION_WORKFLOW_KINDS
            and _compatible_models(workflow)
        ]

    def with_repository(callback):
        def save(value) -> None:
            repository = SQLiteRepository(database)
            try:
                callback(repository, value)
            finally:
                repository.close()
        return save

    def save_run(repository, run):
        repository.save_generation_run(run)
        if run.error_code in {"missing_nodes", "invalid_workflow_inputs"}:
            workflows_manager.invalidate(run.remote_profile_id)

    def plan_resolver(prepared, remote_id, workflow_id, resources, frozen):
        # Obtain credentials without resolving a different graph first.
        base = frozen if frozen is not None else LoraCatalog(workflows_manager).profile(workflow_id).model_dump(mode="json")
        target = target_resolver(remote_id, workflow_id, base)
        graph, resolution = LoraCatalog(workflows_manager).resolve(remote_id, workflow_id,
            prepared.job.model_profile_id, resources, frozen=frozen, credentials=target.credentials, refresh=True)
        job = prepared.job.model_copy(deep=True)
        job.lora_selection = [LoRASelection(logical_id=b["logical_id"], file_name=b["remote_file_name"], weight=b["weight"], trigger_words=b["trigger_words"])
                              for b in resolution["bindings"]]
        job.integration_metadata["resolved_lora_bindings"] = resolution["bindings"]
        planned = PreparedGeneration(job=job, checkpoint_logical_name=prepared.checkpoint_logical_name)
        resolved = GenerationTarget(target.remote_profile, graph, target.credentials, target.output_root)
        GenerationQueueService._validate_target(planned, resolved)
        return planned, resolved, resolution

    def load_durable_run(run_id):
        repository = SQLiteRepository(database)
        try:
            return repository.get_generation_run(run_id)
        except KeyError:
            return None
        finally:
            repository.close()

    return GenerationQueueService(
        target_resolver,
        on_job_saved=with_repository(lambda repository, job: repository.save_job(job)),
        on_run_saved=with_repository(save_run),
        on_artifact_saved=with_repository(
            lambda repository, artifact: repository.save_generation_artifact(artifact)
        ),
        coordinator_factory=coordinator_factory,
        max_pending=max_pending,
        existing_runs=existing_runs,
        existing_artifacts=existing_artifacts,
        target_lister=target_lister,
        passphrase_vault=passphrases,
        recovery_resolver=lambda run: target_resolver(run.remote_profile_id, run.workflow_profile_id, run.request_json.get("workflow_snapshot")),
        plan_resolver=plan_resolver,
        durable_run_loader=load_durable_run,
    )


def _compatible_models(workflow: WorkflowProfile) -> list[str]:
    from ..core.model_versions import workflow_models
    return workflow_models(workflow) if workflow.compatible_model_profiles else infer_workflow_model_profiles(
        workflow.api_workflow,
        workflow.source_path or workflow.display_name or workflow.id,
    )

# Compatibility names for existing callers; implementation belongs to V3.
V2GenerationQueueService = GenerationQueueService
V2GenerationTarget = GenerationTarget
build_v2_generation_queue = build_generation_queue
