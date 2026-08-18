from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from anima_prompt_studio.domain.execution_models import (
    GenerationRun,
    GenerationRunState,
    RemoteArtifact,
    RemoteAuthType,
    RemoteCredentials,
    RemoteProfile,
    WorkflowBinding,
    WorkflowProfile,
)
from anima_prompt_studio.services.gallery_upscale import (
    GALLERY_REGEN_OPERATION,
    GALLERY_UPSCALE_OPERATION,
    GalleryUpscaleError,
    GalleryUpscaleExecutionResult,
    GalleryUpscaleManager,
    GalleryUpscaleRenderer,
    build_gallery_regen_job,
    choose_txt2img_workflow,
    snapshot_regen_parameters,
)
from anima_prompt_studio.services.remote.execution_coordinator import ExecutionResult
from anima_prompt_studio.services.remote.comfy_client import ComfyUIClient


def _tile_profile() -> WorkflowProfile:
    nodes = {
        "4": {"class_type": "Reroute", "inputs": {}},
        "5": {"class_type": "Reroute", "inputs": {}},
        "6": {"class_type": "TTP_Image_Tile_Batch", "inputs": {"image": ["5", 0], "tile_width": ["10", 0], "tile_height": ["10", 1]}},
        "7": {"class_type": "easy imageListToImageBatch", "inputs": {"images": ["13", 0]}},
        "8": {"class_type": "TTP_Image_Assy", "inputs": {"tiles": ["7", 0], "positions": ["6", 1], "original_size": ["6", 2], "grid_size": ["6", 3], "padding": 128}},
        "9": {"class_type": "VAEEncode", "inputs": {"pixels": ["11", 0], "vae": ["17", 0]}},
        "10": {"class_type": "TTP_Tile_image_size", "inputs": {"image": ["5", 0], "width_factor": 2, "height_factor": 2, "overlap_rate": 0.35}},
        "11": {"class_type": "easy imageBatchToImageList", "inputs": {"image": ["6", 0]}},
        "12": {"class_type": "WD14Tagger|pysssss", "inputs": {"image": ["11", 0], "model": "tagger"}},
        "13": {"class_type": "VAEDecodeTiled", "inputs": {"samples": ["24", 0], "vae": ["17", 0], "tile_size": 1024}},
        "14": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "ComfyUI"}},
        "15": {"class_type": "UNETLoader", "inputs": {"unet_name": "anima.safetensors"}},
        "16": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": "RealESRGAN.pth"}},
        "17": {"class_type": "VAELoader", "inputs": {"vae_name": "vae.safetensors"}},
        "18": {"class_type": "LoadImage", "inputs": {"image": "old.png", "upload": "image"}},
        "19": {"class_type": "CLIPLoader", "inputs": {"clip_name": "clip.safetensors"}},
        "20": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 1], "text": ["26", 0]}},
        "21": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 1], "text": "bad"}},
        "22": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["16", 0], "image": ["4", 0]}},
        "23": {"class_type": "Seed (rgthree)", "inputs": {}},
        "24": {"class_type": "ClownsharKSampler_Beta", "inputs": {"model": ["3", 0], "positive": ["20", 0], "negative": ["21", 0], "latent_image": ["9", 0], "seed": ["23", 0], "steps": 20, "cfg": 2.0, "sampler_name": "linear/euler", "scheduler": "beta57", "denoise": 0.3}},
        "25": {"class_type": "ShowText|pysssss", "inputs": {"text": ["12", 0]}},
        "26": {"class_type": "JWStringConcat", "inputs": {"a": "fixed artist", "b": ["25", 0]}},
        "27": {"class_type": "ImageScaleToTotalPixels", "inputs": {"image": ["22", 0], "upscale_method": "lanczos", "megapixels": 6.0, "resolution_steps": 1}},
        "28": {"class_type": "Image Comparer (rgthree)", "inputs": {"image_a": ["4", 0], "image_b": ["8", 0]}},
    }
    return WorkflowProfile(
        id="20_tile",
        display_name="20_分块放大_Tile_Upscale",
        api_workflow=nodes,
        bindings={
            "positive_prompt": WorkflowBinding(node_id="20", input="text"),
            "negative_prompt": WorkflowBinding(node_id="21", input="text"),
        },
    )


