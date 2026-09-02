import json
import io
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest

from anima_prompt_studio.domain.execution_models import (
    GenerationRun,
    GenerationRunState,
    HIRES_FIX_WORKFLOW_KIND,
    RemoteArtifact,
    RemoteProfile,
    WorkflowBinding,
    WorkflowProfile,
)
from anima_prompt_studio.domain.models import LoRASelection, PromptJob
from anima_prompt_studio.repositories import SQLiteRepository
from anima_prompt_studio.services.remote.comfy_client import ComfyAPIError, ComfyUIClient
from anima_prompt_studio.services.remote.execution_coordinator import RemoteExecutionCoordinator, RemoteExecutionError
from anima_prompt_studio.services.remote.result_organizer import ResultOrganizer, sanitize_path_segment
from anima_prompt_studio.services.remote.workflow_renderer import WorkflowRenderError, WorkflowRenderer
from anima_prompt_studio.services.remote.workflow_discovery import (
    discover_compshare_workflows,
    frontend_workflow_to_api,
    parse_ssh_command,
)
from anima_prompt_studio.services.remote.workflow_compatibility import infer_workflow_model_profiles
from anima_prompt_studio.ui.remote_dialogs import (
    build_auto_workflow_profile,
    detect_lora_slots,
    detect_workflow_bindings,
)


def api_workflow():
    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {"seed": 1, "steps": 10, "cfg": 1.0, "sampler_name": "euler", "scheduler": "normal"},
        },
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "old.safetensors"}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old positive"}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "old negative"}},
        "8": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ComfyUI"}},
    }


def hires_fix_workflow():
    return {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "anima-base-v1.0.safetensors", "weight_dtype": "default",
        }},
        "2": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3}},
        "3": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "qwen_3_06b_base.safetensors", "type": "stable_diffusion", "device": "default",
        }},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": "old positive"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": "old negative"}},
        "7": {"class_type": "EmptyLatentImage", "inputs": {
            "width": ["13", 0], "height": ["13", 1], "batch_size": 1,
        }},
        "8": {"class_type": "KSampler", "inputs": {
            "model": ["2", 0], "positive": ["5", 0], "negative": ["6", 0],
            "latent_image": ["7", 0], "seed": 44, "steps": 34, "cfg": 4.5,
            "sampler_name": "er_sde", "scheduler": "simple", "denoise": 1.0,
        }},
        "10": {"class_type": "KSampler", "inputs": {
            "model": ["2", 0], "positive": ["5", 0], "negative": ["6", 0],
            "latent_image": ["14", 0], "seed": 45, "steps": 18, "cfg": 4.5,
            "sampler_name": "er_sde", "scheduler": "simple", "denoise": 0.35,
        }},
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["4", 0]}},
        "12": {"class_type": "SaveImage", "inputs": {
            "images": ["11", 0], "filename_prefix": "anima_hiresfix_1p5x",
        }},
        "13": {"class_type": "ResolutionSelector", "inputs": {
            "aspect_ratio": "4:3 (Standard)", "megapixels": 1, "multiple": 8,
        }},
        "14": {"class_type": "LatentUpscaleBy", "inputs": {
            "samples": ["8", 0], "upscale_method": "nearest-exact", "scale_by": 1.5,
        }},
    }


def workflow_profile():
    raw = {
        "positive_prompt": ("6", "text"),
        "negative_prompt": ("7", "text"),
        "checkpoint": ("4", "ckpt_name"),
        "seed": ("3", "seed"),
        "steps": ("3", "steps"),
        "cfg": ("3", "cfg"),
        "sampler": ("3", "sampler_name"),
        "scheduler": ("3", "scheduler"),
        "width": ("5", "width"),
        "height": ("5", "height"),
        "batch_size": ("5", "batch_size"),
        "filename_prefix": ("8", "filename_prefix"),
    }
    return WorkflowProfile(
        id="anima_turbo_api_v1",
        display_name="ANIMA Turbo",
        api_workflow=api_workflow(),
        bindings={name: WorkflowBinding(node_id=node, input=input_name) for name, (node, input_name) in raw.items()},
        compatible_model_profiles=["anima_turbo_v1"],
    )


