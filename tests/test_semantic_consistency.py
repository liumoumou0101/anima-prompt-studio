from anima_prompt_studio.domain.models import EnhancementItem, ItemState, LoRAProfile, LoRASelection, PromptJob, SubjectMode
from anima_prompt_studio.services.pipeline import PromptPipeline
from anima_prompt_studio.services.translation_service import TranslationService


class DriftEngine:
    name = "semantic-drift"

    def zh_to_en(self, text):
        if "白发金瞳" in text:
            return "A white-haired blonde girl."
        if "蓝色长发红瞳" in text:
            return "A blue-haired, long-haired, red-skinned girl."
        if "脚不着地" in text:
            return "The girl sits on a platform and doesn't have a foot."
        if "倚着窗户看向远方" in text:
            return "The girl looked away from the window."
        if "原本是白发" in text:
            return "The character was black-haired, but this time it's black and short."
        if "场景不是白天" in text:
            return "It's not the day, it's the moon at night."
        if "不在室外" in text:
            return "A girl aren't out there. They're inside."
        if "回头看向镜头" in text:
            return "The girl looks back at the camera."
        if "ZXQ" in text and "and" in text:
            return text
        if "白发女孩" in text:
            return "A white-haired girl."
        return text

    def en_to_zh(self, text):
        return text


def pipeline():
    return PromptPipeline(translation=TranslationService(DriftEngine()))


def test_visual_guards_remove_hallucinated_attributes():
    white = PromptJob(original_zh="一个白发金瞳的女孩")
    blue = PromptJob(original_zh="一个蓝色长发红瞳的女孩")
    pipeline().translate(white)
    pipeline().translate(blue)
    assert "blonde" not in white.translated_en.lower()
    assert "skinned" not in blue.translated_en.lower()
    assert ", girl" not in blue.translated_en.lower()
    assert "character has blue hair" not in blue.translated_en.lower()


def test_feet_off_ground_replaces_missing_foot_hallucination():
    job = PromptJob(original_zh="女孩坐在高台边缘，脚不着地")
    pipeline().translate(job)
    assert "doesn't have a foot" not in job.positive_prompt.lower()
    assert "feet off the ground" in job.positive_prompt.lower()


def test_artist_directive_compiles_as_tag_not_natural_prose():
    job = PromptJob(original_zh="用 @artist_example 的画风画一个白发女孩")
    pipeline().translate(job)
    tags, _, prose = job.positive_prompt.partition("\n\n")
    assert "@artist_example" in tags.split(", ")
    assert "@artist_example" not in prose
    assert "painting" not in prose.lower() and "wind" not in tags.split(", ")


def test_two_character_entities_infer_plural_people_count():
    job = PromptJob(original_zh="艾莉丝和贝拉站在窗边")
    pipeline().translate(job, [("艾莉丝", "character"), ("贝拉", "character")])
    tags = job.positive_prompt.partition("\n\n")[0].split(", ")
    assert job.composition.people_count == 2
    assert "solo" not in tags and "1girl" not in tags


def test_left_right_hand_scope_replaces_broken_translation():
    source = "女孩右手撩头发，左手拿书，同时看向窗外"
    job = PromptJob(original_zh=source)
    pipeline().translate(job)
    prose = job.positive_prompt.partition("\n\n")[2].lower()
    assert "touches her hair with her right hand" in prose
    assert "holds a book in her left hand" in prose
    assert "hair on her right hand" not in prose


def test_right_hand_object_does_not_copy_onto_hanging_left_hand():
    job = PromptJob(original_zh="一个女孩站着，右手拿着一本合上的书，左手自然垂在身侧，半身")
    pipeline().translate(job)
    prose = job.positive_prompt.partition("\n\n")[2].lower()
    assert "closed book" in prose or "book" in prose
    assert "right hand" in prose
    assert "left hand hangs empty" in prose
    assert prose.count("book") == 1


def test_skirt_lift_keeps_right_action_and_empty_left_hand():
    job = PromptJob(original_zh="一个女孩站着，右手把自己的裙摆提起来，左手自然垂下，全身")
    pipeline().translate(job)
    prose = job.positive_prompt.partition("\n\n")[2].lower()
    assert "lifts her skirt with her right hand" in prose
    assert "left hand hangs empty" in prose


