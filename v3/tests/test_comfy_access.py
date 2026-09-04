from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from anima_prompt_studio.domain.execution_models import RemoteAuthType, RemoteProfile
from anima_prompt_studio.repositories.sqlite_repository import SQLiteRepository
from anima_prompt_studio.services.remote.credential_store import CredentialStore, MemoryCredentialBackend
from anima_prompt_studio_v3.adapters.v2.comfy_access import COMFY_ACCESS_PORT, ManagedComfyAccess


def test_managed_comfy_access_uses_fixed_loopback_port_and_closes_with_owner(tmp_path: Path) -> None:
    database = tmp_path / "v2.db"
    repository = SQLiteRepository(database)
    try:
        repository.save_remote_profile(RemoteProfile(
            id="remote-ready",
            display_name="测试云主机",
            ssh_host="gpu.example",
            ssh_user="root",
            auth_type=RemoteAuthType.PASSWORD,
            known_host_fingerprint="SHA256:confirmed",
        ))
        repository.set_setting("last_remote_profile_id", "remote-ready")
    finally:
        repository.close()

    credentials = CredentialStore(MemoryCredentialBackend())
    credentials.save_password("remote-ready", "root", "secret")
    events: list[object] = []

    class FakeTunnel:
        def __init__(self, profile, *, local_bind_host, local_bind_port) -> None:
            events.append((profile.id, local_bind_host, local_bind_port))
            self.base_url = f"http://{local_bind_host}:{local_bind_port}"
            self.client = SimpleNamespace(get_transport=lambda: SimpleNamespace(is_active=lambda: True))
            self.server = object()

        def open(self, supplied):
            events.append(("open", supplied.password))
            return self

        def close(self) -> None:
            events.append("close")
            self.client = None
            self.server = None

    class FakeClient:
        def __init__(self, base_url: str) -> None:
            events.append(("client", base_url))

        def validate_environment(self):
            return SimpleNamespace(
                devices=["NVIDIA Test GPU"],
                queue_running=1,
                queue_pending=2,
            )

    manager = ManagedComfyAccess(
        database,
        credential_store=credentials,
        tunnel_factory=FakeTunnel,
        client_factory=FakeClient,
    )

    state = manager.open("remote-ready")

    assert state["ready"] is True
    assert state["local_url"] == "http://127.0.0.1:18188"
    assert state["devices"] == ["NVIDIA Test GPU"]
    assert ("remote-ready", "127.0.0.1", COMFY_ACCESS_PORT) in events
    assert ("open", "secret") in events

    manager.close()

    assert manager.status()["state"] == "stopped"
    assert "close" in events


def test_managed_comfy_access_starts_the_saved_default_in_background(tmp_path: Path) -> None:
    database = tmp_path / "v2.db"
    repository = SQLiteRepository(database)
    try:
        repository.save_remote_profile(RemoteProfile(
            id="remote-default",
            display_name="默认云主机",
            ssh_host="gpu.example",
            ssh_user="root",
            auth_type=RemoteAuthType.AGENT,
            known_host_fingerprint="SHA256:confirmed",
        ))
        repository.set_setting("last_remote_profile_id", "remote-default")
    finally:
        repository.close()

    opened: list[str] = []
    manager = ManagedComfyAccess(database)
    manager.open = lambda profile_id, **_kwargs: opened.append(profile_id) or manager.status()  # type: ignore[method-assign]

    manager.start_default_async()
    assert manager._startup_thread is not None
    manager._startup_thread.join(timeout=2)

    assert opened == ["remote-default"]
