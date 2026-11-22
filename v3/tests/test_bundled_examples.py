from pathlib import Path
import subprocess
import sys
import tarfile
from zipfile import ZipFile

import pytest

from anima_prompt_studio_v3.storage import bundled_examples
from anima_prompt_studio_v3.storage.official_examples import OfficialPack
from anima_prompt_studio_v3.storage.reference_examples import ExampleStore, ExampleNotes
from anima_prompt_studio_v3.tools import install_example_pack, run_desktop


def test_bundled_install_preserves_personal_notes_on_reinstall(tmp_path):
    destination = tmp_path / "official-examples"
    bundled_examples.install_bundled_examples(destination)
    store = ExampleStore(tmp_path / "examples.db")
    store.save_official_notes("off_cma_166868", 0, ExampleNotes(user_notes="保留我的备注"))
    bundled_examples.install_bundled_examples(destination)
    assert store.get("off_cma_166868")["notes"]["user_notes"] == "保留我的备注"
    assert store.list()["official_pack"]["count"] == 3


def test_desktop_install_does_not_require_frontend_or_start_server(tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Installation must not start the API server")
    monkeypatch.setattr(run_desktop, "LocalApiServer", unexpected)
    assert run_desktop.main(["--install-bundled-examples", "--workspace-db", str(tmp_path / "workspaces.db")]) == 0
    assert OfficialPack(tmp_path / "official-examples").current()[1].pack_id == bundled_examples.PACK_ID
    assert not (tmp_path / "workspaces.db").exists()


@pytest.mark.parametrize("source_args", [[], ["some-pack", "--bundled"]])
def test_cli_rejects_ambiguous_source_before_install(tmp_path, monkeypatch, source_args):
    monkeypatch.setattr(sys, "argv", ["install", *source_args, "--destination", str(tmp_path / "official")])
    with pytest.raises(SystemExit) as caught:
        install_example_pack.main()
    assert caught.value.code == 2
    assert not (tmp_path / "official").exists()


def test_frozen_missing_pack_does_not_use_development_copy(monkeypatch):
    monkeypatch.setattr(bundled_examples.sys, "frozen", True, raising=False)
    with pytest.raises(FileNotFoundError):
        bundled_examples.bundled_example_source()


def test_actual_wheel_ships_verified_pack_and_installs_outside_checkout(tmp_path):
    project = Path(__file__).resolve().parents[1]
    sdist = subprocess.run([sys.executable, "setup.py", "sdist", "--dist-dir", str(tmp_path / "sdist")],
                           cwd=project, capture_output=True, text=True, errors="replace", timeout=60)
    assert sdist.returncode == 0, sdist.stderr[-4000:]
    with tarfile.open(next((tmp_path / "sdist").glob("*.tar.gz"))) as archive:
        archive.extractall(tmp_path / "source", filter="data")
    source_project = next((tmp_path / "source").iterdir())
    result = subprocess.run([
        sys.executable, "setup.py", "build", "--build-base", str(tmp_path / "build"),
        "bdist_wheel", "--dist-dir", str(tmp_path / "dist"), "--bdist-dir", str(tmp_path / "bdist"),
    ], cwd=source_project, capture_output=True, text=True, errors="replace", timeout=120)
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-4000:]
    extracted = tmp_path / "installed"
    with ZipFile(next((tmp_path / "dist").glob("*.whl"))) as archive:
        archive.extractall(extracted)
    source = extracted / "anima_prompt_studio_v3/example_packs" / bundled_examples.PACK_ID
    manifest, entries = OfficialPack.validate(source)
    assert len(entries) == 3
    canonical = project / "example-packs" / bundled_examples.PACK_ID
    for name in ["examples-pack.json", *[item.path for item in manifest.files]]:
        assert (source / name).read_bytes() == (canonical / name).read_bytes()
    # -I plus an explicit wheel path prevents falling back to this checkout's V3.
    script = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv.pop(1))
from anima_prompt_studio_v3.storage.bundled_examples import bundled_example_source
assert Path(sys.path[0]) in bundled_example_source().parents
from anima_prompt_studio_v3.tools.install_example_pack import main
main()
"""
    run = subprocess.run([sys.executable, "-I", "-c", script, str(extracted), "--bundled",
                          "--destination", str(tmp_path / "user" / "official-examples")],
                         cwd=tmp_path, capture_output=True, text=True, errors="replace", timeout=30)
    assert run.returncode == 0, run.stderr
    assert OfficialPack(tmp_path / "user" / "official-examples").current()[1].counts.examples == 3
