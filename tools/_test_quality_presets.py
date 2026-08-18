"""A/B the quality packs: same scene and seed, only the quality profile changes."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from anima_prompt_studio.domain.execution_models import RemoteCredentials
from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio.repositories import SQLiteRepository, default_data_dir
from anima_prompt_studio.services.config_service import ConfigService
from anima_prompt_studio.services.pipeline import PromptPipeline
from anima_prompt_studio.services.remote.comfy_client import ComfyUIClient
from anima_prompt_studio.services.remote.credential_store import CredentialStore
from anima_prompt_studio.services.remote.execution_coordinator import (
    RemoteExecutionCoordinator,
    RemoteExecutionError,
)
from anima_prompt_studio.services.remote.result_organizer import ResultOrganizer
from anima_prompt_studio.services.remote.ssh_tunnel import SshTunnel
from anima_prompt_studio.services.resource_manager import ResourceManager
from anima_prompt_studio.services.translation_service import (
    LazyLocalMarianEngine,
    TranslationService,
    marian_runtime_available,
)

# Round 4: new indoor-warm and overcast-rain packs.
SCENES = [
    {
        "id": "room",
        "zh": "一个长发女孩坐在房间里，半身",
        "expect": "室内暖灯比标准档更像普通室内灯光",
        "profiles": ["standard", "indoor_warm"],
        "seed": 771001,
    },
    {
        "id": "alley",
        "zh": "一个短发女孩站在小巷里，半身",
        "expect": "阴雨雾气比标准档更阴、更湿",
        "profiles": ["standard", "overcast_rain"],
        "seed": 771101,
    },
]


def log(message: str) -> None:
    print(message, flush=True)


def compile_case(pipe: PromptPipeline, zh: str, quality_id: str, locked_en: str = "") -> PromptJob:
    job = PromptJob(
        original_zh=zh,
        project_name="质量预设对照",
        model_profile_id="anima_base_v1",
        generation_preset_id="quality",
        quality_profile_id=quality_id,
    )
    pipe.compiler.apply_model_defaults(job)
    pipe.translate(job)
    if locked_en:
        pipe.update_english(job, locked_en)
    return job


def quality_tags_of(job: PromptJob) -> list[str]:
    return PromptPipeline().compiler.effective_quality_tags(job)


def main() -> int:
    configs = ConfigService()
    repo = SQLiteRepository(default_data_dir() / "anima_prompt_studio.db")
    try:
        profile = repo.get_remote_profile(repo.get_setting("last_remote_profile_id", ""))
        workflow = repo.get_workflow_profile("01___Base_Quality_T2I")
        password = CredentialStore().read_password(profile.id)
        if not password:
            log("NO_PASSWORD")
            return 3
        credentials = RemoteCredentials(password=password)
        resources = ResourceManager()
        translation = TranslationService()
        if marian_runtime_available():
            try:
                translation = TranslationService(
                    LazyLocalMarianEngine(resources.model_path("zh_en"), resources.model_path("en_zh"))
                )
            except Exception as exc:
                log(f"MARIAN_FALLBACK {exc}")
        pipe = PromptPipeline(translation=translation)
        log(f"PROFILE {profile.ssh_host} ENGINE {pipe.translation.engine_name}")
        with SshTunnel(profile) as tunnel:
            tunnel.open(credentials)
            stats = ComfyUIClient(tunnel.base_url).validate_environment()
            log(f"COMFY_OK {stats.devices}")

        organizer = ResultOrganizer(Path.home() / "Pictures" / "AnimaPromptStudio")
        coordinator = RemoteExecutionCoordinator(
            organizer=organizer,
            on_update=lambda run: log(f"  {run.state.value} {run.progress:.0%} {run.status_message}"),
        )
        results = []
        for scene in SCENES:
            for quality_id in scene["profiles"]:
                display = configs.quality_profiles[quality_id].display_name
                case_id = f"{scene['id']}__{quality_id}"
                log(f"START {case_id}")
                job = compile_case(pipe, scene["zh"], quality_id, scene.get("locked_en", ""))
                injected = quality_tags_of(job)
                job.generation_params.width = 896
                job.generation_params.height = 1152
                job.generation_params.seed = scene["seed"]
                job.generation_params.batch_size = 1
                repo.save_job(job)
                entry = {
                    "id": case_id,
                    "scene": scene["id"],
                    "quality_id": quality_id,
                    "display_name": display,
                    "expect": scene["expect"],
                    "zh": scene["zh"],
                    "seed": scene["seed"],
                    "injected": injected,
                    "prompt": job.positive_prompt,
                }
                try:
                    result = coordinator.execute(job, profile, workflow, "anima_base_v1", credentials)
                    entry["ok"] = True
                    entry["paths"] = [item.local_path for item in result.artifacts]
                    log(f"DONE {case_id} {entry['paths']}")
                except RemoteExecutionError as exc:
                    entry["ok"] = False
                    entry["error"] = str(exc)
                    log(f"FAIL {case_id} {exc}")
                results.append(entry)
        out = Path("reports") / "quality_preset_cloud_round4.json"
        out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"WROTE {out} count={len(results)}")
        return 0 if all(item.get("ok") for item in results) else 4
    finally:
        repo.close()


if __name__ == "__main__":
    sys.exit(main())
