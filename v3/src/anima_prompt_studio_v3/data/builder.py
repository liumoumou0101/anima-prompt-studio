from __future__ import annotations

import csv
import json
import math
import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .contracts import (
    DATA_CONTRACT,
    DataContractError,
    DataPackCounts,
    DataPackDiagnostics,
    DataPackFile,
    DataPackManifest,
    DataPackSnapshot,
    UpstreamSource,
    sha256_file,
)


CATEGORY_NAMES = {0: "general", 1: "artist", 3: "copyright", 4: "character", 5: "meta"}


@dataclass(frozen=True)
class ReferenceBuildInputs:
    tags: Path
    aliases: Path | None = None
    tag_cooccurrence: Path | None = None
    artist_cooccurrence: Path | None = None
    tag_groups: Path | None = None


class ReferenceDatabaseBuilder:
    """Normalize pinned upstream exports into the stable V3 SQLite contract."""

    def __init__(
        self,
        inputs: ReferenceBuildInputs,
        *,
        pack_id: str,
        snapshot: DataPackSnapshot,
        sources: list[UpstreamSource],
        algorithms: dict[str, str] | None = None,
    ) -> None:
        self.inputs = inputs
        self.pack_id = pack_id
        self.snapshot = snapshot
        self.sources = sources
        self.algorithms = algorithms or {
            "tag_related": "npmi-v1",
            "artist_related": "npmi-v1",
            "search_index": "fts5-v1",
        }
        self.diagnostics = DataPackDiagnostics()

    def build(self, output_db: Path, manifest_path: Path, *, overwrite: bool = False) -> DataPackManifest:
        self.diagnostics = DataPackDiagnostics()
        output_db = output_db.resolve()
        manifest_path = manifest_path.resolve()
        if output_db == manifest_path:
            raise DataContractError("数据库和 manifest 不能使用同一路径。")
        if output_db.parent != manifest_path.parent:
            raise DataContractError("数据库和 manifest 必须位于同一个数据包目录。")
        if not overwrite and (output_db.exists() or manifest_path.exists()):
            raise DataContractError("目标数据包已存在；默认拒绝覆盖。")
        output_db.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)

        temp_db = output_db.with_name(f".{output_db.name}.{uuid4().hex}.tmp")
        temp_manifest = manifest_path.with_name(f".{manifest_path.name}.{uuid4().hex}.tmp")
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(temp_db)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            self._create_schema(connection)
            self._load_tags(connection)
            self._load_artists(connection)
            self._load_aliases(connection)
            self._load_groups(connection)
            self._load_tag_edges(connection)
            self._load_artist_edges(connection)
            self._build_search_index(connection)
            self._write_metadata(connection)
            connection.commit()
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise DataContractError(f"reference.db 完整性检查失败：{integrity}")
            counts = self._counts(connection)
            connection.close()
            connection = None

            manifest = DataPackManifest(
                pack_id=self.pack_id,
                generated_at=datetime.now(timezone.utc),
                snapshot=self.snapshot,
                sources=self.sources,
                algorithms=self.algorithms,
                counts=counts,
                diagnostics=self.diagnostics,
                files=[DataPackFile(path=output_db.name, size=temp_db.stat().st_size, sha256=sha256_file(temp_db))],
            )
            manifest.write(temp_manifest)
            os.replace(temp_db, output_db)
            os.replace(temp_manifest, manifest_path)
            return manifest
        except (OSError, sqlite3.Error, ValueError, KeyError) as exc:
            if isinstance(exc, DataContractError):
                raise
            raise DataContractError(f"构建 reference.db 失败：{exc}") from exc
        finally:
            if connection is not None:
                connection.close()
            temp_db.unlink(missing_ok=True)
            temp_manifest.unlink(missing_ok=True)

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE tags(
                id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, render_name TEXT NOT NULL,
                category INTEGER NOT NULL, category_name TEXT NOT NULL, post_count INTEGER NOT NULL,
                created_at TEXT, cn_name TEXT, cn_terms TEXT NOT NULL DEFAULT '[]',
                wiki_summary TEXT, nsfw INTEGER NOT NULL DEFAULT -1,
                deprecated INTEGER NOT NULL DEFAULT 0 CHECK(deprecated IN (0,1))
            );
            CREATE TABLE tag_aliases(
                alias TEXT PRIMARY KEY, tag_id INTEGER NOT NULL REFERENCES tags(id),
                source TEXT NOT NULL, status TEXT NOT NULL
            );
            CREATE TABLE artists(
                id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, render_name TEXT NOT NULL,
                post_count INTEGER NOT NULL
            );
            CREATE TABLE tag_groups(
                id TEXT PRIMARY KEY, name TEXT NOT NULL, cn_name TEXT, source TEXT NOT NULL
            );
            CREATE TABLE tag_group_members(
                group_id TEXT NOT NULL REFERENCES tag_groups(id),
                tag_id INTEGER NOT NULL REFERENCES tags(id),
                PRIMARY KEY(group_id, tag_id)
            );
            CREATE TABLE tag_cooccurrence(
                tag_id INTEGER NOT NULL REFERENCES tags(id),
                related_tag_id INTEGER NOT NULL REFERENCES tags(id),
                cooc_count INTEGER NOT NULL CHECK(cooc_count >= 0),
                pmi REAL, npmi REAL, rank INTEGER NOT NULL, score_version TEXT NOT NULL,
                PRIMARY KEY(tag_id, related_tag_id)
            );
            CREATE INDEX idx_tag_cooc_source_rank ON tag_cooccurrence(tag_id, rank);
            CREATE TABLE artist_tag_cooccurrence(
                artist_id INTEGER NOT NULL REFERENCES artists(id),
                tag_id INTEGER NOT NULL REFERENCES tags(id),
                cooc_count INTEGER NOT NULL CHECK(cooc_count >= 0),
                artist_post_count INTEGER NOT NULL CHECK(artist_post_count >= 0),
                tag_post_count INTEGER NOT NULL CHECK(tag_post_count >= 0),
                pmi REAL, npmi REAL, rank INTEGER NOT NULL, score_version TEXT NOT NULL,
                PRIMARY KEY(artist_id, tag_id)
            );
            CREATE INDEX idx_artist_cooc_tag ON artist_tag_cooccurrence(tag_id);
            CREATE VIRTUAL TABLE tag_search USING fts5(term, canonical UNINDEXED, tokenize='unicode61');
            """
        )

    def _load_tags(self, connection: sqlite3.Connection) -> None:
        records = list(_read_records(self.inputs.tags))
        if not records:
            raise DataContractError("标签主表为空。")
        seen: dict[str, tuple[int, int]] = {}
        for row_number, row in enumerate(records, start=2):
            name = _canonical(_required(row, ("name",), self.inputs.tags, row_number))
            category = _integer(_required(row, ("category",), self.inputs.tags, row_number), "category")
            post_count = _integer(_pick(row, "post_count", default=0), "post_count")
            if category not in CATEGORY_NAMES:
                raise DataContractError(f"未知标签 category={category}：{name}")
            if post_count < 0:
                raise DataContractError(f"标签 post_count 不能为负数：{name}")
            if name in seen:
                previous_category, previous_count = seen[name]
                if category != previous_category or post_count != previous_count:
                    raise DataContractError(f"重复标签的 category/post_count 不一致：{name}")
                self.diagnostics.duplicate_tags_merged += 1
                continue
            seen[name] = (category, post_count)
            cn_values = [part.strip() for part in str(_pick(row, "cn_name", default="")).split(",") if part.strip()]
            connection.execute(
                """INSERT INTO tags(
                    name, render_name, category, category_name, post_count, created_at,
                    cn_name, cn_terms, wiki_summary, nsfw, deprecated
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    name,
                    _render_name(name),
                    category,
                    CATEGORY_NAMES[category],
                    post_count,
                    _nullable(row, "created_at"),
                    cn_values[0] if cn_values else None,
                    json.dumps(cn_values[1:], ensure_ascii=False),
                    _nullable(row, "wiki", "wiki_summary"),
                    _nsfw(_pick(row, "nsfw", default=None)),
                    int(_boolean(_pick(row, "deprecated", "is_deprecated", default=False))),
                ),
            )

    def _load_aliases(self, connection: sqlite3.Connection) -> None:
        if self.inputs.aliases is None:
            return
        tag_ids = _tag_ids(connection)
        for row_number, row in enumerate(_read_records(self.inputs.aliases), start=2):
            status = str(_pick(row, "status", default="active"))
            if status != "active":
                self.diagnostics.aliases_skipped_inactive += 1
                continue
            if not _boolean(_pick(row, "target_in_tag_db", default=True)):
                self.diagnostics.aliases_skipped_missing_target += 1
                continue
            alias = _canonical(_required(row, ("alias", "antecedent", "antecedent_name"), self.inputs.aliases, row_number))
            target = _canonical(_required(row, ("tag", "canonical", "consequent", "consequent_name"), self.inputs.aliases, row_number))
            if target not in tag_ids:
                self.diagnostics.aliases_skipped_missing_target += 1
                continue
            if alias in tag_ids:
                self.diagnostics.aliases_skipped_canonical_collision += 1
                continue
            connection.execute(
                "INSERT INTO tag_aliases(alias,tag_id,source,status) VALUES(?,?,?,?)",
                (alias, tag_ids[target], str(_pick(row, "source", default="upstream")), status),
            )

    def _load_artists(self, connection: sqlite3.Connection) -> None:
        path = self.inputs.artist_cooccurrence
        if path is None:
            return
        for row_number, row in enumerate(_read_records(path), start=2):
            artist = _canonical(_required(row, ("artist",), path, row_number))
            artist_count = _integer(_required(row, ("artist_post_count",), path, row_number), "artist_post_count")
            if artist_count < 0:
                raise DataContractError(f"画师 post_count 不能为负数：{artist}")
            connection.execute(
                """INSERT INTO artists(name,render_name,post_count) VALUES(?,?,?)
                   ON CONFLICT(name) DO UPDATE SET post_count=MAX(artists.post_count, excluded.post_count)""",
                (artist, "@" + _render_name(artist), artist_count),
            )

    def _load_groups(self, connection: sqlite3.Connection) -> None:
        path = self.inputs.tag_groups
        if path is None:
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DataContractError(f"无法读取标签组：{exc}") from exc
        if not isinstance(payload, dict):
            raise DataContractError("标签组根对象必须是 JSON object。")
        group_to_tags = payload.get("group_to_tags", {})
        group_cn_names = payload.get("group_cn_names", {})
        if not isinstance(group_to_tags, dict) or not isinstance(group_cn_names, dict):
            raise DataContractError("标签组字段类型无效。")
        tag_ids = _tag_ids(connection)
        for group_id, members in group_to_tags.items():
            if not isinstance(members, list):
                raise DataContractError(f"标签组成员必须是数组：{group_id}")
            connection.execute(
                "INSERT INTO tag_groups(id,name,cn_name,source) VALUES(?,?,?,?)",
                (str(group_id), str(group_id).removeprefix("tag_group:"), group_cn_names.get(group_id), "danbooru"),
            )
            for member in members:
                tag_id = tag_ids.get(_canonical(str(member)))
                if tag_id is not None:
                    connection.execute(
                        "INSERT OR IGNORE INTO tag_group_members(group_id,tag_id) VALUES(?,?)",
                        (str(group_id), tag_id),
                    )

    def _load_tag_edges(self, connection: sqlite3.Connection) -> None:
        path = self.inputs.tag_cooccurrence
        if path is None:
            return
        tag_ids = _tag_ids(connection)
        post_counts = _tag_post_counts(connection)
        edges: dict[int, list[tuple[int, int, float | None, float | None]]] = defaultdict(list)
        for row_number, row in enumerate(_read_records(path), start=2):
            left = _canonical(_required(row, ("tag_a", "source"), path, row_number))
            right = _canonical(_required(row, ("tag_b", "target"), path, row_number))
            if left == right:
                continue
            if left not in tag_ids or right not in tag_ids:
                self.diagnostics.tag_edges_skipped_unknown_tag += 1
                continue
            count = _integer(_required(row, ("count", "cooc_count", "raw_count"), path, row_number), "count")
            if count < 0:
                raise DataContractError("共现次数不能为负数。")
            if count > min(post_counts[left], post_counts[right]):
                self.diagnostics.tag_edges_margin_mismatch += 1
                if self.snapshot.cutoff_mode == "exact":
                    raise DataContractError(f"Tag–Tag 共现次数超过边际计数：{left}, {right}")
            pmi, npmi = self._scores(row, count, post_counts[left], post_counts[right])
            edges[tag_ids[left]].append((tag_ids[right], count, pmi, npmi))
            edges[tag_ids[right]].append((tag_ids[left], count, pmi, npmi))
        for source_id, values in edges.items():
            ordered = sorted(values, key=lambda item: (_score_key(item[3]), item[1]), reverse=True)
            for rank, (target_id, count, pmi, npmi) in enumerate(ordered, start=1):
                connection.execute(
                    "INSERT INTO tag_cooccurrence VALUES(?,?,?,?,?,?,?)",
                    (source_id, target_id, count, pmi, npmi, rank, self.algorithms["tag_related"]),
                )

    def _load_artist_edges(self, connection: sqlite3.Connection) -> None:
        path = self.inputs.artist_cooccurrence
        if path is None:
            return
        rows = list(_read_records(path))
        tag_ids = _tag_ids(connection)
        artist_ids = _artist_ids(connection)
        post_counts = _tag_post_counts(connection)
        edges: dict[int, list[tuple[int, int, int, int, float | None, float | None]]] = defaultdict(list)
        for row_number, row in enumerate(rows, start=2):
            artist = _canonical(_required(row, ("artist",), path, row_number))
            tag = _canonical(_required(row, ("tag",), path, row_number))
            if tag not in tag_ids:
                self.diagnostics.artist_edges_skipped_unknown_tag += 1
                continue
            count = _integer(_required(row, ("cooc_count", "count"), path, row_number), "cooc_count")
            artist_count = _integer(_required(row, ("artist_post_count",), path, row_number), "artist_post_count")
            tag_count = post_counts[tag]
            if count < 0:
                raise DataContractError(f"Artist–Tag 共现次数不能为负数：{artist}, {tag}")
            if count > min(artist_count, tag_count):
                self.diagnostics.artist_edges_margin_mismatch += 1
                if self.snapshot.cutoff_mode == "exact":
                    raise DataContractError(f"Artist–Tag 共现次数与边际计数不一致：{artist}, {tag}")
            pmi, npmi = self._scores(row, count, artist_count, tag_count)
            edges[artist_ids[artist]].append((tag_ids[tag], count, artist_count, tag_count, pmi, npmi))
        for artist_id, values in edges.items():
            ordered = sorted(values, key=lambda item: (_score_key(item[5]), item[1]), reverse=True)
            for rank, (tag_id, count, artist_count, tag_count, pmi, npmi) in enumerate(ordered, start=1):
                connection.execute(
                    "INSERT INTO artist_tag_cooccurrence VALUES(?,?,?,?,?,?,?,?,?)",
                    (artist_id, tag_id, count, artist_count, tag_count, pmi, npmi, rank, self.algorithms["artist_related"]),
                )

    def _scores(self, row: dict[str, Any], count: int, left_count: int, right_count: int) -> tuple[float | None, float | None]:
        supplied_pmi = _optional_float(_pick(row, "pmi", default=None))
        supplied_npmi = _optional_float(_pick(row, "npmi", default=None))
        if supplied_npmi is not None and not -1.0 <= supplied_npmi <= 1.0:
            raise DataContractError(f"NPMI 超出 [-1,1]：{supplied_npmi}")
        if supplied_pmi is not None or supplied_npmi is not None:
            return supplied_pmi, supplied_npmi
        corpus_size = self.snapshot.corpus_size
        if corpus_size <= 0 or min(count, left_count, right_count) <= 0:
            return None, None
        bounded = min(count, left_count, right_count)
        ratio = (bounded * corpus_size) / (left_count * right_count)
        probability = bounded / corpus_size
        if ratio <= 0 or probability <= 0 or probability >= 1:
            return None, None
        pmi = math.log(ratio)
        npmi = max(-1.0, min(1.0, pmi / -math.log(probability)))
        return pmi, npmi

    @staticmethod
    def _build_search_index(connection: sqlite3.Connection) -> None:
        rows = connection.execute("SELECT name,render_name,cn_name,cn_terms FROM tags").fetchall()
        for row in rows:
            terms = {row["name"], row["render_name"]}
            if row["cn_name"]:
                terms.add(row["cn_name"])
            terms.update(json.loads(row["cn_terms"] or "[]"))
            for term in sorted(item for item in terms if item):
                connection.execute("INSERT INTO tag_search(term,canonical) VALUES(?,?)", (term, row["name"]))
        aliases = connection.execute(
            "SELECT a.alias,t.name FROM tag_aliases a JOIN tags t ON t.id=a.tag_id WHERE a.status='active'"
        ).fetchall()
        for row in aliases:
            connection.execute("INSERT INTO tag_search(term,canonical) VALUES(?,?)", (row["alias"], row["name"]))

    def _write_metadata(self, connection: sqlite3.Connection) -> None:
        values = {
            "contract": DATA_CONTRACT,
            "pack_id": self.pack_id,
            "target_cutoff": self.snapshot.target_cutoff.isoformat(),
            "cutoff_mode": self.snapshot.cutoff_mode,
            "corpus_size": str(self.snapshot.corpus_size),
            "corpus_size_mode": self.snapshot.corpus_size_mode,
            "algorithms": json.dumps(self.algorithms, ensure_ascii=False, sort_keys=True),
        }
        connection.executemany("INSERT INTO metadata(key,value) VALUES(?,?)", values.items())

    @staticmethod
    def _counts(connection: sqlite3.Connection) -> DataPackCounts:
        return DataPackCounts(
            tags=connection.execute("SELECT COUNT(*) FROM tags").fetchone()[0],
            artists=connection.execute("SELECT COUNT(*) FROM artists").fetchone()[0],
            aliases=connection.execute("SELECT COUNT(*) FROM tag_aliases").fetchone()[0],
            tag_edges=connection.execute("SELECT COUNT(*) FROM tag_cooccurrence").fetchone()[0],
            artist_edges=connection.execute("SELECT COUNT(*) FROM artist_tag_cooccurrence").fetchone()[0],
        )


