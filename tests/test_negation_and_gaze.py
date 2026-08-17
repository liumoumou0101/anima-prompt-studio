"""First-batch regressions: shared negation, gaze default, fragment tags, limb prose."""
from __future__ import annotations

from anima_prompt_studio.domain.models import PromptJob, SemanticFrame
from anima_prompt_studio.services.enhancer import PromptEnhancer
from anima_prompt_studio.services.negation import phrase_all_negated_zh, phrase_has_unnegated_zh
from anima_prompt_studio.services.pipeline import PromptPipeline
from anima_prompt_studio.services.semantic_frame import SemanticFrameResolver
from anima_prompt_studio.services.tag_matcher import TagMatcher
from anima_prompt_studio.services.visual_semantics import VisualSemanticNormalizer


def _tags(job: PromptJob) -> set[str]:
    return set(job.positive_prompt.partition("\n\n")[0].split(", "))


def _pipeline(source: str) -> PromptJob:
    job = PromptJob(original_zh=source)
    PromptPipeline().translate(job)
    return job


def test_negation_helpers_treat_没有裸体_as_fully_negated():
    text = "一个女孩穿着完整的校服站着，没有裸体"
    assert phrase_all_negated_zh(text, "裸体")
    assert not phrase_has_unnegated_zh(text, "裸体")
    assert phrase_has_unnegated_zh("一个裸体女孩", "裸体")


def test_school_uniform_not_nude_does_not_emit_nude():
    job = _pipeline("一个女孩穿着完整的校服站着，没有裸体，全身")
    tags = _tags(job)
    assert "nude" not in tags
    assert "completely nude" not in tags
    assert "explicit" not in tags
    assert "safe" in tags
    assert "nude" in {item.canonical_tag for item in job.semantic_frame.excluded_concepts}
    assert "nude" not in {concept.id.lower() for concept in job.resolved_concepts}
    assert "STATE_NUDE" not in {concept.id for concept in job.resolved_concepts}
    assert "fully clothed" in (job.translated_en or "").lower()


def test_look_away_and_not_at_camera_do_not_default_to_viewer():
    job = _pipeline("一个裸体女孩站在浴室里，看向画外，没有看镜头，全身")
    tags = _tags(job)
    assert job.semantic_frame.gaze_intent == "away"
    assert job.composition.gaze == "看向画外"
    assert "looking at viewer" not in tags
    assert "looking away" in tags
    assert "looking at viewer" in {item.canonical_tag for item in job.semantic_frame.excluded_concepts}


def test_reading_not_at_camera_is_object_gaze_not_viewer():
    job = _pipeline("一个女孩低头看书，不要看镜头")
    tags = _tags(job)
    assert job.semantic_frame.gaze_intent == "object"
    assert job.composition.gaze == "看物体"
    assert "looking at viewer" not in tags


def test_enhancer_does_not_inject_hug_knees_when_negated():
    items = PromptEnhancer().enhance("一个女孩坐在窗边，没有抱膝")
    assert "hug_knees" not in {item.id for item in items}

    job = _pipeline("一个女孩坐在窗边，没有抱膝")
    tags = _tags(job)
    assert "hug_knees" not in {item.id for item in job.enhancements}
    assert "hugging own legs" not in tags
    assert "hugging own legs" in {item.canonical_tag for item in job.semantic_frame.excluded_concepts}


def test_negated_hug_knees_does_not_restate_the_forbidden_pose():
    job = _pipeline("一个女孩坐在窗边，双手放在身侧，没有抱膝，全身")
    english = (job.translated_en or "").lower()
    assert "hug" not in english
    assert "knees" not in english
    assert "hands" in english and "side" in english
    assert "hugging own legs" not in _tags(job)


def test_pouring_tea_does_not_match_holding_hands():
    matcher = TagMatcher()
    result = matcher.match(
        "She pours tea, holding a cup in her hands",
        "一个女孩在倒茶",
    )
    assert "holding hands" not in {item.tag for item in result}

    job = _pipeline("一个女孩坐着倒茶")
    assert "holding hands" not in _tags(job)


def test_leaves_her_foot_does_not_match_leaf():
    result = TagMatcher().match("She leaves her right foot planted on the floor", "右脚踩地")
    assert "leaf" not in {item.tag for item in result}


def test_figure_four_keeps_contacts_without_detached_head_prose():
    source = "一个女孩坐着，右腿抬起并搭在左膝上，左脚踩地，全身"
    frame = VisualSemanticNormalizer().enrich(SemanticFrame(), source)
    relation = frame.visual_slots["limb_relation"]
    assert "right ankle resting across" in relation
    assert "left foot stays planted on the floor" in relation
    assert "complete head and face" not in relation
    assert "full figure from head to toe" not in relation
    assert "clear space above the head" not in relation
    assert "crossed legs" in frame.visual_tags
    assert "full body" in frame.visual_tags


def test_semantic_frame_object_gaze_beats_negated_viewer():
    frame = SemanticFrameResolver().resolve("低头看书不要看镜头")
    assert frame.gaze_intent == "object"
    assert "looking at viewer" in {item.canonical_tag for item in frame.excluded_concepts}


def test_positive_nude_and_viewer_still_resolve():
    job = _pipeline("一个裸体女孩看着镜头")
    tags = _tags(job)
    assert "nude" in tags
    assert "looking at viewer" in tags
    assert "nude" not in {item.canonical_tag for item in job.semantic_frame.excluded_concepts}
