"""Connect to the saved cloud profile and generate a few action-relation checks."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from anima_prompt_studio.domain.execution_models import RemoteCredentials
from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio.repositories import SQLiteRepository, default_data_dir
from anima_prompt_studio.services.pipeline import PromptPipeline
from anima_prompt_studio.services.remote.credential_store import CredentialStore
from anima_prompt_studio.services.remote.execution_coordinator import (
    RemoteExecutionCoordinator,
    RemoteExecutionError,
)
from anima_prompt_studio.services.remote.result_organizer import ResultOrganizer
from anima_prompt_studio.services.remote.ssh_tunnel import SshTunnel
from anima_prompt_studio.services.remote.comfy_client import ComfyUIClient
from anima_prompt_studio.services.resource_manager import ResourceManager
from anima_prompt_studio.services.translation_service import (
    LazyLocalMarianEngine,
    TranslationService,
)

CASES = [
    {
        "id": "cowgirl",
        "family": "体位",
        "zh": "一个裸体女孩女上位骑在男孩身上，全身",
        "check": "女上位，两人，不是后入",
        "seed": 764001,
    },
    {
        "id": "doggy",
        "family": "体位",
        "zh": "后入式，男孩从背后进入裸体女孩，全身",
        "check": "后入，从背后，不是面对面",
        "seed": 764002,
    },
    {
        "id": "missionary_spread",
        "family": "体位+视线",
        "zh": "一对男女在床上做爱，男上位，女孩张开双腿看着镜头，全身",
        "check": "男上位，张腿，看镜头，hetero",
        "seed": 764003,
    },
    {
        "id": "yuri_sex",
        "family": "双人",
        "zh": "两个裸体女孩在做爱，没有男孩，全身",
        "check": "两个女孩，不是 hetero",
        "seed": 764004,
    },
    {
        "id": "oral_kneel",
        "family": "动作+视线",
        "zh": "一个裸体女孩跪着做口交，抬头看镜头，嘴巴微张，全身",
        "check": "跪+口交+抬头看镜头",
        "seed": 764005,
    },
    {
        "id": "ahegao",
        "family": "表情",
        "zh": "一个高潮中的裸体女孩露出阿嘿颜，舌头伸出，眼睛上翻，半身",
        "check": "阿嘿颜，不是普通微笑",
        "seed": 764006,
    },
    {
        "id": "bound_blindfold",
        "family": "束缚",
        "zh": "一个裸体女孩被绳子捆绑坐在椅子上，眼睛被布蒙住，全身",
        "check": "绳缚+蒙眼+坐椅",
        "seed": 764007,
    },
    {
        "id": "right_skirt_lift",
        "family": "左右手",
        "zh": "一个女孩站着，右手把自己的裙摆提起来，左手自然垂下，全身",
        "check": "右手掀裙，左手垂下，不是双手掀",
        "seed": 764008,
    },
    {
        "id": "upskirt",
        "family": "服装状态",
        "zh": "从低处拍摄一个穿着短裙的女孩走光裙底，全身",
        "check": "裙底视角，不是普通站姿",
        "seed": 764009,
    },
    {
        "id": "nude_look_away",
        "family": "否定+视线",
        "zh": "一个裸体女孩站在浴室里，看向画外，没有看镜头，全身",
        "check": "裸体，看画外，不是对视",
        "seed": 764010,
    },
    {
        "id": "spread_not_sex",
        "family": "否定",
        "zh": "一个裸体女孩独自躺在床上张开双腿，没有和其他人做爱，全身",
        "check": "单人张腿，不要第二个人",
        "seed": 764011,
    },
    {
        "id": "clothed_not_nude",
        "family": "否定",
        "zh": "一个女孩穿着完整的校服站着，没有裸体，全身",
        "check": "校服完整，不是裸",
        "seed": 764012,
    },
    {
        "id": "reverse_cowgirl",
        "family": "体位",
        "zh": "一个裸体女孩反骑乘，背对男孩坐在他身上，全身",
        "check": "反骑乘背对，不是正面女上位",
        "seed": 764013,
    },
    {
        "id": "right_chest_left_hang",
        "family": "左右手",
        "zh": "一个裸体女孩站着，右手放在自己的胸口，左手自然垂在身侧，半身",
        "check": "右手在胸，左手垂下",
        "seed": 764014,
    },
]


def log(message: str) -> None:
    print(message, flush=True)


def main() -> int:
    repo = SQLiteRepository(default_data_dir() / "anima_prompt_studio.db")
    try:
        profile_id = repo.get_setting("last_remote_profile_id", "")
        if not profile_id:
            log("NO_PROFILE")
            return 2
        profile = repo.get_remote_profile(profile_id)
        workflow = repo.get_workflow_profile("01___Base_Quality_T2I")
        password = CredentialStore().read_password(profile.id)
        if not password:
            log("NO_PASSWORD")
            return 3
        credentials = RemoteCredentials(password=password)
        log(f"PROFILE {profile.display_name} {profile.ssh_host}:{profile.ssh_port}")
        log(f"WORKFLOW {workflow.display_name} kind={workflow.workflow_kind}")

        log("CONNECTING")
        tunnel = SshTunnel(profile)
        with tunnel:
            tunnel.open(credentials)
            client = ComfyUIClient(tunnel.base_url)
            stats = client.validate_environment()
            log(f"COMFY_OK queue={getattr(stats, 'queue_running', '?')}+{getattr(stats, 'queue_pending', '?')}")

        resources = ResourceManager()
        if not resources.models_available():
            log("NO_MARIAN_MODELS")
            return 5
        pipe = PromptPipeline(
            translation=TranslationService(
                LazyLocalMarianEngine(resources.model_path("zh_en"), resources.model_path("en_zh"))
            )
        )
        log(f"ENGINE {pipe.translation.engine_name}")
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
                project_name="动作验证NSFW",
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
                result = coordinator.execute(
                    job,
                    profile,
                    workflow,
                    "anima_base_v1",
                    credentials,
                )
                paths = [item.local_path for item in result.artifacts]
                log(f"DONE {case['id']} {paths}")
                results.append({
                    "id": case["id"],
                    "family": case.get("family", ""),
                    "check": case.get("check", ""),
                    "ok": True,
                    "zh": case["zh"],
                    "en": job.translated_en,
                    "slots": job.semantic_frame.visual_slots,
                    "tags": [item.tag for item in job.matched_tags],
                    "prompt": job.positive_prompt,
                    "paths": paths,
                    "seed": case["seed"],
                })
            except RemoteExecutionError as exc:
                log(f"FAIL {case['id']} {exc}")
                results.append({
                    "id": case["id"],
                    "ok": False,
                    "zh": case["zh"],
                    "error": str(exc),
                    "en": job.translated_en,
                    "slots": job.semantic_frame.visual_slots,
                    "prompt": job.positive_prompt,
                })
        out = Path("reports") / "action_scene_wave_nsfw.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"WROTE {out}")
        return 0 if all(item.get("ok") for item in results) else 4
    finally:
        repo.close()


if __name__ == "__main__":
    sys.exit(main())
