"""The acceptance journal shares the workspace database and its CAS transaction."""
from __future__ import annotations

import json

from ..api.workspace_store import WorkspaceNotFoundError, WorkspaceRevisionConflictError, _utc_now
from ..core.requirements import PromptEdit, WorkbenchError, compile_prompt, compile_state, dump


class IdempotencyConflict(ValueError):
    pass


class SubmissionStore:
    def __init__(self, workspaces):
        self.workspaces = workspaces
        with workspaces._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS generation_submissions(
                submission_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
                payload_hash TEXT NOT NULL, run_id TEXT NOT NULL UNIQUE,
                workspace_id TEXT, snapshot_json TEXT NOT NULL, response_json TEXT NOT NULL,
                dispatch_state TEXT NOT NULL CHECK(dispatch_state IN ('accepted','enqueued','failed','canceled')),
                error_code TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")

    @staticmethod
    def record(row):
        if row is None:
            return None
        result = dict(row)
        result["snapshot"] = json.loads(result.pop("snapshot_json"))
        result["response"] = json.loads(result.pop("response_json"))
        return result

    def lookup(self, key, payload_hash=None):
        with self.workspaces._connect() as db:
            row = db.execute("SELECT * FROM generation_submissions WHERE idempotency_key=?", (key,)).fetchone()
        if row and payload_hash is not None and row["payload_hash"] != payload_hash:
            raise IdempotencyConflict("同一幂等键不能用于不同请求。")
        return self.record(row)

    def list(self, state=None):
        with self.workspaces._connect() as db:
            rows = db.execute("SELECT * FROM generation_submissions" +
                              (" WHERE dispatch_state=?" if state else "") + " ORDER BY created_at",
                              (state,) if state else ()).fetchall()
        return [self.record(row) for row in rows]

    def for_runs(self, run_ids):
        if not run_ids:
            return []
        with self.workspaces._connect() as db:
            rows = db.execute("SELECT * FROM generation_submissions WHERE run_id IN (" +
                              ",".join("?" for _ in run_ids) + ") ORDER BY created_at", run_ids).fetchall()
        return [self.record(row) for row in rows]

    def workspace_run_ids(self, workspace_id):
        with self.workspaces._connect() as db:
            rows = db.execute("SELECT run_id FROM generation_submissions WHERE workspace_id=? ORDER BY created_at DESC",
                              (workspace_id,)).fetchall()
        return [row["run_id"] for row in rows]

    def accept(self, *, submission_id, key, payload_hash, run_id, snapshot, response,
               workspace_id=None, revision=None, token=None, prompt=None):
        with self.workspaces._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM generation_submissions WHERE idempotency_key=?", (key,)).fetchone()
            if old:
                if old["payload_hash"] != payload_hash:
                    raise IdempotencyConflict("同一幂等键不能用于不同请求。")
                return self.record(old)
            if workspace_id:
                row = db.execute("SELECT * FROM workspaces WHERE id=? AND deleted_at IS NULL", (workspace_id,)).fetchone()
                if row is None:
                    raise WorkspaceNotFoundError(workspace_id)
                if row["revision"] != revision:
                    raise WorkspaceRevisionConflictError(row["revision"])
                draft = json.loads(row["draft_json"])
                compiled = draft.get("compiled")
                if not compiled or compiled["compiled_token"] != token or compile_state(draft) != "fresh":
                    raise WorkbenchError("stale_compiled_prompt", "要求或编译版本已变化，请重新编译。")
                accepted_revision = revision
                if any(compiled[name] != value for name, value in dump(prompt).items()):
                    draft["compiled"] = compile_prompt(draft, prompt, source="user")
                    accepted_revision += 1
                    db.execute("UPDATE workspaces SET draft_json=?,revision=?,updated_at=? WHERE id=?",
                               (json.dumps(draft, ensure_ascii=False, allow_nan=False), accepted_revision, _utc_now(), workspace_id))
                # Derive the immutable source from the row actually compared under lock.
                snapshot.update(requirements=draft["requirements"], reference_pin=draft.get("reference_pin"),
                                mode=draft["mode"], compiled=draft["compiled"],
                                workspace_revision=accepted_revision, workspace_id=workspace_id)
                snapshot["provenance"].update(requirements=draft["requirements"],
                    reference_pin=draft.get("reference_pin"), mode=draft["mode"], compiled=draft["compiled"],
                    workspace_revision=accepted_revision, workspace_id=workspace_id)
                response.update(workspace_id=workspace_id, workspace_revision=accepted_revision,
                                compiled_token=draft["compiled"]["compiled_token"])
            now = _utc_now()
            db.execute("INSERT INTO generation_submissions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (submission_id, key, payload_hash, run_id, workspace_id,
                        json.dumps(snapshot, ensure_ascii=False, allow_nan=False),
                        json.dumps(response, ensure_ascii=False, allow_nan=False), "accepted", None, now, now))
            result = db.execute("SELECT * FROM generation_submissions WHERE submission_id=?", (submission_id,)).fetchone()
            return self.record(result)

    def mark(self, submission_id, state, error_code=None):
        with self.workspaces._connect() as db:
            db.execute("UPDATE generation_submissions SET dispatch_state=?,error_code=?,updated_at=? "
                       "WHERE submission_id=? AND dispatch_state NOT IN ('failed','canceled')",
                       (state, error_code, _utc_now(), submission_id))