def test_pour_tea_keeps_teapot_and_cup_on_opposite_hands():
    job = PromptJob(original_zh="一个女孩用右手提起白色茶壶，把茶倒进左手拿着的蓝色杯子里")
    pipeline().translate(job)
    prose = job.positive_prompt.partition("\n\n")[2].lower()
    assert "teapot in her right hand" in prose
    assert "cup in her left hand" in prose
    assert "pours" in prose


def test_single_right_hand_scope_corrects_plural_translation():
    service = TranslationService(type("Engine", (), {
        "name": "hand-drift",
        "zh_to_en": lambda self, text: "An elf raises her skirt with her hands.",
        "en_to_zh": lambda self, text: text,
    })())
    translated = service.zh_to_en("一个精灵，她用右手把自己的裙摆提起来")
    assert "with her right hand" in translated
    assert "with her hands" not in translated


def test_skirt_lift_variant_keeps_right_hand_and_emits_canonical_action_tag():
    source = "一个精灵，她用右手把自己的裙摆提起来"
    service = TranslationService(type("Engine", (), {
        "name": "hand-drift",
        "zh_to_en": lambda self, text: "An elf raises her skirt with her hands.",
        "en_to_zh": lambda self, text: text,
    })())
    job = PromptJob(original_zh=source)
    PromptPipeline(translation=service).translate(job)
    tags, _, prose = job.positive_prompt.partition("\n\n")
    assert "skirt lift" in tags.split(", ")
    assert "upskirt" not in tags.split(", ")
    assert "with her right hand" in prose
    assert "with her hands" not in prose
    assert prose.count("skirt lift") == 0


def test_single_left_hand_scope_is_restored_when_translation_drops_it():
    service = TranslationService(type("Engine", (), {
        "name": "hand-drift",
        "zh_to_en": lambda self, text: "A woman lifts the cup.",
        "en_to_zh": lambda self, text: text,
    })())
    translated = service.zh_to_en("一个女人用左手举起杯子")
    assert "left hand" in translated
    assert "right hand" not in translated


def test_explicit_both_hands_are_not_reduced_to_one_hand():
    service = TranslationService(type("Engine", (), {
        "name": "hand-drift",
        "zh_to_en": lambda self, text: "A woman holds the box in her hand.",
        "en_to_zh": lambda self, text: text,
    })())
    translated = service.zh_to_en("一个女人双手抱着箱子")
    assert "both hands" in translated


def test_canonical_prose_aligns_window_gaze_and_removes_bad_translation():
    job = PromptJob(original_zh="女孩倚着窗户看向远方")
    pipeline().translate(job)
    tags, _, prose = job.positive_prompt.partition("\n\n")
    assert "looks into the distance" in prose.lower()
    assert "looked away from the window" not in prose.lower()
    assert "looking away" in tags and "looking at viewer" not in tags


def test_conflict_history_collapses_to_winning_attribute_sentence():
    job = PromptJob(original_zh="角色原本是白发，但本次改成黑色短发")
    pipeline().translate(job)
    assert job.canonical_prose == "The character has short black hair."
    assert "this time" not in job.positive_prompt.lower()


def test_scene_mode_omits_character_defaults():
    job = PromptJob(original_zh="场景不是白天，而是夜晚月光下")
    pipeline().translate(job)
    tags = job.positive_prompt.partition("\n\n")[0].split(", ")
    assert job.effective_subject_mode() == SubjectMode.SCENE
    assert not {"1girl", "solo", "looking at viewer", "upper body", "centered"} & set(tags)
    assert {"night", "moonlight", "wide shot"} <= set(tags)
    assert job.composition.people_count == 0
    assert (job.composition.angle, job.composition.gaze, job.composition.subject_position) == ("无", "无", "无")


def test_person_pronoun_keeps_character_mode():
    job = PromptJob(original_zh="从背后拍摄她")
    pipeline().translate(job)
    assert job.effective_subject_mode() == SubjectMode.CHARACTER
    assert "looking away" in job.positive_prompt.partition("\n\n")[0].split(", ")


