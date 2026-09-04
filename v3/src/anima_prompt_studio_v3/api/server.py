from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

import uvicorn

from .app import ApiRuntime, create_api_runtime


class LocalApiServer:
    """Own the loopback socket and Uvicorn lifecycle for the future desktop shell."""

    def __init__(
        self,
        reference_db: Path,
        *,
        frontend_dist: Path | None = None,
        workspace_db: Path | None = None,
        v2_database: Path | None = None,
        generation_queue: object | None = None,
        intent_parser: object | None = None,
        gallery_service: object | None = None,
        translation_service: object | None = None,
        app_version: str | None = None,
    ) -> None:
        if v2_database is not None and (
            generation_queue is not None or intent_parser is not None or gallery_service is not None
            or translation_service is not None
        ):
            raise ValueError("v2_database 不能与手动注入的 V2 适配器同时指定。")
        self._owned_generation_queue = None
        self._owned_gallery_service = None
        self._owned_comfy_access = None
        if v2_database is not None:
            try:
                from ..adapters.v2 import (
                    build_v2_gallery_service,
                    build_v2_generation_queue,
                    build_v2_intent_parser,
                    build_v2_local_translation_adapter,
                    ManagedComfyAccess,
                )
            except ModuleNotFoundError as exc:
                raise RuntimeError("当前安装不包含 V2 兼容运行时。") from exc
            self._owned_generation_queue = build_v2_generation_queue(v2_database)
            generation_queue = self._owned_generation_queue
            intent_parser = build_v2_intent_parser(v2_database)
            gallery_service = build_v2_gallery_service(v2_database)
            translation_service = build_v2_local_translation_adapter()
            self._owned_gallery_service = gallery_service
            self._owned_comfy_access = ManagedComfyAccess(v2_database)
        self.runtime: ApiRuntime = create_api_runtime(
            reference_db,
            frontend_dist=frontend_dist,
            workspace_db=workspace_db,
            v2_database=v2_database,
            generation_queue=generation_queue,
            intent_parser=intent_parser,
            gallery_service=gallery_service,
            translation_service=translation_service,
            comfy_access=self._owned_comfy_access,
            app_version=app_version,
        )
        self._socket: socket.socket | None = None
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._port: int | None = None

    @property
    def port(self) -> int:
        if self._port is None:
            raise RuntimeError("localhost API 尚未启动。")
        return self._port

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def bootstrap_url(self) -> str:
        return f"{self.base_url}/?{urlencode({'bootstrap': self.runtime.bootstrap_token})}"

    def start(self, *, timeout: float = 10.0) -> "LocalApiServer":
        if self._thread is not None and self._thread.is_alive():
            return self
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", 0))
            sock.listen(128)
            self._port = int(sock.getsockname()[1])
            config = uvicorn.Config(
                self.runtime.app,
                host="127.0.0.1",
                port=self._port,
                log_level="warning",
                access_log=False,
            )
            self._server = uvicorn.Server(config)
            self._socket = sock
            self._thread = threading.Thread(
                target=self._server.run,
                kwargs={"sockets": [sock]},
                name="anima-v3-local-api",
                daemon=True,
            )
            self._thread.start()
            deadline = time.monotonic() + timeout
            while not self._server.started and self._thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            if not self._server.started:
                self.stop()
                raise RuntimeError("localhost API 启动超时或提前退出。")
            if self._owned_comfy_access is not None:
                self._owned_comfy_access.start_default_async()
            return self
        except Exception:
            if self._socket is None:
                sock.close()
            raise

    def stop(self, *, timeout: float = 10.0) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout)
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("localhost API 未能在超时内停止。")
        if self._socket is not None:
            self._socket.close()
        self._socket = None
        self._server = None
        self._thread = None
        self._port = None
        if self._owned_generation_queue is not None:
            self._owned_generation_queue.shutdown(cancel_active=True, timeout=timeout)
            self._owned_generation_queue = None
        if self._owned_gallery_service is not None:
            self._owned_gallery_service.shutdown(timeout=timeout)
            self._owned_gallery_service = None
        if self._owned_comfy_access is not None:
            self._owned_comfy_access.close()
            self._owned_comfy_access = None

    def __enter__(self) -> "LocalApiServer":
        return self.start()

    def __exit__(self, *_args: object) -> None:
        self.stop()
