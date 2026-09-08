import re

import pytest

from anima_prompt_studio_v3.core.prompt_translation import anchors_for, domain_conflict, translate_prompt, review_translation


def identity_engine(text):
    return text


@pytest.mark.parametrize("source,expected", [
    ("一个女孩，水彩绘画，背带裙，举起相机", ["1girl", "watercolor", "pinafore dress", "holding up a camera"]),
    ("两个男孩，铅笔素描，胶片颗粒", ["2boys", "pencil drawing", "film grain"]),
    ("棱镜光，轮廓光，浅景深散景", ["prismatic light", "rim light", "shallow depth of field", "bokeh"]),
    ("画师 @someone，评分9，(fewer digits:2)", ["@someone", "score_9", "(fewer digits:2)"]),
])
def test_domain_anchors_are_preserved(source, expected):
    output, segments = translate_prompt(source, identity_engine)
    assert all(term in output for term in expected)
    assert segments
    assert not re.search(r"ZXQ\d+ZXQ", output)


def test_engine_cannot_drop_or_duplicate_protected_terms():
    def broken_engine(text):
        return "a room" if "ZXQ" in text else "in a room"
    output, segments = translate_prompt("一个女孩在房间里", broken_engine)
    assert output.count("1girl") == 1
    assert "in a room" in output
    assert segments[0]["status"] == "fragment_review"


def test_no_long_input_is_silently_truncated():
    calls = []
    def engine(text):
        calls.append(text)
        return "translated"
    _, segments = translate_prompt("未知场景" * 200, engine)
    assert all(len(call) <= 120 for call in calls)
    assert "".join(s["source"] for s in segments) == "未知场景" * 200


@pytest.mark.parametrize("source,part,tag", [
    ("黑色背带裙", "背带", "harness"),
    ("棱镜光", "棱镜", "prism"),
    ("强轮廓光", "轮廓", "outline"),
    ("金色长发", "金色", "gold"),
    ("35毫米胶片摄影", "摄影", "photo_(object)"),
])
def test_typed_phrase_blocks_unrelated_shorter_index_hit(source, part, tag):
    start = source.index(part)
    assert domain_conflict(source, start, start+len(part), tag)


def test_correct_full_phrase_is_not_blocked():
    assert not domain_conflict("背带裙", 0, 3, "pinafore_dress")
    assert not domain_conflict("棱镜", 0, 2, "prism")


def test_opaque_english_and_weights_are_not_translated():
    def forbidden(text):
        raise AssertionError(text)
    result, _ = translate_prompt("@p1ct01, (fewer digits:2), neferpitou", forbidden)
    assert result == "@p1ct01, (fewer digits:2), neferpitou"


def test_review_exposes_missing_critical_facts():
    review = review_translation("一个女孩，水彩，举起相机", "a portrait")
    assert review["requires_review"]
    assert {item["source"] for item in review["missing_anchors"]} == {"一个女孩", "水彩", "举起相机"}


def test_explicit_name_can_use_local_identity_dictionary():
    output, _ = translate_prompt("博丽灵梦", identity_engine, extra_terms={"博丽灵梦": "hakurei reimu"})
    assert output == "hakurei reimu"


def test_chinese_weight_and_grouped_english_are_preserved():
    output, _ = translate_prompt("强调更少的手指（权重2），(red hair, blue eyes:1.2)", identity_engine)
    assert output == "(fewer digits:2), (red hair, blue eyes:1.2)"


def test_clause_offsets_refer_to_original_source():
    source = "  一个女孩，  水彩绘画。"
    _, clauses = translate_prompt(source, identity_engine)
    assert all(source[item['start']:item['end']] == item['source'] for item in clauses)
