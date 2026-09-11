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


def test_v3_never_discovers_or_loads_marian_even_with_existing_resources(tmp_path, monkeypatch):
    from anima_prompt_studio.services.resource_manager import ResourceManager
    from anima_prompt_studio.services.translation_service import LocalMarianEngine, LazyLocalMarianEngine
    def forbidden(*args, **kwargs):
        raise AssertionError("V3 must not inspect or load neural translation models")
    monkeypatch.setattr(ResourceManager, "__init__", forbidden)
    monkeypatch.setattr(LocalMarianEngine, "__init__", forbidden)
    monkeypatch.setattr(LazyLocalMarianEngine, "__init__", forbidden)
    (tmp_path / "config.json").write_text("{}")
    adapter = build_v2_local_translation_adapter(tmp_path)
    assert adapter.model_ready is False
    assert "girl" in adapter.translate("女孩", direction="zh_en").translated_text
    assert "女孩" in adapter.translate("girl", direction="en_zh").translated_text