def _read_records(path: Path) -> Iterable[dict[str, Any]]:
    if not path.is_file():
        raise DataContractError(f"上游输入不存在：{path}")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        encoding = _csv_encoding(path)
        with path.open("r", encoding=encoding, newline="") as stream:
            yield from csv.DictReader(stream)
        return
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise DataContractError(f"记录 JSON 必须是数组：{path}")
        for item in payload:
            if not isinstance(item, dict):
                raise DataContractError(f"记录 JSON 包含非 object 项：{path}")
            yield item
        return
    if suffix in {".parquet", ".pq"}:
        try:
            import pandas as pd
        except ImportError as exc:
            raise DataContractError("读取 Parquet 需要安装 V3 的 data 可选依赖。") from exc
        yield from pd.read_parquet(path).to_dict(orient="records")
        return
    raise DataContractError(f"不支持的上游输入格式：{path.suffix}")


def _required(row: dict[str, Any], names: tuple[str, ...], path: Path, row_number: int) -> Any:
    value = _pick(row, *names, default=None)
    if value is None or str(value).strip() == "":
        raise DataContractError(f"{path.name} 第 {row_number} 行缺少字段 {'/'.join(names)}。")
    return value


def _pick(row: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in row and row[name] is not None and str(row[name]).strip() != "":
            return row[name]
    return default


def _nullable(row: dict[str, Any], *names: str) -> str | None:
    value = _pick(row, *names, default=None)
    return str(value).strip() if value is not None and str(value).strip() else None


def _canonical(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "_")
    if not normalized or any(character in normalized for character in "\r\n\t"):
        raise DataContractError(f"非法 canonical tag：{value!r}")
    return normalized


def _render_name(name: str) -> str:
    if name.startswith("score_") and name.removeprefix("score_").removesuffix("_up").isdigit():
        return name
    return name.replace("_", " ")


def _integer(value: Any, field: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError) as exc:
        raise DataContractError(f"{field} 必须是整数：{value!r}") from exc


def _optional_float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DataContractError(f"分数字段必须是数值：{value!r}") from exc
    if not math.isfinite(result):
        raise DataContractError("分数字段不能是 NaN 或无穷值。")
    return result


def _boolean(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _nsfw(value: Any) -> int:
    if value is None or str(value).strip().lower() in {"", "unknown", "none", "null"}:
        return -1
    return int(_boolean(value))


def _tag_ids(connection: sqlite3.Connection) -> dict[str, int]:
    return {row["name"]: row["id"] for row in connection.execute("SELECT id,name FROM tags")}


def _artist_ids(connection: sqlite3.Connection) -> dict[str, int]:
    return {row["name"]: row["id"] for row in connection.execute("SELECT id,name FROM artists")}


def _tag_post_counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {row["name"]: row["post_count"] for row in connection.execute("SELECT name,post_count FROM tags")}


def _score_key(value: float | None) -> float:
    return value if value is not None else float("-inf")


def _csv_encoding(path: Path) -> str:
    sample = path.read_bytes()
    try:
        sample.decode("utf-8-sig")
        return "utf-8-sig"
    except UnicodeDecodeError:
        try:
            sample.decode("gb18030")
            return "gb18030"
        except UnicodeDecodeError as exc:
            raise DataContractError(f"CSV 编码既不是 UTF-8 也不是 GB18030：{path}") from exc
