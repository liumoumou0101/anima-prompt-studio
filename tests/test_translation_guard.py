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
