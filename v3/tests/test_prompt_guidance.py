"""Exercise guidance routing at the real workspace/LLM boundary, without paid calls."""
import asyncio
from copy import deepcopy
import json

import pytest

from anima_prompt_studio_v3.api.conversation import ConversationService, TurnRequest
from anima_prompt_studio_v3.api.workspace_store import WorkspaceStore
from anima_prompt_studio_v3.core.requirements import (
    PromptEdit, Requirements, compile_prompt, compile_state, dump,
)
from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService


def workspace(tmp_path, model="anima_aesthetic_v1_1"):
    store = WorkspaceStore(tmp_path / "guidance.db")
    requirements = dump(Requirements.empty())
    requirements["layers"]["subject"]["text"] = "星空下草地上的黑发校服少女，全身"
    record = store.create("night", {"model_profile": model, "requirements_edit": {
        "layers": requirements["layers"], "loras": [],
    }})
    return store, record


def capture_transport(monkeypatch, *, positive="1girl, black hair, school uniform, full body, grass, starry sky", warnings=()):
    calls = []

    async def complete(**kwargs):
        calls.append(deepcopy(kwargs))
        return {"text": json.dumps({"touched_layers": [], "layer_updates": {},
                                   "positive": positive, "negative": "", "warnings": list(warnings)})}

    monkeypatch.setattr(LLMService, "complete", complete)
    return calls


def rewrite(store, record, **changes):
    return asyncio.run(ConversationService(store).turn(TurnRequest(
        workspace_id=record["id"], revision=record["revision"], delta={"text": ""}, **changes)))


@pytest.mark.parametrize("model,variant,prefix,avoid", [
    ("anima_base_v1", "base", ["score_7"], []),
    ("anima_aesthetic_v1_0", "aesthetic", [], ["score_*"]),
    ("anima_aesthetic_v1_1", "aesthetic", [], ["score_*"]),
    ("anima_turbo_v1_1", "turbo", ["score_7"], []),
    ("animayume_v1_5_base", "community", [], []),
])
def test_rewrite_sends_selected_profile_guidance_without_inserting_quality_tags(
    tmp_path, monkeypatch, model, variant, prefix, avoid,
):
    store, record = workspace(tmp_path, model)
    calls = capture_transport(monkeypatch)
    saved = rewrite(store, record)
    context = json.loads(calls[0]["messages"][-1]["content"])
    guidance = context["model_guidance"]
    assert guidance["profile_id"] == model
    assert guidance["variant"] == variant
    assert guidance["optional_positive_prefix"] == prefix
    assert guidance["avoid_adding"] == avoid
    assert saved["positive"] == "1girl, black hair, school uniform, full body, grass, starry sky"
    assert saved["negative"] == ""
    assert saved["draft"]["compiled"]["guidance_version"] == guidance["version"]
    assert saved["draft"]["requirements"] == record["draft"]["requirements"]


def test_unknown_model_does_not_infer_aesthetic_rules_from_its_name(tmp_path, monkeypatch):
    store, record = workspace(tmp_path, "custom_aesthetic_v99")
    calls = capture_transport(monkeypatch)
    rewrite(store, record)
    guidance = json.loads(calls[0]["messages"][-1]["content"])["model_guidance"]
    assert guidance["profile_id"] == "custom_aesthetic_v99"
    assert guidance["variant"] == "unknown"
    assert guidance["optional_positive_prefix"] == []
    assert guidance["avoid_adding"] == []


def test_legacy_workspace_without_model_uses_existing_default(tmp_path, monkeypatch):
    store, template = workspace(tmp_path)
    record = store.create("legacy", {"requirements_edit": {
        "layers": template["draft"]["requirements"]["layers"], "loras": [],
    }})
    calls = capture_transport(monkeypatch)
    saved = rewrite(store, record)
    guidance = json.loads(calls[0]["messages"][-1]["content"])["model_guidance"]
    assert guidance["profile_id"] == "anima_aesthetic_v1"
    assert saved["draft"]["compile_state"] == "fresh"


