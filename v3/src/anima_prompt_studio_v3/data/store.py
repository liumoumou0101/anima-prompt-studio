from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .contracts import DATA_CONTRACT, DataContractError


GENERIC_ARTIST_SEED_TAGS = frozenset({
    "1girl",
    "1boy",
    "1other",
    "solo",
    "multiple_girls",
    "2girls",
    "3girls",
    "looking_at_viewer",
    "smile",
    "open_mouth",
    "standing",
    "sitting",
    "swimming",
    "navel",
    "breasts",
    "simple_background",
    "white_background",
    "cowboy_shot",
    "upper_body",
    "full_body",
    "outdoors",
    "indoors",
})


ARTIST_CONTEXT_GROUPS: dict[str, frozenset[str]] = {
    "composition": frozenset({"image_composition", "focus_tags", "lighting", "backgrounds"}),
    "setting": frozenset({
        "locations", "real_world_locations", "theme", "holidays_and_celebrations",
        "fire", "water", "flowers", "technology",
    }),
    "action": frozenset({
        "posture", "gestures", "holding_tags", "verbs_and_gerunds", "dances", "sports",
    }),
    "appearance": frozenset({
        "accessories", "attire", "colors", "eyes_tags", "eyewear", "face_tags",
        "fashion_style", "hair", "hair_color", "hair_styles", "handwear", "headwear",
        "legwear", "makeup", "neck_and_neckwear", "patterns", "skin_color", "sleeves",
        "wings",
    }),
}


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

    def popular_tags(
        self,
        *,
        categories: set[str] | None = None,
        include_nsfw: bool = False,
        limit: int = 24,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        filters = ["t.deprecated=0"]
        parameters: list[Any] = []
        if categories:
            ordered = sorted(categories)
            filters.append("t.category_name IN (" + ",".join("?" for _ in ordered) + ")")
            parameters.extend(ordered)
        if not include_nsfw:
            filters.append("t.nsfw=0")
        parameters.append(limit)
        rows = self.connection.execute(
            """SELECT t.id,t.name,t.render_name,t.cn_name,t.category,t.category_name,
                      t.post_count,t.nsfw,t.deprecated
               FROM tags t WHERE """
            + " AND ".join(filters)
            + " ORDER BY t.post_count DESC,t.name LIMIT ?",
            parameters,
        ).fetchall()
        return [_tag_summary(row) for row in rows]

    def browse_groups(
        self,
        group_names: Iterable[str],
        *,
        categories: set[str] | None = None,
        include_nsfw: bool = False,
        limit_per_group: int = 12,
    ) -> list[dict[str, Any]]:
        if limit_per_group <= 0:
            return []
        result: list[dict[str, Any]] = []
        for raw_name in group_names:
            name = _canonical(raw_name)
            group = self.connection.execute(
                "SELECT id,name,cn_name FROM tag_groups WHERE name=?",
                (name,),
            ).fetchone()
            if group is None:
                continue
            filters = ["m.group_id=?", "t.deprecated=0"]
            parameters: list[Any] = [group["id"]]
            if categories:
                ordered = sorted(categories)
                filters.append("t.category_name IN (" + ",".join("?" for _ in ordered) + ")")
                parameters.extend(ordered)
            if not include_nsfw:
                filters.append("t.nsfw=0")
            where = " AND ".join(filters)
            count = self.connection.execute(
                "SELECT COUNT(*) FROM tag_group_members m JOIN tags t ON t.id=m.tag_id WHERE " + where,
                parameters,
            ).fetchone()[0]
            rows = self.connection.execute(
                """SELECT t.id,t.name,t.render_name,t.cn_name,t.category,t.category_name,
                          t.post_count,t.nsfw,t.deprecated
                   FROM tag_group_members m JOIN tags t ON t.id=m.tag_id WHERE """
                + where
                + " ORDER BY t.post_count DESC,t.name LIMIT ?",
                [*parameters, limit_per_group],
            ).fetchall()
            if not rows:
                continue
            result.append({
                "id": group["id"],
                "name": group["name"],
                "cn_name": group["cn_name"],
                "tag_count": count,
                "items": [_tag_summary(row) for row in rows],
            })
        return result

    def list_groups(
        self,
        *,
        excluded_names: Iterable[str] = (),
        categories: set[str] | None = None,
        include_nsfw: bool = False,
    ) -> list[dict[str, Any]]:
        filters = ["t.deprecated=0"]
        parameters: list[Any] = []
        excluded = sorted({_canonical(name) for name in excluded_names})
        if excluded:
            filters.append("g.name NOT IN (" + ",".join("?" for _ in excluded) + ")")
            parameters.extend(excluded)
        if categories:
            ordered = sorted(categories)
            filters.append("t.category_name IN (" + ",".join("?" for _ in ordered) + ")")
            parameters.extend(ordered)
        if not include_nsfw:
            filters.append("t.nsfw=0")
        rows = self.connection.execute(
            """SELECT g.id,g.name,g.cn_name,COUNT(*) AS tag_count
               FROM tag_groups g
               JOIN tag_group_members m ON m.group_id=g.id
               JOIN tags t ON t.id=m.tag_id
               WHERE """
            + " AND ".join(filters)
            + " GROUP BY g.id,g.name,g.cn_name HAVING COUNT(*)>0"
            + " ORDER BY tag_count DESC,g.name",
            parameters,
        ).fetchall()
        return [dict(row) for row in rows]

    def ungrouped_summary(
        self,
        *,
        categories: set[str] | None = None,
    ) -> dict[str, Any]:
        filters = ["t.deprecated=0", "t.id NOT IN (SELECT tag_id FROM tag_group_members)"]
        parameters: list[Any] = []
        if categories:
            ordered = sorted(categories)
            filters.append("t.category_name IN (" + ",".join("?" for _ in ordered) + ")")
            parameters.extend(ordered)
        rows = self.connection.execute(
            """SELECT t.category_name,t.nsfw,COUNT(*) AS tag_count
               FROM tags t WHERE """
            + " AND ".join(filters)
            + " GROUP BY t.category_name,t.nsfw",
            parameters,
        ).fetchall()
        category_counts: dict[str, int] = defaultdict(int)
        safe_count = 0
        nsfw_count = 0
        unknown_count = 0
        for row in rows:
            count = int(row["tag_count"])
            category_counts[str(row["category_name"])] += count
            if row["nsfw"] == 1:
                nsfw_count += count
            elif row["nsfw"] == 0:
                safe_count += count
            else:
                unknown_count += count
        return {
            "total": safe_count + nsfw_count + unknown_count,
            "safe_count": safe_count,
            "nsfw_count": nsfw_count,
            "unknown_count": unknown_count,
            "category_counts": dict(category_counts),
        }

    def ungrouped_tags(
        self,
        *,
        query: str = "",
        categories: set[str] | None = None,
        safety: str = "safe",
        heat: str = "all",
        sort: str = "popularity",
        limit: int = 80,
        offset: int = 0,
    ) -> dict[str, Any]:
        filters = ["t.deprecated=0", "t.id NOT IN (SELECT tag_id FROM tag_group_members)"]
        parameters: list[Any] = []
        tokens = re.findall(r"[0-9a-zA-Z_\u3400-\u9fff]+", query.lower())
        source = "FROM tags t"
        if query.strip():
            if not tokens:
                return {"total": 0, "items": []}
            match = " AND ".join(f'"{token}"*' for token in tokens)
            source += " JOIN (SELECT DISTINCT canonical FROM tag_search WHERE tag_search MATCH ?) s ON s.canonical=t.name"
            parameters.append(match)
        if categories:
            ordered = sorted(categories)
            filters.append("t.category_name IN (" + ",".join("?" for _ in ordered) + ")")
            parameters.extend(ordered)
        if safety == "safe":
            filters.append("t.nsfw=0")
        elif safety == "nsfw":
            filters.append("t.nsfw=1")
        if heat == "100k":
            filters.append("t.post_count>=100000")
        elif heat == "10k":
            filters.extend(["t.post_count>=10000", "t.post_count<100000"])
        elif heat == "1k":
            filters.extend(["t.post_count>=1000", "t.post_count<10000"])
        elif heat == "longtail":
            filters.append("t.post_count<1000")
        where = " AND ".join(filters)
        total = self.connection.execute(
            "SELECT COUNT(*) " + source + " WHERE " + where,
            parameters,
        ).fetchone()[0]
        order_by = "t.name" if sort == "name" else "t.post_count DESC,t.name"
        rows = self.connection.execute(
            """SELECT t.id,t.name,t.render_name,t.cn_name,t.category,t.category_name,
                      t.post_count,t.nsfw,t.deprecated """
            + source
            + " WHERE "
            + where
            + f" ORDER BY {order_by} LIMIT ? OFFSET ?",
            [*parameters, max(0, limit), max(0, offset)],
        ).fetchall()
        return {"total": total, "items": [_tag_summary(row) for row in rows]}

    def group_tags(
        self,
        group_name: str,
        *,
        query: str = "",
        categories: set[str] | None = None,
        include_nsfw: bool = False,
        has_cn_name: bool = False,
        sort: str = "popularity",
        limit: int = 80,
        offset: int = 0,
    ) -> dict[str, Any] | None:
        name = _canonical(group_name).removeprefix("tag_group:")
        group = self.connection.execute(
            "SELECT id,name,cn_name FROM tag_groups WHERE name=? OR id=?",
            (name, f"tag_group:{name}"),
        ).fetchone()
        if group is None:
            return None
        filters = ["m.group_id=?", "t.deprecated=0"]
        parameters: list[Any] = [group["id"]]
        if categories:
            ordered = sorted(categories)
            filters.append("t.category_name IN (" + ",".join("?" for _ in ordered) + ")")
            parameters.extend(ordered)
        if not include_nsfw:
            filters.append("t.nsfw=0")
        if has_cn_name:
            filters.append("t.cn_name IS NOT NULL AND TRIM(t.cn_name)<>''")
        normalized_query = query.strip().lower().replace(" ", "_")
        if normalized_query:
            pattern = f"%{normalized_query}%"
            filters.append(
                "(LOWER(t.name) LIKE ? OR LOWER(t.render_name) LIKE ? OR LOWER(COALESCE(t.cn_name,'')) LIKE ?)"
            )
            parameters.extend([pattern, pattern.replace("_", " "), pattern])
        where = " AND ".join(filters)
        total = self.connection.execute(
            "SELECT COUNT(*) FROM tag_group_members m JOIN tags t ON t.id=m.tag_id WHERE " + where,
            parameters,
        ).fetchone()[0]
        order_by = "t.name" if sort == "name" else "t.post_count DESC,t.name"
        rows = self.connection.execute(
            """SELECT t.id,t.name,t.render_name,t.cn_name,t.category,t.category_name,
                      t.post_count,t.nsfw,t.deprecated
               FROM tag_group_members m JOIN tags t ON t.id=m.tag_id WHERE """
            + where
            + f" ORDER BY {order_by} LIMIT ? OFFSET ?",
            [*parameters, max(0, limit), max(0, offset)],
        ).fetchall()
        return {
            "id": group["id"],
            "name": group["name"],
            "cn_name": group["cn_name"],
            "total": total,
            "items": [_tag_summary(row) for row in rows],
        }

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
            weight = 0.2 if seed_name in GENERIC_ARTIST_SEED_TAGS else 1.0
            rows = self.connection.execute(
                """SELECT a.name,a.render_name,a.post_count,e.cooc_count,e.npmi,e.score_version
                   FROM artist_tag_cooccurrence e JOIN artists a ON a.id=e.artist_id
                   WHERE e.tag_id=?""",
                (seed_id,),
            ).fetchall()
            for row in rows:
                name = row["name"]
                scores[name] += weight * (row["npmi"] if row["npmi"] is not None else math.log1p(row["cooc_count"]))
                counts[name] += row["cooc_count"]
                sources[name].append(seed_name)
                post_counts[name] = row["post_count"]
                versions[name] = row["score_version"]
        for name, hit_sources in sources.items():
            scores[name] *= 1.0 + 0.3 * (len(set(hit_sources)) - 1)
        ranked = sorted(scores, key=lambda name: (scores[name], counts[name]), reverse=True)
        ordered: list[str] = []
        for name in ranked:
            unique_sources = set(sources[name])
            if unique_sources <= GENERIC_ARTIST_SEED_TAGS and len(unique_sources) < 2:
                continue
            ordered.append(name)
            if len(ordered) >= limit:
                break
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

    def artist_summary(self) -> dict[str, int]:
        row = self.connection.execute(
            """SELECT COUNT(*) AS artist_count,
                      COALESCE(SUM(a.post_count),0) AS post_count,
                      (SELECT COUNT(*) FROM artist_tag_cooccurrence) AS association_count
               FROM artists a"""
        ).fetchone()
        return {
            "artist_count": int(row["artist_count"]),
            "post_count": int(row["post_count"]),
            "association_count": int(row["association_count"]),
        }

    def search_artists(
        self,
        query: str = "",
        *,
        sort: str = "popularity",
        limit: int = 48,
        offset: int = 0,
    ) -> dict[str, Any]:
        raw_query = query.strip().lower().removeprefix("@").strip()
        canonical_query = _canonical(raw_query) if raw_query else ""
        filters: list[str] = []
        parameters: list[Any] = []
        if canonical_query:
            filters.append("(INSTR(LOWER(a.name),?)>0 OR INSTR(LOWER(a.render_name),?)>0)")
            parameters.extend([canonical_query, raw_query.replace("_", " ")])
        where = " WHERE " + " AND ".join(filters) if filters else ""
        total = self.connection.execute(
            "SELECT COUNT(*) FROM artists a" + where,
            parameters,
        ).fetchone()[0]
        if canonical_query:
            relevance = (
                "CASE WHEN LOWER(a.name)=? THEN 0 WHEN LOWER(a.name) LIKE ? THEN 1 "
                "WHEN LOWER(a.render_name) LIKE ? THEN 2 ELSE 3 END,"
            )
            order_parameters = [canonical_query, canonical_query + "%", "@" + raw_query.replace("_", " ") + "%"]
        else:
            relevance = ""
            order_parameters = []
        order_by = "a.name" if sort == "name" else "a.post_count DESC,a.name"
        rows = self.connection.execute(
            """SELECT a.id,a.name,a.render_name,a.post_count,
                      (SELECT COUNT(*) FROM artist_tag_cooccurrence e WHERE e.artist_id=a.id) AS association_count
               FROM artists a"""
            + where
            + " ORDER BY "
            + relevance
            + order_by
            + " LIMIT ? OFFSET ?",
            [*parameters, *order_parameters, max(0, limit), max(0, offset)],
        ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            preview = self.connection.execute(
                """SELECT t.name,t.render_name,t.cn_name,t.category_name,e.cooc_count,e.npmi
                   FROM artist_tag_cooccurrence e JOIN tags t ON t.id=e.tag_id
                   WHERE e.artist_id=? AND t.deprecated=0 AND t.nsfw=0 AND t.category_name='general'
                   ORDER BY e.rank LIMIT 4""",
                (row["id"],),
            ).fetchall()
            items.append({
                "id": row["id"],
                "name": row["name"],
                "render_name": row["render_name"],
                "post_count": row["post_count"],
                "association_count": row["association_count"],
                "preview_tags": [dict(item) for item in preview],
            })
        return {"total": int(total), "items": items}

    def get_artist(self, canonical_name: str) -> dict[str, Any] | None:
        canonical = _canonical(canonical_name.strip().removeprefix("@"))
        row = self.connection.execute(
            """SELECT a.id,a.name,a.render_name,a.post_count,
                      (SELECT COUNT(*) FROM artist_tag_cooccurrence e WHERE e.artist_id=a.id) AS association_count
               FROM artists a WHERE a.name=?""",
            (canonical,),
        ).fetchone()
        return dict(row) if row is not None else None

    def artist_contexts(self, canonical_name: str) -> list[dict[str, Any]] | None:
        artist = self.get_artist(canonical_name)
        if artist is None:
            return None
        rows = self.connection.execute(
            """SELECT t.id,t.name,t.render_name,t.cn_name,t.category,t.category_name,
                      t.post_count,t.nsfw,t.deprecated,e.cooc_count,e.artist_post_count,
                      e.tag_post_count,e.npmi,e.rank,e.score_version
               FROM artist_tag_cooccurrence e JOIN tags t ON t.id=e.tag_id
               WHERE e.artist_id=? AND t.deprecated=0 ORDER BY e.rank""",
            (artist["id"],),
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            groups = [dict(item) for item in self.connection.execute(
                """SELECT g.id,g.name,g.cn_name FROM tag_group_members m
                   JOIN tag_groups g ON g.id=m.group_id WHERE m.tag_id=? ORDER BY g.id""",
                (row["id"],),
            )]
            dimensions = _artist_context_dimensions(str(row["category_name"]), groups)
            artist_post_count = max(1, int(row["artist_post_count"]))
            npmi = float(row["npmi"]) if row["npmi"] is not None else None
            item = _tag_summary(row)
            item.update({
                "groups": groups,
                "dimensions": dimensions,
                "cooc_count": int(row["cooc_count"]),
                "coverage": round(min(1.0, int(row["cooc_count"]) / artist_post_count), 4),
                "npmi": round(npmi, 6) if npmi is not None else None,
                "association_score": round(min(1.0, max(0.0, npmi)), 4) if npmi is not None else None,
                "rank": int(row["rank"]),
                "algorithm_version": row["score_version"],
                "data_pack_id": self.pack_id,
            })
            result.append(item)
        return result

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


def _artist_context_dimensions(category_name: str, groups: list[dict[str, Any]]) -> list[str]:
    if category_name == "character":
        return ["character"]
    if category_name == "copyright":
        return ["copyright"]
    group_names = {str(group["name"]) for group in groups}
    dimensions = [name for name, members in ARTIST_CONTEXT_GROUPS.items() if group_names & members]
    return dimensions or (["meta"] if category_name == "meta" else ["motif"])


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
