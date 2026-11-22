"""Literal artist combinations and their independently owned sample images.

Tables coexist with the personal library without changing its schema version.
Small sample images live in SQLite so metadata, image ownership and imports commit
atomically. No remote image fetching or caller-provided filesystem paths.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .reference_examples import inspect_image

MAX_BUNDLE_BYTES = 50 * 1024 * 1024
PREFIX = "/api/v3/artist-presets"
FAMILY = Literal["anima", "sdxl", "novelai", "other", "unknown"]
SYNTAX = Literal["comfy", "novelai", "plain", "unknown"]


class PresetNotFound(ValueError):
    pass


class PresetConflict(ValueError):
    pass


class Payload(BaseModel):
    # Raw prompt strings must never inherit ContractModel's whitespace stripping.
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def safe_source(value: str) -> str:
    if value:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("来源链接必须是有效的 HTTP 或 HTTPS 网址。")
    return value


class PresetWrite(Payload):
    name: str = Field(min_length=1, max_length=200)
    positive: str = Field(default="", max_length=20_000)
    negative: str = Field(default="", max_length=20_000)
    model_family: FAMILY = "unknown"
    model_label: str = Field(default="", max_length=200)
    syntax: SYNTAX = "unknown"
    source_url: str = Field(default="", max_length=2000)
    source_author: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=20_000)
    favorite: bool = False

    _source = field_validator("source_url")(safe_source)

    @field_validator("name")
    @classmethod
    def meaningful_name(cls, value):
        if not value.strip():
            raise ValueError("画师串名称不能为空。")
        return value.strip()

    @model_validator(mode="after")
    def meaningful_prompt(self):
        if not self.positive.strip() and not self.negative.strip():
            raise ValueError("至少填写一段正向或负向画师串。")
        return self


class SampleMetadata(Payload):
    caption: str = Field(default="", max_length=2000)
    model_label: str = Field(default="", max_length=200)
    source_url: str = Field(default="", max_length=2000)
    full_positive: str = Field(default="", max_length=40_000)
    full_negative: str = Field(default="", max_length=40_000)
    parameters: dict[str, Any] = Field(default_factory=dict)

    _source = field_validator("source_url")(safe_source)

    @field_validator("parameters")
    @classmethod
    def bounded_parameters(cls, value):
        # JavaScript JSON readers cannot represent large integer seeds exactly.
        # Preserve their decimal spelling before API responses or backup export;
        # other caller-supplied parameters retain their original types.
        seed = value.get("seed")
        if isinstance(seed, int) and not isinstance(seed, bool) and abs(seed) > 2**53 - 1:
            value = {**value, "seed": str(seed)}
        if len(json.dumps(value, ensure_ascii=False, allow_nan=False)) > 40_000:
            raise ValueError("样品参数过长。")
        return value


class ExportSample(SampleMetadata):
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    image_base64: str = Field(max_length=28 * 1024 * 1024)
    mime_type: Literal["image/png", "image/jpeg", "image/webp"]
    source_kind: Literal["upload", "reference"] = "upload"
    source_id: str = Field(default="", max_length=200)


class ExportItem(PresetWrite):
    samples: list[ExportSample] = Field(default_factory=list, max_length=16)


class ExportDocument(Payload):
    format: Literal["anima.artist-presets"] = "anima.artist-presets"
    version: Literal[1] = 1
    items: list[ExportItem] = Field(max_length=500)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _now():
    return datetime.now(UTC).isoformat()


def content_hash(value: PresetWrite) -> str:
    # Renaming, favoriting or adding notes does not invalidate an existing sample.
    return sha256(_json({key: getattr(value, key) for key in (
        "positive", "negative", "model_family", "model_label", "syntax")}).encode()).hexdigest()


class ArtistPresetStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS artist_presets (
                    id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, content_hash TEXT NOT NULL,
                    revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    deleted_at TEXT, reference_key TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS artist_presets_reference ON artist_presets(reference_key)
                    WHERE reference_key IS NOT NULL AND deleted_at IS NULL;
                CREATE TABLE IF NOT EXISTS artist_preset_samples (
                    id TEXT PRIMARY KEY, preset_id TEXT NOT NULL, content_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL, image BLOB NOT NULL, mime_type TEXT NOT NULL,
                    width INTEGER NOT NULL, height INTEGER NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS artist_samples_parent ON artist_preset_samples(preset_id);
                CREATE TABLE IF NOT EXISTS artist_preset_meta (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL);
                INSERT OR IGNORE INTO artist_preset_meta VALUES(1,0);
                CREATE TABLE IF NOT EXISTS artist_preset_imports (token TEXT PRIMARY KEY, result_json TEXT NOT NULL, document_hash TEXT);
            """)
            if "document_hash" not in {row[1] for row in db.execute("PRAGMA table_info(artist_preset_imports)")}:
                db.execute("ALTER TABLE artist_preset_imports ADD COLUMN document_hash TEXT")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _change(db):
        db.execute("UPDATE artist_preset_meta SET revision=revision+1 WHERE id=1")

    @staticmethod
    def _row(db, preset_id, expected_revision=None):
        row = db.execute("SELECT * FROM artist_presets WHERE id=? AND deleted_at IS NULL", (preset_id,)).fetchone()
        if row is None:
            raise PresetNotFound("画师串不存在或已删除。")
        if expected_revision is not None and row["revision"] != expected_revision:
            raise PresetConflict("画师串已在另一处更新，请刷新后重试。")
        return row

    @staticmethod
    def _samples(db, preset_id):
        rows = db.execute("SELECT id,content_hash,payload_json,mime_type,width,height,created_at FROM artist_preset_samples WHERE preset_id=? ORDER BY created_at,id", (preset_id,)).fetchall()
        return [{**json.loads(row["payload_json"]), **{key: row[key] for key in (
            "id", "content_hash", "mime_type", "width", "height", "created_at")},
            "image_url": f"/api/v3/gallery/artist-presets/{preset_id}/samples/{row['id']}/content"} for row in rows]

    def _record(self, db, row):
        samples = self._samples(db, row["id"])
        return {**json.loads(row["payload_json"]), **{key: row[key] for key in (
            "id", "content_hash", "revision", "created_at", "updated_at")}, "samples": samples,
            "ready": any(item["content_hash"] == row["content_hash"] for item in samples)}

    def get(self, preset_id):
        with self.connect() as db:
            return self._record(db, self._row(db, preset_id))

    def list(self):
        with self.connect() as db:
            return [self._record(db, row) for row in db.execute("SELECT * FROM artist_presets WHERE deleted_at IS NULL ORDER BY updated_at DESC,id")]

    @staticmethod
    def _create(db, value, reference_key=None):
        if db.execute("SELECT COUNT(*) FROM artist_presets WHERE deleted_at IS NULL").fetchone()[0] >= 500:
            raise ValueError("画师串库最多保存 500 条，请先整理现有条目。")
        preset_id, stamp = "ap_" + uuid4().hex, _now()
        db.execute("INSERT INTO artist_presets VALUES(?,?,?,?,?,?,NULL,?)", (
            preset_id, _json(value.model_dump()), content_hash(value), 1, stamp, stamp, reference_key))
        return preset_id

    def create(self, value: PresetWrite):
        value = PresetWrite.model_validate(value)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            preset_id = self._create(db, value)
            self._change(db)
            return self._record(db, self._row(db, preset_id))

    def update(self, preset_id, expected_revision, value: PresetWrite):
        value = PresetWrite.model_validate(value)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._row(db, preset_id, expected_revision)
            db.execute("UPDATE artist_presets SET payload_json=?,content_hash=?,revision=revision+1,updated_at=? WHERE id=?",
                (_json(value.model_dump()), content_hash(value), _now(), preset_id))
            self._change(db)
            return self._record(db, self._row(db, preset_id))

    def delete(self, preset_id, expected_revision):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._row(db, preset_id, expected_revision)
            db.execute("UPDATE artist_presets SET deleted_at=?,revision=revision+1 WHERE id=?", (_now(), preset_id))
            self._change(db)

    @staticmethod
    def _sample(db, preset_id, fingerprint, data, metadata, media, source_kind="upload", source_id=""):
        if db.execute("SELECT COUNT(*) FROM artist_preset_samples WHERE preset_id=?", (preset_id,)).fetchone()[0] >= 16:
            raise ValueError("每组画师串最多保存 16 张样品。")
        sample_id = "as_" + uuid4().hex
        payload = {**metadata.model_dump(), "source_kind": source_kind, "source_id": source_id}
        db.execute("INSERT INTO artist_preset_samples VALUES(?,?,?,?,?,?,?,?,?)", (
            sample_id, preset_id, fingerprint, _json(payload), data, media["mime_type"], media["width"], media["height"], _now()))

    def add_sample(self, preset_id, expected_revision, data, metadata: SampleMetadata, *, content_type=None):
        metadata = SampleMetadata.model_validate(metadata)
        media = inspect_image(data, content_type)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._row(db, preset_id, expected_revision)
            self._sample(db, preset_id, row["content_hash"], data, metadata, media)
            db.execute("UPDATE artist_presets SET revision=revision+1,updated_at=? WHERE id=?", (_now(), preset_id))
            self._change(db)
            return self._record(db, self._row(db, preset_id))

    def delete_sample(self, preset_id, sample_id, expected_revision):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._row(db, preset_id, expected_revision)
            if not db.execute("DELETE FROM artist_preset_samples WHERE id=? AND preset_id=?", (sample_id, preset_id)).rowcount:
                raise PresetNotFound("样品不存在。")
            db.execute("UPDATE artist_presets SET revision=revision+1,updated_at=? WHERE id=?", (_now(), preset_id))
            self._change(db)
            return self._record(db, self._row(db, preset_id))

    def sample_content(self, preset_id, sample_id):
        with self.connect() as db:
            self._row(db, preset_id)
            row = db.execute("SELECT image,mime_type FROM artist_preset_samples WHERE id=? AND preset_id=?", (sample_id, preset_id)).fetchone()
            if row is None:
                raise PresetNotFound("样品不存在。")
            return bytes(row["image"]), row["mime_type"]

    def create_from_reference(self, value, reference_id, data, metadata):
        media = inspect_image(data)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM artist_presets WHERE reference_key=? AND deleted_at IS NULL", (reference_id,)).fetchone()
            if existing:
                return self._record(db, existing)
            preset_id = self._create(db, value, reference_id)
            self._sample(db, preset_id, content_hash(value), data, metadata, media, "reference", reference_id)
            self._change(db)
            return self._record(db, self._row(db, preset_id))

    def export(self, preset_id=None):
        items, total = [], 0
        with self.connect() as db:
            rows = [self._row(db, preset_id)] if preset_id else db.execute("SELECT * FROM artist_presets WHERE deleted_at IS NULL ORDER BY created_at,id")
            for row in rows:
                item = json.loads(row["payload_json"])
                item["samples"] = []
                for sample in db.execute("SELECT * FROM artist_preset_samples WHERE preset_id=? ORDER BY created_at,id", (row["id"],)):
                    total += (len(sample["image"]) + 2) // 3 * 4
                    if total > MAX_BUNDLE_BYTES:
                        raise ValueError("含图片备份超过 50 MiB，请按条目分别导出；单条过大时请分开备份样品。")
                    item["samples"].append({**json.loads(sample["payload_json"]), "content_hash": sample["content_hash"],
                        "mime_type": sample["mime_type"], "image_base64": base64.b64encode(sample["image"]).decode("ascii")})
                items.append(item)
        document = {"format": "anima.artist-presets", "version": 1, "items": items}
        if len(_json(document).encode()) > MAX_BUNDLE_BYTES - 1024:
            raise ValueError("含图片备份超过 50 MiB，请按条目分别导出；单条过大时请分开备份样品。")
        return document

    @staticmethod
    def _validate_document(document):
        if len(_json(document).encode()) > MAX_BUNDLE_BYTES:
            raise ValueError("导入文件不能超过 50 MiB。")
        parsed = ExportDocument.model_validate(document)
        prepared = []
        for item in parsed.items:
            value = PresetWrite.model_validate(item.model_dump(exclude={"samples"}))
            samples = []
            for sample in item.samples:
                try:
                    data = base64.b64decode(sample.image_base64, validate=True)
                except ValueError as exc:
                    raise ValueError("样品图片编码无效。") from exc
                media = inspect_image(data, sample.mime_type)
                metadata = SampleMetadata.model_validate(sample.model_dump(include=set(SampleMetadata.model_fields)))
                samples.append((sample, data, metadata, media))
            prepared.append((value, samples))
        return parsed.model_dump(), prepared

    @staticmethod
    def _token(db, document):
        revision = db.execute("SELECT revision FROM artist_preset_meta WHERE id=1").fetchone()[0]
        return sha256((str(revision) + ":" + _json(document)).encode()).hexdigest()

    def preview_import(self, document):
        document, prepared = self._validate_document(document)
        with self.connect() as db:
            existing = {row[0] for row in db.execute("SELECT content_hash FROM artist_presets WHERE deleted_at IS NULL")}
            summaries, duplicates = [], 0
            for value, samples in prepared:
                fingerprint = content_hash(value)
                duplicate = fingerprint in existing
                duplicates += int(duplicate)
                existing.add(fingerprint)
                summaries.append({**value.model_dump(), "duplicate": duplicate, "sample_count": len(samples),
                    "ready": any(sample.content_hash == fingerprint for sample, *_ in samples)})
            return {"items": summaries, "duplicates": duplicates, "warnings": ["无当前样品的条目将保存为待补样品。"] if any(not item["ready"] for item in summaries) else [],
                "token": self._token(db, document)}

    def import_document(self, document, token):
        document, prepared = self._validate_document(document)
        document_hash = sha256(_json(document).encode()).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT result_json,document_hash FROM artist_preset_imports WHERE token=?", (token,)).fetchone()
            if prior:
                if prior["document_hash"] != document_hash:
                    raise PresetConflict("导入内容已经变化，请重新预览。")
                return json.loads(prior["result_json"])
            if token != self._token(db, document):
                raise PresetConflict("导入内容或画师串库已经变化，请重新预览。")
            existing = {row[0] for row in db.execute("SELECT content_hash FROM artist_presets WHERE deleted_at IS NULL")}
            ids, skipped = [], 0
            for value, samples in prepared:
                fingerprint = content_hash(value)
                if fingerprint in existing:
                    skipped += 1
                    continue
                preset_id = self._create(db, value)
                for sample, data, metadata, media in samples:
                    self._sample(db, preset_id, sample.content_hash, data, metadata, media, sample.source_kind, sample.source_id)
                existing.add(fingerprint)
                ids.append(preset_id)
            if ids:
                self._change(db)
            result = {"items": [self._record(db, self._row(db, preset_id)) for preset_id in ids], "skipped": skipped}
            db.execute("INSERT INTO artist_preset_imports VALUES(?,?,?)", (token, _json(result), document_hash))
            return result
