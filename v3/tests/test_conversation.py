from __future__ import annotations

import asyncio
from copy import deepcopy
import json

from fastapi.testclient import TestClient
import httpx
import pytest
from pydantic import ValidationError

from test_api import reference_db
from anima_prompt_studio_v3.api import create_api_runtime
from anima_prompt_studio_v3.api.conversation import ConversationService, TurnRequest
from anima_prompt_studio_v3.api.workspace_store import WorkspaceRevisionConflictError, WorkspaceStore
from anima_prompt_studio_v3.core.requirements import (
    Requirements, RequirementsEdit, PromptEdit, WorkbenchError,
    apply_layer_updates, apply_pin, compile_prompt, compile_state, digest, dump,
)


def requirements():
    result = dump(Requirements.empty())
    result["layers"]["subject"]["text"] = "短发侦探，右手拿信"
    return result


def edit(**updates):
    raw = requirements()
    raw.update(updates)
    return {key: raw[key] for key in ("layers", "loras")}


def llm_output(**overrides):
    return {"text": json.dumps({"touched_layers": [], "layer_updates": {},
                                "positive": "short-haired detective holding a letter in her right hand",
                                "negative": "", "warnings": [], **overrides})}


@pytest.fixture
def conversation_client(reference_db, tmp_path, monkeypatch):
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService

    captured = []
    async def fake_complete(**kwargs):
        captured.append(kwargs)
        return llm_output()
    monkeypatch.setattr(LLMService, "complete", fake_complete)
    runtime = create_api_runtime(reference_db, workspace_db=tmp_path / "workspaces.db")
    with TestClient(runtime.app, base_url="http://127.0.0.1") as client:
        client.headers["Origin"] = "http://127.0.0.1"
        exchange = client.post("/api/v3/session/exchange", json={"bootstrap_token": runtime.bootstrap_token})
        client.headers["X-Anima-Session"] = exchange.json()["session_token"]
        yield client, captured


def create(client):
    response = client.post("/api/v3/workspaces", json={"draft": {"requirements_edit": edit()}})
    assert response.status_code == 201, response.text
    return response.json()


def turn(client, workspace, **overrides):
    return client.post("/api/v3/workbench/turns", json={
        "workspace_id": workspace["id"], "revision": workspace["revision"],
        "mode": "faithful", "delta": {"text": ""}, **overrides,
    })


def test_first_compile_persists_and_restart_restores(conversation_client):
    client, captured = conversation_client
    workspace = create(client)
    response = turn(client, workspace)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["revision"] == 2
    assert saved["draft"]["requirements"]["revision"] == 1
    assert saved["draft"]["compile_state"] == "fresh"
    assert saved["draft"]["compiled"]["negative"] == ""
    assert len(saved["draft"]["conversation_events"]) == 1
    call = captured[0]
    assert call["disable_thinking"] is True and call["images"] is None
    context = json.loads(call["messages"][-1]["content"])
    assert set(context) == {"requirements", "compiled", "delta", "mode"}
    reopened = WorkspaceStore(client.app.state.workspace_store.path).get(workspace["id"])
    assert reopened["draft"] == saved["draft"]
    assert turn(client, saved).status_code == 422
    assert len(captured) == 1  # no chargeable call for fresh empty delta


def test_mode_recompile_changes_token_even_when_text_identical(conversation_client):
    client, _ = conversation_client
    first = turn(client, create(client)).json()
    second = turn(client, first, mode="expand").json()
    assert second["draft"]["compiled"]["prompt_fingerprint"] == first["draft"]["compiled"]["prompt_fingerprint"]
    assert second["draft"]["compiled"]["compiled_token"] != first["draft"]["compiled"]["compiled_token"]
    assert second["draft"]["mode"] == "expand"


def test_first_delta_populates_memory_not_only_compiled_text(conversation_client, monkeypatch):
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    client, _ = conversation_client
    empty = client.post("/api/v3/workspaces", json={"draft": {}}).json()
    # A syntactically valid prompt without any persistent requirements is not a
    # successful first conversation turn.
    rejected = turn(client, empty, delta={"text": "画一位侦探"})
    assert rejected.status_code == 422
    async def populated(**kwargs):
        return llm_output(touched_layers=["subject"], layer_updates={"subject": {"text": "一位侦探"}})
    monkeypatch.setattr(LLMService, "complete", populated)
    response = turn(client, empty, delta={"text": "画一位侦探"})
    assert response.status_code == 200
    assert response.json()["draft"]["requirements"]["layers"]["subject"]["text"] == "一位侦探"
    assert response.json()["draft"]["requirements"]["revision"] == 1


