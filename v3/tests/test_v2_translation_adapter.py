from anima_prompt_studio_v3.adapters.v2 import build_v2_local_translation_adapter


def test_translation_adapter_uses_offline_fallback_without_models(tmp_path) -> None:
    adapter = build_v2_local_translation_adapter(tmp_path / "missing-resources")

    result = adapter.translate("一个女孩，白发，微笑", direction="zh_en")

    assert result.direction == "zh_en"
    assert result.engine_name == "内置离线基础翻译"
    assert "girl" in result.translated_text.lower()
    assert adapter.model_ready is False


def test_translation_adapter_rejects_unknown_direction(tmp_path) -> None:
    adapter = build_v2_local_translation_adapter(tmp_path / "missing-resources")

    try:
        adapter.translate("女孩", direction="auto")
    except ValueError as exc:
        assert "zh_en" in str(exc)
    else:
        raise AssertionError("unknown direction was accepted")