def remote_profile():
    return RemoteProfile(
        id="remote-1",
        provider_preset_id="custom",
        display_name="测试云主机",
        ssh_host="example.invalid",
        ssh_user="root",
        model_aliases={"anima_turbo_v1": "anima-turbo.safetensors"},
    )


def test_v2_repository_round_trip_and_active_run_query(tmp_path):
    repo = SQLiteRepository(tmp_path / "v2.db")
    remote = remote_profile()
    workflow = workflow_profile()
    repo.save_remote_profile(remote)
    repo.save_workflow_profile(workflow)
    run = GenerationRun(
        prompt_job_id="job-1",
        remote_profile_id=remote.id,
        workflow_profile_id=workflow.id,
        state=GenerationRunState.QUEUED,
    )
    repo.save_generation_run(run)

    assert repo.get_remote_profile(remote.id).model_aliases["anima_turbo_v1"] == "anima-turbo.safetensors"
    assert repo.get_workflow_profile(workflow.id).bindings["positive_prompt"].input_name == "text"
    assert repo.list_active_generation_runs()[0].id == run.id
    assert sqlite3.connect(repo.db_path).execute("PRAGMA user_version").fetchone()[0] == 4
    repo.close()


def test_v1_database_migrates_to_v2_with_backup(tmp_path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.execute("""CREATE TABLE prompt_jobs (
        id TEXT PRIMARY KEY, project_name TEXT NOT NULL, updated_at TEXT NOT NULL,
        original_zh TEXT NOT NULL, positive_prompt TEXT NOT NULL, payload_json TEXT NOT NULL,
        favorite INTEGER NOT NULL DEFAULT 0
    )""")
    connection.execute("PRAGMA user_version = 1")
    connection.commit(); connection.close()

    repo = SQLiteRepository(path)
    assert (tmp_path / "legacy.v1.bak").is_file()
    assert repo.connection.execute("PRAGMA user_version").fetchone()[0] == 4
    assert repo.connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='generation_runs'"
    ).fetchone()
    repo.close()


def test_workflow_renderer_injects_job_without_mutating_template():
    profile = workflow_profile()
    job = PromptJob(model_profile_id="anima_turbo_v1", positive_prompt="1girl", negative_prompt="bad")
    job.generation_params.seed = 42
    job.generation_params.width = 896
    job.generation_params.height = 1152
    result = WorkflowRenderer().render(job, profile, remote_profile(), "anima_turbo_v1", "abcdefgh-run")

    assert result.workflow["6"]["inputs"]["text"] == "1girl"
    assert result.workflow["7"]["inputs"]["text"] == "bad"
    assert result.workflow["4"]["inputs"]["ckpt_name"] == "anima-turbo.safetensors"
    assert result.workflow["5"]["inputs"]["width"] == 896
    assert result.workflow["3"]["inputs"]["seed"] == 42
    assert result.workflow["8"]["inputs"]["filename_prefix"] == "Anima_abcdefgh"
    assert profile.api_workflow["6"]["inputs"]["text"] == "old positive"


def test_workflow_renderer_preserves_discovered_template_model_without_alias():
    profile = workflow_profile()
    profile.api_workflow["4"]["inputs"]["ckpt_name"] = "anima-base-v1.0.safetensors"
    remote = remote_profile()
    remote.model_aliases.clear()

    result = WorkflowRenderer().render(
        PromptJob(model_profile_id="anima_turbo_v1"),
        profile,
        remote,
        "anima_turbo_v1",
        "run",
    )

    assert result.checkpoint_name == "anima-base-v1.0.safetensors"
    assert result.workflow["4"]["inputs"]["ckpt_name"] == "anima-base-v1.0.safetensors"