def test_legacy_save_and_read_echo_do_not_clear_or_relabel_compiled(conversation_client):
    client, _ = conversation_client
    first = turn(client, create(client)).json()
    response = client.put(f"/api/v3/workspaces/{first['id']}", json={
        "revision": first["revision"], "draft": {"positive_text": "旧词典输入"},
    })
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["draft"]["compiled"] == first["draft"]["compiled"]
    echoed = client.put(f"/api/v3/workspaces/{first['id']}", json={
        "revision": saved["revision"], "draft": saved["draft"],
    })
    assert echoed.status_code == 200, echoed.text
    assert echoed.json()["draft"]["compiled"] == first["draft"]["compiled"]


@pytest.mark.parametrize("field,value", [("compiled", None), ("requirements", None),
                                         ("reference_preset_id", "off_fake")])
def test_server_owned_fields_cannot_be_forged(conversation_client, field, value):
    client, _ = conversation_client
    saved = turn(client, create(client)).json()
    response = client.put(f"/api/v3/workspaces/{saved['id']}", json={
        "revision": saved["revision"], "draft": {field: value},
    })
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "read_only_field"
    assert client.get(f"/api/v3/workspaces/{saved['id']}").json()["revision"] == saved["revision"]


def test_input_changes_stale_but_manual_prompt_does_not_align_fingerprint(conversation_client):
    client, _ = conversation_client
    first = turn(client, create(client)).json()
    payload = edit()
    payload["layers"]["subject"]["text"] = "长发侦探"
    changed = client.put(f"/api/v3/workspaces/{first['id']}", json={
        "revision": first["revision"], "draft": {"requirements_edit": payload},
    }).json()
    assert changed["draft"]["compile_state"] == "stale"
    assert changed["draft"]["requirements"]["revision"] == 2
    attempt = client.put(f"/api/v3/workspaces/{first['id']}", json={
        "revision": changed["revision"], "draft": {"prompt_edit": {"positive": "long hair", "negative": ""}},
    })
    assert attempt.status_code == 422
    assert client.get(f"/api/v3/workspaces/{first['id']}").json()["draft"]["compile_state"] == "stale"


def test_manual_prompt_edit_uses_new_token_then_is_context_for_turn(conversation_client):
    client, captured = conversation_client
    first = turn(client, create(client)).json()
    prompt = {"positive": "my exact handwritten tag", "negative": ""}
    changed = client.put(f"/api/v3/workspaces/{first['id']}", json={
        "revision": first["revision"], "draft": {"prompt_edit": prompt},
    }).json()
    assert changed["draft"]["compiled"]["source"] == "user"
    assert changed["draft"]["compiled"]["inputs_fingerprint"] == first["draft"]["compiled"]["inputs_fingerprint"]
    assert changed["draft"]["compiled"]["compiled_token"] != first["draft"]["compiled"]["compiled_token"]
    assert turn(client, changed, delta={"text": "光线变冷"}).status_code == 200
    assert json.loads(captured[-1]["messages"][-1]["content"])["compiled"] == prompt


@pytest.mark.parametrize("bad", ["not JSON", '{"positive":"","negative":""}', '{"positive":"only"}'])
def test_failed_model_result_is_atomic(conversation_client, monkeypatch, bad):
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    client, _ = conversation_client
    before = create(client)
    async def fail(**kwargs):
        return {"text": bad}
    monkeypatch.setattr(LLMService, "complete", fail)
    result = turn(client, before, mode="expand")
    assert result.status_code == 502
    assert client.get(f"/api/v3/workspaces/{before['id']}").json() == before


def test_timeout_does_not_persist_mode_or_echo_upstream(conversation_client, monkeypatch):
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    client, _ = conversation_client
    before = create(client)
    async def timeout(**kwargs):
        raise TimeoutError("Bearer secret and complete private prompt")
    monkeypatch.setattr(LLMService, "complete", timeout)
    result = turn(client, before, mode="expand")
    assert result.status_code == 502
    assert "secret" not in result.text
    assert client.get(f"/api/v3/workspaces/{before['id']}").json() == before


