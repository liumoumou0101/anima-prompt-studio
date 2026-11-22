from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess

import pytest

from anima_prompt_studio_v3.tools import run_desktop


ROOT = Path(__file__).parents[2]


def test_v3_pyinstaller_spec_bundles_runtime_web_and_data_pack() -> None:
    spec = (ROOT / "packaging" / "anima_prompt_studio_v3.spec").read_text(encoding="utf-8")
    assert 'ROOT / "packaging" / "run_v3.py"' in spec
    assert '"anima_prompt_studio_v3/web/dist"' in spec
    assert 'f"data-packs/{PACK_SOURCE.name}"' in spec
    assert 'name="AnimaPromptStudioV3"' in spec
    for package in ("runtime", "remote", "storage"):
        assert f'collect_submodules("anima_prompt_studio_v3.{package}")' in spec
    assert "console=True" in spec
    assert '"icuuc.dll", "icudt78.dll"' in spec
    assert 'OfficialPack.validate(EXAMPLE_SOURCE)' in spec
    assert 'anima_prompt_studio_v3/example_packs/{EXAMPLE_SOURCE.name}' in spec


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
    assert "[string]::Equals($resolvedPortable, $expectedPortable" in script
    assert "[string]::Equals($resolvedParent, $distRoot" in script
    assert "[IO.FileAttributes]::ReparsePoint" in script
    assert "ValidatePattern" in script
    assert '"/DAppVersion=$Version"' in script
    assert "ANIMA_V3_PACK_SOURCE" in script
    assert "ANIMA-Prompt-Studio-V3-Portable" in script
    assert "--exit-after-startup" in script
    assert "Upgrade smoke changed the active data-pack pointer" in script
    assert "Upgrade smoke changed the installed reference database" in script
    assert "--install-bundled-examples" in script
    assert "Upgrade smoke changed the active example-pack pointer" in script


def test_v3_release_workflow_pins_data_pack_and_smokes_installer() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release-v3.yml").read_text(encoding="utf-8")
    assert "data_pack_url" in workflow
    assert "data_pack_sha256" in workflow
    assert "Data-pack SHA-256 mismatch" in workflow
    assert "build_windows_v3.ps1" in workflow
    assert "unins000.exe" in workflow
    assert "--exit-after-startup" in workflow


@pytest.mark.skipif(os.name != "nt", reason="Windows reparse point and PowerShell safety")
@pytest.mark.parametrize("redirected", ["dist", "portable", "child", "release"])
def test_build_refuses_redirected_output_without_touching_its_target(tmp_path: Path, redirected: str) -> None:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        pytest.skip("PowerShell is unavailable")
    build_root = tmp_path / "workspace"
    script = build_root / "packaging" / "build_windows_v3.ps1"
    script.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "packaging" / script.name, script)
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "data-pack.json").write_text("{}", encoding="utf-8")
    protected = tmp_path / "protected"
    protected.mkdir()
    sentinel = protected / "keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    target = {"dist": build_root / "dist", "portable": build_root / "dist/AnimaPromptStudioV3",
              "child": build_root / "dist/AnimaPromptStudioV3/redirected", "release": build_root / "release"}[redirected]
    target.parent.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, "ANIMA_TEST_OUTPUT": str(target), "ANIMA_TEST_PROTECTED": str(protected)}
    made = subprocess.run([shell, "-NoProfile", "-Command",
                           "New-Item -ItemType Junction -Path $env:ANIMA_TEST_OUTPUT -Target $env:ANIMA_TEST_PROTECTED | Out-Null"],
                          env=environment, capture_output=True, timeout=15)
    assert made.returncode == 0, made.stderr.decode(errors="replace")
    result = subprocess.run([shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                             "-DataPackSource", str(pack), "-SkipWebBuild", "-SkipInstaller", "-SkipExeSmoke"],
                            capture_output=True, timeout=15)
    assert result.returncode != 0
    assert b"Refusing" in result.stdout + result.stderr
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert target.exists()
