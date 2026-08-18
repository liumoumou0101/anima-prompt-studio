"""Visual A/B for composition presets, auto recommend, and 换一种构图."""
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

# Same Chinese + seed, only the composition preset changes.
PRESET_ZH = "一个短发女孩站着看向镜头"
PRESET_SEED = 772101
PRESET_IDS = [
    "standard_portrait",
    "portrait_closeup",
    "front_fullbody",
    "low_angle_hero",
    "high_angle",
    "back_view",
    "thirds_left",
    "cinematic_wide",
    "dynamic_action",
]

AUTO_CASES = [
    {
        "id": "auto_run",
        "zh": "一个女孩向右奔跑",
        "expect": "全身侧面，横图，主体偏左",
        "seed": 772201,
    },
    {
        "id": "auto_two",
        "zh": "两个女孩并肩站着说话",
        "expect": "膝上或全身，横图",
        "seed": 772202,
    },
]

ALT_ZH = "一个短发女孩看向镜头微笑"
ALT_SEED = 772301


def log(message: str) -> None:
    print(message, flush=True)


def base_job(zh: str) -> PromptJob:
    job = PromptJob(
        original_zh=zh,
        project_name="构图对照",
        model_profile_id="anima_base_v1",
        generation_preset_id="quality",
        quality_profile_id="standard",
    )
    return job


def composition_summary(job: PromptJob) -> dict:
    c = job.composition
    return {
        "shot": c.shot,
        "camera": c.camera_height,
        "angle": c.angle,
        "gaze": c.gaze,
        "aspect": c.aspect,
        "position": c.subject_position,
        "people": c.people_count,
        "size": [job.generation_params.width, job.generation_params.height],
    }


def build_pipe() -> PromptPipeline:
    resources = ResourceManager()
    translation = TranslationService()
    if marian_runtime_available():
        try:
            translation = TranslationService(
                LazyLocalMarianEngine(resources.model_path("zh_en"), resources.model_path("en_zh"))
            )
        except Exception as exc:
            log(f"MARIAN_FALLBACK {exc}")
    return PromptPipeline(translation=translation)


def generate(coordinator, repo, job, profile, workflow, credentials, seed: int, case_id: str) -> dict:
    job.generation_params.seed = seed
    job.generation_params.batch_size = 1
    repo.save_job(job)
    entry = {
        "id": case_id,
        "zh": job.original_zh,
        "seed": seed,
        "composition": composition_summary(job),
        "prompt": job.positive_prompt,
    }
    try:
        result = coordinator.execute(job, profile, workflow, "anima_base_v1", credentials)
        entry["ok"] = True
        entry["paths"] = [item.local_path for item in result.artifacts]
        log(f"DONE {case_id} {entry['composition']} {entry['paths']}")
    except RemoteExecutionError as exc:
        entry["ok"] = False
        entry["error"] = str(exc)
        log(f"FAIL {case_id} {exc}")
    return entry


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
        pipe = build_pipe()
        log(f"PROFILE {profile.ssh_host} ENGINE {pipe.translation.engine_name}")
        with SshTunnel(profile) as tunnel:
            tunnel.open(credentials)
            stats = ComfyUIClient(tunnel.base_url).validate_environment()
            log(f"COMFY_OK {stats.devices}")

        coordinator = RemoteExecutionCoordinator(
            organizer=ResultOrganizer(Path.home() / "Pictures" / "AnimaPromptStudio"),
            on_update=lambda run: log(f"  {run.state.value} {run.progress:.0%} {run.status_message}"),
        )
        results = []

        for preset_id in PRESET_IDS:
            display = configs.composition_presets[preset_id].display_name
            case_id = f"preset__{preset_id}"
            log(f"START {case_id}")
            job = base_job(PRESET_ZH)
            pipe.compiler.apply_model_defaults(job)
            pipe.translate(job)
            pipe.apply_composition_preset(job, preset_id)
            entry = generate(coordinator, repo, job, profile, workflow, credentials, PRESET_SEED, case_id)
            entry["kind"] = "preset"
            entry["preset_id"] = preset_id
            entry["display_name"] = display
            entry["expect"] = "构图和标准人物档能分开"
            results.append(entry)

        for case in AUTO_CASES:
            log(f"START {case['id']}")
            job = base_job(case["zh"])
            pipe.compiler.apply_model_defaults(job)
            pipe.translate(job)
            entry = generate(coordinator, repo, job, profile, workflow, credentials, case["seed"], case["id"])
            entry["kind"] = "auto"
            entry["expect"] = case["expect"]
            results.append(entry)

        for index in (0, 1, 2):
            case_id = f"alt__{index}"
            log(f"START {case_id}")
            job = base_job(ALT_ZH)
            pipe.compiler.apply_model_defaults(job)
            pipe.translate(job)
            pipe.recommend_composition(job, alternative_index=index)
            fallback = pipe.composition_recommender.last_result.fallback_preset_name
            entry = generate(coordinator, repo, job, profile, workflow, credentials, ALT_SEED, case_id)
            entry["kind"] = "alternative"
            entry["alternative_index"] = index
            entry["fallback_preset"] = fallback
            entry["expect"] = "三次构图能分开，且不是同一张图"
            results.append(entry)

        out = Path("reports") / "composition_visual_cloud.json"
        out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"WROTE {out} count={len(results)}")
        return 0 if all(item.get("ok") for item in results) else 4
    finally:
        repo.close()


if __name__ == "__main__":
    sys.exit(main())
