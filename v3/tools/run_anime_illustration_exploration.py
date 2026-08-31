"""Generate five polished anime-illustration directions through the V3 main path.

The script is a local compile-only dry run unless ``--execute`` is passed. Each
remote job uses ANIMA Aesthetic v1.1, one scene-appropriate artist from the
traceable recommendation pool, an explicit fixed seed, and one output image.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import socket
import sys
import time
import traceback

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
for source in (ROOT / "v3" / "src", ROOT / "src"):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from anima_prompt_studio.domain.execution_models import GenerationRunState
from anima_prompt_studio.repositories import SQLiteRepository, default_data_dir
from anima_prompt_studio_v3.adapters.v2 import (
    build_v2_generation_queue,
    build_v2_local_translation_adapter,
)
from anima_prompt_studio_v3.api import create_api_runtime
from anima_prompt_studio_v3.data import DataPackManager


MODEL_PROFILE = "anima_aesthetic_v1"
WORKFLOW_ID = "22___Aesthetic_v1.1"
POLL_SECONDS = 2.0
EXCLUDED_TEXT = "文字、水印、签名、对话框、漫画分镜、multiple girls、monochrome"
TERMINAL_STATES = {
    GenerationRunState.COMPLETED,
    GenerationRunState.FAILED,
    GenerationRunState.CANCELED,
}

CASES = (
    {
        "id": "01_sakura_shrine_twilight",
        "title": "樱暮神社",
        "seed": 8273001,
        "width": 832,
        "height": 1216,
        "artist": "mocha_(cotton)",
        "source_text": "一名成年巫女，黑色长发，金色眼睛，神社石阶，樱花，黄昏逆光，回眸，全身，风和云海。",
        "translated_text": (
            "A polished Japanese anime illustration of an adult shrine maiden with long black hair "
            "and golden eyes, looking back on stone steps at a mountain shrine. Sunset backlight "
            "passes through drifting cherry blossoms while wind lifts her hair and wide sleeves; "
            "a gold and violet sea of clouds fills the distance. Elegant full-body composition."
        ),
        "selected_tags": [
            "1girl", "solo", "miko", "hakama_skirt", "long_hair", "black_hair",
            "golden_eyes", "looking_back", "full_body", "standing", "shrine",
            "cherry_blossoms", "sunset", "backlighting", "wind", "cloud", "depth_of_field",
        ],
    },
    {
        "id": "02_neon_rain_city",
        "title": "雨夜霓虹",
        "seed": 8273002,
        "width": 832,
        "height": 1216,
        "artist": "gemi",
        "source_text": "一名成年女性，白色短发，蓝色眼睛，透明雨伞，雨夜都市，霓虹灯，积水倒影，半身，散景。",
        "translated_text": (
            "A refined anime city illustration of an adult woman with short white hair and blue eyes, "
            "standing alone beneath a transparent umbrella at a rainy night intersection and glancing "
            "toward the viewer. Violet and cyan neon reflects in puddles and on her wet coat; distant "
            "traffic becomes soft bokeh, with cool ambience and a warm edge light. Cinematic thigh-up shot."
        ),
        "selected_tags": [
            "1girl", "solo", "short_hair", "white_hair", "blue_eyes", "looking_at_viewer",
            "upper_body", "rain", "night", "city_lights", "neon_lights", "umbrella",
            "holding_umbrella", "reflection", "wet_clothes", "bokeh", "backlighting",
        ],
    },
    {
        "id": "03_astral_ice_mage",
        "title": "星空冰术",
        "seed": 8273003,
        "width": 832,
        "height": 1216,
        "artist": "vinartwork",
        "source_text": "一名成年冰系法师，白色长发，紫色眼睛，水晶长杖，冰晶，魔法阵，星空，单人全身。",
        "translated_text": (
            "A premium Japanese fantasy game illustration of an adult ice mage with long white hair "
            "and violet eyes, holding a crystal staff among floating ice shards and a luminous magic "
            "circle. Blue-violet energy spirals upward beneath a deep starry sky, lifting her hair, "
            "translucent sleeves, and layered dress. A clear, ornate full-body character key visual."
        ),
        "selected_tags": [
            "1girl", "solo", "long_hair", "white_hair", "purple_eyes", "full_body",
            "standing", "dress", "staff", "holding_staff", "ice", "magic_circle",
            "starry_sky", "floating_hair", "dynamic_pose", "glowing", "sparkles", "light_particles",
        ],
    },
    {
        "id": "04_underwater_library",
        "title": "深海书库",
        "seed": 8273004,
        "width": 1216,
        "height": 832,
        "artist": "makoron117117",
        "source_text": "一名成年女性，蓝色长发，蓝色眼睛，白裙，水下图书馆，水母，书架，单人横向广角。",
        "translated_text": (
            "An exquisite dreamlike anime scene of an adult woman with long blue hair and blue eyes "
            "floating in a light white dress inside an ancient library submerged beneath the sea. "
            "Glowing jellyfish drift between towering bookshelves while open pages and bubbles rise; "
            "caustic light illuminates her profile. Serene, ethereal, detailed wide composition."
        ),
        "selected_tags": [
            "1girl", "solo", "long_hair", "blue_hair", "blue_eyes", "dress", "underwater",
            "library", "jellyfish", "blue_theme", "floating_hair", "wide_shot", "scenery",
            "glowing", "light_particles", "reflection",
        ],
    },
    {
        "id": "05_snow_lantern_kimono",
        "title": "雪夜灯影",
        "seed": 8273005,
        "width": 832,
        "height": 1216,
        "artist": "pochi_(poti1990)",
        "source_text": "一名成年女性，黑色长发，金色眼睛，深蓝和服，纸灯笼，雪夜小巷，单人全身。",
        "translated_text": (
            "A polished Japanese-style anime illustration of an adult woman with long black hair and "
            "golden eyes, wearing a deep navy kimono with delicate gold floral patterns. She carries a "
            "warm paper lantern with both hands in a snowy stone alley at night, turning gently toward "
            "the viewer as snow gathers on her hair and sleeves. Elegant full-body cool-warm lighting."
        ),
        "selected_tags": [
            "1girl", "solo", "long_hair", "black_hair", "golden_eyes", "looking_at_viewer",
            "full_body", "standing", "kimono", "snow", "snowing", "lantern", "night",
            "bokeh", "depth_of_field", "backlighting",
        ],
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="submit five real remote jobs")
    parser.add_argument("--suffix", default="", help="optional safe report/idempotency suffix")
    return parser.parse_args()


def response_or_raise(response, stage: str) -> dict[str, object]:
    if response.status_code not in {200, 202}:
        raise RuntimeError(f"{stage} failed ({response.status_code}): {response.text}")
    return response.json()


def selected_remote_profile(database: Path):
    repository = SQLiteRepository(database)
    try:
        profile_id = repository.get_setting("last_remote_profile_id", "")
        return profile_id, repository.get_remote_profile(profile_id) if profile_id else None
    finally:
        repository.close()


def ssh_banner_available(host: str, port: int, *, timeout: float = 8.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout) as connection:
            connection.settimeout(timeout)
            return connection.recv(80).startswith(b"SSH-")
    except OSError:
        return False


def copy_artifacts(queue, report_dir: Path, run_id: str, label: str) -> list[str]:
    artifacts = []
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        artifacts = queue.artifacts(run_id)
        if artifacts:
            break
        time.sleep(0.1)
    copied: list[str] = []
    for index, artifact in enumerate(artifacts, start=1):
        source = Path(artifact.local_path)
        if not source.is_file():
            continue
        target = report_dir / f"{label}_{index}{source.suffix or '.png'}"
        shutil.copy2(source, target)
        copied.append(str(target))
    return copied


def main() -> int:
    args = parse_args()
    suffix_value = re.sub(r"[^A-Za-z0-9_-]+", "", args.suffix)
    suffix = f"-{suffix_value}" if suffix_value else ""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = ROOT / "reports" / f"v3_anime_illustration_exploration_{timestamp}{suffix.replace('-', '_')}"
    report_path = report_dir / "report.json"
    report_dir.mkdir(parents=True, exist_ok=False)
    report: dict[str, object] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "five polished anime illustration directions through the V3 main path",
        "model_profile": MODEL_PROFILE,
        "workflow": WORKFLOW_ID,
        "excluded_text": EXCLUDED_TEXT,
        "execute": args.execute,
        "cases": {},
        "results": [],
        "errors": [],
    }

    def save() -> None:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    save()
    v2_database = default_data_dir() / "anima_prompt_studio.db"
    queue = build_v2_generation_queue(v2_database) if args.execute else None
    try:
        reference_db = DataPackManager(ROOT / "v3" / ".local" / "data").active_reference_db()
        translator = build_v2_local_translation_adapter(v2_database)
        runtime = create_api_runtime(
            reference_db,
            generation_queue=queue,
            translation_service=translator,
        )
        client = TestClient(runtime.app, base_url="http://127.0.0.1", raise_server_exceptions=False)
        exchange = response_or_raise(
            client.post(
                "/api/v3/session/exchange",
                json={"bootstrap_token": runtime.bootstrap_token},
                headers={"Origin": "http://127.0.0.1"},
            ),
            "session exchange",
        )
        headers = {
            "X-Anima-Session": str(exchange["session_token"]),
            "Origin": "http://127.0.0.1",
        }

        prepared_cases: list[tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]] = []
        for case in CASES:
            case_id = str(case["id"])
            print(f"COMPILE {case_id}", flush=True)
            generated = response_or_raise(
                client.post(
                    "/api/v3/local-natural/candidates",
                    json={
                        "source_text": case["source_text"],
                        "excluded_text": EXCLUDED_TEXT,
                        "translated_text": case["translated_text"],
                        "selected_tags": case["selected_tags"],
                        "model_profile": MODEL_PROFILE,
                    },
                    headers=headers,
                ),
                f"compile {case_id}",
            )
            candidate = next(
                (item for item in generated["candidates"] if item["lane"] == "hybrid"),
                generated["candidates"][0],
            )
            suggestions = list(generated["artist_suggestions"])
            artist = next((item for item in suggestions if item["name"] == case["artist"]), None)
            if artist is None:
                available = ", ".join(str(item["name"]) for item in suggestions)
                raise RuntimeError(
                    f"{case_id} 的目标画师 {case['artist']} 不在当前前端推荐池：{available}"
                )
            rendered_positive = f"{candidate['positive_prompt']}, {artist['render_name']}"
            entry = {
                "title": case["title"],
                "seed": case["seed"],
                "size": [case["width"], case["height"]],
                "source_text": case["source_text"],
                "translated_text": case["translated_text"],
                "selected_tags": case["selected_tags"],
                "candidate_lane": candidate["lane"],
                "positive_prompt": rendered_positive,
                "negative_prompt": candidate["negative_prompt"],
                "artist": artist,
                "validation": generated["validation"],
                "scene_draft": generated["scene_draft"],
            }
            report["cases"][case_id] = entry
            prepared_cases.append((case, generated, candidate, artist))
            save()
            print(f"READY {case_id} artist={artist['render_name']} lane={candidate['lane']}", flush=True)

        if not args.execute:
            report["finished_at"] = datetime.now(timezone.utc).isoformat()
            report["summary"] = {"compiled": len(prepared_cases), "submitted": 0, "completed": 0}
            save()
            print(f"DRY_RUN_REPORT {report_path}", flush=True)
            return 0

        remote_profile_id, remote_profile = selected_remote_profile(v2_database)
        if not remote_profile_id or remote_profile is None:
            raise RuntimeError("没有已选择的 V2 云主机配置。")
        if not ssh_banner_available(remote_profile.ssh_host, remote_profile.ssh_port):
            raise RuntimeError("当前远端端点没有返回 SSH banner。")
        report["preflight"] = {"ssh_banner": True}

        pending: dict[str, str] = {}
        for position, (case, generated, candidate, artist) in enumerate(prepared_cases, start=1):
            case_id = str(case["id"])
            comparison_id = f"comparison_anime_{case_id}_{suffix_value or timestamp}"
            payload = {
                "candidate": candidate,
                "intent": generated["intent"],
                "project_name": f"V3 精致二次元探索 · {case['title']}",
                "settings": {
                    "preset_id": "balanced",
                    "width": case["width"],
                    "height": case["height"],
                    "seed": case["seed"],
                    "batch_size": 1,
                },
                "comparison_id": comparison_id,
                "artist_names": [artist["name"]],
                "remote_profile_id": remote_profile_id,
                "workflow_profile_id": WORKFLOW_ID,
            }
            print(f"SUBMIT {case_id}", flush=True)
            submitted = response_or_raise(
                client.post(
                    "/api/v3/artist-comparisons",
                    json=payload,
                    headers={
                        **headers,
                        "Idempotency-Key": f"v3-anime-exploration-{case_id}-{case['seed']}{suffix}",
                    },
                ),
                f"submit {case_id}",
            )
            run = submitted["submitted"][0]["run"]
            report["cases"][case_id]["submitted"] = submitted
            pending[str(run["id"])] = case_id
            save()

        previous: dict[str, tuple[str, str]] = {}
        started = time.monotonic()
        while pending:
            for run_id, case_id in list(pending.items()):
                run = queue.get(run_id)
                state = run.state.value
                status = run.status_message
                snapshot = (state, status)
                if previous.get(run_id) != snapshot:
                    print(f"RUN {case_id} {state} {status}", flush=True)
                    previous[run_id] = snapshot
                if run.state not in TERMINAL_STATES:
                    continue
                result: dict[str, object] = {
                    "case": case_id,
                    "run_id": run.id,
                    "state": state,
                    "elapsed_s": round(time.monotonic() - started, 1),
                    "status_message": status,
                    "error_code": run.error_code,
                    "error_message": run.error_message,
                    "resolved_seed": run.request_json.get("resolved_seed"),
                }
                if run.state == GenerationRunState.COMPLETED:
                    result["image_paths"] = copy_artifacts(queue, report_dir, run_id, case_id)
                report["results"].append(result)
                pending.pop(run_id)
                save()
            if pending:
                time.sleep(POLL_SECONDS)
    except Exception as exc:
        report["errors"].append({"error": str(exc), "traceback": traceback.format_exc()})
        save()
        print(f"TEST_FAIL {exc}", flush=True)
        return 1
    finally:
        if queue is not None:
            queue.shutdown(cancel_active=False, timeout=20.0)

    completed = sum(1 for item in report["results"] if item["state"] == "completed")
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["summary"] = {
        "compiled": len(prepared_cases),
        "submitted": len(prepared_cases),
        "completed": completed,
        "failed": len(prepared_cases) - completed,
    }
    save()
    print(f"REPORT {report_path}", flush=True)
    return 0 if completed == len(prepared_cases) else 2


if __name__ == "__main__":
    raise SystemExit(main())
