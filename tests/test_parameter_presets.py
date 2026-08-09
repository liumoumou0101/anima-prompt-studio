import pytest

from anima_prompt_studio.domain.models import (
    CompositionFieldState, GenerationFieldState, PromptJob,
)
from anima_prompt_studio.services.pipeline import PromptPipeline


@pytest.mark.parametrize("phrase", [
    "横向构图", "横向画面", "宽幅构图", "横图", "横幅",
])
def test_explicit_landscape_phrases_override_portrait_default(phrase):
    pipeline = PromptPipeline()
    job = PromptJob(original_zh=f"一个女孩骑摩托车穿过城市，{phrase}", model_profile_id="anima_aesthetic_v1")
    pipeline.compiler.apply_model_defaults(job)
    pipeline.translate(job)
    assert job.composition.aspect == "横图"
    assert (job.generation_params.width, job.generation_params.height) == (1152, 896)
    assert "explicit_aspect" in job.composition.decision("aspect").source_rule_ids


@pytest.mark.parametrize("model,preset,expected", [
    ("anima_base_v1", "fast", (30, 4.0, "euler")),
    ("anima_base_v1", "quality", (50, 5.0, "er_sde")),
    ("anima_aesthetic_v1", "balanced", (35, 4.5, "euler")),
    ("anima_turbo_v1", "fast", (8, 1.0, "euler")),
    ("anima_turbo_v1", "quality", (12, 1.0, "euler")),
])
def test_generation_presets_are_model_specific(model, preset, expected):
    pipeline = PromptPipeline()
    job = PromptJob(model_profile_id=model)
    pipeline.apply_generation_preset(job, preset)
    params = job.generation_params
    assert (params.steps, params.cfg, params.sampler) == expected


def test_model_switch_resets_model_dependent_manual_value_but_keeps_locked_value():
    pipeline = PromptPipeline()
    job = PromptJob(model_profile_id="anima_base_v1")
    pipeline.compiler.apply_model_defaults(job)
    job.generation_params.steps = 41
    job.generation_params.set_state("steps", GenerationFieldState.USER_SELECTED)
    job.generation_params.cfg = 3.25
    job.generation_params.set_state("cfg", GenerationFieldState.LOCKED)
    job.generation_params.sampler = "custom_sampler"
    job.generation_params.scheduler = "custom_scheduler"
    job.generation_params.set_state("sampler", GenerationFieldState.USER_SELECTED)
    job.generation_params.set_state("scheduler", GenerationFieldState.USER_SELECTED)
    job.generation_params.width = 1024
    job.generation_params.height = 1024
    job.generation_params.set_state("width", GenerationFieldState.USER_SELECTED)
    job.generation_params.set_state("height", GenerationFieldState.USER_SELECTED)

    pipeline.switch_model(job, "anima_turbo_v1")
    assert job.generation_params.steps == 10
    assert job.generation_params.state("steps") == GenerationFieldState.AUTO
    assert job.generation_params.cfg == 3.25
    assert job.generation_params.sampler == "euler"
    assert job.generation_params.scheduler == "normal"
    assert job.generation_params.state("sampler") == GenerationFieldState.AUTO
    assert job.generation_params.state("scheduler") == GenerationFieldState.AUTO
    assert (job.generation_params.width, job.generation_params.height) == (1024, 1024)
    assert job.generation_params.state("width") == GenerationFieldState.USER_SELECTED
    assert job.generation_params.state("height") == GenerationFieldState.USER_SELECTED

    pipeline.apply_generation_preset(job, "quality")
    assert job.generation_params.steps == 12
    assert job.generation_params.state("steps") == GenerationFieldState.AUTO
    assert job.generation_params.cfg == 3.25
    assert job.generation_params.state("cfg") == GenerationFieldState.LOCKED


@pytest.mark.parametrize("state", [GenerationFieldState.USER_SELECTED, GenerationFieldState.LOCKED])
def test_generation_preset_never_resets_manual_or_locked_dimensions(state):
    pipeline = PromptPipeline()
    job = PromptJob(model_profile_id="anima_aesthetic_v1", generation_preset_id="balanced")
    pipeline.compiler.apply_model_defaults(job)
    job.generation_params.width = 1024
    job.generation_params.height = 1024
    job.generation_params.set_state("width", state)
    job.generation_params.set_state("height", state)

    pipeline.apply_generation_preset(job, "quality")

    params = job.generation_params
    assert (params.width, params.height) == (1024, 1024)
    assert params.state("width") == state
    assert params.state("height") == state
    assert (params.steps, params.cfg, params.sampler, params.scheduler) == (50, 5.0, "euler", "normal")


def test_manual_dimensions_are_not_overwritten_by_aspect_change():
    pipeline = PromptPipeline()
    job = PromptJob(model_profile_id="anima_aesthetic_v1")
    pipeline.compiler.apply_model_defaults(job)
    job.generation_params.width = 1024
    job.generation_params.height = 1024
    job.generation_params.set_state("width", GenerationFieldState.USER_SELECTED)
    job.generation_params.set_state("height", GenerationFieldState.USER_SELECTED)
    job.composition.aspect = "横图"
    pipeline.composition_recommender.apply_aspect_dimensions(job)
    assert (job.generation_params.width, job.generation_params.height) == (1024, 1024)


def test_composition_preset_is_editable_but_respects_locked_field():
    pipeline = PromptPipeline()
    job = PromptJob()
    job.composition.camera_height = "低机位"
    job.composition.decision("camera_height").state = CompositionFieldState.LOCKED
    pipeline.compiler.apply_model_defaults(job)
    pipeline.apply_composition_preset(job, "dynamic_action")
    assert job.composition.shot == "全身"
    assert job.composition.angle == "侧面"
    assert job.composition.gaze == "看向画外"
    assert job.composition.aspect == "横图"
    assert job.composition.camera_height == "低机位"
    assert job.composition.decision("shot").state == CompositionFieldState.USER_SELECTED


def test_long_prompt_only_adds_advisory_and_keeps_source():
    source = "。".join([
        "一个白发女孩站在雨夜城市中，回头看向远方，同时伸手握住围巾，因为她想起命运与灵魂的象征"
    ] * 7)
    pipeline = PromptPipeline()
    job = PromptJob(original_zh=source)
    pipeline.compiler.apply_model_defaults(job)
    pipeline.translate(job)
    assert job.original_zh == source
    warning = next(x for x in job.semantic_warnings if x.concept == "长提示词")
    assert warning.level.value == "yellow"
    assert "不会被自动删改" in warning.message


def test_task_package_exposes_preset_but_not_internal_parameter_states():
    job = PromptJob(generation_preset_id="quality")
    job.generation_params.set_state("steps", GenerationFieldState.LOCKED)
    package = job.task_package()
    assert package["generation_preset"] == "quality"
    assert "field_states" not in package
    assert "locked_fields" not in package
