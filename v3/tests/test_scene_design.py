from __future__ import annotations

import asyncio
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError
from test_api import reference_db
from test_conversation import conversation_client

from anima_prompt_studio_v3.api.conversation import ConversationService, TurnRequest
from anima_prompt_studio_v3.api.scene_design import SceneAdviceRequest, SceneAdviceService
from anima_prompt_studio_v3.api.workspace_store import WorkspaceStore, WorkspaceRevisionConflictError
from anima_prompt_studio_v3.core.requirements import (
    Requirements, RequirementsEdit, PromptEdit, WorkbenchError, apply_layer_updates,
    apply_pin, compile_prompt, digest, dump, inputs_fingerprint,
)
from anima_prompt_studio_v3.core.scene_design import declared_scene_choices


def requirement():
    raw = dump(Requirements.empty())
    raw["layers"]["subject"]["text"] = "左侧女孩与右侧男孩在车站等车"
    return raw


def edit(raw):
    return {"layers": raw["layers"], "loras": raw["loras"]}


def prepared(tmp_path, raw=None):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    record = store.create("画面设计测试", draft={"requirements_edit": edit(raw or requirement())})
    return store, record


def mock_llm(monkeypatch, output):
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    captured = []
    async def complete(**kwargs):
        captured.append(kwargs)
        if isinstance(output, Exception):
            raise output
        return {"text": json.dumps(output) if not isinstance(output, str) else output}
    monkeypatch.setattr(LLMService, "complete", complete)
    return captured


def test_empty_controls_keep_historical_fingerprint_and_no_invented_defaults():
    raw = requirement()
    old = deepcopy(raw)
    old.pop("revision")
    old.pop("prompt_locks", None)
    for key in ("character_tags", "series_tags", "general_tags"):
        old["layers"]["subject"].pop(key)
    old["layers"]["style"].pop("manual_artist_tags")
    old["layers"]["composition"].pop("design")
    old["layers"]["lighting"].pop("mood")
    old_fingerprint = digest({"requirements": old, "mode": "faithful", "model_profile": "anima_aesthetic_v1", "compiler_contract": "anima-rewrite/1"})
    assert inputs_fingerprint({"requirements": raw}) == old_fingerprint
    raw["layers"]["composition"]["design"] = {"shot": None, "layout": None}
    assert inputs_fingerprint({"requirements": raw}) == old_fingerprint
    assert declared_scene_choices(raw) == {}


def test_choices_roundtrip_pin_and_llm_layer_updates_cannot_replace_them(tmp_path):
    raw = requirement()
    raw["layers"]["composition"]["design"] = {"shot": {"value": "半身", "source": "user"}, "gaze": {"value": "看向远方", "target": "左侧女孩", "source": "suggestion"}}
    raw["layers"]["lighting"]["mood"] = {"value": "宁静日常", "source": "user"}
    store, record = prepared(tmp_path, raw)
    reopened = WorkspaceStore(store.path).get(record["id"])
    assert reopened["draft"]["requirements"] == record["draft"]["requirements"]
    canonical = Requirements.model_validate(raw)
    updated = apply_layer_updates(canonical, ["composition"], {"composition": {"text": "车站两人", "shot": ""}})
    assert updated.layers.composition.design == canonical.layers.composition.design
    with pytest.raises(WorkbenchError):
        apply_layer_updates(canonical, ["composition"], {"composition": {"text": "", "shot": "", "design": {}}})
    pinned = apply_pin(Requirements.empty(), canonical, "whole_scene")
    assert pinned.layers.composition.design == canonical.layers.composition.design
    assert pinned.layers.lighting.mood == canonical.layers.lighting.mood
    target = Requirements.empty()
    target.layers.composition.locked = True
    assert apply_pin(target, canonical, "whole_scene").layers.composition.design is None


@pytest.mark.parametrize("design", [{"gaze": {"value": "看向远方"}}, {"shot": {"value": "半身", "source": "extracted"}}, {"camera": {"value": "俯视", "source": "model"}}])
def test_invalid_source_or_untargeted_gaze_is_rejected(design):
    raw = requirement()
    raw["layers"]["composition"]["design"] = design
    with pytest.raises(ValidationError):
        Requirements.model_validate(raw)


