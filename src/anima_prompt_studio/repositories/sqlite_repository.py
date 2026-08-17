from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from anima_prompt_studio.domain.execution_models import (
    ACTIVE_RUN_STATES,
    GenerationArtifact,
    GenerationRun,
    RemoteProfile,
    WorkflowProfile,
)
from anima_prompt_studio.domain.models import ArtistProfile, CharacterCard, LoRAProfile, PromptJob


SCHEMA_VERSION = 4


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
                CREATE TABLE IF NOT EXISTS remote_profiles (
                    id TEXT PRIMARY KEY, display_name TEXT NOT NULL, payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_profiles (
                    id TEXT PRIMARY KEY, display_name TEXT NOT NULL, payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS generation_runs (
                    id TEXT PRIMARY KEY, prompt_job_id TEXT NOT NULL, remote_profile_id TEXT NOT NULL,
                    workflow_profile_id TEXT NOT NULL, remote_prompt_id TEXT NOT NULL,
                    state TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_generation_runs_updated ON generation_runs(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_generation_runs_state ON generation_runs(state);
                CREATE TABLE IF NOT EXISTS generation_artifacts (
                    id TEXT PRIMARY KEY, generation_run_id TEXT NOT NULL, local_path TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_generation_artifacts_run ON generation_artifacts(generation_run_id);
                CREATE TABLE IF NOT EXISTS gallery_asset_states (
                    output_root TEXT NOT NULL, relative_path TEXT NOT NULL,
                    state TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(output_root, relative_path)
                );
                CREATE INDEX IF NOT EXISTS idx_gallery_asset_states_root
                    ON gallery_asset_states(output_root);
                CREATE TABLE IF NOT EXISTS gallery_process_jobs (
                    id TEXT PRIMARY KEY, output_root TEXT NOT NULL,
                    state TEXT NOT NULL, queue_position INTEGER NOT NULL,
                    updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_gallery_process_jobs_root_state
                    ON gallery_process_jobs(output_root,state,queue_position);
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

    def save_remote_profile(self, profile: RemoteProfile) -> None:
        with self.connection:
            self.connection.execute(
                """INSERT INTO remote_profiles(id,display_name,payload_json) VALUES(?,?,?)
                ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name,payload_json=excluded.payload_json""",
                (profile.id, profile.display_name, profile.model_dump_json(by_alias=True)),
            )

    def get_remote_profile(self, profile_id: str) -> RemoteProfile:
        row = self.connection.execute("SELECT payload_json FROM remote_profiles WHERE id=?", (profile_id,)).fetchone()
        if not row:
            raise KeyError(f"云主机配置不存在：{profile_id}")
        return RemoteProfile.model_validate_json(row[0])

    def list_remote_profiles(self, enabled_only: bool = False) -> list[RemoteProfile]:
        profiles = [
            RemoteProfile.model_validate_json(row[0])
            for row in self.connection.execute("SELECT payload_json FROM remote_profiles ORDER BY display_name")
        ]
        return [profile for profile in profiles if profile.enabled] if enabled_only else profiles

    def save_workflow_profile(self, profile: WorkflowProfile) -> None:
        with self.connection:
            self.connection.execute(
                """INSERT INTO workflow_profiles(id,display_name,payload_json) VALUES(?,?,?)
                ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name,payload_json=excluded.payload_json""",
                (profile.id, profile.display_name, profile.model_dump_json(by_alias=True)),
            )

    def get_workflow_profile(self, profile_id: str) -> WorkflowProfile:
        row = self.connection.execute("SELECT payload_json FROM workflow_profiles WHERE id=?", (profile_id,)).fetchone()
        if not row:
            raise KeyError(f"工作流配置不存在：{profile_id}")
        return WorkflowProfile.model_validate_json(row[0])

    def list_workflow_profiles(self) -> list[WorkflowProfile]:
        return [
            WorkflowProfile.model_validate_json(row[0])
            for row in self.connection.execute("SELECT payload_json FROM workflow_profiles ORDER BY display_name")
        ]

    def save_generation_run(self, run: GenerationRun) -> None:
        with self.connection:
            self.connection.execute(
                """INSERT INTO generation_runs(
                    id,prompt_job_id,remote_profile_id,workflow_profile_id,remote_prompt_id,state,updated_at,payload_json
                ) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    remote_prompt_id=excluded.remote_prompt_id,state=excluded.state,
                    updated_at=excluded.updated_at,payload_json=excluded.payload_json""",
                (
                    run.id,
                    run.prompt_job_id,
                    run.remote_profile_id,
                    run.workflow_profile_id,
                    run.remote_prompt_id,
                    run.state.value,
                    run.updated_at.isoformat(),
                    run.model_dump_json(),
                ),
            )

    def get_generation_run(self, run_id: str) -> GenerationRun:
        row = self.connection.execute("SELECT payload_json FROM generation_runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise KeyError(f"远程生成任务不存在：{run_id}")
        return GenerationRun.model_validate_json(row[0])

    def list_generation_runs(self, limit: int = 100) -> list[GenerationRun]:
        rows = self.connection.execute(
            "SELECT payload_json FROM generation_runs ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [GenerationRun.model_validate_json(row[0]) for row in rows]

    def list_active_generation_runs(self) -> list[GenerationRun]:
        states = sorted(state.value for state in ACTIVE_RUN_STATES)
        placeholders = ",".join("?" for _ in states)
        rows = self.connection.execute(
            f"SELECT payload_json FROM generation_runs WHERE state IN ({placeholders}) ORDER BY updated_at DESC",
            states,
        ).fetchall()
        return [GenerationRun.model_validate_json(row[0]) for row in rows]

    def save_generation_artifact(self, artifact: GenerationArtifact) -> None:
        with self.connection:
            self.connection.execute(
                """INSERT INTO generation_artifacts(id,generation_run_id,local_path,payload_json) VALUES(?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET local_path=excluded.local_path,payload_json=excluded.payload_json""",
                (artifact.id, artifact.generation_run_id, artifact.local_path, artifact.model_dump_json()),
            )

    def list_generation_artifacts(self, run_id: str) -> list[GenerationArtifact]:
        rows = self.connection.execute(
            "SELECT payload_json FROM generation_artifacts WHERE generation_run_id=? ORDER BY id", (run_id,)
        ).fetchall()
        return [GenerationArtifact.model_validate_json(row[0]) for row in rows]

    def list_gallery_asset_states(self, output_root: Path | str) -> dict[str, str]:
        root_key = os.path.normcase(str(Path(output_root).expanduser().resolve()))
        rows = self.connection.execute(
            "SELECT relative_path,state FROM gallery_asset_states WHERE output_root=?",
            (root_key,),
        ).fetchall()
        return {str(row["relative_path"]): str(row["state"]) for row in rows}

    def set_gallery_asset_states(
        self,
        output_root: Path | str,
        relative_paths: list[str],
        state: str,
    ) -> None:
        if state not in {"", "kept", "rejected"}:
            raise ValueError(f"不支持的画廊状态：{state}")
        root_key = os.path.normcase(str(Path(output_root).expanduser().resolve()))
        normalized = sorted({Path(path).as_posix() for path in relative_paths if path})
        now = datetime.now().astimezone().isoformat()
        with self.connection:
            if not state:
                self.connection.executemany(
                    "DELETE FROM gallery_asset_states WHERE output_root=? AND relative_path=?",
                    [(root_key, path) for path in normalized],
                )
            else:
                self.connection.executemany(
                    """INSERT INTO gallery_asset_states(output_root,relative_path,state,updated_at)
                    VALUES(?,?,?,?) ON CONFLICT(output_root,relative_path) DO UPDATE SET
                    state=excluded.state,updated_at=excluded.updated_at""",
                    [(root_key, path, state, now) for path in normalized],
                )

    def save_gallery_process_job(
        self,
        output_root: Path | str,
        job_id: str,
        state: str,
        queue_position: int,
        updated_at: datetime,
        payload: dict,
    ) -> None:
        root_key = os.path.normcase(str(Path(output_root).expanduser().resolve()))
        with self.connection:
            self.connection.execute(
                """INSERT INTO gallery_process_jobs(
                    id,output_root,state,queue_position,updated_at,payload_json
                ) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                    output_root=excluded.output_root,state=excluded.state,
                    queue_position=excluded.queue_position,updated_at=excluded.updated_at,
                    payload_json=excluded.payload_json""",
                (
                    job_id,
                    root_key,
                    state,
                    queue_position,
                    updated_at.isoformat(),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )

    def list_gallery_process_jobs(
        self,
        output_root: Path | str,
        limit: int = 100,
    ) -> list[dict]:
        root_key = os.path.normcase(str(Path(output_root).expanduser().resolve()))
        rows = self.connection.execute(
            """SELECT payload_json FROM gallery_process_jobs
            WHERE output_root=?
            ORDER BY
                CASE
                    WHEN state IN ('queued','starting','connecting','preparing','running','downloading')
                        THEN 0
                    WHEN state = 'failed' THEN 1
                    ELSE 2
                END,
                queue_position ASC, updated_at DESC
            LIMIT ?""",
            (root_key, limit),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def delete_gallery_process_job(self, output_root: Path | str, job_id: str) -> None:
        root_key = os.path.normcase(str(Path(output_root).expanduser().resolve()))
        with self.connection:
            self.connection.execute(
                "DELETE FROM gallery_process_jobs WHERE output_root=? AND id=?",
                (root_key, job_id),
            )

    def close(self) -> None:
        self.connection.close()

