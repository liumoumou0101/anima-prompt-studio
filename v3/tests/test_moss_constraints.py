"""Deterministic MOSS protections even when the semantic reviewer misses a loss."""
import asyncio
import json

import pytest

from anima_prompt_studio_v3.api.moss import MossPromptAssistRequest, assist_prompt
from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService

pytestmark = pytest.mark.real_rewrite_review


def run_assist(monkeypatch, source, positives, *, mode="expand", negative=""):
    choices = iter(positives)
    reviewed = []

    async def complete(**kwargs):
        if kwargs["task"] == "rewrite_review":
            request = json.loads(kwargs["messages"][1]["content"])
            reviewed.append(request["candidate"]["positive"])
            return {"text": json.dumps({"issues": [], "conflicts": []})}
        return {"text": json.dumps({"positive": next(choices), "negative": negative,
                                    "changes": [], "warnings": []}, ensure_ascii=False)}

    monkeypatch.setattr(LLMService, "complete", complete)
    result = asyncio.run(assist_prompt(MossPromptAssistRequest(
        source_text=source, negative_prompt=negative, mode=mode)))
    return result, reviewed


@pytest.mark.parametrize("constraint", [
    "不要增加人物、动物或道具。",
    "不要渐变、厚涂、珠宝、花束或新增装饰。",
    "背景只能是纯灰色墙面，没有植物、标牌或家具。",
])
def test_source_constraints_are_present_in_effective_text_before_review(monkeypatch, constraint):
    result, reviewed = run_assist(monkeypatch, "一位成年女性，全身像。" + constraint,
                                  ["一位成年女性，全身像，表情自然。"], negative="额外人物")

    assert constraint in result["positive"]
    assert reviewed == [result["positive"]]
    assert result["negative"] == "额外人物"
    assert "已保留原文明确限制，部分表述可能重复。" in result["warnings"]


def test_preserves_scoped_hat_rule_as_a_whole_sentence_not_global_exclusion(monkeypatch):
    source = "两位成年女性，全身像。左侧女性不戴帽子，右侧女性保留蓝帽，不能把帽子设为全局排除。"
    result, _ = run_assist(monkeypatch, source, ["两位成年女性，全身像。左侧女性光头，右侧女性戴蓝帽。"])

    assert "左侧女性不戴帽子，右侧女性保留蓝帽，不能把帽子设为全局排除。" in result["positive"]
    assert result["negative"] == ""


def test_english_translation_to_chinese_is_repaired_before_source_copy_can_mask_it(monkeypatch):
    source = "One adult woman in a red coat, full body, no extra people or props."
    result, reviewed = run_assist(monkeypatch, source, [
        "一位成年女性穿红色外套，全身像，没有其他人物或道具。",
        "One adult woman in a red coat, full body, no extra people or props, calm expression.",
    ])

    assert "一位成年" not in result["positive"]
    assert "calm expression" in result["positive"]
    assert len(reviewed) == 1


def test_chinese_body_with_a_token_han_appendix_does_not_pass_as_chinese(monkeypatch):
    source = "一位成年女性穿红外套，坐在椅子上，全身像，纯白背景。不要新增道具。"
    result, reviewed = run_assist(monkeypatch, source, [
        "One adult woman in a red coat, seated on a chair, full body, plain white background. 中文",
        "一位成年女性穿红外套，坐在椅子上，全身像，纯白背景，表情平静。",
    ])

    assert "One adult" not in result["positive"]
    assert "不要新增道具。" in result["positive"]
    assert len(reviewed) == 1


@pytest.mark.parametrize("source,positive", [
    ("成人女性が青いコートを着て立っています。全身像、白い背景。帽子や動物を追加しない。",
     "青いコートを着た成人女性が立っています。全身像、白い背景。帽子や動物を追加しない。"),
    ('一位成年女性名叫Mira，穿Chanel蓝外套，全身像。招牌写着“HELLO WORLD”。不要新增人物。',
     'Mira是一位成年女性，穿Chanel蓝外套，全身像。招牌写着“HELLO WORLD”。不要新增人物。'),
    ('One adult woman holds a sign reading “春天 春天 春天 春天 春天 春天 春天 春天”. No extra people.',
     'An adult woman holds a sign reading “春天 春天 春天 春天 春天 春天 春天 春天”. No extra people.'),
])
def test_language_distribution_keeps_japanese_names_and_quoted_picture_text_usable(monkeypatch, source, positive):
    result, reviewed = run_assist(monkeypatch, source, [positive], mode="polish")

    assert result["positive"] == positive
    assert reviewed == [positive]