def test_explicit_negation_is_tracked_and_added_to_enabled_negative_prompt():
    job = PromptJob(original_zh="女孩不在室外，而是在室内", model_profile_id="anima_base_v1")
    pipe = pipeline(); pipe.compiler.apply_model_defaults(job); pipe.translate(job)
    assert "outdoors" in {x.canonical_tag for x in job.semantic_frame.excluded_concepts}
    assert "outdoors" in job.negative_prompt.split(", ")
    assert "outdoors" not in job.positive_prompt.partition("\n\n")[0].split(", ")


def test_lora_mention_binds_real_catalog_profile_without_overwriting_manual_selection():
    profile = LoRAProfile(
        id="RouWeiStyle", display_name="RouWeiStyle", file_name="RouWeiStyle.safetensors",
        default_weight=.9, trigger_words=["rouwei style"], type="style",
    )
    pipe = PromptPipeline(translation=TranslationService(DriftEngine()), lora_profiles=[profile])
    job = PromptJob(original_zh="使用 RouWeiStyle LoRA 绘制一个女孩")
    pipe.translate(job, [("RouWeiStyle", "lora")])
    assert len(job.lora_selection) == 1
    assert job.lora_selection[0].model_dump() == {
        "logical_id": "RouWeiStyle", "file_name": "RouWeiStyle.safetensors",
        "weight": .9, "trigger_words": ["rouwei style"], "source": "text_derived",
    }
    assert "rouwei style" in job.positive_prompt.partition("\n\n")[0].split(", ")
    assert job.canonical_prose_ready is True
    assert "RouWeiStyle" not in job.canonical_prose


def test_intentionally_empty_canonical_prose_does_not_fall_back_to_raw_translation():
    job = PromptJob(translated_en="A girl.", canonical_prose="", canonical_prose_ready=True)
    pipe = pipeline()
    pipe.compiler.apply_model_defaults(job)
    pipe.compiler.compile(job)
    assert "\n\n" not in job.positive_prompt


def test_locked_translation_is_not_replaced_by_auto_canonical_rule():
    job = PromptJob(
        original_zh="场景不是白天，而是夜晚月光下",
        normalized_zh="场景不是白天，而是夜晚月光下",
        translated_en="User locked scene sentence.", translation_state="locked",
    )
    pipe = pipeline(); pipe.recompile(job)
    assert "User locked scene sentence." in job.canonical_prose


def test_camera_gaze_target_does_not_become_object_tag():
    job = PromptJob(original_zh="女孩回头看向镜头")
    pipeline().translate(job)
    tags = job.positive_prompt.partition("\n\n")[0].split(", ")
    assert "looking at viewer" in tags and "looking back" in tags
    assert "camera" not in tags


def test_user_edited_translation_is_authoritative_over_auto_conflict_rewrite():
    job = PromptJob(original_zh="角色原本是白发，但本次改成黑色短发")
    pipe = pipeline(); pipe.translate(job)
    pipe.update_english(job, "User describes a custom silver-haired character.")
    assert job.canonical_prose.startswith("User describes a custom silver-haired character")


def edited_job(chinese: str, english: str, *, locked: bool = False) -> PromptJob:
    job = PromptJob(
        original_zh=chinese, normalized_zh=chinese, translated_en=english,
        translation_state=ItemState.LOCKED if locked else ItemState.USER_EDITED,
        model_profile_id="anima_base_v1",
    )
    pipe = pipeline(); pipe.compiler.apply_model_defaults(job); pipe.recompile(job)
    return job


def test_edited_english_replaces_old_window_pose_and_auto_enhancements():
    job = edited_job("一个女孩坐在窗边", "A girl stands in a forest.")
    tags = set(job.positive_prompt.partition("\n\n")[0].split(", "))
    assert {"standing", "forest"} <= tags
    assert not {"sitting", "window"} & tags
    assert job.enhancements == []
    assert "window" not in job.canonical_prose.casefold()


def test_edited_english_reverses_old_hat_exclusion_and_negative():
    job = edited_job("女孩没有戴帽子", "A girl wearing a hat.")
    assert "hat" in job.positive_prompt.partition("\n\n")[0].split(", ")
    assert "hat" not in {x.canonical_tag for x in job.semantic_frame.excluded_concepts}
    assert "hat" not in job.negative_prompt.split(", ")


