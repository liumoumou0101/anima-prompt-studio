from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import threading

from fastapi.testclient import TestClient
import pytest

from anima_prompt_studio_v3.api import create_api_runtime
from anima_prompt_studio_v3.api.workspace_store import (
    WorkspaceNotFoundError, WorkspaceRevisionConflictError, WorkspaceStore,
)
from anima_prompt_studio_v3.core.requirements import PromptEdit, Requirements, compile_prompt, dump


def test_versions_survive_restart_and_restore_creates_new_revision(tmp_path: Path):
    path = tmp_path / "workspaces.db"
    store = WorkspaceStore(path)
    first = store.create("original", {"positive_text": "first"}, {"note": "original candidate"})
    second = store.update(first["id"], expected_revision=1, title="edited", draft={"positive_text": "second"})
    third = store.transform(first["id"], expected_revision=2, operation=lambda draft: {**draft, "positive_text": "third"})
    reopened = WorkspaceStore(path)
    history = reopened.list_versions(first["id"])
    assert [item["revision"] for item in history] == [3, 2, 1]
    assert [item["draft"]["positive_text"] for item in history] == ["third", "second", "first"]
    assert all(item["created_at"] for item in history)
    assert reopened.list_versions(first["id"], limit=1, offset=1) == [history[1]]
    restored = reopened.restore(first["id"], expected_revision=3, source_revision=1)
    assert restored["revision"] == 4
    assert restored["title"] == "original"
    assert restored["draft"] == first["draft"]
    assert restored["candidate_snapshot"] == {"note": "original candidate"}
    assert [item["revision"] for item in reopened.list_versions(first["id"])] == [4, 3, 2, 1]
    assert reopened.get(first["id"]) == restored


