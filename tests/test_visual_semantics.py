import re

import pytest

from anima_prompt_studio.domain.models import MatchedTag, PromptJob, SemanticFrame
from anima_prompt_studio.services.pipeline import PromptPipeline
from anima_prompt_studio.services.translation_service import TranslationService
from anima_prompt_studio.services.visual_semantics import VisualSemanticNormalizer


@pytest.fixture(scope="module")
def normalizer() -> VisualSemanticNormalizer:
    return VisualSemanticNormalizer()


@pytest.mark.parametrize(("source", "slot", "canonical", "tag"), [
    ("金色瞳孔", "eyes", "golden eyes", "golden eyes"),
    ("蓝色瞳孔", "eyes", "blue eyes", "blue eyes"),
    ("绿色眼", "eyes", "green eyes", "green eyes"),
    ("浅棕色头发", "hair", "light brown hair", "light brown hair"),
    ("粉色头发", "hair", "pink hair", "pink hair"),
])
def test_colour_and_body_part_are_composed_from_catalog(normalizer, source, slot, canonical, tag):
    frame = normalizer.enrich(SemanticFrame(), f"一个{source}的角色")
    assert frame.visual_slots[slot] == canonical
    assert tag in frame.visual_tags


@pytest.mark.parametrize(("source", "canonical", "tag"), [
    ("半精灵", "half-elf", "elf"),
    ("半妖精", "half-fairy", "fairy"),
    ("半天使", "half-angel", "angel"),
    ("半暗精灵", "half-dark elf", "dark elf"),
])
def test_half_modifier_composes_with_catalog_races(normalizer, source, canonical, tag):
    frame = normalizer.enrich(SemanticFrame(), f"一个{source}角色")
    assert frame.visual_slots["race"] == canonical
    assert tag in frame.visual_tags


@pytest.mark.parametrize("source", [
    "看着窗外", "看向窗外", "望着窗外", "望向窗外", "凝视窗外", "注视窗外",
])
def test_gaze_verb_and_target_share_one_relation(normalizer, source):
    frame = normalizer.enrich(SemanticFrame(), f"女孩{source}")
    assert frame.visual_slots["gaze"] == "looking out the window"
    assert frame.gaze_intent == "away"
    assert "looking away" in frame.visual_tags


@pytest.mark.parametrize("emotion", ["忧郁", "忧伤", "惆怅", "落寞", "愁苦"])
def test_melancholy_synonyms_share_one_semantic_family(normalizer, emotion):
    frame = normalizer.enrich(SemanticFrame(), f"女孩神色{emotion}")
    assert frame.visual_slots["emotion"] == "melancholic expression"
    assert "sad" in frame.visual_tags


class PlaceholderAwareBadEngine:
    name = "placeholder-aware-bad-engine"

    def zh_to_en(self, text: str) -> str:
        # Emulates an unreliable MT engine while preserving the opaque visual
        # tokens, which is the contract exercised by the semantic protection.
        tokens = re.findall(r"ZSQ\d+QSZ", text, flags=re.I)
        return f"A character, {', '.join(tokens)}, sitting by the window."

    def en_to_zh(self, text: str) -> str:
        return text


def test_pipeline_uses_one_semantic_result_for_translation_tags_enhancement_and_gaze():
    source = "一个半精灵，白色头发，金色瞳孔，坐在窗边，看着窗外，神色忧郁"
    pipe = PromptPipeline(translation=TranslationService(PlaceholderAwareBadEngine()))
    job = PromptJob(original_zh=source)
    pipe.compiler.apply_model_defaults(job)
    pipe.translate(job)

    translated = job.translated_en.lower()
    assert {"half-elf", "white hair", "golden eyes", "melancholic expression", "looking out the window"} <= {
        value.lower() for value in job.semantic_frame.visual_slots.values()
    }
    assert all(value in translated for value in (
        "half-elf", "white hair", "golden eyes", "melancholic expression", "looking out the window",
    ))
    assert "smurf" not in translated and "looking blue" not in translated

    tags = set(job.positive_prompt.partition("\n\n")[0].split(", "))
    assert {"elf", "white hair", "golden eyes", "sad", "looking away"} <= tags
    assert "looking at viewer" not in tags
    assert job.composition.gaze == "看向画外"
    assert "weak_emotion" not in {item.id for item in job.enhancements}


