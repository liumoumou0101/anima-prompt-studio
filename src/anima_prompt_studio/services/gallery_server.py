from __future__ import annotations

import json
import logging
import mimetypes
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from anima_prompt_studio.repositories import SQLiteRepository
from anima_prompt_studio.services.gallery_assets import (
    IMAGE_SUFFIXES,
    move_images_to_trash,
    resolve_gallery_image,
)
from anima_prompt_studio.services.gallery_index import load_gallery_batches

log = logging.getLogger(__name__)


class GalleryServer:
    """Serve the bundled gallery UI and a localhost-only image management API."""

    def __init__(
        self,
        repository: SQLiteRepository,
        output_root: Path,
        static_root: Path | None = None,
        port: int = 0,
    ) -> None:
        self.repository = repository
        self._output_root = output_root.expanduser()
        self.static_root = static_root or Path(__file__).resolve().parents[1] / "web_gallery" / "dist"
        self.port = port
        self._server: _GalleryHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def url(self) -> str:
        if self._server is None:
            raise RuntimeError("画廊服务尚未启动")
        return f"http://127.0.0.1:{self._server.server_port}/"

    def set_output_root(self, output_root: Path) -> None:
        self._output_root = output_root.expanduser()

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
        finally:
            request_repository.close()
        assets: list[dict[str, Any]] = []
        for batch in batches:
            for path in batch.image_paths:
                relative = _relative_path(path, root)
                if relative is None:
                    continue
                params = batch.parameters if isinstance(batch.parameters, dict) else {}
                width = _positive_int(params.get("width"), 1024)
                height = _positive_int(params.get("height"), 1024)
                asset_id = relative
                assets.append({
                    "id": asset_id,
                    "path": relative,
                    "src": f"/api/image?path={quote(relative, safe='')}",
                    "name": path.name,
                    "project": batch.project_name,
                    "model": batch.model_profile_id,
                    "batchId": batch.run_id,
                    "batchTitle": batch.title,
                    "createdAt": batch.created_at.isoformat(),
                    "prompt": batch.positive_prompt,
                    "parameters": params,
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
        }

    def image_path(self, relative_path: str) -> Path | None:
        return resolve_gallery_image(unquote(relative_path), self._output_root)

    def trash(self, relative_paths: list[str]) -> dict[str, Any]:
        root = self._output_root.resolve()
        paths = [path for raw in relative_paths if (path := resolve_gallery_image(raw, root)) is not None]
        requested = {str(Path(raw).as_posix()) for raw in relative_paths}
        moved, failed = move_images_to_trash(paths, root)
        valid_relative = {
            path.resolve().relative_to(root).as_posix()
            for path in paths
        }
        failed_payload = [{"path": _request_path_label(path, root), "error": error} for path, error in failed]
        failed_set = {item["path"] for item in failed_payload}
        moved_set = valid_relative - failed_set
        for raw in sorted(requested - moved_set):
            if raw not in failed_set:
                failed_payload.append({"path": raw, "error": "图片不存在、越界或不在画廊中"})
        return {
            "moved": sorted(moved_set),
            "failed": failed_payload,
        }


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
                if parsed.path == "/api/image":
                    query = parse_qs(parsed.query)
                    raw_path = query.get("path", [""])[0]
                    image = service.image_path(raw_path)
                    if image is None:
                        self._send_json({"error": "图片不存在"}, status=404)
                        return
                    self._send_file(image)
                    return
                super().do_GET()
            except Exception:
                log.exception("画廊 GET 请求失败：%s", self.path)
                self._send_json({"error": "画廊服务内部错误"}, status=500)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/api/gallery/trash":
                self.send_error(404)
                return
            try:
                length = min(int(self.headers.get("Content-Length", "0")), 2_000_000)
                payload = json.loads(self.rfile.read(length) or b"{}")
                raw_paths = payload.get("paths", [])
                if not isinstance(raw_paths, list) or not all(isinstance(path, str) for path in raw_paths):
                    raise ValueError("paths 必须是字符串数组")
                self._send_json(service.trash(raw_paths))
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
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

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
