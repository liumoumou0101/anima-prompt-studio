from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4


class WorkspaceNotFoundError(LookupError):
    pass


class WorkspaceRevisionConflictError(RuntimeError):
    def __init__(self, current_revision: int) -> None:
        self.current_revision = current_revision
        super().__init__(f"工作台版本冲突；当前 revision={current_revision}。")


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
    ) -> dict[str, Any]:
        now = _utc_now()
        workspace_id = f"workspace_{uuid4().hex}"
        serialized = _serialize_draft(draft)
        serialized_snapshot = _serialize_snapshot(candidate_snapshot)
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO workspaces(id,title,draft_json,candidate_snapshot_json,revision,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (workspace_id, title, serialized, serialized_snapshot, 1, now, now),
            )
        return self.get(workspace_id)

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
        serialized = _serialize_draft(draft)
        serialized_snapshot = _serialize_snapshot(candidate_snapshot)
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
            connection.execute(
                """UPDATE workspaces SET title=?,draft_json=?,candidate_snapshot_json=?,revision=?,updated_at=?
                   WHERE id=? AND revision=? AND deleted_at IS NULL""",
                (title, serialized, serialized_snapshot, current_revision + 1, _utc_now(), workspace_id, current_revision),
            )
        return self.get(workspace_id)

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
            "draft": json.loads(row["draft_json"]),
            "candidate_snapshot": (
                json.loads(row["candidate_snapshot_json"])
                if row["candidate_snapshot_json"] else None
            ),
            "revision": row["revision"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


def _serialize_draft(draft: dict[str, Any]) -> str:
    return json.dumps(draft, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _serialize_snapshot(snapshot: dict[str, Any] | None) -> str | None:
    if snapshot is None:
        return None
    return json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
