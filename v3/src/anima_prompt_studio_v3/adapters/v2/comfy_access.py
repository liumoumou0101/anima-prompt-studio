from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from anima_prompt_studio.domain.execution_models import RemoteAuthType, RemoteCredentials
from anima_prompt_studio.repositories.sqlite_repository import SQLiteRepository
from anima_prompt_studio.services.remote.comfy_client import ComfyUIClient
from anima_prompt_studio.services.remote.credential_store import CredentialStore
from anima_prompt_studio.services.remote.ssh_tunnel import SshTunnel


COMFY_ACCESS_HOST = "127.0.0.1"
COMFY_ACCESS_PORT = 18188
COMFY_ACCESS_URL = f"http://{COMFY_ACCESS_HOST}:{COMFY_ACCESS_PORT}"
LOGGER = logging.getLogger(__name__)


class ManagedComfyAccess:
    """Keep one loopback-only ComfyUI maintenance tunnel alive with the app."""

    def __init__(
        self,
        database: Path,
        *,
        credential_store: CredentialStore | None = None,
        tunnel_factory: type[SshTunnel] = SshTunnel,
        client_factory: type[ComfyUIClient] = ComfyUIClient,
        local_port: int = COMFY_ACCESS_PORT,
    ) -> None:
        self.database = Path(database).expanduser().resolve()
        self.credential_store = credential_store or CredentialStore()
        self.tunnel_factory = tunnel_factory
        self.client_factory = client_factory
        self.local_port = local_port
        self._state_lock = threading.RLock()
        self._operation_lock = threading.Lock()
        self._tunnel: SshTunnel | None = None
        self._profile_id = ""
        self._profile_name = ""
        self._state = "stopped"
        self._message = "维护隧道尚未连接。"
        self._devices: list[str] = []
        self._queue_running = 0
        self._queue_pending = 0
        self._startup_thread: threading.Thread | None = None
        self._closing = False

    @property
    def local_url(self) -> str:
        return f"http://{COMFY_ACCESS_HOST}:{self.local_port}"

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "state": self._state,
                "ready": self._state == "ready" and self._tunnel_is_active(),
                "remote_profile_id": self._profile_id or None,
                "remote_display_name": self._profile_name or None,
                "local_url": self.local_url,
                "message": self._message,
                "devices": list(self._devices),
                "queue_running": self._queue_running,
                "queue_pending": self._queue_pending,
            }

    def start_default_async(self) -> None:
        with self._state_lock:
            self._closing = False
            if self._startup_thread is not None and self._startup_thread.is_alive():
                return
            thread = threading.Thread(
                target=self._open_default_safely,
                name="anima-comfy-maintenance-tunnel",
                daemon=True,
            )
            self._startup_thread = thread
            thread.start()

    def open(
        self,
        profile_id: str,
        *,
        password: str = "",
        passphrase: str = "",
    ) -> dict[str, Any]:
        with self._operation_lock:
            profile = self._profile(profile_id)
            with self._state_lock:
                if self._closing:
                    raise RuntimeError("应用正在关闭，不能建立 ComfyUI 维护隧道。")
                if self._profile_id == profile.id and self._tunnel_is_active():
                    return self.status()
                self._state = "connecting"
                self._profile_id = profile.id
                self._profile_name = profile.display_name
                self._message = f"正在连接 {profile.display_name}…"

            credentials = self._credentials(profile, password=password, passphrase=passphrase)
            self._close_current_tunnel()
            tunnel = self.tunnel_factory(
                profile,
                local_bind_host=COMFY_ACCESS_HOST,
                local_bind_port=self.local_port,
            )
            try:
                tunnel.open(credentials)
                report = self.client_factory(tunnel.base_url).validate_environment()
            except Exception as exc:
                tunnel.close()
                with self._state_lock:
                    self._state = "error"
                    self._message = f"ComfyUI 维护入口连接失败：{exc}"
                    self._devices = []
                    self._queue_running = 0
                    self._queue_pending = 0
                raise

            with self._state_lock:
                if self._closing:
                    tunnel.close()
                    raise RuntimeError("应用正在关闭，已取消 ComfyUI 维护隧道。")
                self._tunnel = tunnel
                self._state = "ready"
                self._message = f"ComfyUI 网页已通过本机安全隧道连接到 {profile.display_name}。"
                self._devices = list(report.devices)
                self._queue_running = int(report.queue_running)
                self._queue_pending = int(report.queue_pending)
                return self.status()

    def close(self) -> None:
        with self._state_lock:
            self._closing = True
        self._close_current_tunnel()
        with self._state_lock:
            self._state = "stopped"
            self._message = "项目已关闭，ComfyUI 维护隧道已停止。"
            self._devices = []
            self._queue_running = 0
            self._queue_pending = 0

    def _open_default_safely(self) -> None:
        try:
            profile_id = self._default_profile_id()
            if not profile_id:
                with self._state_lock:
                    self._message = "没有已启用的云主机，无法启动 ComfyUI 维护入口。"
                return
            self.open(profile_id)
        except Exception as exc:
            LOGGER.warning("ComfyUI maintenance tunnel did not start: %s", exc)

    def _default_profile_id(self) -> str:
        repository = SQLiteRepository(self.database)
        try:
            profiles = repository.list_remote_profiles(enabled_only=True)
            preferred = str(repository.get_setting("last_remote_profile_id", "") or "")
        finally:
            repository.close()
        if any(profile.id == preferred for profile in profiles):
            return preferred
        return profiles[0].id if profiles else ""

    def _profile(self, profile_id: str):
        repository = SQLiteRepository(self.database)
        try:
            profile = repository.get_remote_profile(profile_id)
        finally:
            repository.close()
        if not profile.enabled:
            raise ValueError("所选云主机已停用。")
        if not profile.known_host_fingerprint.strip():
            raise ValueError("请先检测并确认 SSH 主机指纹。")
        return profile

    def _credentials(self, profile, *, password: str, passphrase: str) -> RemoteCredentials:
        if profile.auth_type == RemoteAuthType.PASSWORD and not password:
            password = self.credential_store.read_password(profile.id)
        if profile.auth_type == RemoteAuthType.PASSWORD and not password:
            raise ValueError("没有可用的 SSH 密码；请在设置中填写并保存密码。")
        return RemoteCredentials(password=password, passphrase=passphrase)

    def _tunnel_is_active(self) -> bool:
        tunnel = self._tunnel
        if tunnel is None or tunnel.client is None or tunnel.server is None:
            return False
        transport = tunnel.client.get_transport()
        return bool(transport is not None and transport.is_active())

    def _close_current_tunnel(self) -> None:
        with self._state_lock:
            tunnel = self._tunnel
            self._tunnel = None
        if tunnel is not None:
            tunnel.close()
