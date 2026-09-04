from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import RLock
from typing import Any
import os
import subprocess

from anima_prompt_studio.repositories import SQLiteRepository
from anima_prompt_studio.services.gallery_assets import (
    IMAGE_SUFFIXES,
    TRASH_DIR_NAME,
    delete_gallery_images_permanently,
    delete_images_permanently,
    move_images_to_trash,
    resolve_gallery_image,
    resolve_gallery_trash_image,
    restore_images_from_trash,
)
from anima_prompt_studio.services.gallery_index import GalleryBatch, _batch_from_manifest, load_gallery_batches
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
        self._index_path = self.database.with_name(f"{self.database.stem}.gallery-index-v1.json")
        self._index_lock = RLock()
        self._cached_filesystem: dict[str, dict[str, int]] | None = None
        self._cached_payload = self._load_cached_payload()

    @property
    def available(self) -> bool:
        return self.database.is_file()

    def list_assets(
        self,
        *,
        limit: int = 500,
        refresh: bool = False,
        rebuild: bool = False,
    ) -> dict[str, object]:
        """Return a cached gallery snapshot and rebuild it only when requested.

        The web client renders the last good snapshot immediately, then asks for a
        refresh in the background.  This keeps route changes and application
        restarts from blocking on a complete Windows filesystem walk.
        """
        with self._index_lock:
            if self._cached_payload is None or rebuild:
                self._cached_payload = self._build_assets(limit=1000)
                self._cached_filesystem = self._scan_filesystem()
                self._write_cached_payload(self._cached_payload)
            elif refresh:
                self._cached_payload = self._refresh_assets(limit=1000)
                self._write_cached_payload(self._cached_payload)
            return self._slice_cached_payload(self._cached_payload, limit)

    def _build_assets(self, *, limit: int) -> dict[str, object]:
        repository = SQLiteRepository(self.database)
        try:
            batches = load_gallery_batches(repository, self.output_root, limit=limit)
            states = repository.list_gallery_asset_states(self.output_root)
        finally:
            repository.close()

        assets: list[dict[str, Any]] = []
        for batch in batches:
            for path in batch.image_paths:
                asset = self._asset_from_batch(batch, path, states)
                if asset is not None:
                    assets.append(asset)
        assets.sort(key=lambda item: str(item["created_at"]), reverse=True)
        assets = assets[:limit]
        return self._payload(assets)

    def _refresh_assets(self, *, limit: int) -> dict[str, object]:
        current_filesystem = self._scan_filesystem()
        if self._cached_filesystem is None:
            payload = self._build_assets(limit=limit)
            self._cached_filesystem = current_filesystem
            return payload

        old_filesystem = self._cached_filesystem
        changed_paths = {
            relative
            for relative in old_filesystem.keys() | current_filesystem.keys()
            if old_filesystem.get(relative) != current_filesystem.get(relative)
        }
        repository = SQLiteRepository(self.database)
        try:
            states = repository.list_gallery_asset_states(self.output_root)
        finally:
            repository.close()

        if not changed_paths:
            assets = [
                {**item, "state": states.get(str(item.get("path") or ""), "")}
                for item in self._cached_payload.get("items", [])
            ]
        else:
            changed_folders = {_parent_key(relative) for relative in changed_paths}
            assets = [
                {**item, "state": states.get(str(item.get("path") or ""), "")}
                for item in self._cached_payload.get("items", [])
                if str(item.get("path") or "") in current_filesystem
                and _parent_key(str(item.get("path") or "")) not in changed_folders
            ]
            for folder_key in changed_folders:
                assets.extend(self._rebuild_folder_assets(folder_key, current_filesystem, states))

        assets.sort(key=lambda item: str(item["created_at"]), reverse=True)
        self._cached_filesystem = current_filesystem
        return self._payload(assets[:limit])

    def _asset_from_batch(
        self,
        batch: GalleryBatch,
        path: Path,
        states: dict[str, str],
    ) -> dict[str, Any] | None:
        relative = self._relative(path)
        if relative is None:
            return None
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
            return None
        width, height = gallery_image_dimensions(
            path,
            _positive_int(parameters.get("width")) or 0,
            _positive_int(parameters.get("height")) or 0,
        )
        return {
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
        }

    def _rebuild_folder_assets(
        self,
        folder_key: str,
        filesystem: dict[str, dict[str, int]],
        states: dict[str, str],
    ) -> list[dict[str, Any]]:
        folder = self.output_root if folder_key == "." else self.output_root.joinpath(*Path(folder_key).parts)
        image_paths = [
            self.output_root.joinpath(*Path(relative).parts)
            for relative in filesystem
            if _parent_key(relative) == folder_key
        ]
        indexed: list[dict[str, Any]] = []
        tracked: set[str] = set()
        manifest = folder / "manifest.json"
        if manifest.is_file():
            batch = _batch_from_manifest(manifest, self.output_root)
            if batch is not None:
                for path in batch.image_paths:
                    asset = self._asset_from_batch(batch, path, states)
                    if asset is not None:
                        indexed.append(asset)
                        tracked.add(str(asset["path"]))

        extras = [path for path in image_paths if self._relative(path) not in tracked]
        if extras:
            try:
                relative_folder = folder.relative_to(self.output_root)
                project = relative_folder.parts[0] if relative_folder.parts else "未分类"
                model = next((part for part in relative_folder.parts if part.startswith("anima_")), "")
                created = datetime.fromtimestamp(max(path.stat().st_mtime for path in extras)).astimezone()
            except (OSError, ValueError):
                return indexed
            batch = GalleryBatch(
                run_id="folder:" + str(folder.resolve()),
                output_dir=folder,
                created_at=created,
                project_name=project,
                model_profile_id=model,
                image_paths=extras,
            )
            for path in extras:
                asset = self._asset_from_batch(batch, path, states)
                if asset is not None:
                    indexed.append(asset)
        return indexed

    def _scan_filesystem(self) -> dict[str, dict[str, int]]:
        signatures: dict[str, dict[str, int]] = {}
        if not self.output_root.is_dir():
            return signatures
        for folder_name, directory_names, file_names in os.walk(self.output_root):
            directory_names[:] = [name for name in directory_names if name != TRASH_DIR_NAME]
            folder = Path(folder_name)
            manifest_mtime = 0
            manifest_size = 0
            if "manifest.json" in file_names:
                try:
                    manifest_stat = (folder / "manifest.json").stat()
                    manifest_mtime = manifest_stat.st_mtime_ns
                    manifest_size = manifest_stat.st_size
                except OSError:
                    pass
            for name in file_names:
                if Path(name).suffix.casefold() not in IMAGE_SUFFIXES:
                    continue
                path = folder / name
                try:
                    stat = path.stat()
                    relative = path.relative_to(self.output_root).as_posix()
                except (OSError, ValueError):
                    continue
                signatures[relative] = {
                    "mtime_ns": stat.st_mtime_ns,
                    "size": stat.st_size,
                    "manifest_mtime_ns": manifest_mtime,
                    "manifest_size": manifest_size,
                }
        return signatures

    def _payload(self, assets: list[dict[str, Any]]) -> dict[str, object]:
        return {
            "root": str(self.output_root),
            "items": assets,
            "projects": sorted({str(item["project"]) for item in assets}),
            "models": sorted({str(item["model_profile"]) for item in assets if item["model_profile"]}),
            "trash_count": self._trash_count(),
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }

    def _slice_cached_payload(self, payload: dict[str, object], limit: int) -> dict[str, object]:
        result = deepcopy(payload)
        items = result.get("items")
        if isinstance(items, list):
            result["items"] = items[:limit]
            result["projects"] = sorted({str(item["project"]) for item in result["items"]})
            result["models"] = sorted({str(item["model_profile"]) for item in result["items"] if item.get("model_profile")})
        result["processing"] = self.process_configuration()
        return result

    def _load_cached_payload(self) -> dict[str, object] | None:
        try:
            envelope = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if (
            not isinstance(envelope, dict)
            or envelope.get("schema") != 2
            or envelope.get("database") != str(self.database)
            or envelope.get("output_root") != str(self.output_root)
            or not isinstance(envelope.get("payload"), dict)
            or not isinstance(envelope["payload"].get("items"), list)
            or not isinstance(envelope.get("filesystem"), dict)
        ):
            return None
        filesystem = envelope["filesystem"]
        if not all(isinstance(path, str) and isinstance(signature, dict) for path, signature in filesystem.items()):
            return None
        self._cached_filesystem = filesystem
        return envelope["payload"]

    def _write_cached_payload(self, payload: dict[str, object]) -> None:
        envelope = {
            "schema": 2,
            "database": str(self.database),
            "output_root": str(self.output_root),
            "payload": payload,
            "filesystem": self._cached_filesystem or {},
        }
        temporary = self._index_path.with_suffix(self._index_path.suffix + ".tmp")
        try:
            temporary.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self._index_path)
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _update_cached_payload(self, update: Callable[[dict[str, object]], None]) -> None:
        with self._index_lock:
            if self._cached_payload is None:
                return
            update(self._cached_payload)
            items = self._cached_payload.get("items")
            if isinstance(items, list):
                self._cached_payload["projects"] = sorted({str(item["project"]) for item in items})
                self._cached_payload["models"] = sorted({str(item["model_profile"]) for item in items if item.get("model_profile")})
            self._cached_payload["indexed_at"] = datetime.now(timezone.utc).isoformat()
            self._write_cached_payload(self._cached_payload)

    def _invalidate_cached_payload(self) -> None:
        with self._index_lock:
            self._cached_payload = None
            self._cached_filesystem = None
            try:
                self._index_path.unlink(missing_ok=True)
            except OSError:
                pass

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
        valid_set = set(valid)

        def update_states(payload: dict[str, object]) -> None:
            for item in payload.get("items", []):
                if item.get("path") in valid_set:
                    item["state"] = state

        self._update_cached_payload(update_states)
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
            moved_set = set(moved_originals)

            def remove_moved(payload: dict[str, object]) -> None:
                payload["items"] = [item for item in payload.get("items", []) if item.get("path") not in moved_set]
                payload["trash_count"] = int(payload.get("trash_count") or 0) + len(moved_set)
                if self._cached_filesystem is not None:
                    for relative in moved_set:
                        self._cached_filesystem.pop(relative, None)

            self._update_cached_payload(remove_moved)
        return {
            "moved": sorted(moved_originals),
            "trash_paths": sorted(path.relative_to(self.output_root / TRASH_DIR_NAME).as_posix() for path in moved),
            "failed": failed,
        }

    def delete_permanently(self, relative_paths: list[str]) -> dict[str, object]:
        requested = list(dict.fromkeys(Path(path).as_posix() for path in relative_paths if path))
        locked = self._locked_process_paths()
        valid: list[tuple[str, Path]] = []
        failed: list[dict[str, str]] = []
        for relative in requested:
            if relative.casefold() in locked:
                failed.append({"path": relative, "error": "图片正在处理或等待处理，不能永久删除"})
                continue
            resolved = resolve_gallery_image(relative, self.output_root)
            if resolved is None:
                failed.append({"path": relative, "error": "图片不存在、越界或不在画廊中"})
                continue
            valid.append((relative, resolved))
        for _, path in valid:
            self.thumbnail_cache.purge(path)
        deleted, delete_failed = delete_gallery_images_permanently([path for _, path in valid], self.output_root)
        deleted_keys = {str(path.resolve()).casefold() for path in deleted}
        deleted_originals = sorted(
            relative for relative, path in valid
            if str(path.resolve()).casefold() in deleted_keys
        )
        failed.extend({"path": str(path), "error": error} for path, error in delete_failed)
        if deleted_originals:
            repository = SQLiteRepository(self.database)
            try:
                repository.set_gallery_asset_states(self.output_root, deleted_originals, "")
            finally:
                repository.close()
            deleted_set = set(deleted_originals)

            def remove_deleted(payload: dict[str, object]) -> None:
                payload["items"] = [item for item in payload.get("items", []) if item.get("path") not in deleted_set]
                if self._cached_filesystem is not None:
                    for relative in deleted_set:
                        self._cached_filesystem.pop(relative, None)

            self._update_cached_payload(remove_deleted)
        return {"deleted": deleted_originals, "failed": failed}

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
        if restored:
            self._invalidate_cached_payload()
        return {
            "restored": [path.relative_to(self.output_root).as_posix() for path in restored],
            "failed": [{"path": str(path), "error": error} for path, error in failed],
        }

    def delete_from_trash(self, relative_paths: list[str]) -> dict[str, object]:
        requested = list(dict.fromkeys(Path(path).as_posix() for path in relative_paths if path))
        resolved: list[Path] = []
        for relative in requested:
            path = resolve_gallery_trash_image(relative, self.output_root)
            if path is None:
                continue
            parts = Path(relative).parts
            aliases = (self.output_root.joinpath(*parts[1:]),) if len(parts) > 1 else ()
            self.thumbnail_cache.purge(path, aliases=aliases)
            resolved.append(path)
        deleted, failed = delete_images_permanently(resolved, self.output_root)
        if deleted:
            deleted_count = len(deleted)
            self._update_cached_payload(lambda payload: payload.update({
                "trash_count": max(0, int(payload.get("trash_count") or 0) - deleted_count),
            }))
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
                "parameters": {
                    "generation_params": dict(item.get("generation_params") or {}),
                    "negative_prompt": item.get("negative_prompt") or "",
                    "integration_metadata": {
                        "candidate": dict(item.get("candidate") or {}),
                        **(
                            {"artist_comparison": dict(item["artist_comparison"])}
                            if isinstance(item.get("artist_comparison"), dict)
                            else {}
                        ),
                    },
                },
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


def _parent_key(relative_path: str) -> str:
    parent = Path(relative_path).parent.as_posix()
    return parent or "."


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