def test_parse_compshare_ssh_command():
    parsed = parse_ssh_command("ssh -p 23 root@203.0.113.10")
    assert (parsed.user, parsed.host, parsed.port) == ("root", "203.0.113.10", 23)


def test_frontend_workflow_conversion_supports_links_widgets_and_seed_control():
    frontend = {
        "nodes": [
            {
                "id": 1,
                "type": "KSampler",
                "inputs": [
                    {"name": "model", "link": 8, "type": "MODEL"},
                    {"name": "seed", "link": None, "type": "INT", "widget": {"name": "seed"}},
                    {"name": "steps", "link": None, "type": "INT", "widget": {"name": "steps"}},
                ],
                "widgets_values": [42, "randomize", 30],
            },
            {
                "id": 2,
                "type": "UNETLoader",
                "inputs": [
                    {"name": "unet_name", "link": None, "type": "COMBO", "widget": {"name": "unet_name"}},
                ],
                "widgets_values": ["anima-base-v1.0.safetensors"],
            },
        ],
        "links": [[8, 2, 0, 1, 0, "MODEL"]],
    }

    api = frontend_workflow_to_api(frontend)

    assert api["1"]["inputs"] == {"model": ["2", 0], "seed": 42, "steps": 30}
    assert api["2"]["inputs"]["unet_name"] == "anima-base-v1.0.safetensors"


def test_compshare_discovery_includes_all_numbered_workflow_types():
    payload = json.dumps({"prompt": api_workflow()}).encode()

    class FakeSFTP:
        def listdir(self, root):
            return [
                "01_基础文生图.json",
                "03_NAG少步生成.json",
                "20_分块放大.json",
                "使用说明.txt",
            ]

        def open(self, path, mode):
            return io.BytesIO(payload)

        def close(self):
            pass

    class FakeClient:
        def open_sftp(self):
            return FakeSFTP()

    class FakeTunnel:
        client = FakeClient()

    discovered = discover_compshare_workflows(FakeTunnel())

    assert [item[0] for item in discovered] == ["01_基础文生图", "03_NAG少步生成", "20_分块放大"]


def test_compshare_discovery_derives_aesthetic_workflows_when_models_exist():
    workflow = api_workflow()
    workflow["4"] = {
        "class_type": "UNETLoader",
        "inputs": {"unet_name": "anima-base-v1.0.safetensors", "weight_dtype": "default"},
    }
    payload = json.dumps({"prompt": workflow}).encode()

    class FakeSFTP:
        def listdir(self, root):
            if root.endswith("diffusion_models"):
                return ["anima-aesthetic-v1.0.safetensors", "anima-aesthetic-v1.1.safetensors"]
            return ["01_基础文生图.json"]

        def open(self, path, mode):
            return io.BytesIO(payload)

        def close(self):
            pass

    class FakeClient:
        def open_sftp(self):
            return FakeSFTP()

    class FakeTunnel:
        client = FakeClient()

    discovered = discover_compshare_workflows(FakeTunnel())

    assert [item[0][:2] for item in discovered] == ["01", "21", "22"]
    assert discovered[1][2]["4"]["inputs"]["unet_name"] == "anima-aesthetic-v1.0.safetensors"
    assert discovered[2][2]["4"]["inputs"]["unet_name"] == "anima-aesthetic-v1.1.safetensors"


def test_workflow_binding_detection_finds_standard_comfy_nodes():
    bindings = detect_workflow_bindings(api_workflow())
    assert bindings["positive_prompt"].node_id == "6"
    assert bindings["negative_prompt"].node_id == "7"
    assert bindings["checkpoint"].input_name == "ckpt_name"
    assert bindings["filename_prefix"].node_id == "8"


