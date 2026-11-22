"""Literal limit protection must retain the source's person/scope context."""
import pytest

from anima_prompt_studio_v3.core.moss_constraints import constraint_sentences, preserve_constraints


@pytest.mark.parametrize("source, expected", [
    ("Two women. Left woman:\nNo hat.\nRight woman:\nWearing a blue hat.", "Left woman:\nNo hat."),
    ("两位女性。左侧女性：\n不戴帽子。\n右侧女性：\n戴蓝帽。", "左侧女性：\n不戴帽子。"),
    ("Two women. Left woman: no hat; right woman: wearing a blue hat.",
     "Left woman: no hat; right woman: wearing a blue hat."),
    ("两位女性。左侧女性：不戴帽子；右侧女性：戴蓝帽。", "左侧女性：不戴帽子；右侧女性：戴蓝帽。"),
])
def test_limits_keep_titles_line_layout_and_semicolon_scope(source, expected):
    assert constraint_sentences(source) == [expected]
    protected = preserve_constraints(source, "Two women: bareheaded woman left, blue-hatted woman right.")
    assert expected in protected
    assert "\nNo hat." not in protected.replace(expected, "")
    assert "\n不戴帽子。" not in protected.replace(expected, "")


@pytest.mark.parametrize("source, expected", [
    ("Left woman wears a red coat. No hat. Right woman wears a blue hat.",
     "Left woman wears a red coat. No hat."),
    ("左侧女性穿红外套。不戴帽子。右侧女性戴蓝帽。", "左侧女性穿红外套。不戴帽子。"),
])
def test_subjectless_negative_retains_the_preceding_person_context(source, expected):
    assert constraint_sentences(source) == [expected]
