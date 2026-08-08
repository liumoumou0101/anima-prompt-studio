import pytest

from anima_prompt_studio.domain.models import CharacterSlot, EnhancementItem, ItemState, MatchedTag, PromptJob
from anima_prompt_studio.services.config_service import ConfigService
from anima_prompt_studio.services.enhancer import PromptEnhancer
from anima_prompt_studio.services.pipeline import PromptPipeline
from anima_prompt_studio.services.prompt_compiler import COMPOSITION_MAP, PromptCompiler
from anima_prompt_studio.services.semantic_diff import SemanticDiffService
from anima_prompt_studio.services.tag_matcher import TagMatcher
from anima_prompt_studio.services.translation_service import TranslationService


class DeterministicEngine:
    name = "test"

    def zh_to_en(self, text: str) -> str:
        return {
            "一个女孩看镜头": "one girl looking at viewer",
            "一个暗精灵女孩": "one elf girl",
        }.get(text, text)

    def en_to_zh(self, text: str) -> str:
        return text


@pytest.mark.parametrize("field,value,expected", [
    ("shot", "头像", "portrait"), ("shot", "半身", "upper body"), ("shot", "全身", "full body"),
    ("camera_height", "平视", "eye level"), ("camera_height", "高机位", "from above"), ("camera_height", "低机位", "from below"),
    ("angle", "正面", "front view"), ("angle", "侧面", "from side"), ("angle", "背面", "from behind"),
    ("gaze", "看镜头", "looking at viewer"), ("gaze", "看向画外", "looking away"),
    ("subject_position", "左", "subject on left"), ("subject_position", "中", "centered"), ("subject_position", "右", "subject on right"),
])
def test_composition_mapping_is_driven_by_job(field, value, expected):
    pipeline = PromptPipeline(translation=TranslationService(DeterministicEngine()))
    job = PromptJob(translated_en="one girl")
    setattr(job.composition, field, value)
    pipeline.compiler.apply_model_defaults(job)
    pipeline.compiler.compile(job)
    assert expected in job.positive_prompt.split("\n", 1)[0]


def test_quality_switch_preserves_composition():
    pipeline = PromptPipeline(translation=TranslationService(DeterministicEngine()))
    job = PromptJob(translated_en="one girl")
    job.composition.shot = "全身"; job.composition.camera_height = "高机位"; job.composition.subject_position = "左"
    pipeline.compiler.apply_model_defaults(job)
    before = job.composition.model_copy(deep=True)
    job.quality_profile_id = "portrait_detail"; pipeline.compiler.compile(job)
    assert job.composition == before
    assert "detailed face" in job.positive_prompt


@pytest.mark.parametrize("model,steps,cfg,negative", [
    ("anima_base_v1", 35, 4.5, True), ("anima_aesthetic_v1", 35, 4.5, True), ("anima_turbo_v1", 10, 1.0, False),
])
def test_model_profiles_are_independent(model, steps, cfg, negative):
    pipeline = PromptPipeline(translation=TranslationService(DeterministicEngine()))
    job = PromptJob(translated_en="one girl")
    pipeline.switch_model(job, model)
    assert job.generation_params.steps == steps
    assert job.generation_params.cfg == cfg
    assert bool(job.negative_prompt) is negative


@pytest.mark.parametrize("model", ["anima_base_v1", "anima_aesthetic_v1", "anima_turbo_v1"])
@pytest.mark.parametrize("quality", ["draft", "standard", "portrait_detail", "ornate_illustration", "atmospheric"])
def test_every_model_quality_combination_compiles(model, quality):
    pipeline = PromptPipeline(translation=TranslationService(DeterministicEngine()))
    job = PromptJob(translated_en="one girl", quality_profile_id=quality)
    pipeline.switch_model(job, model)
    assert job.positive_prompt
    assert job.workflow_template_id


def test_locked_generation_parameter_survives_model_switch():
    pipeline = PromptPipeline(translation=TranslationService(DeterministicEngine()))
    job = PromptJob(translated_en="one girl")
    job.generation_params.steps = 77; job.generation_params.locked_fields = ["steps"]
    pipeline.switch_model(job, "anima_turbo_v1")
    assert job.generation_params.steps == 77


def test_locked_english_is_not_overwritten_by_chinese_retranslation():
    pipeline = PromptPipeline(translation=TranslationService(DeterministicEngine()))
    job = PromptJob(original_zh="一个暗精灵女孩", translated_en="User locked sentence.", translation_state="locked")
    pipeline.compiler.apply_model_defaults(job); pipeline.translate(job)
    assert job.translated_en == "User locked sentence."


def test_excluded_tag_does_not_return_after_compile():
    pipeline = PromptPipeline(translation=TranslationService(DeterministicEngine()))
    job = PromptJob(original_zh="一个女孩看镜头", excluded_tags=["looking at viewer"])
    pipeline.compiler.apply_model_defaults(job); pipeline.translate(job)
    assert "looking at viewer" not in {x.tag for x in job.matched_tags}