def test_auto_workflow_detection_follows_sampler_connections(tmp_path):
    workflow = api_workflow()
    workflow["3"]["inputs"].update({
        "model": ["4", 0],
        "positive": ["7", 0],
        "negative": ["6", 0],
        "latent_image": ["5", 0],
    })
    workflow["6"]["inputs"]["text"] = "this is actually negative"
    workflow["7"]["inputs"]["text"] = "this is actually positive"
    profile, missing = build_auto_workflow_profile(
        workflow,
        tmp_path / "基础文生图.json",
        "anima_turbo_v1",
    )
    assert missing == []
    assert profile.workflow_kind == "txt2img_basic"
    assert profile.bindings["positive_prompt"].node_id == "7"
    assert profile.bindings["negative_prompt"].node_id == "6"
    assert profile.bindings["width"].node_id == "5"
    assert profile.compatible_model_profiles == ["anima_turbo_v1"]


def test_auto_workflow_detection_recognizes_two_stage_hires_fix(tmp_path):
    profile, missing = build_auto_workflow_profile(
        hires_fix_workflow(),
        tmp_path / "04_高清修复1点5倍_HiresFix_1_5x.json",
    )

    assert missing == []
    assert profile.workflow_kind == HIRES_FIX_WORKFLOW_KIND
    assert profile.compatible_model_profiles == ["anima_base_v1"]
    assert profile.bindings["seed"].node_id == "8"
    assert profile.bindings["refiner_seed"].node_id == "10"
    assert profile.bindings["refiner_denoise"].node_id == "10"
    assert profile.bindings["upscale_factor"].node_id == "14"


def test_hires_fix_renderer_preserves_template_stages_and_derives_refiner_seed(tmp_path):
    profile, missing = build_auto_workflow_profile(
        hires_fix_workflow(),
        tmp_path / "04_高清修复1点5倍_HiresFix_1_5x.json",
    )
    assert missing == []
    job = PromptJob(model_profile_id="anima_base_v1", positive_prompt="1girl", negative_prompt="bad")
    job.generation_params.seed = 123
    job.generation_params.width = 896
    job.generation_params.height = 1152
    job.generation_params.steps = 99
    job.generation_params.cfg = 9.0
    job.generation_params.sampler = "euler"
    job.generation_params.scheduler = "normal"

    result = WorkflowRenderer().render(job, profile, remote_profile(), "anima_base_v1", "hires-run")

    base = result.workflow["8"]["inputs"]
    refiner = result.workflow["10"]["inputs"]
    assert (base["seed"], base["steps"], base["cfg"], base["sampler_name"], base["scheduler"]) == (
        123, 34, 4.5, "er_sde", "simple",
    )
    assert (refiner["seed"], refiner["steps"], refiner["cfg"], refiner["denoise"]) == (
        124, 18, 4.5, 0.35,
    )
    assert result.workflow["7"]["inputs"]["width"] == 896
    assert result.workflow["7"]["inputs"]["height"] == 1152
    assert result.workflow["5"]["inputs"]["text"] == "1girl"
    assert result.workflow["1"]["inputs"]["unet_name"] == "anima-base-v1.0.safetensors"
    assert result.metadata["output_width"] == 1344
    assert result.metadata["output_height"] == 1728
    assert result.metadata["base_sampler"]["steps"] == 34
    assert result.metadata["refiner_sampler"]["steps"] == 18
    assert profile.api_workflow["8"]["inputs"]["seed"] == 44


def test_v3_hires_recipe_writes_the_declared_base_stage_parameters(tmp_path):
    profile, missing = build_auto_workflow_profile(
        hires_fix_workflow(),
        tmp_path / "04_高清修复1点5倍_HiresFix_1_5x.json",
    )
    assert missing == []
    job = PromptJob(
        model_profile_id="anima_base_v1",
        positive_prompt="1girl",
        integration_metadata={"generation_recipe": {"schema": "v3-workflow-recipe/1", "id": "hires_template"}},
    )
    job.generation_params.steps = 34
    job.generation_params.cfg = 4.5
    job.generation_params.sampler = "er_sde"
    job.generation_params.scheduler = "simple"

    result = WorkflowRenderer().render(job, profile, remote_profile(), "anima_base_v1", "v3-hires-run")

    base = result.workflow["8"]["inputs"]
    assert (base["steps"], base["cfg"], base["sampler_name"], base["scheduler"]) == (34, 4.5, "er_sde", "simple")


