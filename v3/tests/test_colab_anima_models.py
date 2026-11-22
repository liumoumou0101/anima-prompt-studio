import time

import pytest

from anima_prompt_studio.domain.execution_models import RemoteProfile
from anima_prompt_studio_v3.core.profiles import ModelProfileRegistry
from anima_prompt_studio_v3.core.runtime_profiles import V3RuntimeProfiles
from anima_prompt_studio_v3.core.model_versions import workflow_models
from anima_prompt_studio_v3.core.generation_recipes import build_workflow_recipe_contract
from anima_prompt_studio_v3.core.workflow_compiler import V3WorkflowCompiler
from anima_prompt_studio_v3.runtime.generation import CandidateToV2PromptJobAdapter, V2GenerationSettings
from anima_prompt_studio_v3.runtime.workflow_catalog import WorkflowCatalog, catalog, fingerprint
from anima_prompt_studio_v3.runtime.workflow_import import profile_from_api
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository


BASELINES = [
    ('anima_base_v1', 'v3_base_v1', 35, 4.5, 'er_sde', 'normal'),
    ('anima_aesthetic_v1_1', 'v3_aesthetic_v1_1', 35, 4.5, 'euler', 'normal'),
    ('anima_turbo_v1_1', '23_Turbo_v1.1', 10, 1.0, 'er_sde', 'simple'),
    ('animayume_v1_0_final', '24_AnimaYume_v1.0_Final', 30, 5.5, 'euler_ancestral', 'normal'),
    ('miaomiao_harem_anima_v1_6', '25_MiaoMiao_Harem_ANIMA_v1.6', 30, 4.5, 'euler', 'normal'),
    ('wai_anima_v1_0', 'v3_wai_anima_v1_0', 25, 4.5, 'euler_ancestral', 'normal'),
]


def prepare(model):
    return CandidateToV2PromptJobAdapter().prepare_direct(
        positive_prompt='a garden', negative_prompt='', model_profile_id=model,
        settings=V2GenerationSettings(seed=42),
    ).job


def test_wai_registry_recipe_and_compiled_assets(tmp_path):
    model = ModelProfileRegistry.built_in().get('wai_anima_v1_0')
    assert (model.family, model.variant, model.positive_prefix, model.negative_prompt) == ('anima', 'community', (), ())
    workflow = next(p for p, _ in catalog(tmp_path / 'user.db') if p.id == 'v3_wai_anima_v1_0')
    assert workflow_models(workflow) == ['wai_anima_v1_0']
    assert workflow.lora_slots == []
    assert 'model_shift' not in workflow.bindings
    contract = build_workflow_recipe_contract(workflow)
    assert contract['default_recipe_id'] == 'wai_baseline'
    assert contract['stages'] == [dict(id='base', display_name='WAI ANIMA 单阶段', steps=25, cfg=4.5, sampler='euler_ancestral', scheduler='normal')]
    graph = V3WorkflowCompiler().render(prepare(model.id), workflow, RemoteProfile(id='test', display_name='test', ssh_host='localhost', ssh_user='test'), model.id, 'test').workflow
    assert graph['1']['inputs']['unet_name'] == 'waiANIMA_v10Base10.safetensors'
    assert graph['3']['inputs']['clip_name'] == 'qwen_3_06b_base.safetensors'
    assert graph['8']['inputs']['vae_name'] == 'qwen_image_vae.safetensors'
    assert graph['7']['inputs']['seed'] == 42
    assert profile_from_api(graph).compatible_model_profiles == [model.id]


