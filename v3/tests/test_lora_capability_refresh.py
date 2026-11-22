"""A newly installed asset must not remain blocked by a fresh capability cache."""
import copy
import time

import pytest

from anima_prompt_studio.domain.execution_models import RemoteCredentials
from anima_prompt_studio_v3.core.lora_resolution import MappingConflict, ResourceUnavailable
from anima_prompt_studio_v3.core.requirements import RequirementLora
from anima_prompt_studio_v3.remote.preparation_budget import (
    DirectPreparationBudget, DirectPreparationTimeout, current_preparation_budget,
)
from anima_prompt_studio_v3.runtime.lora_catalog import LoraCatalog
from anima_prompt_studio_v3.runtime.workflow_catalog import WorkflowCatalog, fingerprint
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
from test_lora_resolution import profile_and_info
from test_v2_generation_adapter import remote_profile


def capability_catalog(tmp_path, workflow_id="v3_aesthetic_v1_1"):
    remote = remote_profile()
    database = tmp_path / "runtime.db"
    repository = SQLiteRepository(database)
    repository.save_remote_profile(remote)
    repository.close()
    manager = WorkflowCatalog(database)
    resolver = LoraCatalog(manager)
    profile = resolver.profile(workflow_id)
    # Real packaged graph, with the same remote filename mismatch observed live.
    info = {node["class_type"]: {"input": {"required": {}}}
            for node in profile.api_workflow.values()
            if node["class_type"] not in {"AnimaNormalizedAttentionGuidance", "AnimaLayerReplayPatcher"}}
    info["UNETLoader"]["input"]["required"]["unet_name"] = [["anima-base-v1.0.safetensors", "anima-turbo-v1.1.safetensors"]]
    save_capabilities(manager, remote, info)
    return resolver, profile, remote, info


def save_capabilities(manager, remote, info, *, checked_at=None):
    manager._write("workflow_capabilities:" + remote.id, {
        "checked_at": time.time() if checked_at is None else checked_at,
        "fingerprint": fingerprint(remote), "object_info": info,
    })


def install_inspector(monkeypatch, resolver, remote, info):
    calls = []

    def inspect(remote_id, credentials=None):
        calls.append((remote_id, credentials, current_preparation_budget()))
        assert len(calls) == 1, "a single resolution must not repeat remote inspection"
        save_capabilities(resolver.manager, remote, info)

    monkeypatch.setattr(resolver.manager, "inspect", inspect)
    return calls


def test_fresh_cache_missing_new_model_refreshes_same_graph_once(tmp_path, monkeypatch):
    resolver, profile, remote, info = capability_catalog(tmp_path)
    live = copy.deepcopy(info)
    live["UNETLoader"]["input"]["required"]["unet_name"][0].append("anima-aesthetic-v1.1.safetensors")
    calls = install_inspector(monkeypatch, resolver, remote, live)
    credentials = RemoteCredentials()
    with DirectPreparationBudget() as budget:
        graph, resolution = resolver.resolve(remote.id, profile.id, "anima_aesthetic_v1_1", [],
                                             credentials=credentials, refresh=True)
    assert graph.id == "v3_aesthetic_v1_1"
    assert graph.api_workflow["1"]["inputs"]["unet_name"] == "anima-aesthetic-v1.1.safetensors"
    assert resolution["availability"] == "ready"
    assert calls == [(remote.id, credentials, budget)]


def test_experimental_missing_nodes_stay_rejected_with_actionable_details(tmp_path, monkeypatch):
    resolver, profile, remote, info = capability_catalog(tmp_path, "26_Turbo_v1.1")
    calls = install_inspector(monkeypatch, resolver, remote, info)
    with pytest.raises(ResourceUnavailable) as error:
        resolver.resolve(remote.id, profile.id, "anima_turbo_v1_1", [], refresh=True)
    assert len(calls) == 1
    assert error.value.availability == "incompatible_workflow"
    assert error.value.details["missing_nodes"] == ["AnimaLayerReplayPatcher", "AnimaNormalizedAttentionGuidance"]
    assert "缺少实验工作流节点" in str(error.value) and "基础版" in str(error.value)
    assert "AnimaLayerReplayPatcher" in str(error.value)
    assert "AnimaNormalizedAttentionGuidance" in str(error.value)
    assert "901" in profile.api_workflow and "902" in profile.api_workflow


def test_cached_dispatch_never_inspects_on_missing_asset(tmp_path, monkeypatch):
    resolver, profile, remote, info = capability_catalog(tmp_path)
    calls = install_inspector(monkeypatch, resolver, remote, info)
    with pytest.raises(ResourceUnavailable) as error:
        resolver.resolve(remote.id, profile.id, "anima_aesthetic_v1_1", [], refresh=False)
    assert calls == []
    assert "anima-aesthetic-v1.1.safetensors" in str(error.value)
    assert "unet_name" in error.value.details["invalid_inputs"][0]


def test_expired_cache_inspects_only_once_even_if_model_stays_missing(tmp_path, monkeypatch):
    resolver, profile, remote, info = capability_catalog(tmp_path)
    save_capabilities(resolver.manager, remote, info, checked_at=0)
    calls = install_inspector(monkeypatch, resolver, remote, info)
    with pytest.raises(ResourceUnavailable) as error:
        resolver.resolve(remote.id, profile.id, "anima_aesthetic_v1_1", [], refresh=True)
    assert len(calls) == 1
    assert "anima-aesthetic-v1.1.safetensors" in str(error.value)


def test_valid_fresh_graph_does_not_inspect(tmp_path, monkeypatch):
    resolver, profile, remote, info = capability_catalog(tmp_path, "23_Turbo_v1.1")
    calls = install_inspector(monkeypatch, resolver, remote, info)
    graph, resolution = resolver.resolve(remote.id, profile.id, "anima_turbo_v1_1", [], refresh=True)
    assert graph.id == "23_Turbo_v1.1" and resolution["availability"] == "ready"
    assert calls == []