def test_gallery_upscale_renderer_repairs_discovered_template_and_sets_exact_target():
    profile = _tile_profile()

    result = GalleryUpscaleRenderer().render(
        profile,
        uploaded_image="anima_gallery/run/source.png",
        source_width=768,
        source_height=512,
        run_id="abcdefgh-1234",
        source_relative_path="项目/source.png",
        seed=42,
    )

    workflow = result.workflow
    assert not {"4", "5", "23", "25", "26", "28"}.intersection(workflow)
    assert workflow["18"]["inputs"]["image"] == "anima_gallery/run/source.png"
    assert workflow["22"]["inputs"]["image"] == ["18", 0]
    assert workflow["27"]["inputs"]["megapixels"] == 0.884736
    assert workflow["6"]["inputs"]["image"] == ["27", 0]
    assert workflow["20"]["inputs"]["clip"] == ["19", 0]
    assert workflow["20"]["inputs"]["text"] == ["12", 0]
    assert workflow["24"]["inputs"]["model"] == ["15", 0]
    assert workflow["24"]["inputs"]["seed"] == 42
    assert workflow["24"]["inputs"]["sampler_mode"] == "standard"
    assert workflow["24"]["inputs"]["bongmath"] is True
    assert workflow["900001"]["inputs"]["image"] == ["8", 0]
    assert workflow["900001"]["inputs"]["width"] == 1152
    assert workflow["900001"]["inputs"]["height"] == 768
    assert workflow["14"]["inputs"]["images"] == ["900001", 0]
    assert result.metadata["operation"] == GALLERY_UPSCALE_OPERATION
    assert result.metadata["output_width"] == 1152
    assert result.metadata["output_height"] == 768
    assert profile.api_workflow["27"]["inputs"]["megapixels"] == 6.0


class _UploadResponse:
    headers = {"Content-Type": "application/json"}

    def raise_for_status(self):
        return None

    def json(self):
        return {"name": "source_test.png", "subfolder": "anima_gallery/run", "type": "input"}


class _UploadSession:
    def __init__(self):
        self.upload = None

    def post(self, url, *, files, data, timeout):
        filename, stream, mime = files["image"]
        self.upload = {
            "url": url,
            "filename": filename,
            "content": stream.read(),
            "mime": mime,
            "data": data,
            "timeout": timeout,
        }
        return _UploadResponse()


def test_comfy_client_uploads_gallery_image_as_input(tmp_path):
    source = tmp_path / "source.png"
    source.write_bytes(b"png-data")
    session = _UploadSession()
    client = ComfyUIClient("http://comfy", session=session)

    uploaded = client.upload_image(
        source,
        subfolder="anima_gallery/run",
        remote_name="source_test.png",
    )

    assert uploaded == "anima_gallery/run/source_test.png"
    assert session.upload["url"] == "http://comfy/upload/image"
    assert session.upload["content"] == b"png-data"
    assert session.upload["data"]["type"] == "input"


class _QueueCoordinator:
    def __init__(self, controller, *, organizer, on_update):
        self.controller = controller
        self.organizer = organizer
        self.on_update = on_update

    def execute(self, *, job, source_path, remote_profile, workflow_profile, **kwargs):
        run = GenerationRun(
            prompt_job_id=job.id,
            remote_profile_id=remote_profile.id,
            workflow_profile_id=workflow_profile.id,
        )
        run.update_state(GenerationRunState.RUNNING, "正在处理", 0.5)
        self.on_update(run)
        with self.controller["lock"]:
            self.controller["started"].append(source_path.name)
            sequence = len(self.controller["started"])
        if sequence == 1:
            self.controller["first_started"].set()
            assert self.controller["release_first"].wait(timeout=5)
        artifact = self.organizer.save_artifact(
            job,
            run,
            RemoteArtifact(filename="result.png"),
            b"result-" + source_path.name.encode(),
            1,
            "image/png",
        )
        run.update_state(GenerationRunState.COMPLETED, "完成", 1.0)
        self.on_update(run)
        with self.controller["lock"]:
            self.controller["finished"].append(source_path.name)
        return GalleryUpscaleExecutionResult(run=run, artifacts=[artifact])