def test_reset_keeps_legacy_inputs_and_does_not_need_llm(conversation_client):
    client, captured = conversation_client
    first = turn(client, create(client)).json()
    result = client.post("/api/v3/workbench/reset", json={"workspace_id": first["id"], "revision": first["revision"]})
    assert result.status_code == 200
    assert result.json()["draft"]["compiled"] is None
    assert result.json()["draft"]["requirements"] is None
    assert result.json()["draft"]["conversation_events"] == []
    assert result.json()["revision"] == first["revision"] + 1
    assert len(captured) == 1


def test_slow_turn_does_not_hold_write_lock_and_cas_rejects_late_result(tmp_path, monkeypatch):
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    store = WorkspaceStore(tmp_path / "workspaces.db")
    first = store.create("one", {"requirements_edit": edit()})
    second = store.create("two", {})
    service = ConversationService(store)

    async def run():
        started, release = asyncio.Event(), asyncio.Event()
        async def slow(**kwargs):
            started.set()
            await release.wait()
            return llm_output()
        monkeypatch.setattr(LLMService, "complete", slow)
        request = TurnRequest(workspace_id=first["id"], revision=1, delta={"text": ""})
        task = asyncio.create_task(service.turn(request))
        await started.wait()
        try:
            with pytest.raises(WorkbenchError, match="正在处理"):
                await service.turn(request)
            # Reopen the database: not a mocked lock test.
            another = WorkspaceStore(store.path)
            await asyncio.wait_for(asyncio.to_thread(another.update, second["id"], expected_revision=1,
                                                     title="saved while waiting", draft={}), timeout=2)
            another.update(first["id"], expected_revision=1, title="user edited", draft={"mode": "expand"})
        finally:
            release.set()
        with pytest.raises(WorkspaceRevisionConflictError):
            await task
        assert service.active == set()
    asyncio.run(run())
    saved = store.get(first["id"])
    assert saved["title"] == "user edited" and saved["revision"] == 2
    assert saved["draft"]["compiled"] is None


def test_cancellation_releases_turn_slot_without_write(tmp_path, monkeypatch):
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    store = WorkspaceStore(tmp_path / "workspaces.db")
    before = store.create("one", {"requirements_edit": edit()})
    service = ConversationService(store)
    async def run():
        started = asyncio.Event()
        async def waiting(**kwargs):
            started.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(LLMService, "complete", waiting)
        task = asyncio.create_task(service.turn(TurnRequest(workspace_id=before["id"], revision=1, delta={"text": ""})))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not service.active
    asyncio.run(run())
    assert store.get(before["id"]) == before


@pytest.mark.parametrize("updates,touched", [
    ({"subject": {"text": "two people"}}, []),
    ({"lighting": {"text": "cold", "locked": False}}, ["lighting"]),
    ({"composition": {"text": "close"}}, ["composition"]),
    ({"lighting": {"text": "cold"}}, ["lighting", "lighting"]),
    ({"unknown": {"text": "cold"}}, ["unknown"]),
])
def test_invalid_layer_updates_are_not_partially_applied(updates, touched):
    canonical = Requirements.model_validate(requirements())
    before = dump(canonical)
    with pytest.raises(WorkbenchError):
        apply_layer_updates(canonical, touched, updates)
    assert dump(canonical) == before


def test_pins_copy_content_preserve_locks_and_replace_resources():
    base = Requirements.model_validate(requirements())
    base.layers.subject.locked = True
    source = Requirements.empty()
    source.layers.subject.text = "two strangers"
    source.layers.style.text = "charcoal"
    source.layers.style.locked = True
    source.layers.lighting.text = "cold light"
    source.layers.lighting.include_with_style_pin = True
    result = apply_pin(base, source, "style")
    assert result.layers.subject == base.layers.subject
    assert result.layers.style.text == "charcoal" and not result.layers.style.locked
    assert result.layers.lighting.text == "cold light"
    assert not result.layers.lighting.include_with_style_pin
    whole = apply_pin(base, source, "whole_scene")
    assert whole.layers.subject == base.layers.subject
    with pytest.raises(WorkbenchError):
        apply_layer_updates(base, ["subject"], {"subject": {"text": "someone else"}})


