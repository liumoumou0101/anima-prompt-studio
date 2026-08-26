from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .contracts import DATA_CONTRACT, DataContractError


class ReferenceDataStore:
    """Read-only query facade over a validated V3 reference database."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        if not self.path.is_file():
            raise DataContractError(f"参考数据库不存在：{self.path}")
        self.connection = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True)
        self.connection.row_factory = sqlite3.Row
        try:
            contract = self.metadata("contract")
            if contract != DATA_CONTRACT:
                raise DataContractError(f"参考数据库契约不兼容：{contract!r}")
        except Exception:
            self.connection.close()
            raise

    def __enter__(self) -> "ReferenceDataStore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def metadata(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    @property
    def pack_id(self) -> str:
        return self.metadata("pack_id") or ""

    def search(self, query: str, *, categories: set[str] | None = None, limit: int = 50) -> list[dict[str, Any]]:
        tokens = re.findall(r"[0-9a-zA-Z_\u3400-\u9fff]+", query.lower())
        if not tokens or limit <= 0:
            return []
        match = " AND ".join(f'"{token}"*' for token in tokens)
        category_sql = ""
        parameters: list[Any] = [match]
        if categories:
            ordered = sorted(categories)
            category_sql = " AND t.category_name IN (" + ",".join("?" for _ in ordered) + ")"
            parameters.extend(ordered)
        parameters.append(min(limit * 4, 1000))
        rows = self.connection.execute(
            """SELECT t.id,t.name,t.render_name,t.cn_name,t.category,t.category_name,
                      t.post_count,t.nsfw,t.deprecated,bm25(tag_search) AS search_rank
               FROM tag_search s JOIN tags t ON t.name=s.canonical
               WHERE tag_search MATCH ? AND t.deprecated=0"""
            + category_sql
            + " ORDER BY search_rank,t.post_count DESC LIMIT ?",
            parameters,
        ).fetchall()
        result: list[dict[str, Any]] = []
        seen: set[int] = set()
        for row in rows:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            result.append(_tag_summary(row))
            if len(result) >= limit:
                break
        return result

    def get_tag(self, canonical_name: str) -> dict[str, Any] | None:
        canonical = _canonical(canonical_name)
        row = self.connection.execute("SELECT * FROM tags WHERE name=?", (canonical,)).fetchone()
        if row is None:
            alias = self.connection.execute(
                "SELECT t.* FROM tag_aliases a JOIN tags t ON t.id=a.tag_id WHERE a.alias=? AND a.status='active'",
                (canonical,),
            ).fetchone()
            row = alias
        if row is None:
            return None
        aliases = [item[0] for item in self.connection.execute(
            "SELECT alias FROM tag_aliases WHERE tag_id=? ORDER BY alias", (row["id"],)
        )]
        groups = [dict(item) for item in self.connection.execute(
            """SELECT g.id,g.name,g.cn_name FROM tag_group_members m
               JOIN tag_groups g ON g.id=m.group_id WHERE m.tag_id=? ORDER BY g.id""",
            (row["id"],),
        )]
        result = _tag_summary(row)
        result.update({
            "created_at": row["created_at"],
            "cn_terms": json.loads(row["cn_terms"] or "[]"),
            "wiki_summary": row["wiki_summary"],
            "aliases": aliases,
            "groups": groups,
            "pack_id": self.pack_id,
        })
        return result

    def related_tags(
        self,
        seed_tags: Iterable[str],
        *,
        excluded: set[str] | None = None,
        categories: set[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        resolved = self._resolve_tags(seed_tags)
        if not resolved or limit <= 0:
            return []
        excluded_names = {_canonical(item) for item in (excluded or set())}
        excluded_names.update(resolved)
        scores: dict[str, float] = defaultdict(float)
        counts: dict[str, int] = defaultdict(int)
        sources: dict[str, list[str]] = defaultdict(list)
        summaries: dict[str, dict[str, Any]] = {}
        for seed_name, seed_id in resolved.items():
            rows = self.connection.execute(
                """SELECT t.id,t.name,t.render_name,t.cn_name,t.category,t.category_name,t.post_count,
                          t.nsfw,t.deprecated,e.cooc_count,e.npmi,e.score_version
                   FROM tag_cooccurrence e JOIN tags t ON t.id=e.related_tag_id
                   WHERE e.tag_id=? ORDER BY e.rank LIMIT 500""",
                (seed_id,),
            ).fetchall()
            for row in rows:
                name = row["name"]
                if name in excluded_names or (categories and row["category_name"] not in categories):
                    continue
                scores[name] += row["npmi"] if row["npmi"] is not None else math.log1p(row["cooc_count"])
                counts[name] += row["cooc_count"]
                sources[name].append(seed_name)
                summaries[name] = _tag_summary(row)
                summaries[name]["algorithm_version"] = row["score_version"]
        ordered = sorted(scores, key=lambda name: (scores[name], counts[name]), reverse=True)[:limit]
        scale = max((abs(scores[name]) for name in ordered), default=1.0) or 1.0
        return [
            {
                **summaries[name],
                "raw_score": round(scores[name], 6),
                "display_score": round(scores[name] / scale, 4),
                "cooc_count": counts[name],
                "sources": sources[name],
                "data_pack_id": self.pack_id,
            }
            for name in ordered
        ]

    def recommend_artists(self, seed_tags: Iterable[str], *, limit: int = 20) -> list[dict[str, Any]]:
        resolved = self._resolve_tags(seed_tags)
        if not resolved or limit <= 0:
            return []
        scores: dict[str, float] = defaultdict(float)
        counts: dict[str, int] = defaultdict(int)
        sources: dict[str, list[str]] = defaultdict(list)
        post_counts: dict[str, int] = {}
        versions: dict[str, str] = {}
        for seed_name, seed_id in resolved.items():
            rows = self.connection.execute(
                """SELECT a.name,a.render_name,a.post_count,e.cooc_count,e.npmi,e.score_version
                   FROM artist_tag_cooccurrence e JOIN artists a ON a.id=e.artist_id
                   WHERE e.tag_id=?""",
                (seed_id,),
            ).fetchall()
            for row in rows:
                name = row["name"]
                scores[name] += row["npmi"] if row["npmi"] is not None else math.log1p(row["cooc_count"])
                counts[name] += row["cooc_count"]
                sources[name].append(seed_name)
                post_counts[name] = row["post_count"]
                versions[name] = row["score_version"]
        for name, hit_sources in sources.items():
            scores[name] *= 1.0 + 0.3 * (len(set(hit_sources)) - 1)
        ordered = sorted(scores, key=lambda name: (scores[name], counts[name]), reverse=True)[:limit]
        scale = max((abs(scores[name]) for name in ordered), default=1.0) or 1.0
        return [
            {
                "name": name,
                "render_name": "@" + name.replace("_", " "),
                "post_count": post_counts[name],
                "raw_score": round(scores[name], 6),
                "display_score": round(scores[name] / scale, 4),
                "cooc_count": counts[name],
                "sources": list(dict.fromkeys(sources[name])),
                "hit_count": len(set(sources[name])),
                "algorithm_version": versions[name],
                "data_pack_id": self.pack_id,
            }
            for name in ordered
        ]

    def _resolve_tags(self, names: Iterable[str]) -> dict[str, int]:
        resolved: dict[str, int] = {}
        for raw_name in names:
            name = _canonical(raw_name)
            row = self.connection.execute("SELECT id,name FROM tags WHERE name=?", (name,)).fetchone()
            if row is None:
                row = self.connection.execute(
                    """SELECT t.id,t.name FROM tag_aliases a JOIN tags t ON t.id=a.tag_id
                       WHERE a.alias=? AND a.status='active'""",
                    (name,),
                ).fetchone()
            if row is not None:
                resolved[row["name"]] = row["id"]
        return resolved


def _canonical(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def _tag_summary(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "render_name": row["render_name"],
        "cn_name": row["cn_name"],
        "category": row["category"],
        "category_name": row["category_name"],
        "post_count": row["post_count"],
        "nsfw": None if row["nsfw"] == -1 else bool(row["nsfw"]),
        "deprecated": bool(row["deprecated"]),
    }
