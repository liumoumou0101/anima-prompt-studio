from __future__ import annotations

import json
import hashlib
import logging
import mimetypes
import os
import secrets
import subprocess
import threading
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from PySide6.QtCore import Qt
from PySide6.QtGui import QImageReader

from anima_prompt_studio.repositories import SQLiteRepository
from anima_prompt_studio.domain.execution_models import RemoteCredentials, RemoteProfile, WorkflowProfile
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
from anima_prompt_studio.services.gallery_upscale import GalleryUpscaleError, GalleryUpscaleManager

log = logging.getLogger(__name__)


class GalleryServer:
    """Serve the bundled gallery UI and a localhost-only image management API."""

    def __init__(
        self,
        repository: SQLiteRepository,
        output_root: Path,
        static_root: Path | None = None,
        port: int = 0,
        upscale_manager: GalleryUpscaleManager | None = None,
    ) -> None:
        self.repository = repository
        self._output_root = output_root.expanduser()
        self.static_root = static_root or Path(__file__).resolve().parents[1] / "web_gallery" / "dist"
        self.port = port
        self.thumbnail_root = repository.db_path.parent / "gallery_thumbnails"
        self._server: _GalleryHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._thumbnail_lock = threading.Lock()
        self._session_token = secrets.token_urlsafe(24)
        self.upscale_manager = upscale_manager or GalleryUpscaleManager(
            repository.db_path,
            self._output_root,
        )

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def url(self) -> str:
        if self._server is None:
            raise RuntimeError("画廊服务尚未启动")
        return f"http://127.0.0.1:{self._server.server_port}/"

    def set_output_root(self, output_root: Path) -> None:
        resolved = output_root.expanduser()
        self.upscale_manager.set_output_root(resolved)
        self._output_root = resolved

    def configure_gallery_upscale(
        self,
        remote_profile: RemoteProfile | None,
        workflow_profile: WorkflowProfile | None,
        credentials: RemoteCredentials | None,
    ) -> None:
        self.upscale_manager.configure(remote_profile, workflow_profile, credentials)

    def start(self) -> str:
        if self._server is not None:
            return self.url
        handler = _make_handler(self)
        self._server = _GalleryHTTPServer(("127.0.0.1", self.port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, name="anima-gallery", daemon=True)
        self._thread.start()
        return self.url

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=2)

    def gallery_payload(self) -> dict[str, Any]:
        root = self._output_root.resolve()
        request_repository = SQLiteRepository(self.repository.db_path)
        try:
            batches = load_gallery_batches(request_repository, root, limit=500)
            states = request_repository.list_gallery_asset_states(root)
        finally:
            request_repository.close()
        assets: list[dict[str, Any]] = []
        for batch in batches:
            for path in batch.image_paths:
                relative = _relative_path(path, root)
                if relative is None:
                    continue
                params = batch.parameters if isinstance(batch.parameters, dict) else {}
                fallback_width = _positive_int(params.get("width"), 1024)
                fallback_height = _positive_int(params.get("height"), 1024)
                width, height = _image_dimensions(path, fallback_width, fallback_height)
                asset_id = relative
                assets.append({
                    "id": asset_id,
                    "path": relative,
                    "src": f"/api/image?path={quote(relative, safe='')}",
                    "thumbnail": f"/api/thumbnail?path={quote(relative, safe='')}&size=720",
                    "name": path.name,
                    "project": batch.project_name,
                    "model": batch.model_profile_id,
                    "batchId": batch.run_id,
                    "batchTitle": batch.title,
                    "createdAt": batch.created_at.isoformat(),
                    "prompt": batch.positive_prompt,
                    "parameters": params,
                    "source": "external" if batch.run_id.startswith("folder:") else "generated",
                    "state": states.get(relative, ""),
                    "width": width,
                    "height": height,
                    "bytes": _file_size(path),
                })
        return {
            "root": str(root),
            "assets": assets,
            "projects": sorted({asset["project"] for asset in assets}),
            "models": sorted({asset["model"] for asset in assets if asset["model"]}),
            "batches": sorted(
                {asset["batchId"]: {"id": asset["batchId"], "title": asset["batchTitle"]} for asset in assets}.values(),
                key=lambda item: item["title"],
            ),
            "trashCount": self._trash_count(root),
            "processing": self.upscale_manager.configuration_payload(),
            "processingToken": self._session_token,
        }

    def start_upscale(self, relative_path: str) -> dict[str, Any]:
        result = self.start_upscales([relative_path])
        if result["jobs"]:
            return result["jobs"][0]
        failure = result["failed"][0] if result["failed"] else {"error": "无法加入任务队列"}
        raise GalleryUpscaleError(str(failure["error"]))

    def start_upscales(self, relative_paths: list[str]) -> dict[str, Any]:
        decoded_paths = list(dict.fromkeys(unquote(path) for path in relative_paths if path))
        assets = {item["path"]: item for item in self.gallery_payload()["assets"]}
        jobs: list[dict[str, Any]] = []
        failed: list[dict[str, str]] = []
        for decoded in decoded_paths:
            source = self.image_path(decoded)
            asset = assets.get(decoded)
            if source is None or asset is None:
                failed.append({"path": decoded, "error": "画廊中找不到待处理图片"})
                continue
            try:
                jobs.append(self.upscale_manager.submit(source, decoded, asset))
            except GalleryUpscaleError as exc:
                failed.append({"path": decoded, "error": str(exc)})
        return {"jobs": jobs, "failed": failed}

    def upscale_status(self, job_id: str) -> dict[str, Any] | None:
        return self.upscale_manager.get(job_id)

    def upscale_jobs(self) -> dict[str, Any]:
        return {
            "jobs": self.upscale_manager.list_jobs(),
            "processing": self.upscale_manager.configuration_payload(),
        }

    def upscale_action(self, job_id: str, action: str) -> dict[str, Any]:
        if action == "cancel":
            return {"job": self.upscale_manager.cancel(job_id)}
        if action == "retry":
            return {"job": self.upscale_manager.retry(job_id)}
        if action == "clear_completed":
            return {"cleared": self.upscale_manager.clear_completed()}
        raise ValueError("不支持的任务操作")

    def valid_processing_token(self, value: str) -> bool:
        return bool(value) and secrets.compare_digest(value, self._session_token)

    def image_path(self, relative_path: str) -> Path | None:
        return resolve_gallery_image(unquote(relative_path), self._output_root)

    def trash_image_path(self, relative_path: str) -> Path | None:
        return resolve_gallery_trash_image(unquote(relative_path), self._output_root)

    def thumbnail_path(self, relative_path: str, size: int, *, trash: bool = False) -> Path | None:
        source = self.trash_image_path(relative_path) if trash else self.image_path(relative_path)
        if source is None:
            return None
        size = max(160, min(size, 1440))
        try:
            stat = source.stat()
        except OSError:
            return None
        digest = hashlib.sha256(
            f"{source.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|{size}".encode("utf-8")
        ).hexdigest()
        target = self.thumbnail_root / digest[:2] / f"{digest}.webp"
        if target.is_file():
            return target
        with self._thumbnail_lock:
            if target.is_file():
                return target
            reader = QImageReader(str(source))
            reader.setAutoTransform(True)
            image = reader.read()
            if image.isNull():
                return source
            scaled = image.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(".tmp")
            if not scaled.save(str(temporary), "WEBP", 82):
                return source
            temporary.replace(target)
        return target

    def set_state(self, relative_paths: list[str], state: str) -> dict[str, Any]:
        root = self._output_root.resolve()
        valid = []
        for raw in relative_paths:
            path = resolve_gallery_image(raw, root)
            if path is not None:
                valid.append(path.resolve().relative_to(root).as_posix())
        request_repository = SQLiteRepository(self.repository.db_path)
        try:
            request_repository.set_gallery_asset_states(root, valid, state)
        finally:
            request_repository.close()
        return {"updated": sorted(set(valid)), "state": state}

    def trash(self, relative_paths: list[str]) -> dict[str, Any]:
        root = self._output_root.resolve()
        locked = {Path(path).as_posix() for path in self.upscale_manager.locked_paths()}
        locked_requested = {
            Path(raw).as_posix()
            for raw in relative_paths
            if Path(raw).as_posix() in locked
        }
        paths = [
            path
            for raw in relative_paths
            if Path(raw).as_posix() not in locked
            and (path := resolve_gallery_image(raw, root)) is not None
        ]
        requested = {str(Path(raw).as_posix()) for raw in relative_paths}
        moved, failed = move_images_to_trash(paths, root)
        valid_relative = {
            path.resolve().relative_to(root).as_posix()
            for path in paths
        }
        failed_payload = [{"path": _request_path_label(path, root), "error": error} for path, error in failed]
        failed_payload.extend(
            {"path": path, "error": "图片正在处理或等待处理，不能移入回收站"}
            for path in sorted(locked_requested)
        )
        failed_set = {item["path"] for item in failed_payload}
        moved_set = valid_relative - failed_set
        for raw in sorted(requested - moved_set):
            if raw not in failed_set:
                failed_payload.append({"path": raw, "error": "图片不存在、越界或不在画廊中"})
        return {
            "moved": sorted(moved_set),
            "failed": failed_payload,
        }

    def trash_payload(self) -> dict[str, Any]:
        root = self._output_root.resolve()
        trash_root = root / TRASH_DIR_NAME
        assets: list[dict[str, Any]] = []
        if trash_root.is_dir():
            try:
                candidates = sorted(
                    (path for path in trash_root.rglob("*") if path.suffix.casefold() in IMAGE_SUFFIXES and path.is_file()),
                    key=lambda path: path.stat().st_mtime,
                    reverse=True,
                )[:3000]
            except OSError:
                candidates = []
            for path in candidates:
                try:
                    relative = path.resolve().relative_to(trash_root).as_posix()
                    parts = Path(relative).parts
                    original = Path(*parts[1:]).as_posix() if len(parts) > 1 else path.name
                    stat = path.stat()
                except (OSError, ValueError):
                    continue
                width, height = _image_dimensions(path, 1024, 1024)
                assets.append({
                    "id": relative,
                    "path": relative,
                    "originalPath": original,
                    "name": path.name,
                    "src": f"/api/trash-image?path={quote(relative, safe='')}",
                    "thumbnail": f"/api/thumbnail?trash=1&path={quote(relative, safe='')}&size=720",
                    "width": width,
                    "height": height,
                    "bytes": stat.st_size,
                    "createdAt": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
                    "source": "trash",
                    "state": "",
                    "project": Path(original).parts[0] if len(Path(original).parts) > 1 else "未分类",
                    "model": "",
                    "batchId": parts[0] if parts else "trash",
                    "batchTitle": f"回收站 · {parts[0] if parts else '未分组'}",
                    "prompt": "",
                    "parameters": {},
                })
        return {
            "root": str(root),
            "assets": assets,
            "trashCount": len(assets),
            "processing": self.upscale_manager.configuration_payload(),
            "processingToken": self._session_token,
        }

    def restore(self, relative_paths: list[str]) -> dict[str, Any]:
        root = self._output_root.resolve()
        paths = [path for raw in relative_paths if (path := resolve_gallery_trash_image(raw, root)) is not None]
        restored, failed = restore_images_from_trash(paths, root)
        return {
            "restored": [path.resolve().relative_to(root).as_posix() for path in restored],
            "failed": [{"path": str(path), "error": error} for path, error in failed],
        }

    def delete_forever(self, relative_paths: list[str]) -> dict[str, Any]:
        root = self._output_root.resolve()
        trash_root = root / TRASH_DIR_NAME
        paths = [path for raw in relative_paths if (path := resolve_gallery_trash_image(raw, root)) is not None]
        deleted, failed = delete_images_permanently(paths, root)
        return {
            "deleted": [path.resolve().relative_to(trash_root).as_posix() for path in deleted],
            "failed": [{"path": str(path), "error": error} for path, error in failed],
        }

    def reveal(self, relative_path: str) -> bool:
        path = resolve_gallery_image(relative_path, self._output_root)
        if path is None:
            return False
        if os.name == "nt":
            subprocess.Popen(
                ["explorer.exe", f"/select,{path}"],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        return False

    def _trash_count(self, root: Path) -> int:
        trash_root = root / TRASH_DIR_NAME
        if not trash_root.is_dir():
            return 0
        try:
            return sum(1 for path in trash_root.rglob("*") if path.suffix.casefold() in IMAGE_SUFFIXES and path.is_file())
        except OSError:
            return 0


class _GalleryHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def _make_handler(service: GalleryServer):
    class GalleryRequestHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(service.static_root), **kwargs)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/api/health":
                    self._send_json({"ok": True})
                    return
                if parsed.path == "/api/gallery":
                    self._send_json(service.gallery_payload())
                    return
                if parsed.path == "/api/gallery/trash":
                    self._send_json(service.trash_payload())
                    return
                if parsed.path == "/api/gallery/process":
                    if not service.valid_processing_token(self.headers.get("X-Gallery-Token", "")):
                        self._send_json({"error": "画廊处理会话无效，请刷新页面后重试。"}, status=403)
                        return
                    query = parse_qs(parsed.query)
                    job = service.upscale_status(query.get("job", [""])[0])
                    if job is None:
                        self._send_json({"error": "处理任务不存在"}, status=404)
                    else:
                        self._send_json(job)
                    return
                if parsed.path == "/api/gallery/process/jobs":
                    if not service.valid_processing_token(self.headers.get("X-Gallery-Token", "")):
                        self._send_json({"error": "画廊处理会话无效，请刷新页面后重试。"}, status=403)
                        return
                    self._send_json(service.upscale_jobs())
                    return
                if parsed.path == "/api/image":
                    query = parse_qs(parsed.query)
                    raw_path = query.get("path", [""])[0]
                    image = service.image_path(raw_path)
                    if image is None:
                        self._send_json({"error": "图片不存在"}, status=404)
                        return
                    self._send_file(image)
                    return
                if parsed.path == "/api/trash-image":
                    query = parse_qs(parsed.query)
                    image = service.trash_image_path(query.get("path", [""])[0])
                    if image is None:
                        self._send_json({"error": "回收站图片不存在"}, status=404)
                        return
                    self._send_file(image)
                    return
                if parsed.path == "/api/thumbnail":
                    query = parse_qs(parsed.query)
                    raw_size = query.get("size", ["720"])[0]
                    try:
                        size = int(raw_size)
                    except ValueError:
                        size = 720
                    thumbnail = service.thumbnail_path(
                        query.get("path", [""])[0],
                        size,
                        trash=query.get("trash", ["0"])[0] == "1",
                    )
                    if thumbnail is None:
                        self._send_json({"error": "图片不存在"}, status=404)
                        return
                    self._send_file(thumbnail)
                    return
                super().do_GET()
            except Exception:
                log.exception("画廊 GET 请求失败：%s", self.path)
                self._send_json({"error": "画廊服务内部错误"}, status=500)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path not in {
                "/api/gallery/trash",
                "/api/gallery/state",
                "/api/gallery/restore",
                "/api/gallery/delete",
                "/api/gallery/reveal",
                "/api/gallery/process",
                "/api/gallery/process/action",
            }:
                self.send_error(404)
                return
            try:
                length = min(int(self.headers.get("Content-Length", "0")), 2_000_000)
                payload = json.loads(self.rfile.read(length) or b"{}")
                if (
                    parsed.path in {"/api/gallery/process", "/api/gallery/process/action"}
                    and not service.valid_processing_token(self.headers.get("X-Gallery-Token", ""))
                ):
                    self._send_json({"error": "画廊处理会话无效，请刷新页面后重试。"}, status=403)
                    return
                if parsed.path == "/api/gallery/process":
                    raw_paths = payload.get("paths")
                    if raw_paths is None:
                        raw_path = payload.get("path", "")
                        if not isinstance(raw_path, str) or not raw_path:
                            raise ValueError("path 必须是非空字符串")
                        self._send_json(service.start_upscale(raw_path), status=202)
                        return
                    if not isinstance(raw_paths, list) or not raw_paths or not all(
                        isinstance(path, str) and path for path in raw_paths
                    ):
                        raise ValueError("path 或 paths 必须包含非空字符串")
                    result = service.start_upscales(raw_paths)
                    self._send_json(result, status=202)
                    return
                if parsed.path == "/api/gallery/process/action":
                    job_id = payload.get("job", "")
                    action = payload.get("action", "")
                    if not isinstance(job_id, str) or not isinstance(action, str):
                        raise ValueError("job 和 action 必须是字符串")
                    self._send_json(service.upscale_action(job_id, action))
                    return
                if parsed.path == "/api/gallery/reveal":
                    raw_path = payload.get("path", "")
                    if not isinstance(raw_path, str):
                        raise ValueError("path 必须是字符串")
                    if not service.reveal(raw_path):
                        self._send_json({"error": "无法在文件夹中显示图片"}, status=404)
                    else:
                        self._send_json({"ok": True})
                    return
                raw_paths = payload.get("paths", [])
                if not isinstance(raw_paths, list) or not all(isinstance(path, str) for path in raw_paths):
                    raise ValueError("paths 必须是字符串数组")
                if parsed.path == "/api/gallery/trash":
                    result = service.trash(raw_paths)
                elif parsed.path == "/api/gallery/state":
                    state = payload.get("state", "")
                    if not isinstance(state, str):
                        raise ValueError("state 必须是字符串")
                    result = service.set_state(raw_paths, state)
                elif parsed.path == "/api/gallery/restore":
                    result = service.restore(raw_paths)
                else:
                    result = service.delete_forever(raw_paths)
                self._send_json(result)
            except FileNotFoundError as exc:
                self._send_json({"error": str(exc)}, status=404)
            except GalleryUpscaleError as exc:
                self._send_json({"error": str(exc)}, status=409)
            except (ValueError, TypeError, json.JSONDecodeError):
                self._send_json({"error": "请求格式无效"}, status=400)
            except Exception:
                log.exception("画廊批量回收失败")
                self._send_json({"error": "画廊服务内部错误"}, status=500)

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path) -> None:
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(path.stat().st_size))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            with path.open("rb") as source:
                while chunk := source.read(1024 * 256):
                    self.wfile.write(chunk)

        def log_message(self, format: str, *args) -> None:
            log.debug("gallery http: " + format, *args)

    return GalleryRequestHandler


def _relative_path(path: Path, root: Path) -> str | None:
    try:
        relative = path.resolve().relative_to(root)
    except (OSError, ValueError):
        return None
    if not relative.parts or relative.parts[0] == ".trash" or path.suffix.casefold() not in IMAGE_SUFFIXES:
        return None
    return relative.as_posix()


def _request_path_label(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except (OSError, ValueError):
        return str(path)


def _positive_int(value: Any, default: int) -> int:
    try:
        result = int(value)
        return result if result > 0 else default
    except (TypeError, ValueError):
        return default


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _image_dimensions(path: Path, fallback_width: int, fallback_height: int) -> tuple[int, int]:
    try:
        size = QImageReader(str(path)).size()
        if size.isValid() and size.width() > 0 and size.height() > 0:
            return size.width(), size.height()
    except (OSError, RuntimeError):
        pass
    return fallback_width, fallback_height
