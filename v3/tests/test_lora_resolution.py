import time

import pytest
from anima_prompt_studio.domain.execution_models import LoRASlotBinding
from anima_prompt_studio.domain.models import LoRASelection
from anima_prompt_studio_v3.core.lora_resolution import (
    LoraBinding, LoraBindingsRequest, MappingConflict, ResourceUnavailable, resolve_loras, resource_digest,
)
from anima_prompt_studio_v3.core.requirements import RequirementLora
from anima_prompt_studio_v3.core.workflow_compiler import V3WorkflowCompiler, WorkflowRenderError
from anima_prompt_studio_v3.runtime.generation import CandidateToPromptJobAdapter
from anima_prompt_studio_v3.runtime.lora_catalog import LoraCatalog
from anima_prompt_studio_v3.runtime.packaged_workflows import workflow_revision
from anima_prompt_studio_v3.runtime.workflow_catalog import WorkflowCatalog, fingerprint
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
from test_v2_generation_adapter import workflow_profile, remote_profile


def profile_and_info():
    profile = workflow_profile()
    for node in ("9", "10"):
        profile.api_workflow[node] = {"class_type": "LoraLoader", "inputs": {
            "lora_name": "a.safetensors", "strength_model": 1.0, "strength_clip": 1.0}}
        profile.lora_slots.append(LoRASlotBinding(node_id=node))
    info = {"LoraLoader": {"input": {"required": {"lora_name": [["a.safetensors", "sub/b.safetensors"]],
            "strength_model": ["FLOAT"], "strength_clip": ["FLOAT"]}}}}
    for node in profile.api_workflow.values():
        if node["class_type"] not in info:
            info[node["class_type"]] = {"input": {"required": {k: ["STRING"] if isinstance(v, str) else ["FLOAT"]
                                       for k, v in node["inputs"].items()}}}
    return profile, info


def binding(resource, slot="10.lora_name", name="sub/b.safetensors"):
    return LoraBinding(logical_id=resource.logical_id, resource_digest=resource_digest(resource),
                       slot_key=slot, remote_file_name=name)


def test_explicit_slots_reserved_before_automatic_assignment():
    profile, info = profile_and_info()
    a = RequirementLora(logical_id="a", file_name="a.safetensors")
    b = RequirementLora(logical_id="b", file_name="local-b.safetensors")
    resolved = resolve_loras([a, b], profile, info, [binding(b, "9.lora_name")])
    assert [(r["logical_id"], r["slot_key"]) for r in resolved] == [("b", "9.lora_name"), ("a", "10.lora_name")]
    assert resolved[0]["remote_file_name"] == "sub/b.safetensors"


def test_missing_renamed_and_stale_resources_do_not_guess():
    profile, info = profile_and_info()
    resource = RequirementLora(logical_id="b", file_name="b.safetensors")
    with pytest.raises(ResourceUnavailable) as error:
        resolve_loras([resource], profile, info)
    assert error.value.availability == "missing_lora"
    with pytest.raises(ResourceUnavailable):
        resolve_loras([resource], profile, info, [binding(resource)], mapping_current=False)
    changed = resource.model_copy(update={"trigger_words": ["new"]})
    with pytest.raises(ResourceUnavailable):
        resolve_loras([changed], profile, info, [binding(resource)])
    changed.weight = 0.5
    assert resource_digest(changed) != resource_digest(resource)
    assert resource_digest(resource.model_copy(update={"weight": 0.5})) == resource_digest(resource)


def test_renderer_obeys_nonleading_slot_and_ignores_alias_override():
    profile, info = profile_and_info()
    resource = RequirementLora(logical_id="b", file_name="local.safetensors", weight=0.6)
    resolved = resolve_loras([resource], profile, info, [binding(resource)])
    job = CandidateToPromptJobAdapter().prepare_direct(positive_prompt="cat", model_profile_id="anima_base_v1").job
    job.lora_selection = [LoRASelection(logical_id="b", file_name="sub/b.safetensors", weight=0.6)]
    job.integration_metadata["resolved_lora_bindings"] = resolved
    remote = remote_profile()
    remote.model_aliases["sub/b.safetensors"] = "WRONG.safetensors"
    rendered = V3WorkflowCompiler().render(job, profile, remote, "anima_base_v1", "run-test").workflow
    assert rendered["9"]["inputs"]["strength_model"] == 0
    assert rendered["10"]["inputs"]["lora_name"] == "sub/b.safetensors"
    assert rendered["10"]["inputs"]["strength_clip"] == 0.6
    job.lora_selection[0].weight = 0.7
    with pytest.raises(WorkflowRenderError):
        V3WorkflowCompiler().render(job, profile, remote, "anima_base_v1", "run-test")