@pytest.mark.parametrize(("filename", "checkpoint", "expected"), [
    ("01_基础文生图.json", "anima-base-v1.0.safetensors", "anima_base_v1"),
    ("02_Turbo极速文生图.json", "anima-turbo-v1.0.safetensors", "anima_turbo_v1"),
    ("05_DMDX少步文生图.json", "anima-base-v1.0.safetensors", "anima_turbo_v1"),
    ("21_美学文生图_Aesthetic_v1.0.json", "anima-aesthetic-v1.0.safetensors", "anima_aesthetic_v1"),
])
def test_compshare_workflow_name_infers_model_profile(filename, checkpoint, expected, tmp_path):
    workflow = api_workflow()
    workflow["4"]["inputs"]["ckpt_name"] = checkpoint

    profile, _ = build_auto_workflow_profile(workflow, tmp_path / filename)

    assert profile.compatible_model_profiles == [expected]
    assert infer_workflow_model_profiles(workflow, filename) == [expected]


def test_renderer_rejects_legacy_unmapped_base_workflow_with_turbo_job():
    profile = workflow_profile()
    profile.display_name = "01_基础文生图"
    profile.source_path = "/workspace/ComfyUI/user/default/workflows/01_基础文生图.json"
    profile.compatible_model_profiles = []
    profile.api_workflow["4"]["inputs"]["ckpt_name"] = "anima-base-v1.0.safetensors"

    with pytest.raises(WorkflowRenderError, match="不支持模型配置 anima_turbo_v1"):
        WorkflowRenderer().render(
            PromptJob(model_profile_id="anima_turbo_v1"),
            profile,
            remote_profile(),
            "anima_turbo_v1",
            "run",
        )


def test_auto_detection_does_not_bind_same_text_node_as_positive_and_negative():
    workflow = api_workflow()
    workflow.pop("7")
    workflow["3"]["inputs"].update({
        "model": ["4", 0],
        "positive": ["6", 0],
        "negative": ["6", 0],
        "latent_image": ["5", 0],
    })
    bindings = detect_workflow_bindings(workflow)
    assert bindings["positive_prompt"].node_id == "6"
    assert "negative_prompt" not in bindings


def test_workflow_with_extra_control_or_second_sampler_is_not_basic_txt2img(tmp_path):
    workflow = api_workflow()
    workflow["3"]["inputs"].update({
        "model": ["4", 0],
        "positive": ["6", 0],
        "negative": ["7", 0],
        "latent_image": ["5", 0],
    })
    workflow["9"] = {"class_type": "LoadImage", "inputs": {"image": "control.png"}}

    profile, missing = build_auto_workflow_profile(workflow, tmp_path / "控制工作流.json")

    assert missing == []
    assert profile.workflow_kind == "unknown"


def test_lora_slot_detection_and_unused_slot_neutralization():
    profile = workflow_profile()
    profile.api_workflow["9"] = {
        "class_type": "LoraLoader",
        "inputs": {"lora_name": "default.safetensors", "strength_model": 1.0, "strength_clip": 1.0},
    }
    profile.lora_slots = detect_lora_slots(profile.api_workflow)
    result = WorkflowRenderer().render(
        PromptJob(model_profile_id="anima_turbo_v1"),
        profile,
        remote_profile(),
        "anima_turbo_v1",
        "run",
    )
    assert result.workflow["9"]["inputs"]["strength_model"] == 0.0
    assert result.workflow["9"]["inputs"]["strength_clip"] == 0.0


