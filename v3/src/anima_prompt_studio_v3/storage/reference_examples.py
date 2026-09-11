"""User-owned reference media and versioned metadata. No network calls."""
from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sqlite3
from uuid import uuid4
import warnings

from PIL import Image, UnidentifiedImageError
from pydantic import Field

from ..core.requirements import (
    ContractModel, ReferenceCompat, Requirements, RequirementsEdit, WorkbenchError,
    dump, replace_requirements,
)

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000


class ExampleNotes(ContractModel):
    external_prompt: str = Field(default="", max_length=20_000)
    user_notes: str = Field(default="", max_length=20_000)
    source_url: str = Field(default="", max_length=2000)


class DeclaredCompat(ContractModel):
    model_profiles: list[str] = Field(default_factory=list, max_length=32)
    workflow_kinds: list[str] = Field(default_factory=list, max_length=32)


class ExampleMetadata(ContractModel):
    notes: ExampleNotes = Field(default_factory=ExampleNotes)
    requirements_edit: RequirementsEdit | None = None
    compat: DeclaredCompat = Field(default_factory=DeclaredCompat)


class ExamplePatch(ContractModel):
    revision: int = Field(ge=1)
    title: str = Field(default="", min_length=1, max_length=200)
    notes: ExampleNotes = Field(default_factory=ExampleNotes)
    requirements_edit: RequirementsEdit | None = None
    compat: DeclaredCompat = Field(default_factory=DeclaredCompat)


def now():
    return datetime.now(UTC).isoformat()


def fail(code, message):
    raise WorkbenchError(code, message)


def inspect_image(data: bytes, content_type: str | None = None):
    if not data or len(data) > MAX_IMAGE_BYTES:
        fail("invalid_reference_image", "图片必须非空且不超过 20 MB。")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as picture:
                fmt, width, height = picture.format, picture.width, picture.height
                if fmt not in {"PNG", "JPEG", "WEBP"} or getattr(picture, "n_frames", 1) != 1:
                    fail("invalid_reference_image", "仅支持静态 PNG、JPEG、WebP 图片。")
                if width * height > MAX_IMAGE_PIXELS:
                    fail("invalid_reference_image", "图片超过 4000 万像素。")
                mime = Image.MIME[fmt]
                if content_type and content_type != mime:
                    fail("invalid_reference_image", "图片内容与声明类型不一致。")
                picture.verify()
            with Image.open(BytesIO(data)) as picture:
                picture.load()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError,
            Image.DecompressionBombWarning, Image.DecompressionBombError):
        fail("invalid_reference_image", "图片无法完整解码。")
    return {"sha256": sha256(data).hexdigest(), "byte_size": len(data),
            "width": width, "height": height, "mime_type": mime,
            "extension": {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}[fmt]}


