from contextlib import contextmanager
import time

from fastapi.testclient import TestClient

from anima_prompt_studio_v3.api import create_api_runtime
from test_reference_import import collection


PREFIX = "/api/v3/reference-examples"


@contextmanager
def application(root):
    frontend = root / "v3/web/dist"
    frontend.mkdir(parents=True, exist_ok=True)
    (frontend / "index.html").write_text("<title>ANIMA</title>", encoding="utf-8")
    runtime = create_api_runtime(root / "reference.db", frontend_dist=frontend,
                                 workspace_db=root / "v3/.local/state/workspaces.db")
    with TestClient(runtime.app, base_url="http://127.0.0.1") as client:
        client.headers["Origin"] = "http://127.0.0.1"
        token = client.post("/api/v3/session/exchange", json={"bootstrap_token": runtime.bootstrap_token})
        client.headers["X-Anima-Session"] = token.json()["session_token"]
        yield client


def finished(client):
    deadline = time.monotonic() + 10
    while True:
        response = client.get(PREFIX + "/local-sync")
        assert response.status_code == 200, response.text
        result = response.json()
        if result["status"] not in {"idle", "scanning"}:
            return result
        assert time.monotonic() < deadline, result
        time.sleep(0.01)


def add_collection(root, target):
    source, _ = collection(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)


def test_startup_discovers_project_collection_and_imports_without_click(tmp_path):
    add_collection(tmp_path, tmp_path / "anima-ref")
    with application(tmp_path) as client:
        status = finished(client)
        assert status["status"] == "ready"
        assert status["counts"]["created"] == 1
        page = client.get(PREFIX).json()
        assert len(page["items"]) == 1
        assert page["items"][0]["origin"] == "research_import"
        assert client.get(PREFIX + "/facets").json()["count"] == 1


def test_rescan_discovers_collection_added_after_start_and_does_not_duplicate(tmp_path):
    with application(tmp_path) as client:
        assert finished(client)["status"] == "missing"
        add_collection(tmp_path, tmp_path / "anima-ref")
        first = client.post(PREFIX + "/local-sync", json={})
        assert first.status_code == 200
        assert finished(client)["counts"]["created"] == 1
        client.post(PREFIX + "/local-sync", json={})
        second = finished(client)
        assert second["counts"]["created"] == 0
        assert second["counts"]["unchanged"] == 1
        assert len(client.get(PREFIX).json()["items"]) == 1


def test_data_directory_collection_is_found_without_project_layout(tmp_path):
    add_collection(tmp_path, tmp_path / "data/anima-ref")
    runtime = create_api_runtime(tmp_path / "reference.db", workspace_db=tmp_path / "data/workspaces.db")
    with TestClient(runtime.app, base_url="http://127.0.0.1") as client:
        client.headers["Origin"] = "http://127.0.0.1"
        token = client.post("/api/v3/session/exchange", json={"bootstrap_token": runtime.bootstrap_token})
        client.headers["X-Anima-Session"] = token.json()["session_token"]
        assert finished(client)["counts"]["created"] == 1


def test_scan_does_not_search_unrelated_parent_or_working_directory(tmp_path, monkeypatch):
    add_collection(tmp_path, tmp_path / "unrelated/anima-ref")
    monkeypatch.chdir(tmp_path / "unrelated")
    with application(tmp_path / "app") as client:
        assert finished(client)["status"] == "missing"
        assert client.get(PREFIX).json()["items"] == []


def test_rescan_auth_origin_and_empty_payload_are_enforced(tmp_path):
    with application(tmp_path) as client:
        status = finished(client)
        for payload in ({"path": str(tmp_path)}, {"force": True}):
            assert client.post(PREFIX + "/local-sync", json=payload).status_code == 422
        assert client.get(PREFIX + "/local-sync").json()["run_id"] == status["run_id"]
        assert client.post(PREFIX + "/local-sync", json={}, headers={"Origin": "https://example.com"}).status_code == 403
        client.headers.pop("X-Anima-Session")
        client.cookies.clear()
        assert client.get(PREFIX + "/local-sync").status_code == 401
        assert client.post(PREFIX + "/local-sync", json={}).status_code == 401


def test_invalid_local_collection_does_not_prevent_startup_or_leak_paths(tmp_path):
    source = tmp_path / "anima-ref/batches"
    source.mkdir(parents=True)
    (source / "01.json").write_text("broken", encoding="utf-8")
    with application(tmp_path) as client:
        assert finished(client)["status"] == "error"
        assert str(tmp_path) not in client.get(PREFIX + "/local-sync").text
        assert client.get(PREFIX).json()["items"] == []


def test_frozen_application_discovers_executable_neighbor_and_prefers_its_data_directory(tmp_path, monkeypatch):
    from anima_prompt_studio_v3.api import reference_sync

    installed = tmp_path / "install"
    installed.mkdir()
    add_collection(tmp_path, installed / "anima-ref")
    monkeypatch.setattr(reference_sync.sys, "frozen", True, raising=False)
    monkeypatch.setattr(reference_sync.sys, "executable", str(installed / "ANIMA.exe"))
    database = tmp_path / "data/workspaces.db"
    assert reference_sync.local_reference_source(database, None) == installed / "anima-ref"
    local_source = database.parent / "anima-ref"
    local_source.mkdir(parents=True)
    assert reference_sync.local_reference_source(database, None) == local_source
