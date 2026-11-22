"""Anima rewrites must translate Chinese without silently dropping scene facts."""
import asyncio
from copy import deepcopy

import pytest

from anima_prompt_studio_v3.api.conversation import ConversationService, TurnRequest
from anima_prompt_studio_v3.core.requirements import (
    PromptEdit, WorkbenchError, compile_prompt,
)
from test_conversation_reliability import mock_results, output, prepared, rewrite


@pytest.mark.parametrize("mode", ["faithful", "expand"])
@pytest.mark.parametrize("field,text", [
    ("positive", "detective, 蓝色外套"),
    ("negative", "文字, watermark"),
])
def test_chinese_prompt_gets_one_translation_repair(tmp_path, monkeypatch, mode, field, text):
    store, record = prepared(tmp_path)
    corrected = output(negative="text, watermark", warnings=["已翻译为英文"])
    calls = mock_results(monkeypatch, output(**{field: text}), corrected)
    result = rewrite(store, record, mode=mode)
    assert result["positive"] == corrected["positive"]
    assert result["negative"] == corrected["negative"]
    assert result["warnings"] == corrected["warnings"]
    assert len(calls) == 2
    assert calls[1]["messages"][:2] == calls[0]["messages"]
    repair = calls[1]["messages"][-1]["content"]
    assert field in repair and "English" in repair
    assert "do not delete" in repair.lower()
    assert calls[1]["timeout_s"] <= 30
    assert store.get(record["id"])["draft"]["requirements"] == record["draft"]["requirements"]


@pytest.mark.parametrize("preview", [False, True])
@pytest.mark.parametrize("first", ["not JSON", output(positive="detective, 外套")])
def test_failed_translation_shares_repair_budget_and_never_saves(tmp_path, monkeypatch, preview, first):
    store, record = prepared(tmp_path)
    calls = mock_results(monkeypatch, first, output(negative="文字"))
    with pytest.raises(WorkbenchError) as error:
        rewrite(store, record, preview=preview)
    assert error.value.code == "llm_generation_failed"
    assert "中文" in str(error.value)
    assert len(calls) == 2
    assert store.get(record["id"]) == record
    assert store.get_proposal(record["id"]) is None


def test_english_output_with_accented_name_and_chinese_notes_takes_one_call(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    calls = mock_results(monkeypatch, output(
        positive="a detective named Chloé, blue coat", warnings=["保留原有画面要求"]))
    result = rewrite(store, record)
    assert result["positive"] == "a detective named Chloé, blue coat"
    assert len(calls) == 1


@pytest.mark.parametrize("kind", ["manual_tag", "artist", "trigger", "positive_lock", "negative_lock"])
def test_chinese_literal_controls_report_conflict_before_calling_model(tmp_path, monkeypatch, kind):
    store, record = prepared(tmp_path)
    def add_control(draft):
        requirements = draft["requirements"]
        if kind == "manual_tag":
            requirements["layers"]["subject"]["general_tags"] = ["蓝色外套"]
        elif kind == "artist":
            requirements["layers"]["style"]["manual_artist_tags"] = ["画师名"]
        elif kind == "trigger":
            requirements["loras"] = [{"logical_id": "test", "file_name": "test.safetensors",
                                       "trigger_words": ["蓝色外套"]}]
        else:
            requirements["prompt_locks"] = [{"target": kind.removesuffix("_lock"), "text": "外套"}]
        return draft
    record = store.transform(record["id"], expected_revision=record["revision"], operation=add_control)
    calls = mock_results(monkeypatch, output())
    with pytest.raises(WorkbenchError) as error:
        rewrite(store, record)
    assert error.value.code == "prompt_language_conflict"
    assert "英文" in str(error.value)
    assert not calls
    assert store.get(record["id"]) == record


def test_recompile_translates_old_chinese_negative_instead_of_restoring_it(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    record = store.update(record["id"], expected_revision=record["revision"], title=record["title"],
        draft={"prompt_edit": {"positive": "detective, blue coat", "negative": "文字, watermark"}})
    calls = mock_results(monkeypatch, output(negative="text, watermark"))
    request = TurnRequest(workspace_id=record["id"], revision=record["revision"], delta={"text": ""})
    result = asyncio.run(ConversationService(store).turn(request))
    assert result["negative"] == "text, watermark"
    assert len(calls) == 1


@pytest.mark.parametrize("field,text", [
    ("positive", "detective, 外套"), ("negative", "漢字"),
    ("positive", "a sign reading '中文'"), ("positive", "a sign with 𠀀"),
])
def test_llm_compiler_rejects_chinese_but_keeps_manual_text_verbatim(tmp_path, field, text):
    _, record = prepared(tmp_path)
    prompt = PromptEdit(**{"positive": "detective", "negative": "", field: text})
    with pytest.raises(WorkbenchError, match="中文"):
        compile_prompt(record["draft"], prompt, source="llm")
    compiled = compile_prompt(record["draft"], prompt, source="user")
    assert compiled[field] == text


def test_final_compiler_checks_server_inserted_tags(tmp_path):
    _, record = prepared(tmp_path)
    draft = deepcopy(record["draft"])
    draft["requirements"]["layers"]["subject"]["general_tags"] = ["外套"]
    with pytest.raises(WorkbenchError, match="中文"):
        compile_prompt(draft, PromptEdit(positive="detective", negative=""), source="llm")


def test_sync_describes_manual_text_without_rewriting_it(tmp_path, monkeypatch):
    store, record = prepared(tmp_path)
    manual = {"positive": "detective, 蓝外套", "negative": "文字"}
    calls = mock_results(monkeypatch, output())
    result = rewrite(store, record, task="sync_requirements", compiled=manual)
    assert result["positive"] == manual["positive"]
    assert result["negative"] == manual["negative"]
    assert len(calls) == 1
    assert store.get(record["id"]) == record
