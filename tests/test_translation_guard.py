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