def test_workflow_renderer_rejects_unavailable_lora_slots():
    job = PromptJob(model_profile_id="anima_turbo_v1", lora_selection=[LoRASelection(logical_id="style")])
    with pytest.raises(WorkflowRenderError, match="LoRA"):
        WorkflowRenderer().render(job, workflow_profile(), remote_profile(), "anima_turbo_v1", "run")


def test_result_organizer_sanitizes_and_writes_reproducible_sidecars(tmp_path):
    job = PromptJob(project_name='雨夜:少女?*', positive_prompt="1girl")
    run = GenerationRun(
        prompt_job_id=job.id,
        remote_profile_id="remote",
        workflow_profile_id="workflow",
        state=GenerationRunState.DOWNLOADING,
        request_json={"resolved_seed": 42},
        actual_workflow={"1": {"class_type": "SaveImage", "inputs": {}}},
    )
    organizer = ResultOrganizer(tmp_path)
    artifact = organizer.save_artifact(
        job,
        run,
        RemoteArtifact(node_id="8", filename="remote.png", subfolder="../../unsafe"),
        b"fake-png",
        1,
        "image/png",
    )
    organizer.write_sidecars(job, run, [artifact])

    local_path = Path(artifact.local_path)
    assert local_path.is_file()
    assert local_path.read_bytes() == b"fake-png"
    assert tmp_path.resolve() in local_path.resolve().parents
    assert ":" not in local_path.name and "?" not in local_path.name
    manifest = json.loads((local_path.parent / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["generation_run"]["request_json"]["resolved_seed"] == 42
    assert manifest["generation_run"]["state"] == "downloading"
    assert (local_path.parent / "workflow_api.json").is_file()
    assert sanitize_path_segment("CON") == "_CON"

    duplicate = organizer.save_artifact(
        job,
        run,
        RemoteArtifact(node_id="8", filename="remote.png"),
        b"fake-png",
        1,
        "image/png",
    )
    assert duplicate.local_path == artifact.local_path
    assert len(list(local_path.parent.glob("*.png"))) == 1


class FakeResponse:
    def __init__(self, payload=None, content=b"", content_type="application/json", status_code=200):
        self.payload = payload
        self.content = content
        self.headers = {"Content-Type": content_type}
        self.status_code = status_code
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self):
        self.posts = []

    def get(self, url, timeout=None):
        if url.endswith("/system_stats"):
            return FakeResponse({"devices": [{"name": "RTX Test"}]})
        if url.endswith("/queue"):
            return FakeResponse({"queue_running": [], "queue_pending": []})
        if "/history/prompt-1" in url:
            return FakeResponse({
                "prompt-1": {
                    "status": {"completed": True, "status_str": "success"},
                    "outputs": {"8": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]}},
                }
            })
        if "/view?" in url:
            return FakeResponse(content=b"image", content_type="image/png")
        if url.endswith("/object_info"):
            return FakeResponse({name: {} for name in ["KSampler", "CheckpointLoaderSimple", "EmptyLatentImage", "CLIPTextEncode", "SaveImage"]})
        raise AssertionError(url)

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json))
        if url.endswith("/prompt"):
            return FakeResponse({"prompt_id": "prompt-1", "number": 1})
        if url.endswith("/queue"):
            return FakeResponse({})
        raise AssertionError(url)


def test_comfy_client_health_submit_history_and_download():
    client = ComfyUIClient("http://127.0.0.1:8188", FakeSession())
    report = client.validate_environment()
    assert report.devices == ["RTX Test"]
    assert client.submit(api_workflow(), "client", "requested") == "prompt-1"
    history = client.wait_for_completion("prompt-1", sleep=lambda _: None)
    artifacts = client.list_output_artifacts(history)
    content, mime_type = client.download_artifact(artifacts[0])
    assert content == b"image" and mime_type == "image/png"


