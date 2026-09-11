import pytest

from anima_prompt_studio.domain.execution_models import RemoteProfile
from anima_prompt_studio_v3.core.model_versions import workflow_models
from anima_prompt_studio_v3.core.profiles import ModelProfileRegistry
from anima_prompt_studio_v3.core.workflow_compiler import V3WorkflowCompiler, WorkflowRenderError
from anima_prompt_studio_v3.runtime.generation import CandidateToPromptJobAdapter, GenerationSettings
from anima_prompt_studio_v3.runtime.packaged_workflows import packaged_workflow_profiles
from anima_prompt_studio_v3.runtime.workflow_compatibility import infer_workflow_model_profiles


def workflow(version):
    return next(p for p in packaged_workflow_profiles() if p.id == f"v3_aesthetic_v1_{version}")


@pytest.mark.parametrize("version", [0, 1])
def test_explicit_version_renders_its_weight_and_rejects_other_version(version):
    model = f"anima_aesthetic_v1_{version}"
    prepared = CandidateToPromptJobAdapter().prepare_direct(
        positive_prompt="an adult woman holding flowers", negative_prompt="blurry",
        model_profile_id=model, settings=GenerationSettings(seed=8798399215689017476, steps=37, cfg=4.25))
    remote = RemoteProfile(display_name="test", ssh_host="example.test", ssh_user="test")
    compiler = V3WorkflowCompiler()
    rendered = compiler.render(prepared.job, workflow(version), remote, model, "test")
    assert rendered.checkpoint_name == f"anima-aesthetic-v1.{version}.safetensors"
    assert rendered.workflow["7"]["inputs"]["seed"] == 8798399215689017476
    assert rendered.workflow["7"]["inputs"]["cfg"] == 4.25
    assert rendered.workflow["7"]["inputs"]["steps"] == 37
    assert rendered.workflow["5"]["inputs"]["text"] == "blurry"
    with pytest.raises(WorkflowRenderError, match="不支持"):
        compiler.render(prepared.job, workflow(1-version), remote, model, "test")


def test_legacy_workflow_version_comes_from_bound_weight_without_mutating_source():
    profile = workflow(0)
    profile.compatible_model_profiles = ["anima_aesthetic_v1"]
    before = profile.model_dump()
    assert workflow_models(profile) == ["anima_aesthetic_v1_0"]
    assert profile.model_dump() == before
    assert infer_workflow_model_profiles(profile.api_workflow, "22_misleading_v1.1.json") == ["anima_aesthetic_v1_0"]
    profile.api_workflow["1"]["inputs"]["unet_name"] = "custom-aesthetic.safetensors"
    assert workflow_models(profile) == ["anima_aesthetic_v1"]


def test_cross_version_server_mapping_is_not_compatible():
    profile = workflow(0)
    profile.api_workflow["1"]["inputs"]["unet_name"] = "anima-aesthetic-v1.1.safetensors"
    assert workflow_models(profile) == []


def test_gallery_compatibility_understands_explicit_version_without_collapsing_weight():
    from anima_prompt_studio.services.gallery_upscale import choose_txt2img_workflow, build_gallery_regen_job
    profiles = [workflow(1), workflow(0)]
    selected = choose_txt2img_workflow(profiles, "anima_aesthetic_v1_0")
    assert selected.id == "v3_aesthetic_v1_0"
    job = build_gallery_regen_job({"model":"anima_aesthetic_v1_0", "prompt":"adult woman", "width":768, "height":1024}, workflow_id=selected.id, count=1)
    assert job.model_profile_id == "anima_aesthetic_v1_0"


def test_catalog_hides_family_alias_but_can_read_old_records():
    registry = ModelProfileRegistry.built_in()
    assert registry.get("anima_aesthetic_v1").variant.value == "aesthetic"
    ids = {p.id for p in registry.all()}
    assert "anima_aesthetic_v1" not in ids
    assert {"anima_aesthetic_v1_0", "anima_aesthetic_v1_1"} <= ids
