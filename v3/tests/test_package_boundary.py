from anima_prompt_studio_v3 import __version__
from anima_prompt_studio_v3.adapters.v2 import CandidateToV2PromptJobAdapter
import inspect
import anima_prompt_studio_v3.adapters.v2.generation as generation_adapter
import anima_prompt_studio_v3.adapters.v2.natural_language as natural_language_adapter
import anima_prompt_studio_v3.adapters.v2.gallery as gallery_adapter
import anima_prompt_studio_v3.adapters.v2.translation as translation_adapter


def test_v3_package_has_independent_version() -> None:
    assert __version__ == "0.1.0"


def test_v2_adapter_imports_without_loading_v2_ui() -> None:
    assert CandidateToV2PromptJobAdapter.__module__.endswith("adapters.v2.generation")
    assert "anima_prompt_studio.ui" not in inspect.getsource(generation_adapter)


def test_natural_language_adapter_reuses_extraction_but_not_v2_prompt_pipeline() -> None:
    source = inspect.getsource(natural_language_adapter)
    assert "anima_prompt_studio.ui" not in source
    assert "PromptPipeline" not in source
    assert "PromptCompiler" not in source
    assert "prompt_compiler" not in source


def test_gallery_adapter_reuses_services_without_v2_http_or_ui_layer() -> None:
    source = inspect.getsource(gallery_adapter)
    assert "anima_prompt_studio.ui" not in source
    assert "gallery_server" not in source
    assert "PySide6" not in source


def test_translation_adapter_reuses_only_the_local_translation_service() -> None:
    source = inspect.getsource(translation_adapter)
    assert "TranslationService" in source
    assert "PromptPipeline" not in source
    assert "PromptCompiler" not in source
    assert "from_pretrained" not in source
    assert "anima_prompt_studio.ui" not in source
