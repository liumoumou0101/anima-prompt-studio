from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import sqlite3
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from anima_prompt_studio_v3.api import create_api_runtime
from anima_prompt_studio_v3.api.workspace_store import WorkspaceStore, WorkspaceRevisionConflictError
from anima_prompt_studio_v3.storage.generation_submissions import SubmissionStore


@pytest.fixture
def store(tmp_path):
    return WorkspaceStore(tmp_path / "workspaces.db")


def workspace(store, positive="Original_Tag,\n  text ", negative="old_negative "):
    draft = {"model_profile": "anima_base_v1", "generation_settings": {"steps": 31, "seed": "42"},
             "custom_field": {"keep": True}}
    if positive is not None:
        draft["prompt_edit"] = {"positive": positive, "negative": negative}
    return store.create("original", draft, candidate_snapshot={"keep": "snapshot"})


def append(store, item, **overrides):
    args = {"transfer_id": "transfer-1", "expected_revision": item["revision"],
            "positive": " New_Tag,\n fragment ", "negative": " Bad_Tag "}
    args.update(overrides)
    return store.append_personal_prompt(item["id"], **args)


def edit(store, item, **changes):
    draft = deepcopy(item["draft"])
    draft.update(changes)
    return store.update(item["id"], expected_revision=item["revision"], title=item["title"], draft=draft,
                        candidate_snapshot=item["candidate_snapshot"])


def test_append_retry_after_lost_response_is_exactly_once(store):
    item = workspace(store)
    first = append(store, item)
    replay = append(WorkspaceStore(store.path), item)
    assert first["replayed"] is False and replay["replayed"] is True
    assert replay["workspace"] == first["workspace"]
    assert first["workspace"]["revision"] == 2
    compiled = first["workspace"]["draft"]["compiled"]
    assert compiled["positive"] == "Original_Tag,\n  text \n New_Tag,\n fragment "
    assert compiled["negative"] == "old_negative \n Bad_Tag "
    for key in ("model_profile", "generation_settings", "custom_field", "requirements"):
        assert first["workspace"]["draft"][key] == item["draft"][key]
    assert first["workspace"]["candidate_snapshot"] == item["candidate_snapshot"]
    assert first["receipt"]["can_undo"] is True
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT count(*) FROM workspace_prompt_transfers").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM workspace_versions").fetchone()[0] == 2


def test_retry_returns_latest_workspace_without_overwriting_later_edits(store):
    item = workspace(store)
    first = append(store, item)
    latest = edit(store, first["workspace"], prompt_edit={"positive": "later text", "negative": ""})
    replay = append(store, item)
    assert replay["workspace"] == latest
    assert replay["receipt"]["result_revision"] == 2
    assert replay["receipt"]["can_undo"] is False
    assert store.get_personal_prompt_transfer(item["id"], "transfer-1")["workspace"] == latest


@pytest.mark.parametrize("change", ["positive", "negative", "target"])
def test_key_reuse_with_other_payload_conflicts(store, change):
    item = workspace(store)
    append(store, item)
    target = workspace(store) if change == "target" else item
    with pytest.raises(ValueError) as caught:
        append(store, target, **({change: "different"} if change != "target" else {}))
    assert caught.value.code == "personal_prompt_transfer_conflict"
    assert store.get(item["id"])["revision"] == 2


def test_pending_proposal_and_revision_conflict_do_not_consume_transfer(store):
    item = workspace(store)
    proposal = store.create_proposal(item["id"], expected_revision=1, draft=item["draft"], metadata={})
    with pytest.raises(ValueError) as caught:
        append(store, item)
    assert caught.value.code == "workspace_proposal_pending"
    assert store.get_proposal(item["id"])["id"] == proposal["id"]
    store.discard_proposal(item["id"], proposal["id"], expected_revision=1)
    with pytest.raises(WorkspaceRevisionConflictError):
        append(store, item, expected_revision=9)
    assert append(store, item)["workspace"]["revision"] == 2


@pytest.mark.parametrize("original", [None, "original"])
def test_undo_preserves_settings_and_handles_original_empty_prompt(store, original):
    item = workspace(store, positive=original)
    appended = append(store, item)["workspace"]
    latest = edit(store, appended, generation_settings={"steps": 37, "seed": "100"}, model_profile="anima_aesthetic_v1")
    undone = store.undo_personal_prompt(item["id"], transfer_id="transfer-1", expected_revision=latest["revision"])
    assert undone["workspace"]["draft"]["compiled"] == item["draft"]["compiled"]
    assert undone["workspace"]["draft"]["generation_settings"] == {"steps": 37, "seed": "100"}
    assert undone["workspace"]["draft"]["model_profile"] == "anima_aesthetic_v1"
    assert undone["receipt"]["state"] == "undone"
    assert undone["receipt"]["can_undo"] is False
    assert undone["receipt"]["undo_revision"] == 4
    replay = store.undo_personal_prompt(item["id"], transfer_id="transfer-1", expected_revision=3)
    assert replay["replayed"] is True
    assert replay["workspace"] == undone["workspace"]


