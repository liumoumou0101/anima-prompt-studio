"""Run the final four-image V3 ANIMA Aesthetic acceptance probe.

The command is dry-run by default. Pass ``--execute`` to submit four remote
jobs. No credential is printed or persisted; the existing V2 credential-store
integration supplies the selected remote profile's secret.

The matrix isolates two questions with fixed seeds:

1. Literal tags versus a user-confirmed ``wearing`` Hybrid phrase.
2. One artist-positive prompt with and without the generic ``artist name``
   negative token.
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
SOURCE_TEXT = "博丽灵梦穿女仆装，站在神社前"
TRANSLATED_TEXT = "Hakurei Reimu wears a maid outfit and stands in front of a shrine"
WIDTH = 1024
HEIGHT = 1024
POLL_SECONDS = 2.0
TERMINAL_STATES = {
    GenerationRunState.COMPLETED,
    GenerationRunState.FAILED,
    GenerationRunState.CANCELED,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="submit the four real remote generation jobs (default: print plan only)",
    )
    parser.add_argument("--relation-seed", type=int, default=8270830)
    parser.add_argument("--artist-seed", type=int, default=8270831)
    parser.add_argument(
        "--artist",
        default="",
        help="canonical artist name from the returned recommendation pool; default: first recommendation",
    )
    parser.add_argument(
        "--suffix",
        default="",
        help="optional report/idempotency suffix containing letters, digits, dash, or underscore",
    )
    return parser.parse_args()


def remove_negative_token(prompt: str, token: str) -> str:
    parts = [item.strip() for item in prompt.split(",")]
    return ", ".join(item for item in parts if item and item.casefold() != token.casefold())


def response_or_raise(response, stage: str) -> dict[str, object]:
    if response.status_code not in {200, 202}:
        raise RuntimeError(f"{stage} failed ({response.status_code}): {response.text}")
    return response.json()


def copy_artifacts(queue, report_dir: Path, run_id: str, label: str) -> list[str]:
    artifacts = []
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        artifacts = queue.artifacts(run_id)
        if artifacts:
            break
        time.sleep(0.1)
    copied: list[str] = []
    safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("_") or "image"
    for index, artifact in enumerate(artifacts, start=1):
        source = Path(artifact.local_path)
        if not source.is_file():
            continue
        target = report_dir / f"{safe_label}_{index}{source.suffix or '.png'}"
        shutil.copy2(source, target)
        copied.append(str(target))
    return copied


def selected_remote_profile(database: Path):
    repository = SQLiteRepository(database)
    try:
        profile_id = repository.get_setting("last_remote_profile_id", "")
        return profile_id, repository.get_remote_profile(profile_id) if profile_id else None
    finally:
        repository.close()


def ssh_banner_available(host: str, port: int, *, timeout: float = 8.0) -> bool:
    """Check that the configured TCP endpoint actually speaks SSH."""

    try:
        with socket.create_connection((host, port), timeout=timeout) as connection:
            connection.settimeout(timeout)
            return connection.recv(80).startswith(b"SSH-")
    except OSError:
        return False


def submit(
    client: TestClient,
    headers: dict[str, str],
    *,
    candidate: dict[str, object],
    intent: dict[str, object],
    seed: int,
    label: str,
    remote_profile_id: str,
    suffix: str,
) -> dict[str, object]:
    payload = {
        "candidate": candidate,
        "intent": intent,
        "project_name": "V3 收尾固定 Seed 验收",
        "settings": {
            "preset_id": "balanced",
            "width": WIDTH,
            "height": HEIGHT,
            "seed": seed,
            "batch_size": 1,
        },
        "remote_profile_id": remote_profile_id,
        "workflow_profile_id": WORKFLOW_ID,
    }
    return response_or_raise(
        client.post(
            "/api/v3/generation-runs",
            json=payload,
            headers={**headers, "Idempotency-Key": f"v3-finish-{label}-{seed}{suffix}"},
        ),
        f"submit {label}",
    )


def main() -> int:
    args = parse_args()
    suffix_value = re.sub(r"[^A-Za-z0-9_-]+", "", args.suffix)
    suffix = f"-{suffix_value}" if suffix_value else ""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_dir = ROOT / "reports" / f"v3_finish_image_smoke_{timestamp}{suffix.replace('-', '_')}"
    plan = {
        "model_profile": MODEL_PROFILE,
        "workflow": WORKFLOW_ID,
        "source_text": SOURCE_TEXT,
        "size": [WIDTH, HEIGHT],
        "jobs": [
            {"label": "relation_literal", "seed": args.relation_seed},
            {"label": "relation_hybrid", "seed": args.relation_seed},
            {"label": "artist_negative_default", "seed": args.artist_seed},
            {"label": "artist_negative_without_artist_name", "seed": args.artist_seed},
        ],
    }
    print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
    if not args.execute:
        print("DRY_RUN: add --execute to submit four remote jobs", flush=True)
        return 0

    report_dir.mkdir(parents=True, exist_ok=False)
    report_path = report_dir / "report.json"
    report: dict[str, object] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "V3 final fixed-seed relation and artist-negative acceptance",
        "plan": plan,
        "candidate": {},
        "selected_artist": {},
        "submitted": [],
        "results": [],
        "errors": [],
    }

    def save() -> None:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    save()
    v2_database = default_data_dir() / "anima_prompt_studio.db"
    remote_profile_id, remote_profile = selected_remote_profile(v2_database)
    if not remote_profile_id or remote_profile is None:
        report["errors"].append({"error": "没有已选择的 V2 云主机配置。"})
        save()
        print("TEST_FAIL 没有已选择的 V2 云主机配置。", flush=True)
        return 1
    if not ssh_banner_available(remote_profile.ssh_host, remote_profile.ssh_port):
        message = "当前远端端点没有返回 SSH banner；请启动实例或刷新 SSH 地址/端口后重试。"
        report["preflight"] = {"ssh_banner": False}
        report["errors"].append({"error": message})
        save()
        print(f"TEST_FAIL {message}", flush=True)
        return 1
    report["preflight"] = {"ssh_banner": True}
    save()

    queue = build_v2_generation_queue(v2_database)
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
        base_request = {
            "source_text": SOURCE_TEXT,
            "translated_text": TRANSLATED_TEXT,
            "model_profile": MODEL_PROFILE,
        }
        first = response_or_raise(
            client.post("/api/v3/local-natural/candidates", json=base_request, headers=headers),
            "initial local candidate",
        )
        entities = first["scene_draft"]["entities"]
        if not entities:
            raise RuntimeError("场景未识别出实体，无法进行 wearing 关系验收。")
        entity = entities[0]
        maid = next(
            item for item in first["scene_draft"]["confirmed"] if item.get("canonical_tag") == "maid"
        )
        ownership = {str(maid["id"]): str(entity["id"])}
        confirmed = response_or_raise(
            client.post(
                "/api/v3/local-natural/candidates",
                json={
                    **base_request,
                    "fact_owners": ownership,
                    "confirmed_relations": [{
                        "source_entity_id": entity["id"],
                        "target_element_id": maid["id"],
                        "relation": "wearing",
                    }],
                },
                headers=headers,
            ),
            "confirmed relation candidate",
        )
        literal = next(item for item in confirmed["candidates"] if item["lane"] == "literal")
        hybrid = next(item for item in confirmed["candidates"] if item["lane"] == "hybrid")
        recommendations = list(confirmed["artist_suggestions"])
        if not recommendations:
            raise RuntimeError("当前候选没有画师推荐，无法进行画师负向词验收。")
        requested_artist = args.artist.strip().lower().replace(" ", "_")
        artist = next(
            (item for item in recommendations if item["name"] == requested_artist),
            recommendations[0] if not requested_artist else None,
        )
        if artist is None:
            raise RuntimeError(f"指定画师不在当前推荐池：{requested_artist}")
        source_element_ids = list(literal["preserved_element_ids"])
        if not source_element_ids:
            source_element_ids = [confirmed["intent"]["graph"]["elements"][0]["id"]]
        artist_record = {
            "name": artist["name"],
            "rendered": artist["render_name"],
            "source": "artist",
            "source_element_ids": source_element_ids,
            "reason": f"收尾固定 Seed 验收；匹配标签：{', '.join(artist['sources'])}",
            "raw_score": artist["raw_score"],
            "display_score": artist["display_score"],
            "data_pack_id": artist["data_pack_id"],
            "algorithm_version": artist["algorithm_version"],
            "removable": True,
        }
        artist_candidate = {
            **literal,
            "id": "candidate_finish_artist_negative_default",
            "lane": "artist",
            "title": f"画师负向词验收 · {artist['render_name']}",
            "positive_prompt": f"{literal['positive_prompt']}, {artist['render_name']}",
            "artists": [artist_record],
        }
        artist_without_negative = {
            **artist_candidate,
            "id": "candidate_finish_artist_negative_removed",
            "negative_prompt": remove_negative_token(str(literal["negative_prompt"]), "artist name"),
        }
        if artist_without_negative["negative_prompt"] == artist_candidate["negative_prompt"]:
            raise RuntimeError("Aesthetic 默认负向词中没有 artist name，测试矩阵失去变量。")

        report["candidate"] = {
            "scene_draft": confirmed["scene_draft"],
            "literal": literal,
            "hybrid": hybrid,
        }
        report["selected_artist"] = artist
        save()

        jobs = [
            ("relation_literal", literal, confirmed["intent"], args.relation_seed),
            ("relation_hybrid", hybrid, confirmed["intent"], args.relation_seed),
            ("artist_negative_default", artist_candidate, confirmed["intent"], args.artist_seed),
            (
                "artist_negative_without_artist_name",
                artist_without_negative,
                confirmed["intent"],
                args.artist_seed,
            ),
        ]
        pending: dict[str, str] = {}
        for label, candidate, intent, seed in jobs:
            print(f"SUBMIT {label}", flush=True)
            run = submit(
                client,
                headers,
                candidate=candidate,
                intent=intent,
                seed=seed,
                label=label,
                remote_profile_id=remote_profile_id,
                suffix=suffix,
            )
            report["submitted"].append({"label": label, "run": run})
            pending[str(run["id"])] = label
            save()

        previous: dict[str, tuple[str, str]] = {}
        started = time.monotonic()
        while pending:
            for run_id, label in list(pending.items()):
                run = queue.get(run_id)
                state = run.state.value
                status = run.status_message
                snapshot = (state, status)
                if previous.get(run_id) != snapshot:
                    print(f"RUN {label} {state} {status}", flush=True)
                    previous[run_id] = snapshot
                if run.state not in TERMINAL_STATES:
                    continue
                entry: dict[str, object] = {
                    "label": label,
                    "run_id": run.id,
                    "state": state,
                    "elapsed_s": round(time.monotonic() - started, 1),
                    "status_message": status,
                    "error_code": run.error_code,
                    "error_message": run.error_message,
                    "resolved_seed": run.request_json.get("resolved_seed"),
                }
                if run.state == GenerationRunState.COMPLETED:
                    entry["image_paths"] = copy_artifacts(queue, report_dir, run_id, label)
                report["results"].append(entry)
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
        queue.shutdown(cancel_active=False, timeout=20.0)

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    completed = sum(
        1 for item in report["results"] if item.get("state") == GenerationRunState.COMPLETED.value
    )
    report["summary"] = {
        "requested": len(plan["jobs"]),
        "completed": completed,
        "failed": len(plan["jobs"]) - completed,
    }
    save()
    print(f"REPORT {report_path}", flush=True)
    return 0 if completed == len(plan["jobs"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
