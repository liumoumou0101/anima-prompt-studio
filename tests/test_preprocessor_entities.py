from anima_prompt_studio.services.entity_protector import EntityProtector
from anima_prompt_studio.services.input_preprocessor import InputPreprocessor


def test_normalization_preserves_lines_and_normalizes_width():
    assert InputPreprocessor().normalize("ＡＮＩＭＡ　测试，  好\n第二行") == "ANIMA 测试, 好\n第二行"


def test_entity_round_trip():
    service = EntityProtector()
    protected, entities = service.protect("薇尔莉特用 @rurudo 风格", [("薇尔莉特", "character")])
    assert "薇尔莉特" not in protected and "@rurudo" not in protected
    assert service.restore(protected, entities) == "薇尔莉特用 @rurudo 风格"


def test_locked_syntax_is_restored_without_brackets():
    service = EntityProtector()
    protected, entities = service.protect("[[Special Name]]")
    assert service.restore(protected, entities) == "Special Name"


def test_placeholder_shape_survives_marian_style_text():
    service = EntityProtector()
    protected, entities = service.protect("薇尔莉特", [("薇尔莉特", "character")])
    assert protected.startswith("ZXQ") and protected.endswith("QXZ")
    assert service.restore(protected, entities) == "薇尔莉特"
