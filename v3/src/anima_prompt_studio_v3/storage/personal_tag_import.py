"""Previewable, idempotent import and lossless personal-library export."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from anima_prompt_studio_v3.core.personal_tags import (
    CategoryRecord, CategoryWrite, CompositionItem, CompositionRecord,
    TagRecord, TagWrite, normalize_search, validate_composition_items,
)
from anima_prompt_studio_v3.storage.personal_tags import (
    PersonalTagConflictError, PersonalTagStore, _json, _now,
)


@dataclass(frozen=True)
class ImportOptions:
    use_legacy_weights: bool = False
    fragment_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.use_legacy_weights, bool) or not isinstance(self.fragment_ids, list) or any(
            not isinstance(value, str) or not value for value in self.fragment_ids
        ):
            raise ValueError("Invalid import options")


def _digest(document: dict, options: ImportOptions) -> str:
    try:
        canonical = json.dumps({"document": document, "options": {
            "use_legacy_weights": options.use_legacy_weights,
            "fragment_ids": sorted(set(options.fragment_ids)),
        }}, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Import document must be finite JSON") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _source_id(row: dict, label: str) -> str:
    value = row.get("id")
    if isinstance(value, bool) or not isinstance(value, (int, str)) or str(value) == "":
        raise ValueError(f"{label} needs a source id")
    return str(value)


def _stable_id(source_key: str, entity: str, source_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"anima-personal-tags/{source_key}/{entity}/{source_id}"))


def _issue(code: str, entity: str, source_id: str, message: str, *, blocking: bool = False) -> dict:
    return {"code": code, "entity": entity, "source_id": source_id,
            "message": message, "blocking": blocking}


def _weight_valid(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and (
        0.1 <= value <= 2.0 and abs(value * 20 - round(value * 20)) <= 1e-8
    )


def _record_dict(row: sqlite3.Row, json_fields: tuple[str, ...]) -> dict:
    value = dict(row)
    for key in json_fields:
        value[key] = json.loads(value[key])
    value.pop("search_key", None)
    value.pop("display_sort", None)
    return value


def export_bundle(store: PersonalTagStore) -> dict:
    """Return every library row, including trashed rows and saved snapshots."""
    with store._connect() as db:
        db.execute("BEGIN")
        categories = [_record_dict(row, ("source_metadata", "needs_review")) for row in
                      db.execute("SELECT * FROM personal_categories ORDER BY id")]
        tags = [_record_dict(row, ("aliases", "source_metadata", "needs_review")) for row in
                db.execute("SELECT * FROM personal_tags ORDER BY id")]
        combinations = [_record_dict(row, ("items",)) for row in
                        db.execute("SELECT * FROM personal_compositions ORDER BY id")]
        draft_row = db.execute("SELECT * FROM personal_draft WHERE id=1").fetchone()
        draft = {"items": json.loads(draft_row["items"]), "revision": draft_row["revision"],
                 "updated_at": draft_row["updated_at"]} if draft_row else None
    return {"format": "anima-personal-tags", "version": 1,
            "source_key": "personal-library", "categories": categories,
            "tags": tags, "combinations": combinations, "draft": draft}


def backup_database(store: PersonalTagStore) -> Path:
    """Take a consistent SQLite backup, including transactions in a WAL."""
    directory = store.path.parent / "personal-tags-backups"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = directory / f"personal-tags-{stamp}.db"
    try:
        with sqlite3.connect(store.path) as source, sqlite3.connect(target) as destination:
            source.backup(destination)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


def _shape(document: dict) -> str:
    if not isinstance(document, dict) or type(document.get("version")) is not int or document["version"] != 1:
        raise ValueError("Unsupported import format or version")
    kind = document.get("format")
    if kind not in ("anima-legacy-tags", "anima-personal-tags"):
        raise ValueError("Unsupported import format or version")
    if not isinstance(document.get("source_key"), str) or not document["source_key"]:
        raise ValueError("Import source_key must be a nonempty string")
    for field_name in ("categories", "tags"):
        if not isinstance(document.get(field_name), list):
            raise ValueError(f"Import {field_name} must be a list")
    if kind == "anima-personal-tags" and "draft" not in document:
        raise ValueError("Import draft field is required; use null when there is no draft")
    if kind == "anima-personal-tags" and (not isinstance(document.get("combinations"), list)
                                           or document.get("draft") is not None and not isinstance(document["draft"], dict)):
        raise ValueError("Import combinations or draft has invalid structure")
    return kind


def _prepare(db: sqlite3.Connection, document: dict, options: ImportOptions) -> dict:
    kind = _shape(document)
    source_key = document["source_key"]
    issues: list[dict] = []
    counts = dict.fromkeys(("new", "existing", "invalid", "similar", "unmapped",
                            "fragment_candidates", "legacy_weights"), 0)
    prepared: dict[str, object] = {"categories": [], "tags": [], "combinations": [], "draft": None,
                                   "counts": counts, "issues": issues}
    category_rows: dict[str, dict] = {}
    seen_category_origins: set[tuple[str, str]] = set()
    category_ids: dict[str, str] = {}
    names: dict[str, str] = {}
    parents: dict[str, str | None] = {}
    category_db = {row["id"]: row for row in db.execute("SELECT * FROM personal_categories")}
    tag_db = {row["id"]: row for row in db.execute("SELECT * FROM personal_tags")}
    composition_db = {row["id"]: row for row in db.execute("SELECT * FROM personal_compositions")}
    category_source = {(row["source_key"], row["source_id"]): row["id"] for row in category_db.values()
                       if row["source_key"] is not None and row["source_id"] is not None}
    tag_source = {(row["source_key"], row["source_id"]): row["id"] for row in tag_db.values()
                  if row["source_key"] is not None and row["source_id"] is not None}

    def origin(row: dict) -> tuple[str | None, str | None] | None:
        if row.get("source_key") is None or row.get("source_id") is None:
            return None
        return row["source_key"], str(row["source_id"])

    for index, row in enumerate(document["categories"]):
        label = str(index)
        try:
            if not isinstance(row, dict):
                raise ValueError("category row must be an object")
            label = _source_id(row, "category")
            if label in category_rows:
                raise ValueError("duplicate category source id")
            value = CategoryRecord.model_validate(row) if kind == "anima-personal-tags" else CategoryWrite(
                name=row.get("name"), parent_id=None, position=index)
            row_origin = origin(row) if kind == "anima-personal-tags" else (source_key, label)
            if row_origin is not None and row_origin in seen_category_origins:
                issues.append(_issue("duplicate_source", "category", label,
                                     "Multiple categories claim the same source key and id", blocking=True))
                continue
            if row_origin is not None:
                seen_category_origins.add(row_origin)
            category_rows[label] = row
            category_ids[label] = (category_source.get(origin(row), row["id"])
                                   if kind == "anima-personal-tags" else category_source.get(
                                       (source_key, label), _stable_id(source_key, "category", label)))
            names[label] = value.name
            parent = row.get("parent_id")
            parents[label] = str(parent) if parent is not None else None
        except (ValueError, TypeError) as exc:
            issues.append(_issue("invalid_category", "category", label, str(exc), blocking=True))

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(source_id: str) -> None:
        if source_id in visited:
            return
        if source_id in visiting:
            raise ValueError("category parent cycle")
        visiting.add(source_id)
        parent = parents[source_id]
        if parent is not None:
            if parent not in category_rows:
                if kind == "anima-legacy-tags":
                    raise ValueError("missing category parent")
                if category_ids.get(parent, parent) not in category_db:
                    raise ValueError("missing category parent")
            else:
                visit(parent)
        visiting.remove(source_id)
        visited.add(source_id)

    for source_id in category_rows:
        try:
            visit(source_id)
        except ValueError as exc:
            issues.append(_issue("invalid_category", "category", source_id, str(exc), blocking=True))

    for source_id in category_rows:
        row = category_rows[source_id]
        target_id = category_ids[source_id]
        parent = parents[source_id]
        parent_id = category_ids.get(parent, parent) if parent is not None else None
        try:
            if kind == "anima-legacy-tags":
                payload = {"id": target_id, "name": names[source_id], "parent_id": parent_id,
                           "position": len(prepared["categories"]), "revision": 1,
                           "created_at": _now(), "updated_at": _now(), "deleted_at": None,
                           "source_key": source_key, "source_id": source_id,
                           "source_metadata": row, "needs_review": []}
            else:
                payload = CategoryRecord.model_validate(row).model_dump()
                payload["id"] = target_id
                payload["parent_id"] = parent_id
            CategoryRecord.model_validate(payload)
            key = origin(row) if kind == "anima-personal-tags" else (source_key, source_id)
            if target_id in category_db or key in category_source:
                counts["existing"] += 1
            else:
                counts["new"] += 1
                prepared["categories"].append(payload)
        except (ValueError, TypeError) as exc:
            issues.append(_issue("invalid_category", "category", source_id, str(exc), blocking=True))

    similar_seen: dict[str, set[str]] = {}
    for existing in tag_db.values():
        similar_seen.setdefault(normalize_search(existing["content"]), set()).add(existing["content"])
    seen_tag_ids: set[str] = set()
    seen_tag_origins: set[tuple[str, str]] = set()
    for index, row in enumerate(document["tags"]):
        label = str(index)
        try:
            if not isinstance(row, dict):
                raise ValueError("tag row must be an object")
            label = _source_id(row, "tag")
            if label in seen_tag_ids:
                raise ValueError("duplicate tag source id")
            seen_tag_ids.add(label)
            key = origin(row) if kind == "anima-personal-tags" else (source_key, label)
            target_id = (tag_source.get(key, row["id"]) if kind == "anima-personal-tags" else
                         tag_source.get(key, _stable_id(source_key, "tag", label)))
            if kind == "anima-personal-tags":
                payload = TagRecord.model_validate(row).model_dump()
                row_origin = origin(payload)
                if row_origin is not None and row_origin in seen_tag_origins:
                    issues.append(_issue("duplicate_source", "tag", label,
                                         "Multiple tags claim the same source key and id", blocking=True))
                    continue
                if row_origin is not None:
                    seen_tag_origins.add(row_origin)
                payload["id"] = target_id
                payload["category_id"] = category_ids.get(payload["category_id"], payload["category_id"])
                if payload["category_id"] is not None and payload["category_id"] not in category_db and payload["category_id"] not in category_ids.values():
                    raise ValueError("unknown category id")
            else:
                root_source = str(row.get("category_id"))
                if root_source not in category_rows:
                    raise ValueError("unknown root category id")
                raw_weight = row.get("global_weight", 1.0)
                weight = 1.0
                review: list[str] = []
                if raw_weight != 1.0:
                    counts["legacy_weights"] += 1
                if options.use_legacy_weights:
                    if _weight_valid(raw_weight):
                        weight = float(raw_weight)
                    else:
                        review.append("legacy_weight_invalid")
                        issues.append(_issue("legacy_weight_invalid", "tag", label,
                                             "Old weight cannot be used; retained in source metadata and defaulted to 1.0"))
                sub_name = row.get("sub_category")
                matches = [candidate for candidate, name in names.items()
                           if parents[candidate] == root_source and name == sub_name]
                if len(matches) != 1 and isinstance(sub_name, str) and "/" in sub_name:
                    pieces = [piece.strip() for piece in sub_name.split("/")]

                    def relative_path(candidate: str) -> list[str] | None:
                        path: list[str] = []
                        visited: set[str] = set()
                        while candidate != root_source:
                            if candidate in visited or candidate not in names:
                                return None
                            visited.add(candidate)
                            path.append(names[candidate])
                            candidate = parents[candidate]
                            if candidate is None:
                                return None
                        return list(reversed(path))

                    matches = [candidate for candidate in names if relative_path(candidate) == pieces]
                category_source_id = matches[0] if len(matches) == 1 else root_source
                if len(matches) != 1:
                    counts["unmapped"] += 1
                    review.append("category_unmapped")
                    issues.append(_issue("category_unmapped", "tag", label,
                                         "Subcategory did not uniquely match a direct child; kept at original root"))
                content = row.get("content")
                if isinstance(content, str) and any(mark in content for mark in (",", "\n", "，", "<", ">")):
                    counts["fragment_candidates"] += 1
                    issues.append(_issue("fragment_candidate", "tag", label, "Review prompt fragment type"))
                payload = {"id": target_id, "display_name": row.get("display_name"),
                           "content": content, "aliases": row.get("aliases", []),
                           "category_id": category_ids[category_source_id],
                           "kind": "fragment" if label in options.fragment_ids else "tag",
                           "notes": "", "default_weight": weight, "revision": 1,
                           "created_at": _now(), "updated_at": _now(), "deleted_at": None,
                           "source_key": source_key, "source_id": label,
                           "source_metadata": row, "needs_review": review}
                payload = TagRecord.model_validate(payload).model_dump()
            if target_id in tag_db or key in tag_source:
                counts["existing"] += 1
                continue
            key = normalize_search(payload["content"])
            variants = similar_seen.setdefault(key, set())
            if variants and payload["content"] not in variants:
                counts["similar"] += 1
                issues.append(_issue("similar_variant", "tag", label, "Similar content preserved as separate tag"))
            variants.add(payload["content"])
            counts["new"] += 1
            prepared["tags"].append(payload)
        except (ValueError, TypeError) as exc:
            issues.append(_issue("invalid_tag", "tag", label, str(exc), blocking=True))

    if kind == "anima-personal-tags":
        seen_combinations: set[str] = set()
        for index, row in enumerate(document["combinations"]):
            label = str(index)
            try:
                if not isinstance(row, dict):
                    raise ValueError("combination row must be an object")
                label = _source_id(row, "combination")
                if label in seen_combinations:
                    raise ValueError("duplicate combination id")
                seen_combinations.add(label)
                payload = CompositionRecord.model_validate(row).model_dump()
                if label in composition_db:
                    counts["existing"] += 1
                else:
                    counts["new"] += 1
                    prepared["combinations"].append(payload)
            except (ValueError, TypeError) as exc:
                issues.append(_issue("invalid_combination", "combination", label, str(exc), blocking=True))
        draft = document["draft"]
        if draft is not None:
            try:
                if isinstance(draft.get("revision"), bool) or not isinstance(draft.get("revision"), int) or draft["revision"] < 0:
                    raise ValueError("draft revision must be nonnegative integer")
                items = validate_composition_items([CompositionItem.model_validate(item) for item in draft["items"]])
                if not isinstance(draft.get("updated_at"), str):
                    raise ValueError("draft updated_at must be a string")
                current_draft = db.execute("SELECT items,revision,updated_at FROM personal_draft WHERE id=1").fetchone()
                if (current_draft["revision"] == 0 and current_draft["items"] == "[]"
                        and current_draft["updated_at"] == ""
                        and (items or draft["revision"] or draft["updated_at"])):
                    prepared["draft"] = {"items": [item.model_dump() for item in items],
                                         "revision": draft["revision"], "updated_at": draft["updated_at"]}
                    counts["new"] += 1
            except (ValueError, TypeError, KeyError) as exc:
                issues.append(_issue("invalid_draft", "draft", "1", str(exc), blocking=True))

    counts["invalid"] = sum(issue["blocking"] for issue in issues)
    return prepared


def preview_import(store: PersonalTagStore, document: dict, options: ImportOptions) -> dict:
    digest = _digest(document, options)
    with store._connect() as db:
        revision = db.execute("SELECT library_revision FROM library_meta WHERE id=1").fetchone()[0]
        prepared = _prepare(db, document, options)
    return {"digest": digest, "library_revision": revision,
            "counts": prepared["counts"], "issues": prepared["issues"]}


def commit_import(store: PersonalTagStore, document: dict, options: ImportOptions, *,
                  digest: str, expected_library_revision: int) -> dict:
    if digest != _digest(document, options):
        raise ValueError("Import digest mismatch")
    preview = preview_import(store, document, options)
    if preview["library_revision"] != expected_library_revision:
        raise PersonalTagConflictError("Library revision changed since import preview")
    if preview["counts"]["invalid"]:
        raise ValueError(f"Import contains invalid records: {preview['issues']}")
    if preview["counts"]["new"]:
        backup_database(store)
    with store._connect(write=True) as db:
        current = db.execute("SELECT library_revision FROM library_meta WHERE id=1").fetchone()[0]
        if current != expected_library_revision:
            raise PersonalTagConflictError("Library revision changed since import preview")
        prepared = _prepare(db, document, options)
        if prepared["counts"]["invalid"]:
            raise ValueError(f"Import contains invalid records: {prepared['issues']}")
        pending = {row["id"]: row for row in prepared["categories"]}
        while pending:
            ready = [row for row in pending.values() if row["parent_id"] not in pending]
            if not ready:
                raise ValueError("Import category cycle")
            for row in ready:
                db.execute("""INSERT INTO personal_categories
                    (id,name,parent_id,position,revision,created_at,updated_at,deleted_at,
                     source_key,source_id,source_metadata,needs_review)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (row["id"], row["name"], row["parent_id"], row["position"], row["revision"],
                     row["created_at"], row["updated_at"], row["deleted_at"], row["source_key"],
                     row["source_id"], _json(row["source_metadata"]), _json(row["needs_review"])))
                del pending[row["id"]]
        for row in prepared["tags"]:
            db.execute("""INSERT INTO personal_tags
                (id,display_name,content,aliases,category_id,kind,notes,default_weight,
                 search_key,display_sort,revision,created_at,updated_at,deleted_at,
                 source_key,source_id,source_metadata,needs_review)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (row["id"], row["display_name"], row["content"], _json(row["aliases"]),
                 row["category_id"], row["kind"], row["notes"], row["default_weight"],
                 normalize_search(" ".join([row["display_name"], row["content"], *row["aliases"]])),
                 normalize_search(row["display_name"]), row["revision"], row["created_at"],
                 row["updated_at"], row["deleted_at"], row["source_key"], row["source_id"],
                 _json(row["source_metadata"]), _json(row["needs_review"])))
        for row in prepared["combinations"]:
            db.execute("""INSERT INTO personal_compositions
                (id,name,items,revision,created_at,updated_at,deleted_at) VALUES (?,?,?,?,?,?,?)""",
                (row["id"], row["name"], _json(row["items"]), row["revision"],
                 row["created_at"], row["updated_at"], row["deleted_at"]))
        draft = prepared["draft"]
        if draft is not None:
            current_draft = db.execute("SELECT revision,items,updated_at FROM personal_draft WHERE id=1").fetchone()
            if current_draft["revision"] == 0 and current_draft["items"] == "[]" and current_draft["updated_at"] == "":
                db.execute("UPDATE personal_draft SET items=?,revision=?,updated_at=? WHERE id=1",
                           (_json(draft["items"]), draft["revision"], draft["updated_at"]))
        if prepared["counts"]["new"]:
            store._bump(db)
    return {"counts": prepared["counts"], "issues": prepared["issues"],
            "library_revision": store.library_revision}


__all__ = ["ImportOptions", "preview_import", "commit_import", "export_bundle", "backup_database"]
