import copy
import pytest

from anima_prompt_studio.domain.execution_models import RemoteProfile
from anima_prompt_studio_v3.core.profiles import ModelProfileRegistry
from anima_prompt_studio_v3.core.runtime_profiles import V3RuntimeProfiles
from anima_prompt_studio_v3.core.model_versions import workflow_models, expanded_anima_version_error
from anima_prompt_studio_v3.core.generation_recipes import build_workflow_recipe_contract
from anima_prompt_studio_v3.core.workflow_compiler import V3WorkflowCompiler, WorkflowRenderError
from anima_prompt_studio_v3.runtime.generation import CandidateToV2PromptJobAdapter, V2GenerationSettings
from anima_prompt_studio_v3.runtime.packaged_workflows import packaged_workflow_profiles
from anima_prompt_studio_v3.runtime.workflow_compatibility import infer_workflow_model_profiles
from anima_prompt_studio_v3.runtime.workflow_import import profile_from_api

CASES = [
    ("anima_2_9b_preview_v1", "Anima-2.9B-preview-v1.safetensors", "anima29_creator", 4.0, "euler", "sgm_uniform"),
    ("animayume_v1_5_base", "AnimaYume_v15_base.safetensors", "yume15_creator", 5.5, "euler_ancestral", "normal"),
]

def get_profile(model):
    return next(p for p in packaged_workflow_profiles() if p.id == "v3_" + model)

@pytest.mark.parametrize("model,weight,recipe,cfg,sampler,scheduler", CASES)
def test_complete_model_contract_and_import(model, weight, recipe, cfg, sampler, scheduler):
    model_profile = ModelProfileRegistry.built_in().get(model)
    assert model_profile.variant == "community" and model_profile.positive_prefix == ()
    assert model_profile.negative_prompt == ()
    workflow = get_profile(model)
    assert workflow.lora_slots == []
    assert set(n['class_type'] for n in workflow.api_workflow.values()) == {
        'UNETLoader', 'CLIPLoader', 'CLIPTextEncode', 'EmptyLatentImage', 'KSampler', 'VAELoader', 'VAEDecode', 'SaveImage'}
    assert 'model_shift' not in workflow.bindings
    contract = build_workflow_recipe_contract(workflow)
    assert contract['default_recipe_id'] == recipe
    default = next(r['parameters'] for r in contract['generation_recipes'] if r['id'] == recipe)
    assert default == dict(steps=30, cfg=cfg, sampler=sampler, scheduler=scheduler)
    runtime = V3RuntimeProfiles().get_model(model)
    assert (runtime.steps, runtime.cfg, runtime.sampler, runtime.scheduler) == (30, cfg, sampler, scheduler)
    job = CandidateToV2PromptJobAdapter().prepare_direct(positive_prompt='a garden', negative_prompt='', model_profile_id=model, settings=V2GenerationSettings(seed=42)).job
    remote = RemoteProfile(id='test', display_name='test', ssh_host='localhost', ssh_user='test')
    graph = V3WorkflowCompiler().render(job, workflow, remote, model, 'test').workflow
    assert graph['1']['inputs']['unet_name'] == weight
    assert graph['7']['inputs']['seed'] == 42
    assert graph['5']['inputs']['text'] == ''
    assert (graph['7']['inputs']['steps'], graph['7']['inputs']['cfg'], graph['7']['inputs']['sampler_name'], graph['7']['inputs']['scheduler']) == (30, cfg, sampler, scheduler)
    assert profile_from_api(graph).compatible_model_profiles == [model]
    # Actual loader beats old workflow filenames and names mentioned in prompts.
    graph['4']['inputs']['text'] = 'animayume, anima-aesthetic-v1.1.safetensors'
    assert infer_workflow_model_profiles(graph, '24_AnimaYume_v1.0_Final.json') == [model]

def test_yume_versions_cannot_be_silently_crossed_by_file_mapping():
    profile = get_profile('animayume_v1_5_base')
    profile.api_workflow['1']['inputs']['unet_name'] = 'animayume_v10BaseFinal.safetensors'
    assert workflow_models(profile) == []
    job = CandidateToV2PromptJobAdapter().prepare_direct(positive_prompt='a garden', model_profile_id='animayume_v1_5_base', settings=V2GenerationSettings()).job
    with pytest.raises(WorkflowRenderError, match='不支持'):
        V3WorkflowCompiler().render(job, profile, RemoteProfile(id='test', display_name='test', ssh_host='localhost', ssh_user='test'), job.model_profile_id, 'test')

def test_civitai_yume_filename_and_nested_paths():
    graph = copy.deepcopy(get_profile('animayume_v1_5_base').api_workflow)
    graph['1']['inputs']['unet_name'] = 'Anima/animayume_v15Base.safetensors'
    assert infer_workflow_model_profiles(graph) == ['animayume_v1_5_base']

@pytest.mark.parametrize('version,blocked', [(None, True), ('0.25.0', True), ('0.33.0', True), ('0.33.1', False), ('0.35.0', False)])
def test_expanded_model_requires_native_support(version, blocked):
    assert bool(expanded_anima_version_error(version)) == blocked