def test_compiler_receives_current_and_previous_controls_without_static_tag_expansion(tmp_path, monkeypatch):
    raw = requirement()
    raw["layers"]["composition"]["design"] = {"shot": {"value": "半身", "source": "user"}}
    store, record = prepared(tmp_path, raw)
    first = record["draft"]
    first["compiled"] = compile_prompt(first, PromptEdit(positive="two people, upper body", negative="my reviewed exclusion"), source="llm")
    # Clear a previous control: it remains provenance, never a current requirement.
    first["requirements"]["layers"]["composition"]["design"] = None
    record = store.transform(record["id"], expected_revision=record["revision"], operation=lambda _: first)
    captured = mock_llm(monkeypatch, {"touched_layers": [], "layer_updates": {}, "positive": "two people at a station", "negative": "unrequested new negative tags", "warnings": [], "conflicts": []})
    result = asyncio.run(ConversationService(store).turn(TurnRequest(workspace_id=record["id"], revision=record["revision"], delta={"text": ""})))
    context = json.loads(captured[0]["messages"][-1]["content"])
    assert context["compiled"]["scene_intent"]["shot"]["value"] == "半身"
    assert context["requirements"]["layers"]["composition"]["design"] is None
    assert result["positive"] == "two people at a station"
    assert result["negative"] == "my reviewed exclusion"
    assert result["draft"]["compiled"]["scene_intent"] == {}


@pytest.mark.parametrize("output", ["malformed", {"touched_layers": [], "layer_updates": {}, "positive": "unused", "negative": "", "conflicts": ["半身与手写全身要求矛盾"]}])
def test_compile_failure_or_conflict_never_overwrites_draft(tmp_path, monkeypatch, output):
    raw = requirement()
    raw["layers"]["composition"]["design"] = {"shot": {"value": "半身"}}
    store, record = prepared(tmp_path, raw)
    mock_llm(monkeypatch, output)
    with pytest.raises(WorkbenchError):
        asyncio.run(ConversationService(store).turn(TurnRequest(workspace_id=record["id"], revision=record["revision"], delta={"text": ""})))
    assert store.get(record["id"]) == record