def test_edited_english_replaces_old_night_scene_with_daylight_character():
    job = edited_job("场景不是白天，而是夜晚月光下", "A girl stands in daylight.")
    tags = set(job.positive_prompt.partition("\n\n")[0].split(", "))
    assert job.effective_subject_mode() == SubjectMode.CHARACTER
    assert {"1girl", "daylight", "standing"} <= tags
    assert not {"night", "moonlight"} & tags
    assert "day" not in {x.canonical_tag for x in job.semantic_frame.excluded_concepts}


def test_edited_english_controls_people_count_and_solo_tag():
    job = edited_job("一个女孩站在窗边", "Two girls stand by the window.")
    tags = set(job.positive_prompt.partition("\n\n")[0].split(", "))
    assert job.composition.people_count == 2
    assert "2girls" in tags and not {"1girl", "solo"} & tags


def test_edited_english_controls_gaze_without_old_viewer_fact():
    job = edited_job("女孩看镜头", "A girl looks away into the distance.")
    tags = set(job.positive_prompt.partition("\n\n")[0].split(", "))
    assert job.semantic_frame.gaze_intent == "away"
    assert job.composition.gaze == "看向画外"
    assert "looking away" in tags and "looking at viewer" not in tags


def test_locked_english_has_same_authority_and_is_not_rewritten():
    english = "A girl stands in a forest."
    job = edited_job("一个女孩坐在窗边", english, locked=True)
    assert job.canonical_prose == english
    assert "window" not in job.positive_prompt.casefold()
    assert job.translation_state == ItemState.LOCKED


def test_edited_english_can_bind_a_real_lora_profile():
    profile = LoRAProfile(
        id="RouWeiStyle", display_name="RouWeiStyle", file_name="RouWeiStyle.safetensors",
        default_weight=.9, trigger_words=["rouwei style"], type="style",
    )
    pipe = PromptPipeline(translation=TranslationService(DriftEngine()), lora_profiles=[profile])
    job = PromptJob(
        original_zh="一个女孩", normalized_zh="一个女孩",
        translated_en="A girl using RouWeiStyle LoRA.", translation_state=ItemState.USER_EDITED,
    )
    pipe.recompile(job)
    assert [x.logical_id for x in job.lora_selection] == ["RouWeiStyle"]
    assert "rouwei style" in job.positive_prompt.partition("\n\n")[0].split(", ")


def test_text_derived_lora_follows_authoritative_text_but_manual_and_locked_survive():
    profiles = [
        LoRAProfile(id="StyleA", display_name="StyleA", file_name="StyleA.safetensors", trigger_words=["style a"]),
        LoRAProfile(id="StyleB", display_name="StyleB", file_name="StyleB.safetensors", trigger_words=["style b"]),
    ]
    pipe = PromptPipeline(translation=TranslationService(DriftEngine()), lora_profiles=profiles)
    job = PromptJob(original_zh="使用 StyleA LoRA 绘制一个女孩")
    pipe.translate(job, [("StyleA", "lora"), ("StyleB", "lora")])
    assert [(x.logical_id, x.source) for x in job.lora_selection] == [("StyleA", "text_derived")]
    pipe.update_english(job, "A girl using StyleB LoRA.")
    assert [(x.logical_id, x.source) for x in job.lora_selection] == [("StyleB", "text_derived")]
    pipe.update_english(job, "A girl.")
    assert job.lora_selection == []

    job.lora_selection = [
        LoRASelection(logical_id="StyleA", file_name="StyleA.safetensors", source="manual"),
        LoRASelection(logical_id="StyleB", file_name="StyleB.safetensors", source="locked"),
    ]
    pipe.update_english(job, "A girl.")
    assert [(x.logical_id, x.source) for x in job.lora_selection] == [("StyleA", "manual"), ("StyleB", "locked")]


