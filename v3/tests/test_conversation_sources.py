"""Source precedence reaches the generator; semantic review is isolated here."""
import asyncio
from copy import deepcopy
import json

import pytest

from anima_prompt_studio_v3.api.conversation import ConversationService, TurnRequest
from anima_prompt_studio_v3.api.workspace_store import WorkspaceStore
from anima_prompt_studio_v3.core.requirements import Requirements, PromptEdit, dump, compile_prompt
from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService


def prepared(tmp_path):
    store = WorkspaceStore(tmp_path / "sources.db")
    requirements = dump(Requirements.empty())
    requirements["layers"]["subject"]["text"] = "一个穿蓝外套的成年女子"
    requirements["layers"]["composition"]["text"] = "全身"
    requirements["layers"]["style"]["text"] = "纯色色块，禁止渐变"
    record = store.create("sources", {"requirements_edit": {"layers": requirements["layers"], "loras": []}})
    return store, record


def transport(monkeypatch):
    calls = []

    async def complete(**kwargs):
        calls.append(deepcopy(kwargs))
        assert len(calls) == 1, "Source assembly needs a single generation call in this isolated unit"
        return {"text": json.dumps({"touched_layers": [], "layer_updates": {},
                                   "positive": "a woman, full body, flat colors", "negative": "", "warnings": []})}

    monkeypatch.setattr(LLMService, "complete", complete)
    return calls


def run(store, record, **changes):
    request = TurnRequest(workspace_id=record["id"], revision=record["revision"],
                          delta={"text": ""}, **changes)
    return asyncio.run(ConversationService(store).turn(request))