class ExampleStore:
    def __init__(self, path: Path):
        from .official_examples import OfficialPack
        from .reference_thumbnails import ReferenceThumbnailCache
        self.path = Path(path)
        self.official = OfficialPack(self.path.parent / "official-examples")
        self.thumbnails = ReferenceThumbnailCache(self.path.parent / "example-thumbnails")
        self.root = self.path.parent / "example-media"
        self.root.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS examples (
                    id TEXT PRIMARY KEY, payload_json TEXT NOT NULL,
                    revision INTEGER NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT);
                CREATE TABLE IF NOT EXISTS example_files (
                    example_id TEXT PRIMARY KEY, image_relpath TEXT NOT NULL,
                    sha256 TEXT NOT NULL, byte_size INTEGER NOT NULL,
                    width INTEGER NOT NULL, height INTEGER NOT NULL, mime_type TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS example_catalog_revision (
                    id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL);
                INSERT OR IGNORE INTO example_catalog_revision VALUES(1,0);
                CREATE TABLE IF NOT EXISTS official_example_overrides (
                    id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                    notes_json TEXT NOT NULL, updated_at TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def changed(db):
        db.execute("UPDATE example_catalog_revision SET revision=revision+1 WHERE id=1")

    @staticmethod
    def record(row):
        if row is None:
            fail("reference_preset_not_found", "参考图不存在或已删除。")
        value = json.loads(row["payload_json"])
        value.update(revision=row["revision"], source_version=str(row["revision"]), updated_at=row["updated_at"])
        try:
            Requirements.model_validate(value["requirements"])
            value["requirements_valid"] = True
        except ValueError:
            value["requirements_valid"] = False
        return value

    def get(self, example_id, source_version=None):
        if example_id.startswith("off_"):
            value = self.official.get(example_id, source_version)
            value.pop("media_path")
            with self.connect() as db:
                return self.official_notes(db, value)
        with self.connect() as db:
            value = self.record(db.execute("SELECT * FROM examples WHERE id=? AND deleted_at IS NULL", (example_id,)).fetchone())
        if source_version is not None and value["source_version"] != source_version:
            fail("reference_version_conflict", "参考图版本已变化，请刷新后再操作。")
        return value

    @staticmethod
    def official_notes(db, value):
        row = db.execute("SELECT * FROM official_example_overrides WHERE id=?", (value["id"],)).fetchone()
        value["override_revision"] = row["revision"] if row else 0
        if row:
            value["notes"] = json.loads(row["notes_json"])
        return value

    def save_official_notes(self, example_id, revision, notes):
        self.official.get(example_id)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT revision FROM official_example_overrides WHERE id=?", (example_id,)).fetchone()
            if (row["revision"] if row else 0) != revision:
                fail("example_revision_conflict", "官方参考笔记已在另一处更新。")
            db.execute("INSERT INTO official_example_overrides VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                       "revision=excluded.revision,notes_json=excluded.notes_json,updated_at=excluded.updated_at",
                       (example_id, revision + 1, json.dumps(dump(notes), ensure_ascii=False), now()))
            self.changed(db)
        return self.get(example_id)

    def create(self, data: bytes, title: str, metadata: ExampleMetadata, *, content_type=None,
               origin="upload", origin_ref=None, requirements=None, compat=None, provenance=None):
        media = inspect_image(data, content_type)
        example_id = "ex_" + uuid4().hex
        folder = self.root / example_id
        folder.mkdir()
        target = folder / ("original." + media.pop("extension"))
        temporary = folder / "upload.tmp"
        if requirements is None and metadata.requirements_edit is not None:
            requirements = dump(Requirements(**dump(metadata.requirements_edit)))
        if requirements is not None:
            requirements = dump(Requirements.model_validate(requirements))
        value = dict(id=example_id, title=title, origin=origin, origin_ref=origin_ref,
                     requirements=requirements, notes=dump(metadata.notes),
                     compat=dump(ReferenceCompat.model_validate(compat or dump(metadata.compat))),
                     provenance=provenance, ingest_state="none", ingest_attempt_id=None,
                     ingest_error_code=None, created_at=now())
        try:
            temporary.write_bytes(data)
            temporary.replace(target)
            with self.connect() as db:
                db.execute("INSERT INTO examples VALUES(?,?,1,?,NULL)", (example_id, json.dumps(value, ensure_ascii=False), now()))
                db.execute("INSERT INTO example_files VALUES(?,?,?,?,?,?,?)", (example_id, target.relative_to(self.root).as_posix(),
                    media["sha256"], media["byte_size"], media["width"], media["height"], media["mime_type"]))
                self.changed(db)
        except BaseException:
            temporary.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            folder.rmdir()
            raise
        return self.get(example_id)

    def patch(self, example_id, patch: ExamplePatch):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            value = self.record(db.execute("SELECT * FROM examples WHERE id=? AND deleted_at IS NULL", (example_id,)).fetchone())
            if value["revision"] != patch.revision:
                fail("example_revision_conflict", "参考图已在另一处更新。")
            for field in ("title", "notes", "compat"):
                if field in patch.model_fields_set:
                    edited = getattr(patch, field)
                    if field == "compat":
                        value[field].update(dump(edited))  # preserve server-owned workflow snapshot
                    else:
                        value[field] = edited if field == "title" else dump(edited)
            if "requirements_edit" in patch.model_fields_set:
                if patch.requirements_edit is None:
                    fail("invalid_request", "要求不能设为 null；清空请提交空的五层要求。")
                old = value["requirements"]
                value["requirements"] = dump(replace_requirements(Requirements.model_validate(old), patch.requirements_edit)
                    if old else Requirements(**dump(patch.requirements_edit)))
            if value["ingest_state"] == "pending":
                value.update(ingest_state="none", ingest_attempt_id=None, ingest_error_code=None)
            db.execute("UPDATE examples SET payload_json=?,revision=revision+1,updated_at=? WHERE id=?",
                       (json.dumps(value, ensure_ascii=False), now(), example_id))
            self.changed(db)
            return self.record(db.execute("SELECT * FROM examples WHERE id=?", (example_id,)).fetchone())

    def delete(self, example_id, revision):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            value = self.record(db.execute("SELECT * FROM examples WHERE id=? AND deleted_at IS NULL", (example_id,)).fetchone())
            if value["revision"] != revision:
                fail("example_revision_conflict", "参考图已在另一处更新。")
            db.execute("UPDATE examples SET revision=revision+1,deleted_at=?,updated_at=? WHERE id=?", (now(), now(), example_id))
            self.changed(db)

    def list(self, *, q="", origin=None, limit=40, cursor=None):
        pack = self.official.current()
        pack_stamp = None if pack is None else sha256(json.dumps(dump(pack[1]), sort_keys=True).encode()).hexdigest()
        official = [] if pack is None or origin not in (None, "official") else [self.official.record(pack[0], pack[1], item)
            for item in pack[2] if q.casefold() in item.title.casefold()]
        official.sort(key=lambda item: item["id"])
        pack_status = {"ready": False} if pack is None else {"ready": True, "id": pack[1].pack_id, "count": len(pack[2])}
        with self.connect() as db:
            db.execute("BEGIN")
            version = db.execute("SELECT revision FROM example_catalog_revision WHERE id=1").fetchone()[0]
            offset = 0
            if cursor:
                try:
                    decoded = json.loads(base64.urlsafe_b64decode(cursor))
                    if len(decoded) != 5 or decoded[:3] != [version, q, origin] or decoded[4] != pack_stamp or type(decoded[3]) is not int or decoded[3] < 0:
                        raise ValueError()
                    offset = decoded[3]
                except (ValueError, IndexError, KeyError, TypeError):
                    fail("reference_version_conflict", "参考库或查询已变化，请重新加载列表。")
            # JSON fields stay server-owned; query parameters are bound, never SQL fragments.
            selected = official[offset:offset + limit + 1]
            rows = db.execute("""SELECT * FROM examples WHERE deleted_at IS NULL
                AND instr(lower(json_extract(payload_json,'$.title') || ' ' ||
                    coalesce(json_extract(payload_json,'$.notes.user_notes'),'') || ' ' ||
                    coalesce(json_extract(payload_json,'$.notes.external_prompt'),'')),lower(?)) > 0
                AND (? IS NULL OR json_extract(payload_json,'$.origin')=?)
                ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?""", (q, origin, origin, max(0,limit + 1-len(selected)), max(0,offset-len(official)))).fetchall()
            for item in selected:
                item.pop("media_path")
                self.official_notes(db, item)
            selected += [self.record(row) for row in rows]
            next_cursor = base64.urlsafe_b64encode(json.dumps([version,q,origin,offset+limit,pack_stamp]).encode()).decode() if len(selected) > limit else None
            return {"items": selected[:limit], "next_cursor": next_cursor, "official_pack": pack_status}

    def content(self, example_id):
        if example_id.startswith("off_"):
            return self.official.get(example_id)["media_path"], "image/webp"
        self.get(example_id)
        with self.connect() as db:
            row = db.execute("SELECT * FROM example_files WHERE example_id=?", (example_id,)).fetchone()
        if row is None:
            fail("reference_preset_not_found", "参考图片不存在。")
        raw = row["image_relpath"]
        path = (self.root / raw).resolve()
        if Path(raw).is_absolute() or ".." in Path(raw).parts or not path.is_relative_to(self.root.resolve()) or not path.is_file():
            fail("reference_preset_not_found", "参考图片不存在。")
        return path, row["mime_type"]

    def thumbnail(self, example_id, size=320):
        path, _ = self.content(example_id)
        try:
            with path.open("rb") as stream:
                data = stream.read(MAX_IMAGE_BYTES + 1)
        except OSError:
            fail("reference_preset_not_found", "参考图片不存在。")
        if len(data) > MAX_IMAGE_BYTES:
            fail("invalid_reference_image", "图片超过大小限制。")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                return self.thumbnails.get(example_id, data, size)
        except (OSError, SyntaxError, ValueError,
                Image.DecompressionBombWarning, Image.DecompressionBombError):
            fail("invalid_reference_image", "参考图片无法生成缩略图。")

    def start_ingest(self, example_id, revision):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            value = self.record(db.execute("SELECT * FROM examples WHERE id=? AND deleted_at IS NULL", (example_id,)).fetchone())
            if value["revision"] != revision:
                fail("example_revision_conflict", "参考图已在另一处更新。")
            value.update(ingest_state="pending", ingest_attempt_id=uuid4().hex, ingest_error_code=None)
            db.execute("UPDATE examples SET payload_json=?,revision=revision+1,updated_at=? WHERE id=?",
                       (json.dumps(value, ensure_ascii=False), now(), example_id))
            self.changed(db)
            return self.record(db.execute("SELECT * FROM examples WHERE id=?", (example_id,)).fetchone())

    def finish_ingest(self, frozen, *, requirements=None, error=None, analysis_source=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM examples WHERE id=? AND deleted_at IS NULL", (frozen["id"],)).fetchone()
            if row is None:
                fail("ingest_superseded", "参考图已删除，本次分析结果未写入。")
            value = self.record(row)
            if value["revision"] != frozen["revision"] or value["ingest_attempt_id"] != frozen["ingest_attempt_id"]:
                fail("ingest_superseded", "参考图已被修改，本次分析结果未写入。")
            value.update(ingest_state="failed" if error else "ready", ingest_attempt_id=None, ingest_error_code=error)
            if not error:
                value["requirements"] = dump(Requirements.model_validate(requirements))
                if analysis_source is not None:
                    value["analysis_source"] = analysis_source
            db.execute("UPDATE examples SET payload_json=?,revision=revision+1,updated_at=? WHERE id=?",
                       (json.dumps(value, ensure_ascii=False), now(), frozen["id"]))
            self.changed(db)
            return self.record(db.execute("SELECT * FROM examples WHERE id=?", (frozen["id"],)).fetchone())

    def recover_ingests(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT * FROM examples WHERE deleted_at IS NULL AND json_extract(payload_json,'$.ingest_state')='pending'").fetchall()
            for row in rows:
                value = self.record(row)
                value.update(ingest_state="failed", ingest_attempt_id=None, ingest_error_code="ingest_interrupted")
                db.execute("UPDATE examples SET payload_json=?,revision=revision+1,updated_at=? WHERE id=?",
                           (json.dumps(value, ensure_ascii=False), now(), value["id"]))
            if rows:
                self.changed(db)
