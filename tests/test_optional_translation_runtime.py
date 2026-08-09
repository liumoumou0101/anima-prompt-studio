from pathlib import Path

from anima_prompt_studio.services import translation_service
from anima_prompt_studio.services.resource_manager import ResourceManager
from anima_prompt_studio.tools import resource_setup
from anima_prompt_studio.tools import verify_translation_env


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


def test_translation_environment_inspector_reports_cpu_and_missing_models(monkeypatch, tmp_path):
    class FakeTorchVersion:
        cuda = None

    class FakeCuda:
        @staticmethod
        def is_available():
            return False

    class FakeTorch:
        version = FakeTorchVersion()
        cuda = FakeCuda()

    monkeypatch.setattr(verify_translation_env.importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(verify_translation_env.importlib.metadata, "version", lambda _name: "test-version")
    monkeypatch.setattr(verify_translation_env.importlib, "import_module", lambda name: FakeTorch() if name == "torch" else None)

    status = verify_translation_env.inspect_environment(ResourceManager(tmp_path))
    assert status["runtime_ready"] is True
    assert status["torch"] == {"backend": "CPU", "cuda_build": None, "cuda_available": False}
    assert status["models_ready"] is False
    assert all(item["available"] is False for item in status["models"].values())


def test_cpu_install_script_uses_official_cpu_index():
    script = (Path(__file__).parents[1] / "install_translation_cpu.ps1").read_text(encoding="utf-8")
    assert "https://download.pytorch.org/whl/cpu" in script
    assert "--require-models" in script
