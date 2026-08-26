"""Run a one-shot V3 API -> V2 queue -> real ComfyUI acceptance test.

The SSH password is read interactively and is never persisted or included in
the JSON report. This tool intentionally creates only local report artifacts.
"""
from __future__ import annotations

import argparse
from getpass import getpass
import json
from pathlib import Path
import sys
from time import monotonic, sleep


ROOT = Path(__file__).resolve().parents[1]
for source in (ROOT / "v3" / "src", ROOT / "src"):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from fastapi.testclient import TestClient

from anima_prompt_studio.domain.execution_models import RemoteAuthType, RemoteCredentials, RemoteProfile
from anima_prompt_studio.repositories import SQLiteRepository, default_data_dir
from anima_prompt_studio.services.remote.execution_coordinator import RemoteExecutionCoordinator
from anima_prompt_studio.services.remote.result_organizer import ResultOrganizer
from anima_prompt_studio_v3.adapters.v2 import V2GenerationQueueService, V2GenerationTarget
from anima_prompt_studio_v3.api import create_api_runtime
from anima_prompt_studio_v3.data import DataPackManager


ORIGIN = "http://127.0.0.1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the real V3 remote-generation acceptance test.")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--user", default="root")
    parser.add_argument("--fingerprint", required=True)
    parser.add_argument("--workflow-id", default="01___Base_Quality_T2I")
    parser.add_argument("--reference-data-root", type=Path, default=ROOT / "v3" / ".local" / "data")
    parser.add_argument("--output-root", type=Path, default=ROOT / "reports" / "v3_remote_acceptance")
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args(argv)

    password = getpass("SSH password (memory only): ")
    if not password:
        raise RuntimeError("SSH password is empty.")

    reference_db = DataPackManager(args.reference_data_root.resolve()).active_reference_db()
    repository = SQLiteRepository(default_data_dir() / "anima_prompt_studio.db")
    try:
        workflow = repository.get_workflow_profile(args.workflow_id)
    finally:
        repository.close()

    profile = RemoteProfile(
        id="v3-real-acceptance-ephemeral",
        provider_preset_id="compshare_container",
        display_name="V3 real acceptance (ephemeral)",
        ssh_host=args.host,
        ssh_port=args.port,
        ssh_user=args.user,
        auth_type=RemoteAuthType.PASSWORD,
        known_host_fingerprint=args.fingerprint,
        comfy_host="127.0.0.1",
        comfy_port=8188,
        model_aliases={"anima_base_v1": "anima-base-v1.0.safetensors"},
    )
    credentials = RemoteCredentials(password=password)
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    def resolve(_remote_profile_id: str, _workflow_profile_id: str) -> V2GenerationTarget:
        return V2GenerationTarget(
            remote_profile=profile,
            workflow_profile=workflow,
            credentials=credentials,
            output_root=output_root,
        )

    queue = V2GenerationQueueService(
        resolve,
        coordinator_factory=lambda root, on_update: RemoteExecutionCoordinator(
            organizer=ResultOrganizer(root),
            on_update=on_update,
            poll_interval=1.0,
        ),
        target_lister=lambda: [{
            "remote_profile_id": profile.id,
            "remote_display_name": profile.display_name,
            "workflow_profile_id": workflow.id,
            "workflow_display_name": workflow.display_name,
            "workflow_kind": workflow.workflow_kind,
            "compatible_model_profiles": list(workflow.compatible_model_profiles),
            "host_fingerprint_ready": True,
            "auth_type": "password",
            "private_key_passphrase_configured": False,
        }],
    )
    report: dict[str, object] = {
        "host": args.host,
        "gpu_expected": "RTX 4090",
        "workflow": workflow.display_name,
        "status": "starting",
    }
    report_path = output_root / "acceptance-report.json"
    try:
        runtime = create_api_runtime(reference_db, generation_queue=queue)
        client = TestClient(runtime.app, base_url=ORIGIN, raise_server_exceptions=False)
        exchanged = client.post(
            "/api/v3/session/exchange",
            json={"bootstrap_token": runtime.bootstrap_token},
            headers={"Origin": ORIGIN},
        )
        exchanged.raise_for_status()
        session = exchanged.json()["session_token"]
        headers = {"Origin": ORIGIN, "X-Anima-Session": session}
        generated = client.post(
            "/api/v3/workbench/candidates",
            json={
                "source_text": "雨夜里，一名白发红眼女性撑伞独自站立，不看镜头；不要文字和水印",
                "source_language": "zh",
                "model_profile": "anima_base_v1",
                "elements": [
                    {"id": "e_subject", "text": "一个女孩", "canonical_tag": "1girl", "state": "locked"},
                    {"id": "e_solo", "text": "独自", "canonical_tag": "solo"},
                    {"id": "e_hair", "text": "白发", "canonical_tag": "white_hair"},
                    {"id": "e_eyes", "text": "红眼", "canonical_tag": "red_eyes"},
                    {"id": "e_rain", "text": "下雨", "canonical_tag": "rain"},
                    {"id": "e_umbrella", "text": "雨伞", "canonical_tag": "umbrella"},
                    {"id": "e_night", "text": "夜晚", "canonical_tag": "night"},
                    {"id": "e_away", "text": "不看镜头", "canonical_tag": "looking_away"},
                    {"id": "e_text", "text": "文字", "canonical_tag": "text", "state": "excluded"},
                    {"id": "e_watermark", "text": "水印", "canonical_tag": "watermark", "state": "excluded"},
                ],
            },
            headers=headers,
        )
        generated.raise_for_status()
        candidate_payload = generated.json()
        candidate = candidate_payload["candidates"][0]
        submitted = client.post(
            "/api/v3/generation-runs",
            json={
                "candidate": candidate,
                "intent": candidate_payload["intent"],
                "project_name": "V3 4090 real acceptance",
                "settings": {"preset_id": "balanced", "width": 640, "height": 640, "seed": 8264090, "batch_size": 1},
                "remote_profile_id": profile.id,
                "workflow_profile_id": workflow.id,
            },
            headers={**headers, "Idempotency-Key": "v3-real-4090-8264090"},
        )
        submitted.raise_for_status()
        run_id = submitted.json()["id"]
        deadline = monotonic() + args.timeout
        status = submitted.json()
        while monotonic() < deadline:
            status_response = client.get(
                f"/api/v3/generation-runs/{run_id}",
                headers={"X-Anima-Session": session},
            )
            status_response.raise_for_status()
            status = status_response.json()
            print(f"STATE {status['state']} {status['progress']:.2f} {status['status_message']}", flush=True)
            if status["state"] in {"completed", "failed", "canceled", "remote_missing"}:
                break
            sleep(2.0)
        artifacts = queue.artifacts(run_id)
        report.update({
            "status": status["state"],
            "run_id": run_id,
            "candidate_id": candidate["id"],
            "candidate_lane": candidate["lane"],
            "positive_prompt": candidate["positive_prompt"],
            "negative_prompt": candidate["negative_prompt"],
            "artifact_paths": [item.local_path for item in artifacts],
            "artifact_sha256": [item.sha256 for item in artifacts],
            "error": status.get("error"),
        })
        return 0 if status["state"] == "completed" and artifacts else 2
    finally:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        credentials.password = ""
        password = ""
        queue.shutdown(cancel_active=True, timeout=10.0)
        print(f"REPORT {report_path}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
