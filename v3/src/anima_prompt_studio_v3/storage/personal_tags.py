"""Transactional SQLite storage for personal tags and categories."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from anima_prompt_studio_v3.core.personal_tags import (
    CategoryRecord, CategoryWrite, TagRecord, TagWrite, normalize_search,
)


class PersonalTagNotFoundError(LookupError):
    pass


class PersonalTagConflictError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _tag(row: sqlite3.Row) -> TagRecord:
    data = dict(row)
    data["aliases"] = json.loads(data["aliases"])
    data["source_metadata"] = json.loads(data["source_metadata"])
    data["needs_review"] = json.loads(data["needs_review"])
    data.pop("search_key", None)
    data.pop("display_sort", None)
    return TagRecord(**data)


def _category(row: sqlite3.Row) -> CategoryRecord:
    data = dict(row)
    data["source_metadata"] = json.loads(data["source_metadata"])
    data["needs_review"] = json.loads(data["needs_review"])
    return CategoryRecord(**data)


class PersonalTagStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError(f"Unsupported personal tag database version: {version}")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS library_meta (
                    id INTEGER PRIMARY KEY CHECK (id = 1), library_revision INTEGER NOT NULL
                );
                INSERT OR IGNORE INTO library_meta VALUES (1, 0);
                CREATE TABLE IF NOT EXISTS personal_categories (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, parent_id TEXT,
                    position INTEGER NOT NULL, revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
                    source_key TEXT, source_id TEXT, source_metadata TEXT NOT NULL DEFAULT '{}',
                    needs_review TEXT NOT NULL DEFAULT '[]',
                    FOREIGN KEY (parent_id) REFERENCES personal_categories(id)
                );
                CREATE INDEX IF NOT EXISTS personal_categories_parent ON personal_categories(parent_id);
                CREATE TABLE IF NOT EXISTS personal_tags (
                    id TEXT PRIMARY KEY, display_name TEXT NOT NULL, content TEXT NOT NULL,
                    aliases TEXT NOT NULL, category_id TEXT, kind TEXT NOT NULL,
                    notes TEXT NOT NULL, default_weight REAL NOT NULL,
                    search_key TEXT NOT NULL, display_sort TEXT NOT NULL, revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT,
                    source_key TEXT, source_id TEXT, source_metadata TEXT NOT NULL DEFAULT '{}',
                    needs_review TEXT NOT NULL DEFAULT '[]',
                    FOREIGN KEY (category_id) REFERENCES personal_categories(id)
                );
                CREATE INDEX IF NOT EXISTS personal_tags_category ON personal_tags(category_id);
                CREATE TABLE IF NOT EXISTS personal_compositions (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, items TEXT NOT NULL,
                    revision INTEGER NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, deleted_at TEXT
                );
                CREATE TABLE IF NOT EXISTS personal_draft (
                    id INTEGER PRIMARY KEY CHECK (id = 1), items TEXT NOT NULL,
                    revision INTEGER NOT NULL, updated_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO personal_draft VALUES (1, '[]', 0, '');
            """)
            db.execute("PRAGMA user_version = 1")

    @contextmanager
    def _connect(self, *, write: bool = False):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 5000")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @property
    def library_revision(self) -> int:
        with self._connect() as db:
            return db.execute("SELECT library_revision FROM library_meta WHERE id=1").fetchone()[0]

    @staticmethod
    def _bump(db: sqlite3.Connection) -> None:
        db.execute("UPDATE library_meta SET library_revision=library_revision+1 WHERE id=1")

    @staticmethod
    def _require(db: sqlite3.Connection, table: str, value_id: str) -> sqlite3.Row:
        row = db.execute(f"SELECT * FROM {table} WHERE id=?", (value_id,)).fetchone()
        if row is None:
            raise PersonalTagNotFoundError(value_id)
        return row

    @staticmethod
    def _revision(row: sqlite3.Row, expected: int) -> None:
        if row["revision"] != expected:
            raise PersonalTagConflictError(f"Expected revision {expected}, found {row['revision']}")

    @staticmethod
    def _category_available(db: sqlite3.Connection, category_id: str | None) -> None:
        if category_id is None:
            return
        row = PersonalTagStore._require(db, "personal_categories", category_id)
        if row["deleted_at"] is not None:
            raise ValueError("Cannot use a category in the trash")

    def get_tag(self, tag_id: str) -> TagRecord:
        with self._connect() as db:
            return _tag(self._require(db, "personal_tags", tag_id))

    def create_tag(self, value: TagWrite) -> TagRecord:
        value = TagWrite.model_validate(value)
        now, tag_id = _now(), str(uuid4())
        key = normalize_search(" ".join([value.display_name, value.content, *value.aliases]))
        with self._connect(write=True) as db:
            self._category_available(db, value.category_id)
            db.execute("""INSERT INTO personal_tags
                (id,display_name,content,aliases,category_id,kind,notes,default_weight,
                 search_key,display_sort,revision,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)""",
                (tag_id, value.display_name, value.content, _json(value.aliases), value.category_id,
                 value.kind, value.notes, value.default_weight, key, normalize_search(value.display_name), now, now))
            self._bump(db)
            return _tag(self._require(db, "personal_tags", tag_id))

    def update_tag(self, tag_id: str, value: TagWrite, *, expected_revision: int) -> TagRecord:
        value = TagWrite.model_validate(value)
        key = normalize_search(" ".join([value.display_name, value.content, *value.aliases]))
        with self._connect(write=True) as db:
            old = self._require(db, "personal_tags", tag_id)
            self._revision(old, expected_revision)
            self._category_available(db, value.category_id)
            db.execute("""UPDATE personal_tags SET display_name=?,content=?,aliases=?,category_id=?,
                kind=?,notes=?,default_weight=?,search_key=?,display_sort=?,revision=revision+1,updated_at=? WHERE id=?""",
                (value.display_name, value.content, _json(value.aliases), value.category_id,
                 value.kind, value.notes, value.default_weight, key, normalize_search(value.display_name), _now(), tag_id))
            self._bump(db)
            return _tag(self._require(db, "personal_tags", tag_id))

    def set_tag_deleted(self, tag_id: str, deleted: bool, *, expected_revision: int) -> TagRecord:
        with self._connect(write=True) as db:
            old = self._require(db, "personal_tags", tag_id)
            self._revision(old, expected_revision)
            if old["deleted_at"] is None and deleted or old["deleted_at"] is not None and not deleted:
                db.execute("UPDATE personal_tags SET deleted_at=?,revision=revision+1,updated_at=? WHERE id=?",
                           (_now() if deleted else None, _now(), tag_id))
                self._bump(db)
            return _tag(self._require(db, "personal_tags", tag_id))

    def list_tags(self, *, q: str = "", category_id: str | None = None,
                  include_descendants: bool = True, trash: bool = False,
                  offset: int = 0, limit: int = 60) -> dict:
        if not (0 <= offset) or not (1 <= limit <= 200):
            raise ValueError("offset must be nonnegative and limit must be 1..200")
        where = ["t.deleted_at IS NOT NULL" if trash else "t.deleted_at IS NULL"]
        params: list[object] = []
        if q:
            escaped = normalize_search(q).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where.append("t.search_key LIKE ? ESCAPE '\\'")
            params.append(f"%{escaped}%")
        if category_id is not None:
            if include_descendants:
                where.append("t.category_id IN (WITH RECURSIVE descendants(id) AS (SELECT ? UNION ALL SELECT c.id FROM personal_categories c JOIN descendants d ON c.parent_id=d.id) SELECT id FROM descendants)")
            else:
                where.append("t.category_id=?")
            params.append(category_id)
        clause = " AND ".join(where)
        with self._connect() as db:
            total = db.execute(f"SELECT count(*) FROM personal_tags t WHERE {clause}", params).fetchone()[0]
            rows = db.execute(f"SELECT t.* FROM personal_tags t WHERE {clause} ORDER BY t.display_sort, t.display_name, t.id LIMIT ? OFFSET ?",
                              [*params, limit, offset]).fetchall()
        return {"items": [_tag(row) for row in rows], "total": total, "offset": offset,
                "limit": limit, "has_more": offset + len(rows) < total}

    def list_categories(self, *, trash: bool = False) -> list[CategoryRecord]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM personal_categories WHERE deleted_at IS NOT NULL" if trash
                              else "SELECT * FROM personal_categories WHERE deleted_at IS NULL").fetchall()
        return sorted((_category(row) for row in rows), key=lambda x: (x.position, normalize_search(x.name), x.name, x.id))

    def create_category(self, value: CategoryWrite) -> CategoryRecord:
        value = CategoryWrite.model_validate(value)
        now, category_id = _now(), str(uuid4())
        with self._connect(write=True) as db:
            self._category_available(db, value.parent_id)
            db.execute("""INSERT INTO personal_categories
                (id,name,parent_id,position,revision,created_at,updated_at)
                VALUES (?,?,?,?,1,?,?)""", (category_id, value.name, value.parent_id, value.position, now, now))
            self._bump(db)
            return _category(self._require(db, "personal_categories", category_id))

    def update_category(self, category_id: str, value: CategoryWrite, *, expected_revision: int) -> CategoryRecord:
        value = CategoryWrite.model_validate(value)
        with self._connect(write=True) as db:
            old = self._require(db, "personal_categories", category_id)
            self._revision(old, expected_revision)
            self._category_available(db, value.parent_id)
            if value.parent_id is not None:
                ancestors = db.execute("""WITH RECURSIVE chain(id,parent_id) AS (
                    SELECT id,parent_id FROM personal_categories WHERE id=?
                    UNION ALL SELECT c.id,c.parent_id FROM personal_categories c JOIN chain x ON c.id=x.parent_id
                ) SELECT id FROM chain""", (value.parent_id,)).fetchall()
                if category_id in {row[0] for row in ancestors}:
                    raise ValueError("Category parent would create a cycle")
            db.execute("""UPDATE personal_categories SET name=?,parent_id=?,position=?,
                revision=revision+1,updated_at=? WHERE id=?""",
                (value.name, value.parent_id, value.position, _now(), category_id))
            self._bump(db)
            return _category(self._require(db, "personal_categories", category_id))

    def set_category_deleted(self, category_id: str, deleted: bool, *, expected_revision: int) -> CategoryRecord:
        with self._connect(write=True) as db:
            old = self._require(db, "personal_categories", category_id)
            self._revision(old, expected_revision)
            changing = (old["deleted_at"] is None) == deleted
            if changing and deleted:
                tags = db.execute("SELECT 1 FROM personal_tags WHERE category_id=? LIMIT 1", (category_id,)).fetchone()
                children = db.execute("SELECT 1 FROM personal_categories WHERE parent_id=? LIMIT 1", (category_id,)).fetchone()
                if tags or children:
                    raise ValueError("Move tags and child categories before deleting a category")
            if changing and not deleted:
                self._category_available(db, old["parent_id"])
            if changing:
                db.execute("UPDATE personal_categories SET deleted_at=?,revision=revision+1,updated_at=? WHERE id=?",
                           (_now() if deleted else None, _now(), category_id))
                self._bump(db)
            return _category(self._require(db, "personal_categories", category_id))

    def move_tags(self, items: list[dict], category_id: str | None) -> int:
        if any(not isinstance(entry, dict) or "id" not in entry or "revision" not in entry for entry in items):
            raise ValueError("Each batch item needs id and revision")
        if len({entry.get("id") for entry in items}) != len(items):
            raise ValueError("Duplicate tag IDs in batch")
        with self._connect(write=True) as db:
            self._category_available(db, category_id)
            records = []
            for entry in items:
                old = self._require(db, "personal_tags", entry["id"])
                self._revision(old, entry["revision"])
                records.append(old)
            now = _now()
            for old in records:
                db.execute("UPDATE personal_tags SET category_id=?,revision=revision+1,updated_at=? WHERE id=?",
                           (category_id, now, old["id"]))
            if records:
                self._bump(db)
            return len(records)


__all__ = ["PersonalTagStore", "PersonalTagNotFoundError", "PersonalTagConflictError", "normalize_search"]