def test_output_keeps_tag_and_natural_language_sections_separate():
    compiler = PromptCompiler(ConfigService())
    job = PromptJob(translated_en="A girl sits by the window.")
    compiler.apply_model_defaults(job); compiler.compile(job)
    tag_section, prose = job.positive_prompt.split("\n\n", 1)
    assert "A girl" not in tag_section
    assert prose.endswith(".")


@pytest.mark.parametrize("english,forbidden", [
    ("a girl without a hat", "hat"), ("a girl not holding a sword", "sword"),
    ("a girl not holding a flower", "flower"),
])
def test_negation_scope_blocks_positive_tag(english, forbidden):
    result = TagMatcher().match(english)
    assert forbidden not in {x.tag for x in result}


def test_edited_english_controls_tag_matching():
    pipeline = PromptPipeline(translation=TranslationService(DeterministicEngine()))
    job = PromptJob(original_zh="一个女孩看镜头")
    pipeline.compiler.apply_model_defaults(job); pipeline.translate(job)
    pipeline.update_english(job, "She looks away from the viewer.")
    tags = {x.tag for x in job.matched_tags}
    assert "looking at viewer" not in tags
    assert "looking away" in tags


def test_current_appearance_overrides_character_slot_defaults():
    compiler = PromptCompiler(ConfigService())
    job = PromptJob(translated_en="a girl with short black hair", matched_tags=[
        MatchedTag(tag="black hair", category="hair"), MatchedTag(tag="short hair", category="hair_length"),
    ], character_slots=[CharacterSlot(appearance_tags=["white hair", "very long hair"])])
    compiler.apply_model_defaults(job); compiler.compile(job)
    tags = job.positive_prompt.split("\n", 1)[0]
    assert "white hair" not in tags and "very long hair" not in tags


@pytest.mark.parametrize("text", ["双手抱膝", "双臂环抱膝盖", "缩着腿抱膝"])
def test_hugging_knees_synonyms_trigger_template(text):
    items = PromptEnhancer().enhance(text)
    assert "hug_knees" in {x.id for x in items}


def test_dark_elf_strong_mapping_survives_generic_translation():
    pipeline = PromptPipeline(translation=TranslationService(DeterministicEngine()))
    job = PromptJob(original_zh="一个暗精灵女孩")
    pipeline.compiler.apply_model_defaults(job); pipeline.translate(job)
    tags = {x.tag for x in job.matched_tags}
    assert "dark elf" in tags and "elf" not in tags


def test_single_person_adds_solo():
    compiler = PromptCompiler(ConfigService()); job = PromptJob(translated_en="one girl")
    compiler.apply_model_defaults(job); compiler.compile(job)
    assert "solo" in job.positive_prompt.split("\n", 1)[0].split(", ")


def test_window_relation_offers_soft_light():
    assert "window_soft_light" in {x.id for x in PromptEnhancer().enhance("一个女孩坐在窗边")}


def test_enhancement_supports_locking():
    item = EnhancementItem(id="x", type="场景", source_rule="x", content="Soft light.")
    assert hasattr(item, "state") and item.state.value == "auto"


def test_locked_enhancement_survives_when_trigger_disappears():
    pipeline = PromptPipeline(translation=TranslationService(DeterministicEngine()))
    job = PromptJob(original_zh="一个女孩坐在窗边")
    pipeline.compiler.apply_model_defaults(job); pipeline.translate(job)
    item = next(x for x in job.enhancements if x.id == "window_soft_light")
    item.state = ItemState.LOCKED; item.content = "User locked light."
    job.original_zh = "一个女孩站在房间里"; job.normalized_zh = job.original_zh
    pipeline.recompile(job)
    locked = next(x for x in job.enhancements if x.id == "window_soft_light")
    assert locked.content == "User locked light." and locked.state.value == "locked"


def test_semantic_diff_detects_negation_loss():
    warnings = SemanticDiffService().compare("女孩没有戴帽子", "A girl wearing a hat", "女孩戴着帽子")
    assert any(x.level.value == "red" for x in warnings)


def test_semantic_diff_accepts_canonical_negative_and_overridden_attributes():
    feet = SemanticDiffService().compare(
        "女孩坐着，脚不着地", "A girl sits with her feet off the ground.", "女孩双脚离地坐着"
    )
    override = SemanticDiffService().compare(
        "女孩原本白发，后来改成黑发", "A girl with black hair.", "一个黑发女孩"
    )
    assert not any(x.level.value == "red" for x in feet)
    assert not any(x.level.value == "red" for x in override)


def test_back_angle_uses_verified_canonical_tag():
    assert COMPOSITION_MAP["angle"]["背面"] == "from behind"