def test_weight_order_and_controls_participate_in_stale_digest():
    from anima_prompt_studio_v3.core.requirements import RequirementLora
    canonical = Requirements.model_validate(requirements())
    canonical.loras = [RequirementLora(logical_id="a", file_name="a.safetensors"),
                       RequirementLora(logical_id="b", file_name="b.safetensors")]
    draft = {"requirements": dump(canonical), "mode": "faithful"}
    draft["compiled"] = compile_prompt(draft, PromptEdit(positive="detective", negative=""), source="llm")
    assert compile_state(draft) == "fresh"
    for mutate in (lambda d: d["requirements"]["loras"][0].update(weight=0.5),
                   lambda d: d["requirements"]["loras"].reverse(),
                   lambda d: d["requirements"]["layers"]["subject"].update(locked=True)):
        changed = deepcopy(draft)
        mutate(changed)
        assert compile_state(changed) == "stale"
    assert digest({"x": 1, "y": 2}) == digest({"y": 2, "x": 1})


@pytest.mark.parametrize("weight", [float("nan"), float("inf"), -3, 3])
def test_invalid_lora_weights_rejected(weight):
    with pytest.raises(ValidationError):
        RequirementsEdit.model_validate(edit(loras=[{"logical_id": "a", "file_name": "a", "weight": weight}]))


def test_duplicate_lora_and_unknown_contract_rejected(tmp_path):
    with pytest.raises(ValidationError):
        RequirementsEdit.model_validate(edit(loras=[{"logical_id": "a", "file_name": "a"}] * 2))
    store = WorkspaceStore(tmp_path / "workspaces.db")
    workspace = store.create("test", {})
    with store._connect() as connection:
        raw = {"requirements": {**requirements(), "contract": "anima-requirements/99"}}
        connection.execute("UPDATE workspaces SET draft_json=? WHERE id=?", (json.dumps(raw), workspace["id"]))
    with pytest.raises(WorkbenchError, match="不兼容"):
        store.get(workspace["id"])
    with store._connect() as connection:
        assert json.loads(connection.execute("SELECT draft_json FROM workspaces").fetchone()[0]) == raw


