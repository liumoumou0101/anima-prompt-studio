import pytest

from anima_prompt_studio_v3.storage.official_examples import OfficialPack
from anima_prompt_studio_v3.tools.build_example_pack import build_manifest
from test_official_examples import pack


def source(tmp_path):
    root = pack(tmp_path / "source")
    (root / "examples-pack.json").unlink()
    return root


def test_build_round_trip_preserves_images_and_can_install(tmp_path):
    root = source(tmp_path)
    image = root / "media/off_one/original.webp"
    original = image.read_bytes()
    evidence = root / "SOURCES"
    evidence.mkdir()
    (evidence / "provenance.json").write_text('{"fixture":true}')
    result = build_manifest(root, "curation-v1")
    assert result.counts.examples == 1
    assert result.counts.files == 5
    assert image.read_bytes() == original
    manager = OfficialPack(tmp_path / "installed")
    assert manager.install(root)["ready"]


def test_existing_manifest_is_never_overwritten(tmp_path):
    root = pack(tmp_path / "source")
    manifest = root / "examples-pack.json"
    original = manifest.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        build_manifest(root, "new-id")
    assert manifest.read_bytes() == original


@pytest.mark.parametrize("bad_file", ["media/off_one/original.webp", "catalog.json"])
def test_invalid_source_leaves_no_manifest_and_keeps_input(tmp_path, bad_file):
    root = source(tmp_path)
    (root / bad_file).write_bytes(b"invalid data")
    with pytest.raises(ValueError):
        build_manifest(root, "bad-source")
    assert not (root / "examples-pack.json").exists()
    assert (root / bad_file).read_bytes() == b"invalid data"


def test_unexpected_local_file_is_not_accidentally_packaged(tmp_path):
    root = source(tmp_path)
    (root / ".env").write_text("private configuration")
    with pytest.raises(ValueError, match="Unexpected file"):
        build_manifest(root, "bad-source")
    assert not (root / "examples-pack.json").exists()