def test_binding_cas_and_frozen_workflow_survives_same_id_update(tmp_path):
    profile, info = profile_and_info()
    remote = remote_profile()
    database = tmp_path / "runtime.db"
    repo = SQLiteRepository(database)
    repo.save_remote_profile(remote)
    repo.save_workflow_profile(profile)
    repo.close()
    manager = WorkflowCatalog(database)
    manager._write("workflow_capabilities:" + remote.id, {"checked_at": time.time(),
                   "fingerprint": fingerprint(remote), "object_info": info})
    catalog = LoraCatalog(manager)
    resource = RequirementLora(logical_id="b", file_name="local.safetensors")
    payload = LoraBindingsRequest(mapping_revision=0, workflow_revision=workflow_revision(profile),
                                 remote_fingerprint=fingerprint(remote), bindings=[binding(resource)])
    assert catalog.save(remote.id, profile.id, payload)["mapping_revision"] == 1
    saved_mapping = catalog.get(remote.id, profile.id)
    assert saved_mapping["capabilities_ready"]
    assert saved_mapping["slots"]["9.lora_name"] == ["a.safetensors", "sub/b.safetensors"]
    with pytest.raises(MappingConflict):
        catalog.save(remote.id, profile.id, payload)
    frozen, resolution = catalog.resolve(remote.id, profile.id, "anima_base_v1", [resource])
    assert frozen.api_workflow["9"]["inputs"]["strength_clip"] == 0
    profile.api_workflow["99"] = {"class_type": "MissingNewNode", "inputs": {}}
    repo = SQLiteRepository(database)
    repo.save_workflow_profile(profile)
    repo.close()
    replay, replay_resolution = catalog.resolve(remote.id, profile.id, "anima_base_v1", [resource], frozen=frozen.model_dump(mode="json"))
    assert replay == frozen and replay_resolution == resolution
    with pytest.raises(ResourceUnavailable):
        catalog.resolve(remote.id, profile.id, "anima_base_v1", [resource])
    info["LoraLoader"]["input"]["required"]["lora_name"] = [["a.safetensors"]]
    manager._write("workflow_capabilities:" + remote.id, {"checked_at": time.time(),
                   "fingerprint": fingerprint(remote), "object_info": info})
    with pytest.raises(ResourceUnavailable) as error:
        catalog.resolve(remote.id, profile.id, "anima_base_v1", [resource], frozen=frozen.model_dump(mode="json"))
    assert error.value.availability == "missing_lora"


def test_production_queue_plan_uses_resolved_binding(tmp_path):
    from anima_prompt_studio_v3.runtime.generation_queue import build_generation_queue
    profile, info = profile_and_info()
    remote = remote_profile()
    database = tmp_path / "runtime.db"
    repo = SQLiteRepository(database)
    repo.save_remote_profile(remote)
    repo.save_workflow_profile(profile)
    repo.close()
    manager = WorkflowCatalog(database)
    manager._write("workflow_capabilities:" + remote.id, {"checked_at": time.time(),
                   "fingerprint": fingerprint(remote), "object_info": info})
    queue = build_generation_queue(database)
    try:
        prepared = CandidateToPromptJobAdapter().prepare_direct(positive_prompt="cat", model_profile_id="anima_base_v1")
        job, target, resolved = queue.plan(prepared, remote.id, profile.id,
            [RequirementLora(logical_id="b", file_name="sub/b.safetensors", weight=0.4)])
        assert job.job.lora_selection[0].logical_id == "b"
        rendered = V3WorkflowCompiler().render(job.job, target.workflow_profile, remote, "anima_base_v1", "test").workflow
        assert rendered["9"]["inputs"]["lora_name"] == "sub/b.safetensors"
        assert rendered["9"]["inputs"]["strength_model"] == 0.4
        assert rendered["10"]["inputs"]["strength_model"] == 0
    finally:
        queue.shutdown()
