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
                """
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(workspaces)")}
            if "candidate_snapshot_json" not in columns:
                connection.execute("ALTER TABLE workspaces ADD COLUMN candidate_snapshot_json TEXT")

    def list(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT id,title,draft_json,candidate_snapshot_json,revision,created_at,updated_at
                   FROM workspaces WHERE deleted_at IS NULL
                   ORDER BY updated_at DESC LIMIT ?""",
                (limit,),
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
            connection.execute(
                """UPDATE workspaces SET title=?,draft_json=?,candidate_snapshot_json=?,revision=?,updated_at=?
                   WHERE id=? AND revision=? AND deleted_at IS NULL""",
                (title, serialized, serialized_snapshot, current_revision + 1, _utc_now(), workspace_id, current_revision),
            )
            updated = connection.execute("SELECT * FROM workspaces WHERE id=?", (workspace_id,)).fetchone()
            result = self._record(updated)
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
            projected = project_conversation(draft)
            for key in ("reference_preset_id", "session_previews", "compile_state"):
                projected.pop(key, None)
            connection.execute(
                "UPDATE workspaces SET draft_json=?,revision=?,updated_at=? WHERE id=?",
                (_serialize_draft(projected), expected_revision + 1, _utc_now(), workspace_id),
            )
            updated = connection.execute("SELECT * FROM workspaces WHERE id=?", (workspace_id,)).fetchone()
            result = self._record(updated)
        return result

    def delete(self, workspace_id: str, *, expected_revision: int) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT revision FROM workspaces WHERE id=? AND deleted_at IS NULL",
                (workspace_id,),
            ).fetchone()
            if row is None:
                raise WorkspaceNotFoundError(workspace_id)
            current_revision = int(row["revision"])
            if current_revision != expected_revision:
                raise WorkspaceRevisionConflictError(current_revision)
            now = _utc_now()
            connection.execute(
                """UPDATE workspaces SET revision=?,updated_at=?,deleted_at=?
                   WHERE id=? AND revision=? AND deleted_at IS NULL""",
                (current_revision + 1, now, now, workspace_id, current_revision),
            )

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


def _serialize_snapshot(snapshot: dict[str, Any] | None) -> str | None:
    if snapshot is None:
        return None
    return json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