@pytest.mark.parametrize("native", [False, True])
def test_completion_transports_images_and_filters_reasoning(native, monkeypatch):
    from anima_prompt_studio_v3.prompt_assistant.services.completion import complete
    from anima_prompt_studio_v3.prompt_assistant.services.core import HTTPClientPool
    captured = []
    def handle(request):
        captured.append(request)
        if native:
            return httpx.Response(200, text=json.dumps({"message": {"content": "<think>private</think>OK"}, "done": True}) + "\n")
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"<think>private</think>OK"}}]}\n\ndata: [DONE]\n\n', headers={"Content-Type": "text/event-stream"})
    messages = [{"role": "user", "content": "analyze"}]
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            monkeypatch.setattr(HTTPClientPool, "get_client", lambda **kwargs: client)
            return await complete({"provider": "test", "model": "test", "base_url": "http://localhost:1234"},
                                  {"type": "ollama" if native else "openai_compatible", "supports_vision": True},
                                  messages=messages, images=[b"\xff\xd8jpeg"], task="ingest")
    result = asyncio.run(run())
    assert result["text"] == "OK" and result["capabilities"]["vision"]
    payload = json.loads(captured[0].content)
    user = payload["messages"][-1]
    assert ("images" in user) if native else user["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "temperature" not in payload and "options" not in payload
    assert messages == [{"role": "user", "content": "analyze"}]


def test_completion_vision_rejected_before_transport_and_no_upstream_leak(monkeypatch):
    from anima_prompt_studio_v3.prompt_assistant.services.completion import complete, CompletionError
    from anima_prompt_studio_v3.prompt_assistant.services.core import HTTPClientPool
    count = 0
    def handle(request):
        nonlocal count
        count += 1
        return httpx.Response(400, text="Bearer SECRET full private prompt")
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            monkeypatch.setattr(HTTPClientPool, "get_client", lambda **kwargs: client)
            config = {"provider": "test", "model": "test", "base_url": "http://localhost:1234"}
            with pytest.raises(ValueError):
                await complete(config, {}, messages=[{"role": "user", "content": "test"}],
                               images=[b"\xff\xd8jpeg"], task="ingest")
            assert count == 0
            with pytest.raises(CompletionError) as exc:
                await complete(config, {}, messages=[{"role": "user", "content": "test"}])
            assert "SECRET" not in str(exc.value)
            assert count == 1  # no automatic paid retry
    asyncio.run(run())


def test_completion_stops_at_split_sse_done_without_waiting_for_connection_close(monkeypatch):
    from anima_prompt_studio_v3.prompt_assistant.services.completion import complete
    from anima_prompt_studio_v3.prompt_assistant.services.core import HTTPClientPool
    closed = []

    class HeldOpenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"OK"}}]}\r\n\r\ndata: [DO'
            yield b'NE]\r\n\r\n'
            pytest.fail("completion must not wait for another chunk after DONE")

        async def aclose(self):
            closed.append(True)

    async def run():
        def handle(request):
            return httpx.Response(200, stream=HeldOpenStream(), headers={"Content-Type":"text/event-stream"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            monkeypatch.setattr(HTTPClientPool, "get_client", lambda **kwargs: client)
            return await complete({"provider":"test","model":"test","base_url":"http://localhost:1234"},
                                  {}, messages=[{"role":"user","content":"test"}], task="rewrite")

    assert asyncio.run(run())["text"] == "OK"
    assert closed == [True]


@pytest.mark.parametrize("status,body,reason", [
    (401, "Bearer SECRET private prompt", "upstream_http_error"),
    (429, "private prompt", "upstream_http_error"),
    (400, "GLM-5.3 is a thinking-only model; disabling thinking is not supported. SECRET", "thinking_disable_unsupported"),
    (200, "not JSON SECRET", "invalid_response"),
])
def test_completion_safe_diagnostics_do_not_leak_or_retry(status, body, reason, monkeypatch):
    from anima_prompt_studio_v3.prompt_assistant.services.completion import complete, CompletionError
    from anima_prompt_studio_v3.prompt_assistant.services.core import HTTPClientPool
    calls = []
    def handle(request):
        calls.append(True)
        return httpx.Response(status, text=body)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            monkeypatch.setattr(HTTPClientPool, "get_client", lambda **kwargs: client)
            with pytest.raises(CompletionError) as exc:
                await complete({"provider": "test", "model": "test", "base_url": "https://example.com/v1"},
                               {}, messages=[{"role": "user", "content": "private prompt"}])
            assert exc.value.safe_details == {"reason": reason, **({"upstream_status": status} if status != 200 else {})}
            assert "SECRET" not in str(exc.value)
            assert "private prompt" not in str(exc.value)
    asyncio.run(run())
    assert calls == [True]


@pytest.mark.parametrize("error", [httpx.ReadTimeout("SECRET"), httpx.ConnectError("SECRET")])
def test_completion_distinguishes_timeout_from_transport_error(error, monkeypatch):
    from anima_prompt_studio_v3.prompt_assistant.services.completion import complete, CompletionError
    from anima_prompt_studio_v3.prompt_assistant.services.core import HTTPClientPool
    def handle(request):
        raise error
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            monkeypatch.setattr(HTTPClientPool, "get_client", lambda **kwargs: client)
            expected = TimeoutError if isinstance(error, httpx.TimeoutException) else CompletionError
            with pytest.raises(expected) as exc:
                await complete({"provider": "test", "model": "test", "base_url": "https://example.com/v1"},
                               {}, messages=[{"role": "user", "content": "test"}])
            assert "SECRET" not in str(exc.value)
            if isinstance(exc.value, CompletionError):
                assert exc.value.reason == "transport_error"
    asyncio.run(run())


def test_upstream_parameter_rejection_is_not_retryable(conversation_client, monkeypatch):
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    from anima_prompt_studio_v3.prompt_assistant.services.completion import CompletionError
    client, _ = conversation_client
    async def reject(**kwargs):
        raise CompletionError("SECRET", reason="thinking_disable_unsupported", upstream_status=400)
    monkeypatch.setattr(LLMService, "complete", reject)
    workspace = create(client)
    response = turn(client, workspace)
    assert response.status_code == 502
    assert response.json()["error"]["retryable"] is False
    assert response.json()["error"]["details"] == {"reason": "thinking_disable_unsupported", "upstream_status": 400}
    assert "SECRET" not in response.text
    assert client.get('/api/v3/workspaces/' + workspace['id']).json()['draft'] == workspace['draft']


@pytest.mark.parametrize("task,ingest_enabled,expected", [("rewrite", True, True), ("probe", True, True),
                                                         ("ingest", True, False), ("ingest", False, True),
                                                         ("prompt_ingest", True, True)])
def test_task_owns_thinking_override(task, ingest_enabled, expected, monkeypatch):
    from anima_prompt_studio_v3.prompt_assistant.services import completion
    seen = []
    def control(provider, model, disable_thinking):
        seen.append(disable_thinking)
        return {}
    def handle(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
    monkeypatch.setattr(completion, "build_thinking_suppression", control)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            monkeypatch.setattr(completion.HTTPClientPool, "get_client", lambda **kwargs: client)
            await completion.complete({"provider": "test", "model": "test", "base_url": "http://localhost:1234"},
                                      {"ingest_enable_thinking": ingest_enabled},
                                      messages=[{"role": "user", "content": "test"}],
                                      task=task, disable_thinking=False)
    asyncio.run(run())
    assert seen == [expected]


@pytest.mark.parametrize("model", ["glm-5.3", "GLM-5.3-FLASH", "z-ai/glm-5.3"])
def test_reasoning_only_glm_rejected_before_paid_request(model, monkeypatch):
    from anima_prompt_studio_v3.prompt_assistant.services.completion import complete
    from anima_prompt_studio_v3.prompt_assistant.services.core import HTTPClientPool
    from anima_prompt_studio_v3.prompt_assistant.services.thinking_control import build_thinking_suppression
    monkeypatch.setattr(HTTPClientPool, "get_client", lambda **kwargs: pytest.fail("must not call provider"))
    assert build_thinking_suppression("opencode", model) == {}
    for task in ("rewrite", "prompt_ingest", "probe", "ingest"):
        with pytest.raises(WorkbenchError) as exc:
            asyncio.run(complete({"provider": "opencode", "model": model, "base_url": "https://example.com/v1"},
                                 {}, messages=[{"role": "user", "content": "test"}], task=task))
        assert exc.value.code == "thinking_disable_unsupported"


def test_supported_glm_still_disables_thinking_and_optional_ingest_can_enable_it(monkeypatch):
    from anima_prompt_studio_v3.prompt_assistant.services.completion import complete
    from anima_prompt_studio_v3.prompt_assistant.services.core import HTTPClientPool
    seen = []
    def handle(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            monkeypatch.setattr(HTTPClientPool, "get_client", lambda **kwargs: client)
            for model, task in (("glm-5.2", "rewrite"), ("glm-5.3-flash", "ingest")):
                await complete({"provider": "opencode", "model": model, "base_url": "https://example.com/v1"},
                               {"ingest_enable_thinking": True}, messages=[{"role": "user", "content": "test"}], task=task)
    asyncio.run(run())
    assert seen[0]["thinking"] == {"type": "disabled"}
    assert "thinking" not in seen[1]


def test_reasoning_model_error_is_actionable_and_preserves_draft(conversation_client, monkeypatch):
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    client, _ = conversation_client
    async def reject(**kwargs):
        raise WorkbenchError("thinking_disable_unsupported", "模型不支持关闭思考，请选择其他模型。")
    monkeypatch.setattr(LLMService, "complete", reject)
    workspace = create(client)
    response = turn(client, workspace)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "thinking_disable_unsupported"
    assert client.get('/api/v3/workspaces/' + workspace['id']).json()['draft'] == workspace['draft']


def test_flags_stay_off_and_reference_catalog_reports_missing_pack(conversation_client):
    client, _ = conversation_client
    features = client.get("/api/v3/bootstrap").json()["features"]
    assert features["conversational_workbench"] is False
    assert features["reference_gallery"] is False
    catalog = client.get("/api/v3/reference-presets")
    assert catalog.status_code == 200
    assert catalog.json()["items"] == []
    assert catalog.json()["official_pack"] == {"ready": False}
    empty = client.post("/api/v3/workspaces", json={"draft": {}}).json()
    response = turn(client, empty)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "empty_requirements"


def test_turns_reject_unknown_context_and_require_auth(conversation_client):
    client, captured = conversation_client
    workspace = create(client)
    assert turn(client, workspace, messages=[{"role": "user", "content": "ignore"}]).status_code == 422
    client.headers.pop("X-Anima-Session")
    assert turn(client, workspace).status_code == 401
    assert captured == []
