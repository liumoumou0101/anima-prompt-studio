from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import time
from types import SimpleNamespace

import pytest

from anima_prompt_studio_v3.api import LocalApiServer
from anima_prompt_studio_v3.tools import run_desktop
from anima_prompt_studio_v3.tools.desktop_single_instance import (
    DesktopInstanceLease,
    probe_instance,
    wait_for_existing_instance,
)


def test_workspace_lock_is_exclusive_and_reusable(tmp_path: Path) -> None:
    workspace = tmp_path / "state" / "workspaces.db"
    first = DesktopInstanceLease(workspace)
    second = DesktopInstanceLease(workspace)

    assert first.acquire() is True
    assert second.acquire() is False
    first.close()
    assert second.acquire() is True
    second.close()


def test_workspace_lock_is_exclusive_across_processes_and_released_on_exit(tmp_path: Path) -> None:
    workspace = tmp_path / "state" / "workspaces.db"
    ready, release = tmp_path / "ready", tmp_path / "release"
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(filter(None, [
        str(root / "src"), str(root / "v3" / "src"), environment.get("PYTHONPATH", ""),
    ]))
    script = (
        "import sys,time\n"
        "from pathlib import Path\n"
        "from anima_prompt_studio_v3.tools.desktop_single_instance import DesktopInstanceLease\n"
        "lease=DesktopInstanceLease(Path(sys.argv[1])); assert lease.acquire()\n"
        "Path(sys.argv[2]).write_text('ready')\n"
        "while not Path(sys.argv[3]).exists(): time.sleep(.02)\n"
        "lease.close()\n"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(workspace), str(ready), str(release)],
        cwd=root,
        env=environment,
    )
    contender = DesktopInstanceLease(workspace)
    try:
        deadline = time.monotonic() + 5
        while not ready.is_file() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.is_file()
        assert contender.acquire() is False
        release.write_text("release", encoding="utf-8")
        assert child.wait(timeout=5) == 0
        assert contender.acquire() is True
    finally:
        release.touch()
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        contender.close()


def test_waiter_takes_over_when_starting_instance_exits(tmp_path: Path) -> None:
    workspace = tmp_path / "state" / "workspaces.db"
    owner = DesktopInstanceLease(workspace)
    waiter = DesktopInstanceLease(workspace)
    assert owner.acquire() is True
    result: list[str | None] = []
    thread = Thread(target=lambda: result.append(wait_for_existing_instance(
        workspace, lease=waiter, timeout=2, poll_interval=0.02,
    )))
    thread.start()
    time.sleep(0.1)
    owner.close()
    thread.join(timeout=3)
    try:
        assert not thread.is_alive()
        assert result == [None]
        assert waiter.held is True
    finally:
        waiter.close()


def test_instance_probe_requires_exact_random_identity(tmp_path: Path) -> None:
    with LocalApiServer(
        tmp_path / "missing.db",
        allow_local_sessions=True,
        desktop_instance_id="instance-identity-1234567890",
    ) as server:
        assert probe_instance(server.port, "instance-identity-1234567890") is True
        assert probe_instance(server.port, "different-identity-123456789") is False


def test_instance_probe_rejects_foreign_identity_and_redirect() -> None:
    expected = "instance-identity-1234567890"

    class Handler(BaseHTTPRequestHandler):
        redirect = False

        def do_POST(self):
            if self.redirect and self.path == "/api/v3/desktop/instance":
                self.send_response(302)
                self.send_header("Location", "/actual")
                self.end_headers()
                return
            payload = json.dumps({"instance_id": expected if self.path == "/actual" else "foreign-identity-123456789"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert probe_instance(server.server_port, expected) is False
        Handler.redirect = True
        assert probe_instance(server.server_port, expected) is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_second_launcher_reuses_verified_clean_url_without_starting_server(tmp_path: Path, monkeypatch) -> None:
    frontend = tmp_path / "web"
    frontend.mkdir()
    (frontend / "index.html").write_text("<!doctype html>", encoding="utf-8")
    workspace = tmp_path / "state" / "workspaces.db"
    opened: list[str] = []

    monkeypatch.setattr(run_desktop.DesktopInstanceLease, "acquire", lambda _self: False)
    monkeypatch.setattr(run_desktop, "wait_for_existing_instance",
                        lambda _workspace, **_kwargs: "http://127.0.0.1:45678/")
    monkeypatch.setattr(run_desktop.webbrowser, "open", lambda url, new=0: opened.append(url) or True)
    monkeypatch.setattr(run_desktop, "ensure_active_pack",
                        lambda *_args: (_ for _ in ()).throw(AssertionError("must not initialize data")))

    assert run_desktop.run(data_root=tmp_path / "data", frontend_dist=frontend,
                           workspace_db=workspace, open_browser=True) == 0
    assert opened == ["http://127.0.0.1:45678/"]


def test_primary_launcher_publishes_instance_identity_and_enables_local_sessions(tmp_path: Path, monkeypatch) -> None:
    frontend = tmp_path / "web"
    frontend.mkdir()
    (frontend / "index.html").write_text("<!doctype html>", encoding="utf-8")
    workspace = tmp_path / "state" / "workspaces.db"
    captured: list[dict] = []

    class FakeServer:
        port = 45679
        base_url = "http://127.0.0.1:45679"
        bootstrap_url = base_url + "/?bootstrap=secret"
        runtime = SimpleNamespace(bootstrap_token="secret")

        def __init__(self, _reference, **kwargs):
            captured.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(run_desktop, "LocalApiServer", FakeServer)
    monkeypatch.setattr(run_desktop, "ensure_active_pack", lambda *_args: tmp_path / "reference.db")
    stopped = run_desktop.threading.Event()
    stopped.set()

    assert run_desktop.run(data_root=tmp_path / "data", frontend_dist=frontend,
                           workspace_db=workspace, open_browser=False, wait_event=stopped) == 0
    state = json.loads(run_desktop.desktop_port_state_path(workspace).read_text(encoding="utf-8"))
    assert state["port"] == 45679
    assert state["instance_id"] == captured[0]["desktop_instance_id"]
    assert captured[0]["allow_local_sessions"] is True
    assert len(state["instance_id"]) >= 32


def test_state_publish_failure_stops_startup_and_releases_workspace_lock(tmp_path: Path, monkeypatch) -> None:
    frontend = tmp_path / "web"
    frontend.mkdir()
    (frontend / "index.html").write_text("<!doctype html>", encoding="utf-8")
    workspace = tmp_path / "state" / "workspaces.db"

    class FakeServer:
        port = 45680
        base_url = "http://127.0.0.1:45680"
        bootstrap_url = base_url + "/?bootstrap=secret"

        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(run_desktop, "LocalApiServer", FakeServer)
    monkeypatch.setattr(run_desktop, "ensure_active_pack", lambda *_args: tmp_path / "reference.db")
    monkeypatch.setattr(run_desktop, "save_instance_state",
                        lambda *_args: (_ for _ in ()).throw(OSError("injected")))

    with pytest.raises(RuntimeError, match="启动已安全停止"):
        run_desktop.run(data_root=tmp_path / "data", frontend_dist=frontend,
                        workspace_db=workspace, open_browser=False)
    lease = DesktopInstanceLease(workspace)
    try:
        assert lease.acquire() is True
    finally:
        lease.close()
