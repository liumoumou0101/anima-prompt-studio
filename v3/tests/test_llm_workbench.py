from __future__ import annotations

import json
import asyncio
import httpx
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from test_api import reference_db, client_and_session  # reuse isolated fixture data
from anima_prompt_studio_v3.api.llm_workbench import parse_prompt_output
from anima_prompt_studio_v3.adapters.v2 import CandidateToV2PromptJobAdapter


@pytest.fixture
def llm_client(tmp_path, monkeypatch, reference_db):
    monkeypatch.setenv("ANIMA_PROMPT_ASSISTANT_DIR", str(tmp_path / "llm"))
    from anima_prompt_studio_v3.prompt_assistant import config_manager as module
    monkeypatch.setattr(module, "config_manager", module.ConfigManager())
    client, token = client_and_session(reference_db)
    client.headers.update({"X-Anima-Session": token, "Origin": "http://127.0.0.1"})
    with client:
        yield client, module.config_manager


def settings(**overrides):
    return {"service_id": "custom", "base_url": "http://127.0.0.1:9876/v1",
            "model_name": "test-model", "api_key": "test-secret-12345", **overrides}


def test_settings_custom_model_masking_restart_and_key_retention(llm_client):
    client, manager = llm_client
    assert client.put("/api/v3/llm/settings", json=settings()).status_code == 200
    result = client.get("/api/v3/llm/settings")
    assert "test-secret-12345" not in result.text
    assert result.json()["current"] == {"service": "custom", "model": "test-model"}
    assert client.put("/api/v3/llm/settings", json=settings(api_key=None, model_name="another-model")).status_code == 200
    from anima_prompt_studio_v3.prompt_assistant.config_manager import ConfigManager
    reloaded = ConfigManager().get_llm_config()
    assert reloaded["api_key"] == "test-secret-12345"
    assert reloaded["model"] == "another-model"
    before = manager.load_config()
    bad = client.put("/api/v3/llm/settings", json=settings(api_key=None, base_url="https://other.example/v1"))
    assert bad.status_code == 422
    assert manager.load_config() == before
    assert client.put("/api/v3/llm/settings", json=settings(api_key=None, clear_api_key=True, base_url="https://other.example/v1")).status_code == 200
    assert manager.get_llm_config()["api_key"] == ""


