from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Callable
from uuid import uuid4

from ..core.requirements import apply_workspace_edit, project_conversation


class WorkspaceNotFoundError(LookupError):
    pass


class WorkspaceVersionNotFoundError(LookupError):
    pass


class WorkspaceProposalNotFoundError(LookupError):
    pass


class WorkspaceRevisionConflictError(RuntimeError):
    def __init__(self, current_revision: int) -> None:
        self.current_revision = current_revision
        super().__init__(f"工作台版本冲突；当前 revision={current_revision}。")


class WorkspaceIdempotencyKeyError(ValueError):
    pass


class WorkspaceCreateConflictError(ValueError):
    def __init__(self, message: str, *, code: str = "idempotency_conflict") -> None:
        self.code = code
        super().__init__(message)


class WorkspaceStore:
    """Small independent SQLite store for mutable user workspace state."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    draft_json TEXT NOT NULL,
                    candidate_snapshot_json TEXT,
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_workspaces_active_updated
                ON workspaces(deleted_at, updated_at DESC);
                CREATE TABLE IF NOT EXISTS workspace_creations (
                    idempotency_key TEXT PRIMARY KEY,
                    payload_hash TEXT NOT NULL,
                    workspace_id TEXT NOT NULL UNIQUE REFERENCES workspaces(id)
                );
                CREATE TABLE IF NOT EXISTS workspace_versions (
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                    revision INTEGER NOT NULL CHECK (revision >= 1),
                    title TEXT NOT NULL,
                    draft_json TEXT NOT NULL,
                    candidate_snapshot_json TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (workspace_id, revision)
                );
                CREATE TABLE IF NOT EXISTS workspace_proposals (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL UNIQUE REFERENCES workspaces(id),
                    base_revision INTEGER NOT NULL CHECK (base_revision >= 1),
                    draft_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workspace_proposal_decisions (
                    proposal_id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                    base_revision INTEGER NOT NULL,
                    decision TEXT NOT NULL CHECK (decision IN ('accepted', 'discarded')),
                    result_revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(workspaces)")}
            if "candidate_snapshot_json" not in columns:
                connection.execute("ALTER TABLE workspaces ADD COLUMN candidate_snapshot_json TEXT")

    def list(self, *, limit: int = 50, offset: int = 0, q: str = "",
             archived: bool = False) -> list[dict[str, Any]]:
        search = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT id,title,draft_json,candidate_snapshot_json,revision,created_at,updated_at
                   FROM workspaces WHERE (deleted_at IS NOT NULL)=?
                   AND title LIKE ? ESCAPE char(92)
                   ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?""",
                (archived, f"%{search}%", limit, offset),
            ).fetchall()
        return [self._record(row) for row in rows]

    def create(
        self,
        title: str,
        draft: dict[str, Any],
        candidate_snapshot: dict[str, Any] | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if idempotency_key is not None and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", idempotency_key) is None:
            raise WorkspaceIdempotencyKeyError("Idempotency-Key 须为 1–128 个字母、数字或 . _ : -，并以字母或数字开头。")
        # Hash the caller's input, not the projected record containing server
        # defaults or generated fields. Equivalent JSON key order is harmless.
        payload_hash = hashlib.sha256(_serialize_draft({
            "title": title, "draft": draft, "candidate_snapshot": candidate_snapshot,
        }).encode("utf-8")).hexdigest() if idempotency_key is not None else None
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if idempotency_key is not None:
                previous = connection.execute(
                    "SELECT payload_hash,workspace_id FROM workspace_creations WHERE idempotency_key=?",
                    (idempotency_key,),
                ).fetchone()
                if previous is not None:
                    if previous["payload_hash"] != payload_hash:
                        raise WorkspaceCreateConflictError("同一幂等键不能用于不同的新建会话请求。")
                    existing = connection.execute("SELECT * FROM workspaces WHERE id=?", (previous["workspace_id"],)).fetchone()
                    if existing is None or existing["deleted_at"] is not None:
                        raise WorkspaceCreateConflictError("原请求创建的工作台已删除，不能重放；请重新发起操作。",
                                                           code="workspace_idempotency_target_deleted")
                    return self._record(existing)
            now = _utc_now()
            workspace_id = f"workspace_{uuid4().hex}"
            serialized = _serialize_draft(apply_workspace_edit(None, draft))
            serialized_snapshot = _serialize_snapshot(candidate_snapshot)
            connection.execute(
                """INSERT INTO workspaces(id,title,draft_json,candidate_snapshot_json,revision,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (workspace_id, title, serialized, serialized_snapshot, 1, now, now),
            )
            if idempotency_key is not None:
                connection.execute("INSERT INTO workspace_creations(idempotency_key,payload_hash,workspace_id) VALUES(?,?,?)",
                                   (idempotency_key, payload_hash, workspace_id))
            created = connection.execute("SELECT * FROM workspaces WHERE id=?", (workspace_id,)).fetchone()
            self._snapshot(connection, created)
            return self._record(created)

    def get(self, workspace_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT id,title,draft_json,candidate_snapshot_json,revision,created_at,updated_at
                   FROM workspaces WHERE id=? AND deleted_at IS NULL""",
                (workspace_id,),
            ).fetchone()
        if row is None:
            raise WorkspaceNotFoundError(workspace_id)
        return self._record(row)

    def update(
        self,
        workspace_id: str,
        *,
        expected_revision: int,
        title: str,
        draft: dict[str, Any],
        candidate_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        serialized_snapshot = _serialize_snapshot(candidate_snapshot)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM workspaces WHERE id=? AND deleted_at IS NULL",
                (workspace_id,),
            ).fetchone()
            if row is None:
                raise WorkspaceNotFoundError(workspace_id)
            current_revision = int(row["revision"])
            if current_revision != expected_revision:
                raise WorkspaceRevisionConflictError(current_revision)
            serialized = _serialize_draft(apply_workspace_edit(json.loads(row["draft_json"]), draft))
            result = self._save_revision(connection, row, title=title, draft_json=serialized,
                                         candidate_snapshot_json=serialized_snapshot)
        return result

    def transform(
        self, workspace_id: str, *, expected_revision: int,
        operation: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        """Internal short CAS. The callback MUST NOT perform network or slow IO."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM workspaces WHERE id=? AND deleted_at IS NULL", (workspace_id,),
            ).fetchone()
            if row is None:
                raise WorkspaceNotFoundError(workspace_id)
            if row["revision"] != expected_revision:
                raise WorkspaceRevisionConflictError(row["revision"])
            draft = operation(json.loads(row["draft_json"]))
            # Validate internal transitions as well as public input before commit.
            result = self._save_revision(connection, row, title=row["title"],
                draft_json=_serialize_draft(_persistent_draft(draft)),
                candidate_snapshot_json=row["candidate_snapshot_json"])
        return result

    def rename(self, workspace_id: str, *, expected_revision: int, title: str) -> dict[str, Any]:
        """Change only the title; do not project default-valued edit fields."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._require_row(connection, workspace_id, expected_revision)
            return self._save_revision(connection, row, title=title, draft_json=row["draft_json"],
                candidate_snapshot_json=row["candidate_snapshot_json"])

    def delete(self, workspace_id: str, *, expected_revision: int) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._require_row(connection, workspace_id, expected_revision)
            self._save_revision(connection, row, title=row["title"], draft_json=row["draft_json"],
                candidate_snapshot_json=row["candidate_snapshot_json"], deleted_at=_utc_now())

    def unarchive(self, workspace_id: str, *, expected_revision: int) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._require_row(connection, workspace_id, expected_revision, archived=True)
            return self._save_revision(connection, row, title=row["title"], draft_json=row["draft_json"],
                candidate_snapshot_json=row["candidate_snapshot_json"])

    def list_versions(self, workspace_id: str, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self._connect() as connection:
            self._require_row(connection, workspace_id)
            # An older database has only its current draft. Offer that actual
            # baseline without pretending event summaries contain old drafts.
            rows = connection.execute("""
                SELECT revision,title,draft_json,created_at FROM workspace_versions WHERE workspace_id=?
                UNION ALL
                SELECT revision,title,draft_json,updated_at FROM workspaces WHERE id=?
                    AND NOT EXISTS (SELECT 1 FROM workspace_versions
                        WHERE workspace_id=workspaces.id AND revision=workspaces.revision)
                ORDER BY revision DESC LIMIT ? OFFSET ?
            """, (workspace_id, workspace_id, limit, offset)).fetchall()
            return [{"revision": row["revision"], "title": row["title"],
                     "draft": project_conversation(json.loads(row["draft_json"])),
                     "created_at": row["created_at"]} for row in rows]

    def restore(self, workspace_id: str, *, expected_revision: int, source_revision: int) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = self._require_row(connection, workspace_id, expected_revision)
            self._snapshot(connection, current)
            source = connection.execute("SELECT * FROM workspace_versions WHERE workspace_id=? AND revision=?",
                                        (workspace_id, source_revision)).fetchone()
            if source is None:
                raise WorkspaceVersionNotFoundError(source_revision)
            draft = _persistent_draft(json.loads(source["draft_json"]))
            # Historical tokens cannot become active credentials again. The
            # restored prompt retains its original fresh/stale fingerprint.
            if draft.get("compiled"):
                draft["compiled"]["compiled_token"] = f"cmp_{uuid4().hex}"
            return self._save_revision(connection, current, title=source["title"],
                draft_json=_serialize_draft(draft), candidate_snapshot_json=source["candidate_snapshot_json"])

    def get_version(self, workspace_id: str, revision: int, *, include_archived: bool = False) -> dict[str, Any]:
        """Read an actual saved version, including a pre-history current baseline."""
        with self._connect() as connection:
            row = self._version_row(connection, workspace_id, revision, include_archived=include_archived)
            return {"revision": row["revision"], "title": row["title"],
                    "draft": project_conversation(json.loads(row["draft_json"]))}

    def fork_version(self, workspace_id: str, *, source_revision: int, idempotency_key: str,
                     title: str | None = None) -> dict[str, Any]:
        identity = {"kind": "workspace_version", "workspace_id": workspace_id,
                    "revision": source_revision, "title": title}
        payload_hash = self._snapshot_creation_hash(identity, idempotency_key)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = self._replay_snapshot_creation(connection, idempotency_key, payload_hash)
            if previous is not None:
                return previous
            source = self._version_row(connection, workspace_id, source_revision)
            draft = _persistent_draft(json.loads(source["draft_json"]))
            draft["workspace_origin"] = {"workspace_id": workspace_id, "revision": source_revision, "run_id": None}
            draft["conversation_events"] = []
            if draft.get("compiled"):
                # New workspace credentials must not revive the parent's token.
                # Keep its fingerprint, including stale state, unchanged.
                draft["compiled"]["compiled_token"] = f"cmp_{uuid4().hex}"
            return self._insert_snapshot_workspace(connection,
                title=title or f"{source['title']} · 版本 {source_revision} 分支"[:200], draft=draft,
                candidate_snapshot_json=source["candidate_snapshot_json"],
                idempotency_key=idempotency_key, payload_hash=payload_hash)

    def create_snapshot(self, title: str, draft: dict[str, Any], *, request_identity: dict[str, Any],
                        idempotency_key: str | None = None) -> dict[str, Any]:
        """Internal creation from trusted, validated state in one transaction."""
        payload_hash = self._snapshot_creation_hash(request_identity, idempotency_key)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = self._replay_snapshot_creation(connection, idempotency_key, payload_hash)
            if previous is not None:
                return previous
            return self._insert_snapshot_workspace(connection, title=title, draft=draft,
                candidate_snapshot_json=None, idempotency_key=idempotency_key, payload_hash=payload_hash)

    @staticmethod
    def _snapshot_creation_hash(identity: dict[str, Any], key: str | None) -> str:
        if key is not None and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", key) is None:
            raise WorkspaceIdempotencyKeyError("Idempotency-Key 须为 1–128 个字母、数字或 . _ : -，并以字母或数字开头。")
        return hashlib.sha256(_serialize_draft({"internal_creation": identity}).encode("utf-8")).hexdigest()

    def _replay_snapshot_creation(self, connection: sqlite3.Connection, key: str | None,
                                  payload_hash: str) -> dict[str, Any] | None:
        if key is None:
            return None
        previous = connection.execute("SELECT payload_hash,workspace_id FROM workspace_creations WHERE idempotency_key=?",
                                      (key,)).fetchone()
        if previous is None:
            return None
        if previous["payload_hash"] != payload_hash:
            raise WorkspaceCreateConflictError("同一幂等键不能用于不同的新建会话请求。")
        row = connection.execute("SELECT * FROM workspaces WHERE id=?", (previous["workspace_id"],)).fetchone()
        if row is None or row["deleted_at"] is not None:
            raise WorkspaceCreateConflictError("原请求创建的工作台已归档，不能重放；请恢复该会话或重新发起操作。",
                                               code="workspace_idempotency_target_deleted")
        return self._record(row)

    def _insert_snapshot_workspace(self, connection: sqlite3.Connection, *, title: str, draft: dict[str, Any],
                                   candidate_snapshot_json: str | None, idempotency_key: str | None,
                                   payload_hash: str) -> dict[str, Any]:
        now = _utc_now()
        workspace_id = f"workspace_{uuid4().hex}"
        serialized = _serialize_draft(_persistent_draft(draft))
        connection.execute("""INSERT INTO workspaces(id,title,draft_json,candidate_snapshot_json,revision,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?)""", (workspace_id, title, serialized, candidate_snapshot_json, 1, now, now))
        if idempotency_key is not None:
            connection.execute("INSERT INTO workspace_creations(idempotency_key,payload_hash,workspace_id) VALUES(?,?,?)",
                               (idempotency_key, payload_hash, workspace_id))
        row = connection.execute("SELECT * FROM workspaces WHERE id=?", (workspace_id,)).fetchone()
        self._snapshot(connection, row)
        return self._record(row)

    @staticmethod
    def _version_row(connection: sqlite3.Connection, workspace_id: str, revision: int,
                     *, include_archived: bool = False) -> sqlite3.Row:
        current = connection.execute("SELECT * FROM workspaces WHERE id=?", (workspace_id,)).fetchone()
        if current is None or (current["deleted_at"] is not None and not include_archived):
            raise WorkspaceNotFoundError(workspace_id)
        source = connection.execute("SELECT * FROM workspace_versions WHERE workspace_id=? AND revision=?",
                                    (workspace_id, revision)).fetchone()
        if source is not None:
            return source
        if current["revision"] == revision:
            return current
        raise WorkspaceVersionNotFoundError(revision)

    def create_proposal(self, workspace_id: str, *, expected_revision: int,
                        draft: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        serialized = _serialize_draft(_persistent_draft(draft))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_row(connection, workspace_id, expected_revision)
            proposal_id = f"proposal_{uuid4().hex}"
            connection.execute("""INSERT INTO workspace_proposals
                (id,workspace_id,base_revision,draft_json,metadata_json,created_at) VALUES(?,?,?,?,?,?)
                ON CONFLICT(workspace_id) DO UPDATE SET id=excluded.id,base_revision=excluded.base_revision,
                    draft_json=excluded.draft_json,metadata_json=excluded.metadata_json,created_at=excluded.created_at""",
                (proposal_id, workspace_id, expected_revision, serialized, _serialize_draft(metadata), _utc_now()))
            row = connection.execute("SELECT * FROM workspace_proposals WHERE id=?", (proposal_id,)).fetchone()
            return self._proposal_record(row)

    def get_proposal(self, workspace_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            current = self._require_row(connection, workspace_id)
            row = connection.execute("SELECT * FROM workspace_proposals WHERE workspace_id=? AND base_revision=?",
                                     (workspace_id, current["revision"])).fetchone()
            return self._proposal_record(row) if row is not None else None

    def accept_proposal(self, workspace_id: str, proposal_id: str, *, expected_revision: int) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if self._replay_proposal_decision(connection, workspace_id, proposal_id, expected_revision, "accepted"):
                return self._record(self._require_row(connection, workspace_id))
            current = self._require_row(connection, workspace_id, expected_revision)
            proposal = self._require_proposal(connection, workspace_id, proposal_id, expected_revision)
            result = self._save_revision(connection, current, title=current["title"],
                draft_json=_serialize_draft(_persistent_draft(json.loads(proposal["draft_json"]))),
                candidate_snapshot_json=current["candidate_snapshot_json"])
            self._save_proposal_decision(connection, workspace_id, proposal_id, expected_revision, "accepted", result["revision"])
            return result

    def discard_proposal(self, workspace_id: str, proposal_id: str, *, expected_revision: int) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if self._replay_proposal_decision(connection, workspace_id, proposal_id, expected_revision, "discarded"):
                return
            self._require_row(connection, workspace_id, expected_revision)
            self._require_proposal(connection, workspace_id, proposal_id, expected_revision)
            connection.execute("DELETE FROM workspace_proposals WHERE workspace_id=? AND id=?", (workspace_id, proposal_id))
            self._save_proposal_decision(connection, workspace_id, proposal_id, expected_revision, "discarded", expected_revision)

    def _replay_proposal_decision(self, connection: sqlite3.Connection, workspace_id: str, proposal_id: str,
                                  expected_revision: int, decision: str) -> bool:
        previous = connection.execute("SELECT * FROM workspace_proposal_decisions WHERE workspace_id=? AND proposal_id=?",
                                      (workspace_id, proposal_id)).fetchone()
        if previous is None:
            return False
        current = self._require_row(connection, workspace_id)
        if previous["decision"] != decision:
            raise WorkspaceProposalNotFoundError(proposal_id)
        if previous["base_revision"] != expected_revision or previous["result_revision"] != current["revision"]:
            raise WorkspaceRevisionConflictError(current["revision"])
        # Replaying an old receipt must never return an older draft over a
        # later user edit, or mutate a newer proposal at the same revision.
        return True

    @staticmethod
    def _save_proposal_decision(connection: sqlite3.Connection, workspace_id: str, proposal_id: str,
                                base_revision: int, decision: str, result_revision: int) -> None:
        connection.execute("""INSERT INTO workspace_proposal_decisions
            (proposal_id,workspace_id,base_revision,decision,result_revision,created_at) VALUES(?,?,?,?,?,?)""",
            (proposal_id, workspace_id, base_revision, decision, result_revision, _utc_now()))

    @staticmethod
    def _require_row(connection: sqlite3.Connection, workspace_id: str, expected_revision: int | None = None,
                     *, archived: bool = False) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM workspaces WHERE id=? AND (deleted_at IS NOT NULL)=?",
                                 (workspace_id, archived)).fetchone()
        if row is None:
            raise WorkspaceNotFoundError(workspace_id)
        if expected_revision is not None and row["revision"] != expected_revision:
            raise WorkspaceRevisionConflictError(row["revision"])
        return row

    @staticmethod
    def _require_proposal(connection: sqlite3.Connection, workspace_id: str, proposal_id: str,
                          expected_revision: int) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM workspace_proposals WHERE workspace_id=? AND id=?",
                                 (workspace_id, proposal_id)).fetchone()
        if row is None:
            raise WorkspaceProposalNotFoundError(proposal_id)
        if row["base_revision"] != expected_revision:
            raise WorkspaceRevisionConflictError(expected_revision)
        return row

    @staticmethod
    def _snapshot(connection: sqlite3.Connection, row: sqlite3.Row) -> None:
        connection.execute("""INSERT OR IGNORE INTO workspace_versions
            (workspace_id,revision,title,draft_json,candidate_snapshot_json,created_at) VALUES(?,?,?,?,?,?)""",
            (row["id"], row["revision"], row["title"], row["draft_json"], row["candidate_snapshot_json"], row["updated_at"]))

    def _save_revision(self, connection: sqlite3.Connection, row: sqlite3.Row, *, title: str,
                       draft_json: str, candidate_snapshot_json: str | None,
                       deleted_at: str | None = None) -> dict[str, Any]:
        self._snapshot(connection, row)
        connection.execute("""UPDATE workspaces SET title=?,draft_json=?,candidate_snapshot_json=?,
            revision=?,updated_at=?,deleted_at=? WHERE id=? AND revision=?""",
            (title, draft_json, candidate_snapshot_json, row["revision"] + 1, _utc_now(), deleted_at,
             row["id"], row["revision"]))
        updated = connection.execute("SELECT * FROM workspaces WHERE id=?", (row["id"],)).fetchone()
        self._snapshot(connection, updated)
        connection.execute("DELETE FROM workspace_proposals WHERE workspace_id=?", (row["id"],))
        return self._record(updated)

    @staticmethod
    def _proposal_record(row: sqlite3.Row) -> dict[str, Any]:
        metadata = json.loads(row["metadata_json"])
        return {"id": row["id"], "workspace_id": row["workspace_id"], "base_revision": row["base_revision"],
                "draft": project_conversation(json.loads(row["draft_json"])),
                "changed_layers": metadata.get("changed_layers", []), "warnings": metadata.get("warnings", []),
                "created_at": row["created_at"]}

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    @staticmethod
    def _record(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "draft": project_conversation(json.loads(row["draft_json"])),
            "candidate_snapshot": (
                json.loads(row["candidate_snapshot_json"])
                if row["candidate_snapshot_json"] else None
            ),
            "revision": row["revision"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


def _serialize_draft(draft: dict[str, Any]) -> str:
    return json.dumps(draft, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False)


def _persistent_draft(draft: dict[str, Any]) -> dict[str, Any]:
    projected = project_conversation(draft)
    for key in ("reference_preset_id", "session_previews", "compile_state"):
        projected.pop(key, None)
    return projected


def _serialize_snapshot(snapshot: dict[str, Any] | None) -> str | None:
    if snapshot is None:
        return None
    return json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