def _queue_manager(tmp_path):
    controller = {
        "lock": threading.Lock(),
        "started": [],
        "finished": [],
        "first_started": threading.Event(),
        "release_first": threading.Event(),
    }

    def factory(*, organizer, on_update):
        return _QueueCoordinator(controller, organizer=organizer, on_update=on_update)

    output_root = tmp_path / "images"
    output_root.mkdir()
    manager = GalleryUpscaleManager(
        tmp_path / "queue.db",
        output_root,
        coordinator_factory=factory,
    )
    manager.configure(
        RemoteProfile(
            display_name="test",
            ssh_host="localhost",
            ssh_user="tester",
            auth_type=RemoteAuthType.AGENT,
            known_host_fingerprint="SHA256:test",
        ),
        _tile_profile(),
        RemoteCredentials(),
    )
    return manager, controller, output_root


def _wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("timed out waiting for queue state")


def test_gallery_upscale_manager_runs_multiple_jobs_serially_and_persists_them(tmp_path):
    manager, controller, output_root = _queue_manager(tmp_path)
    first = output_root / "first.png"
    second = output_root / "second.png"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    asset = {"project": "queue", "model": "test", "prompt": "", "width": 64, "height": 48}

    first_job = manager.submit(first, "first.png", {**asset, "path": "first.png"})
    assert controller["first_started"].wait(timeout=5)
    second_job = manager.submit(second, "second.png", {**asset, "path": "second.png"})

    assert manager.get(second_job["id"])["state"] == "queued"
    assert manager.get(second_job["id"])["queuePosition"] == 1
    controller["release_first"].set()
    _wait_for(lambda: manager.get(second_job["id"])["state"] == "completed")

    assert controller["started"] == ["first.png", "second.png"]
    assert controller["finished"] == ["first.png", "second.png"]
    assert manager.get(first_job["id"])["state"] == "completed"
    assert len(manager.list_jobs()) == 2

    reloaded = GalleryUpscaleManager(tmp_path / "queue.db", output_root)
    assert {job["id"] for job in reloaded.list_jobs()} == {first_job["id"], second_job["id"]}


def test_gallery_upscale_manager_can_cancel_and_retry_a_waiting_job(tmp_path):
    manager, controller, output_root = _queue_manager(tmp_path)
    first = output_root / "first.png"
    second = output_root / "second.png"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    asset = {"project": "queue", "model": "test", "prompt": "", "width": 64, "height": 48}

    manager.submit(first, "first.png", {**asset, "path": "first.png"})
    assert controller["first_started"].wait(timeout=5)
    waiting = manager.submit(second, "second.png", {**asset, "path": "second.png"})
    canceled = manager.cancel(waiting["id"])
    assert canceled["state"] == "canceled"
    retried = manager.retry(waiting["id"])
    assert retried["state"] == "queued"
    assert retried["queuePosition"] == 1

    controller["release_first"].set()
    _wait_for(lambda: manager.get(waiting["id"])["state"] == "completed")
    assert controller["started"] == ["first.png", "second.png"]


def test_gallery_upscale_manager_refuses_output_root_change_while_busy(tmp_path):
    manager, controller, output_root = _queue_manager(tmp_path)
    source = output_root / "busy.png"
    source.write_bytes(b"busy")
    manager.submit(source, "busy.png", {"project": "queue", "model": "test", "prompt": "", "width": 64, "height": 48})
    assert controller["first_started"].wait(timeout=5)

    assert "未完成" in manager.output_root_change_blocked_reason()
    with pytest.raises(GalleryUpscaleError, match="未完成"):
        manager.set_output_root(tmp_path / "other-gallery")
    assert manager.output_root.resolve() == output_root.resolve()

    controller["release_first"].set()
    _wait_for(lambda: manager.get(manager.list_jobs()[0]["id"])["state"] == "completed")
    manager.set_output_root(tmp_path / "other-gallery")
    assert manager.output_root.resolve() == (tmp_path / "other-gallery").resolve()
    assert manager.output_root_change_blocked_reason() == ""


class _FailingCoordinator:
    def __init__(self, *, organizer, on_update):
        self.organizer = organizer
        self.on_update = on_update

    def execute(self, **kwargs):
        raise RuntimeError("cloud failed")


