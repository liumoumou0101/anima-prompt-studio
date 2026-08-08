from __future__ import annotations

import re
import sqlite3
from pathlib import Path


STOPWORDS = {"a", "an", "the", "and", "or", "with", "of", "to", "in", "on", "at", "is", "are", "she", "he", "her", "his", "it", "this", "that"}


class TagDatabase:
    """Read-only query facade for the downloaded Danbooru vocabulary."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @property
    def available(self) -> bool:
        return self.path.is_file()

    @staticmethod
    def _ngrams(text: str, maximum: int = 5) -> list[str]:
        words = re.findall(r"[a-z0-9]+", text.lower())
        values: list[str] = []
        for size in range(1, min(maximum, len(words)) + 1):
            for index in range(len(words) - size + 1):
                part = words[index:index + size]
                if size == 1 and part[0] in STOPWORDS:
                    continue
                values.append("_".join(part))
        return values

    def match_english(self, text: str, limit: int = 32) -> list[dict]:
        if not self.available:
            return []
        candidates = self._ngrams(text)
        if not candidates:
            return []
        connection = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        found: dict[str, dict] = {}
        try:
            for offset in range(0, len(candidates), 400):
                chunk = candidates[offset:offset + 400]
                marks = ",".join("?" for _ in chunk)
                rows = connection.execute(
                    f"SELECT name, output_name, category, post_count FROM tags WHERE name IN ({marks}) AND is_deprecated=0 AND post_count>=25",
                    chunk,
                ).fetchall()
                for row in rows:
                    found[row["name"]] = dict(row)
                if self._table_exists(connection, "aliases"):
                    rows = connection.execute(
                        f"SELECT a.antecedent AS name, t.output_name, t.category, t.post_count FROM aliases a JOIN tags t ON t.name=a.consequent WHERE a.antecedent IN ({marks}) AND t.is_deprecated=0",
                        chunk,
                    ).fetchall()
                    for row in rows:
                        found[row["name"]] = dict(row)
        finally:
            connection.close()
        ranked = sorted(found.values(), key=lambda x: (x["name"].count("_") + 1, x["post_count"]), reverse=True)
        compact: list[dict] = []
        for item in ranked:
            words = set(item["name"].split("_"))
            if any(words < set(existing["name"].split("_")) for existing in compact):
                continue
            compact.append(item)
        return compact[:limit]

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
        return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

    def search(self, query: str, limit: int = 50) -> list[dict]:
        if not self.available or not query.strip():
            return []
        connection = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            safe = " ".join(re.findall(r"[\w]+", query.lower()))
            if not safe:
                return []
            rows = connection.execute(
                "SELECT t.output_name, t.category, t.post_count FROM tag_search s JOIN tags t ON t.name=s.canonical WHERE tag_search MATCH ? ORDER BY bm25(tag_search), t.post_count DESC LIMIT ?",
                (safe + "*", limit),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()
