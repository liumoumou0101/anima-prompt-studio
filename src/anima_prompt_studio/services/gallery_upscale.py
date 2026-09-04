from __future__ import annotations

import copy
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from anima_prompt_studio.domain.execution_models import (
    GenerationArtifact,
    GenerationRun,
    GenerationRunState,
    RemoteAuthType,
    RemoteCredentials,
    RemoteProfile,
    WorkflowProfile,
)
from anima_prompt_studio.domain.models import GenerationFieldState, GenerationParams, PromptJob, utc_now
from anima_prompt_studio.repositories import SQLiteRepository
from anima_prompt_studio.services.config_service import ConfigService
from anima_prompt_studio.services.prompt_compiler import PromptCompiler
from anima_prompt_studio.services.remote.comfy_client import ComfyAPIError, ComfyUIClient
from anima_prompt_studio.services.remote.execution_coordinator import (
    RemoteExecutionCoordinator,
    RemoteExecutionError,
)
from anima_prompt_studio.services.remote.result_organizer import ResultOrganizer
from anima_prompt_studio.services.remote.ssh_tunnel import SshTunnel
from anima_prompt_studio.services.remote.workflow_renderer import WorkflowRenderer, WorkflowRenderResult
from anima_prompt_studio.services.remote.workflow_compatibility import infer_workflow_model_profiles


GALLERY_UPSCALE_OPERATION = "gallery_upscale_1_5x"
GALLERY_REGEN_OPERATION = "gallery_txt2img_more"
GALLERY_UPSCALE_SCALE = 1.5
GALLERY_REGEN_MAX_COUNT = 4


def choose_txt2img_workflow(
    profiles: list[WorkflowProfile],
    model_profile_id: str,
) -> WorkflowProfile | None:
    """Pick a tested basic txt2img workflow compatible with the source model."""
    candidates = [
        profile for profile in profiles
        if profile.workflow_kind == "txt2img_basic"
        and model_profile_id in (
            profile.compatible_model_profiles
            or infer_workflow_model_profiles(
                profile.api_workflow,
                profile.source_path or profile.display_name or profile.id,
            )
        )
    ]
    preferred = {
        "anima_base_v1": "01",
        "anima_turbo_v1": "02",
        "anima_aesthetic_v1": "22",
        "anima_turbo_v1_1": "23",
        "animayume_v1_0_final": "24",
        "miaomiao_harem_anima_v1_6": "25",
    }.get(model_profile_id, "")
    return next((item for item in candidates if item.id.startswith(preferred)), None) or (
        candidates[0] if candidates else None
    )


def snapshot_regen_parameters(asset: dict[str, Any]) -> dict[str, Any]:
    """Keep the source image's sampling settings so regen does not fall back to defaults."""
    raw = asset.get("parameters") if isinstance(asset.get("parameters"), dict) else {}
    nested = raw.get("generation_params") if isinstance(raw.get("generation_params"), dict) else {}
    source = raw.get("source") if isinstance(raw.get("source"), dict) else {}
    snapshot: dict[str, Any] = {}
    for field_name in ("steps", "cfg", "sampler", "scheduler"):
        value = nested.get(field_name, raw.get(field_name))
        if value not in (None, ""):
            snapshot[field_name] = value
    preset = raw.get("generation_preset_id") or raw.get("generation_preset") or nested.get("generation_preset_id")
    quality = raw.get("quality_profile_id") or raw.get("quality_profile") or nested.get("quality_profile_id")
    if preset:
        snapshot["generation_preset_id"] = preset
    if quality:
        snapshot["quality_profile_id"] = quality
    for field_name, value in (
        ("negative_prompt", raw.get("negative_prompt") or nested.get("negative_prompt")),
        ("original_zh", raw.get("original_zh") or source.get("original_zh")),
        ("translated_en", raw.get("translated_en") or source.get("translated_en")),
    ):
        if value not in (None, ""):
            snapshot[field_name] = value
    integration = raw.get("integration_metadata")
    if isinstance(integration, dict):
        snapshot["integration_metadata"] = copy.deepcopy(integration)
    return snapshot


def build_gallery_regen_job(
    asset: dict[str, Any],
    *,
    workflow_id: str,
    count: int,
) -> PromptJob:
    """Rebuild a PromptJob from a gallery asset so the same prompt can run again."""
    prompt = str(asset.get("prompt") or "").strip()
    if not prompt:
        raise GalleryUpscaleError("这张图片没有保存提示词，无法再出图。")
    raw = snapshot_regen_parameters(asset)
    nested = raw
    model_id = str(asset.get("model") or raw.get("model_profile_id") or "anima_base_v1")
    count = max(1, min(int(count), GALLERY_REGEN_MAX_COUNT))
    integration = copy.deepcopy(raw.get("integration_metadata")) if isinstance(raw.get("integration_metadata"), dict) else {}
    comparison = integration.get("artist_comparison")
    if isinstance(comparison, dict) and comparison.get("rendered_artist"):
        source_comparison_id = str(comparison.get("source_comparison_id") or comparison.get("id") or "")
        integration["artist_comparison"] = {
            "id": str(comparison.get("id") or source_comparison_id),
            "artist": str(comparison.get("artist") or ""),
            "rendered_artist": str(comparison["rendered_artist"]),
            "derived_from": "gallery_regenerate",
            "source_comparison_id": source_comparison_id,
        }
    integration["gallery_regeneration"] = {
        "source_image": str(asset.get("path") or asset.get("name") or ""),
    }
    job = PromptJob(
        project_name=str(asset.get("project") or "画廊再出图") + "·再出图",
        original_zh=str(raw.get("original_zh") or ""),
        translated_en=str(raw.get("translated_en") or ""),
        positive_prompt=prompt,
        negative_prompt=str(raw.get("negative_prompt") or ""),
        model_profile_id=model_id,
        generation_preset_id=str(raw.get("generation_preset_id") or "balanced"),
        quality_profile_id=str(raw.get("quality_profile_id") or "standard"),
        workflow_template_id=workflow_id,
        notes=f"画廊同提示词再出图，源图：{asset.get('path') or asset.get('name') or ''}",
        integration_metadata=integration,
    )
    PromptCompiler(ConfigService()).apply_model_defaults(job)
    width = int(asset.get("width") or nested.get("width") or job.generation_params.width)
    height = int(asset.get("height") or nested.get("height") or job.generation_params.height)
    job.generation_params.width = width
    job.generation_params.height = height
    job.generation_params.batch_size = count
    job.generation_params.seed = -1
    job.generation_params.set_state("width", GenerationFieldState.USER_SELECTED)
    job.generation_params.set_state("height", GenerationFieldState.USER_SELECTED)
    job.generation_params.set_state("batch_size", GenerationFieldState.USER_SELECTED)
    for field_name in ("steps", "cfg", "sampler", "scheduler"):
        value = nested.get(field_name)
        if value in (None, ""):
            continue
        if field_name == "cfg":
            setattr(job.generation_params, field_name, float(value))
        elif field_name in {"steps"}:
            setattr(job.generation_params, field_name, int(value))
        else:
            setattr(job.generation_params, field_name, str(value))
        job.generation_params.set_state(field_name, GenerationFieldState.USER_SELECTED)
    return job