def test_model_switch_updates_guidance_on_next_rewrite(tmp_path, monkeypatch):
    store, record = workspace(tmp_path)
    calls = capture_transport(monkeypatch)
    first = rewrite(store, record)
    changed = store.update(first["id"], expected_revision=first["revision"], title="night",
                           draft={"model_profile": "anima_turbo_v1_1"})
    assert changed["draft"]["compiled"]["positive"] == first["positive"]
    assert changed["draft"]["compile_state"] == "stale"
    second = rewrite(store, changed)
    assert json.loads(calls[-1]["messages"][-1]["content"])["model_guidance"]["profile_id"] == "anima_turbo_v1_1"
    assert second["draft"]["compile_state"] == "fresh"


def test_mode_selection_sends_distinct_task_without_fabricating_user_delta(tmp_path, monkeypatch):
    store, record = workspace(tmp_path)
    calls = capture_transport(monkeypatch)
    first = rewrite(store, record)
    second = rewrite(store, first, mode="expand")
    faithful = json.loads(calls[0]["messages"][-1]["content"])
    expanded = json.loads(calls[1]["messages"][-1]["content"])
    assert faithful["rewrite_goal"] and expanded["rewrite_goal"]
    assert faithful["rewrite_goal"] != expanded["rewrite_goal"]
    assert faithful["delta"] == expanded["delta"] == {"kind": "user_text", "text": ""}
    assert second["draft"]["conversation_events"][-1]["delta"] == ""


def test_expansion_can_save_lighting_prose_and_review_notes_without_inventing_requirements(tmp_path, monkeypatch):
    store, record = workspace(tmp_path)
    expanded = "1girl, black hair, school uniform, full body. Soft moonlight reaches her face and collar beneath the dark starry sky."
    notes = ["补充了月光照到脸部与衣领的细节，保留夜色。"]
    capture_transport(monkeypatch, positive=expanded, warnings=notes)
    saved = rewrite(store, record, mode="expand")
    assert saved["positive"] == expanded
    assert saved["warnings"] == notes
    assert saved["draft"]["conversation_events"][-1]["warnings"] == notes
    assert saved["draft"]["requirements"] == record["draft"]["requirements"]
    assert WorkspaceStore(store.path).get(saved["id"])["draft"] == saved["draft"]


def test_legacy_llm_prompt_can_be_refreshed_without_replacing_it_on_load(tmp_path, monkeypatch):
    store, record = workspace(tmp_path)
    draft = deepcopy(record["draft"])
    draft["compiled"] = compile_prompt(draft, PromptEdit(positive="reviewed night scene", negative=""), source="llm")
    draft["compiled"].pop("guidance_version", None)
    record = store.transform(record["id"], expected_revision=record["revision"], operation=lambda _: draft)
    assert record["draft"]["compiled"]["positive"] == "reviewed night scene"
    assert record["draft"]["compile_state"] == "stale"
    calls = capture_transport(monkeypatch, positive="reviewed night scene")
    saved = rewrite(store, record)
    assert len(calls) == 1
    assert saved["draft"]["compile_state"] == "fresh"
    assert saved["draft"]["compiled"]["guidance_version"]


def test_guidance_update_does_not_invalidate_handwritten_prompts():
    draft = {"requirements": dump(Requirements.empty()), "mode": "faithful"}
    draft["compiled"] = compile_prompt(draft, PromptEdit(positive="my silhouette", negative=""), source="user")
    draft["compiled"]["guidance_version"] = "previous-guidance"
    assert compile_state(draft) == "fresh"


def test_sync_remains_a_description_of_reviewed_text_not_a_guided_rewrite(tmp_path, monkeypatch):
    store, record = workspace(tmp_path)
    calls = capture_transport(monkeypatch, positive="model tried to improve the image")
    result = rewrite(store, record, task="sync_requirements",
                     compiled=PromptEdit(positive="my exact silhouette", negative="no text"))
    assert "model_guidance" not in json.loads(calls[0]["messages"][-1]["content"])
    assert result["positive"] == "my exact silhouette"
    assert result["negative"] == "no text"
