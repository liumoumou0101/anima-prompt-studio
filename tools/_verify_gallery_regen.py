"""End-to-end check: gallery same-prompt regen against the saved cloud profile."""
from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from anima_prompt_studio.domain.execution_models import RemoteCredentials
from anima_prompt_studio.repositories import SQLiteRepository, default_data_dir
from anima_prompt_studio.services.gallery_index import load_gallery_batches
from anima_prompt_studio.services.gallery_upscale import (
    GALLERY_REGEN_OPERATION,
    GalleryUpscaleManager,
    choose_txt2img_workflow,
)
from anima_prompt_studio.services.remote.comfy_client import ComfyUIClient
from anima_prompt_studio.services.remote.credential_store import CredentialStore
from anima_prompt_studio.services.remote.ssh_tunnel import SshTunnel


COUNT = 2
REPORT_PATH = Path("reports") / "gallery_same_prompt_regen_verify.json"


def log(message: str) -> None:
    print(message, flush=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_size(path: Path) -> tuple[int, int]:
    from PySide6.QtGui import QImageReader

    reader = QImageReader(str(path))
    size = reader.size()
    return int(size.width()), int(size.height())


def pick_source(batches):
    preferred = []
    fallback = []
    for batch in batches:
        if not batch.positive_prompt or not batch.image_paths:
            continue
        width = int((batch.parameters or {}).get("width") or 0)
        height = int((batch.parameters or {}).get("height") or 0)
        item = (batch, batch.image_paths[0], width, height)
        if "再出图" in batch.project_name:
            continue
        if "校服" in (batch.positive_prompt + batch.project_name) or "school" in batch.positive_prompt:
            preferred.append(item)
        else:
            fallback.append(item)
    chosen = (preferred or fallback)
    if not chosen:
        raise SystemExit("NO_SOURCE_IMAGE")
    return chosen[0]


def main() -> int:
    repo = SQLiteRepository(default_data_dir() / "anima_prompt_studio.db")
    checks: list[dict] = []
    result: dict = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "ok": False,
        "checks": checks,
    }
    try:
        profile_id = repo.get_setting("last_remote_profile_id", "")
        if not profile_id:
            log("NO_PROFILE")
            return 2
        profile = repo.get_remote_profile(profile_id)
        password = CredentialStore().read_password(profile.id)
        if not password:
            log("NO_PASSWORD")
            return 3
        credentials = RemoteCredentials(password=password)
        workflows = [
            item
            for item in repo.list_workflow_profiles()
            if item.workflow_kind == "txt2img_basic"
        ]
        workflow = choose_txt2img_workflow(workflows, "anima_base_v1")
        output_root = Path(
            repo.get_setting("generation_output_root", str(Path.home() / "Pictures" / "AnimaPromptStudio"))
        )
        log(f"PROFILE {profile.display_name} {profile.ssh_host}:{profile.ssh_port}")
        log(f"WORKFLOW {workflow.display_name if workflow else None}")
        log(f"OUTPUT {output_root}")

        log("CONNECTING")
        tunnel = SshTunnel(profile)
        with tunnel:
            tunnel.open(credentials)
            client = ComfyUIClient(tunnel.base_url)
            stats = client.validate_environment()
            devices = ", ".join(stats.devices) or "?"
            log(f"COMFY_OK devices={devices} queue={stats.queue_running}+{stats.queue_pending}")
            result["devices"] = list(stats.devices)
            result["queue"] = {"running": stats.queue_running, "pending": stats.queue_pending}
            gpu_ok = any("3080" in name for name in stats.devices)
            checks.append({"id": "gpu_is_3080_class", "ok": gpu_ok, "devices": list(stats.devices)})
            if not gpu_ok:
                log(f"WARN GPU_NOT_3080 {devices}")

        batches = load_gallery_batches(repo, output_root, limit=80)
        batch, source, width, height = pick_source(batches)
        if width <= 0 or height <= 0:
            width, height = image_size(source)
        relative = source.resolve().relative_to(output_root.resolve()).as_posix()
        original_hash = sha256_file(source)
        original_mtime = source.stat().st_mtime
        prompt = batch.positive_prompt
        log(f"SOURCE {relative}")
        log(f"SOURCE_SIZE {width}x{height} hash={original_hash[:12]}")
        log(f"PROMPT {prompt[:160]}")
        result["source"] = {
            "path": relative,
            "project": batch.project_name,
            "model": batch.model_profile_id,
            "width": width,
            "height": height,
            "prompt": prompt,
            "hash": original_hash,
        }

        manager = GalleryUpscaleManager(repo.db_path, output_root)
        manager.configure(profile, None, credentials, txt2img_workflows=workflows)
        payload = manager.configuration_payload()
        regen_available = bool(payload.get("regenAvailable"))
        checks.append({
            "id": "regen_available",
            "ok": regen_available,
            "reason": payload.get("regenReason", ""),
            "workflow": payload.get("regenWorkflowName", ""),
        })
        log(f"REGEN_AVAILABLE {regen_available} {payload.get('regenWorkflowName')} {payload.get('regenReason')}")
        if not regen_available:
            result["error"] = payload.get("regenReason") or "regen unavailable"
            return 4

        submitted = manager.submit_regenerate(
            source,
            relative,
            {
                "path": relative,
                "project": batch.project_name,
                "model": batch.model_profile_id or "anima_base_v1",
                "prompt": prompt,
                "width": width,
                "height": height,
                "parameters": batch.parameters,
            },
            count=COUNT,
        )
        log(f"QUEUED {submitted['id']} op={submitted['operation']} batch={submitted['batchCount']}")
        checks.append({
            "id": "queued_as_regen",
            "ok": submitted["operation"] == GALLERY_REGEN_OPERATION and submitted["batchCount"] == COUNT,
            "job": {k: submitted[k] for k in ("id", "operation", "batchCount", "sourceWidth", "sourceHeight", "workflowName")},
        })

        deadline = time.monotonic() + 900
        last_state = ""
        while time.monotonic() < deadline:
            job = manager.get(submitted["id"])
            state = f"{job['state']} {job.get('progress', 0):.0%} {job.get('message', '')}"
            if state != last_state:
                log(f"  {state}")
                last_state = state
            if job["state"] in {"completed", "failed", "canceled"}:
                break
            time.sleep(2)
        else:
            log("TIMEOUT")
            result["error"] = "timeout waiting for regen"
            return 5

        job = manager.get(submitted["id"])
        result["job"] = job
        completed = job["state"] == "completed"
        checks.append({
            "id": "job_completed",
            "ok": completed,
            "state": job["state"],
            "message": job.get("message"),
            "error": job.get("error"),
            "resultPath": job.get("resultPath"),
        })
        if not completed:
            log(f"FAIL {job.get('error') or job.get('message')}")
            return 6

        still_exists = source.is_file()
        same_hash = still_exists and sha256_file(source) == original_hash
        same_mtime = still_exists and source.stat().st_mtime == original_mtime
        checks.append({
            "id": "original_not_overwritten",
            "ok": still_exists and same_hash,
            "exists": still_exists,
            "same_hash": same_hash,
            "same_mtime": same_mtime,
        })
        log(f"ORIGINAL kept={still_exists} same_hash={same_hash} same_mtime={same_mtime}")

        result_path = job.get("resultPath") or ""
        result_file = (output_root / result_path).resolve() if result_path else None
        new_images: list[Path] = []
        if result_file and result_file.is_file():
            new_images = sorted(
                path for path in result_file.parent.iterdir()
                if path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp"}
            )
        checks.append({
            "id": "new_images_written",
            "ok": len(new_images) >= COUNT,
            "count": len(new_images),
            "paths": [str(path) for path in new_images],
            "result_dir": str(result_file.parent) if result_file else "",
        })
        log(f"NEW_IMAGES {len(new_images)}")
        for path in new_images:
            log(f"  {path}")

        size_ok = True
        sizes = []
        for path in new_images:
            got_w, got_h = image_size(path)
            sizes.append({"path": path.name, "width": got_w, "height": got_h})
            if (got_w, got_h) != (width, height):
                size_ok = False
        checks.append({
            "id": "same_size",
            "ok": bool(new_images) and size_ok,
            "expected": [width, height],
            "actual": sizes,
        })
        log(f"SIZE expected={width}x{height} actual={sizes}")

        different_from_source = all(sha256_file(path) != original_hash for path in new_images)
        checks.append({
            "id": "results_are_new_files",
            "ok": bool(new_images) and different_from_source and all(path.resolve() != source.resolve() for path in new_images),
        })

        # Confirm the gallery indexer can see the regen batch and prompt.
        refreshed = load_gallery_batches(repo, output_root, limit=20)
        regen_batches = [
            item for item in refreshed
            if "再出图" in item.project_name and item.positive_prompt == prompt
        ]
        checks.append({
            "id": "gallery_indexes_regen",
            "ok": bool(regen_batches),
            "projects": [item.project_name for item in regen_batches[:3]],
            "image_count": sum(len(item.image_paths) for item in regen_batches),
        })
        log(f"GALLERY_REGEN_BATCHES {len(regen_batches)}")

        result["ok"] = all(item["ok"] for item in checks)
        return 0 if result["ok"] else 7
    except Exception as exc:
        log(f"ERROR {type(exc).__name__}: {exc}")
        result["error"] = f"{type(exc).__name__}: {exc}"
        return 8
    finally:
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"WROTE {REPORT_PATH}")
        repo.close()


if __name__ == "__main__":
    sys.exit(main())
