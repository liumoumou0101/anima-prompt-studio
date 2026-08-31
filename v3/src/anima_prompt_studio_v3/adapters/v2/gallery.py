from __future__ import annotations

from pathlib import Path
from typing import Any
import os
import subprocess

from anima_prompt_studio.repositories import SQLiteRepository
from anima_prompt_studio.services.gallery_assets import (
    IMAGE_SUFFIXES,
    TRASH_DIR_NAME,
    delete_images_permanently,
    move_images_to_trash,
    resolve_gallery_image,
    resolve_gallery_trash_image,
    restore_images_from_trash,
)
from anima_prompt_studio.services.gallery_index import load_gallery_batches
from anima_prompt_studio.services.gallery_thumbnail import GalleryThumbnailCache
from anima_prompt_studio.services.gallery_thumbnail import gallery_image_dimensions
from anima_prompt_studio.services.gallery_upscale import (
    GalleryUpscaleError,
    GalleryUpscaleManager,
    GalleryUpscaleRenderer,
)
from anima_prompt_studio.domain.execution_models import RemoteAuthType, RemoteCredentials
from anima_prompt_studio.services.remote.credential_store import CredentialStore, CredentialStoreError


class V2GalleryReadService:
    """Expose the V2 gallery index through a UI-independent V3 boundary."""

    def __init__(
        self,
        v2_database: Path,
        output_root: Path,
        *,
        process_manager: GalleryUpscaleManager | None = None,
    ) -> None:
        self.database = Path(v2_database).expanduser().resolve()
        self.output_root = Path(output_root).expanduser().resolve()
        self.thumbnail_cache = GalleryThumbnailCache(self.database.parent / "v3_gallery_thumbnails")
        self.process_manager = process_manager

    @property
    def available(self) -> bool:
        return self.database.is_file()

    def list_assets(self, *, limit: int = 500) -> dict[str, object]:
        repository = SQLiteRepository(self.database)
        try:
            batches = load_gallery_batches(repository, self.output_root, limit=limit)
            states = repository.list_gallery_asset_states(self.output_root)
        finally:
            repository.close()

        assets: list[dict[str, Any]] = []
        for batch in batches:
            for path in batch.image_paths:
                relative = self._relative(path)
                if relative is None:
                    continue
                parameters = dict(batch.parameters) if isinstance(batch.parameters, dict) else {}
                integration = parameters.get("integration_metadata")
                if not isinstance(integration, dict):
                    integration = {}
                candidate = integration.get("candidate")
                candidate = candidate if isinstance(candidate, dict) else {}
                comparison = integration.get("artist_comparison")
                comparison = comparison if isinstance(comparison, dict) else None
                try:
                    stat = path.stat()
                except OSError:
                    continue
                width, height = gallery_image_dimensions(
                    path,
                    _positive_int(parameters.get("width")) or 0,
                    _positive_int(parameters.get("height")) or 0,
                )
                assets.append({
                    "id": relative,
                    "path": relative,
                    "name": path.name,
                    "project": batch.project_name,
                    "model_profile": batch.model_profile_id,
                    "batch_id": batch.run_id,
                    "batch_title": batch.title,
                    "created_at": batch.created_at.isoformat(),
                    "positive_prompt": batch.positive_prompt,
                    "negative_prompt": str(parameters.get("negative_prompt") or ""),
                    "width": width or None,
                    "height": height or None,
                    "byte_size": stat.st_size,
                    "generation_params": _gallery_generation_params(parameters),
                    "source": "external" if batch.run_id.startswith("folder:") else "generated",
                    "state": states.get(relative, ""),
                    "candidate": {
                        "id": str(candidate.get("id") or ""),
                        "lane": str(candidate.get("lane") or ""),
                        "versions": candidate.get("versions") if isinstance(candidate.get("versions"), dict) else {},
                    },
                    "artist_comparison": comparison,
                    "content_url": f"/api/v3/gallery/assets/content?path={_query_value(relative)}",
                    "thumbnail_url": f"/api/v3/gallery/assets/thumbnail?path={_query_value(relative)}&size=640",
                })
        assets.sort(key=lambda item: str(item["created_at"]), reverse=True)
        assets = assets[:limit]
        return {
            "root": str(self.output_root),
            "items": assets,
            "projects": sorted({str(item["project"]) for item in assets}),
            "models": sorted({str(item["model_profile"]) for item in assets if item["model_profile"]}),
            "trash_count": self._trash_count(),
            "processing": self.process_configuration(),
        }

    def resolve_content(self, relative_path: str) -> Path | None:
        return resolve_gallery_image(relative_path, self.output_root)

    def resolve_thumbnail(self, relative_path: str, size: int) -> Path | None:
        source = self.resolve_content(relative_path)
        return self.thumbnail_cache.thumbnail(source, size) if source is not None else None

    def set_state(self, relative_paths: list[str], state: str) -> dict[str, object]:
        valid = self._valid_relative_paths(relative_paths)
        repository = SQLiteRepository(self.database)
        try:
            repository.set_gallery_asset_states(self.output_root, valid, state)
        finally:
            repository.close()
        return {"updated": valid, "state": state}

    def move_to_trash(self, relative_paths: list[str]) -> dict[str, object]:
        requested = list(dict.fromkeys(Path(path).as_posix() for path in relative_paths if path))
        locked = self._locked_process_paths()
        valid: list[tuple[str, Path]] = []
        failed: list[dict[str, str]] = []
        for relative in requested:
            if relative.casefold() in locked:
                failed.append({"path": relative, "error": "图片正在处理或等待处理，不能移入回收站"})
                continue
            resolved = resolve_gallery_image(relative, self.output_root)
            if resolved is None:
                failed.append({"path": relative, "error": "图片不存在、越界或不在画廊中"})
                continue
            valid.append((relative, resolved))
        moved, move_failed = move_images_to_trash([path for _, path in valid], self.output_root)
        moved_originals = {
            relative for relative, source in valid
            if not source.exists() and not any(failed_path.resolve() == source.resolve() for failed_path, _ in move_failed)
        }
        failed.extend({"path": str(path), "error": error} for path, error in move_failed)
        if moved_originals:
            repository = SQLiteRepository(self.database)
            try:
                repository.set_gallery_asset_states(self.output_root, sorted(moved_originals), "")
            finally:
                repository.close()
        return {
            "moved": sorted(moved_originals),
            "trash_paths": sorted(path.relative_to(self.output_root / TRASH_DIR_NAME).as_posix() for path in moved),
            "failed": failed,
        }

    def list_trash(self, *, limit: int = 500) -> dict[str, object]:
        trash_root = self.output_root / TRASH_DIR_NAME
        items: list[dict[str, object]] = []
        if trash_root.is_dir():
            try:
                paths = sorted(
                    (path for path in trash_root.rglob("*") if path.is_file() and path.suffix.casefold() in IMAGE_SUFFIXES),
                    key=lambda path: path.stat().st_mtime,
                    reverse=True,
                )[:limit]
            except OSError:
                paths = []
            for path in paths:
                try:
                    relative = path.resolve().relative_to(trash_root.resolve()).as_posix()
                    parts = Path(relative).parts
                    original = Path(*parts[1:]).as_posix() if len(parts) > 1 else path.name
                    stat = path.stat()
                except (OSError, ValueError):
                    continue
                items.append({
                    "id": relative,
                    "path": relative,
                    "original_path": original,
                    "name": path.name,
                    "byte_size": stat.st_size,
                    "created_at": stat.st_mtime,
                    "content_url": f"/api/v3/gallery/trash/content?path={_query_value(relative)}",
                    "thumbnail_url": f"/api/v3/gallery/trash/thumbnail?path={_query_value(relative)}&size=640",
                })
        return {"items": items, "trash_count": len(items)}

    def restore_from_trash(self, relative_paths: list[str]) -> dict[str, object]:
        requested = list(dict.fromkeys(Path(path).as_posix() for path in relative_paths if path))
        resolved = [
            path for relative in requested
            if (path := resolve_gallery_trash_image(relative, self.output_root)) is not None
        ]
        restored, failed = restore_images_from_trash(resolved, self.output_root)
        return {
            "restored": [path.relative_to(self.output_root).as_posix() for path in restored],
            "failed": [{"path": str(path), "error": error} for path, error in failed],
        }

    def delete_from_trash(self, relative_paths: list[str]) -> dict[str, object]:
        requested = list(dict.fromkeys(Path(path).as_posix() for path in relative_paths if path))
        resolved = [
            path for relative in requested
            if (path := resolve_gallery_trash_image(relative, self.output_root)) is not None
        ]
        deleted, failed = delete_images_permanently(resolved, self.output_root)
        trash_root = self.output_root / TRASH_DIR_NAME
        return {
            "deleted": [path.relative_to(trash_root).as_posix() for path in deleted],
            "failed": [{"path": str(path), "error": error} for path, error in failed],
        }

    def reveal(self, relative_path: str) -> bool:
        """Open the local file manager only for a validated gallery asset."""
        path = self.resolve_content(relative_path)
        if path is None or os.name != "nt":
            return False
        try:
            subprocess.Popen(
                ["explorer.exe", f"/select,{path}"],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            return False
        return True

    def resolve_trash_content(self, relative_path: str) -> Path | None:
        return resolve_gallery_trash_image(relative_path, self.output_root)

    def resolve_trash_thumbnail(self, relative_path: str, size: int) -> Path | None:
        source = self.resolve_trash_content(relative_path)
        return self.thumbnail_cache.thumbnail(source, size) if source is not None else None

    def _valid_relative_paths(self, relative_paths: list[str]) -> list[str]:
        valid: list[str] = []
        for raw in relative_paths:
            path = resolve_gallery_image(raw, self.output_root)
            if path is not None:
                valid.append(path.relative_to(self.output_root).as_posix())
        return sorted(set(valid))

    def _locked_process_paths(self) -> set[str]:
        active_states = {"queued", "starting", "connecting", "preparing", "running", "downloading"}
        repository = SQLiteRepository(self.database)
        try:
            jobs = repository.list_gallery_process_jobs(self.output_root, limit=1000)
        finally:
            repository.close()
        return {
            str(job.get("sourcePath") or "").casefold()
            for job in jobs
            if str(job.get("state") or "") in active_states and job.get("sourcePath")
        }

    def _trash_count(self) -> int:
        trash_root = self.output_root / TRASH_DIR_NAME
        if not trash_root.is_dir():
            return 0
        try:
            return sum(1 for path in trash_root.rglob("*") if path.is_file() and path.suffix.casefold() in IMAGE_SUFFIXES)
        except OSError:
            return 0

    def process_configuration(self) -> dict[str, object]:
        if self.process_manager is None:
            return {
                "available": False,
                "reason": "画廊处理队列尚未配置。",
                "regenAvailable": False,
                "regenReason": "画廊处理队列尚未配置。",
            }
        return self.process_manager.configuration_payload()

    def list_process_jobs(self) -> dict[str, object]:
        return {
            "jobs": self.process_manager.list_jobs() if self.process_manager else [],
            "processing": self.process_configuration(),
        }

    def submit_process(self, relative_paths: list[str], operation: str, count: int = 1) -> dict[str, object]:
        if self.process_manager is None:
            raise GalleryUpscaleError("画廊处理队列尚未配置。")
        indexed = {item["path"]: item for item in self.list_assets(limit=1000)["items"]}
        jobs: list[dict[str, object]] = []
        failed: list[dict[str, str]] = []
        for relative in dict.fromkeys(Path(path).as_posix() for path in relative_paths if path):
            source = resolve_gallery_image(relative, self.output_root)
            item = indexed.get(relative)
            if source is None or item is None:
                failed.append({"path": relative, "error": "画廊中找不到待处理图片"})
                continue
            legacy_asset = {
                "path": relative,
                "project": item["project"],
                "model": item["model_profile"] or "anima_base_v1",
                "prompt": item["positive_prompt"],
                "width": item["width"],
                "height": item["height"],
                "parameters": {},
            }
            try:
                if operation == "regenerate":
                    jobs.append(self.process_manager.submit_regenerate(source, relative, legacy_asset, count))
                elif operation == "upscale":
                    jobs.append(self.process_manager.submit(source, relative, legacy_asset))
                else:
                    raise ValueError("不支持的画廊处理操作。")
            except (GalleryUpscaleError, ValueError) as exc:
                failed.append({"path": relative, "error": str(exc)})
        return {"jobs": jobs, "failed": failed}

    def process_action(self, job_id: str, action: str) -> dict[str, object]:
        if self.process_manager is None:
            raise GalleryUpscaleError("画廊处理队列尚未配置。")
        if action == "cancel":
            return {"job": self.process_manager.cancel(job_id)}
        if action == "retry":
            return {"job": self.process_manager.retry(job_id)}
        if action == "clear_completed":
            return {"cleared": self.process_manager.clear_completed()}
        raise ValueError("不支持的任务操作。")

    def shutdown(self, *, timeout: float = 10.0) -> bool:
        return self.process_manager.shutdown(timeout=timeout) if self.process_manager else True

    def _relative(self, path: Path) -> str | None:
        try:
            resolved = path.resolve()
            resolved.relative_to(self.output_root)
        except (OSError, ValueError):
            return None
        if resolve_gallery_image(resolved.relative_to(self.output_root).as_posix(), self.output_root) is None:
            return None
        return resolved.relative_to(self.output_root).as_posix()


def build_v2_gallery_service(
    v2_database: Path,
    *,
    credential_store: CredentialStore | None = None,
) -> V2GalleryReadService:
    database = Path(v2_database).expanduser().resolve()
    repository = SQLiteRepository(database)
    manager: GalleryUpscaleManager | None = None
    try:
        output_root = Path(repository.get_setting(
            "generation_output_root",
            str(Path.home() / "Pictures" / "AnimaPromptStudio"),
        ))
        profile_id = str(repository.get_setting("last_remote_profile_id", "") or "")
        profiles = repository.list_remote_profiles(enabled_only=True)
        remote_profile = next((item for item in profiles if item.id == profile_id), profiles[0] if profiles else None)
        workflows = repository.list_workflow_profiles()
        upscale_workflow = next((
            item for item in workflows
            if GalleryUpscaleRenderer.supports(item)
            and (item.id.startswith("20_") or item.display_name.startswith("20_") or "Tile_Upscale" in item.display_name)
        ), None)
        txt2img_workflows = [item for item in workflows if item.workflow_kind == "txt2img_basic"]
    finally:
        repository.close()
    manager = GalleryUpscaleManager(database, output_root)
    credentials = RemoteCredentials()
    if remote_profile is not None and remote_profile.auth_type == RemoteAuthType.PASSWORD:
        try:
            password = (credential_store or CredentialStore()).read_password(remote_profile.id)
            credentials = RemoteCredentials(password=password)
        except CredentialStoreError:
            remote_profile = None
    manager.configure(remote_profile, upscale_workflow, credentials, txt2img_workflows=txt2img_workflows)
    return V2GalleryReadService(database, output_root, process_manager=manager)


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _query_value(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


def _gallery_generation_params(parameters: dict[str, Any]) -> dict[str, object]:
    """Return only the display-safe generation controls stored by V2 manifests."""
    nested = parameters.get("generation_params")
    source = nested if isinstance(nested, dict) else parameters
    keys = ("steps", "cfg", "sampler", "scheduler", "seed", "batch_size", "width", "height")
    return {
        key: source[key]
        for key in keys
        if key in source and isinstance(source[key], (str, int, float, bool))
    }
