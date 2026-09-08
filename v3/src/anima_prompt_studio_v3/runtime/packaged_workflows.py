from __future__ import annotations

from importlib.resources import files
from pathlib import Path
import hashlib
import json
import sqlite3
from datetime import datetime, timezone

from anima_prompt_studio.domain.execution_models import WorkflowProfile
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository


def workflow_revision(profile: WorkflowProfile) -> str:
    """Content-addressed revision, independent of JSON formatting."""
    payload = json.dumps(profile.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def packaged_workflow_profiles() -> list[WorkflowProfile]:
    resources = files("anima_prompt_studio_v3").joinpath("configs", "workflow_profiles")
    profiles = [
        WorkflowProfile.model_validate_json(resource.read_text(encoding="utf-8"))
        for resource in sorted(resources.iterdir(), key=lambda item: item.name)
        if resource.name.endswith(".json")
    ]
    if len({profile.id for profile in profiles}) != len(profiles):
        raise ValueError("内置工作流 ID 重复。")
    manifest = workflow_catalog_manifest()
    if set(manifest["templates"]) != {p.id for p in profiles}:
        raise ValueError("工作流目录声明与打包文件不一致。")
    for profile in profiles:
        if manifest["templates"][profile.id]["model"] not in profile.compatible_model_profiles:
            raise ValueError("工作流模型声明不一致。")
    return profiles


def workflow_catalog_manifest():
    manifest = json.loads(files("anima_prompt_studio_v3").joinpath("configs", "workflow_catalog.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != "anima-workflow-catalog/1" or not isinstance(manifest.get("templates"), dict):
        raise ValueError("不支持的工作流目录格式。")
    for item in manifest["templates"].values():
        if not item.get("version") or item.get("tier") not in {"baseline", "experimental"} or not item.get("model"):
            raise ValueError("工作流目录缺少版本、模型或推荐级别。")
    return manifest


def migrate_packaged_workflow_ownership(database: Path) -> None:
    """One-time adoption of exact legacy copies; never seed the user database."""
    repository = SQLiteRepository(database)
    try:
        if repository.get_setting("workflow_catalog_schema") == 1:
            return
        backup = Path(database).parent / "backups" / ("workflow-catalog-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + ".db")
        backup.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(backup) as target:
            repository.connection.backup(target)
        official = {p.id: workflow_revision(p) for p in packaged_workflow_profiles()}
        with repository.connection:
            for profile in repository.list_workflow_profiles():
                revision = workflow_revision(profile)
                if official.get(profile.id) == revision:
                    repository.connection.execute(
                        "INSERT INTO settings(key,value_json) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                        ("workflow_template_revision:" + profile.id, json.dumps(revision)),
                    )
            repository.connection.execute("INSERT INTO settings(key,value_json) VALUES('workflow_catalog_schema','1') ON CONFLICT(key) DO UPDATE SET value_json='1'")
    finally:
        repository.close()


def ensure_packaged_workflow_profiles(database: Path) -> int:
    """Seed verified workflow profiles into a V2 database without overwriting local edits."""

    database = Path(database).expanduser().resolve()
    packaged = packaged_workflow_profiles()

    repository = SQLiteRepository(database)
    try:
        existing = {profile.id: profile for profile in repository.list_workflow_profiles()}
        imported = 0
        # All profile and ownership changes commit atomically. Unknown or edited
        # records are never overwritten merely because they share an official ID.
        with repository.connection:
            for profile in packaged:
                revision = workflow_revision(profile)
                current = existing.get(profile.id)
                key = "workflow_template_revision:" + profile.id
                previous = repository.get_setting(key)
                current_revision = workflow_revision(current) if current else None
                if current and current_revision not in (revision, previous):
                    continue
                if current_revision != revision:
                    if current:
                        repository.connection.execute(
                            "INSERT OR IGNORE INTO settings(key,value_json) VALUES(?,?)",
                            ("workflow_template_archive:" + profile.id + ":" + current_revision,
                             current.model_dump_json()),
                        )
                    repository.connection.execute(
                        "INSERT INTO workflow_profiles(id,display_name,payload_json) VALUES(?,?,?) "
                        "ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name,payload_json=excluded.payload_json",
                        (profile.id, profile.display_name, profile.model_dump_json(by_alias=True)),
                    )
                    imported += 1
                repository.connection.execute(
                    "INSERT INTO settings(key,value_json) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                    (key, json.dumps(revision)),
                )
        return imported
    finally:
        repository.close()
