import pytest

from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio.services.config_service import ConfigService
from anima_prompt_studio.services.prompt_compiler import PromptCompiler


ULTIMATE_PROFILE_IDS = (
    "ultimate_general",
    "ultimate_character",
    "ultimate_portrait",
    "ultimate_scene",
    "ultimate_landscape_architecture",
    "ultimate_action",
    "ultimate_material",
    "ultimate_adult",
)


def _tags(profile_id: str) -> set[str]:
    return set(ConfigService().quality_profiles[profile_id].all_tags())


def _compiled_tags(profile_id: str, source: str) -> set[str]:
    configs = ConfigService()
    compiler = PromptCompiler(configs)
    job = PromptJob(
        original_zh=source,
        normalized_zh=source,
        translated_en="A subject.",
        quality_profile_id=profile_id,
    )
    compiler.apply_model_defaults(job)
    compiler.compile(job)
    return set(job.positive_prompt.partition("\n\n")[0].split(", "))


def test_ultimate_quality_profiles_are_complete_and_uncensored_by_default():
    profiles = ConfigService().quality_profiles
    assert set(ULTIMATE_PROFILE_IDS) <= set(profiles)

    for profile_id in ULTIMATE_PROFILE_IDS:
        profile = profiles[profile_id]
        tags = profile.all_tags()
        assert profile.notes
        assert {"masterpiece", "best quality", "highres", "absurdres"} <= set(tags)
        assert "safe" not in tags
        assert len(tags) == len({tag.casefold() for tag in tags})


def test_ultimate_general_does_not_change_subject_style_time_or_composition():
    forbidden = {
        "safe",
        "uncensored",
        "anime illustration",
        "painterly",
        "cel shading",
        "night",
        "day",
        "cyberpunk atmosphere",
        "dynamic pose",
        "dynamic angle",
        "action shot",
        "wide shot",
        "portrait",
        "detailed breasts",
        "sheer fabric",
    }
    assert _tags("ultimate_general").isdisjoint(forbidden)


def test_ultimate_character_and_adult_profiles_remain_gender_neutral():
    gender_or_body_specific = {
        "1girl",
        "1boy",
        "female",
        "male",
        "detailed breasts",
        "nipples",
        "penis",
        "vagina",
    }
    assert _tags("ultimate_character").isdisjoint(gender_or_body_specific)
    assert _tags("ultimate_adult").isdisjoint(gender_or_body_specific)
    assert "uncensored" not in _tags("ultimate_character")
    assert "uncensored" in _tags("ultimate_adult")
    assert "explicit" in _tags("ultimate_adult")


def test_quality_profiles_do_not_emit_unrecognized_hand_detail_phrases():
    configs = ConfigService()
    for profile in configs.quality_profiles.values():
        assert {"detailed hands", "detailed fingers"}.isdisjoint(profile.all_tags())


def test_removed_and_harmful_quality_tags_stay_out_of_the_catalog():
    configs = ConfigService()
    assert "sharp_focus" not in configs.quality_profiles
    assert "daylight_clear" in configs.quality_profiles
    assert "indoor_warm" in configs.quality_profiles
    assert "overcast_rain" in configs.quality_profiles
    for profile in configs.quality_profiles.values():
        assert "anatomical detail" not in profile.all_tags(), profile.id
        assert "crisp lines" not in profile.all_tags(), profile.id
        if profile.id != "flat_color":
            assert "clean lineart" not in profile.all_tags(), profile.id


def test_daylight_clear_does_not_override_an_explicit_night_scene():
    tags = _compiled_tags("daylight_clear", "夜晚月光下的短发女孩")
    assert not {"sunlight", "bright lighting", "clear sky"} & tags


def test_indoor_warm_does_not_move_an_outdoor_scene_inside():
    tags = _compiled_tags("indoor_warm", "一个女孩站在海边")
    assert not {"indoor lighting", "lamp light", "cozy atmosphere"} & tags
    room = _compiled_tags("indoor_warm", "一个女孩坐在房间里")
    assert {"indoor lighting", "lamp light", "cozy atmosphere"} <= room


def test_overcast_rain_does_not_override_an_explicit_sunny_day():
    tags = _compiled_tags("overcast_rain", "晴天街道上的短发女孩")
    assert not {"overcast", "rain", "fog", "mist"} & tags
    rainy = _compiled_tags("overcast_rain", "一个女孩站在小巷里")
    assert {"overcast", "rain", "fog", "mist"} <= rainy
    dry = _compiled_tags("overcast_rain", "一个女孩站着，没有下雨")
    assert "rain" not in dry


def test_adult_and_character_packs_do_not_compile_anatomical_detail():
    for profile_id in ("uncensored_detail", "ultimate_adult", "ultimate_character"):
        tags = _compiled_tags(profile_id, "一个裸体女孩站着")
        assert "anatomical detail" not in tags


def test_ultimate_material_profile_does_not_invent_clothing_type_or_transparency():
    assert _tags("ultimate_material").isdisjoint(
        {"lingerie", "lace details", "sheer fabric", "latex", "bikini"}
    )


def test_body_detail_does_not_add_female_specific_parts_to_a_man():
    tags = _compiled_tags("body_detail", "一个穿西装的男人")
    assert "1boy" in tags and "1girl" not in tags
    assert "detailed breasts" not in tags
    assert "detailed navel" not in tags


def test_lingerie_focus_does_not_make_an_opaque_coat_sheer_or_lacy():
    tags = _compiled_tags("lingerie_focus", "一个人穿着厚重不透明的冬季外套")
    assert not {"sheer fabric", "lace details"} & tags


def test_night_neon_does_not_override_an_explicit_day_scene():
    tags = _compiled_tags("night_neon", "正午阳光下的城市街道")
    assert not {"night", "neon lights", "cyberpunk atmosphere", "rim lighting"} & tags


def test_explicit_daytime_neon_is_preserved_without_inventing_night():
    tags = _compiled_tags("night_neon", "白天仍然亮着霓虹灯的街道")
    assert "neon lights" in tags
    assert "night" not in tags


def test_action_dynamic_does_not_animate_an_explicitly_still_pose():
    tags = _compiled_tags("action_dynamic", "人物保持静止，一动不动")
    assert not {"dynamic angle", "motion lines", "speed lines", "dynamic pose", "action shot"} & tags


@pytest.mark.parametrize(("source", "expected"), [
    ("一个女孩站在窗边", "safe"),
    ("一个女孩穿着蕾丝内衣", "sensitive"),
    ("一个裸体女孩", "explicit"),
    ("一个女孩穿着完整的校服站着，没有裸体", "safe"),
])
def test_safety_level_is_derived_from_content_not_quality_pack(source: str, expected: str):
    tags = _compiled_tags("dramatic_light", source)
    safety = tags & {"safe", "sensitive", "nsfw", "explicit"}
    assert safety == {expected}


@pytest.mark.parametrize("model_id", ["anima_base_v1", "anima_aesthetic_v1", "anima_turbo_v1"])
@pytest.mark.parametrize("quality_id", ULTIMATE_PROFILE_IDS)
def test_every_ultimate_profile_compiles_for_every_model(model_id: str, quality_id: str):
    configs = ConfigService()
    compiler = PromptCompiler(configs)
    job = PromptJob(translated_en="one person", quality_profile_id=quality_id)
    compiler.apply_model_defaults(job)
    job.model_profile_id = model_id
    compiler.apply_model_defaults(job)
    compiler.compile(job)

    tag_section = job.positive_prompt.partition("\n\n")[0]
    for tag in configs.quality_profiles[quality_id].all_tags():
        assert tag in tag_section