def test_static_broken_graph_rejected_without_network_even_when_cache_expired(tmp_path, monkeypatch):
    resolver, profile, remote, info = capability_catalog(tmp_path, "23_Turbo_v1.1")
    profile.api_workflow["7"]["inputs"]["model"] = ["nonexistent", 0]
    save_capabilities(resolver.manager, remote, info, checked_at=0)
    calls = install_inspector(monkeypatch, resolver, remote, info)
    with pytest.raises(ResourceUnavailable) as error:
        resolver.resolve(remote.id, profile.id, "anima_turbo_v1_1", [], frozen=profile.model_dump(mode="json"), refresh=True)
    assert calls == []
    assert error.value.details["graph_errors"]


def test_stale_mapping_does_not_trigger_remote_refresh(tmp_path, monkeypatch):
    resolver, profile, remote, info = capability_catalog(tmp_path)
    resolver.manager._write("workflow_mapping:" + remote.id + ":" + profile.id, {
        "revision": "old", "fingerprint": fingerprint(remote), "mapping": {},
    })
    save_capabilities(resolver.manager, remote, info, checked_at=0)
    calls = install_inspector(monkeypatch, resolver, remote, info)
    with pytest.raises(ResourceUnavailable, match="映射已过期"):
        resolver.resolve(remote.id, profile.id, "anima_aesthetic_v1_1", [], refresh=True)
    assert calls == []


def test_refresh_propagates_preparation_timeout(tmp_path, monkeypatch):
    resolver, profile, remote, _ = capability_catalog(tmp_path)

    def timeout(*_args):
        raise DirectPreparationTimeout()

    monkeypatch.setattr(resolver.manager, "inspect", timeout)
    with pytest.raises(DirectPreparationTimeout):
        resolver.resolve(remote.id, profile.id, "anima_aesthetic_v1_1", [], refresh=True)


def test_remote_changed_during_refresh_cannot_accept_old_mapping(tmp_path, monkeypatch):
    resolver, profile, remote, info = capability_catalog(tmp_path)
    live = copy.deepcopy(info)
    live["UNETLoader"]["input"]["required"]["unet_name"][0].append("anima-aesthetic-v1.1.safetensors")

    def inspect(*_args):
        changed = remote.model_copy(update={"comfy_port": 8190})
        repository = SQLiteRepository(resolver.manager.database)
        repository.save_remote_profile(changed)
        repository.close()
        save_capabilities(resolver.manager, changed, live)

    monkeypatch.setattr(resolver.manager, "inspect", inspect)
    with pytest.raises(MappingConflict):
        resolver.resolve(remote.id, profile.id, "anima_aesthetic_v1_1", [], refresh=True)


def test_new_lora_uses_same_single_refresh_path(tmp_path, monkeypatch):
    resolver, _, remote, _ = capability_catalog(tmp_path)
    profile, info = profile_and_info()
    repository = SQLiteRepository(resolver.manager.database)
    repository.save_workflow_profile(profile)
    repository.close()
    resource = RequirementLora(logical_id="new", file_name="new.safetensors", weight=0.6)
    save_capabilities(resolver.manager, remote, info)
    live = copy.deepcopy(info)
    live["LoraLoader"]["input"]["required"]["lora_name"][0].append("new.safetensors")
    calls = install_inspector(monkeypatch, resolver, remote, live)
    graph, resolution = resolver.resolve(remote.id, profile.id, "anima_base_v1", [resource], refresh=True)
    assert resolution["bindings"][0]["remote_file_name"] == "new.safetensors"
    assert graph.api_workflow["9"]["inputs"]["strength_model"] == 0.6
    assert len(calls) == 1


@pytest.mark.parametrize("refresh,expired,inspection_count", [(False, False, 0), (True, False, 1), (True, True, 1)])
def test_missing_lora_loader_reports_node_dependency_before_resource_file(tmp_path, monkeypatch, refresh, expired, inspection_count):
    resolver, _, remote, _ = capability_catalog(tmp_path)
    profile, info = profile_and_info()
    repository = SQLiteRepository(resolver.manager.database)
    repository.save_workflow_profile(profile)
    repository.close()
    del info["LoraLoader"]
    save_capabilities(resolver.manager, remote, info, checked_at=0 if expired else None)
    calls = install_inspector(monkeypatch, resolver, remote, info)
    resource = RequirementLora(logical_id="existing", file_name="a.safetensors")
    with pytest.raises(ResourceUnavailable) as error:
        resolver.resolve(remote.id, profile.id, "anima_base_v1", [resource], refresh=refresh)
    assert error.value.availability == "incompatible_workflow"
    assert error.value.details["missing_nodes"] == ["LoraLoader"]
    assert "LoraLoader" in str(error.value)
    assert len(calls) == inspection_count


def test_present_lora_loader_still_reports_missing_file_after_one_refresh(tmp_path, monkeypatch):
    resolver, _, remote, _ = capability_catalog(tmp_path)
    profile, info = profile_and_info()
    repository = SQLiteRepository(resolver.manager.database)
    repository.save_workflow_profile(profile)
    repository.close()
    save_capabilities(resolver.manager, remote, info)
    calls = install_inspector(monkeypatch, resolver, remote, info)
    resource = RequirementLora(logical_id="missing", file_name="absent.safetensors")
    with pytest.raises(ResourceUnavailable) as error:
        resolver.resolve(remote.id, profile.id, "anima_base_v1", [resource], refresh=True)
    assert error.value.availability == "missing_lora"
    assert error.value.code == "lora_not_installed"
    assert len(calls) == 1
