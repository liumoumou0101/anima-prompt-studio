import pytest

from anima_prompt_studio.domain.models import Composition, CompositionFieldState, PromptJob
from anima_prompt_studio.services.config_service import ConfigService
from anima_prompt_studio.services.composition_recommender import CompositionRecommendationService
from anima_prompt_studio.services.pipeline import PromptPipeline
from anima_prompt_studio.services.translation_service import TranslationService


class EchoEngine:
    name = "echo"
    def zh_to_en(self, text): return text
    def en_to_zh(self, text): return text


@pytest.fixture
def recommender():
    configs = ConfigService()
    return CompositionRecommendationService(configs)


def recommend(recommender, text, people=1):
    job = PromptJob(original_zh=text, normalized_zh=text)
    job.composition.people_count = people
    recommender.recommend(job)
    return job


def test_mushroom_picking_golden_case(recommender):
    job = recommend(recommender, "一个暗精灵小女孩在森林里采蘑菇")
    c = job.composition
    assert (c.shot, c.camera_height, c.angle, c.gaze, c.aspect) == ("全身", "高机位", "三分之四", "看物体", "竖图")
    assert "mushroom_picking" in c.decision("shot").source_rule_ids


def test_descending_angel_golden_case(recommender):
    job = recommend(recommender, "一名天使从天而降，长着巨大的白色羽翼")
    c = job.composition
    assert c.shot == "全身" and c.camera_height == "低机位"
    assert c.aspect == "竖图" and c.subject_position == "中"


def test_train_window_golden_case(recommender):
    job = recommend(recommender, "一个女孩将头伸出列车外，瞳孔中有复杂的六角星图案")
    c = job.composition
    assert (c.shot, c.camera_height, c.angle, c.gaze) == ("半身", "平视", "三分之四", "看向画外")
    assert c.aspect == "横图" and c.subject_position == "左"


def test_explicit_terms_outrank_action_rules(recommender):
    job = recommend(recommender, "正面特写，看镜头的天使从天而降")
    assert job.composition.shot == "头像"
    assert job.composition.angle == "正面"
    assert job.composition.gaze == "看镜头"
    assert job.composition.camera_height == "低机位"


def test_knee_contact_does_not_become_cowboy_shot(recommender):
    job = recommend(recommender, "女孩把右脚踝搭在左膝上，要求全身侧前方视角")
    assert job.composition.shot == "全身"
    assert job.composition.angle == "三分之四"


def test_explicit_cowboy_shot_phrase_still_works(recommender):
    assert recommend(recommender, "女孩坐着，使用膝上景别").composition.shot == "膝上"


@pytest.mark.parametrize("state", [CompositionFieldState.USER_SELECTED, CompositionFieldState.LOCKED])
def test_manual_and_locked_values_are_preserved(recommender, state):
    job = PromptJob(original_zh="天使从天而降", normalized_zh="天使从天而降")
    job.composition.shot = "胸像"
    job.composition.decision("shot").state = state
    recommender.recommend(job)
    assert job.composition.shot == "胸像"


def test_manual_mode_disables_all_recommendations(recommender):
    job = PromptJob(original_zh="天使从天而降", normalized_zh="天使从天而降")
    job.composition.mode = "manual"
    before = job.composition.model_copy(deep=True)
    result = recommender.recommend(job)
    assert job.composition == before and result.applied_fields == []


@pytest.mark.parametrize("people,shot,aspect", [(2, "膝上", "横图"), (3, "全身", "横图"), (5, "远景", "横图")])
def test_people_count_changes_framing(recommender, people, shot, aspect):
    job = recommend(recommender, "人物站在广场上", people)
    assert job.composition.shot == shot and job.composition.aspect == aspect


@pytest.mark.parametrize("text,position", [("女孩向右看", "左"), ("女孩向左看", "右")])
def test_subject_leaves_space_in_gaze_direction(recommender, text, position):
    job = recommend(recommender, text)
    assert job.composition.subject_position == position
    assert job.composition.gaze == "看向画外"


def test_aspect_updates_unlocked_dimensions(recommender):
    job = recommend(recommender, "两个女孩并肩站着", 2)
    assert job.composition.aspect == "横图"
    assert job.generation_params.width > job.generation_params.height


