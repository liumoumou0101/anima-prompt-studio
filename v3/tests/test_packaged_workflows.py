from __future__ import annotations

from pathlib import Path

from anima_prompt_studio.repositories import SQLiteRepository
from anima_prompt_studio_v3.adapters.v2 import ensure_packaged_workflow_profiles


def test_packaged_community_workflows_seed_a_new_v2_database(tmp_path: Path) -> None:
    database = tmp_path / "v2.db"

    assert ensure_packaged_workflow_profiles(database) == 6
    assert ensure_packaged_workflow_profiles(database) == 0

    repository = SQLiteRepository(database)
    try:
        profiles = {item.id: item for item in repository.list_workflow_profiles()}
    finally:
        repository.close()

    assert profiles["24_AnimaYume_v1.0_Final"].compatible_model_profiles == ["animayume_v1_0_final"]
    assert profiles["25_MiaoMiao_Harem_ANIMA_v1.6"].runtime_assets["text_encoder"] == "miaomiaoHarem_anima16_txt.safetensors"
    assert profiles["27_AnimaYume"].api_workflow["902"]["class_type"] == "AnimaLayerReplayPatcher"
    assert profiles["28_MiaoMiao"].compatible_model_profiles == ["miaomiao_harem_anima_v1_6"]
    assert profiles["23_Turbo_v1.1"].runtime_assets["checkpoint"] == "anima-turbo-v1.1.safetensors"
    assert profiles["26_Turbo_v1.1"].api_workflow["901"]["class_type"] == "AnimaNormalizedAttentionGuidance"


def test_official_upgrade_archives_previous_version(tmp_path, monkeypatch):
    from anima_prompt_studio_v3.adapters.v2 import packaged_workflows as module
    database = tmp_path / "v2.db"
    originals = module.packaged_workflow_profiles()
    module.ensure_packaged_workflow_profiles(database)
    revised = originals[0].model_copy(update={"notes": "updated official guidance"})
    monkeypatch.setattr(module, "packaged_workflow_profiles", lambda: [revised])
    assert module.ensure_packaged_workflow_profiles(database) == 1
    assert module.ensure_packaged_workflow_profiles(database) == 0
    repository = SQLiteRepository(database)
    try:
        assert repository.get_workflow_profile(revised.id).notes == revised.notes
        key = "workflow_template_archive:" + revised.id + ":" + module.workflow_revision(originals[0])
        assert repository.get_setting(key)["notes"] == originals[0].notes
    finally:
        repository.close()


def test_official_upgrade_preserves_user_edits(tmp_path, monkeypatch):
    from anima_prompt_studio_v3.adapters.v2 import packaged_workflows as module
    database = tmp_path / "v2.db"
    original = module.packaged_workflow_profiles()[0]
    module.ensure_packaged_workflow_profiles(database)
    repository = SQLiteRepository(database)
    try:
        repository.save_workflow_profile(original.model_copy(update={"notes": "my custom settings"}))
    finally:
        repository.close()
    monkeypatch.setattr(module, "packaged_workflow_profiles", lambda: [original.model_copy(update={"notes": "new official"})])
    assert module.ensure_packaged_workflow_profiles(database) == 0
    repository = SQLiteRepository(database)
    try:
        assert repository.get_workflow_profile(original.id).notes == "my custom settings"
    finally:
        repository.close()


def test_unknown_existing_record_is_not_claimed(tmp_path):
    from anima_prompt_studio_v3.adapters.v2 import packaged_workflows as module
    database = tmp_path / "v2.db"
    original = module.packaged_workflow_profiles()[0]
    repository = SQLiteRepository(database)
    try:
        repository.save_workflow_profile(original.model_copy(update={"notes": "legacy custom"}))
    finally:
        repository.close()
    assert module.ensure_packaged_workflow_profiles(database) == 5
    repository = SQLiteRepository(database)
    try:
        assert repository.get_workflow_profile(original.id).notes == "legacy custom"
        assert repository.get_setting("workflow_template_revision:" + original.id) is None
    finally:
        repository.close()


def test_failed_import_rolls_back_profiles_and_revisions(tmp_path):
    import pytest
    import sqlite3
    from anima_prompt_studio_v3.adapters.v2 import packaged_workflows as module
    database = tmp_path / "v2.db"
    second = module.packaged_workflow_profiles()[1]
    repository = SQLiteRepository(database)
    try:
        # Fail after the first profile has already been inserted.
        repository.connection.execute(
            "CREATE TRIGGER reject_second BEFORE INSERT ON workflow_profiles "
            "WHEN NEW.id = '" + second.id.replace("'", "''") + "' "
            "BEGIN SELECT RAISE(ABORT, 'simulated failure'); END"
        )
        repository.connection.commit()
    finally:
        repository.close()
    with pytest.raises(sqlite3.IntegrityError):
        module.ensure_packaged_workflow_profiles(database)
    repository = SQLiteRepository(database)
    try:
        assert repository.list_workflow_profiles() == []
        assert repository.connection.execute(
            "SELECT count(*) FROM settings WHERE key LIKE 'workflow_template_revision:%'"
        ).fetchone()[0] == 0
    finally:
        repository.close()
