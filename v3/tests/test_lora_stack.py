import time

import pytest
from pydantic import ValidationError

from anima_prompt_studio_v3.api.models import SubmissionLora
from anima_prompt_studio_v3.core.lora_resolution import ResourceUnavailable
from anima_prompt_studio_v3.core.requirements import RequirementLora
from anima_prompt_studio_v3.core.workflow_compiler import V3WorkflowCompiler
from anima_prompt_studio_v3.runtime.generation import CandidateToPromptJobAdapter
from anima_prompt_studio_v3.runtime.generation_queue import build_generation_queue
from anima_prompt_studio_v3.runtime.lora_catalog import LoraCatalog
from anima_prompt_studio_v3.runtime.workflow_catalog import WorkflowCatalog, fingerprint
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
from test_v2_generation_adapter import remote_profile


def library_item(character, **kwargs):
    sha = character * 64
    return RequirementLora(logical_id="library:" + sha, file_name=f"anima_library/{sha}.safetensors",
                           sha256=sha, **kwargs)


def test_legacy_resource_serialization_and_managed_identity():
    item = SubmissionLora(logical_id="old", file_name="style.safetensors")
    assert item.model_dump(mode="json") == dict(logical_id="old", file_name="style.safetensors",
                                               weight=.8, trigger_words=[])
    assert set(RequirementLora.model_validate(item.model_dump()).model_dump()) == {
        "logical_id", "file_name", "weight", "trigger_words", "required", "source"}
    bad = {**library_item("a").model_dump(), "file_name": "elsewhere.safetensors"}
    with pytest.raises(ValidationError):
        RequirementLora.model_validate(bad)


def test_disabled_trigger_is_absent_from_rewrite_request_but_preserved_in_draft():
    from anima_prompt_studio_v3.api.conversation import active_prompt_requirements, validate_rewrite_language_inputs
    from anima_prompt_studio_v3.core.requirements import Requirements

    draft = Requirements(layers=Requirements.empty().layers, loras=[
        library_item("a", trigger_words=["ink"]), library_item("b", enabled=False, trigger_words=["沉睡"])])
    validate_rewrite_language_inputs(draft)
    assert [item["trigger_words"] for item in active_prompt_requirements(draft)["loras"]] == [["ink"]]
    assert draft.loras[1].trigger_words == ["沉睡"]


@pytest.mark.parametrize(("workflow", "model", "loader", "sink"), [
    ("23_Turbo_v1.1", "anima_turbo_v1_1", "LoraLoader", "2"),
    ("v3_moss_image_sft_int8", "moss_image_sft_int8", "LoraLoaderModelOnly", "7"),
])
def test_native_stack_materializes_in_list_order_and_frozen_graph_is_idempotent(tmp_path, monkeypatch, workflow, model, loader, sink):
    manager = WorkflowCatalog(tmp_path / "runtime.db")
    remote = remote_profile()
    repository = SQLiteRepository(manager.database)
    repository.save_remote_profile(remote)
    repository.close()
    catalog = LoraCatalog(manager)
    base = catalog.profile(workflow)
    dual = loader == "LoraLoader"
    a = library_item("a", weight=.8, clip_weight=.25 if dual else None)
    b = library_item("b", weight=-.35)
    disabled = library_item("d", enabled=False)
    validated = []
    monkeypatch.setattr("anima_prompt_studio_v3.runtime.lora_library.validate_library_resources",
                        lambda db, model_id, resources: validated.append([item.sha256 for item in resources]))
    info = {node["class_type"]: {"input": {"required": {}}} for node in base.api_workflow.values()}
    info[loader] = {"input": {"required": {"lora_name": [[a.file_name, b.file_name]]}}}
    manager._write("workflow_capabilities:" + remote.id, {"checked_at": time.time(),
                   "fingerprint": fingerprint(remote), "object_info": info})
    resources = [b, disabled, a]
    graph, resolution = catalog.resolve(remote.id, workflow, model, resources)
    slots = [slot.node_id for slot in graph.lora_slots]
    assert len(slots) == 2
    first, last = [graph.api_workflow[key]["inputs"] for key in slots]
    assert [first["lora_name"], last["lora_name"]] == [b.file_name, a.file_name]
    assert [first["strength_model"], last["strength_model"]] == [-.35, .8]
    assert first["model"] == ["1", 0] and last["model"] == [slots[0], 0]
    assert graph.api_workflow[sink]["inputs"]["model"] == [slots[1], 0]
    assert [r["sha256"] for r in resolution["bindings"]] == [b.sha256, a.sha256]
    if dual:
        assert last["clip"] == [slots[0], 1] and last["strength_clip"] == .25
        assert graph.api_workflow["4"]["inputs"]["clip"] == [slots[1], 1]
        assert graph.api_workflow["2"]["inputs"]["shift"] == 3
    else:
        assert "strength_clip" not in last and "clip" not in first
        assert graph.api_workflow["4"]["inputs"]["clip"] == ["3", 0]
    frozen = graph.model_dump(mode="json")
    replay, again = catalog.resolve(remote.id, workflow, model, resources, frozen=frozen)
    assert replay.model_dump(mode="json") == frozen
    assert resolution["bindings"] == again["bindings"]
    assert validated == [[b.sha256, a.sha256]]
    # A new submission may retain a workflow snapshot while changing its files.
    replacement = library_item("c")
    info[loader]["input"]["required"]["lora_name"][0].append(replacement.file_name)
    manager._write("workflow_capabilities:" + remote.id, {"checked_at": time.time(),
                   "fingerprint": fingerprint(remote), "object_info": info})
    def swapped_family(db, model_id, resources):
        assert [r.sha256 for r in resources] == [replacement.sha256]
        raise ResourceUnavailable("incompatible_model", "当前库记录属于另一个底模。")
    with monkeypatch.context() as patch:
        patch.setattr("anima_prompt_studio_v3.runtime.lora_library.validate_library_resources", swapped_family)
        with pytest.raises(ResourceUnavailable) as mismatch:
            catalog.resolve(remote.id, workflow, model, [b, replacement], frozen=frozen)
        assert mismatch.value.availability == "incompatible_model"
    queue = build_generation_queue(manager.database)
    try:
        prepared = CandidateToPromptJobAdapter().prepare_direct(positive_prompt="cafe", model_profile_id=model)
        prepared, target, _ = queue.plan_cached(prepared, remote.id, workflow, resources, frozen)
        rendered = V3WorkflowCompiler().render(prepared.job, target.workflow_profile, remote, model, "stack")
        assert [x.sha256 for x in prepared.job.lora_selection] == [b.sha256, a.sha256]
        assert rendered.workflow[slots[1]] == frozen["api_workflow"][slots[1]]
    finally:
        queue.shutdown()
    with pytest.raises(ResourceUnavailable) as absent:
        catalog.resolve(remote.id, workflow, model, [library_item("e")])
    assert absent.value.availability == "missing_lora"
    del info[loader]
    manager._write("workflow_capabilities:" + remote.id, {"checked_at": time.time(),
                   "fingerprint": fingerprint(remote), "object_info": info})
    idle, unused = catalog.resolve(remote.id, workflow, model, [disabled])
    assert idle.api_workflow == base.api_workflow and not unused["bindings"]