def test_locked_dimensions_survive_aspect_recommendation(recommender):
    job = PromptJob(original_zh="两个女孩", normalized_zh="两个女孩")
    job.composition.people_count = 2
    job.generation_params.width = 777; job.generation_params.height = 999
    job.generation_params.locked_fields = ["width", "height"]
    recommender.recommend(job)
    assert (job.generation_params.width, job.generation_params.height) == (777, 999)


def test_reason_and_rule_source_are_recorded(recommender):
    job = recommend(recommender, "女孩读书")
    decision = job.composition.decision("gaze")
    assert decision.reason and "reading" in decision.source_rule_ids


def test_legacy_composition_payload_is_preserved_as_manual():
    composition = Composition.model_validate({"shot":"全身", "camera_height":"高机位", "angle":"侧面", "gaze":"看向画外", "aspect":"横图", "subject_position":"右"})
    assert composition.shot == "全身"
    assert all(composition.decision(field).state == CompositionFieldState.USER_SELECTED for field in composition.decisions)


def test_pipeline_compiles_recommended_gaze_without_default_viewer():
    pipeline = PromptPipeline(translation=TranslationService(EchoEngine()))
    job = PromptJob(original_zh="一个女孩在森林里采蘑菇")
    pipeline.compiler.apply_model_defaults(job); pipeline.translate(job)
    tags = job.positive_prompt.partition("\n\n")[0].split(", ")
    assert "looking at object" in tags
    assert "looking at viewer" not in tags


def test_alternative_recommendation_changes_ranked_fields_but_keeps_explicit_intent(recommender):
    text = "看镜头的天使从天而降"
    job = recommend(recommender, text)
    best = (job.composition.shot, job.composition.camera_height, job.composition.angle, job.composition.aspect)
    assert job.composition.gaze == "看镜头"

    result = recommender.recommend(job, alternative_index=1)
    alternative = (job.composition.shot, job.composition.camera_height, job.composition.angle, job.composition.aspect)

    assert alternative != best
    assert job.composition.gaze == "看镜头"
    assert result.alternative_fields


def test_classic_composition_presets_are_available(recommender):
    expected = {
        "cowboy_shot", "front_fullbody", "low_angle_hero", "high_angle",
        "back_view", "thirds_left", "thirds_right", "cinematic_wide", "two_person",
    }
    assert expected <= set(recommender.configs.composition_presets)


def test_generic_portrait_alternative_uses_classic_preset(recommender):
    job = recommend(recommender, "一个短发女孩看向镜头微笑")
    best = (job.composition.shot, job.composition.camera_height, job.composition.angle, job.composition.aspect)
    result = recommender.recommend(job, alternative_index=1)
    alternative = (job.composition.shot, job.composition.camera_height, job.composition.angle, job.composition.aspect)
    assert alternative != best
    assert result.fallback_preset_id == "portrait_closeup"
    assert job.composition.shot == "头像"
    assert job.composition.aspect == "方形"
    assert job.composition.gaze == "看镜头"


def test_generic_portrait_can_cycle_to_a_second_classic_preset(recommender):
    job = recommend(recommender, "一个短发女孩看向镜头微笑")
    first = recommender.recommend(job, alternative_index=1)
    second = recommender.recommend(job, alternative_index=2)
    assert first.fallback_preset_id != second.fallback_preset_id
    assert job.composition.shot == "全身"
    assert job.composition.angle == "正面"


def test_mushroom_alternative_changes_only_one_nonsemantic_field(recommender):
    job = recommend(recommender, "一个暗精灵蹲在地上采蘑菇")
    best = {field: getattr(job.composition, field) for field in recommender.VALID_VALUES}

    result = recommender.recommend(job, alternative_index=1)
    changed = {
        field for field, old_value in best.items()
        if getattr(job.composition, field) != old_value
    }

    assert len(changed) == 1
    assert changed == set(result.alternative_fields)
    assert job.composition.gaze == "看物体"
    assert job.composition.shot == "膝上"
    assert job.composition.camera_height == "高机位"
    assert job.composition.angle == "三分之四"
    assert job.composition.subject_position == "左"