def test_legacy_workspace_saves_available_baseline_without_inventing_history(tmp_path: Path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE workspaces (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, draft_json TEXT NOT NULL,
            revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT)""")
        db.execute("INSERT INTO workspaces VALUES(?,?,?,?,?,?,?)", (
            "workspace_legacy", "legacy", json.dumps({"positive_text": "known version"}),
            7, "2025-01-01", "2025-02-01", None))
    store = WorkspaceStore(path)
    store.update("workspace_legacy", expected_revision=7, title="new", draft={"positive_text": "changed"})
    history = store.list_versions("workspace_legacy")
    assert [item["revision"] for item in history] == [8, 7]
    assert history[1]["draft"]["positive_text"] == "known version"
    assert history[1]["created_at"] == "2025-02-01"


def test_restore_is_scoped_and_stale_restore_cannot_overwrite(tmp_path: Path):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    one = store.create("one", {"positive_text": "one"})
    two = store.create("two", {"positive_text": "two"})
    updated = store.update(two["id"], expected_revision=1, title="two", draft={"positive_text": "two new"})
    with pytest.raises(LookupError):
        store.restore(one["id"], expected_revision=1, source_revision=2)
    with pytest.raises(WorkspaceRevisionConflictError):
        store.restore(two["id"], expected_revision=1, source_revision=1)
    with pytest.raises(WorkspaceNotFoundError):
        store.list_versions("workspace_missing")
    assert store.get(one["id"]) == one
    assert store.get(two["id"]) == updated
    assert len(store.list_versions(one["id"])) == 1


def test_failed_snapshot_write_rolls_back_workspace_mutation(tmp_path: Path):
    path = tmp_path / "workspaces.db"
    store = WorkspaceStore(path)
    record = store.create("original", {"positive_text": "saved"})
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TRIGGER fail_history BEFORE INSERT ON workspace_versions
            WHEN NEW.revision = 2 BEGIN SELECT RAISE(ABORT, 'snapshot failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="snapshot failure"):
        store.update(record["id"], expected_revision=1, title="not saved", draft={"positive_text": "lost"})
    assert store.get(record["id"]) == record
    assert [item["revision"] for item in store.list_versions(record["id"])] == [1]


def test_restore_rotates_old_token_without_certifying_a_stale_prompt(tmp_path: Path):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    requirements = dump(Requirements.empty())
    edit = {"layers": requirements["layers"], "loras": []}
    edit["layers"]["subject"]["text"] = "cat"
    record = store.create("compiled", {"model_profile": "anima_base_v1", "requirements_edit": edit})
    def compile(draft):
        return {**draft, "compiled": compile_prompt(draft, PromptEdit(positive="cat", negative=""), source="llm")}
    fresh = store.transform(record["id"], expected_revision=1, operation=compile)
    changed = deepcopy(edit)
    changed["layers"]["subject"]["text"] = "dog"
    stale = store.update(record["id"], expected_revision=2, title="changed", draft={"requirements_edit": changed})
    assert stale["draft"]["compile_state"] == "stale"
    restored = store.restore(record["id"], expected_revision=3, source_revision=2)
    assert restored["draft"]["compile_state"] == "fresh"
    assert restored["draft"]["compiled"]["positive"] == "cat"
    assert restored["draft"]["compiled"]["compiled_token"] != fresh["draft"]["compiled"]["compiled_token"]
    restored_stale = store.restore(record["id"], expected_revision=4, source_revision=3)
    assert restored_stale["draft"]["compile_state"] == "stale"
    assert restored_stale["draft"]["compiled"]["compiled_token"] != stale["draft"]["compiled"]["compiled_token"]


def test_failed_acceptance_preserves_pending_proposal_and_current_draft(tmp_path: Path):
    path = tmp_path / "workspaces.db"
    store = WorkspaceStore(path)
    record = store.create("original", {"positive_text": "saved"})
    proposal = store.create_proposal(record["id"], expected_revision=1, draft={"positive_text": "AI"}, metadata={})
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TRIGGER fail_history BEFORE INSERT ON workspace_versions
            WHEN NEW.revision = 2 BEGIN SELECT RAISE(ABORT, 'snapshot failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="snapshot failure"):
        store.accept_proposal(record["id"], proposal["id"], expected_revision=1)
    assert store.get(record["id"]) == record
    assert store.get_proposal(record["id"]) == proposal
    assert len(store.list_versions(record["id"])) == 1


def test_proposal_is_durable_without_mutating_workspace_until_acceptance(tmp_path: Path):
    path = tmp_path / "workspaces.db"
    store = WorkspaceStore(path)
    record = store.create("original", {"positive_text": "saved"})
    draft = {**record["draft"], "positive_text": "proposed", "mode": "expand"}
    proposal = store.create_proposal(record["id"], expected_revision=1, draft=draft,
                                    metadata={"changed_layers": ["subject"], "warnings": ["review addition"]})
    assert proposal["workspace_id"] == record["id"]
    assert proposal["base_revision"] == 1
    assert proposal["draft"]["mode"] == "expand"
    assert proposal["changed_layers"] == ["subject"]
    assert proposal["warnings"] == ["review addition"]
    assert store.get(record["id"]) == record
    assert len(store.list_versions(record["id"])) == 1
    reopened = WorkspaceStore(path)
    assert reopened.get_proposal(record["id"]) == proposal
    accepted = reopened.accept_proposal(record["id"], proposal["id"], expected_revision=1)
    assert accepted["revision"] == 2
    assert accepted["draft"]["positive_text"] == "proposed"
    assert accepted["title"] == "original"
    assert reopened.get_proposal(record["id"]) is None
    assert [item["revision"] for item in reopened.list_versions(record["id"])] == [2, 1]


def test_discard_keeps_current_workspace_and_rejects_cross_workspace_proposal(tmp_path: Path):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    one = store.create("one", {"positive_text": "one"})
    two = store.create("two", {"positive_text": "two"})
    proposal = store.create_proposal(one["id"], expected_revision=1, draft=one["draft"], metadata={})
    with pytest.raises(LookupError):
        store.accept_proposal(two["id"], proposal["id"], expected_revision=1)
    with pytest.raises(LookupError):
        store.discard_proposal(two["id"], proposal["id"], expected_revision=1)
    assert store.get_proposal(one["id"]) == proposal
    store.discard_proposal(one["id"], proposal["id"], expected_revision=1)
    assert store.get_proposal(one["id"]) is None
    assert store.get(one["id"]) == one
    assert store.get(two["id"]) == two


def test_edit_invalidates_pending_proposal_and_stale_accept_cannot_overwrite(tmp_path: Path):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    record = store.create("one", {"positive_text": "saved"})
    proposal = store.create_proposal(record["id"], expected_revision=1, draft={"positive_text": "old AI"}, metadata={})
    updated = store.update(record["id"], expected_revision=1, title="edited", draft={"positive_text": "new user"})
    assert store.get_proposal(record["id"]) is None
    with pytest.raises(WorkspaceRevisionConflictError):
        store.accept_proposal(record["id"], proposal["id"], expected_revision=1)
    with pytest.raises((LookupError, WorkspaceRevisionConflictError)):
        store.accept_proposal(record["id"], proposal["id"], expected_revision=2)
    with pytest.raises(WorkspaceRevisionConflictError):
        store.create_proposal(record["id"], expected_revision=1, draft={}, metadata={})
    assert store.get(record["id"]) == updated


def test_accepted_proposal_replays_after_restart_without_creating_another_version(tmp_path: Path):
    path = tmp_path / "workspaces.db"
    store = WorkspaceStore(path)
    record = store.create("one", {"positive_text": "saved"})
    proposal = store.create_proposal(record["id"], expected_revision=1, draft={"positive_text": "accepted"}, metadata={})
    accepted = store.accept_proposal(record["id"], proposal["id"], expected_revision=1)
    reopened = WorkspaceStore(path)
    assert reopened.accept_proposal(record["id"], proposal["id"], expected_revision=1) == accepted
    assert [row["revision"] for row in reopened.list_versions(record["id"])] == [2, 1]
    updated = reopened.update(record["id"], expected_revision=2, title="later", draft={"positive_text": "newer edit"})
    with pytest.raises(WorkspaceRevisionConflictError):
        reopened.accept_proposal(record["id"], proposal["id"], expected_revision=1)
    assert reopened.get(record["id"]) == updated


def test_discard_replay_does_not_discard_new_pending_proposal(tmp_path: Path):
    path = tmp_path / "workspaces.db"
    store = WorkspaceStore(path)
    record = store.create("one", {"positive_text": "saved"})
    old = store.create_proposal(record["id"], expected_revision=1, draft={"positive_text": "old"}, metadata={})
    store.discard_proposal(record["id"], old["id"], expected_revision=1)
    latest = store.create_proposal(record["id"], expected_revision=1, draft={"positive_text": "new"}, metadata={})
    reopened = WorkspaceStore(path)
    reopened.discard_proposal(record["id"], old["id"], expected_revision=1)
    assert reopened.get_proposal(record["id"]) == latest
    with pytest.raises(LookupError):
        reopened.accept_proposal(record["id"], old["id"], expected_revision=1)
    assert reopened.get(record["id"]) == record


def test_empty_draft_rename_api_preserves_every_draft_field_and_candidate(tmp_path: Path):
    runtime = create_api_runtime(tmp_path / "reference.db", workspace_db=tmp_path / "workspaces.db")
    store = runtime.app.state.workspace_store
    original = store.create("old title", {"positive_text": "custom text", "excluded_text": "keep exclusion",
        "natural_text": "keep description", "model_profile": "anima_base_v1", "input_mode": "natural",
        "selected_tags": ["cat"], "suppressed_tags": ["dog"], "mode": "expand",
        "generation_settings": {"seed": "8798399215689017476", "steps": 43},
        "legacy_extension": {"key": "preserve"}}, {"old_snapshot": "preserve exactly"})
    origin = "http://127.0.0.1:9534"
    with TestClient(runtime.app, base_url=origin) as client:
        client.headers["Origin"] = origin
        exchange = client.post("/api/v3/session/exchange", json={"bootstrap_token": runtime.bootstrap_token})
        client.headers["X-Anima-Session"] = exchange.json()["session_token"]
        renamed = client.put("/api/v3/workspaces/" + original["id"],
            json={"title": "new title", "revision": 1, "draft": {}})
        assert renamed.status_code == 200
        assert renamed.json()["draft"] == original["draft"]
        assert renamed.json()["candidate_snapshot"] == original["candidate_snapshot"]
        assert renamed.json()["title"] == "new title"
        assert renamed.json()["revision"] == 2
        assert [row["title"] for row in store.list_versions(original["id"])] == ["new title", "old title"]


def test_concurrent_proposal_accept_and_edit_have_exactly_one_winner(tmp_path: Path):
    path = tmp_path / "workspaces.db"
    store = WorkspaceStore(path)
    record = store.create("one", {"positive_text": "saved"})
    proposal = store.create_proposal(record["id"], expected_revision=1, draft={"positive_text": "AI"}, metadata={})
    barrier = threading.Barrier(2)
    def mutate(kind):
        other = WorkspaceStore(path)
        barrier.wait(timeout=10)
        try:
            return (other.accept_proposal(record["id"], proposal["id"], expected_revision=1) if kind == "accept"
                    else other.update(record["id"], expected_revision=1, title="one", draft={"positive_text": "user"}))
        except WorkspaceRevisionConflictError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(mutate, ["accept", "edit"]))
    assert sum(result is not None for result in results) == 1
    assert store.get(record["id"])["revision"] == 2
    assert [item["revision"] for item in store.list_versions(record["id"])] == [2, 1]


def test_workspace_search_paginates_literal_titles_and_archive_is_recoverable(tmp_path: Path):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    first = store.create("cat 100%", {"positive_text": "first"})
    second = store.create("CAT two", {"positive_text": "second"})
    third = store.create("dog", {"positive_text": "third"})
    assert [row["id"] for row in store.list(q="cat", limit=1)] == [second["id"]]
    assert [row["id"] for row in store.list(q="cat", limit=1, offset=1)] == [first["id"]]
    assert [row["id"] for row in store.list(q="%")] == [first["id"]]
    store.delete(second["id"], expected_revision=1)
    assert [row["id"] for row in store.list(archived=True)] == [second["id"]]
    archived = store.list(archived=True)[0]
    assert archived["revision"] == 2
    with pytest.raises(WorkspaceRevisionConflictError):
        store.unarchive(second["id"], expected_revision=1)
    restored = store.unarchive(second["id"], expected_revision=2)
    assert restored["revision"] == 3
    assert restored["draft"] == second["draft"]
    assert store.list(archived=True) == []
    assert len(store.list()) == 3
    assert [item["revision"] for item in store.list_versions(second["id"])] == [3, 2, 1]


def test_workspace_history_proposal_archive_api_contracts(tmp_path: Path):
    runtime = create_api_runtime(tmp_path / "reference.db", workspace_db=tmp_path / "workspaces.db")
    origin = "http://127.0.0.1:9534"
    with TestClient(runtime.app, base_url=origin) as client:
        client.headers["Origin"] = origin
        exchanged = client.post("/api/v3/session/exchange", json={"bootstrap_token": runtime.bootstrap_token})
        client.headers["X-Anima-Session"] = exchanged.json()["session_token"]
        first = client.post("/api/v3/workspaces", json={"title": "cat", "draft": {"positive_text": "first"}}).json()
        second = client.post("/api/v3/workspaces", json={"title": "cat other", "draft": {}}).json()
        base = "/api/v3/workspaces/" + first["id"]
        assert client.get("/api/v3/workspaces", params={"q": "cat", "limit": 1, "offset": 1}).json()["items"][0]["id"] == first["id"]
        assert client.get(base + "/versions").json()["items"][0]["revision"] == 1
        assert client.get(base + "/proposal").json() == {"proposal": None}
        proposal = runtime.app.state.workspace_store.create_proposal(first["id"], expected_revision=1,
            draft={"positive_text": "proposal"}, metadata={})
        assert client.get(base + "/proposal").json()["proposal"] == proposal
        foreign = client.post(f"/api/v3/workspaces/{second['id']}/proposals/{proposal['id']}/accept", json={"revision": 1})
        assert foreign.status_code == 404
        accepted = client.post(base + f"/proposals/{proposal['id']}/accept", json={"revision": 1})
        assert accepted.status_code == 200
        assert accepted.json()["revision"] == 2
        replay = client.post(base + f"/proposals/{proposal['id']}/accept", json={"revision": 1})
        assert replay.status_code == 200
        assert replay.json() == accepted.json()
        stale = client.post(base + "/restore", json={"revision": 1, "source_revision": 1})
        assert stale.status_code == 409
        restored = client.post(base + "/restore", json={"revision": 2, "source_revision": 1})
        assert restored.status_code == 200
        assert restored.json()["revision"] == 3
        assert restored.json()["draft"]["positive_text"] == "first"
        missing = client.post(base + "/restore", json={"revision": 3, "source_revision": 999})
        assert missing.status_code == 404
        assert client.get(base + "/versions", params={"limit": 1, "offset": 1}).json()["items"][0]["revision"] == 2
        pending = runtime.app.state.workspace_store.create_proposal(first["id"], expected_revision=3,
            draft={"positive_text": "discard"}, metadata={})
        assert client.request("DELETE", base + f"/proposals/{pending['id']}", json={"revision": 3}).json() == {"ok": True}
        assert client.request("DELETE", base + f"/proposals/{pending['id']}", json={"revision": 3}).json() == {"ok": True}
        assert client.request("DELETE", base, json={"revision": 3}).status_code == 204
        assert client.get("/api/v3/workspaces", params={"archived": True}).json()["items"][0]["revision"] == 4
        unarchived = client.post(base + "/unarchive", json={"revision": 4})
        assert unarchived.status_code == 200
        assert unarchived.json()["revision"] == 5
        assert client.get("/api/v3/workspaces", params={"offset": -1}).status_code == 422
