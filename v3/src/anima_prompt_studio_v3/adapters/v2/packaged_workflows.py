from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from anima_prompt_studio.domain.execution_models import WorkflowProfile
from anima_prompt_studio.repositories import SQLiteRepository


def ensure_packaged_workflow_profiles(database: Path) -> int:
    """Seed verified workflow profiles into a V2 database without overwriting local edits."""

    database = Path(database).expanduser().resolve()
    resources = files("anima_prompt_studio_v3").joinpath("configs", "workflow_profiles")
    packaged: list[WorkflowProfile] = []
    for resource in sorted(resources.iterdir(), key=lambda item: item.name):
        if not resource.name.endswith(".json"):
            continue
        packaged.append(WorkflowProfile.model_validate_json(resource.read_text(encoding="utf-8")))

    repository = SQLiteRepository(database)
    try:
        existing = {profile.id for profile in repository.list_workflow_profiles()}
        imported = 0
        for profile in packaged:
            if profile.id in existing:
                continue
            repository.save_workflow_profile(profile)
            imported += 1
        return imported
    finally:
        repository.close()
