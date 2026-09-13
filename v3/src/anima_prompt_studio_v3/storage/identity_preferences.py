"""User-owned identity shortcuts; the read-only reference pack is never modified."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
import sqlite3
import unicodedata


def normalize_name(value: str) -> str:
    return "_".join(unicodedata.normalize("NFKC", value).strip().lstrip("@").lower()
                    .replace("\\(", "(").replace("\\)", ")").replace("_", " ").split())


def normalize_alias(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).strip().lstrip("@").casefold().replace("_", " ").split())


class IdentityPreferences:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS identity_preferences (
                    kind TEXT NOT NULL, name TEXT NOT NULL, favorite INTEGER NOT NULL DEFAULT 0,
                    used_at TEXT, used_count INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(kind,name));
                CREATE TABLE IF NOT EXISTS identity_aliases (
                    kind TEXT NOT NULL, normalized_alias TEXT NOT NULL, alias TEXT NOT NULL,
                    name TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(kind,normalized_alias));
                CREATE INDEX IF NOT EXISTS identity_alias_name ON identity_aliases(kind,name);
            """)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def list(self, kind: str) -> dict:
        with self._connect() as db:
            favorites = [dict(row) for row in db.execute(
                "SELECT * FROM identity_preferences WHERE kind=? AND favorite=1 ORDER BY name", (kind,))]
            recent = [dict(row) for row in db.execute(
                "SELECT * FROM identity_preferences WHERE kind=? AND used_at IS NOT NULL ORDER BY used_at DESC,name LIMIT 20", (kind,))]
            aliases = [dict(row) for row in db.execute(
                "SELECT * FROM identity_aliases WHERE kind=? ORDER BY normalized_alias", (kind,))]
        return {"favorites": favorites, "recent": recent, "aliases": aliases}

    def use(self, kind: str, names: list[str]):
        stamp = datetime.now(UTC).isoformat()
        with self._connect() as db:
            db.executemany("""INSERT INTO identity_preferences(kind,name,used_at,used_count) VALUES(?,?,?,1)
                ON CONFLICT(kind,name) DO UPDATE SET used_at=excluded.used_at,used_count=used_count+1""",
                [(kind, name, stamp) for name in dict.fromkeys(normalize_name(n) for n in names) if name])

    def favorite(self, kind: str, name: str, enabled: bool):
        with self._connect() as db:
            db.execute("""INSERT INTO identity_preferences(kind,name,favorite) VALUES(?,?,?)
                ON CONFLICT(kind,name) DO UPDATE SET favorite=excluded.favorite""",
                (kind, normalize_name(name), int(enabled)))

    def save_alias(self, kind: str, name: str, alias: str):
        name, normalized = normalize_name(name), normalize_alias(alias)
        if not name or not normalized:
            raise ValueError("别名和 tag 不能为空。")
        with self._connect() as db:
            existing = db.execute("SELECT name FROM identity_aliases WHERE kind=? AND normalized_alias=?",
                                  (kind, normalized)).fetchone()
            if existing and existing[0] != name:
                raise ValueError("这个别名已指向另一个 tag，请先删除旧映射。")
            db.execute("""INSERT INTO identity_aliases(kind,normalized_alias,alias,name,created_at)
                VALUES(?,?,?,?,?) ON CONFLICT(kind,normalized_alias) DO UPDATE SET alias=excluded.alias""",
                (kind, normalized, alias.strip(), name, datetime.now(UTC).isoformat()))

    def delete_alias(self, kind: str, alias: str):
        with self._connect() as db:
            db.execute("DELETE FROM identity_aliases WHERE kind=? AND normalized_alias=?", (kind, normalize_alias(alias)))
