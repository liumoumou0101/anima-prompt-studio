"""Declared identity tags keep their ownership through rewrites and reloads."""
import asyncio
import json

import pytest

from anima_prompt_studio_v3.api.conversation import ConversationService, TurnRequest
from anima_prompt_studio_v3.api.workspace_store import WorkspaceStore
from anima_prompt_studio_v3.core.requirements import (
    PromptEdit, Requirements, WorkbenchError, compile_prompt, dump,
)
from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
from pydantic import ValidationError


@pytest.mark.parametrize("field", ["character_tags", "series_tags", "general_tags"])
def test_symbol_only_manual_tags_are_rejected_before_a_workspace_can_be_saved(field):
    raw = dump(Requirements.empty())
    raw["layers"]["subject"][field] = ["___"]
    with pytest.raises(ValidationError):
        Requirements.model_validate(raw)


@pytest.mark.parametrize("tag,weighted", [
    ("shana", "(shana:1.2)"),
    (r"unknown hero (game)", r"(unknown_hero_\(game\):1.2)"),
    ("@sample artist", "(@sample_artist:0.8)"),
    ("shana", "((shana))"),
])
def test_rewrite_keeps_one_weighted_identity_entry_and_removes_it_when_deselected(tag, weighted):
    requirements = dump(Requirements.empty())
    if tag.startswith("@"):
        requirements["layers"]["style"]["manual_artist_tags"] = [tag[1:]]
    else:
        requirements["layers"]["subject"]["character_tags"] = [tag]
    draft = {"requirements": requirements, "model_profile": "anima_turbo_v1_1"}
    first = compile_prompt(draft, PromptEdit(positive=weighted + ", standing in a garden", negative=""), source="llm")
    assert first["positive"] == weighted + ", standing in a garden"
    draft["compiled"] = first
    draft["requirements"]["layers"]["subject"]["character_tags"] = []
    draft["requirements"]["layers"]["style"]["manual_artist_tags"] = []
    removed = compile_prompt(draft, PromptEdit(positive=first["positive"], negative=""), source="llm")
    assert removed["positive"] == "standing in a garden"


def test_weighted_identity_matching_does_not_remove_a_name_inside_a_sentence():
    requirements = dump(Requirements.empty())
    draft = {"requirements": requirements, "compiled": {"manual_tags": ["shana", "@sample artist"]}}
    prompt = "a portrait inspired by Shana, (standing beside Shana:1.2), (@sample artist style:0.8)"
    assert compile_prompt(draft, PromptEdit(positive=prompt, negative=""), source="llm")["positive"] == prompt


@pytest.mark.parametrize("model", ["anima_turbo_v1_1", "moss_image_sft_int8"])
def test_user_authored_weighted_or_chinese_text_remains_exact(model):
    prompt = "  中文原文，(@sample_artist:1.2)\n (Shana:0.8)  "
    result = compile_prompt({"model_profile": model}, PromptEdit(positive=prompt, negative="负面原文"), source="user")
    assert result["positive"] == prompt
    assert result["negative"] == "负面原文"


@pytest.mark.parametrize("existing,delta,returned", [
    (["sample_artist"], "只修改光照", "sample artist"),
    ([], "画师使用 @sample_artist", "sample artist"),
    ([], r"画师使用 @artist_\(name\)", "artist (name)"),
    ([], "使用 sample_artist 画风", "sample artist"),
    ([], "in the style of sample_artist", "sample artist"),
    ([], "@sample_artist画风", "sample artist"),
])
def test_equivalent_artist_spellings_are_not_rejected_as_invented(tmp_path, monkeypatch, existing, delta, returned):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    requirements = dump(Requirements.empty())
    requirements["layers"]["subject"]["text"] = "花园中的成年女性"
    requirements["layers"]["style"]["artists"] = existing
    record = store.create("标签验收", {"requirements_edit": {"layers": requirements["layers"], "loras": []}})

    async def complete(**_kwargs):
        return {"text": json.dumps({"touched_layers": ["style"], "layer_updates": {"style": {"artists": [returned]}},
            "positive": "adult woman, sunlit garden", "negative": "", "warnings": []})}
    monkeypatch.setattr(LLMService, "complete", complete)
    request = TurnRequest(workspace_id=record["id"], revision=record["revision"], delta={"text": delta})
    result = asyncio.run(ConversationService(store).turn(request))
    expected = "@" + returned.replace("(", r"\(").replace(")", r"\)") + ", adult woman, sunlit garden"
    assert result["positive"] == expected
    reloaded = WorkspaceStore(store.path).get(record["id"])
    assert reloaded["draft"]["compiled"]["positive"] == expected
    assert reloaded["draft"]["requirements"]["layers"]["style"]["artists"] == [returned]


@pytest.mark.parametrize("delta,artist", [
    ("只修改光照", "invented artist"),
    ("画师使用 @sample_artist_extended", "sample artist"),
    ("角色站在 red_coat 旁边", "red coat"),
    ("A woman in a cartoon garden", "art"),
])
def test_an_unmentioned_artist_is_still_rejected(tmp_path, monkeypatch, delta, artist):
    store = WorkspaceStore(tmp_path / "workspaces.db")
    requirements = dump(Requirements.empty())
    requirements["layers"]["subject"]["text"] = "花园中的成年女性"
    record = store.create("标签验收", {"requirements_edit": {"layers": requirements["layers"], "loras": []}})

    async def complete(**_kwargs):
        return {"text": json.dumps({"touched_layers": ["style"], "layer_updates": {"style": {"artists": [artist]}},
            "positive": "adult woman, garden", "negative": "", "warnings": []})}
    monkeypatch.setattr(LLMService, "complete", complete)
    with pytest.raises(WorkbenchError, match="未声明"):
        asyncio.run(ConversationService(store).turn(TurnRequest(workspace_id=record["id"], revision=record["revision"], delta={"text": delta})))
    assert store.get(record["id"])["revision"] == record["revision"]
