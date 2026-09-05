from __future__ import annotations

from pathlib import Path

from anima_prompt_studio.repositories import SQLiteRepository
from anima_prompt_studio_v3.adapters.v2 import ensure_packaged_workflow_profiles


def test_packaged_community_workflows_seed_a_new_v2_database(tmp_path: Path) -> None:
    database = tmp_path / "v2.db"

    assert ensure_packaged_workflow_profiles(database) == 4
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
