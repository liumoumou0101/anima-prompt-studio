from __future__ import annotations

from copy import deepcopy

import pytest

from test_llm_workbench import llm_client, reference_db, settings


@pytest.fixture(autouse=True)
def capability_stub(monkeypatch):
    from anima_prompt_studio_v3.prompt_assistant.services import thinking_control

    calls = []
    result = {"mode": "unverified", "message": "此模型的思考控制尚未验证。"}

    def capability(provider, model, *, base_url=""):
        calls.append((provider, model, base_url))
        return result.copy()

    monkeypatch.setattr(thinking_control, "get_thinking_capability", capability, raising=False)
    return calls, result


def test_missing_workbench_thinking_preference_defaults_to_off(llm_client):
    client, _ = llm_client
    assert client.put("/api/v3/llm/settings", json=settings()).status_code == 200
    response = client.get("/api/v3/llm/settings")
    assert response.status_code == 200
    payload = response.json()
    assert payload["current"].get("workbench_enable_thinking") is False
    assert all(service.get("workbench_enable_thinking") is False for service in payload["services"])
    assert "test-secret-12345" not in response.text


@pytest.mark.parametrize("enabled", [True, False])
def test_quick_toggle_persists_without_changing_model_key_or_other_settings(llm_client, enabled):
    client, manager = llm_client
    assert client.put("/api/v3/llm/settings", json=settings(
        supports_vision=True, ingest_enable_thinking=True)).status_code == 200
    assert client.put("/api/v3/llm/settings", json=settings(
        model_name="selected-nondefault-model", api_key=None)).status_code == 200
    before = manager.load_config()
    custom = next(service for service in before["model_services"] if service["id"] == "custom")
    custom["workbench_enable_thinking"] = not enabled
    manager.save_config(before)

    response = client.put("/api/v3/llm/settings", json={
        "service_id": "custom", "model_name": "selected-nondefault-model",
        "workbench_enable_thinking": enabled,
    })
    assert response.status_code == 200, response.text
    expected = deepcopy(before)
    next(service for service in expected["model_services"] if service["id"] == "custom")["workbench_enable_thinking"] = enabled
    assert manager.load_config() == expected

    from anima_prompt_studio_v3.prompt_assistant.config_manager import ConfigManager

    reloaded = ConfigManager()
    assert reloaded.get_service("custom")["workbench_enable_thinking"] is enabled
    assert reloaded.get_llm_config()["model"] == "selected-nondefault-model"
    assert reloaded.get_llm_config()["api_key"] == "test-secret-12345"
    response = client.get("/api/v3/llm/settings")
    assert response.json()["current"]["workbench_enable_thinking"] is enabled
    assert next(service for service in response.json()["services"] if service["id"] == "custom")["workbench_enable_thinking"] is enabled
    assert "test-secret-12345" not in response.text


def test_omitting_workbench_thinking_preserves_saved_preference(llm_client):
    client, manager = llm_client
    assert client.put("/api/v3/llm/settings", json=settings(workbench_enable_thinking=True)).status_code == 200
    assert client.put("/api/v3/llm/settings", json={
        "service_id": "custom", "model_name": "another-model",
    }).status_code == 200
    assert manager.get_service("custom")["workbench_enable_thinking"] is True
    assert client.get("/api/v3/llm/settings").json()["current"]["workbench_enable_thinking"] is True


@pytest.mark.parametrize("mode", ["switchable", "required", "unverified"])
def test_current_settings_expose_model_capability_without_secrets(llm_client, capability_stub, mode):
    client, _ = llm_client
    calls, capability = capability_stub
    capability.update(mode=mode, message="当前模型能力说明。")
    assert client.put("/api/v3/llm/settings", json=settings(
        base_url="https://opencode.ai/zen/go/v1", model_name="mimo-v2.5")).status_code == 200
    response = client.get("/api/v3/llm/settings")
    assert response.status_code == 200
    assert response.json()["current"].get("thinking") == {"mode": mode, "message": "当前模型能力说明。"}
    assert calls[-1] == ("custom", "mimo-v2.5", "https://opencode.ai/zen/go/v1")
    assert "test-secret-12345" not in response.text


@pytest.mark.parametrize("enabled", [True, False])
def test_required_model_still_allows_saving_either_preference(llm_client, capability_stub, enabled):
    client, _ = llm_client
    _, capability = capability_stub
    capability.update(mode="required", message="此模型必须启用思考。")
    response = client.put("/api/v3/llm/settings", json=settings(
        model_name="glm-5.3", workbench_enable_thinking=enabled))
    assert response.status_code == 200, response.text
    current = client.get("/api/v3/llm/settings").json()["current"]
    assert current["workbench_enable_thinking"] is enabled
    assert current["thinking"]["mode"] == "required"


@pytest.mark.parametrize("base_url,provider", [
    ("http://127.0.0.1:11434", "ollama"),
    ("http://127.0.0.1:11434/v1", "custom"),
])
def test_capability_uses_same_ollama_protocol_as_completion(llm_client, capability_stub, base_url, provider):
    client, _ = llm_client
    calls, _ = capability_stub
    assert client.put("/api/v3/llm/settings", json=settings(
        service_type="ollama", base_url=base_url, model_name="qwen3", api_key=None)).status_code == 200
    assert client.get("/api/v3/llm/settings").status_code == 200
    assert calls == [(provider, "qwen3", base_url)]