def test_all_layer_sources_reach_the_single_generation_request(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    calls = transport(monkeypatch)
    saved = run(store, record)
    sources = json.loads(calls[0]["messages"][1]["content"])["preservation_sources"]
    assert sources["authority"] == "requirements"
    assert sources["required"] == [
        {"path": "requirements.layers.subject.text", "value": "一个穿蓝外套的成年女子"},
        {"path": "requirements.layers.style.text", "value": "纯色色块，禁止渐变"},
        {"path": "requirements.layers.composition.text", "value": "全身"},
    ]
    assert saved["draft"]["requirements"] == record["draft"]["requirements"]
    assert len(calls) == 1


def test_visible_edit_separates_old_unlocked_prose_from_authoritative_prompt(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    calls = transport(monkeypatch)
    visible = PromptEdit(positive="a woman in a red coat, full body, flat colors", negative="watermark")
    run(store, record, compiled=visible)
    context = json.loads(calls[0]["messages"][1]["content"])
    sources = context["preservation_sources"]
    assert sources["authority"] == context["prompt_authority"] == "visible_prompt"
    assert sources["required"] == [
        {"path": "compiled.positive", "value": visible.positive},
        {"path": "compiled.negative", "value": "watermark"},
    ]
    assert {"path": "requirements.layers.subject.text", "value": "一个穿蓝外套的成年女子"} in sources["previous_context"]
    # Raw values remain available for updating the ledger; no server translation.
    assert context["requirements"] == record["draft"]["requirements"]


@pytest.mark.real_rewrite_review
def test_deleted_action_is_not_sent_back_during_rewrite_review_or_repair(tmp_path, monkeypatch):
    store = WorkspaceStore(tmp_path / "removed-action.db")
    old_action = "raises her right hand"
    old_description = "一位成年女性举起右手"
    visible = {"positive": "an adult woman in a quiet room, oil painting", "negative": "watermark"}
    requirements = dump(Requirements.empty())
    requirements["layers"]["subject"]["text"] = old_description
    requirements["layers"]["style"].update(text="油画", locked=True)
    requirements["layers"]["lighting"]["mood"] = {
        "value": "安静", "source": "extracted", "evidence": "an adult woman " + old_action + " in a quiet room",
    }
    record = store.create("removed action", {"requirements_edit": {"layers": requirements["layers"], "loras": []},
        "prompt_edit": {**visible, "positive": visible["positive"] + ", " + old_action}})
    def compile_original(draft):
        draft["compiled"] = compile_prompt(draft, PromptEdit(positive=visible["positive"] + ", " + old_action,
            negative=visible["negative"]), source="llm")
        return draft

    record = store.transform(record["id"], expected_revision=record["revision"], operation=compile_original)
    saved = store.update(record["id"], expected_revision=record["revision"], title=record["title"], draft={"prompt_edit": visible})
    calls = []

    async def complete(task, messages, **kwargs):
        calls.append((task, messages))
        if task == "rewrite_review":
            issues = ([{"field": "positive", "quote": "harsh lighting", "reason": "用户要求柔和侧光"}]
                      if len(calls) == 2 else [])
            return {"text": json.dumps({"prompt_issues": issues})}
        # Simulate a model recovering any old action it sees in the supplied scene data.
        source = "\n".join(message["content"] for message in messages[1:])
        leaked = old_action in source or old_description in source
        lighting = "harsh lighting" if len(calls) == 1 else "soft side lighting"
        return {"text": json.dumps({"positive": visible["positive"] + ", " + lighting + (", " + old_action if leaked else ""),
            "negative": visible["negative"], "layer_updates": {"lighting": {"text": "柔和侧光"}}})}

    monkeypatch.setattr(LLMService, "complete", complete)
    request = TurnRequest(workspace_id=saved["id"], revision=saved["revision"], compiled=visible,
                          delta={"text": "只改成柔和侧光，其余保持不变"})
    result = asyncio.run(ConversationService(store).turn(request))

    assert [task for task, _ in calls] == ["rewrite", "rewrite_review", "rewrite", "rewrite_review"]
    assert result["positive"] == visible["positive"] + ", soft side lighting"
    assert result["negative"] == visible["negative"]
    for _, messages in calls:
        for message in messages[1:]:
            assert old_action not in message["content"]
            assert old_description not in message["content"]
    context = json.loads(calls[0][1][1]["content"])
    assert context["requirements"]["layers"]["style"]["text"] == "油画"
    assert context["requirements"]["layers"]["lighting"]["mood"]["value"] == "安静"
    repair = json.loads(calls[2][1][-1]["content"])
    assert repair["final_candidate"]["requirements"]["layers"]["lighting"]["text"] == "柔和侧光"
    assert result["draft"]["requirements"]["layers"]["subject"]["text"] == old_description


def test_prompt_edit_still_receives_a_new_uncompiled_requirement(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    visible = PromptEdit(positive="a woman in a blue coat", negative="")

    def compile_original(draft):
        draft["compiled"] = compile_prompt(draft, visible, source="llm")
        return draft

    record = store.transform(record["id"], expected_revision=record["revision"], operation=compile_original)
    requirements = deepcopy(record["draft"]["requirements"])
    requirements["layers"]["subject"]["text"] = "一位手持茶杯的成年女性"
    saved = store.update(record["id"], expected_revision=record["revision"], title=record["title"],
        draft={"requirements_edit": {"layers": requirements["layers"], "loras": []}})
    assert saved["draft"]["compile_state"] == "stale"
    calls = transport(monkeypatch)
    request = TurnRequest(workspace_id=saved["id"], revision=saved["revision"], compiled=visible,
                          delta={"text": "改成暖光"})
    asyncio.run(ConversationService(store).turn(request))
    context = json.loads(calls[0]["messages"][1]["content"])
    assert context["requirements"]["layers"]["subject"]["text"] == "一位手持茶杯的成年女性"


def test_removed_control_and_manual_tag_provenance_reaches_generator(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    req = deepcopy(record["draft"]["requirements"])
    req["layers"]["composition"]["text"] = ""
    req["layers"]["composition"]["design"] = {"shot": {"value": "半身", "source": "user"}}
    req["layers"]["subject"]["general_tags"] = ["blue eyes"]
    record = store.update(record["id"], expected_revision=record["revision"], title="old choices",
                          draft={"requirements_edit": {"layers": req["layers"], "loras": []}})
    draft = deepcopy(record["draft"])
    draft["compiled"] = compile_prompt(draft, PromptEdit(positive="a woman, upper body", negative=""), source="llm")
    record = store.transform(record["id"], expected_revision=record["revision"], operation=lambda _: draft)
    req["layers"]["composition"]["design"] = {}
    req["layers"]["subject"]["general_tags"] = []
    record = store.update(record["id"], expected_revision=record["revision"], title="cleared choices",
                          draft={"requirements_edit": {"layers": req["layers"], "loras": []}})
    calls = transport(monkeypatch)
    run(store, record)
    sources = json.loads(calls[0]["messages"][1]["content"])["preservation_sources"]
    assert sources["superseded"] == [
        {"path": "compiled.scene_intent.shot", "value": {"value": "半身", "source": "user", "target": "", "evidence": ""}},
    ]
    # Explicit tag selection now removes the exact token before the rewrite;
    # scene wording still needs its previous control provenance for the LLM.
    context = json.loads(calls[0]["messages"][1]["content"])
    assert "blue eyes" not in context["compiled"]["positive"]


def test_sync_keeps_reviewed_prompt_and_uses_its_existing_single_call(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    calls = transport(monkeypatch)
    exact = PromptEdit(positive="reviewed watercolor portrait", negative="text, watermark")
    saved = run(store, record, task="sync_requirements", compiled=exact)
    assert saved["positive"] == exact.positive
    assert saved["negative"] == exact.negative
    assert "preservation_sources" not in json.loads(calls[0]["messages"][1]["content"])
    assert len(calls) == 1