def test_text_derived_artist_follows_authority_but_manual_and_locked_survive():
    pipe = pipeline()
    job = PromptJob(original_zh="使用 @rurudo 的画风画一个女孩")
    pipe.translate(job)
    assert job.artist_selection == ["@rurudo"]
    assert job.artist_selection_sources == {"@rurudo": "text_derived"}
    pipe.update_english(job, "A girl with white hair.")
    assert job.artist_selection == [] and job.artist_selection_sources == {}

    job.artist_selection = ["@manual", "@locked"]
    job.artist_selection_sources = {"@manual": "manual", "@locked": "locked"}
    pipe.update_english(job, "A girl.")
    assert job.artist_selection == ["@manual", "@locked"]
    assert job.artist_selection_sources == {"@manual": "manual", "@locked": "locked"}


def test_curated_authority_tags_work_without_downloaded_tag_database(tmp_path):
    from anima_prompt_studio.repositories.tag_database import TagDatabase
    pipe = pipeline()
    pipe.matcher.database = TagDatabase(tmp_path / "missing.db")
    forest = PromptJob(original_zh="旧中文", normalized_zh="旧中文")
    pipe.update_english(forest, "A girl stands in a forest.")
    assert {"standing", "forest"} <= set(forest.positive_prompt.partition("\n\n")[0].split(", "))
    hat = PromptJob(original_zh="旧中文", normalized_zh="旧中文")
    pipe.update_english(hat, "A girl wearing a hat.")
    assert "hat" in hat.positive_prompt.partition("\n\n")[0].split(", ")


def test_edited_english_discards_auto_enhancement_but_keeps_user_enhancement():
    job = PromptJob(
        original_zh="一个女孩坐在窗边", normalized_zh="一个女孩坐在窗边",
        translated_en="A girl stands in a forest.", translation_state=ItemState.USER_EDITED,
        enhancements=[
            EnhancementItem(id="old", type="auto", source_rule="old", content="She sits by the window."),
            EnhancementItem(id="mine", type="user", source_rule="user", content="Custom mist.", state=ItemState.USER_EDITED),
        ],
    )
    pipeline().recompile(job)
    assert [x.id for x in job.enhancements] == ["mine"]
    assert "Custom mist." in job.canonical_prose


def test_auto_canonical_prose_cleans_known_v1_tail_cases():
    cases = [
        ("女孩坐在桌边，双腿垂下", "The girl sat at the table with her legs down.",
         "She sits on the edge of the table with both legs dangling freely, her feet off the ground."),
        ("女孩把头发拨到耳后", "The girl put her hair behind her ear.",
         "She gently raises one hand and tucks a strand of hair behind her ear."),
        ("女孩用右手撩头发", "The girl touches her hair with her right hand.",
         "right hand"),
        ("女孩低头看镜头", "The girl looks down at the camera.",
         "She lowers her head and looks directly at the camera positioned below her."),
        ("愤怒的女孩站在雨中", "Angry girls standing in the rain.",
         "An angry girl stands in the rain."),
    ]
    for chinese, translated, required in cases:
        job = PromptJob(original_zh=chinese, normalized_zh=chinese, translated_en=translated)
        pipeline().recompile(job)
        assert required in job.canonical_prose
        assert "The girl ." not in job.canonical_prose
        assert not job.cleanliness_failures


def test_touching_hair_and_explicit_hair_tuck_remain_distinct():
    touching = PromptJob(
        original_zh="女孩用右手撩头发", normalized_zh="女孩用右手撩头发",
        translated_en="The girl touches her hair with her right hand.",
    )
    tucked = PromptJob(
        original_zh="女孩用右手把头发拨到耳后", normalized_zh="女孩用右手把头发拨到耳后",
        translated_en="The girl puts her hair behind her ear with her right hand.",
    )
    pipe = pipeline(); pipe.recompile(touching); pipe.recompile(tucked)
    touching_tags = set(touching.positive_prompt.partition("\n\n")[0].split(", "))
    tucked_tags = set(tucked.positive_prompt.partition("\n\n")[0].split(", "))
    assert "right hand" in touching.canonical_prose and "behind her ear" not in touching.canonical_prose
    assert "hand in hair" in touching_tags and "hair tuck" not in touching_tags
    assert "right hand" in tucked.canonical_prose and "behind her ear" in tucked.canonical_prose
    assert "hair tuck" in tucked_tags
