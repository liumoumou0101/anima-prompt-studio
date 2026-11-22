from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import sqlite3
import threading

from fastapi.testclient import TestClient
import pytest

from anima_prompt_studio_v3.api import create_api_runtime
from anima_prompt_studio_v3.api.workspace_store import (
    WorkspaceCreateConflictError, WorkspaceNotFoundError, WorkspaceStore,
    WorkspaceVersionNotFoundError,
)
from anima_prompt_studio_v3.core.requirements import PromptEdit, Requirements, WorkbenchError, compile_prompt, dump


def compiled_workspace(store):
    initial = store.create("蓝色外套", {"model_profile": "anima_base_v1", "requirements_edit": {
        "layers": dump(Requirements.empty().layers), "loras": []}}, {"candidate": "preserve"})
    def compile(draft):
        draft["requirements"]["layers"]["subject"]["text"] = "蓝色外套"
        draft["compiled"] = compile_prompt(draft, PromptEdit(positive="woman, blue coat", negative="text"), source="llm")
        return draft
    return store.transform(initial["id"], expected_revision=1, operation=compile)


def test_fork_saved_version_preserves_parent_and_creates_fresh_token(tmp_path):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    source = compiled_workspace(store)
    latest = store.update(source["id"], expected_revision=2, title="红色外套", draft={"prompt_edit": {
        "positive": "woman, red coat", "negative": "text"}})
    history = store.list_versions(source["id"])
    pending = store.create_proposal(source["id"], expected_revision=3, draft=latest["draft"], metadata={})
    branch = store.fork_version(source["id"], source_revision=2, idempotency_key="fork-blue")
    assert branch["id"] != source["id"]
    assert branch["revision"] == 1
    assert branch["draft"]["workspace_origin"] == {"workspace_id": source["id"], "revision": 2, "run_id": None}
    assert branch["draft"]["compiled"]["positive"] == "woman, blue coat"
    assert branch["draft"]["compiled"]["negative"] == "text"
    assert branch["draft"]["compiled"]["compiled_token"] != source["draft"]["compiled"]["compiled_token"]
    assert branch["draft"]["compile_state"] == "fresh"
    assert branch["candidate_snapshot"] == {"candidate": "preserve"}
    assert branch["draft"]["conversation_events"] == []
    assert store.get(source["id"]) == latest
    assert store.get_proposal(source["id"]) == pending
    assert store.list_versions(source["id"]) == history
    assert [item["revision"] for item in store.list_versions(branch["id"])] == [1]


def test_fork_stale_version_does_not_certify_prompt_and_records_immediate_parent(tmp_path):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    source = compiled_workspace(store)
    requirements = deepcopy(source["draft"]["requirements"])
    requirements.pop("contract"); requirements.pop("revision")
    requirements["layers"]["subject"]["text"] = "绿色外套"
    stale = store.update(source["id"], expected_revision=2, title="changed", draft={"requirements_edit": requirements})
    branch = store.fork_version(source["id"], source_revision=3, idempotency_key="fork-stale")
    assert branch["draft"]["compile_state"] == "stale"
    assert branch["draft"]["compiled"]["inputs_fingerprint"] == stale["draft"]["compiled"]["inputs_fingerprint"]
    child = store.fork_version(branch["id"], source_revision=1, idempotency_key="fork-child")
    assert child["draft"]["workspace_origin"] == {"workspace_id": branch["id"], "revision": 1, "run_id": None}


