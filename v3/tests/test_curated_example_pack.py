from hashlib import sha256
import json
from pathlib import Path

from anima_prompt_studio_v3.core.requirements import Requirements, apply_pin
from anima_prompt_studio_v3.storage.reference_examples import ExampleStore
from anima_prompt_studio_v3.storage.official_examples import OfficialPack


def test_curated_pack_installs_with_provenance_and_style_only_pins(tmp_path):
    source = Path(__file__).resolve().parents[1] / "example-packs/cma-styles-20260910-v1"
    manifest, entries = OfficialPack.validate(source)
    assert manifest.counts.examples == 3
    assert {entry.id for entry in entries} == {"off_cma_144688", "off_cma_166868", "off_cma_159769"}
    store = ExampleStore(tmp_path / "examples.db")
    store.official.install(source)
    assert store.list()["official_pack"]["ready"]
    for entry in entries:
        evidence = json.loads((source / f"SOURCES/{entry.id}.json").read_bytes())
        original = (source / entry.media).read_bytes()
        assert evidence["share_license_status"] == "CC0"
        assert evidence["packaged_webp_sha256"] == sha256(original).hexdigest()
        assert evidence["url"] and evidence["creators"]
        assert entry.requirements.layers.subject.text
        assert entry.requirements.layers.style.medium
        assert not entry.requirements.layers.style.artists
        assert not entry.requirements.loras
        target = Requirements.empty()
        target.layers.subject.text = "A single robot reading a book"
        pinned = apply_pin(target, entry.requirements, "style")
        assert pinned.layers.subject == target.layers.subject
        assert pinned.layers.style.text == entry.requirements.layers.style.text
        assert pinned.layers.lighting == target.layers.lighting
        assert pinned.layers.composition == target.layers.composition
        assert store.content(entry.id)[0].read_bytes() == original
        assert store.thumbnail(entry.id)
