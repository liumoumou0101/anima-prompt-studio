"""Transport/storage regression cases carried forward from the stable V2 suite."""
import json
import io
import sqlite3
import threading
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest

from anima_prompt_studio.domain.execution_models import (
    GenerationRun,
    GenerationRunState,
    HIRES_FIX_WORKFLOW_KIND,
    RemoteArtifact,
    RemoteCredentials,
    RemoteProfile,
    WorkflowBinding,
    WorkflowProfile,
)
from anima_prompt_studio.domain.models import LoRASelection, PromptJob
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
from anima_prompt_studio_v3.remote.comfy_client import ComfyAPIError, ComfyUIClient
from anima_prompt_studio_v3.remote.execution_coordinator import RemoteExecutionCoordinator, RemoteExecutionError
from anima_prompt_studio_v3.remote.result_organizer import ResultOrganizer, sanitize_path_segment
from anima_prompt_studio_v3.remote.ssh_tunnel import SshTunnel


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


def test_comfy_client_preflights_enum_backed_model_inputs():
    class ObjectInfoSession(FakeSession):
        def get(self, url, timeout=None):
            if url.endswith("/object_info"):
                return FakeResponse({
                    "UNETLoader": {"input": {"required": {
                        "unet_name": [["available.safetensors"]],
                        "weight_dtype": [["default", "fp8_e4m3fn"]],
                    }}},
                })
            return super().get(url, timeout)

    client = ComfyUIClient("http://127.0.0.1:8188", ObjectInfoSession())
    errors = client.validate_workflow_inputs({
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "missing.safetensors", "weight_dtype": "default",
        }},
    })

    assert len(errors) == 1
    assert "missing.safetensors" in errors[0]


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


def test_ssh_tunnel_retries_transient_handshake_failures(monkeypatch):
    class FakeSSHException(Exception):
        pass

    class FakeAuthenticationException(FakeSSHException):
        pass

    class FakeTransport:
        @staticmethod
        def is_active():
            return True

    class FakeSSHClient:
        attempts = 0

        def load_system_host_keys(self):
            pass

        def set_missing_host_key_policy(self, _policy):
            pass

        def connect(self, **_kwargs):
            type(self).attempts += 1
            if type(self).attempts < 3:
                raise FakeSSHException("No existing session")

        def get_transport(self):
            return FakeTransport()

        def close(self):
            pass

    fake_paramiko = SimpleNamespace(
        SSHClient=FakeSSHClient,
        SSHException=FakeSSHException,
        AuthenticationException=FakeAuthenticationException,
    )
    profile = remote_profile()
    profile.known_host_fingerprint = "SHA256:test"
    tunnel = SshTunnel(profile, local_bind_port=0)
    monkeypatch.setattr(tunnel, "probe_fingerprint", lambda: profile.known_host_fingerprint)
    monkeypatch.setattr(tunnel, "_paramiko", lambda: fake_paramiko)
    monkeypatch.setattr("anima_prompt_studio_v3.remote.ssh_tunnel.time.sleep", lambda _seconds: None)

    with tunnel:
        tunnel.open(RemoteCredentials(password="secret"))
        assert tunnel.local_port > 0
        assert tunnel.server is not None
        assert tunnel.server.server_address[0] == "127.0.0.1"

    assert FakeSSHClient.attempts == 3


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
    timing = manifest["generation_run"]["request_json"]["execution_timings"][0]
    assert set(timing) == {"ssh_open_ms", "environment_ms", "compile_ms",
                           "node_validation_ms", "input_validation_ms", "submit_ms", "prepare_total_ms"}
    assert all(value >= 0 for value in timing.values())


def test_preparation_failure_records_duration_without_submitting(tmp_path):
    class BrokenClient(FakeClient):
        def validate_workflow_nodes(self, workflow):
            raise ComfyAPIError("offline", code="connection_error")

        def submit(self, *args):
            pytest.fail("failed preflight must not submit")

    coordinator = RemoteExecutionCoordinator(organizer=ResultOrganizer(tmp_path),
        tunnel_factory=FakeTunnel, client_factory=lambda _: BrokenClient())
    job = PromptJob(model_profile_id="anima_turbo_v1", positive_prompt="a garden")
    with pytest.raises(RemoteExecutionError) as error:
        coordinator.execute(job, remote_profile(), workflow_profile(), "anima_turbo_v1")
    timing = error.value.run.request_json["execution_timings"][0]
    assert timing["node_validation_ms"] >= 0
    assert "submit_ms" not in timing


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
