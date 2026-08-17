"""Keep the visual-semantic layer from rewriting or dropping NSFW intent."""
from __future__ import annotations

import pytest

from anima_prompt_studio.domain.models import PromptJob, SemanticFrame
from anima_prompt_studio.services.pipeline import PromptPipeline
from anima_prompt_studio.services.visual_semantics import VisualSemanticNormalizer

from tests._nsfw_compat_probe import ENGLISH_CASES, HARD_CASES, SOFT_CASES


def _any_group_in(text: str, groups: list[list[str]]) -> bool:
    haystack = text.lower()
    return any(any(token.lower() in haystack for token in group) for group in groups)


def _pipeline_job(source: str) -> PromptJob:
    job = PromptJob(original_zh=source)
    PromptPipeline().translate(job)
    return job


@pytest.mark.parametrize("case", SOFT_CASES + HARD_CASES, ids=lambda case: case["id"])
def test_visual_layer_preserves_existing_nsfw_probe_intents(case):
    job = _pipeline_job(case["input"])
    tags = {item.tag for item in job.matched_tags}
    blob = " ".join([
        job.translated_en or "",
        job.positive_prompt or "",
        " ".join(tags),
    ]).lower()

    assert job.translated_en.strip()
    assert job.positive_prompt.strip()
    assert _any_group_in(blob, case["expect_en_any"])
    assert _any_group_in(blob, case["expect_tags_any"])
    if not any(token in case["input"] for token in ("开心", "高兴", "愉快", "喜悦", "微笑")):
        assert "happy" not in tags
        assert "happy expression" not in (job.translated_en or "").lower()


@pytest.mark.parametrize("case", ENGLISH_CASES, ids=lambda case: case["id"])
def test_english_authority_nsfw_tags_survive_visual_recompile(case):
    job = PromptJob(original_zh=case["input_zh"])
    pipe = PromptPipeline()
    pipe.translate(job)
    pipe.update_english(job, case["english"])
    blob = " ".join(item.tag for item in job.matched_tags) + " " + job.positive_prompt
    assert _any_group_in(blob, case["expect_tags_any"])
    assert job.semantic_frame.visual_slots == {}


def test_adult_excitement_and_gaze_do_not_collapse_to_window_sadness():
    job = _pipeline_job("一个裸体女孩很兴奋，看着镜头")
    tags = {item.tag for item in job.matched_tags}
    assert job.semantic_frame.visual_slots["emotion"] == "aroused expression"
    assert job.semantic_frame.visual_slots["gaze"] == "looking at the viewer"
    assert {"nude", "aroused", "looking at viewer"} <= tags
    assert "happy" not in tags
    assert "looking away" not in tags


def test_complex_limb_relation_still_applies_in_adult_scene():
    source = "一个裸体女孩坐着，右腿抬起并搭在左膝上，左脚踩地，看着镜头"
    frame = VisualSemanticNormalizer().enrich(SemanticFrame(), source)
    assert "right ankle resting across" in frame.visual_slots["limb_relation"]
    assert frame.visual_slots["gaze"] == "looking at the viewer"
    assert "happy" not in frame.visual_tags

    job = _pipeline_job(source)
    tags = {item.tag for item in job.matched_tags}
    assert "nude" in tags
    assert "crossed legs" in tags
    assert "looking at viewer" in tags
    assert "happy" not in tags
