from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anima_prompt_studio_v3.api import LocalApiServer, SessionManager, create_api_runtime
from anima_prompt_studio_v3.api.security import SessionInvalidError
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
from anima_prompt_studio_v3.tools.run_desktop import verify_first_connection
from anima_prompt_studio_v3.tools import run_api, run_desktop


def test_active_session_uses_idle_timeout_and_recovery_survives_closed_tab(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("anima_prompt_studio_v3.api.security.time.monotonic", lambda: clock[0])
    manager = SessionManager(session_ttl=3600, recovery_ttl=20000)
    original = manager.exchange(manager.issue_bootstrap_token())
    for instant in (1800, 3599, 5400, 7200):
        clock[0] = instant
        assert manager.validate(original.token)
    clock[0] = 11001
    assert not manager.validate(original.token)
    recovered = manager.restore(recovery_token=original.recovery_token)
    assert recovered.token != original.token
    assert recovered.recovery_token == original.recovery_token
    assert manager.validate(recovered.token)
    clock[0] = 32000
    with pytest.raises(SessionInvalidError):
        manager.restore(recovery_token=original.recovery_token)


def test_restore_requires_secret_and_exact_origin_and_is_not_cacheable(tmp_path: Path):
    runtime = create_api_runtime(tmp_path / "missing.db")
    origin = "http://127.0.0.1:12345"
    client = TestClient(runtime.app, base_url=origin)
    endpoint = "/api/v3/session/restore"
    assert client.post(endpoint, json={}, headers={"Origin": origin}).status_code == 401
    exchanged = client.post("/api/v3/session/exchange", json={"bootstrap_token": runtime.bootstrap_token},
                            headers={"Origin": origin})
    assert exchanged.status_code == 200
    secret = exchanged.json()["recovery_token"]
    for unsafe in ("http://127.0.0.1:54321", "http://localhost:12345", "https://127.0.0.1:12345",
                   "https://evil.example", "null", "http://127.0.0.1:12345/path"):
        assert client.post(endpoint, json={}, headers={"Origin": unsafe, "X-Anima-Recovery": secret}).status_code == 403
    assert client.post(endpoint, json={}, headers={"X-Anima-Recovery": secret}).status_code == 403
    # Even manually copying the image cookie does not authorize recovery or API reads.
    cookie = exchanged.headers["set-cookie"].split(";", 1)[0]
    assert client.post(endpoint, json={}, headers={"Origin": origin, "Cookie": cookie}).status_code == 401
    assert client.get("/api/v3/bootstrap", headers={"Cookie": cookie}).status_code == 401
    restored = client.post(endpoint, json={}, headers={"Origin": origin, "X-Anima-Recovery": secret})
    assert restored.status_code == 200
    assert restored.headers["cache-control"] == "no-store"
    assert client.get("/api/v3/bootstrap", headers={"X-Anima-Session": restored.json()["session_token"]}).status_code == 200


def test_session_tokens_and_image_cookie_names_are_separate_for_each_server(tmp_path: Path):
    clients = []
    exchanges = []
    for port in (12345, 12346):
        runtime = create_api_runtime(tmp_path / "missing.db")
        origin = f"http://127.0.0.1:{port}"
        client = TestClient(runtime.app, base_url=origin)
        clients.append(client)
        exchanges.append(client.post("/api/v3/session/exchange", json={"bootstrap_token": runtime.bootstrap_token},
                                      headers={"Origin": origin}))
    assert exchanges[0].headers["set-cookie"].split("=", 1)[0] != exchanges[1].headers["set-cookie"].split("=", 1)[0]
    assert clients[1].post("/api/v3/session/restore", json={}, headers={
        "Origin": "http://127.0.0.1:12346", "X-Anima-Recovery": exchanges[0].json()["recovery_token"],
    }).status_code == 401
    # Current bearer clients can adopt recovery without re-opening the desktop launcher.
    upgraded = clients[0].post("/api/v3/session/restore", json={}, headers={
        "Origin": "http://127.0.0.1:12345", "X-Anima-Session": exchanges[0].json()["session_token"],
    })
    assert upgraded.status_code == 200
    assert upgraded.json()["recovery_token"]


def test_image_cookie_cannot_be_used_as_api_bearer_or_recovery(tmp_path: Path):
    class Gallery:
        def list_assets(self, **_kwargs):
            return {"items": []}

    origin = "http://127.0.0.1:9534"
    runtime = create_api_runtime(tmp_path / "reference.db", gallery_service=Gallery())
    client = TestClient(runtime.app, base_url=origin)
    exchanged = client.post("/api/v3/session/exchange", json={"bootstrap_token": runtime.bootstrap_token},
                            headers={"Origin": origin})
    image_token = exchanged.headers["set-cookie"].split(";", 1)[0].split("=", 1)[1]
    assert image_token != exchanged.json()["session_token"]
    assert client.get("/api/v3/gallery/assets").status_code == 200
    assert client.get("/api/v3/bootstrap", headers={"X-Anima-Session": image_token}).status_code == 401
    for header in ("X-Anima-Session", "X-Anima-Recovery"):
        assert client.post("/api/v3/session/restore", json={}, headers={"Origin": origin, header: image_token}).status_code == 401
    assert client.post("/api/v3/gallery/assets/state", json={"paths": ["test.png"], "state": "kept"},
                       headers={"Origin": origin}).status_code == 401
    manager = runtime.app.state.sessions
    manager.revoke(exchanged.json()["session_token"])
    assert not manager.validate_gallery(image_token)


def test_fresh_runtime_can_create_its_first_connection_over_real_http(tmp_path: Path):
    database = tmp_path / "new-user" / "runtime.db"
    assert not database.exists()
    with LocalApiServer(tmp_path / "reference.db", workspace_db=tmp_path / "workspace.db",
                        v2_database=database) as server:
        verify_first_connection(server)
    repository = SQLiteRepository(database)
    try:
        profiles = repository.list_remote_profiles()
        assert len(profiles) == 1
        assert profiles[0].connection_type == "local"
        assert profiles[0].enabled is False
        assert repository.get_setting("workflow_catalog_schema") == 1
    finally:
        repository.close()


def test_direct_api_initializes_requested_runtime_database(tmp_path: Path):
    database = tmp_path / "new-user" / "runtime.db"
    runtime = create_api_runtime(tmp_path / "missing.db", v2_database=database)
    client = TestClient(runtime.app, base_url="http://127.0.0.1")
    exchanged = client.post("/api/v3/session/exchange", json={"bootstrap_token": runtime.bootstrap_token},
                            headers={"Origin": "http://127.0.0.1"})
    assert client.get("/api/v3/settings/remote-profiles", headers={"X-Anima-Session": exchanged.json()["session_token"]}).json()["items"] == []
    assert database.is_file()


def test_desktop_fresh_runtime_path_is_not_silently_disabled(tmp_path: Path, monkeypatch):
    frontend = tmp_path / "web"
    frontend.mkdir()
    (frontend / "index.html").write_text("<!doctype html><title>ANIMA V3</title>", encoding="utf-8")
    monkeypatch.setattr(run_desktop, "ensure_active_pack", lambda *_args: tmp_path / "reference.db")
    event = run_desktop.threading.Event()
    event.set()
    database = tmp_path / "new-user" / "runtime.db"
    assert run_desktop.run(data_root=tmp_path / "data", frontend_dist=frontend,
                           workspace_db=tmp_path / "workspace.db", v2_database=database,
                           open_browser=False, wait_event=event, verify_runtime=True) == 0
    assert database.is_file()
    with pytest.raises(ValueError):
        run_desktop.run(data_root=tmp_path / "data", frontend_dist=frontend,
                        workspace_db=tmp_path / "workspace.db", v2_database=database,
                        open_browser=False, wait_event=event, verify_runtime=True)


def test_api_launcher_enables_runtime_unless_explicitly_disabled(tmp_path: Path, monkeypatch):
    captured = []

    class FakeServer:
        base_url = "http://127.0.0.1:12345"
        bootstrap_url = "http://127.0.0.1:12345/?bootstrap=test"

        def __init__(self, _reference, **kwargs):
            captured.append(kwargs["v2_database"])

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    class StopImmediately:
        def wait(self):
            pass

    monkeypatch.setattr(run_api, "LocalApiServer", FakeServer)
    monkeypatch.setattr(run_api.threading, "Event", StopImmediately)
    args = ["--reference-db", str(tmp_path / "reference.db"), "--workspace-db", str(tmp_path / "state/workspaces.db")]
    assert run_api.main(args) == 0
    assert captured == [tmp_path / "state/runtime.db"]
    assert captured[0].is_file()
    assert run_api.main([*args, "--without-runtime"]) == 0
    assert captured[-1] is None