class GalleryUpscaleError(RuntimeError):
    pass


@dataclass(frozen=True)
class GalleryUpscaleRenderResult:
    workflow: dict[str, Any]
    seed: int
    metadata: dict[str, Any]


class GalleryUpscaleRenderer:
    """Turn the bundled tile-upscale template into a safe one-image API prompt."""

    DROPPED_CLASSES = {
        "reroute",
        "seed (rgthree)",
        "showtext|pysssss",
        "jwstringconcat",
        "image comparer (rgthree)",
    }

    @classmethod
    def supports(cls, profile: WorkflowProfile | None) -> bool:
        if profile is None:
            return False
        classes = {
            str(node.get("class_type", "")).casefold()
            for node in profile.api_workflow.values()
            if isinstance(node, dict)
        }
        required = {
            "loadimage",
            "imageupscalewithmodel",
            "imagescaletototalpixels",
            "ttp_image_tile_batch",
            "ttp_image_assy",
            "saveimage",
        }
        return required.issubset(classes) and any("ksampler" in name for name in classes)

    def render(
        self,
        profile: WorkflowProfile,
        *,
        uploaded_image: str,
        source_width: int,
        source_height: int,
        run_id: str,
        source_relative_path: str,
        seed: int = -1,
    ) -> GalleryUpscaleRenderResult:
        if not self.supports(profile):
            raise GalleryUpscaleError("分块放大工作流缺少必要的图片输入、放大或保存节点。")
        if source_width <= 0 or source_height <= 0:
            raise GalleryUpscaleError("无法识别原图尺寸。")

        workflow = {
            str(node_id): copy.deepcopy(node)
            for node_id, node in profile.api_workflow.items()
            if isinstance(node, dict)
            and str(node.get("class_type", "")).casefold() not in self.DROPPED_CLASSES
        }
        load_id = self._node_id(workflow, "loadimage")
        upscale_id = self._node_id(workflow, "imageupscalewithmodel")
        scale_id = self._node_id(workflow, "imagescaletototalpixels")
        tile_size_id = self._node_id(workflow, "ttp_tile_image_size")
        tile_batch_id = self._node_id(workflow, "ttp_image_tile_batch")
        tile_assembly_id = self._node_id(workflow, "ttp_image_assy")
        tagger_id = self._node_id(workflow, "wd14tagger|pysssss")
        unet_id = self._node_id(workflow, "unetloader")
        clip_id = self._node_id(workflow, "cliploader")
        sampler_id = self._node_id_contains(workflow, "ksampler")
        save_id = self._node_id(workflow, "saveimage")

        positive_id = self._binding_node(profile, "positive_prompt", workflow)
        negative_id = self._binding_node(profile, "negative_prompt", workflow)
        target_width = round(source_width * GALLERY_UPSCALE_SCALE)
        target_height = round(source_height * GALLERY_UPSCALE_SCALE)
        resolved_seed = seed if seed >= 0 else secrets.randbelow(2**63 - 1)

        workflow[load_id]["inputs"]["image"] = uploaded_image
        workflow[upscale_id]["inputs"]["image"] = [load_id, 0]
        workflow[scale_id]["inputs"]["image"] = [upscale_id, 0]
        workflow[scale_id]["inputs"]["megapixels"] = target_width * target_height / 1_000_000
        workflow[scale_id]["inputs"]["resolution_steps"] = 1
        workflow[tile_size_id]["inputs"]["image"] = [scale_id, 0]
        workflow[tile_batch_id]["inputs"]["image"] = [scale_id, 0]
        workflow[positive_id]["inputs"]["clip"] = [clip_id, 0]
        workflow[positive_id]["inputs"]["text"] = [tagger_id, 0]
        workflow[negative_id]["inputs"]["clip"] = [clip_id, 0]
        workflow[sampler_id]["inputs"]["model"] = [unet_id, 0]
        workflow[sampler_id]["inputs"]["seed"] = resolved_seed
        workflow[sampler_id]["inputs"]["sampler_mode"] = "standard"
        workflow[sampler_id]["inputs"]["bongmath"] = True
        final_scale_id = self._available_node_id(workflow, "900001")
        workflow[final_scale_id] = {
            "class_type": "ImageScale",
            "inputs": {
                "image": [tile_assembly_id, 0],
                "upscale_method": "lanczos",
                "width": target_width,
                "height": target_height,
                "crop": "disabled",
            },
            "_meta": {"title": "ANIMA 精确输出尺寸"},
        }
        workflow[save_id]["inputs"]["images"] = [final_scale_id, 0]
        workflow[save_id]["inputs"]["filename_prefix"] = f"Anima_Gallery15x_{run_id[:8]}"

        self._validate_connections(workflow)
        metadata = {
            "workflow_kind": GALLERY_UPSCALE_OPERATION,
            "operation": GALLERY_UPSCALE_OPERATION,
            "scale": GALLERY_UPSCALE_SCALE,
            "base_width": source_width,
            "base_height": source_height,
            "output_width": target_width,
            "output_height": target_height,
            "source_image": source_relative_path,
            "sampler": self._sampler_snapshot(workflow[sampler_id].get("inputs", {})),
        }
        return GalleryUpscaleRenderResult(workflow=workflow, seed=resolved_seed, metadata=metadata)

    @staticmethod
    def _node_id(workflow: dict[str, Any], class_name: str) -> str:
        expected = class_name.casefold()
        for node_id, node in workflow.items():
            if str(node.get("class_type", "")).casefold() == expected:
                return node_id
        raise GalleryUpscaleError(f"分块放大工作流缺少节点：{class_name}")

    @staticmethod
    def _node_id_contains(workflow: dict[str, Any], text: str) -> str:
        expected = text.casefold()
        for node_id, node in workflow.items():
            if expected in str(node.get("class_type", "")).casefold():
                return node_id
        raise GalleryUpscaleError(f"分块放大工作流缺少节点：{text}")

    @staticmethod
    def _binding_node(profile: WorkflowProfile, name: str, workflow: dict[str, Any]) -> str:
        binding = profile.bindings.get(name)
        if binding is None or binding.node_id not in workflow:
            raise GalleryUpscaleError(f"分块放大工作流缺少绑定：{name}")
        return binding.node_id

    @staticmethod
    def _validate_connections(workflow: dict[str, Any]) -> None:
        for node_id, node in workflow.items():
            for input_name, value in node.get("inputs", {}).items():
                if (
                    isinstance(value, list)
                    and len(value) == 2
                    and isinstance(value[0], (str, int))
                    and str(value[0]) not in workflow
                ):
                    raise GalleryUpscaleError(
                        f"工作流连接无效：{node_id}.{input_name} 引用了缺失节点 {value[0]}"
                    )

    @staticmethod
    def _available_node_id(workflow: dict[str, Any], preferred: str) -> str:
        if preferred not in workflow:
            return preferred
        candidate = int(preferred) + 1
        while str(candidate) in workflow:
            candidate += 1
        return str(candidate)

    @staticmethod
    def _sampler_snapshot(inputs: dict[str, Any]) -> dict[str, Any]:
        return {
            key: inputs[key]
            for key in ("seed", "steps", "cfg", "sampler_name", "scheduler", "denoise")
            if key in inputs and not isinstance(inputs[key], (list, tuple, dict))
        }


