import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from pydantic import ValidationError

from anima_prompt_studio.domain.execution_models import GenerationRunState, RemoteProfile
from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio_v3.api.app import _save_remote_profile_settings
from anima_prompt_studio_v3.api.models import RemoteProfileSettingsRequest
from anima_prompt_studio_v3.remote.execution_coordinator import RemoteExecutionCoordinator
from anima_prompt_studio_v3.remote.local_connection import LocalComfyConnection
from anima_prompt_studio_v3.remote.result_organizer import ResultOrganizer
from anima_prompt_studio_v3.runtime.comfy_access import ManagedComfyAccess
from anima_prompt_studio_v3.runtime.workflow_catalog import WorkflowCatalog, fingerprint
from anima_prompt_studio_v3.storage.runtime_repository import SQLiteRepository
from test_remote_runtime_regression import api_workflow, workflow_profile
from test_api import reference_db


@pytest.fixture
def protocol_server():
    class Handler(BaseHTTPRequestHandler):
        submissions = []

        def log_message(self, *_args):
            pass

        def reply(self, value, mime="application/json"):
            data = json.dumps(value).encode() if mime == "application/json" else value
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/system_stats":
                self.reply({"devices": [{"name": "Local protocol simulator"}]})
            elif path == "/queue":
                self.reply({"queue_running": [], "queue_pending": []})
            elif path == "/object_info":
                self.reply({node["class_type"]: {} for node in api_workflow().values()})
            elif path.startswith("/history/"):
                self.reply({"local-prompt": {"status": {"completed": True}, "outputs": {
                    "8": {"images": [{"filename": "local.png", "type": "output"}]}}}})
            elif path == "/view":
                self.reply(b"simulated-image", "image/png")
            else:
                self.send_error(404)

        def do_POST(self):
            assert self.path == "/prompt"
            self.submissions.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.reply({"prompt_id": "local-prompt"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, Handler.submissions
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def local_profile(port=8188):
    return RemoteProfile(id="local", connection_type="local", ssh_host="", ssh_user="",
                         comfy_port=port, model_aliases={"anima_turbo_v1": "anima-turbo.safetensors"})


@pytest.mark.parametrize("host", ["example.com", "127.0.0.1.evil", "0.0.0.0", "127.0.0.1/path"])
def test_local_endpoint_rejects_non_loopback(host):
    with pytest.raises(ValidationError):
        RemoteProfileSettingsRequest(display_name="Local", connection_type="local", comfy_host=host)
    with pytest.raises(ValueError):
        LocalComfyConnection(local_profile().model_copy(update={"comfy_host": host}))


def test_local_save_and_ssh_hash_compatibility(tmp_path):
    database = tmp_path / "runtime.db"
    saved = _save_remote_profile_settings(database, RemoteProfileSettingsRequest(
        display_name="Local", connection_type="local", comfy_port=8288))
    assert saved["connection_ready"] and not saved["host_fingerprint_confirmed"]
    assert not saved["has_saved_password"]
    repo = SQLiteRepository(database)
    profile = repo.get_remote_profile(saved["id"])
    repo.close()
    assert profile.connection_type == "local" and profile.comfy_port == 8288
    ssh = local_profile().model_copy(update={"connection_type": "ssh"})
    old = ssh.model_dump(mode="json")
    old.pop("connection_type")
    old.pop("display_name")
    assert fingerprint(ssh) == hashlib.sha256(json.dumps(old, sort_keys=True).encode()).hexdigest()
    assert fingerprint(profile) != fingerprint(profile.model_copy(update={"comfy_port": 8388}))


def test_local_execution_download_and_resume_without_ssh(tmp_path, protocol_server):
    port, submissions = protocol_server
    profile = local_profile(port)
    coordinator = RemoteExecutionCoordinator(
        organizer=ResultOrganizer(tmp_path), poll_interval=0,
        tunnel_factory=lambda _: pytest.fail("Local execution must not create SSH"))
    job = PromptJob(model_profile_id="anima_turbo_v1", positive_prompt="1girl", negative_prompt="blur")
    result = coordinator.execute(job, profile, workflow_profile(), "anima_turbo_v1")
    assert result.run.state == GenerationRunState.COMPLETED
    assert len(submissions) == 1
    assert submissions[0]["prompt"]["6"]["inputs"]["text"] == "1girl"
    assert submissions[0]["prompt"]["7"]["inputs"]["text"] == "blur"
    assert Path(result.artifacts[0].local_path).read_bytes() == b"simulated-image"
    assert (Path(result.run.output_dir) / "workflow_api.json").exists()
    resumed = coordinator.resume(result.run, profile, workflow_profile())
    assert resumed.run.state == GenerationRunState.COMPLETED
    assert len(submissions) == 1
    assert "local_open_ms" in result.run.request_json["execution_timings"][0]


def test_local_inspection_and_browser_access_invalidate_changed_endpoint(tmp_path, protocol_server):
    port, submissions = protocol_server
    database = tmp_path / "runtime.db"
    repo = SQLiteRepository(database)
    profile = local_profile(port)
    repo.save_remote_profile(profile)
    catalog = WorkflowCatalog(database)
    catalog.inspect(profile.id)
    snapshot = repo.get_setting("workflow_capabilities:" + profile.id)
    assert snapshot["devices"] == ["Local protocol simulator"]
    manager = ManagedComfyAccess(database, tunnel_factory=lambda *_a, **_k: pytest.fail("No SSH"))
    try:
        assert manager.open(profile.id)["local_url"] == f"http://127.0.0.1:{port}"
        previous = manager._tunnel
        repo.save_remote_profile(profile.model_copy(update={"comfy_host": "localhost"}))
        assert manager.open(profile.id)["local_url"] == f"http://localhost:{port}"
        assert not previous.active
        assert all(item["state"] != "ready" for item in catalog.report(profile.id)["items"])
        with pytest.raises(ValueError, match="文件导入"):
            catalog.read_remote_file(profile.id, "/tmp/workflow.json", None)
    finally:
        manager.close()
        repo.close()
    assert not manager.status()["ready"]
    assert submissions == []


def test_local_api_connection_and_inspection_accept_no_ssh(reference_db, tmp_path, protocol_server):
    from fastapi.testclient import TestClient
    from anima_prompt_studio_v3.api import create_api_runtime

    port, submissions = protocol_server
    runtime = create_api_runtime(reference_db, v2_database=tmp_path / "runtime.db")
    with TestClient(runtime.app, base_url="http://127.0.0.1") as client:
        exchanged = client.post("/api/v3/session/exchange", json={"bootstrap_token": runtime.bootstrap_token},
                                headers={"Origin": "http://127.0.0.1"})
        headers = {"Origin": "http://127.0.0.1", "X-Anima-Session": exchanged.json()["session_token"]}
        saved = client.post("/api/v3/settings/remote-profiles", headers=headers,
                            json={"display_name": "Local", "connection_type": "local", "comfy_port": port})
        assert saved.status_code == 201, saved.text
        profile_id = saved.json()["id"]
        url = f"/api/v3/settings/remote-profiles/{profile_id}"
        tested = client.post(url + "/test-connection", headers=headers, json={})
        assert tested.status_code == 200, tested.text
        assert tested.json()["devices"] == ["Local protocol simulator"]
        assert client.post(url + "/probe-host-key", headers=headers, json={}).status_code == 409
        inspected = client.post(f"/api/v3/workflows/servers/{profile_id}/inspect", headers=headers, json={})
        assert inspected.status_code == 200, inspected.text
    runtime.app.state.workflow_jobs.close()
    assert submissions == []


def test_fast_inspection_does_not_pair_old_report_with_completed_state(reference_db, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from anima_prompt_studio_v3.api import create_api_runtime

    runtime = create_api_runtime(reference_db, v2_database=tmp_path / "runtime.db")
    jobs = runtime.app.state.workflow_jobs
    jobs.jobs["local"] = {"state": "running", "error": None, "cancel": threading.Event()}

    def report_while_finishing(_remote_id):
        # Reproduce completion just after the old SQLite snapshot was read.
        jobs.jobs["local"]["state"] = "completed"
        return {"checked_at": None, "items": []}

    monkeypatch.setattr(jobs.manager, "report", report_while_finishing)
    with TestClient(runtime.app, base_url="http://127.0.0.1") as client:
        exchanged = client.post("/api/v3/session/exchange", json={"bootstrap_token": runtime.bootstrap_token},
                                headers={"Origin": "http://127.0.0.1"})
        result = client.get("/api/v3/workflows/servers/local",
                            headers={"X-Anima-Session": exchanged.json()["session_token"]})
        assert result.status_code == 200
        assert result.json()["checked_at"] is None
        assert result.json()["inspection"]["state"] == "running"  # UI must fetch again.
    jobs.close()
