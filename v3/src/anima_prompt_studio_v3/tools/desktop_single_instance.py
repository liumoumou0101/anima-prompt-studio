"""Workspace-scoped desktop instance coordination without trusting arbitrary localhost services."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


STATE_SCHEMA = "anima-local-api-port/1"


def state_path(workspace_db: Path) -> Path:
    workspace_db = workspace_db.resolve()
    return workspace_db.with_name(workspace_db.name + ".local-api.json")


class DesktopInstanceLease:
    """Hold one OS file lock for the lifetime of a workspace desktop server."""

    def __init__(self, workspace_db: Path) -> None:
        workspace_db = workspace_db.resolve()
        self.path = workspace_db.with_name(workspace_db.name + ".local-api.lock")
        self._file = None

    @property
    def held(self) -> bool:
        return self._file is not None

    def acquire(self) -> bool:
        if self._file is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file = self.path.open("a+b")
        try:
            if file.seek(0, os.SEEK_END) == 0:
                file.write(b"\0")
                file.flush()
            file.seek(0)
            if os.name == "nt":
                import msvcrt
                try:
                    msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    file.close()
                    return False
            else:
                import fcntl
                try:
                    fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    file.close()
                    return False
            self._file = file
            return True
        except Exception:
            file.close()
            raise

    def close(self) -> None:
        file, self._file = self._file, None
        if file is None:
            return
        try:
            file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)
        finally:
            file.close()

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("工作区已由另一个 ANIMA 实例使用。")
        return self

    def __exit__(self, *_args) -> None:
        self.close()


def read_instance_state(workspace_db: Path) -> dict[str, object]:
    try:
        value = json.loads(state_path(workspace_db).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return {}
    if not isinstance(value, dict) or value.get("schema") != STATE_SCHEMA:
        return {}
    port = value.get("port")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        return {}
    instance_id = value.get("instance_id")
    if instance_id is not None and (not isinstance(instance_id, str) or not 16 <= len(instance_id) <= 256):
        return {}
    return {"port": port, **({"instance_id": instance_id} if instance_id else {})}


def save_instance_state(workspace_db: Path, port: int, instance_id: str) -> None:
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("保存的本地端口必须为 1–65535 的整数。")
    if not isinstance(instance_id, str) or not 16 <= len(instance_id) <= 256:
        raise ValueError("桌面实例 ID 无效。")
    path = state_path(workspace_db)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            json.dump({"schema": STATE_SCHEMA, "port": port, "instance_id": instance_id}, file)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


_LOCAL_OPENER = build_opener(ProxyHandler({}), _NoRedirect())


def probe_instance(port: int, instance_id: str, *, timeout: float = 0.75) -> bool:
    base_url = f"http://127.0.0.1:{port}"
    request = Request(
        base_url + "/api/v3/desktop/instance",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Origin": base_url,
            "X-Anima-Local": "1",
        },
        data=b"{}",
    )
    try:
        with _LOCAL_OPENER.open(request, timeout=timeout) as response:
            if response.status != 200 or response.geturl() != request.full_url:
                return False
            payload = json.loads(response.read(4097))
            return isinstance(payload, dict) and payload.get("instance_id") == instance_id
    except (OSError, HTTPError, URLError, ValueError, UnicodeError, json.JSONDecodeError):
        return False


def wait_for_existing_instance(
    workspace_db: Path,
    *,
    lease: DesktopInstanceLease | None = None,
    timeout: float = 90.0,
    poll_interval: float = 0.1,
) -> str | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = read_instance_state(workspace_db)
        port, instance_id = state.get("port"), state.get("instance_id")
        if isinstance(port, int) and isinstance(instance_id, str) and probe_instance(port, instance_id):
            return f"http://127.0.0.1:{port}/"
        if lease is not None and lease.acquire():
            return None
        time.sleep(poll_interval)
    return None