def test_undo_after_further_prompt_edit_is_rejected(store):
    item = workspace(store)
    latest = edit(store, append(store, item)["workspace"], prompt_edit={"positive": "new", "negative": ""})
    with pytest.raises(ValueError) as caught:
        store.undo_personal_prompt(item["id"], transfer_id="transfer-1", expected_revision=latest["revision"])
    assert caught.value.code == "personal_prompt_undo_conflict"
    assert store.get(item["id"]) == latest


def test_undone_transfer_never_reapplies(store):
    item = workspace(store)
    append(store, item)
    undone = store.undo_personal_prompt(item["id"], transfer_id="transfer-1", expected_revision=2)
    replay = append(WorkspaceStore(store.path), item)
    assert replay["workspace"] == undone["workspace"]
    assert replay["receipt"]["state"] == "undone"
    assert replay["replayed"] is True


@pytest.mark.parametrize("positive,negative", [("", ""), (" \n", "\t"), ("x" * 20001, ""), ("", "x" * 20001)],
                         ids=["empty", "whitespace", "positive-long", "negative-long"])
def test_invalid_payload_does_not_write(store, positive, negative):
    item = workspace(store)
    with pytest.raises(ValueError):
        append(store, item, positive=positive, negative=negative)
    assert store.get(item["id"]) == item


def test_negative_only_empty_target_is_rejected_without_consuming_transfer(store):
    item = workspace(store, positive=None)
    with pytest.raises(ValueError) as caught:
        append(store, item, positive="", negative="bad")
    assert str(caught.value) == "请先在工作台填写正向提示词，再追加这段负向内容"
    updated = edit(store, item, prompt_edit={"positive": "good", "negative": ""})
    result = append(store, updated, positive="", negative="bad")
    assert result["workspace"]["draft"]["compiled"]["positive"] == "good"
    assert result["workspace"]["draft"]["compiled"]["negative"] == "bad"


@pytest.mark.parametrize("field", ["positive", "negative"])
def test_combined_prompt_limit_is_validated_before_writing(store, field):
    item = workspace(store, positive="x" * 19999, negative="y" * 19999)
    with pytest.raises(ValueError):
        append(store, item, positive="ab" if field == "positive" else "", negative="ab" if field == "negative" else "")
    shorter = edit(store, item, prompt_edit={"positive": "x" * 19998, "negative": "y" * 19998})
    result = append(store, shorter, positive="z", negative="z")
    assert len(result["workspace"]["draft"]["compiled"]["positive"]) == 20000
    assert len(result["workspace"]["draft"]["compiled"]["negative"]) == 20000


def test_receipt_failure_rolls_back_workspace_revision(store):
    item = workspace(store)
    with sqlite3.connect(store.path) as db:
        db.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON workspace_prompt_transfers BEGIN SELECT RAISE(ABORT, 'receipt failed'); END")
    with pytest.raises(sqlite3.IntegrityError, match="receipt failed"):
        append(store, item)
    assert store.get(item["id"]) == item
    assert len(store.list_versions(item["id"])) == 1


def test_concurrent_retries_append_once(store):
    item = workspace(store)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: append(WorkspaceStore(store.path), item), range(4)))
    assert sum(not result["replayed"] for result in results) == 1
    assert all(result["workspace"]["revision"] == 2 for result in results)


