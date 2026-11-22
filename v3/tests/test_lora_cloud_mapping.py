"""Submission consumes exact current gateway proposals without changing user maps."""
import pytest

from anima_prompt_studio_v3.core.lora_resolution import ResourceUnavailable
from anima_prompt_studio_v3.runtime.lora_catalog import LoraCatalog
from anima_prompt_studio_v3.runtime.packaged_workflows import workflow_revision
from anima_prompt_studio_v3.runtime.workflow_catalog import fingerprint
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
from test_cloud_submission_mapping import inspected_catalog


def test_miao_submission_uses_verified_directory_mapping_without_persisting_it(inspected_catalog):
    state=inspected_catalog
    state.manager.inspect(state.remote.id)
    resolver=LoraCatalog(state.manager)
    for workflow in state.workflows:
        graph, resolution=resolver.resolve(state.remote.id,workflow.id,"miaomiao_harem_anima_v1_6",[],refresh=False)
        assert graph.api_workflow["3"]["inputs"]["clip_name"]=="qwen_3_06b_base.safetensors"
        assert graph.runtime_assets["text_encoder"]=="qwen_3_06b_base.safetensors"
        assert resolution["availability"]=="ready"
        assert state.manager._read("workflow_mapping:"+state.remote.id+":"+workflow.id) is None
    assert state.calls==["environment","object_info","/_moss/models"]


def test_first_miao_resolution_captures_catalog_during_its_only_inspection(inspected_catalog):
    state=inspected_catalog
    graph,_=LoraCatalog(state.manager).resolve(state.remote.id,state.workflows[0].id,
                                             "miaomiao_harem_anima_v1_6",[],refresh=True)
    assert graph.api_workflow["3"]["inputs"]["clip_name"]=="qwen_3_06b_base.safetensors"
    assert state.calls==["environment","object_info","/_moss/models"]


def test_user_mapping_wins_over_a_gateway_proposal(inspected_catalog):
    state=inspected_catalog
    state.info["CLIPLoader"]["input"]["required"]["clip_name"][0].append("manual-encoder.safetensors")
    state.manager.inspect(state.remote.id)
    resolver=LoraCatalog(state.manager)
    workflow=resolver.profile(state.workflows[0].id)
    mapping={"revision":workflow_revision(workflow),"fingerprint":fingerprint(state.remote),
             "mapping":{"3.clip_name":"manual-encoder.safetensors"}}
    key="workflow_mapping:"+state.remote.id+":"+workflow.id
    state.manager._write(key,mapping)
    graph,_=resolver.resolve(state.remote.id,workflow.id,"miaomiao_harem_anima_v1_6",[],refresh=False)
    assert graph.api_workflow["3"]["inputs"]["clip_name"]=="manual-encoder.safetensors"
    assert state.manager._read(key)==mapping


def test_frozen_history_never_adopts_a_new_directory_mapping(inspected_catalog):
    state=inspected_catalog
    state.manager.inspect(state.remote.id)
    resolver=LoraCatalog(state.manager)
    profile=resolver.profile(state.workflows[0].id)
    with pytest.raises(ResourceUnavailable) as error:
        resolver.resolve(state.remote.id,profile.id,"miaomiao_harem_anima_v1_6",[],
                         frozen=profile.model_dump(mode="json"),refresh=False)
    assert "miaomiaoHarem_anima16_txt.safetensors" in str(error.value)


def test_changed_catalog_session_cannot_supply_an_automatic_mapping(inspected_catalog):
    state=inspected_catalog
    state.manager.inspect(state.remote.id)
    repository=SQLiteRepository(state.database)
    try:
        catalog=repository.get_setting("cloud_model_catalog:"+state.remote.id)
        catalog["signature"][1]="previous-session"
        repository.set_setting("cloud_model_catalog:"+state.remote.id,catalog)
    finally:
        repository.close()
    with pytest.raises(ResourceUnavailable,match="miaomiaoHarem_anima16_txt"):
        LoraCatalog(state.manager).resolve(state.remote.id,state.workflows[0].id,
                                          "miaomiao_harem_anima_v1_6",[],refresh=False)
