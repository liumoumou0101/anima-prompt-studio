"""Cloud-check split left/right hand and prop-scope guards."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from anima_prompt_studio.domain.execution_models import RemoteCredentials
from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio.repositories import SQLiteRepository, default_data_dir
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
from anima_prompt_studio.services.translation_service import LazyLocalMarianEngine, TranslationService

CASES = [
    {
        "id": "right_book_left_hang",
        "zh": "一个女孩站着，右手拿着一本合上的书，左手自然垂在身侧，半身",
        "check": "右手一本书，左手空着垂下，不是两本书",
        "seed": 765001,
    },
    {
        "id": "right_skirt_left_hang",
        "zh": "一个女孩站着，右手把自己的裙摆提起来，左手自然垂下，全身",
        "check": "右手掀裙，左手空着垂下",
        "seed": 765002,
    },
    {
        "id": "right_chest_left_hang",
        "zh": "一个裸体女孩站着，右手放在自己的胸口，左手自然垂在身侧，半身",
        "check": "右手在胸，左手空着垂下",
        "seed": 765003,
    },
    {
        "id": "right_mug_left_hang",
        "zh": "一个女孩站着，右手握住白色马克杯的杯柄，左手自然垂下，半身",
        "check": "右手一只杯子，左手空着，不是 marquee",
        "seed": 765004,
    },
    {
        "id": "pour_tea",
        "zh": "一个女孩用右手提起白色茶壶，把茶倒进左手拿着的蓝色杯子里",
        "check": "右手壶，左手蓝杯，中间有水流",
        "seed": 765005,
    },
]


def log(message: str) -> None:
    print(message, flush=True)


def main() -> int:
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
        pipe = PromptPipeline(
            translation=TranslationService(
                LazyLocalMarianEngine(resources.model_path("zh_en"), resources.model_path("en_zh"))
            )
        )
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
        for case in CASES:
            log(f"START {case['id']}")
            job = PromptJob(
                original_zh=case["zh"],
                project_name="左右作用域",
                model_profile_id="anima_base_v1",
                generation_preset_id="quality",
                quality_profile_id="ultimate_general",
            )
            pipe.compiler.apply_model_defaults(job)
            pipe.translate(job)
            job.generation_params.width = 896
            job.generation_params.height = 1152
            job.generation_params.seed = case["seed"]
            job.generation_params.batch_size = 1
            repo.save_job(job)
            try:
                result = coordinator.execute(job, profile, workflow, "anima_base_v1", credentials)
                paths = [item.local_path for item in result.artifacts]
                log(f"DONE {case['id']} {paths}")
                results.append({**case, "ok": True, "en": job.translated_en, "prompt": job.positive_prompt, "paths": paths})
            except RemoteExecutionError as exc:
                log(f"FAIL {case['id']} {exc}")
                results.append({**case, "ok": False, "error": str(exc), "en": job.translated_en, "prompt": job.positive_prompt})
        out = Path("reports") / "hand_scope_cloud.json"
        out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"WROTE {out}")
        return 0 if all(item.get("ok") for item in results) else 4
    finally:
        repo.close()


if __name__ == "__main__":
    sys.exit(main())
