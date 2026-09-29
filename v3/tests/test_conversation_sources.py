"""Source precedence reaches the generator without another model call."""
import asyncio
from copy import deepcopy
import json

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
        assert len(calls) == 1, "A normal rewrite must not add a paid semantic review"
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
        {"path": "previous_manual_tags[0]", "value": "blue eyes"},
    ]


def test_sync_keeps_reviewed_prompt_and_uses_its_existing_single_call(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    calls = transport(monkeypatch)
    exact = PromptEdit(positive="reviewed watercolor portrait", negative="text, watermark")
    saved = run(store, record, task="sync_requirements", compiled=exact)
    assert saved["positive"] == exact.positive
    assert saved["negative"] == exact.negative
    assert "preservation_sources" not in json.loads(calls[0]["messages"][1]["content"])
    assert len(calls) == 1
