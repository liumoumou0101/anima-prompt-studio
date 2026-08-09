from anima_prompt_studio.services import translation_service
from anima_prompt_studio.tools import resource_setup


def test_marian_runtime_requires_all_optional_packages(monkeypatch):
    available = {"torch": object(), "transformers": object(), "sentencepiece": None}
    monkeypatch.setattr(translation_service.importlib.util, "find_spec", lambda name: available[name])
    assert translation_service.marian_runtime_available() is False
    available["sentencepiece"] = object()
    assert translation_service.marian_runtime_available() is True


def test_resource_setup_requires_explicit_download_scope():
    try:
        resource_setup.main([])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("resource_setup without --tags/--models must not start a full download")
