import json

import pytest
from pydantic import ValidationError

from anima_prompt_studio_v3.api.models import WorkbenchGenerationSettings, GenerationBridgeSettings
from anima_prompt_studio_v3.api.workspace_store import WorkspaceStore
from anima_prompt_studio_v3.runtime.generation import GenerationSettings
from anima_prompt_studio_v3.adapters.v2.gallery import _gallery_generation_params


@pytest.mark.parametrize("model", [WorkbenchGenerationSettings, GenerationBridgeSettings])
@pytest.mark.parametrize("seed", [2**53 - 1, 2**53 + 1, 8798399215689017476, 2**63 - 1])
def test_seed_survives_browser_json_and_runtime_conversion(model, seed):
    request = model(seed=str(seed))
    assert request.seed == seed
    wire = json.loads(request.model_dump_json())
    assert wire["seed"] == (str(seed) if seed > 2**53 - 1 else seed)
    assert GenerationSettings(seed=wire["seed"]).seed == seed


@pytest.mark.parametrize("seed", [True, 1.5, "1e9", "", "-2", str(2**63)])
def test_invalid_seed_is_rejected(seed):
    with pytest.raises(ValidationError):
        GenerationBridgeSettings(seed=seed)


def test_legacy_workspace_and_gallery_display_exact_seed(tmp_path):
    seed = 8798399215689017476
    from anima_prompt_studio_v3.core.requirements import project_conversation
    draft = {"generation_settings": {"seed": seed}}
    projected = project_conversation(draft)
    assert projected["generation_settings"]["seed"] == str(seed)
    assert draft["generation_settings"]["seed"] == seed
    assert _gallery_generation_params({"seed": seed})["seed"] == str(seed)
    store = WorkspaceStore(tmp_path / "workspaces.sqlite")
    saved = store.create("large seed", draft)
    restored = store.get(saved["id"])
    assert restored["draft"]["generation_settings"]["seed"] == str(seed)
