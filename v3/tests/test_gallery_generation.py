from copy import deepcopy

import pytest
from anima_prompt_studio.domain.execution_models import WorkflowProfile
from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio_v3.core.requirements import WorkbenchError
from anima_prompt_studio_v3.core.workflow_compiler import V3WorkflowCompiler
from anima_prompt_studio_v3.runtime.gallery_generation import GalleryGenerationService
from anima_prompt_studio_v3.runtime.generation import CandidateToPromptJobAdapter, GenerationSettings
from anima_prompt_studio_v3.runtime.generation_queue import GenerationTarget
from anima_prompt_studio_v3.storage.generation_submissions import IdempotencyConflict
from test_generation_submissions import harness, payload, submit, reference_source
from test_aesthetic_versions import workflow


@pytest.mark.parametrize("version", [0, 1])
def test_gallery_freezes_version_prompts_parameters_and_executes_in_shared_queue(harness, version):
    _, start, _, executed, finished, base_plan = harness
    model = f"anima_aesthetic_v1_{version}"
    graph = workflow(version)
    def plan(prepared, remote, workflow_id, resources, frozen):
        prepared, target, resolution = base_plan(prepared, remote, workflow_id, resources, frozen)
        return prepared, GenerationTarget(target.remote_profile,
            WorkflowProfile.model_validate(frozen) if frozen else graph.model_copy(deep=True),
            target.credentials, target.output_root), resolution
    queue, service = start(plan_resolver=plan)
    original = CandidateToPromptJobAdapter().prepare_direct(
        positive_prompt="an adult woman holding flowers", negative_prompt="blurry, text",
        model_profile_id=model, settings=GenerationSettings(seed=8798399215689017476,
            steps=37, cfg=4.25, width=768, height=1024))
    request = payload().model_copy(update={"model_profile": model, "workflow_profile_id": graph.id})
    accepted = submit(service, request, prepare=lambda: original)
    source = {"batch_id": accepted["id"], "path": "original/image.png"}
    before = deepcopy(service.store.for_runs([accepted["id"]])[0]["snapshot"])
    # Even an edited current template must not replace the frozen source graph.
    graph.api_workflow["1"]["inputs"]["unet_name"] = "wrong-model.safetensors"
    gallery = GalleryGenerationService(service)
    response = gallery.submit(source, 2, "variation")
    assert gallery.submit(source, 2, "variation")["id"] == response["id"]
    with pytest.raises(IdempotencyConflict):
        gallery.submit(source, 3, "variation")
    saved = service.store.for_runs([response["id"]])[0]["snapshot"]
    assert saved["workflow"] == before["workflow"]
    assert service.store.for_runs([accepted["id"]])[0]["snapshot"] == before
    job = PromptJob.model_validate(saved["job"])
    assert job.id != original.job.id
    assert job.positive_prompt == original.job.positive_prompt
    assert job.negative_prompt == original.job.negative_prompt
    assert job.generation_params.batch_size == 2
    assert 0 <= job.generation_params.seed < 2**63
    target = plan(original, "remote-1", graph.id, [], before["workflow"])[1]
    rendered = V3WorkflowCompiler().render(job, target.workflow_profile, target.remote_profile,
        saved["checkpoint_logical_name"], "new-run")
    assert rendered.checkpoint_name == f"anima-aesthetic-v1.{version}.safetensors"
    assert rendered.workflow["7"]["inputs"]["steps"] == 37
    assert rendered.workflow["7"]["inputs"]["cfg"] == 4.25
    assert rendered.workflow["5"]["inputs"]["text"] == "blurry, text"
    queue.cancel_queued(accepted["id"])
    service.dispatch_pending()
    assert finished.wait(2)
    assert executed[0][1] == response["id"]
    assert executed[0][0].generation_params.seed == job.generation_params.seed
    assert gallery.list_jobs()[0]["sourceName"] == "image.png"


def test_gallery_retains_full_lora_provenance_and_blocks_remapping(harness):
    _, start, _, _, _, base_plan = harness
    received, binding = [], {"remote_file_name": "original.safetensors"}
    def plan(prepared, remote, workflow_id, resources, frozen):
        received.append(deepcopy(resources))
        prepared, target, resolution = base_plan(prepared, remote, workflow_id, resources, frozen)
        resolution["bindings"] = [deepcopy(binding)]
        return prepared, target, resolution
    queue, service = start(plan_resolver=plan)
    reference = reference_source()
    reference["requirements"]["loras"] = [{"logical_id": "style", "file_name": "style.safetensors",
        "weight": 0.65, "trigger_words": ["ink"], "required": True,
        "source": {"kind": "civitai", "model_version_id": "123456"}}]
    service.reference_get = lambda *_: reference
    source = submit(service, payload(submission_kind="reference", reference_preset_id="ex_abc", source_version="2"))
    gallery = GalleryGenerationService(service)
    asset = {"batch_id": source["id"], "path": "image.png"}
    result = gallery.submit(asset, 1, "first")
    assert received[-1] == received[0]
    assert service.store.for_runs([result["id"]])[0]["snapshot"]["resources"] == service.store.for_runs([source["id"]])[0]["snapshot"]["resources"]
    binding["remote_file_name"] = "replacement.safetensors"
    with pytest.raises(WorkbenchError, match="映射已变化"):
        gallery.submit(asset, 1, "second")
    assert len(queue.list()) == 2


def test_gallery_missing_snapshot_rejects_without_guessing(harness):
    _, start, _, _, _, _ = harness
    queue, service = start()
    with pytest.raises(WorkbenchError, match="缺少完整生成快照"):
        GalleryGenerationService(service).submit({"batch_id": "legacy", "path": "old.png"}, 1, "key")
    assert queue.list() == []
