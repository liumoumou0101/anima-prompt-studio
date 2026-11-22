"""MOSS review/repair behavior at the real API-to-LLM boundary."""
import asyncio
import json

import pytest

from anima_prompt_studio_v3.api.moss import MossPromptAssistRequest, assist_prompt
from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService

pytestmark = pytest.mark.real_rewrite_review


def suggestion(positive, *, negative="", changes=(), warnings=()):
    return dict(positive=positive, negative=negative, changes=list(changes), warnings=list(warnings))


def install_transport(monkeypatch, outputs, reviews):
    """Replace the external transport only, retaining API parsing and control flow."""
    output_iter, review_iter = iter(outputs), iter(reviews)
    calls = []

    async def complete(**kwargs):
        task = kwargs.get("task")
        calls.append(task)
        value = next(review_iter) if task == "rewrite_review" else next(output_iter)
        if isinstance(value, Exception):
            raise value
        return {"text": json.dumps(value, ensure_ascii=False)}

    monkeypatch.setattr(LLMService, "complete", complete)
    return calls


@pytest.mark.parametrize("mode", ["polish", "expand"])
def test_moss_allows_name_quotes_that_do_not_request_image_lettering(monkeypatch, mode):
    output = suggestion("一位成年女性穿蓝色外套，全身像，纯白背景，不出现文字。")
    install_transport(monkeypatch, [output], [{"issues": []}])

    result = asyncio.run(assist_prompt(MossPromptAssistRequest(
        source_text='一位成年女性，服装称为“蓝色外套”，引号仅标注名称，不是在画面上写字。全身像，纯白背景，不出现文字。',
        mode=mode)))

    assert result["positive"] == "一位成年女性穿蓝色外套，全身像，纯白背景，不出现文字。"


@pytest.mark.parametrize("mode", ["polish", "expand"])
def test_moss_repairs_lost_count_and_attribute_ownership_before_returning(monkeypatch, mode):
    bad = suggestion("一位成年女性穿蓝色外套，坐在椅子上，半身像。")
    good = suggestion("两位成年女性，全身像。左侧女性穿红外套并站立，右侧女性穿蓝外套并坐在椅子上。")
    calls = install_transport(monkeypatch, [bad, good], [
        {"issues": ["人数应为两位；左侧红衣站立、右侧蓝衣坐姿和全身构图未保留。"]},
        {"issues": []},
    ])

    result = asyncio.run(assist_prompt(MossPromptAssistRequest(
        source_text="两位成年女性，全身像。左侧女性穿红外套并站立，右侧女性穿蓝外套并坐在椅子上。", mode=mode)))

    assert result["positive"] == good["positive"]
    assert calls.count("rewrite") == 2
    assert calls.count("rewrite_review") == 2


def test_moss_rejects_a_semantically_wrong_result_after_one_repair(monkeypatch):
    bad = suggestion("一位成年女性穿蓝色外套，半身像。")
    calls = install_transport(monkeypatch, [bad, bad], [
        {"issues": ["人数和服装颜色与原文相反。"]},
        {"issues": ["人数和服装颜色仍与原文相反。"]},
    ])

    with pytest.raises(RuntimeError, match="原文|草稿"):
        asyncio.run(assist_prompt(MossPromptAssistRequest(
            source_text="两位成年女性穿红色外套，全身像。", mode="polish")))

    assert calls.count("rewrite") == 2


def test_moss_polish_repairs_unrequested_new_lighting(monkeypatch):
    bad = suggestion("一位成年女性站在纯白背景前，夕阳照在脸上。", changes=["整理表达"])
    good = suggestion("一位成年女性站在纯白背景前。", changes=["整理语序"])
    install_transport(monkeypatch, [bad, good], [
        {"issues": ["polish不允许新增夕阳光照。"]}, {"issues": []},
    ])

    result = asyncio.run(assist_prompt(MossPromptAssistRequest(
        source_text="一位成年女性，站立，纯白背景。", mode="polish")))

    assert result["positive"] == "一位成年女性站在纯白背景前。"
    assert "夕阳" not in result["positive"]


def test_moss_keeps_image_lettering_and_repeated_occurrences_after_repair(monkeypatch):
    bad = suggestion('一位成年女性举着两块招牌，一块写着“春”，另一块写着“春天”。')
    good = suggestion('一位成年女性举着两块招牌，分别写着“春天”和“春天”。')
    install_transport(monkeypatch, [bad, good], [
        {"issues": ["第一块招牌上的图片文字春天被改成春。两处必须逐字保留。"]},
        {"issues": []},
    ])

    result = asyncio.run(assist_prompt(MossPromptAssistRequest(
        source_text='一位成年女性举着两块招牌，分别写着“春天”和“春天”。', mode="polish")))

    assert result["positive"].count('“春天”') == 2


def test_moss_repairs_negative_without_changing_original_whitespace(monkeypatch):
    good = suggestion("一位成年女性，全身像。", negative=" 不要帽子、文字 ")
    install_transport(monkeypatch, [suggestion(good["positive"], negative="不要帽子、文字"), good], [
        {"issues": []}, {"issues": []},
    ])

    result = asyncio.run(assist_prompt(MossPromptAssistRequest(
        source_text="一位成年女性，全身像。", negative_prompt=" 不要帽子、文字 ", mode="polish")))

    assert result["negative"] == " 不要帽子、文字 "


def test_moss_keeps_english_source_language_through_review_and_repair(monkeypatch):
    wrong_language = suggestion("一位成年女性穿红色外套，全身像。")
    good = suggestion("An adult woman wearing a red coat, full body.")
    install_transport(monkeypatch, [wrong_language, good], [
        {"issues": []},
    ])

    result = asyncio.run(assist_prompt(MossPromptAssistRequest(
        source_text="An adult woman wearing a red coat, full body.", mode="polish")))

    assert result["positive"] == good["positive"]


def test_moss_does_not_release_an_unreviewed_candidate_when_reviewer_fails(monkeypatch):
    install_transport(monkeypatch, [suggestion("一位成年女性，全身像。")], [
        RuntimeError("https://secret.example sk-private-key"),
    ])

    with pytest.raises(RuntimeError) as exc:
        asyncio.run(assist_prompt(MossPromptAssistRequest(source_text="一位成年女性，全身像。", mode="polish")))

    assert "secret" not in str(exc.value)
    assert "private" not in str(exc.value)