def test_japanese_to_chinese_body_is_repaired(monkeypatch):
    source = "成人女性が青いコートを着て立っています。全身像、白い背景。"
    result, reviewed = run_assist(monkeypatch, source, [
        "一位成年女性穿蓝色外套站立，全身像，白色背景。",
        "青いコートを着た成人女性が立っています。全身像、白い背景。",
    ], mode="polish")

    assert "青いコート" in result["positive"]
    assert len(reviewed) == 1


def test_quote_name_meta_sentence_is_not_reinserted_as_picture_instruction(monkeypatch):
    source = '衣服称为“蓝色外套”，引号仅标注名称，不要求画上文字。一位成年女性穿蓝色外套，全身像。'
    positive = "一位成年女性穿蓝色外套，全身像。"
    result, reviewed = run_assist(monkeypatch, source, [positive], mode="polish")

    assert result["positive"] == positive
    assert "“蓝色外套”" not in result["positive"]
    assert reviewed == [positive]


def test_no_inside_picture_lettering_is_not_itself_a_source_constraint(monkeypatch):
    source = 'An adult woman carries a sign reading "NO ENTRY".'
    positive = 'An adult woman carries a sign reading "NO ENTRY", with a calm expression.'
    result, _ = run_assist(monkeypatch, source, [positive])

    assert result["positive"] == positive


def test_copied_constraints_cannot_exceed_the_final_output_limit(monkeypatch):
    source = "不要新增动物或道具。"
    with pytest.raises(RuntimeError, match="草稿"):
        run_assist(monkeypatch, source, ["成年女性" * 4999, "成年女性" * 4999])


def test_review_receives_original_constraint_blocks_as_source_provenance(monkeypatch):
    async def complete(**kwargs):
        if kwargs["task"] == "rewrite_review":
            data = json.loads(kwargs["messages"][1]["content"])
            assert data["context"]["source_constraint_sentences"] == ["左侧女性：\n不戴帽子。"]
            assert "左侧女性：\n不戴帽子。" in data["candidate"]["positive"]
            return {"text": json.dumps({"issues": [], "conflicts": []})}
        return {"text": json.dumps({"positive": "左侧女性不戴帽子，右侧女性戴蓝帽。", "negative": "",
                                    "changes": [], "warnings": []}, ensure_ascii=False)}

    monkeypatch.setattr(LLMService, "complete", complete)
    result = asyncio.run(assist_prompt(MossPromptAssistRequest(
        source_text="左侧女性：\n不戴帽子。右侧女性：\n戴蓝帽。", mode="polish")))
    assert "左侧女性：\n不戴帽子。" in result["positive"]


@pytest.mark.parametrize("source, expected_script", [
    ("An adult woman in a red coat, full body.", "latin"),
    ("一位成年女性穿红色外套，全身像。", "han"),
    ("赤いコートを着た成人女性が立っています。全身像。", "japanese"),
])
def test_generation_receives_positive_source_language_hint(monkeypatch, source, expected_script):
    async def complete(**kwargs):
        if kwargs["task"] == "rewrite_review":
            return {"text": json.dumps({"issues": [], "conflicts": []})}
        request = json.loads(kwargs["messages"][1]["content"])
        assert request["language_contract"]["source_script"] == expected_script
        assert request["language_contract"]["notes_language"] == "free"
        return {"text": json.dumps({"positive": source, "negative": "", "changes": [], "warnings": []}, ensure_ascii=False)}

    monkeypatch.setattr(LLMService, "complete", complete)
    result = asyncio.run(assist_prompt(MossPromptAssistRequest(source_text=source, mode="polish")))
    assert result["positive"] == source


def test_language_repair_retains_the_expand_goal_within_two_generation_calls(monkeypatch):
    requests = []
    source = "An adult woman in a red coat, full body."

    async def complete(**kwargs):
        if kwargs["task"] == "rewrite_review":
            data = json.loads(kwargs["messages"][1]["content"])
            assert "calm expression" in data["candidate"]["positive"]
            return {"text": json.dumps({"issues": [], "conflicts": []})}
        requests.append(kwargs["messages"])
        if len(requests) == 1:
            positive = "一位成年女性穿红色外套，全身像，表情平静。"
        else:
            repair = json.loads(kwargs["messages"][-1]["content"])
            assert repair["mode"] == "expand"
            assert repair["preserve_compatible_elaboration"] is True
            assert repair["language_repair"] is True
            positive = "An adult woman in a red coat, full body, calm expression."
        return {"text": json.dumps({"positive": positive, "negative": "", "changes": ["Added calm expression."], "warnings": []}, ensure_ascii=False)}

    monkeypatch.setattr(LLMService, "complete", complete)
    result = asyncio.run(assist_prompt(MossPromptAssistRequest(source_text=source, mode="expand")))
    assert result["positive"] == "An adult woman in a red coat, full body, calm expression."
    assert len(requests) == 2
