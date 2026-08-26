"""Exercise V3 gallery regeneration and 1.5x upscale on a real ComfyUI host."""
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

from anima_prompt_studio.domain.execution_models import RemoteAuthType, RemoteCredentials, RemoteProfile
from anima_prompt_studio.repositories import SQLiteRepository, default_data_dir
from anima_prompt_studio.services.gallery_upscale import GalleryUpscaleManager
from anima_prompt_studio_v3.adapters.v2 import V2GalleryReadService


def wait_for_job(manager: GalleryUpscaleManager, job_id: str, timeout: float) -> dict:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        job = manager.get(job_id)
        if job is None:
            raise RuntimeError("Gallery job disappeared.")
        print(f"{job['operation']} {job['state']} {job['progress']:.2f} {job['message']}", flush=True)
        if job["state"] in {"completed", "failed", "canceled"}:
            return job
        sleep(2)
    raise TimeoutError(f"Gallery job timed out: {job_id}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument("--user", default="root")
    parser.add_argument("--fingerprint", required=True)
    parser.add_argument("--output-root", type=Path, default=ROOT / "reports" / "v3_remote_acceptance")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args(argv)
    password = getpass("SSH password (memory only): ")
    if not password:
        raise RuntimeError("SSH password is empty.")

    output_root = args.output_root.resolve()
    database = output_root / "gallery-smoke.db"
    local_repository = SQLiteRepository(default_data_dir() / "anima_prompt_studio.db")
    try:
        base_workflow = local_repository.get_workflow_profile("01___Base_Quality_T2I")
        upscale_workflow = local_repository.get_workflow_profile("20___Tile_Upscale")
    finally:
        local_repository.close()
    SQLiteRepository(database).close()

    profile = RemoteProfile(
        id="v3-gallery-acceptance-ephemeral",
        provider_preset_id="compshare_container",
        display_name="V3 gallery acceptance (ephemeral)",
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
    manager = GalleryUpscaleManager(database, output_root)
    manager.configure(profile, upscale_workflow, credentials, txt2img_workflows=[base_workflow])
    service = V2GalleryReadService(database, output_root, process_manager=manager)
    report: dict[str, object] = {"status": "starting", "jobs": []}
    report_path = output_root / "gallery-acceptance-report.json"
    try:
        assets = service.list_assets(limit=100)["items"]
        source = next((item for item in assets if "seed8264090" in item["name"]), None)
        if source is None:
            raise RuntimeError("The base acceptance image was not found in the V3 gallery.")

        regen_submit = service.submit_process([source["path"]], "regenerate", 1)
        if regen_submit["failed"] or not regen_submit["jobs"]:
            raise RuntimeError(f"Regeneration was rejected: {regen_submit['failed']}")
        regen = wait_for_job(manager, regen_submit["jobs"][0]["id"], args.timeout)
        report["jobs"].append(regen)
        if regen["state"] != "completed":
            raise RuntimeError(f"Regeneration failed: {regen['error']}")

        upscale_submit = service.submit_process([source["path"]], "upscale", 1)
        if upscale_submit["failed"] or not upscale_submit["jobs"]:
            raise RuntimeError(f"Upscale was rejected: {upscale_submit['failed']}")
        upscale = wait_for_job(manager, upscale_submit["jobs"][0]["id"], args.timeout)
        report["jobs"].append(upscale)
        if upscale["state"] != "completed":
            raise RuntimeError(f"Upscale failed: {upscale['error']}")

        refreshed = service.list_assets(limit=100)["items"]
        report.update({
            "status": "completed",
            "source": source["path"],
            "asset_count_before": len(assets),
            "asset_count_after": len(refreshed),
            "result_paths": [regen["resultPath"], upscale["resultPath"]],
        })
        return 0
    finally:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        credentials.password = ""
        password = ""
        manager.shutdown(timeout=15)
        print(f"REPORT {report_path}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