def test_gallery_upscale_manager_clear_completed_includes_failed_jobs(tmp_path):
    output_root = tmp_path / "images"
    output_root.mkdir()
    manager = GalleryUpscaleManager(
        tmp_path / "queue.db",
        output_root,
        coordinator_factory=_FailingCoordinator,
    )
    manager.configure(
        RemoteProfile(
            display_name="test",
            ssh_host="localhost",
            ssh_user="tester",
            auth_type=RemoteAuthType.AGENT,
            known_host_fingerprint="SHA256:test",
        ),
        _tile_profile(),
        RemoteCredentials(),
    )
    source = output_root / "failed.png"
    source.write_bytes(b"failed")
    submitted = manager.submit(
        source,
        "failed.png",
        {"project": "queue", "model": "test", "prompt": "", "width": 64, "height": 48},
    )
    _wait_for(lambda: manager.get(submitted["id"])["state"] == "failed")

    assert manager.clear_completed() == 1
    assert manager.list_jobs() == []


def test_gallery_upscale_manager_marks_interrupted_jobs_failed_on_reload(tmp_path):
    manager, controller, output_root = _queue_manager(tmp_path)
    source = output_root / "live.png"
    source.write_bytes(b"live")
    submitted = manager.submit(source, "live.png", {"project": "queue", "model": "test", "prompt": "", "width": 64, "height": 48})
    assert controller["first_started"].wait(timeout=5)

    reloaded = GalleryUpscaleManager(tmp_path / "queue.db", output_root)
    reloaded_job = reloaded.get(submitted["id"])
    assert reloaded_job["state"] == "failed"
    assert "退出" in reloaded_job["message"]
    controller["release_first"].set()


def _txt2img_profile(profile_id="01___Base_Quality_T2I", model="anima_base_v1"):
    return WorkflowProfile(
        id=profile_id,
        display_name=profile_id,
        api_workflow={
            "3": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 20, "cfg": 4.5, "sampler_name": "euler", "scheduler": "normal"}},
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "anima.safetensors"}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 896, "height": 1152, "batch_size": 1}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "pos"}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "neg"}},
            "8": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ComfyUI"}},
        },
        bindings={
            "positive_prompt": WorkflowBinding(node_id="6", input="text"),
            "negative_prompt": WorkflowBinding(node_id="7", input="text"),
            "checkpoint": WorkflowBinding(node_id="4", input="ckpt_name"),
            "seed": WorkflowBinding(node_id="3", input="seed"),
            "steps": WorkflowBinding(node_id="3", input="steps"),
            "cfg": WorkflowBinding(node_id="3", input="cfg"),
            "sampler": WorkflowBinding(node_id="3", input="sampler_name"),
            "scheduler": WorkflowBinding(node_id="3", input="scheduler"),
            "width": WorkflowBinding(node_id="5", input="width"),
            "height": WorkflowBinding(node_id="5", input="height"),
            "batch_size": WorkflowBinding(node_id="5", input="batch_size"),
            "filename_prefix": WorkflowBinding(node_id="8", input="filename_prefix"),
        },
        workflow_kind="txt2img_basic",
        compatible_model_profiles=[model],
    )


def test_choose_txt2img_workflow_prefers_base_quality_for_anima_base():
    profiles = [
        _txt2img_profile("02___Turbo_Fast_T2I", "anima_turbo_v1"),
        _txt2img_profile("01___Base_Quality_T2I", "anima_base_v1"),
        _txt2img_profile("22___Aesthetic_v1.1", "anima_aesthetic_v1"),
    ]
    chosen = choose_txt2img_workflow(profiles, "anima_base_v1")
    assert chosen is not None
    assert chosen.id.startswith("01")


def test_build_gallery_regen_job_requires_prompt_and_keeps_size():
    with pytest.raises(GalleryUpscaleError, match="提示词"):
        build_gallery_regen_job({"width": 640, "height": 832}, workflow_id="01", count=2)

    job = build_gallery_regen_job(
        {
            "prompt": "1girl, solo, sitting",
            "project": "测试项目",
            "model": "anima_base_v1",
            "width": 640,
            "height": 832,
            "parameters": {
                "steps": 40,
                "cfg": 5.0,
                "sampler": "er_sde",
                "scheduler": "sgm_uniform",
                "generation_preset": "quality",
                "quality_profile": "ultimate_general",
                "negative_prompt": "lowres, blurry",
            },
        },
        workflow_id="01___Base_Quality_T2I",
        count=3,
    )
    assert job.positive_prompt == "1girl, solo, sitting"
    assert job.generation_params.width == 640
    assert job.generation_params.height == 832
    assert job.generation_params.batch_size == 3
    assert job.generation_params.steps == 40
    assert job.generation_params.cfg == 5.0
    assert job.generation_params.sampler == "er_sde"
    assert job.generation_params.scheduler == "sgm_uniform"
    assert job.generation_preset_id == "quality"
    assert job.quality_profile_id == "ultimate_general"
    assert job.negative_prompt == "lowres, blurry"
    assert job.generation_params.seed == -1


