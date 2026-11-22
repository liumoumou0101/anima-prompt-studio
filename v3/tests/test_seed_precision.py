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


@pytest.mark.parametrize("seed", [True, 1.5, "1e9", "", "-", "-2", "-1.5", -2, -1.5, str(2**63)])
def test_invalid_seed_is_rejected(seed):
    with pytest.raises(ValidationError):
        GenerationBridgeSettings(seed=seed)


@pytest.mark.parametrize("model", [WorkbenchGenerationSettings, GenerationBridgeSettings])
@pytest.mark.parametrize("seed", [-1, "-1"])
def test_random_seed_sentinel_survives_the_api_and_runtime_boundary(model, seed):
    request = model(seed=seed)
    assert request.seed == -1
    wire = json.loads(request.model_dump_json())
    assert wire["seed"] == -1
    assert GenerationSettings(seed=wire["seed"]).seed == -1


@pytest.mark.parametrize("model_id,workflow_id", [
    ("anima_base_v1", "v3_base_v1"),
    ("moss_image_sft_int8", "v3_moss_image_sft_int8"),
])
@pytest.mark.parametrize("submitted,expected", [("-1", 8798399215689017476), ("8798399215689017476", 8798399215689017476), ("0", 0)])
def test_seed_reaches_anima_and_moss_comfy_workflows_as_an_exact_nonnegative_integer(model_id, workflow_id, submitted, expected, monkeypatch):
    from anima_prompt_studio.domain.execution_models import RemoteProfile
    from anima_prompt_studio_v3.adapters.v2.packaged_workflows import packaged_workflow_profiles
    from anima_prompt_studio_v3.core import workflow_compiler
    from anima_prompt_studio_v3.runtime.generation import CandidateToPromptJobAdapter

    def random_seed(_):
        assert submitted == "-1", "fixed seeds must not be randomized"
        return 8798399215689017476

    monkeypatch.setattr(workflow_compiler.secrets, "randbelow", random_seed)
    request = GenerationBridgeSettings(seed=submitted)
    prepared = CandidateToPromptJobAdapter().prepare_direct(positive_prompt="a crane in a garden", model_profile_id=model_id,
        settings=GenerationSettings(seed=request.seed))
    profile = next(item for item in packaged_workflow_profiles() if item.id == workflow_id)
    remote = RemoteProfile(id="test", display_name="test", ssh_host="localhost", ssh_user="test")
    rendered = workflow_compiler.V3WorkflowCompiler().render(prepared.job, profile, remote, model_id, "seed-regression")
    binding = profile.bindings["seed"]
    actual = rendered.workflow[binding.node_id]["inputs"][binding.input_name]
    assert type(actual) is int and 0 <= actual <= 2**64 - 1
    assert actual == rendered.resolved_seed == expected
    assert json.loads(json.dumps(rendered.workflow))[binding.node_id]["inputs"][binding.input_name] == expected


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
