"""Install the packaged personal tag baseline once for a pristine library."""

from __future__ import annotations

import json
import sqlite3
from importlib import resources

from .personal_tag_import import ImportOptions, _insert_prepared, _prepare
from .personal_tags import PersonalTagStore


SEED_VERSION = "personal-tags-20260929-v1"
SEED_FILENAME = f"{SEED_VERSION}.json"


def _eligible(db: sqlite3.Connection) -> bool:
    if db.execute("SELECT library_revision FROM library_meta WHERE id=1").fetchone()[0] != 0:
        return False
    if db.execute("SELECT 1 FROM personal_seed_meta WHERE id=1").fetchone():
        return False
    for table in ("personal_categories", "personal_tags", "personal_compositions"):
        if db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
            return False
    draft = db.execute("SELECT items,revision,updated_at FROM personal_draft WHERE id=1").fetchone()
    return draft is not None and draft["items"] == "[]" and draft["revision"] == 0 and draft["updated_at"] == ""


def _load_seed_document() -> dict:
    path = resources.files("anima_prompt_studio_v3").joinpath("seed_data", SEED_FILENAME)
    return json.loads(path.read_text(encoding="utf-8"))


def initialize_bundled_personal_tags(store: PersonalTagStore) -> bool:
    """Return whether this startup installed the seed; keep user libraries untouched."""
    # This cheap probe avoids reading a large resource on every normal startup.
    # The same eligibility decision is repeated after obtaining the write lock.
    with store._connect() as db:
        if not _eligible(db):
            return False

    document = _load_seed_document()
    if (document.get("format") != "anima-personal-tags"
            or len(document.get("categories", [])) != 174
            or len(document.get("tags", [])) != 11473
            or document.get("combinations") != []
            or document.get("draft") != {"items": [], "revision": 0, "updated_at": ""}):
        raise ValueError("Bundled personal tag baseline has unexpected structure")

    with store._connect(write=True) as db:
        if not _eligible(db):
            return False
        prepared = _prepare(db, document, ImportOptions())
        if prepared["counts"]["invalid"] or prepared["counts"]["new"] != 11647:
            raise ValueError(f"Bundled personal tag baseline is invalid: {prepared['issues']}")
        _insert_prepared(db, prepared)
        db.execute("INSERT INTO personal_seed_meta (id,version) VALUES (1,?)", (SEED_VERSION,))
        store._bump(db)
    return True