@pytest.mark.parametrize("operation", ["append", "undo"])
def test_submission_accepted_after_busy_snapshot_blocks_mutation(tmp_path, operation):
    runtime = create_api_runtime(tmp_path / "reference.db", workspace_db=tmp_path / "workspaces.db")
    store = runtime.app.state.workspace_store
    item = workspace(store)
    if operation == "undo":
        item = append(store, item)["workspace"]
    journal = SubmissionStore(store)
    with store._connect() as connection:
        connection.execute("""INSERT INTO generation_submissions VALUES(
            's1','key1','hash1','run1',?,'{}','{}','enqueued',NULL,'now','now')""", (item["id"],))

    def read_run(run_id):
        # Deterministically accept a second submission after the first snapshot
        # has been read, before the append/undo can acquire its DB transaction.
        with store._connect() as connection:
            connection.execute("""INSERT INTO generation_submissions VALUES(
                's2','key2','hash2','run2',?,'{}','{}','accepted',NULL,'now','now')""", (item["id"],))
        return SimpleNamespace(state=SimpleNamespace(value="completed"))

    runtime.app.state.submission_service = SimpleNamespace(store=journal, queue=SimpleNamespace(get=read_run))
    with pytest.raises(ValueError) as caught:
        if operation == "append":
            append(store, item)
        else:
            store.undo_personal_prompt(item["id"], transfer_id="transfer-1", expected_revision=item["revision"])
    assert caught.value.code == "workspace_busy"
    assert store.get(item["id"]) == item
    with store._connect() as connection:
        receipts = connection.execute("SELECT state FROM workspace_prompt_transfers").fetchall()
    assert [receipt[0] for receipt in receipts] == ([] if operation == "append" else ["applied"])


def test_undo_receipt_failure_rolls_back_restoration(store):
    item = append(store, workspace(store))["workspace"]
    with store._connect() as connection:
        connection.execute("CREATE TRIGGER fail_undo BEFORE UPDATE ON workspace_prompt_transfers BEGIN SELECT RAISE(ABORT, 'undo failed'); END")
    with pytest.raises(sqlite3.IntegrityError, match="undo failed"):
        store.undo_personal_prompt(item["id"], transfer_id="transfer-1", expected_revision=2)
    assert store.get(item["id"]) == item
    assert store.get_personal_prompt_transfer(item["id"], "transfer-1")["receipt"]["state"] == "applied"


def test_api_session_receipts_errors_and_busy_generation(tmp_path):
    runtime = create_api_runtime(tmp_path / "reference.db", workspace_db=tmp_path / "workspaces.db")
    store = runtime.app.state.workspace_store
    item = workspace(store)
    url = f"/api/v3/workspaces/{item['id']}/personal-prompt-transfers"
    body = {"transfer_id": "api-1", "revision": 1, "positive": " New_Tag ", "negative": ""}
    with TestClient(runtime.app, base_url="http://127.0.0.1:9534") as client:
        client.headers["Origin"] = "http://127.0.0.1:9534"
        assert client.post(url, json=body).status_code == 401
        session = client.post("/api/v3/session/exchange", json={"bootstrap_token": runtime.bootstrap_token})
        client.headers["X-Anima-Session"] = session.json()["session_token"]
        assert client.get(url + "/api-1").status_code == 404
        runtime.app.state.conversation_service.active.add(item["id"])
        assert client.post(url, json=body).status_code == 409
        runtime.app.state.conversation_service.active.clear()
        run = SimpleNamespace(state=SimpleNamespace(value="running"))
        def read_run(run_id):
            # Generation acceptance holds the queue lock while writing this
            # database. Queue reads must happen before our write transaction.
            with sqlite3.connect(store.path, timeout=0) as connection:
                connection.execute("BEGIN IMMEDIATE")
            return run

        journal = SubmissionStore(store)
        with store._connect() as connection:
            connection.execute("""INSERT INTO generation_submissions VALUES(
                'submission-1','key-1','hash-1','run-1',?,'{}','{}','enqueued',NULL,'now','now')""", (item["id"],))
        runtime.app.state.submission_service = SimpleNamespace(store=journal, queue=SimpleNamespace(get=read_run))
        assert client.post(url, json=body).json()["error"]["code"] == "workspace_busy"
        run.state.value = "completed"
        first = client.post(url, json=body)
        assert first.status_code == 200, first.text
        assert first.json()["workspace"]["draft"]["compiled"]["positive"].endswith("\n New_Tag ")
        assert client.get(url + "/api-1").json()["receipt"]["can_undo"] is True
        assert client.post(url, json={**body, "negative": "other"}).status_code == 409
        assert client.post(url, json={**body, "transfer_id": "api-2"}).json()["error"]["code"] == "workspace_revision_conflict"
        assert client.post(url, json={**body, "positive": "x" * 20001}).status_code == 422
        runtime.app.state.conversation_service.active.add(item["id"])
        assert client.post(url, json=body).json()["replayed"] is True
        assert client.post(url + "/api-1/undo", json={"revision": 2}).status_code == 409
        runtime.app.state.conversation_service.active.clear()
        assert client.post(url + "/api-1/undo", json={"revision": 2}).status_code == 200
        assert client.get(url + "/api-1").json()["receipt"]["state"] == "undone"

