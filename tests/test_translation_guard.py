from anima_prompt_studio.services.translation_service import TranslationService


def test_white_hair_corrects_blonde_drift():
    result = TranslationService._guard_visual_terms("白发女孩", "A blonde girl.")
    assert "white-haired" in result
    assert "blonde" not in result


def test_missing_eye_colour_is_restored():
    result = TranslationService._guard_visual_terms("金瞳女孩", "A girl.")
    assert "golden eyes" in result


def test_guard_does_not_invent_unspecified_features():
    result = TranslationService._guard_visual_terms("一个女孩", "A girl.")
    assert result == "A girl."


def test_full_body_shot_does_not_become_all_over_the_body():
    result = TranslationService._guard_visual_terms(
        "一个女孩坐在高脚凳上，全身",
        "A girl sits on a stool, all over her body, all over her face.",
    )
    assert "all over" not in result.lower()
    assert "full body" in result.lower()


def test_closed_umbrella_is_not_opened():
    result = TranslationService._guard_visual_terms(
        "女孩左手提着闭合的雨伞",
        "A girl holds an open umbrella in her left hand.",
    )
    assert "open umbrella" not in result.lower()
    assert "closed umbrella" in result.lower()


def test_two_modified_girls_are_not_collapsed_to_singular():
    result = TranslationService._guard_visual_terms(
        "两个裸体女孩在做爱",
        "Girls having sex.",
    )
    assert not result.startswith("A girl")


def test_rolling_eyes_does_not_invert_the_composition():
    result = TranslationService._guard_visual_terms(
        "一个高潮中的裸体女孩露出阿嘿颜，舌头伸出，眼睛上翻，半身",
        "A nude girl in a climax shows his face, her eyes are upside down.",
    )
    assert "upside down" not in result.lower()
    assert "upside-down" not in result.lower()
    assert "rolling eyes" in result.lower()


def test_bare_all_over_from_full_body_is_stripped():
    result = TranslationService._guard_visual_terms(
        "两个裸体女孩在做爱，没有男孩，全身",
        "Two nude girls having sex, no boys, all over yuri.",
    )
    assert "all over" not in result.lower()
    assert "full body" in result.lower()


def test_hanging_hand_is_not_fallen_down():
    result = TranslationService._guard_visual_terms(
        "一个女孩站着，右手把自己的裙摆提起来，左手自然垂下，全身",
        "A girl stood, her right hand raised her skirt, and her left hand fell down, full body",
    )
    assert "fell down" not in result.lower()
    assert "fallen down" not in result.lower()
    assert "left hand hangs" in result.lower()


def test_negated_hug_knees_is_deleted_not_restated():
    result = TranslationService._guard_visual_terms(
        "一个女孩坐在窗边，双手放在身侧，没有抱膝，全身",
        "A girl sits by the window, hands on her side, no knees, full body",
    )
    lower = result.lower()
    assert "no knees" not in lower
    assert "hug" not in lower
    assert "knees" not in lower
    assert "hands" in lower and "side" in lower


def test_negated_hug_knees_does_not_keep_not_hugging_phrase():
    result = TranslationService._guard_visual_terms(
        "一个女孩坐在窗边，双手放在身侧，没有抱膝，全身",
        "A girl sits by the window, not hugging her knees, full body",
    )
    lower = result.lower()
    assert "hug" not in lower
    assert "knees" not in lower
    assert "hands at her sides" in lower


def test_hanging_hand_is_not_falling_on_her_side():
    result = TranslationService._guard_visual_terms(
        "一个裸体女孩站着，右手放在自己的胸口，左手自然垂在身侧，半身",
        "A nude girl standing, right hand on her chest, left hand falling on her side, half body",
    )
    assert "falling" not in result.lower()
    assert "left hand hangs" in result.lower()


def test_reverse_cowgirl_cleans_rides_back_debris():
    result = TranslationService._guard_visual_terms(
        "一个裸体女孩反骑乘，背对男孩坐在他身上，全身",
        "A nude girl rides back and backs to the boy and sits on him full body Reverse cowgirl",
    )
    lower = result.lower()
    assert "rides back" not in lower
    assert "backs to the boy" not in lower
    assert "back to the boy" in lower
    assert "reverse cowgirl" in lower


def test_clothed_not_nude_keeps_fully_clothed():
    result = TranslationService._guard_visual_terms(
        "一个女孩穿着完整的校服站着，没有裸体，全身",
        "A girl standing in a full school uniform, not naked, full body",
    )
    assert "naked" not in result.lower()
    assert "nude" not in result.lower()
    assert "fully clothed" in result.lower()


def test_mug_is_not_marquee_and_singular_cup_stays_singular():
    result = TranslationService._guard_visual_terms(
        "一个女孩右手端着一只白色杯子",
        "A girl holds a marquee in her right hand, white cups.",
    )
    assert "marquee" not in result.lower()
    assert "cups" not in result.lower()
    assert "mug" in result.lower()


def test_reading_one_book_does_not_become_two_books():
    result = TranslationService._guard_visual_terms(
        "一个女孩低头看书，没有看镜头，半身",
        "A girl looks down at two books.",
    )
    assert "books" not in result.lower()
    assert "book" in result.lower()