def test_comfy_client_against_local_protocol_server():
    pytest.importorskip("requests")

    class Handler(BaseHTTPRequestHandler):
        submitted = None

        def log_message(self, format, *args):
            pass

        def _json(self, payload, status=200):
            encoded = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers(); self.wfile.write(encoded)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/system_stats":
                self._json({"devices": [{"name": "Protocol GPU"}]})
            elif path == "/queue":
                self._json({"queue_running": [], "queue_pending": []})
            elif path == "/object_info":
                self._json({node["class_type"]: {} for node in api_workflow().values()})
            elif path == "/history/protocol-prompt":
                self._json({"protocol-prompt": {"status": {"completed": True}, "outputs": {
                    "8": {"images": [{"filename": "协议 图.png", "subfolder": "批量 1", "type": "output"}]}
                }}})
            elif path == "/view":
                payload = b"protocol-image"
                self.send_response(200); self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(payload))); self.end_headers(); self.wfile.write(payload)
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            Handler.submitted = json.loads(self.rfile.read(length))
            if self.path == "/prompt":
                self._json({"prompt_id": "protocol-prompt"})
            else:
                self._json({})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        client = ComfyUIClient(f"http://127.0.0.1:{server.server_port}")
        assert client.validate_environment().devices == ["Protocol GPU"]
        prompt_id = client.submit(api_workflow(), "client", "requested")
        history = client.wait_for_completion(prompt_id, sleep=lambda _: None)
        artifact = client.list_output_artifacts(history)[0]
        content, mime_type = client.download_artifact(artifact)
        assert Handler.submitted["client_id"] == "client"
        assert artifact.filename == "协议 图.png"
        assert content == b"protocol-image" and mime_type == "image/png"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


class RunningSession(FakeSession):
    def get(self, url, timeout=None):
        if "/history/" in url:
            return FakeResponse({})
        if url.endswith("/queue"):
            return FakeResponse({"queue_running": [[0, "prompt-running", {}, {}]], "queue_pending": []})
        return super().get(url, timeout)


def test_comfy_client_does_not_globally_interrupt_running_shared_task():
    client = ComfyUIClient("http://127.0.0.1:8188", RunningSession())
    with pytest.raises(ComfyAPIError) as captured:
        client.wait_for_completion("prompt-running", is_cancelled=lambda: True, sleep=lambda _: None)
    assert captured.value.code == "running_cancel_unsupported"


class FakeTunnel:
    def __init__(self, profile):
        self.profile = profile
        self.base_url = "http://fake"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def open(self, credentials):
        return self


class FakeClient:
    def validate_environment(self):
        return None

    def validate_workflow_nodes(self, workflow):
        return []

    def submit(self, workflow, client_id, prompt_id):
        return "remote-prompt"

    def wait_for_completion(self, prompt_id, on_state, **kwargs):
        on_state("running", "运行中")
        return {"outputs": {"8": {"images": [{"filename": "result.png", "type": "output"}]}}}

    def list_output_artifacts(self, history):
        return [RemoteArtifact(node_id="8", filename="result.png")]

    def download_artifact(self, artifact):
        return b"generated", "image/png"

    def cancel_pending(self, prompt_id):
        pass


class BatchFakeClient(FakeClient):
    def __init__(self, image_count=3):
        self.image_count = image_count

    def wait_for_completion(self, prompt_id, on_state, **kwargs):
        on_state("running", "运行中")
        return {"outputs": {"8": {"images": [
            {"filename": f"result_{index}.png", "type": "output"}
            for index in range(1, self.image_count + 1)
        ]}}}

    def list_output_artifacts(self, history):
        return [RemoteArtifact(node_id="8", filename=f"result_{index}.png")
                for index in range(1, self.image_count + 1)]

    def download_artifact(self, artifact):
        return f"generated-{artifact.filename}".encode(), "image/png"