def test_fork_retries_survive_restart_and_parent_archive_without_duplicates(tmp_path):
    path = tmp_path / "workspaces.db"
    store = WorkspaceStore(path)
    source = compiled_workspace(store)
    branch = store.fork_version(source["id"], source_revision=2, title="支线", idempotency_key="retry-key")
    store.delete(source["id"], expected_revision=2)
    reopened = WorkspaceStore(path)
    assert reopened.fork_version(source["id"], source_revision=2, title="支线", idempotency_key="retry-key") == branch
    assert len(reopened.list()) == 1
    with pytest.raises(WorkspaceNotFoundError):
        reopened.fork_version(source["id"], source_revision=2, idempotency_key="new-key")
    with pytest.raises(WorkspaceCreateConflictError):
        reopened.fork_version(source["id"], source_revision=2, title="不同标题", idempotency_key="retry-key")
    reopened.delete(branch["id"], expected_revision=1)
    with pytest.raises(WorkspaceCreateConflictError):
        reopened.fork_version(source["id"], source_revision=2, title="支线", idempotency_key="retry-key")


def test_fork_missing_version_and_snapshot_failure_leave_no_partial_workspace(tmp_path):
    path = tmp_path / "workspaces.db"
    store = WorkspaceStore(path)
    source = compiled_workspace(store)
    with pytest.raises(WorkspaceVersionNotFoundError):
        store.fork_version(source["id"], source_revision=999, idempotency_key="invalid")
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TRIGGER fail_branch_history BEFORE INSERT ON workspace_versions
            WHEN NEW.revision = 1 BEGIN SELECT RAISE(ABORT, 'snapshot failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="snapshot failure"):
        store.fork_version(source["id"], source_revision=2, idempotency_key="failed-key")
    assert store.list() == [source]
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM workspace_creations").fetchone()[0] == 0


def test_fork_idempotency_is_atomic_between_parallel_clients(tmp_path):
    path = tmp_path / "workspaces.db"
    source = compiled_workspace(WorkspaceStore(path))
    barrier = threading.Barrier(2)
    def fork(_):
        store = WorkspaceStore(path)
        barrier.wait(timeout=10)
        return store.fork_version(source["id"], source_revision=2, idempotency_key="shared-request")
    with ThreadPoolExecutor(max_workers=2) as pool:
        left, right = list(pool.map(fork, [0, 1]))
    assert left == right
    assert len(WorkspaceStore(path).list()) == 2


def test_workspace_origin_cannot_be_forged_through_public_edits(tmp_path):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    origin = {"workspace_id": "workspace_fake", "revision": 1, "run_id": None}
    with pytest.raises(WorkbenchError, match="服务端维护"):
        store.create("fake", {"workspace_origin": origin})
    source = store.create("real", {})
    with pytest.raises(WorkbenchError, match="服务端维护"):
        store.update(source["id"], expected_revision=1, title="fake", draft={"workspace_origin": origin})


def test_fork_api_requires_key_and_validates_version_and_title(tmp_path):
    runtime = create_api_runtime(tmp_path / "reference.db", workspace_db=tmp_path / "workspaces.db")
    source = compiled_workspace(runtime.app.state.workspace_store)
    origin = "http://127.0.0.1:9534"
    with TestClient(runtime.app, base_url=origin) as client:
        client.headers["Origin"] = origin
        exchanged = client.post("/api/v3/session/exchange", json={"bootstrap_token": runtime.bootstrap_token})
        client.headers["X-Anima-Session"] = exchanged.json()["session_token"]
        base = f"/api/v3/workspaces/{source['id']}/versions"
        assert client.post(base + "/2/fork", json={}).status_code == 422
        assert client.post(base + "/2/fork", json={}, headers={"Idempotency-Key": "bad key"}).status_code == 422
        headers = {"Idempotency-Key": "api-fork"}
        response = client.post(base + "/2/fork", json={}, headers=headers)
        assert response.status_code == 201, response.text
        assert client.post(base + "/2/fork", json={}, headers=headers).json() == response.json()
        assert client.post(base + "/1/fork", json={}, headers=headers).status_code == 409
        assert client.post(base + "/2/fork", json={"title": " "}, headers=headers).status_code == 422
        assert client.post(base + "/0/fork", json={}, headers=headers).status_code == 422
        missing = client.post(base + "/999/fork", json={}, headers={"Idempotency-Key": "missing"})
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "workspace_version_not_found"