@dataclass(frozen=True)
class GalleryUpscaleExecutionResult:
    run: GenerationRun
    artifacts: list[GenerationArtifact]


class GalleryUpscaleCoordinator:
    def __init__(
        self,
        *,
        organizer: ResultOrganizer,
        renderer: GalleryUpscaleRenderer | None = None,
        tunnel_factory: Callable[[RemoteProfile], object] = SshTunnel,
        client_factory: Callable[[str], ComfyUIClient] = ComfyUIClient,
        on_update: Callable[[GenerationRun], None] | None = None,
        poll_interval: float = 1.5,
    ) -> None:
        self.organizer = organizer
        self.renderer = renderer or GalleryUpscaleRenderer()
        self.tunnel_factory = tunnel_factory
        self.client_factory = client_factory
        self.on_update = on_update
        self.poll_interval = poll_interval

    def execute(
        self,
        *,
        job: PromptJob,
        source_path: Path,
        source_relative_path: str,
        source_width: int,
        source_height: int,
        remote_profile: RemoteProfile,
        workflow_profile: WorkflowProfile,
        credentials: RemoteCredentials,
    ) -> GalleryUpscaleExecutionResult:
        run = GenerationRun(
            prompt_job_id=job.id,
            remote_profile_id=remote_profile.id,
            workflow_profile_id=workflow_profile.id,
            request_json={
                "prompt_job": job.model_dump(mode="json"),
                "operation": GALLERY_UPSCALE_OPERATION,
                "source_image": source_relative_path,
            },
        )
        artifacts: list[GenerationArtifact] = []
        try:
            self._update(run, GenerationRunState.CONNECTING, "正在连接云主机", 0.05)
            tunnel = self.tunnel_factory(remote_profile)
            with tunnel:
                tunnel.open(credentials)
                client = self.client_factory(tunnel.base_url)
                client.validate_environment()
                self._update(run, GenerationRunState.PREPARING, "正在上传原图", 0.12)
                suffix = source_path.suffix.casefold() or ".png"
                uploaded = client.upload_image(
                    source_path,
                    subfolder=f"anima_gallery/{run.id}",
                    remote_name=f"source_{run.id[:8]}{suffix}",
                )
                rendered = self.renderer.render(
                    workflow_profile,
                    uploaded_image=uploaded,
                    source_width=source_width,
                    source_height=source_height,
                    run_id=run.id,
                    source_relative_path=source_relative_path,
                )
                missing_nodes = client.validate_workflow_nodes(rendered.workflow)
                if missing_nodes:
                    raise ComfyAPIError(
                        "云端缺少放大工作流节点：" + ", ".join(missing_nodes),
                        code="missing_nodes",
                    )
                input_validator = getattr(client, "validate_workflow_inputs", None)
                invalid_inputs = input_validator(rendered.workflow) if callable(input_validator) else []
                if invalid_inputs:
                    raise ComfyAPIError(
                        "云端工作流参数预检失败：" + "；".join(invalid_inputs),
                        code="invalid_workflow_inputs",
                        details=invalid_inputs,
                    )
                run.actual_workflow = rendered.workflow
                run.request_json["resolved_seed"] = rendered.seed
                run.request_json["render_metadata"] = rendered.metadata
                requested_prompt_id = str(uuid4())
                run.remote_prompt_id = client.submit(rendered.workflow, run.client_id, requested_prompt_id)
                self._update(run, GenerationRunState.QUEUED, "已提交到云端队列", 0.2)
                history = client.wait_for_completion(
                    run.remote_prompt_id,
                    on_state=lambda state, message: self._remote_state(run, state, message),
                    poll_interval=self.poll_interval,
                )
                remote_artifacts = client.list_output_artifacts(history)
                if not remote_artifacts:
                    raise ComfyAPIError("高清修复完成，但没有发现图片输出。", code="no_outputs")
                self._update(run, GenerationRunState.DOWNLOADING, "正在下载高清修复结果", 0.82)
                for index, remote_artifact in enumerate(remote_artifacts, 1):
                    content, mime_type = client.download_artifact(remote_artifact)
                    artifacts.append(
                        self.organizer.save_artifact(job, run, remote_artifact, content, index, mime_type)
                    )
                    self._update(
                        run,
                        GenerationRunState.DOWNLOADING,
                        f"正在下载结果 {index}/{len(remote_artifacts)}",
                        0.82 + 0.16 * index / len(remote_artifacts),
                    )
                run.update_state(GenerationRunState.COMPLETED, "1.5× 高清修复完成", 1.0)
                self.organizer.write_sidecars(job, run, artifacts)
                self._notify(run)
                return GalleryUpscaleExecutionResult(run=run, artifacts=artifacts)
        except ComfyAPIError as exc:
            run.error_code = exc.code
            run.error_message = str(exc)
            self._update(run, GenerationRunState.FAILED, str(exc), run.progress)
            raise GalleryUpscaleError(str(exc)) from exc
        except Exception as exc:
            run.error_code = type(exc).__name__
            run.error_message = str(exc)
            self._update(run, GenerationRunState.FAILED, str(exc), run.progress)
            raise GalleryUpscaleError(str(exc)) from exc

    def _remote_state(self, run: GenerationRun, state: str, message: str) -> None:
        if state == "running":
            self._update(run, GenerationRunState.RUNNING, "云端正在进行 1.5× 高清修复", max(run.progress, 0.35))
        elif state == "queued" and run.state != GenerationRunState.RUNNING:
            self._update(run, GenerationRunState.QUEUED, message, max(run.progress, 0.2))

    def _update(self, run: GenerationRun, state: GenerationRunState, message: str, progress: float) -> None:
        run.update_state(state, message, progress)
        self._notify(run)

    def _notify(self, run: GenerationRun) -> None:
        if self.on_update:
            self.on_update(run.model_copy(deep=True))


