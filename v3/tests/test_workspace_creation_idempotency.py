from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import sqlite3
import threading

from fastapi.testclient import TestClient
import pytest

from anima_prompt_studio_v3.api import create_api_runtime
from anima_prompt_studio_v3.api.workspace_store import (
    WorkspaceCreateConflictError, WorkspaceIdempotencyKeyError, WorkspaceStore,
)


def test_same_key_survives_reopen_and_preserves_later_edits(tmp_path: Path):
    path = tmp_path / "workspaces.db"
    draft = {"positive_text": "hatsune_miku", "model_profile": "anima_base_v1"}
    first = WorkspaceStore(path).create("角色参考", draft, idempotency_key="transfer:one")
    reopened = WorkspaceStore(path)
    assert reopened.create("角色参考", dict(reversed(list(draft.items()))), idempotency_key="transfer:one") == first
    edited = reopened.update(first["id"], expected_revision=1, title="后续修改", draft={"positive_text": "later edit"})
    assert WorkspaceStore(path).create("角色参考", draft, idempotency_key="transfer:one") == edited
    assert len(reopened.list()) == 1


def test_concurrent_same_key_creates_exactly_one_workspace(tmp_path: Path):
    path = tmp_path / "workspaces.db"
    stores = [WorkspaceStore(path) for _ in range(8)]
    barrier = threading.Barrier(len(stores))

    def create(store):
        barrier.wait(timeout=10)
        return store.create("same request", {"positive_text": "hatsune_miku"}, idempotency_key="transfer_concurrent")

    with ThreadPoolExecutor(max_workers=len(stores)) as pool:
        records = list(pool.map(create, stores))
    assert all(record == records[0] for record in records)
    with sqlite3.connect(path) as database:
        assert database.execute("SELECT count(*) FROM workspaces").fetchone()[0] == 1
        assert database.execute("SELECT count(*) FROM workspace_creations").fetchone()[0] == 1


@pytest.mark.parametrize("changed", ["title", "draft", "candidate_snapshot"])
def test_same_key_different_payload_conflicts_without_modification(tmp_path: Path, changed: str):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    payload = {"title": "original", "draft": {"positive_text": "first"}, "candidate_snapshot": None}
    first = store.create(**payload, idempotency_key="transfer_conflict")
    altered = deepcopy(payload)
    altered[changed] = {"title": "changed", "draft": {"positive_text": "second"}, "candidate_snapshot": {"note": "different"}}[changed]
    with pytest.raises(WorkspaceCreateConflictError) as caught:
        store.create(**altered, idempotency_key="transfer_conflict")
    assert caught.value.code == "idempotency_conflict"
    assert store.list() == [first]


def test_deleted_target_is_not_recreated_after_restart(tmp_path: Path):
    path = tmp_path / "workspaces.db"
    store = WorkspaceStore(path)
    first = store.create("deleted", {}, idempotency_key="transfer_deleted")
    store.delete(first["id"], expected_revision=1)
    with pytest.raises(WorkspaceCreateConflictError) as caught:
        WorkspaceStore(path).create("deleted", {}, idempotency_key="transfer_deleted")
    assert caught.value.code == "workspace_idempotency_target_deleted"
    assert store.list() == []
    with sqlite3.connect(path) as database:
        assert database.execute("SELECT count(*) FROM workspaces").fetchone()[0] == 1
        assert database.execute("SELECT count(*) FROM workspace_creations").fetchone()[0] == 1


@pytest.mark.parametrize("key", ["", "x" * 129, "has space", "line\nbreak", "tab\there", "\x00bad", "汉字", "-leading"])
def test_unsafe_keys_are_rejected_before_writing(tmp_path: Path, key: str):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    with pytest.raises(WorkspaceIdempotencyKeyError):
        store.create("invalid", {}, idempotency_key=key)
    assert store.list() == []


def test_failed_creation_rolls_back_workspace_and_key_together(tmp_path: Path, monkeypatch):
    path = tmp_path / "workspaces.db"
    store = WorkspaceStore(path)
    with monkeypatch.context() as patch:
        def fail(_row):
            raise RuntimeError("injected readback failure")
        patch.setattr(store, "_record", fail)
        with pytest.raises(RuntimeError, match="readback failure"):
            store.create("atomic", {}, idempotency_key="transfer_atomic")
    with sqlite3.connect(path) as database:
        assert database.execute("SELECT count(*) FROM workspaces").fetchone()[0] == 0
        assert database.execute("SELECT count(*) FROM workspace_creations").fetchone()[0] == 0
    assert store.create("atomic", {}, idempotency_key="transfer_atomic")["revision"] == 1


def test_api_creation_replay_conflict_deletion_and_legacy_behavior(tmp_path: Path):
    runtime = create_api_runtime(tmp_path / "reference.db", workspace_db=tmp_path / "workspaces.db")
    origin = "http://127.0.0.1:9534"
    with TestClient(runtime.app, base_url=origin) as client:
        client.headers["Origin"] = origin
        exchange = client.post("/api/v3/session/exchange", json={"bootstrap_token": runtime.bootstrap_token})
        client.headers["X-Anima-Session"] = exchange.json()["session_token"]
        body = {"title": "carried character", "draft": {"positive_text": "hatsune_miku"}}
        headers = {"Idempotency-Key": "transfer-api-1"}
        first = client.post("/api/v3/workspaces", json=body, headers=headers)
        replay = client.post("/api/v3/workspaces", json=body, headers=headers)
        assert first.status_code == replay.status_code == 201
        assert first.json() == replay.json()
        conflict = client.post("/api/v3/workspaces", json={**body, "title": "different"}, headers=headers)
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "idempotency_conflict"
        invalid = client.post("/api/v3/workspaces", json=body, headers={"Idempotency-Key": "unsafe key"})
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "invalid_idempotency_key"
        deleted = client.request("DELETE", "/api/v3/workspaces/" + first.json()["id"], json={"revision": 1})
        assert deleted.status_code == 204
        replay_deleted = client.post("/api/v3/workspaces", json=body, headers=headers)
        assert replay_deleted.status_code == 409
        assert replay_deleted.json()["error"]["code"] == "workspace_idempotency_target_deleted"
        # Older callers retain create-on-every-call behavior when no key is supplied.
        legacy_one = client.post("/api/v3/workspaces", json=body)
        legacy_two = client.post("/api/v3/workspaces", json=body)
        assert legacy_one.status_code == legacy_two.status_code == 201
        assert legacy_one.json()["id"] != legacy_two.json()["id"]
