"""Saved composition snapshots and the single autosaved draft."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from anima_prompt_studio_v3.core.personal_tags import (
    CompositionItem, CompositionRecord, CompositionWrite, validate_composition_items,
)
from anima_prompt_studio_v3.storage.personal_tags import (
    PersonalTagConflictError, PersonalTagNotFoundError, PersonalTagStore, _json, _now,
)


def _record(row) -> CompositionRecord:
    data = dict(row)
    data["items"] = json.loads(data["items"])
    return CompositionRecord(**data)


def _items(items: list[CompositionItem]) -> str:
    valid = validate_composition_items([CompositionItem.model_validate(item) for item in items])
    return _json([item.model_dump() for item in valid])


class PersonalTagCompositions:
    def __init__(self, path: Path):
        self.store = PersonalTagStore(path)

    def list(self, *, trash: bool = False) -> list[CompositionRecord]:
        with self.store._connect() as db:
            rows = db.execute("SELECT * FROM personal_compositions WHERE deleted_at IS NOT NULL ORDER BY name,id" if trash
                              else "SELECT * FROM personal_compositions WHERE deleted_at IS NULL ORDER BY name,id").fetchall()
        return [_record(row) for row in rows]

    def get(self, id: str) -> CompositionRecord:
        with self.store._connect() as db:
            return _record(self.store._require(db, "personal_compositions", id))

    def create(self, value: CompositionWrite) -> CompositionRecord:
        value = CompositionWrite.model_validate(value)
        now, composition_id = _now(), str(uuid4())
        with self.store._connect(write=True) as db:
            db.execute("""INSERT INTO personal_compositions
                (id,name,items,revision,created_at,updated_at) VALUES (?,?,?,1,?,?)""",
                (composition_id, value.name, _items(value.items), now, now))
            self.store._bump(db)
            return _record(self.store._require(db, "personal_compositions", composition_id))

    def update(self, id: str, value: CompositionWrite, *, expected_revision: int) -> CompositionRecord:
        value = CompositionWrite.model_validate(value)
        with self.store._connect(write=True) as db:
            old = self.store._require(db, "personal_compositions", id)
            self.store._revision(old, expected_revision)
            db.execute("""UPDATE personal_compositions SET name=?,items=?,revision=revision+1,
                updated_at=? WHERE id=?""", (value.name, _items(value.items), _now(), id))
            self.store._bump(db)
            return _record(self.store._require(db, "personal_compositions", id))

    def set_deleted(self, id: str, deleted: bool, *, expected_revision: int) -> CompositionRecord:
        with self.store._connect(write=True) as db:
            old = self.store._require(db, "personal_compositions", id)
            self.store._revision(old, expected_revision)
            if (old["deleted_at"] is None) == deleted:
                db.execute("UPDATE personal_compositions SET deleted_at=?,revision=revision+1,updated_at=? WHERE id=?",
                           (_now() if deleted else None, _now(), id))
                self.store._bump(db)
            return _record(self.store._require(db, "personal_compositions", id))

    def get_draft(self) -> dict:
        with self.store._connect() as db:
            row = db.execute("SELECT * FROM personal_draft WHERE id=1").fetchone()
        return {"items": [CompositionItem(**item) for item in json.loads(row["items"])],
                "revision": row["revision"], "updated_at": row["updated_at"]}

    def save_draft(self, items: list[CompositionItem], *, expected_revision: int) -> dict:
        payload = _items(items)
        with self.store._connect(write=True) as db:
            row = db.execute("SELECT revision FROM personal_draft WHERE id=1").fetchone()
            if row["revision"] != expected_revision:
                raise PersonalTagConflictError(f"Expected draft revision {expected_revision}, found {row['revision']}")
            db.execute("UPDATE personal_draft SET items=?,revision=revision+1,updated_at=? WHERE id=1",
                       (payload, _now()))
            saved = db.execute("SELECT * FROM personal_draft WHERE id=1").fetchone()
        return {"items": [CompositionItem(**item) for item in json.loads(saved["items"])],
                "revision": saved["revision"], "updated_at": saved["updated_at"]}


__all__ = ["PersonalTagCompositions", "PersonalTagNotFoundError", "PersonalTagConflictError"]