def test_execution_coordinator_completes_full_fake_remote_flow(tmp_path):
    updates = []
    job = PromptJob(model_profile_id="anima_turbo_v1", project_name="完整流程", positive_prompt="1girl")
    coordinator = RemoteExecutionCoordinator(
        organizer=ResultOrganizer(tmp_path),
        tunnel_factory=FakeTunnel,
        client_factory=lambda _: FakeClient(),
        on_update=lambda run: updates.append(run.state),
        poll_interval=0,
    )
    result = coordinator.execute(job, remote_profile(), workflow_profile(), "anima_turbo_v1")

    assert result.run.state == GenerationRunState.COMPLETED
    assert result.run.remote_prompt_id == "remote-prompt"
    assert Path(result.artifacts[0].local_path).read_bytes() == b"generated"
    assert GenerationRunState.RUNNING in updates
    assert updates[-1] == GenerationRunState.COMPLETED
    manifest = json.loads((Path(result.run.output_dir) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["generation_run"]["state"] == "completed"


def test_batch_generation_renders_downloads_and_records_every_image(tmp_path):
    job = PromptJob(model_profile_id="anima_turbo_v1", project_name="批量完整流程", positive_prompt="1girl")
    job.generation_params.batch_size = 3
    profile = workflow_profile(); profile.workflow_kind = "txt2img_basic"
    coordinator = RemoteExecutionCoordinator(
        organizer=ResultOrganizer(tmp_path),
        tunnel_factory=FakeTunnel,
        client_factory=lambda _: BatchFakeClient(3),
        poll_interval=0,
    )

    result = coordinator.execute(job, remote_profile(), profile, "anima_turbo_v1")

    assert result.run.actual_workflow["5"]["inputs"]["batch_size"] == 3
    assert len(result.artifacts) == 3
    assert all(Path(artifact.local_path).is_file() for artifact in result.artifacts)
    manifest = json.loads((Path(result.run.output_dir) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["prompt_job"]["batch_size"] == 3
    assert len(manifest["artifacts"]) == 3


def test_batch_generation_rejects_incomplete_comfy_output(tmp_path):
    job = PromptJob(model_profile_id="anima_turbo_v1", project_name="批量少图", positive_prompt="1girl")
    job.generation_params.batch_size = 3
    profile = workflow_profile(); profile.workflow_kind = "txt2img_basic"
    coordinator = RemoteExecutionCoordinator(
        organizer=ResultOrganizer(tmp_path),
        tunnel_factory=FakeTunnel,
        client_factory=lambda _: BatchFakeClient(2),
        poll_interval=0,
    )

    with pytest.raises(RemoteExecutionError, match="请求 3 张.*只返回了 2 张") as captured:
        coordinator.execute(job, remote_profile(), profile, "anima_turbo_v1")

    assert captured.value.run.state == GenerationRunState.FAILED
    assert captured.value.run.error_code == "incomplete_batch"


def test_execution_coordinator_resumes_submitted_task_without_resubmitting(tmp_path):
    job = PromptJob(model_profile_id="anima_turbo_v1", project_name="恢复", positive_prompt="1girl")
    run = GenerationRun(
        prompt_job_id=job.id,
        remote_profile_id="remote-1",
        workflow_profile_id="anima_turbo_api_v1",
        remote_prompt_id="already-submitted",
        state=GenerationRunState.RUNNING,
        request_json={"prompt_job": job.model_dump(mode="json"), "resolved_seed": 7},
        actual_workflow=api_workflow(),
    )
    coordinator = RemoteExecutionCoordinator(
        organizer=ResultOrganizer(tmp_path),
        tunnel_factory=FakeTunnel,
        client_factory=lambda _: FakeClient(),
        poll_interval=0,
    )
    result = coordinator.resume(run, remote_profile(), workflow_profile())
    assert result.run.remote_prompt_id == "already-submitted"
    assert result.run.state == GenerationRunState.COMPLETED