def test_refresh_models_preserves_selection_options_and_uses_saved_key(llm_client, monkeypatch):
    client, manager = llm_client
    client.put("/api/v3/llm/settings", json=settings())
    config = manager.load_config()
    svc = next(s for s in config['model_services'] if s['id'] == 'custom')
    svc['llm_models'][0]['custom_option'] = 'preserved'
    manager.save_config(config)
    observed = []
    async def get(self, url, **kwargs):
        observed.append((url, kwargs))
        return httpx.Response(200, json={'data': [{'id': 'qwen-new'}, {'id': 'kimi-new'}, {'id': 'qwen-new'}]}, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    response = client.post('/api/v3/llm/services/custom/models/refresh', json={})
    assert response.json() == {'models': ['kimi-new', 'qwen-new'], 'count': 2}
    assert observed[0][0] == 'http://127.0.0.1:9876/v1/models'
    assert observed[0][1]['headers']['Authorization'] == 'Bearer test-secret-12345'
    assert manager.get_llm_config()['model'] == 'test-model'
    saved = next(s for s in manager.load_config()['model_services'] if s['id'] == 'custom')
    assert next(m for m in saved['llm_models'] if m['name'] == 'test-model')['custom_option'] == 'preserved'
    assert 'test-secret' not in response.text


def test_failed_model_refresh_keeps_config_and_hides_upstream_error(llm_client, monkeypatch):
    client, manager = llm_client
    client.put('/api/v3/llm/settings', json=settings())
    before = manager.load_config()
    async def get(self, url, **kwargs):
        return httpx.Response(401, text='secret upstream body', request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    response = client.post('/api/v3/llm/services/custom/models/refresh', json={})
    assert response.status_code == 502
    assert 'secret upstream' not in response.text
    assert manager.load_config() == before


def test_model_refresh_rejects_changed_service_while_fetching(llm_client, monkeypatch):
    client, manager = llm_client
    client.put('/api/v3/llm/settings', json=settings())
    async def get(self, url, **kwargs):
        config = manager.load_config()
        next(s for s in config['model_services'] if s['id'] == 'custom')['base_url'] = 'https://new.example/v1'
        manager.save_config(config)
        return httpx.Response(200, json={'data': [{'id': 'late-model'}]}, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    assert client.post('/api/v3/llm/services/custom/models/refresh', json={}).status_code == 422
    service = next(s for s in manager.load_config()['model_services'] if s['id'] == 'custom')
    assert service['base_url'] == 'https://new.example/v1'
    assert not any(m['name'] == 'late-model' for m in service['llm_models'])


def test_ollama_model_discovery(llm_client, monkeypatch):
    client, _ = llm_client
    client.put('/api/v3/llm/settings', json=settings(service_type='ollama', base_url='http://127.0.0.1:11434', api_key=None))
    async def get(self, url, **kwargs):
        assert url == 'http://127.0.0.1:11434/api/tags'
        assert kwargs['headers'] == {}
        return httpx.Response(200, json={'models': [{'name': 'local:latest'}]}, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    assert client.post('/api/v3/llm/services/custom/models/refresh', json={}).json()['models'] == ['local:latest']


@pytest.mark.parametrize("url", ["file:///tmp/api", "https://key:secret@example.com", "https://example.com?key=secret", "http://localhost:invalid"])
def test_invalid_url_does_not_save(llm_client, url):
    client, manager = llm_client
    before = manager.load_config()
    assert client.put("/api/v3/llm/settings", json=settings(base_url=url)).status_code == 422
    assert manager.load_config() == before


@pytest.mark.parametrize("mode", ["faithful", "expand"])
def test_prompt_contract_exclusions_and_mode(llm_client, monkeypatch, mode):
    client, _ = llm_client
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    async def fake(prompt, **kwargs):
        assert json.loads(prompt) == {"source_text": "水墨白鹤", "excluded_text": "文字"}
        system = kwargs["system_message_override"]["content"]
        assert ("FAITHFUL MODE" if mode == "faithful" else "EXPANSION MODE") in system
        assert "LOCAL exclusion scope" in system
        return {"success": True, "data": {"expanded": json.dumps({"positive": "An ink painting of a white crane bird", "negative": "text", "warnings": []})}}
    monkeypatch.setattr(LLMService, "expand_prompt", fake)
    response = client.post("/api/v3/workbench/prompt", json={"source_text": "水墨白鹤", "excluded_text": "文字", "mode": mode})
    assert response.status_code == 200
    assert response.json()["negative"] == "text"
    assert response.json()["rule_id"] == mode


@pytest.mark.parametrize("raw", ["just a prompt", '{"positive":"","negative":""}', '{"positive":"bird"}'])
def test_invalid_prompt_output_not_accepted(llm_client, monkeypatch, raw):
    client, _ = llm_client
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    async def fake(*args, **kwargs):
        return {"success": True, "data": {"expanded": raw}}
    monkeypatch.setattr(LLMService, "expand_prompt", fake)
    response = client.post("/api/v3/workbench/prompt", json={"source_text": "白鹤"})
    assert response.status_code == 502


def test_errors_do_not_echo_secrets_and_timeouts_are_explicit(llm_client, monkeypatch):
    client, _ = llm_client
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    async def failed(*args, **kwargs):
        return {"success": False, "error": "Bearer secret-credential"}
    monkeypatch.setattr(LLMService, "expand_prompt", failed)
    response = client.post("/api/v3/llm/test", json={})
    assert response.status_code == 502
    assert "secret-credential" not in response.text
    async def timeout(*args, **kwargs):
        raise TimeoutError()
    monkeypatch.setattr(LLMService, "expand_prompt", timeout)
    assert client.post("/api/v3/llm/test", json={}).status_code == 504


def test_real_local_http_stream_and_language_contract(llm_client):
    client, _ = llm_client
    captured = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            captured.append((self.path, self.headers.get("Authorization"), body))
            content = json.dumps({"positive": "A white crane bird", "negative": "text", "warnings": []})
            event = json.dumps({"choices": [{"delta": {"content": content}, "finish_reason": None}]})
            output = ("data: " + event + "\n\ndata: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(output)))
            self.end_headers()
            self.wfile.write(output)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/v1"
        assert client.put("/api/v3/llm/settings", json=settings(base_url=url)).status_code == 200
        response = client.post("/api/v3/workbench/prompt", json={"source_text": "白鹤", "excluded_text": "文字"})
        assert response.status_code == 200, response.text
        assert response.json()["negative"] == "text"
        assert client.post("/api/v3/llm/test", json={}).status_code == 200
        path, auth, body = captured[0]
        assert path == "/v1/chat/completions"
        assert auth == "Bearer test-secret-12345"
        assert body["model"] == "test-model"
        assert "请用中文回答" not in json.dumps(body, ensure_ascii=False)
        assert "temperature" not in body  # no hidden advanced sampling overrides
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("negative", ["", "text, watermark"])
def test_direct_bridge_never_injects_negative_defaults(negative):
    prepared = CandidateToV2PromptJobAdapter().prepare_direct(positive_prompt="A white crane bird", negative_prompt=negative)
    assert prepared.job.negative_prompt == negative


def test_fenced_json_supported():
    assert parse_prompt_output('```json\n{"positive":"bird", "negative":""}\n```').negative == ""


@pytest.mark.parametrize("negative", ["", "text, watermark"])
def test_rendered_workflow_preserves_reviewed_prompts_and_advanced_parameters(negative):
    from test_v2_generation_adapter import workflow_profile, remote_profile
    from anima_prompt_studio_v3.adapters.v2 import V2GenerationSettings
    from anima_prompt_studio.services.remote.workflow_renderer import WorkflowRenderer
    prepared = CandidateToV2PromptJobAdapter().prepare_direct(
        positive_prompt="A white crane bird", negative_prompt=negative, model_profile_id="anima_base_v1",
        settings=V2GenerationSettings(width=1024, height=768, steps=37, cfg=4.5, sampler="euler", scheduler="simple", seed=20260907, batch_size=2),
    )
    rendered = WorkflowRenderer().render(prepared.job, workflow_profile(), remote_profile(), prepared.checkpoint_logical_name, "test-run")
    assert rendered.workflow["6"]["inputs"]["text"] == "A white crane bird"
    assert rendered.workflow["7"]["inputs"]["text"] == negative
    assert rendered.workflow["3"]["inputs"] == {"seed": 20260907, "steps": 37, "cfg": 4.5, "sampler_name": "euler", "scheduler": "simple"}
    assert rendered.workflow["5"]["inputs"] == {"width": 1024, "height": 768, "batch_size": 2}


@pytest.mark.parametrize("model", ["mimo-v2.5", "mimo-v2.5-pro"])
def test_mimo_thinking_control(model):
    from anima_prompt_studio_v3.prompt_assistant.services.thinking_control import build_thinking_suppression
    assert build_thinking_suppression("opencode_go", model) == {"thinking": {"type": "disabled"}}
    assert build_thinking_suppression("opencode_go", model, disable_thinking=False) == {}
    assert build_thinking_suppression("opencode_go", "mimo-v2-other") == {}


def test_go_transport_identity_and_thinking_parameter(llm_client, monkeypatch):
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    from anima_prompt_studio_v3.prompt_assistant.services.core import HTTPClientPool
    monkeypatch.setattr(LLMService, "_get_config", lambda: {"provider": "opencode_go", "model": "mimo-v2.5", "base_url": "https://opencode.ai/zen/go/v1", "api_key": "fake"})
    captured = []
    def handle(request):
        captured.append(request)
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"OK"}}]}\n\ndata: [DONE]\n\n', headers={"Content-Type": "text/event-stream"})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            monkeypatch.setattr(HTTPClientPool, "get_client", lambda **kwargs: client)
            assert (await LLMService.expand_prompt("Reply OK"))["success"]
    asyncio.run(run())
    assert captured[0].headers["User-Agent"] == "AnimaPromptStudio/0.1"
    assert captured[0].headers["x-opencode-session"]
    assert json.loads(captured[0].content)["thinking"] == {"type": "disabled"}


def test_transport_does_not_swallow_timeout_cancellation(llm_client, monkeypatch):
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    from anima_prompt_studio_v3.prompt_assistant.services.core import HTTPClientPool
    monkeypatch.setattr(LLMService, "_get_config", lambda: {"provider": "opencode_go", "model": "mimo-v2.5", "base_url": "https://opencode.ai/zen/go/v1", "api_key": "fake"})
    async def handle(request):
        await asyncio.sleep(60)
        return httpx.Response(200)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            monkeypatch.setattr(HTTPClientPool, "get_client", lambda **kwargs: client)
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(LLMService.expand_prompt("Reply OK"), timeout=0.05)
    asyncio.run(run())