def test_only_generated_combinations_are_protected(normalizer):
    direct = normalizer.enrich(SemanticFrame(), "白发金瞳的天使")
    direct_text, direct_replacements = normalizer.protect("白发金瞳的天使", direct)
    assert direct_text == "白发金瞳的天使"
    assert direct_replacements == []

    composed = normalizer.enrich(SemanticFrame(), "金色瞳孔的半天使")
    composed_text, replacements = normalizer.protect("金色瞳孔的半天使", composed)
    assert len(replacements) == 2
    assert "金色瞳孔" not in composed_text and "半天使" not in composed_text


def test_semantic_tags_respect_locked_single_value_attribute(normalizer):
    frame = normalizer.enrich(SemanticFrame(), "白色头发的女孩")
    current = [MatchedTag(tag="black hair", category="hair", state="locked")]
    merged = normalizer.merge_tags(current, frame, excluded=set(), locked={"black hair"})
    assert [item.tag for item in merged] == ["black hair"]


def test_scene_specific_wall_interaction_is_not_hardcoded(normalizer):
    frame = normalizer.enrich(
        SemanticFrame(),
        "女孩从狭窄不规则墙洞中挤出上半身，双手扶住洞口",
    )
    assert "spatial_relation" not in frame.visual_slots
    assert not {"through wall", "hole", "stuck", "punching"} & set(frame.visual_tags)


def test_cross_limb_relation_preserves_sides_contacts_and_full_body(normalizer):
    source = "右腿抬起并搭在左膝上，左脚踩地，右脚脚尖向下，一只手扶着抬起的膝盖，身体微微后仰，全身侧前方视角"
    frame = normalizer.enrich(SemanticFrame(), source)
    relation = frame.visual_slots["limb_relation"]
    assert "right ankle resting across their left knee" in relation
    assert "left foot stays planted on the floor" in relation
    assert "right toes point downward" in relation
    assert "full figure from head to toe" in relation
    assert "front three-quarter view" in relation
    assert {"crossed legs", "arched back", "full body", "three-quarter view"} <= set(frame.visual_tags)
    assert "leg up" not in frame.visual_tags


def test_pipeline_protects_complex_limb_relation_from_bad_translation():
    source = "一个成年女性精灵坐在高脚凳边缘，右腿抬起并搭在左膝上，左脚踩地，右脚脚尖向下，一只手扶着抬起的膝盖，身体微微后仰，全身侧前方视角"
    pipe = PromptPipeline(translation=TranslationService(PlaceholderAwareBadEngine()))
    job = PromptJob(original_zh=source)
    pipe.translate(job)
    tags = set(job.positive_prompt.partition("\n\n")[0].split(", "))
    assert "right ankle resting across her left knee" in job.canonical_prose
    assert job.composition.shot == "全身"
    assert job.composition.angle == "三分之四"
    assert {"crossed legs", "full body", "three-quarter view"} <= tags
    assert not {"horns", "cowboy shot", "stairs", "looking back", "on back", "hands up"} & tags


def test_turbo_warns_for_complex_limb_relation():
    pipe = PromptPipeline(translation=TranslationService(PlaceholderAwareBadEngine()))
    job = PromptJob(
        original_zh="女孩坐着，右脚踝搭在左膝上，左脚踩地",
        model_profile_id="anima_turbo_v1",
    )
    pipe.translate(job)
    warning = next(item for item in job.semantic_warnings if item.concept == "复杂肢体关系")
    assert warning.level.value == "yellow"
    assert "ANIMA Base" in warning.message


def test_base_does_not_receive_turbo_relation_warning():
    pipe = PromptPipeline(translation=TranslationService(PlaceholderAwareBadEngine()))
    job = PromptJob(
        original_zh="女孩坐着，右脚踝搭在左膝上，左脚踩地",
        model_profile_id="anima_base_v1",
    )
    pipe.translate(job)
    assert "复杂肢体关系" not in {item.concept for item in job.semantic_warnings}
