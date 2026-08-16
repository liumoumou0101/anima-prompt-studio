from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from anima_prompt_studio.domain.models import utc_now


HIRES_FIX_WORKFLOW_KIND = "txt2img_hiresfix_1_5x"
SUPPORTED_GENERATION_WORKFLOW_KINDS = frozenset({"txt2img_basic", HIRES_FIX_WORKFLOW_KIND})


class RemoteAuthType(StrEnum):
    PRIVATE_KEY = "private_key"
    PASSWORD = "password"
    AGENT = "agent"


class GenerationRunState(StrEnum):
    DRAFT = "draft"
    CONNECTING = "connecting"
    PREPARING = "preparing"
    QUEUED = "queued"
    RUNNING = "running"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    REMOTE_MISSING = "remote_missing"


ACTIVE_RUN_STATES = {
    GenerationRunState.CONNECTING,
    GenerationRunState.PREPARING,
    GenerationRunState.QUEUED,
    GenerationRunState.RUNNING,
    GenerationRunState.DOWNLOADING,
}


class RemoteProfile(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    provider_preset_id: str = "compshare_container"
    display_name: str = "云端 ComfyUI"
    ssh_host: str
    ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_user: str
    auth_type: RemoteAuthType = RemoteAuthType.PRIVATE_KEY
    private_key_path: str = ""
    known_host_fingerprint: str = ""
    comfy_host: str = "127.0.0.1"
    comfy_port: int = Field(default=8188, ge=1, le=65535)
    startup_mode: Literal["manual", "systemd", "command"] = "manual"
    startup_command: str = ""
    model_aliases: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class WorkflowBinding(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    node_id: str
    input_name: str = Field(alias="input")


class LoRASlotBinding(BaseModel):
    node_id: str
    name_input: str = "lora_name"
    model_strength_input: str = "strength_model"
    clip_strength_input: str = "strength_clip"


class WorkflowProfile(BaseModel):
    id: str
    display_name: str
    api_workflow: dict[str, Any]
    bindings: dict[str, WorkflowBinding]
    workflow_kind: Literal["txt2img_basic", "txt2img_hiresfix_1_5x", "unknown"] = "unknown"
    lora_slots: list[LoRASlotBinding] = Field(default_factory=list)
    compatible_model_profiles: list[str] = Field(default_factory=list)
    source_path: str = ""
    notes: str = ""


class GenerationRun(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    prompt_job_id: str
    remote_profile_id: str
    workflow_profile_id: str
    remote_prompt_id: str = ""
    client_id: str = Field(default_factory=lambda: str(uuid4()))
    state: GenerationRunState = GenerationRunState.DRAFT
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    status_message: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    output_dir: str = ""
    error_code: str = ""
    error_message: str = ""
    request_json: dict[str, Any] = Field(default_factory=dict)
    actual_workflow: dict[str, Any] = Field(default_factory=dict)

    def update_state(
        self,
        state: GenerationRunState,
        message: str = "",
        progress: float | None = None,
    ) -> None:
        self.state = state
        self.status_message = message
        if progress is not None:
            self.progress = max(0.0, min(1.0, progress))
        self.updated_at = utc_now()
        if state == GenerationRunState.COMPLETED:
            self.completed_at = self.updated_at
            self.progress = 1.0


class GenerationArtifact(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    generation_run_id: str
    node_id: str = ""
    remote_filename: str
    remote_subfolder: str = ""
    remote_type: str = "output"
    local_path: str = ""
    sha256: str = ""
    byte_size: int = Field(default=0, ge=0)
    mime_type: str = "application/octet-stream"
    download_state: Literal["pending", "completed", "failed"] = "pending"


class RemoteArtifact(BaseModel):
    node_id: str = ""
    filename: str
    subfolder: str = ""
    folder_type: str = "output"


class EnvironmentReport(BaseModel):
    connected: bool = True
    system_stats: dict[str, Any] = Field(default_factory=dict)
    queue_running: int = 0
    queue_pending: int = 0
    devices: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RemoteCredentials(BaseModel):
    """Ephemeral credentials. Never persist this model."""

    password: str = ""
    passphrase: str = ""
