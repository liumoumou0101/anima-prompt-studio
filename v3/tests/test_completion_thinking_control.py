from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from anima_prompt_studio_v3.prompt_assistant.services.completion import complete
from anima_prompt_studio_v3.prompt_assistant.services.core import HTTPClientPool
from anima_prompt_studio_v3.prompt_assistant.services.thinking_control import build_thinking_suppression


def capture_payload(monkeypatch, model, base_url, *, task="rewrite", ingest_thinking=False):
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            monkeypatch.setattr(HTTPClientPool, "get_client", lambda **kwargs: client)
            result = await complete(
                {"provider": "opencode_go", "model": model, "base_url": base_url},
                {"type": "openai_compatible", "ingest_enable_thinking": ingest_thinking},
                messages=[{"role": "user", "content": "Return OK."}], task=task,
            )
            assert result["text"] == "OK"

    asyncio.run(run())
    assert len(requests) == 1
    return requests[0]


@pytest.mark.parametrize("model", ["mimo-v2.5", "minimax-m3"])
@pytest.mark.parametrize("task", ["rewrite", "prompt_ingest", "probe", "ingest"])
def test_opencode_go_sends_both_verified_controls_when_thinking_is_disabled(model, task, monkeypatch):
    payload = capture_payload(monkeypatch, model, "https://opencode.ai/zen/go/v1", task=task)
    assert payload["thinking"] == {"type": "disabled"}
    assert payload.get("reasoning") == {"enabled": False}


@pytest.mark.parametrize("base_url", [
    "https://opencode.ai/zen/go/v1/",
    "https://opencode.ai/zen/go/v1/chat/completions",
])
def test_opencode_go_control_accepts_base_url_or_full_chat_endpoint(base_url, monkeypatch):
    payload = capture_payload(monkeypatch, "MiniMax-M3", base_url)
    assert payload["thinking"] == {"type": "disabled"}
    assert payload.get("reasoning") == {"enabled": False}


@pytest.mark.parametrize("model", ["mimo-v2.5", "minimax-m3"])
def test_opencode_go_ingest_can_still_enable_thinking(model, monkeypatch):
    payload = capture_payload(monkeypatch, model, "https://opencode.ai/zen/go/v1",
                              task="ingest", ingest_thinking=True)
    assert payload["thinking"] == {"type": "adaptive" if model == "minimax-m3" else "enabled"}
    assert payload["reasoning"] == {"enabled": True}


@pytest.mark.parametrize("base_url", [
    "https://api.minimax.io/v1",
    "https://api.xiaomimimo.com/v1",
    "https://opencode.ai.example.com/zen/go/v1",
    "https://proxy.opencode.ai/zen/go/v1",
    "http://opencode.ai/zen/go/v1",
    "https://opencode.ai:8443/zen/go/v1",
    "https://opencode.ai/zen/v1",
    "https://opencode.ai/zen/go/v10",
    "https://opencode.ai/other/zen/go/v1",
])
def test_go_specific_control_is_not_sent_to_other_endpoints(base_url, monkeypatch):
    payload = capture_payload(monkeypatch, "mimo-v2.5", base_url)
    assert payload["thinking"] == {"type": "disabled"}
    assert "reasoning" not in payload


@pytest.mark.parametrize("model", ["qwen3", "mimo-v2.5-flash",
                                  "minimax-m30", "minimax-m3-preview"])
def test_go_specific_control_is_not_guessed_for_other_models(model, monkeypatch):
    payload = capture_payload(monkeypatch, model, "https://opencode.ai/zen/go/v1")
    assert "reasoning" not in payload


@pytest.mark.parametrize("model", ["MiniMax-M3", "minimax-m3", "minimax/minimax-m3", "minimax-m3-preview"])
def test_minimax_m3_uses_native_thinking_control_without_go_override(model):
    assert build_thinking_suppression("minimax", model) == {"thinking": {"type": "disabled"}}
    assert build_thinking_suppression("minimax", model, disable_thinking=False) == {}


@pytest.mark.parametrize("model", ["MiniMax-M2.7", "MiniMax-M30", "fake-minimax-m3", "MiniMax-M3x"])
def test_minimax_m3_rule_does_not_match_other_model_names(model):
    assert build_thinking_suppression("minimax", model) == {}


def test_minimax_native_endpoint_does_not_receive_go_override(monkeypatch):
    payload = capture_payload(monkeypatch, "MiniMax-M3", "https://api.minimax.io/v1")
    assert payload["thinking"] == {"type": "disabled"}
    assert "reasoning" not in payload
