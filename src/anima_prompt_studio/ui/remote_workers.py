from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from anima_prompt_studio.domain.execution_models import (
    GenerationRun,
    RemoteCredentials,
    RemoteProfile,
    WorkflowProfile,
)
from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio.services.remote.comfy_client import ComfyUIClient
from anima_prompt_studio.services.remote.execution_coordinator import RemoteExecutionCoordinator, RemoteExecutionError
from anima_prompt_studio.services.remote.result_organizer import ResultOrganizer
from anima_prompt_studio.services.remote.ssh_tunnel import HostKeyMismatchError, SshTunnel
from anima_prompt_studio.services.remote.workflow_discovery import discover_compshare_workflows


class ConnectionTestWorker(QObject):
    fingerprint_required = Signal(object, str)
    succeeded = Signal(object, object)
    failed = Signal(str)
    done = Signal()

    def __init__(self, profile: RemoteProfile, credentials: RemoteCredentials) -> None:
        super().__init__()
        self.profile = profile
        self.credentials = credentials

    @Slot()
    def run(self) -> None:
        tunnel = SshTunnel(self.profile)
        try:
            fingerprint = tunnel.probe_fingerprint()
            if not self.profile.known_host_fingerprint:
                self.fingerprint_required.emit(self.profile, fingerprint)
                return
            if fingerprint != self.profile.known_host_fingerprint:
                raise HostKeyMismatchError(
                    f"SSH 主机指纹不匹配。已保存 {self.profile.known_host_fingerprint}，当前 {fingerprint}。"
                )
            with tunnel:
                tunnel.open(self.credentials)
                report = ComfyUIClient(tunnel.base_url).validate_environment()
                discovered = []
                if self.profile.provider_preset_id == "compshare_container":
                    discovered = discover_compshare_workflows(tunnel)
                self.succeeded.emit(report, discovered)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            tunnel.close()
            self.done.emit()


class GenerationWorker(QObject):
    updated = Signal(object)
    succeeded = Signal(object, object)
    failed = Signal(object, str)
    done = Signal()

    def __init__(
        self,
        *,
        job: PromptJob | None,
        run: GenerationRun | None,
        profile: RemoteProfile,
        workflow_profile: WorkflowProfile,
        checkpoint_logical_name: str,
        credentials: RemoteCredentials,
        output_root: Path,
    ) -> None:
        super().__init__()
        self.job = job
        self.existing_run = run
        self.profile = profile
        self.workflow_profile = workflow_profile
        self.checkpoint_logical_name = checkpoint_logical_name
        self.credentials = credentials
        self.coordinator = RemoteExecutionCoordinator(
            organizer=ResultOrganizer(output_root),
            on_update=self.updated.emit,
        )

    @Slot()
    def run(self) -> None:
        try:
            if self.existing_run is not None:
                result = self.coordinator.resume(
                    self.existing_run,
                    self.profile,
                    self.workflow_profile,
                    self.credentials,
                )
            else:
                if self.job is None:
                    raise ValueError("缺少待生成的 PromptJob。")
                result = self.coordinator.execute(
                    self.job,
                    self.profile,
                    self.workflow_profile,
                    self.checkpoint_logical_name,
                    self.credentials,
                )
            self.succeeded.emit(result.run, result.artifacts)
        except RemoteExecutionError as exc:
            self.failed.emit(exc.run, str(exc))
        except Exception as exc:
            fallback = self.existing_run or GenerationRun(
                prompt_job_id=self.job.id if self.job else "",
                remote_profile_id=self.profile.id,
                workflow_profile_id=self.workflow_profile.id,
            )
            self.failed.emit(fallback, str(exc))
        finally:
            self.done.emit()

    @Slot()
    def cancel(self) -> None:
        self.coordinator.cancel()