@dataclass
class GalleryProcessJob:
    id: str
    source_path: str
    source_name: str
    source_width: int
    source_height: int
    target_width: int
    target_height: int
    workflow_name: str
    operation: str = GALLERY_UPSCALE_OPERATION
    batch_count: int = 1
    project: str = "画廊高清修复"
    model: str = "anima_base_v1"
    prompt: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    queue_position: int = 0
    generation_run_id: str = ""
    remote_prompt_id: str = ""
    attempt: int = 0
    state: str = "queued"
    message: str = "等待处理"
    progress: float = 0.0
    result_path: str = ""
    error: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @property
    def terminal(self) -> bool:
        return self.state in {"completed", "failed", "canceled"}

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> GalleryProcessJob:
        def parsed_time(name: str) -> datetime:
            value = payload.get(name)
            try:
                return datetime.fromisoformat(str(value))
            except (TypeError, ValueError):
                return utc_now()

        return cls(
            id=str(payload["id"]),
            source_path=str(payload.get("sourcePath") or ""),
            source_name=str(payload.get("sourceName") or ""),
            source_width=int(payload.get("sourceWidth") or 0),
            source_height=int(payload.get("sourceHeight") or 0),
            target_width=int(payload.get("targetWidth") or 0),
            target_height=int(payload.get("targetHeight") or 0),
            workflow_name=str(payload.get("workflowName") or ""),
            operation=str(payload.get("operation") or GALLERY_UPSCALE_OPERATION),
            batch_count=max(1, min(int(payload.get("batchCount") or 1), GALLERY_REGEN_MAX_COUNT)),
            project=str(payload.get("project") or "画廊高清修复"),
            model=str(payload.get("model") or "anima_base_v1"),
            prompt=str(payload.get("prompt") or ""),
            parameters=dict(payload.get("parameters") or {}) if isinstance(payload.get("parameters"), dict) else {},
            queue_position=int(payload.get("queuePosition") or 0),
            generation_run_id=str(payload.get("generationRunId") or ""),
            remote_prompt_id=str(payload.get("remotePromptId") or ""),
            attempt=int(payload.get("attempt") or 0),
            state=str(payload.get("state") or "queued"),
            message=str(payload.get("message") or "等待处理"),
            progress=float(payload.get("progress") or 0.0),
            result_path=str(payload.get("resultPath") or ""),
            error=str(payload.get("error") or ""),
            created_at=parsed_time("createdAt"),
            updated_at=parsed_time("updatedAt"),
        )

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "sourcePath": self.source_path,
            "sourceName": self.source_name,
            "sourceWidth": self.source_width,
            "sourceHeight": self.source_height,
            "targetWidth": self.target_width,
            "targetHeight": self.target_height,
            "workflowName": self.workflow_name,
            "operation": self.operation,
            "batchCount": self.batch_count,
            "project": self.project,
            "model": self.model,
            "prompt": self.prompt,
            "parameters": dict(self.parameters),
            "queuePosition": self.queue_position,
            "generationRunId": self.generation_run_id,
            "remotePromptId": self.remote_prompt_id,
            "attempt": self.attempt,
            "state": self.state,
            "message": self.message,
            "progress": self.progress,
            "resultPath": self.result_path,
            "error": self.error,
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }


