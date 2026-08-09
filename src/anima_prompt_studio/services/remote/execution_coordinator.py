from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from anima_prompt_studio.domain.execution_models import (
    GenerationArtifact,
    GenerationRun,
    GenerationRunState,
    RemoteCredentials,
    RemoteProfile,
    WorkflowProfile,
)
from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio.services.remote.comfy_client import ComfyAPIError, ComfyUIClient
from anima_prompt_studio.services.remote.result_organizer import ResultOrganizer
from anima_prompt_studio.services.remote.ssh_tunnel import SshTunnel
from anima_prompt_studio.services.remote.workflow_renderer import WorkflowRenderer


@dataclass
class ExecutionResult:
    run: GenerationRun
    artifacts: list[GenerationArtifact]


class RemoteExecutionError(RuntimeError):
    def __init__(self, message: str, run: GenerationRun) -> None:
        super().__init__(message)
        self.run = run


class RemoteExecutionCoordinator:
    def __init__(
        self,
        *,
        organizer: ResultOrganizer | None = None,
        renderer: WorkflowRenderer | None = None,
        tunnel_factory: Callable[[RemoteProfile], object] = SshTunnel,
        client_factory: Callable[[str], ComfyUIClient] = ComfyUIClient,
        on_update: Callable[[GenerationRun], None] | None = None,
        poll_interval: float = 1.5,
    ) -> None:
        self.organizer = organizer or ResultOrganizer()
        self.renderer = renderer or WorkflowRenderer()
        self.tunnel_factory = tunnel_factory
        self.client_factory = client_factory
        self.on_update = on_update
        self.poll_interval = poll_interval
        self._cancel = threading.Event()
        self._active_client: ComfyUIClient | None = None
        self._active_prompt_id = ""

    def cancel(self) -> None:
        self._cancel.set()

    def execute(
        self,
        job: PromptJob,
        remote_profile: RemoteProfile,
        workflow_profile: WorkflowProfile,
        checkpoint_logical_name: str,
        credentials: RemoteCredentials | None = None,
    ) -> ExecutionResult:
        run = GenerationRun(
            prompt_job_id=job.id,
            remote_profile_id=remote_profile.id,
            workflow_profile_id=workflow_profile.id,
            request_json={"prompt_job": job.model_dump(mode="json")},
        )
        return self._run(job, run, remote_profile, workflow_profile, checkpoint_logical_name, credentials, resume=False)

    def resume(
        self,
        run: GenerationRun,
        remote_profile: RemoteProfile,
        workflow_profile: WorkflowProfile,
        credentials: RemoteCredentials | None = None,
    ) -> ExecutionResult:
        if not run.remote_prompt_id:
            raise RemoteExecutionError("任务尚未提交到 ComfyUI，无法恢复。", run)
        raw_job = run.request_json.get("prompt_job")
        if not isinstance(raw_job, dict):
            raise RemoteExecutionError("任务缺少 PromptJob 快照，无法恢复。", run)
        job = PromptJob.model_validate(raw_job)
        return self._run(job, run, remote_profile, workflow_profile, "", credentials, resume=True)

    def _run(
        self,
        job: PromptJob,
        run: GenerationRun,
        remote_profile: RemoteProfile,
        workflow_profile: WorkflowProfile,
        checkpoint_logical_name: str,
        credentials: RemoteCredentials | None,
        *,
        resume: bool,
    ) -> ExecutionResult:
        self._cancel.clear()
        artifacts: list[GenerationArtifact] = []
        try:
            self._update(run, GenerationRunState.CONNECTING, "正在连接云主机", 0.05)
            tunnel = self.tunnel_factory(remote_profile)
            with tunnel:
                tunnel.open(credentials or RemoteCredentials())
                client = self.client_factory(tunnel.base_url)
                self._active_client = client
                client.validate_environment()

                if not resume:
                    self._update(run, GenerationRunState.PREPARING, "正在准备 ComfyUI 工作流", 0.12)
                    rendered = self.renderer.render(
                        job,
                        workflow_profile,
                        remote_profile,
                        checkpoint_logical_name,
                        run.id,
                    )
                    missing_nodes = client.validate_workflow_nodes(rendered.workflow)
                    if missing_nodes:
                        raise ComfyAPIError(
                            "云端缺少工作流节点：" + ", ".join(missing_nodes),
                            code="missing_nodes",
                        )
                    run.actual_workflow = rendered.workflow
                    run.request_json["resolved_seed"] = rendered.resolved_seed
                    run.request_json["checkpoint_name"] = rendered.checkpoint_name
                    requested_prompt_id = str(uuid4())
                    run.remote_prompt_id = client.submit(rendered.workflow, run.client_id, requested_prompt_id)
                    self._active_prompt_id = run.remote_prompt_id
                    self._update(run, GenerationRunState.QUEUED, "已提交到 ComfyUI 队列", 0.2)
                else:
                    self._active_prompt_id = run.remote_prompt_id
                    self._update(run, GenerationRunState.QUEUED, "正在恢复云端任务", max(run.progress, 0.2))

                history = client.wait_for_completion(
                    run.remote_prompt_id,
                    on_state=lambda state, message: self._remote_state(run, state, message),
                    is_cancelled=self._cancel.is_set,
                    poll_interval=self.poll_interval,
                )
                remote_artifacts = client.list_output_artifacts(history)
                if not remote_artifacts:
                    raise ComfyAPIError("ComfyUI 任务完成，但没有发现图片输出。", code="no_outputs")
                expected_images = job.generation_params.batch_size
                if workflow_profile.workflow_kind == "txt2img_basic" and len(remote_artifacts) < expected_images:
                    raise ComfyAPIError(
                        f"批量任务请求 {expected_images} 张，但 ComfyUI 只返回了 "
                        f"{len(remote_artifacts)} 张；任务不会被误标为完整成功。",
                        code="incomplete_batch",
                    )
                self._update(run, GenerationRunState.DOWNLOADING, "正在下载生成结果", 0.82)
                for index, remote_artifact in enumerate(remote_artifacts, 1):
                    content, mime_type = client.download_artifact(remote_artifact)
                    artifacts.append(
                        self.organizer.save_artifact(job, run, remote_artifact, content, index, mime_type)
                    )
                    self._update(
                        run,
                        GenerationRunState.DOWNLOADING,
                        f"正在下载生成结果 {index}/{len(remote_artifacts)}",
                        0.82 + 0.16 * index / len(remote_artifacts),
                    )
                run.update_state(GenerationRunState.COMPLETED, f"已下载 {len(artifacts)} 个文件", 1.0)
                self.organizer.write_sidecars(job, run, artifacts)
                if self.on_update:
                    self.on_update(run.model_copy(deep=True))
                return ExecutionResult(run=run, artifacts=artifacts)
        except ComfyAPIError as exc:
            if exc.code == "canceled":
                state = GenerationRunState.CANCELED
            elif exc.code == "remote_missing":
                state = GenerationRunState.REMOTE_MISSING
            elif exc.code == "running_cancel_unsupported":
                state = GenerationRunState.RUNNING
            else:
                state = GenerationRunState.FAILED
            run.error_code = exc.code
            run.error_message = str(exc)
            self._update(run, state, str(exc), run.progress)
            raise RemoteExecutionError(str(exc), run) from exc
        except Exception as exc:
            run.error_code = type(exc).__name__
            run.error_message = str(exc)
            self._update(run, GenerationRunState.FAILED, str(exc), run.progress)
            raise RemoteExecutionError(str(exc), run) from exc
        finally:
            self._active_client = None
            self._active_prompt_id = ""

    def _remote_state(self, run: GenerationRun, state: str, message: str) -> None:
        if state == "running":
            self._update(run, GenerationRunState.RUNNING, message, max(run.progress, 0.35))
        elif state == "queued" and run.state != GenerationRunState.RUNNING:
            self._update(run, GenerationRunState.QUEUED, message, max(run.progress, 0.2))

    def _update(
        self,
        run: GenerationRun,
        state: GenerationRunState,
        message: str,
        progress: float,
    ) -> None:
        run.update_state(state, message, progress)
        if self.on_update:
            self.on_update(run.model_copy(deep=True))