@pytest.fixture
def native_catalog(tmp_path):
    manager = WorkflowCatalog(tmp_path / 'user.db')
    remote = RemoteProfile(id='native', display_name='Native ComfyUI', ssh_host='localhost', ssh_user='test', known_host_fingerprint='SHA256:test')
    repo = SQLiteRepository(manager.database)
    repo.save_remote_profile(remote)
    repo.close()
    # Independent native-node allowlist: a leaked ResolutionSelector/custom optimization node cannot pass.
    info = {name: {'input': {'required': {}}} for name in (
        'UNETLoader', 'CLIPLoader', 'CLIPTextEncode', 'EmptyLatentImage',
        'KSampler', 'VAELoader', 'VAEDecode', 'SaveImage', 'ModelSamplingAuraFlow',
    )}
    for profile, _ in catalog(manager.database):
        for node in profile.api_workflow.values():
            if node['class_type'] not in info:
                continue
            inputs = info[node['class_type']]['input']['required']
            for name, value in node['inputs'].items():
                if isinstance(value, (str, int, float)):
                    choices = inputs.setdefault(name, [[]])[0]
                    if value not in choices:
                        choices.append(value)
    info['KSampler']['input']['required']['sampler_name'] = [['euler', 'euler_ancestral', 'er_sde']]
    info['KSampler']['input']['required']['scheduler'] = [['normal', 'simple']]
    manager._write('workflow_capabilities:native', dict(checked_at=time.time(), fingerprint=fingerprint(remote), object_info=info, comfyui_version='0.35.0'))
    return manager


@pytest.mark.parametrize('model,workflow_id,steps,cfg,sampler,scheduler', BASELINES)
def test_six_baselines_resolve_native_nodes_and_keep_defaults(native_catalog, model, workflow_id, steps, cfg, sampler, scheduler):
    manager = native_catalog
    item = next(i for i in manager.report('native')['items'] if i['workflow_id'] == workflow_id)
    assert item['state'] == 'ready', item
    workflow = manager.resolve('native', workflow_id)
    assert all(n['class_type'] != 'ResolutionSelector' for n in workflow.api_workflow.values())
    runtime = V3RuntimeProfiles().get_model(model)
    assert (runtime.steps, runtime.cfg, runtime.sampler, runtime.scheduler) == (steps, cfg, sampler, scheduler)
    contract = build_workflow_recipe_contract(workflow)
    recipe = next(r for r in contract['generation_recipes'] if r['id'] == contract['default_recipe_id'])
    assert recipe['parameters'] == dict(steps=steps, cfg=cfg, sampler=sampler, scheduler=scheduler)
    graph = V3WorkflowCompiler().render(prepare(model), workflow, manager.remote('native'), model, 'test').workflow
    inputs = graph[workflow.bindings['steps'].node_id]['inputs']
    assert (inputs['steps'], inputs['cfg'], inputs['sampler_name'], inputs['scheduler']) == (steps, cfg, sampler, scheduler)


def test_miaomiao_explicit_encoder_mapping_reaches_compiled_graph(native_catalog):
    manager = native_catalog
    snapshot = manager._read('workflow_capabilities:native')
    snapshot['object_info']['CLIPLoader']['input']['required']['clip_name'] = [['qwen_3_06b_base.safetensors']]
    manager._write('workflow_capabilities:native', snapshot)
    workflow_id = '25_MiaoMiao_Harem_ANIMA_v1.6'
    item = next(i for i in manager.report('native')['items'] if i['workflow_id'] == workflow_id)
    assert item['state'] == 'invalid_inputs'
    encoder = next(a for a in item['assets'] if a['key'].endswith('.clip_name'))
    manager.save_mapping('native', workflow_id, item['revision'], {encoder['key']: 'qwen_3_06b_base.safetensors'})
    workflow = manager.resolve('native', workflow_id)
    model = 'miaomiao_harem_anima_v1_6'
    graph = V3WorkflowCompiler().render(prepare(model), workflow, manager.remote('native'), model, 'mapped').workflow
    assert graph['3']['inputs']['clip_name'] == 'qwen_3_06b_base.safetensors'
    assert graph['1']['inputs']['unet_name'] == 'miaomiaoHarem_anima16.safetensors'
    assert graph['2']['inputs']['shift'] == 3
    original = next(p for p, _ in catalog(manager.database) if p.id == workflow_id)
    assert original.api_workflow['3']['inputs']['clip_name'] == 'miaomiaoHarem_anima16_txt.safetensors'
