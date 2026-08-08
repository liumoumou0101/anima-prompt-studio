from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from anima_prompt_studio.domain.models import ArtistProfile, CharacterCard, LoRAProfile, PromptJob


SCHEMA_VERSION = 1


def default_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    return base / "AnimaPromptStudio"


class SQLiteRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        data_dir = (db_path.parent if db_path else default_data_dir())
        data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path or data_dir / "anima_prompt_studio.db"
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError("数据库版本高于当前程序支持的版本。")
        if version and version < SCHEMA_VERSION:
            shutil.copy2(self.db_path, self.db_path.with_suffix(f".v{version}.bak"))
        with self.connection:
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS prompt_jobs (
                    id TEXT PRIMARY KEY, project_name TEXT NOT NULL, updated_at TEXT NOT NULL,
                    original_zh TEXT NOT NULL, positive_prompt TEXT NOT NULL, payload_json TEXT NOT NULL,
                    favorite INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_updated ON prompt_jobs(updated_at DESC);
                CREATE TABLE IF NOT EXISTS characters (id TEXT PRIMARY KEY, display_name TEXT NOT NULL, payload_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS artists (id TEXT PRIMARY KEY, display_name TEXT NOT NULL, payload_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS loras (id TEXT PRIMARY KEY, display_name TEXT NOT NULL, payload_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
            """)
            self.connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def save_job(self, job: PromptJob, favorite: bool = False) -> None:
        job.touch()
        payload = job.model_dump_json()
        with self.connection:
            self.connection.execute("""
                INSERT INTO prompt_jobs(id, project_name, updated_at, original_zh, positive_prompt, payload_json, favorite)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET project_name=excluded.project_name,
                updated_at=excluded.updated_at, original_zh=excluded.original_zh,
                positive_prompt=excluded.positive_prompt, payload_json=excluded.payload_json,
                favorite=MAX(prompt_jobs.favorite, excluded.favorite)
            """, (job.id, job.project_name, job.updated_at.isoformat(), job.original_zh, job.positive_prompt, payload, int(favorite)))

    def load_job(self, job_id: str) -> PromptJob:
        row = self.connection.execute("SELECT payload_json FROM prompt_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError(f"历史任务不存在：{job_id}")
        return PromptJob.model_validate_json(row[0])

    def list_jobs(self, limit: int = 100) -> list[dict]:
        rows = self.connection.execute(
            "SELECT id, project_name, updated_at, original_zh, favorite FROM prompt_jobs ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    def save_entity(self, entity: CharacterCard | ArtistProfile | LoRAProfile) -> None:
        table = {CharacterCard: "characters", ArtistProfile: "artists", LoRAProfile: "loras"}[type(entity)]
        with self.connection:
            self.connection.execute(
                f"INSERT INTO {table}(id, display_name, payload_json) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name, payload_json=excluded.payload_json",
                (entity.id, entity.display_name, entity.model_dump_json()),
            )

    def list_entities(self, model_type: type[CharacterCard] | type[ArtistProfile] | type[LoRAProfile]):
        table = {CharacterCard: "characters", ArtistProfile: "artists", LoRAProfile: "loras"}[model_type]
        return [model_type.model_validate_json(row[0]) for row in self.connection.execute(f"SELECT payload_json FROM {table} ORDER BY display_name")]

    def set_setting(self, key: str, value) -> None:
        with self.connection:
            self.connection.execute(
                "INSERT INTO settings(key,value_json) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                (key, json.dumps(value, ensure_ascii=False)),
            )

    def get_setting(self, key: str, default=None):
        row = self.connection.execute("SELECT value_json FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def close(self) -> None:
        self.connection.close()