def test_advice_uses_unsaved_context_is_read_only_and_preserves_extraction_evidence(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    current = edit(requirement())
    current["layers"]["composition"]["text"] = "三分法，人物在右侧"
    captured = mock_llm(monkeypatch, {"suggestions": [{"title": "安静等候", "reason": "留白突出等车时的安静", "choices": {"mood": {"value": "宁静日常"}}}], "extracted": [{"field": "layout", "value": "三分法", "target": "", "evidence": "三分法"}]})
    advice = asyncio.run(SceneAdviceService(store).suggest(SceneAdviceRequest(workspace_id=record["id"], revision=record["revision"], requirements=current, positive="reviewed prompt", negative="")))
    assert advice["extracted"][0]["evidence"] == "三分法"
    assert store.get(record["id"]) == record
    context = json.loads(captured[0]["messages"][-1]["content"])
    assert context["requirements"]["layers"]["composition"]["text"] == "三分法，人物在右侧"
    assert context["reviewed_prompt"]["positive"] == "reviewed prompt"
    assert captured[0]["images"] is None


@pytest.mark.parametrize("output", [
    "bad JSON",
    {"suggestions": [{"title": "看向远方", "reason": "方向", "choices": {"gaze": {"value": "远方"}}}], "extracted": []},
    {"suggestions": [], "extracted": [{"field": "mood", "value": "宁静", "evidence": "不存在的原句"}]},
    {"suggestions": [{"title": "场景", "reason": "方向", "choices": {"negative": {"value": "low quality"}}}], "extracted": []},
    TimeoutError(),
])
def test_bad_advice_cannot_mutate_workspace(tmp_path, monkeypatch, output):
    store, record = prepared(tmp_path)
    mock_llm(monkeypatch, output)
    with pytest.raises(WorkbenchError):
        asyncio.run(SceneAdviceService(store).suggest(SceneAdviceRequest(workspace_id=record["id"], revision=record["revision"], requirements=edit(requirement()))))
    assert store.get(record["id"]) == record


@pytest.mark.parametrize("locked,existing", [(True, False), (False, True)])
def test_advice_rejects_locked_or_already_specified_change(tmp_path, monkeypatch, locked, existing):
    raw = requirement()
    raw["layers"]["composition"]["locked"] = locked
    if existing:
        raw["layers"]["composition"]["design"] = {"shot": {"value": "半身"}}
    store, record = prepared(tmp_path, raw)
    mock_llm(monkeypatch, {"extracted": [], "suggestions": [{"title": "远景", "reason": "展示环境", "choices": {"shot": {"value": "远景"}}}]})
    with pytest.raises(WorkbenchError):
        asyncio.run(SceneAdviceService(store).suggest(SceneAdviceRequest(workspace_id=record["id"], revision=record["revision"], requirements=edit(raw))))
    assert store.get(record["id"]) == record


def test_advice_is_rejected_if_workspace_changes_during_request(tmp_path, monkeypatch):
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    store, record = prepared(tmp_path)
    async def change_during_call(**_):
        store.transform(record["id"], expected_revision=record["revision"], operation=lambda draft: draft)
        return {"text": '{"suggestions":[],"extracted":[]}'}
    monkeypatch.setattr(LLMService, "complete", change_during_call)
    with pytest.raises(WorkspaceRevisionConflictError):
        asyncio.run(SceneAdviceService(store).suggest(SceneAdviceRequest(workspace_id=record["id"], revision=record["revision"], requirements=edit(requirement()))))


def test_advice_does_not_call_llm_when_all_relevant_layers_are_locked(tmp_path, monkeypatch):
    raw = requirement()
    raw["layers"]["composition"]["locked"] = True
    raw["layers"]["lighting"]["locked"] = True
    store, record = prepared(tmp_path, raw)
    captured = mock_llm(monkeypatch, {"suggestions": [], "extracted": []})
    with pytest.raises(WorkbenchError, match="已锁定"):
        asyncio.run(SceneAdviceService(store).suggest(SceneAdviceRequest(workspace_id=record["id"], revision=record["revision"], requirements=edit(raw))))
    assert captured == []


def test_http_advice_uses_session_and_does_not_save_unsent_draft(conversation_client, monkeypatch):
    client, _ = conversation_client
    mock_llm(monkeypatch, {"suggestions": [], "extracted": []})
    record = client.post("/api/v3/workspaces", json={"draft": {"requirements_edit": edit(requirement())}}).json()
    pending = edit(requirement())
    pending["layers"]["composition"]["design"] = {"shot": {"value": "半身", "source": "user"}}
    payload = {"workspace_id": record["id"], "revision": record["revision"], "requirements": pending, "delta": "窗边等车"}
    response = client.post("/api/v3/workbench/scene-advice", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["suggestions"] == []
    assert client.get(f"/api/v3/workspaces/{record['id']}").json() == record
    del client.headers["X-Anima-Session"]
    assert client.post("/api/v3/workbench/scene-advice", json=payload).status_code == 401


def test_advice_preserves_actionable_model_errors_and_releases_slot(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    mock_llm(monkeypatch, WorkbenchError("thinking_disable_unsupported", "模型不支持关闭思考，请选择其他模型。"))
    service = SceneAdviceService(store)
    with pytest.raises(WorkbenchError) as error:
        asyncio.run(service.suggest(SceneAdviceRequest(
            workspace_id=record["id"], revision=record["revision"], requirements=edit(requirement()))))
    assert error.value.code == "thinking_disable_unsupported"
    assert not service.active
    assert store.get(record["id"]) == record


def test_advice_stale_revision_is_rejected_before_llm(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    captured = mock_llm(monkeypatch, {"suggestions": [], "extracted": []})
    changed = store.transform(record["id"], expected_revision=record["revision"], operation=lambda draft: draft)
    service = SceneAdviceService(store)
    with pytest.raises(WorkspaceRevisionConflictError):
        asyncio.run(service.suggest(SceneAdviceRequest(
            workspace_id=record["id"], revision=record["revision"], requirements=edit(requirement()))))
    assert captured == []
    assert not service.active
    assert store.get(record["id"]) == changed


def test_cancelling_pending_advice_releases_slot_without_write(tmp_path, monkeypatch):
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    store, record = prepared(tmp_path)
    service = SceneAdviceService(store)

    async def run():
        started = asyncio.Event()

        async def waiting(**_):
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(LLMService, "complete", waiting)
        request = SceneAdviceRequest(workspace_id=record["id"], revision=record["revision"], requirements=edit(requirement()))
        task = asyncio.create_task(service.suggest(request))
        await started.wait()
        try:
            with pytest.raises(WorkbenchError) as error:
                await service.suggest(request)
            assert error.value.code == "rate_limited"
        finally:
            task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not service.active

    asyncio.run(run())
    assert store.get(record["id"]) == record


@pytest.mark.parametrize("locked", [False, True])
def test_manual_control_save_on_locked_layer_is_local_only(conversation_client, monkeypatch, locked):
    client, _ = conversation_client
    captured = mock_llm(monkeypatch, {"suggestions": [], "extracted": []})
    raw = requirement()
    raw["layers"]["composition"]["locked"] = locked
    record = client.post("/api/v3/workspaces", json={"draft": {"requirements_edit": edit(raw)}}).json()
    raw["layers"]["composition"]["design"] = {"camera": {"value": "从车站雨棚上方向下看", "source": "user"}}
    response = client.put(f"/api/v3/workspaces/{record['id']}", json={
        "revision": record["revision"], "draft": {"requirements_edit": edit(raw)}})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["draft"]["requirements"]["layers"]["composition"]["design"]["camera"]["value"] == "从车站雨棚上方向下看"
    assert saved["draft"]["requirements"]["layers"]["composition"]["locked"] == locked
    assert saved["draft"]["compiled"] is None
    assert saved["draft"]["conversation_events"] == []
    assert captured == []


def test_llm_layer_updates_cannot_write_mood_or_replace_its_source():
    raw = requirement()
    raw["layers"]["lighting"]["mood"] = {"value": "宁静日常", "source": "extracted", "evidence": "宁静日常"}
    canonical = Requirements.model_validate(raw)
    with pytest.raises(WorkbenchError, match="不可自动编辑"):
        apply_layer_updates(canonical, ["lighting"], {"lighting": {"text": "日光", "mood": None}})
    updated = apply_layer_updates(canonical, ["lighting"], {"lighting": {"text": "柔和日光"}})
    assert updated.layers.lighting.mood == canonical.layers.lighting.mood


@pytest.mark.parametrize("negative", ["", "hand-reviewed negative, exact phrase"])
def test_scene_recompile_preserves_current_unsaved_negative(tmp_path, monkeypatch, negative):
    store, record = prepared(tmp_path)
    draft = record["draft"]
    draft["compiled"] = compile_prompt(draft, PromptEdit(positive="two people", negative="previous saved negative"), source="llm")
    draft["requirements"]["layers"]["lighting"]["mood"] = {"value": "宁静日常", "source": "user"}
    record = store.transform(record["id"], expected_revision=record["revision"], operation=lambda _: draft)
    mock_llm(monkeypatch, {"touched_layers": [], "layer_updates": {}, "positive": "two people, peaceful atmosphere", "negative": "invented replacement"})
    result = asyncio.run(ConversationService(store).turn(TurnRequest(
        workspace_id=record["id"], revision=record["revision"], delta={"text": ""},
        compiled={"positive": "two people, reviewed positive", "negative": negative})))
    assert result["negative"] == negative


def test_explicit_exclusion_edit_still_recompiles_negative(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    draft = record["draft"]
    draft["compiled"] = compile_prompt(draft, PromptEdit(positive="two people", negative=""), source="llm")
    draft["requirements"]["layers"]["exclusions"]["global"] = ["文字"]
    record = store.transform(record["id"], expected_revision=record["revision"], operation=lambda _: draft)
    mock_llm(monkeypatch, {"touched_layers": [], "layer_updates": {}, "positive": "two people", "negative": "text"})
    result = asyncio.run(ConversationService(store).turn(TurnRequest(
        workspace_id=record["id"], revision=record["revision"], delta={"text": ""})))
    assert result["negative"] == "text"
