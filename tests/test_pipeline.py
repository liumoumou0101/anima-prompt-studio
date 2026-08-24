import re

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


def test_pipeline_repairs_marian_long_garter_drift_and_adds_dress_tags():
    class GarterDriftEngine:
        name = "garter-drift"

        def zh_to_en(self, _text):
            return "A young girl in a long garter."

        def en_to_zh(self, _text):
            return "一个穿长吊带的年轻女孩。"

    from anima_prompt_studio.services.translation_service import TranslationService

    pipeline = PromptPipeline(translation=TranslationService(GarterDriftEngine()))
    job = PromptJob(original_zh="一个身穿吊带长裙的年轻女孩")
    pipeline.compiler.apply_model_defaults(job)
    pipeline.translate(job)

    assert "long spaghetti-strap dress" in job.translated_en.lower()
    assert not re.search(r"\bgarters?\b", job.translated_en.lower())
    tags = {item.tag for item in job.matched_tags}
    assert {"dress", "long dress", "spaghetti strap"} <= tags
    assert "long spaghetti-strap dress" in job.positive_prompt.lower()


def test_builtin_pipeline_understands_spaghetti_strap_dress_variants():
    cases = [
        ("一个身穿吊带长裙的女孩", {"dress", "long dress", "spaghetti strap"}),
        ("一个身穿细肩带长裙的女孩", {"dress", "long dress", "spaghetti strap"}),
        ("一个身穿吊带连衣裙的女孩", {"dress", "spaghetti strap"}),
        ("一个身穿吊带裙的女孩", {"dress", "spaghetti strap"}),
    ]
    for source, expected_tags in cases:
        pipeline = PromptPipeline()
        job = PromptJob(original_zh=source)
        pipeline.compiler.apply_model_defaults(job)
        pipeline.translate(job)
        assert "spaghetti-strap dress" in job.translated_en.lower()
        assert expected_tags <= {item.tag for item in job.matched_tags}


def test_curtsy_with_spaghetti_strap_dress_preserves_complete_action():
    pipeline = PromptPipeline()
    job = PromptJob(original_zh="一个年轻女孩，穿着吊带裙，做提裙礼")
    pipeline.compiler.apply_model_defaults(job)
    pipeline.translate(job)

    lower_translation = job.translated_en.lower()
    tags, _, prose = job.positive_prompt.partition("\n\n")
    tag_set = set(tags.split(", "))
    assert "wearing a spaghetti-strap dress" in lower_translation
    assert "curtsy" in lower_translation
    assert "holding both sides of her skirt" in lower_translation
    assert not re.search(r"[\u4e00-\u9fff]", job.translated_en)
    assert {"dress", "spaghetti strap", "curtsey", "skirt hold"} <= tag_set
    assert "curtsy" not in tag_set
    assert "skirt" not in tag_set
    assert "skirt lift" not in tag_set
    assert "upskirt" not in tag_set
    assert "curtsy" in prose.lower()
    assert job.composition.shot == "全身"
    assert job.composition.angle == "三分之四"


def test_external_translation_drift_is_repaired_without_duplicate_dress_sentence():
    class CurtsyDriftEngine:
        name = "curtsy-drift"

        def zh_to_en(self, _text):
            return "A young girl in a garter's dress."

        def en_to_zh(self, text):
            return text

    from anima_prompt_studio.services.translation_service import TranslationService

    pipeline = PromptPipeline(translation=TranslationService(CurtsyDriftEngine()))
    job = PromptJob(original_zh="一个年轻女孩，穿着吊带裙，做提裙礼")
    pipeline.compiler.apply_model_defaults(job)
    pipeline.translate(job)

    lower_translation = job.translated_en.lower()
    _, _, prose = job.positive_prompt.partition("\n\n")
    assert lower_translation.count("spaghetti-strap dress") == 1
    assert "garter" not in lower_translation
    assert "curtsy" in prose.lower()
    assert "holding both sides of her skirt" in prose.lower()


def test_curtsy_synonyms_do_not_fall_back_to_skirt_lift():
    for phrase in ("提裙礼", "做提裙礼", "行提裙礼", "屈膝礼", "屈膝行礼", "行屈膝礼"):
        pipeline = PromptPipeline()
        job = PromptJob(original_zh=f"一个女孩穿着连衣裙，{phrase}")
        pipeline.compiler.apply_model_defaults(job)
        pipeline.translate(job)
        tag_section = set(job.positive_prompt.partition("\n\n")[0].split(", "))
        assert "curtsey" in tag_section
        assert "curtsy" not in tag_section
        assert "skirt lift" not in tag_section
        assert "upskirt" not in tag_section


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


def test_expanded_two_person_phrases_keep_each_subjects_attributes_and_objects():
    pipeline = PromptPipeline()
    job = PromptJob(
        original_zh="两个女孩，左边白色长发蓝瞳拿着一本书，右边黑色短发红瞳拿着一朵花，两人看向彼此"
    )
    pipeline.compiler.apply_model_defaults(job)
    pipeline.translate(job)

    assert "On the left, white hair, blue eyes, long hair, holding a book, looking at each other." in job.positive_prompt
    assert "On the right, black hair, red eyes, short hair, holding a flower, looking at each other." in job.positive_prompt
    assert "On the left, black hair" not in job.positive_prompt
    assert "On the right, white hair" not in job.positive_prompt
    tag_section = set(job.positive_prompt.partition("\n\n")[0].split(", "))
    assert "looking at viewer" not in tag_section
    assert "holding book" not in tag_section


def test_multi_person_translation_drift_is_visible_while_final_prompt_stays_scoped():
    class DriftingEngine:
        name = "drifting"

        def zh_to_en(self, _text):
            return (
                "Two girls: the left one has black long hair and red eyes and is holding a book; "
                "the right one has black short hair and red eyes and is holding a flower."
            )

        def en_to_zh(self, _text):
            return "两个女孩，左边黑色长发红瞳拿书，右边黑色短发红瞳拿花。"

    from anima_prompt_studio.services.translation_service import TranslationService

    pipeline = PromptPipeline(translation=TranslationService(DriftingEngine()))
    job = PromptJob(
        original_zh="两个女孩，左边白色长发蓝瞳拿着一本书，右边黑色短发红瞳拿着一朵花"
    )
    pipeline.translate(job)

    assert "On the left, white hair, blue eyes, long hair, holding a book." in job.positive_prompt
    warnings = [item.message for item in job.semantic_warnings if item.concept == "多人作用域"]
    assert warnings and "white hair" in warnings[0] and "blue eyes" in warnings[0]
    assert "最终 ANIMA Prompt 已优先采用中文分区事实" in warnings[0]


def test_task_package_only_exports_active_character_slots():
    job = PromptJob(character_slots=[
        CharacterSlot(display_name="A"), CharacterSlot(display_name="B"), CharacterSlot(display_name="C"),
    ])
    job.composition.people_count = 1
    assert [item["display_name"] for item in job.task_package()["characters"]] == ["A"]


def test_task_package_has_schema_and_source():
    _, job = make_job()
    package = job.task_package()
    assert package["schema_version"] == "1.5"
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
