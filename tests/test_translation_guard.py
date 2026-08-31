import re

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


def test_right_hand_book_is_not_copied_to_hanging_left_hand():
    result = TranslationService._guard_visual_terms(
        "一个女孩站着，右手拿着一本合上的书，左手自然垂在身侧，半身",
        "A girl standing with a book on her right hand and a book on her left hand Upper body shot.",
    )
    lower = result.lower()
    assert lower.count("book") == 1
    assert "right hand" in lower
    assert "left hand hangs empty" in lower


def test_split_hands_keep_distinct_objects():
    result = TranslationService._guard_visual_terms(
        "一个女孩用右手提起白色茶壶，把茶倒进左手拿着的蓝色杯子里",
        "A girl lifts a white teapot in her right hand and pours it into a blue cup in her left hand",
    )
    lower = result.lower()
    assert "teapot" in lower and "right hand" in lower
    assert "cup" in lower and "left hand" in lower
    assert "teapot in her left" not in lower
    assert "cup in her right" not in lower


def test_long_spaghetti_strap_dress_is_not_translated_as_garter():
    result = TranslationService._guard_visual_terms(
        "一个身穿吊带长裙的年轻女孩",
        "A young girl in a long garter.",
    )
    lower = result.lower()
    assert "long spaghetti-strap dress" in lower
    assert not re.search(r"\bgarters?\b", lower)


def test_real_marian_strap_dress_variants_are_replaced_not_duplicated():
    cases = [
        (
            "一个身穿细肩带长裙的年轻女孩",
            "A young girl in a long skirt with a strap on her shoulder.",
            "long spaghetti-strap dress",
        ),
        (
            "一个身穿吊带裙的年轻女孩",
            "A young girl in a hanging dress.",
            "spaghetti-strap dress",
        ),
    ]
    for source, translated, expected in cases:
        result = TranslationService._guard_visual_terms(source, translated).lower()
        assert expected in result
        assert "hanging dress" not in result
        assert "skirt with a strap" not in result


def test_possessive_garter_dress_variants_are_replaced_not_duplicated():
    cases = (
        "A young girl in a garter's dress.",
        "A young girl in a garter’s dress.",
        "A young girl in a garter dress.",
        "A young girl in a hanging dress.",
    )
    for translated in cases:
        result = TranslationService._guard_visual_terms(
            "一个年轻女孩，穿着吊带裙，做提裙礼",
            translated,
        ).lower()
        assert result.count("spaghetti-strap dress") == 1
        assert not re.search(r"\bgarters?(?:['’]s)?\b", result)
        assert "hanging dress" not in result


def test_spaghetti_strap_dress_gets_an_article_after_wearing_or_in():
    cases = (
        "A young girl wearing spaghetti-strap dress.",
        "A young girl in spaghetti-strap dress.",
    )
    for translated in cases:
        result = TranslationService._guard_visual_terms(
            "一个年轻女孩穿着吊带裙",
            translated,
        ).lower()
        assert "a spaghetti-strap dress" in result


def test_real_garter_belt_and_stockings_are_not_changed_by_dress_guard():
    result = TranslationService._guard_visual_terms(
        "女孩穿着吊带袜和吊袜带",
        "A girl wearing thighhighs and a garter belt.",
    )
    assert "garter belt" in result.lower()
