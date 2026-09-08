import pytest

from anima_prompt_studio.domain.execution_models import RemoteProfile
from anima_prompt_studio_v3.adapters.v2.packaged_workflows import packaged_workflow_profiles
from anima_prompt_studio_v3.adapters.v2.generation import CandidateToV2PromptJobAdapter, V2GenerationSettings
from anima_prompt_studio_v3.core.generation_recipes import validate_job_recipe
from anima_prompt_studio_v3.core.workflow_compiler import V3WorkflowCompiler


@pytest.mark.parametrize("profile", packaged_workflow_profiles(), ids=lambda p: p.id)
@pytest.mark.parametrize("label", ["quality", "balanced", "custom", "turbo_v11_baseline", "yume_creator"])
def test_explicit_edits_reach_actual_sampler_regardless_of_recipe_label(profile, label):
    model = profile.compatible_model_profiles[0]
    prepared = CandidateToV2PromptJobAdapter().prepare_direct(
        positive_prompt="a crane in a garden", negative_prompt="text",
        model_profile_id=model,
        settings=V2GenerationSettings(preset_id=label, steps=47, cfg=6.25,
            sampler="euler", scheduler="normal", seed=123, width=768, height=1024),
    )
    validate_job_recipe(prepared.job, profile)
    remote = RemoteProfile(id="test", display_name="test", ssh_host="localhost", ssh_user="test",
        model_aliases={model: "wrong-legacy-alias.safetensors"})
    result = V3WorkflowCompiler().render(prepared.job, profile, remote, model, "test-run")
    def actual(name):
        binding = profile.bindings[name]
        return result.workflow[binding.node_id]["inputs"][binding.input_name]
    assert [actual(k) for k in ("steps", "cfg", "sampler", "scheduler", "seed", "width", "height")] == [
        47, 6.25, "euler", "normal", 123, 768, 1024]
    assert actual("checkpoint") != "wrong-legacy-alias.safetensors"
    assert result.metadata["compiler"] == "v3-workflow/1"
    assert actual("positive_prompt") == "a crane in a garden"


def test_missing_parameters_use_v3_defaults_even_for_old_quality_label():
    job = CandidateToV2PromptJobAdapter().prepare_direct(
        positive_prompt="a garden", model_profile_id="anima_aesthetic_v1",
        settings=V2GenerationSettings(preset_id="quality"),
    ).job
    assert (job.generation_params.steps, job.generation_params.cfg,
        job.generation_params.sampler, job.generation_params.scheduler) == (35, 4.5, "euler", "normal")


def test_hires_manual_base_parameters_do_not_reset_refiner():
    from copy import deepcopy
    from anima_prompt_studio.domain.execution_models import HIRES_FIX_WORKFLOW_KIND, WorkflowBinding
    profile = next(p for p in packaged_workflow_profiles() if p.id == "v3_base_v1")
    profile.workflow_kind = HIRES_FIX_WORKFLOW_KIND
    profile.api_workflow["12"] = deepcopy(profile.api_workflow["7"])
    profile.api_workflow["12"]["inputs"].update(steps=18, cfg=3, denoise=0.35)
    profile.bindings["refiner_seed"] = WorkflowBinding(node_id="12", input_name="seed")
    prepared = CandidateToV2PromptJobAdapter().prepare_direct(
        positive_prompt="a garden", model_profile_id="anima_base_v1",
        settings=V2GenerationSettings(preset_id="quality", steps=47, cfg=0,
            sampler="euler", scheduler="normal", seed=123),
    )
    remote = RemoteProfile(id="test", display_name="test", ssh_host="localhost", ssh_user="test")
    rendered = V3WorkflowCompiler().render(prepared.job, profile, remote, "anima_base_v1", "test")
    assert rendered.workflow["7"]["inputs"]["steps"] == 47
    assert rendered.workflow["7"]["inputs"]["cfg"] == 0
    assert rendered.workflow["12"]["inputs"]["steps"] == 18
    assert rendered.workflow["12"]["inputs"]["seed"] == 124