def test_snapshot_regen_parameters_reads_nested_generation_params():
    snapshot = snapshot_regen_parameters({
        "parameters": {
            "generation_params": {"steps": 35, "cfg": 4.5, "sampler": "euler", "scheduler": "normal"},
            "generation_preset_id": "balanced",
            "source": {"original_zh": "一个女孩"},
        }
    })
    assert snapshot["steps"] == 35
    assert snapshot["cfg"] == 4.5
    assert snapshot["sampler"] == "euler"
    assert snapshot["scheduler"] == "normal"
    assert snapshot["generation_preset_id"] == "balanced"
    assert snapshot["original_zh"] == "一个女孩"


class _RegenCoordinator:
    def __init__(self, controller, *, organizer, renderer=None, on_update=None, **kwargs):
        self.controller = controller
        self.organizer = organizer
        self.on_update = on_update

    def execute(self, job, remote_profile, workflow_profile, checkpoint_logical_name, credentials=None):
        run = GenerationRun(
            prompt_job_id=job.id,
            remote_profile_id=remote_profile.id,
            workflow_profile_id=workflow_profile.id,
        )
        run.request_json = {"prompt_job": job.model_dump(mode="json"), "resolved_seed": 99}
        if self.on_update:
            self.on_update(run)
        artifact = self.organizer.save_artifact(
            job,
            run,
            RemoteArtifact(filename="more.png"),
            b"regen-bytes",
            1,
            "image/png",
        )
        run.update_state(GenerationRunState.COMPLETED, "完成", 1.0)
        if self.on_update:
            self.on_update(run)
        self.controller["jobs"].append(job)
        return ExecutionResult(run=run, artifacts=[artifact])


def test_gallery_manager_queues_same_prompt_regen(tmp_path):
    output_root = tmp_path / "images"
    output_root.mkdir()
    source = output_root / "kept.png"
    source.write_bytes(b"source")
    controller = {"jobs": []}
    manager = GalleryUpscaleManager(
        tmp_path / "queue.db",
        output_root,
        regen_coordinator_factory=lambda **kwargs: _RegenCoordinator(controller, **kwargs),
    )
    manager.configure(
        RemoteProfile(
            display_name="test",
            ssh_host="localhost",
            ssh_user="tester",
            auth_type=RemoteAuthType.AGENT,
            known_host_fingerprint="SHA256:test",
        ),
        _tile_profile(),
        RemoteCredentials(),
        txt2img_workflows=[_txt2img_profile()],
    )
    payload = manager.configuration_payload()
    assert payload["regenAvailable"] is True
    submitted = manager.submit_regenerate(
        source,
        "kept.png",
        {
            "path": "kept.png",
            "project": "动作验证",
            "model": "anima_base_v1",
            "prompt": "1girl, hugging own legs",
            "width": 896,
            "height": 1152,
            "parameters": {
                "steps": 40,
                "cfg": 5.0,
                "sampler": "er_sde",
                "scheduler": "beta",
                "generation_preset_id": "quality",
                "negative_prompt": "lowres",
            },
        },
        count=2,
    )
    assert submitted["operation"] == GALLERY_REGEN_OPERATION
    assert submitted["batchCount"] == 2
    assert submitted["parameters"]["steps"] == 40
    _wait_for(lambda: manager.get(submitted["id"])["state"] == "completed")
    queued_job = controller["jobs"][0]
    assert queued_job.generation_params.batch_size == 2
    assert queued_job.positive_prompt == "1girl, hugging own legs"
    assert queued_job.generation_params.steps == 40
    assert queued_job.generation_params.cfg == 5.0
    assert queued_job.generation_params.sampler == "er_sde"
    assert queued_job.generation_params.scheduler == "beta"
    assert queued_job.generation_preset_id == "quality"
    assert queued_job.negative_prompt == "lowres"
    completed = manager.get(submitted["id"])
    assert completed["resultPath"]
    assert "再出图完成" in completed["message"]
