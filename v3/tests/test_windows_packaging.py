from __future__ import annotations

from pathlib import Path

from anima_prompt_studio_v3.tools import run_desktop


ROOT = Path(__file__).parents[2]


def test_v3_pyinstaller_spec_bundles_runtime_web_and_data_pack() -> None:
    spec = (ROOT / "packaging" / "anima_prompt_studio_v3.spec").read_text(encoding="utf-8")
    assert 'ROOT / "packaging" / "run_v3.py"' in spec
    assert '"anima_prompt_studio_v3/web/dist"' in spec
    assert 'f"data-packs/{PACK_SOURCE.name}"' in spec
    assert 'name="AnimaPromptStudioV3"' in spec
    assert "console=True" in spec
    assert '"icuuc.dll", "icudt78.dll"' in spec


def test_v3_installer_has_distinct_identity_and_double_click_executable() -> None:
    installer = (ROOT / "packaging" / "installer_v3.iss").read_text(encoding="utf-8")
    assert "300000000001" in installer
    assert '#define AppExeName "AnimaPromptStudioV3.exe"' in installer
    assert "AnimaPromptStudioV3\\*" in installer
    assert "desktopicon" in installer


def test_frozen_launcher_resolves_bundled_resources(monkeypatch) -> None:
    monkeypatch.setattr(run_desktop.sys, "_MEIPASS", r"C:\portable\_internal", raising=False)
    assert run_desktop.bundled_path("data-packs") == Path(r"C:\portable\_internal\data-packs")
    assert run_desktop.bundled_path("anima_prompt_studio_v3/web/dist") == Path(
        r"C:\portable\_internal\anima_prompt_studio_v3/web/dist"
    )


def test_v3_build_script_checks_cleanup_scope_and_accepts_release_version() -> None:
    script = (ROOT / "packaging" / "build_windows_v3.ps1").read_text(encoding="utf-8")
    assert "resolvedPortable.StartsWith($distRoot" in script
    assert '"/DAppVersion=$Version"' in script
    assert "ANIMA_V3_PACK_SOURCE" in script
    assert "ANIMA-Prompt-Studio-V3-Portable" in script
    assert "--exit-after-startup" in script
    assert "Upgrade smoke changed the active data-pack pointer" in script
    assert "Upgrade smoke changed the installed reference database" in script


def test_v3_release_workflow_pins_data_pack_and_smokes_installer() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release-v3.yml").read_text(encoding="utf-8")
    assert "data_pack_url" in workflow
    assert "data_pack_sha256" in workflow
    assert "Data-pack SHA-256 mismatch" in workflow
    assert "build_windows_v3.ps1" in workflow
    assert "unins000.exe" in workflow
    assert "--exit-after-startup" in workflow
