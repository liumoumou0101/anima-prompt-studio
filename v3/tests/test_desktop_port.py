import json
from pathlib import Path
import socket
from urllib.request import Request, urlopen

import pytest

from anima_prompt_studio_v3.api import LocalApiServer
from anima_prompt_studio_v3.tools import run_desktop


def prepare_desktop(tmp_path, monkeypatch):
    frontend = tmp_path / "web"
    frontend.mkdir()
    (frontend / "index.html").write_text("<!doctype html><title>ANIMA</title>", encoding="utf-8")
    monkeypatch.setattr(run_desktop, "ensure_active_pack", lambda *_args: tmp_path / "reference.db")
    event = run_desktop.threading.Event()
    event.set()
    return {"data_root": tmp_path / "data", "frontend_dist": frontend,
            "workspace_db": tmp_path / "state/workspaces.db", "open_browser": False, "wait_event": event}


def test_desktop_restarts_on_same_port_with_new_server_credentials(tmp_path: Path, monkeypatch):
    arguments = prepare_desktop(tmp_path, monkeypatch)
    ports, tokens = [], []

    class ObservedServer(LocalApiServer):
        def __enter__(self):
            super().__enter__()
            ports.append(self.port)
            if tokens:
                assert not self.runtime.app.state.sessions.validate(tokens[-1])
            request = Request(self.base_url + "/api/v3/session/exchange", method="POST",
                              headers={"Origin": self.base_url, "Content-Type": "application/json"},
                              data=json.dumps({"bootstrap_token": self.runtime.bootstrap_token}).encode())
            with urlopen(request, timeout=5) as response:
                token = json.loads(response.read())["session_token"]
            tokens.append(token)
            with urlopen(Request(self.base_url + "/api/v3/bootstrap", headers={"X-Anima-Session": token}), timeout=5) as response:
                assert response.status == 200
            return self

    monkeypatch.setattr(run_desktop, "LocalApiServer", ObservedServer)
    assert run_desktop.run(**arguments) == 0
    assert run_desktop.read_desktop_port(arguments["workspace_db"]) == ports[0]
    assert run_desktop.run(**arguments) == 0
    assert len(ports) == 2 and ports[0] == ports[1]
    assert tokens[0] != tokens[1]
    state = json.loads(run_desktop.desktop_port_state_path(arguments["workspace_db"]).read_text(encoding="utf-8"))
    assert state["schema"] == "anima-local-api-port/1"
    assert state["port"] == ports[0]
    assert len(state["instance_id"]) >= 32


def test_occupied_desktop_port_falls_back_and_preserves_other_listener(tmp_path: Path, monkeypatch, capsys):
    arguments = prepare_desktop(tmp_path, monkeypatch)
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        occupied = blocker.getsockname()[1]
        run_desktop.save_desktop_port(arguments["workspace_db"], occupied)
        assert run_desktop.run(**arguments) == 0
        assert run_desktop.read_desktop_port(arguments["workspace_db"]) != occupied
        assert "本地地址已改为" in capsys.readouterr().out
        # A normal client must still reach the original socket after fallback.
        with socket.create_connection(("127.0.0.1", occupied), timeout=2):
            connection, _address = blocker.accept()
            connection.close()
    finally:
        blocker.close()


@pytest.mark.parametrize("state", [None, [], {"schema": "wrong", "port": 9534},
                                      *({"schema": "anima-local-api-port/1", "port": value}
                                        for value in (0, -1, 65536, True, "9534", 9534.5))])
def test_invalid_port_state_is_ignored(tmp_path: Path, state):
    workspace = tmp_path / "workspaces.db"
    path = run_desktop.desktop_port_state_path(workspace)
    path.write_text(json.dumps(state), encoding="utf-8")
    assert run_desktop.read_desktop_port(workspace) == 0


def test_corrupt_state_does_not_prevent_desktop_start_and_is_replaced(tmp_path: Path, monkeypatch):
    arguments = prepare_desktop(tmp_path, monkeypatch)
    path = run_desktop.desktop_port_state_path(arguments["workspace_db"])
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xffbroken-json")
    assert run_desktop.run(**arguments) == 0
    assert 1 <= run_desktop.read_desktop_port(arguments["workspace_db"]) <= 65535


def test_port_state_update_is_atomic_and_workspace_scoped(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "first.db"
    other = tmp_path / "second.db"
    run_desktop.save_desktop_port(workspace, 12345)
    assert run_desktop.read_desktop_port(other) == 0
    with monkeypatch.context() as patch:
        def fail_replace(*_args):
            raise OSError("injected failed replacement")
        patch.setattr(run_desktop.os, "replace", fail_replace)
        with pytest.raises(OSError):
            run_desktop.save_desktop_port(workspace, 12346)
    assert run_desktop.read_desktop_port(workspace) == 12345
    assert list(tmp_path.glob("*.tmp")) == []


def test_default_servers_remain_random_and_cannot_share_an_active_port(tmp_path: Path):
    with LocalApiServer(tmp_path / "reference.db") as first:
        assert first.preferred_port == 0
        with LocalApiServer(tmp_path / "reference.db", preferred_port=first.port) as second:
            assert first.port != second.port


@pytest.mark.parametrize("port", [-1, 65536, True, "9534"])
def test_invalid_preferred_port_is_rejected(tmp_path: Path, port):
    with pytest.raises(ValueError):
        LocalApiServer(tmp_path / "reference.db", preferred_port=port)