class GalleryUpscaleManager:
    MAX_PENDING_JOBS = 50

    def __init__(
        self,
        repository_path: Path,
        output_root: Path,
        *,
        coordinator_factory: Callable[..., GalleryUpscaleCoordinator] = GalleryUpscaleCoordinator,
        regen_coordinator_factory: Callable[..., RemoteExecutionCoordinator] = RemoteExecutionCoordinator,
    ) -> None:
        self.repository_path = repository_path
        self.output_root = output_root.expanduser()
        self.coordinator_factory = coordinator_factory
        self.regen_coordinator_factory = regen_coordinator_factory
        self._remote_profile: RemoteProfile | None = None
        self._workflow_profile: WorkflowProfile | None = None
        self._txt2img_workflows: list[WorkflowProfile] = []
        self._credentials = RemoteCredentials()
        self._jobs: dict[str, GalleryProcessJob] = {}
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._stopping = False
        self._load_jobs()
        self._worker = threading.Thread(
            target=self._run_loop,
            name="anima-gallery-upscale-queue",
            daemon=True,
        )
        self._worker.start()

    def pending_count(self) -> int:
        with self._lock:
            return sum(1 for job in self._jobs.values() if not job.terminal)

    def output_root_change_blocked_reason(self) -> str:
        pending = self.pending_count()
        if not pending:
            return ""
        return (
            f"还有 {pending} 项高清修复任务未完成。"
            "请先在任务中心等待完成，或取消仍在排队的任务后再切换画廊目录。"
        )

    def set_output_root(self, output_root: Path) -> None:
        with self._condition:
            resolved = output_root.expanduser()
            if resolved.resolve() == self.output_root.resolve():
                return
            reason = self.output_root_change_blocked_reason()
            if reason:
                raise GalleryUpscaleError(reason)
            self.output_root = resolved
            self._jobs.clear()
            self._load_jobs_locked()
            self._condition.notify_all()

    def configure(
        self,
        remote_profile: RemoteProfile | None,
        workflow_profile: WorkflowProfile | None,
        credentials: RemoteCredentials | None,
        txt2img_workflows: list[WorkflowProfile] | None = None,
    ) -> None:
        with self._condition:
            self._remote_profile = remote_profile.model_copy(deep=True) if remote_profile else None
            self._workflow_profile = workflow_profile.model_copy(deep=True) if workflow_profile else None
            self._txt2img_workflows = [
                item.model_copy(deep=True) for item in (txt2img_workflows or [])
            ]
            self._credentials = (credentials or RemoteCredentials()).model_copy(deep=True)
            self._condition.notify_all()

    def configuration_payload(self) -> dict[str, Any]:
        with self._lock:
            reason = self._unavailable_reason()
            active_job = next((job for job in self._jobs.values() if self._is_active(job)), None)
            queued = [job for job in self._jobs.values() if job.state == "queued"]
            failed = [job for job in self._jobs.values() if job.state == "failed"]
            regen_reason = self._regen_reason()
            return {
                "available": not reason,
                "reason": reason,
                "scale": GALLERY_UPSCALE_SCALE,
                "workflowName": self._workflow_profile.display_name if self._workflow_profile else "",
                "regenAvailable": not regen_reason,
                "regenReason": regen_reason,
                "regenWorkflowName": "按原图模型自动选择" if not regen_reason else "",
                "regenMaxCount": GALLERY_REGEN_MAX_COUNT,
                "activeJob": active_job.payload() if active_job else None,
                "activeCount": 1 if active_job else 0,
                "queuedCount": len(queued),
                "failedCount": len(failed),
                "totalCount": len(self._jobs),
            }

    def submit(self, source: Path, relative_path: str, asset: dict[str, Any]) -> dict[str, Any]:
        with self._condition:
            reason = self._unavailable_reason()
            if reason:
                raise GalleryUpscaleError(reason)
            pending = [job for job in self._jobs.values() if not job.terminal]
            if len(pending) >= self.MAX_PENDING_JOBS:
                raise GalleryUpscaleError(f"任务队列已达到 {self.MAX_PENDING_JOBS} 项，请稍后再添加。")
            duplicate = next(
                (job for job in pending if job.source_path.casefold() == relative_path.casefold()),
                None,
            )
            if duplicate:
                raise GalleryUpscaleError("这张图片已经在高清修复队列中。")
            width = int(asset.get("width") or 0)
            height = int(asset.get("height") or 0)
            if width <= 0 or height <= 0:
                raise GalleryUpscaleError("无法识别原图尺寸。")
            queue_position = max(
                (job.queue_position for job in self._jobs.values() if job.state == "queued"),
                default=0,
            ) + 1
            process_job = GalleryProcessJob(
                id=str(uuid4()),
                source_path=relative_path,
                source_name=source.name,
                source_width=width,
                source_height=height,
                target_width=round(width * GALLERY_UPSCALE_SCALE),
                target_height=round(height * GALLERY_UPSCALE_SCALE),
                workflow_name=self._workflow_profile.display_name,
                project=str(asset.get("project") or source.parent.name or "画廊高清修复"),
                model=str(asset.get("model") or "anima_base_v1"),
                prompt=str(asset.get("prompt") or ""),
                queue_position=queue_position,
                message=f"等待处理 · 队列第 {queue_position} 位",
            )
            self._jobs[process_job.id] = process_job
            self._persist_locked(process_job)
            self._condition.notify_all()
            return process_job.payload()

    def submit_regenerate(
        self,
        source: Path,
        relative_path: str,
        asset: dict[str, Any],
        count: int = 1,
    ) -> dict[str, Any]:
        with self._condition:
            reason = self._regen_reason(str(asset.get("model") or ""))
            if reason:
                raise GalleryUpscaleError(reason)
            prompt = str(asset.get("prompt") or "").strip()
            if not prompt:
                raise GalleryUpscaleError("这张图片没有保存提示词，无法再出图。外部导入的图片请先用主窗口生成。")
            pending = [job for job in self._jobs.values() if not job.terminal]
            if len(pending) >= self.MAX_PENDING_JOBS:
                raise GalleryUpscaleError(f"任务队列已达到 {self.MAX_PENDING_JOBS} 项，请稍后再添加。")
            count = max(1, min(int(count), GALLERY_REGEN_MAX_COUNT))
            width = int(asset.get("width") or 0)
            height = int(asset.get("height") or 0)
            if width <= 0 or height <= 0:
                raise GalleryUpscaleError("无法识别原图尺寸。")
            model_id = str(asset.get("model") or "anima_base_v1")
            workflow = choose_txt2img_workflow(self._txt2img_workflows, model_id)
            if workflow is None:
                raise GalleryUpscaleError("没有找到可用的基础文生图工作流。")
            queue_position = max(
                (job.queue_position for job in self._jobs.values() if job.state == "queued"),
                default=0,
            ) + 1
            process_job = GalleryProcessJob(
                id=str(uuid4()),
                source_path=relative_path,
                source_name=source.name,
                source_width=width,
                source_height=height,
                target_width=width,
                target_height=height,
                workflow_name=workflow.display_name,
                operation=GALLERY_REGEN_OPERATION,
                batch_count=count,
                project=str(asset.get("project") or source.parent.name or "画廊再出图"),
                model=model_id,
                prompt=prompt,
                parameters=snapshot_regen_parameters(asset),
                queue_position=queue_position,
                message=f"等待再出图 · 队列第 {queue_position} 位",
            )
            self._jobs[process_job.id] = process_job
            self._persist_locked(process_job)
            self._condition.notify_all()
            return process_job.payload()

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.payload() if job else None

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = sorted(
                self._jobs.values(),
                key=lambda job: (
                    0 if self._is_active(job) else 1 if job.state == "queued" else 2,
                    job.queue_position if not job.terminal else 0,
                    -job.updated_at.timestamp(),
                ),
            )
            return [job.payload() for job in jobs]

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._condition:
            job = self._jobs.get(job_id)
            if job is None:
                raise GalleryUpscaleError("任务不存在或已经被清理。")
            if job.state != "queued":
                raise GalleryUpscaleError("只能取消尚未开始的排队任务。")
            job.state = "canceled"
            job.message = "已取消"
            job.queue_position = 0
            job.updated_at = utc_now()
            self._persist_locked(job)
            self._renumber_queue_locked()
            self._condition.notify_all()
            return job.payload()

    def retry(self, job_id: str) -> dict[str, Any]:
        with self._condition:
            job = self._jobs.get(job_id)
            if job is None:
                raise GalleryUpscaleError("任务不存在或已经被清理。")
            reason = (
                self._regen_reason(job.model)
                if job.operation == GALLERY_REGEN_OPERATION
                else self._unavailable_reason()
            )
            if reason:
                raise GalleryUpscaleError(reason)
            if job.state not in {"failed", "canceled"}:
                raise GalleryUpscaleError("只有失败或已取消的任务可以重试。")
            if job.operation != GALLERY_REGEN_OPERATION and any(
                not other.terminal
                and other.id != job.id
                and other.operation != GALLERY_REGEN_OPERATION
                and other.source_path.casefold() == job.source_path.casefold()
                for other in self._jobs.values()
            ):
                raise GalleryUpscaleError("这张图片已经在高清修复队列中。")
            job.state = "queued"
            job.queue_position = max(
                (item.queue_position for item in self._jobs.values() if item.state == "queued"),
                default=0,
            ) + 1
            job.message = f"等待处理 · 队列第 {job.queue_position} 位"
            job.progress = 0.0
            job.error = ""
            job.result_path = ""
            job.generation_run_id = ""
            job.remote_prompt_id = ""
            job.updated_at = utc_now()
            self._persist_locked(job)
            self._condition.notify_all()
            return job.payload()

    def clear_completed(self) -> int:
        with self._condition:
            finished = [
                job for job in self._jobs.values()
                if job.state in {"completed", "canceled", "failed"}
            ]
            if not finished:
                return 0
            repository = SQLiteRepository(self.repository_path)
            try:
                for job in finished:
                    repository.delete_gallery_process_job(self.output_root, job.id)
                    self._jobs.pop(job.id, None)
            finally:
                repository.close()
            return len(finished)

    def locked_paths(self) -> set[str]:
        with self._lock:
            return {job.source_path for job in self._jobs.values() if not job.terminal}

    def shutdown(self, *, cancel_queued: bool = True, timeout: float = 10.0) -> bool:
        """Stop accepting work and end the queue thread after any active call returns."""
        with self._condition:
            if cancel_queued:
                for job in self._jobs.values():
                    if job.state == "queued":
                        job.state = "canceled"
                        job.message = "应用退出，排队任务已取消"
                        job.queue_position = 0
                        job.updated_at = utc_now()
                        self._persist_locked(job)
            self._stopping = True
            self._condition.notify_all()
        self._worker.join(timeout)
        return not self._worker.is_alive()

    def _connection_reason(self) -> str:
        if self._remote_profile is None:
            return "请先在主窗口配置并连接云显卡。"
        if (
            self._remote_profile.auth_type == RemoteAuthType.PASSWORD
            and not self._credentials.password
        ):
            return "云主机密码不可用，请先回到主窗口连接一次。"
        if not self._remote_profile.known_host_fingerprint:
            return "请先在主窗口连接并确认云主机指纹。"
        return ""

    def _unavailable_reason(self) -> str:
        connection = self._connection_reason()
        if connection:
            return connection
        if self._workflow_profile is None or not GalleryUpscaleRenderer.supports(self._workflow_profile):
            return "没有找到可用的“20 分块放大”工作流。"
        return ""

    def _regen_reason(self, model_profile_id: str = "") -> str:
        connection = self._connection_reason()
        if connection:
            return connection
        if model_profile_id:
            available = choose_txt2img_workflow(self._txt2img_workflows, model_profile_id) is not None
        else:
            available = any(
                profile.workflow_kind == "txt2img_basic"
                and bool(
                    profile.compatible_model_profiles
                    or infer_workflow_model_profiles(
                        profile.api_workflow,
                        profile.source_path or profile.display_name or profile.id,
                    )
                )
                for profile in self._txt2img_workflows
            )
        if not available:
            return "没有找到可用的基础文生图工作流。"
        return ""

    @staticmethod
    def _is_active(job: GalleryProcessJob) -> bool:
        return job.state not in {"queued", "completed", "failed", "canceled"}

    def _load_jobs(self) -> None:
        with self._condition:
            self._load_jobs_locked()

    def _load_jobs_locked(self) -> None:
        repository = SQLiteRepository(self.repository_path)
        try:
            payloads = repository.list_gallery_process_jobs(self.output_root)
        finally:
            repository.close()
        for payload in payloads:
            job = GalleryProcessJob.from_payload(payload)
            if self._is_active(job):
                job.state = "failed"
                job.message = "应用上次退出时任务仍在执行，请确认云端状态后重试"
                job.error = "任务执行被应用退出中断"
                job.queue_position = 0
                job.updated_at = utc_now()
                self._persist_locked(job)
            self._jobs[job.id] = job
        self._renumber_queue_locked()

    def _persist_locked(self, job: GalleryProcessJob) -> None:
        repository = SQLiteRepository(self.repository_path)
        try:
            repository.save_gallery_process_job(
                self.output_root,
                job.id,
                job.state,
                job.queue_position,
                job.updated_at,
                job.payload(),
            )
        finally:
            repository.close()

    def _renumber_queue_locked(self) -> None:
        queued = sorted(
            (job for job in self._jobs.values() if job.state == "queued"),
            key=lambda job: (job.queue_position, job.created_at),
        )
        for index, job in enumerate(queued, 1):
            message = f"等待处理 · 队列第 {index} 位"
            if job.queue_position != index or job.message != message:
                job.queue_position = index
                job.message = message
                job.updated_at = utc_now()
                self._persist_locked(job)

    def _job_ready_locked(self, job: GalleryProcessJob) -> bool:
        if job.operation == GALLERY_REGEN_OPERATION:
            return not self._regen_reason(job.model)
        return not self._unavailable_reason()

    def _next_runnable_locked(self) -> GalleryProcessJob | None:
        queued = sorted(
            (job for job in self._jobs.values() if job.state == "queued"),
            key=lambda job: (job.queue_position, job.created_at),
        )
        return next((job for job in queued if self._job_ready_locked(job)), None)

    def _run_loop(self) -> None:
        while True:
            with self._condition:
                while True:
                    if self._stopping:
                        return
                    process_job = self._next_runnable_locked()
                    if process_job:
                        process_job.state = "starting"
                        process_job.message = "正在准备任务"
                        process_job.progress = 0.01
                        process_job.queue_position = 0
                        process_job.attempt += 1
                        process_job.updated_at = utc_now()
                        self._persist_locked(process_job)
                        self._renumber_queue_locked()
                        remote = self._remote_profile.model_copy(deep=True)
                        workflow = (
                            choose_txt2img_workflow(self._txt2img_workflows, process_job.model)
                            if process_job.operation == GALLERY_REGEN_OPERATION
                            else self._workflow_profile
                        )
                        workflow = workflow.model_copy(deep=True) if workflow else None
                        credentials = self._credentials.model_copy(deep=True)
                        output_root = self.output_root
                        txt2img_workflows = [item.model_copy(deep=True) for item in self._txt2img_workflows]
                        break
                    self._condition.wait()
            if process_job.operation == GALLERY_REGEN_OPERATION:
                self._run_regen(process_job, remote, workflow, credentials, output_root, txt2img_workflows)
            else:
                self._run(process_job, remote, workflow, credentials, output_root)

    def _run(
        self,
        process_job: GalleryProcessJob,
        remote: RemoteProfile,
        workflow: WorkflowProfile,
        credentials: RemoteCredentials,
        output_root: Path,
    ) -> None:
        source = (output_root / process_job.source_path).resolve()
        asset = {
            "path": process_job.source_path,
            "project": process_job.project,
            "model": process_job.model,
            "prompt": process_job.prompt,
            "width": process_job.source_width,
            "height": process_job.source_height,
        }
        job = PromptJob(
            project_name=str(asset.get("project") or source.parent.name or "画廊高清修复"),
            model_profile_id=str(asset.get("model") or "anima_base_v1"),
            positive_prompt=str(asset.get("prompt") or ""),
            generation_params=GenerationParams(
                width=int(asset.get("width") or 0),
                height=int(asset.get("height") or 0),
                seed=-1,
                batch_size=1,
            ),
            workflow_template_id=workflow.id,
            notes=f"画廊 1.5× 高清修复，源图：{asset.get('path', source.name)}",
        )
        repository = SQLiteRepository(self.repository_path)
        repository.save_job(job)

        def on_update(run: GenerationRun) -> None:
            repository.save_generation_run(run)
            with self._lock:
                current = self._jobs.get(process_job.id)
                if current is None:
                    return
                if run.state == GenerationRunState.COMPLETED:
                    current.state = GenerationRunState.DOWNLOADING.value
                    current.message = "正在将结果加入画廊"
                    current.progress = 0.99
                else:
                    current.state = run.state.value
                    current.message = run.status_message or run.state.value
                    current.progress = run.progress
                current.generation_run_id = run.id
                current.remote_prompt_id = run.remote_prompt_id
                current.updated_at = utc_now()
                self._persist_locked(current)

        coordinator = self.coordinator_factory(
            organizer=ResultOrganizer(output_root),
            on_update=on_update,
        )
        try:
            result = coordinator.execute(
                job=job,
                source_path=source,
                source_relative_path=str(asset.get("path") or source.name),
                source_width=int(asset.get("width") or 0),
                source_height=int(asset.get("height") or 0),
                remote_profile=remote,
                workflow_profile=workflow,
                credentials=credentials,
            )
            repository.save_generation_run(result.run)
            for artifact in result.artifacts:
                repository.save_generation_artifact(artifact)
            result_path = ""
            if result.artifacts:
                try:
                    result_path = Path(result.artifacts[0].local_path).resolve().relative_to(output_root.resolve()).as_posix()
                except ValueError:
                    result_path = ""
            with self._lock:
                current = self._jobs.get(process_job.id)
                if current:
                    current.state = "completed"
                    current.message = "1.5× 高清修复完成，结果已加入画廊"
                    current.progress = 1.0
                    current.result_path = result_path
                    current.updated_at = utc_now()
                    self._persist_locked(current)
        except Exception as exc:
            with self._lock:
                current = self._jobs.get(process_job.id)
                if current:
                    current.state = "failed"
                    current.message = "高清修复失败"
                    current.error = str(exc)
                    current.updated_at = utc_now()
                    self._persist_locked(current)
        finally:
            repository.close()

    def _run_regen(
        self,
        process_job: GalleryProcessJob,
        remote: RemoteProfile,
        workflow: WorkflowProfile | None,
        credentials: RemoteCredentials,
        output_root: Path,
        txt2img_workflows: list[WorkflowProfile],
    ) -> None:
        if workflow is None:
            workflow = choose_txt2img_workflow(txt2img_workflows, process_job.model)
        if workflow is None:
            with self._lock:
                current = self._jobs.get(process_job.id)
                if current:
                    current.state = "failed"
                    current.message = "再出图失败"
                    current.error = "没有找到可用的基础文生图工作流。"
                    current.updated_at = utc_now()
                    self._persist_locked(current)
            return
        asset = {
            "path": process_job.source_path,
            "project": process_job.project,
            "model": process_job.model,
            "prompt": process_job.prompt,
            "width": process_job.source_width,
            "height": process_job.source_height,
            "parameters": dict(process_job.parameters),
        }
        try:
            job = build_gallery_regen_job(asset, workflow_id=workflow.id, count=process_job.batch_count)
        except GalleryUpscaleError as exc:
            with self._lock:
                current = self._jobs.get(process_job.id)
                if current:
                    current.state = "failed"
                    current.message = "再出图失败"
                    current.error = str(exc)
                    current.updated_at = utc_now()
                    self._persist_locked(current)
            return
        repository = SQLiteRepository(self.repository_path)
        repository.save_job(job)

        def on_update(run: GenerationRun) -> None:
            repository.save_generation_run(run)
            with self._lock:
                current = self._jobs.get(process_job.id)
                if current is None:
                    return
                if run.state == GenerationRunState.COMPLETED:
                    current.state = GenerationRunState.DOWNLOADING.value
                    current.message = "正在将结果加入画廊"
                    current.progress = 0.99
                else:
                    current.state = run.state.value
                    current.message = run.status_message or run.state.value
                    current.progress = run.progress
                current.generation_run_id = run.id
                current.remote_prompt_id = run.remote_prompt_id
                current.updated_at = utc_now()
                self._persist_locked(current)

        class _TaggedRenderer(WorkflowRenderer):
            def render(self, *args, **kwargs) -> WorkflowRenderResult:
                result = super().render(*args, **kwargs)
                metadata = dict(result.metadata)
                metadata["operation"] = GALLERY_REGEN_OPERATION
                metadata["source_image"] = process_job.source_path
                return WorkflowRenderResult(
                    workflow=result.workflow,
                    resolved_seed=result.resolved_seed,
                    checkpoint_name=result.checkpoint_name,
                    metadata=metadata,
                )

        coordinator = self.regen_coordinator_factory(
            organizer=ResultOrganizer(output_root),
            renderer=_TaggedRenderer(),
            on_update=on_update,
        )
        try:
            checkpoint_logical_name = ConfigService().get_model(
                job.model_profile_id
            ).checkpoint_logical_name
            result = coordinator.execute(
                job,
                remote,
                workflow,
                checkpoint_logical_name,
                credentials,
            )
            repository.save_generation_run(result.run)
            for artifact in result.artifacts:
                repository.save_generation_artifact(artifact)
            result_path = ""
            if result.artifacts:
                try:
                    result_path = Path(result.artifacts[0].local_path).resolve().relative_to(output_root.resolve()).as_posix()
                except ValueError:
                    result_path = ""
            with self._lock:
                current = self._jobs.get(process_job.id)
                if current:
                    current.state = "completed"
                    current.message = f"再出图完成，已加入 {len(result.artifacts)} 张"
                    current.progress = 1.0
                    current.result_path = result_path
                    current.updated_at = utc_now()
                    self._persist_locked(current)
        except (RemoteExecutionError, Exception) as exc:
            with self._lock:
                current = self._jobs.get(process_job.id)
                if current:
                    current.state = "failed"
                    current.message = "再出图失败"
                    current.error = str(exc)
                    current.updated_at = utc_now()
                    self._persist_locked(current)
        finally:
            repository.close()
