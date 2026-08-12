from anima_prompt_studio.domain.models import CharacterSlot, ItemState, PromptJob
from anima_prompt_studio.services.pipeline import PromptPipeline


def make_job(text="一个白发金瞳的女孩坐在桌边，双腿垂下，清晨看镜头"):
    pipeline = PromptPipeline()
    job = PromptJob(original_zh=text)
    pipeline.compiler.apply_model_defaults(job)
    return pipeline, pipeline.translate(job)


def test_full_offline_pipeline():
    _, job = make_job()
    assert job.translated_en and job.back_translated_zh
    assert "white hair" in job.positive_prompt
    assert "legs dangling" in job.positive_prompt
    assert "Soft morning light" in job.positive_prompt


def test_user_english_is_not_retranslated():
    pipeline, job = make_job()
    pipeline.update_english(job, "one girl with short black hair")
    assert job.translation_state == ItemState.USER_EDITED
    assert job.translated_en == "one girl with short black hair"
    assert "short hair" in job.positive_prompt


def test_excluded_tag_stays_excluded():
    pipeline, job = make_job()
    job.excluded_tags.append("white hair")
    pipeline.recompile(job)
    assert all(x.tag != "white hair" for x in job.matched_tags)
    assert "white hair" not in job.positive_prompt.split("\n", 1)[0].split(", ")


def test_model_switch_keeps_input_and_changes_params():
    pipeline, job = make_job()
    source = job.original_zh
    pipeline.switch_model(job, "anima_aesthetic_v1")
    assert job.original_zh == source
    assert job.generation_params.steps == 35
    assert job.negative_prompt
    pipeline.switch_model(job, "anima_turbo_v1")
    assert job.generation_params.steps == 10
    assert job.negative_prompt == ""


def test_score_tag_keeps_required_underscore():
    pipeline, job = make_job()
    pipeline.switch_model(job, "anima_base_v1")
    assert "score_7" in job.positive_prompt.split("\n", 1)[0]


def test_multi_person_features_are_scoped():
    pipeline = PromptPipeline()
    job = PromptJob(original_zh="两个女孩", character_slots=[
        CharacterSlot(position="left", display_name="A", appearance_tags=["white hair"], action_text="holding a book"),
        CharacterSlot(position="right", display_name="B", appearance_tags=["black hair"], action_text="holding a flower"),
    ])
    job.composition.people_count = 2
    pipeline.compiler.apply_model_defaults(job)
    pipeline.translate(job)
    assert "On the left, A, white hair, holding a book." in job.positive_prompt
    assert "On the right, B, black hair, holding a flower." in job.positive_prompt


def test_custom_multi_person_positions_are_not_overwritten_by_slot_order():
    pipeline = PromptPipeline()
    job = PromptJob(translated_en="Two people.", character_slots=[
        CharacterSlot(position="foreground", display_name="A"),
        CharacterSlot(position="background", display_name="B"),
    ])
    job.composition.people_count = 2
    pipeline.compiler.apply_model_defaults(job)
    pipeline.compiler.compile(job)
    assert "In the foreground, A." in job.positive_prompt
    assert "In the background, B." in job.positive_prompt


def test_one_and_another_are_split_into_scoped_slots_with_mixed_gaze():
    pipeline = PromptPipeline()
    job = PromptJob(original_zh="一个白发女孩看镜头，另一个黑发女孩看向前方")
    pipeline.compiler.apply_model_defaults(job)
    pipeline.translate(job)

    assert job.composition.people_count == 2
    assert job.character_slots[0].appearance_tags == ["white hair"]
    assert job.character_slots[0].action_text == "looking at viewer"
    assert job.character_slots[1].appearance_tags == ["black hair"]
    assert job.character_slots[1].action_text == "looking forward"
    tag_section = set(job.positive_prompt.partition("\n\n")[0].split(", "))
    assert not {"looking at viewer", "looking forward", "looking away"} & tag_section
    assert "On the left, white hair, looking at viewer." in job.positive_prompt
    assert "On the right, black hair, looking forward." in job.positive_prompt


def test_task_package_only_exports_active_character_slots():
    job = PromptJob(character_slots=[
        CharacterSlot(display_name="A"), CharacterSlot(display_name="B"), CharacterSlot(display_name="C"),
    ])
    job.composition.people_count = 1
    assert [item["display_name"] for item in job.task_package()["characters"]] == ["A"]


def test_task_package_has_schema_and_source():
    _, job = make_job()
    package = job.task_package()
    assert package["schema_version"] == "1.4"
    assert package["composition"]["shot"]
    assert package["source"]["original_zh"] == job.original_zh
    assert "canonical_prose" in package and "subject_mode" in package and "excluded_concepts" in package


def test_scene_task_package_omits_inactive_character_slots():
    job = PromptJob(original_zh="夜晚月光下的森林", character_slots=[CharacterSlot(display_name="inactive")])
    pipe = PromptPipeline(); pipe.compiler.apply_model_defaults(job); pipe.translate(job)
    package = job.task_package()
    assert package["subject_mode"] == "scene"
    assert package["composition"]["people_count"] == 0
    assert package["characters"] == []
