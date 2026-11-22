from hashlib import sha256
import json

import pytest

from anima_prompt_studio_v3.core.requirements import Requirements, dump
from anima_prompt_studio_v3.storage.reference_examples import ExampleStore, ExampleMetadata, ExampleNotes
from anima_prompt_studio_v3.storage.official_examples import OfficialPack
from test_reference_examples import picture


def pack(root, pack_id="test1", title="参考样例"):
    root.mkdir(parents=True)
    files = {"catalog.json": json.dumps([{"id": "off_one", "title": title,
        "requirements": dump(Requirements.empty()), "compat": {}, "media": "media/off_one/original.webp"}], ensure_ascii=False).encode(),
        "NOTICE.txt": b"Test fixture, not a production official example.",
        "LICENSES/test.txt": b"Generated test pixels.", "media/off_one/original.webp": picture("WEBP")}
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    manifest = {"contract": "anima-v3-examples/1", "pack_id": pack_id, "generated_at": "2026-09-10",
        "counts": {"examples": 1, "files": len(files)},
        "files": [{"path": name, "size": len(data), "sha256": sha256(data).hexdigest()} for name,data in files.items()]}
    (root / "examples-pack.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def test_install_upgrade_preserves_notes_and_old_version(tmp_path):
    store = ExampleStore(tmp_path / "app" / "examples.db")
    assert store.list()["official_pack"] == {"ready": False}
    store.official.install(pack(tmp_path / "source1"))
    old = store.get("off_one")
    assert "media_path" not in old
    store.save_official_notes("off_one", 0, ExampleNotes(user_notes="my note"))
    store.official.install(pack(tmp_path / "source2", "test2", "新版"))
    assert store.get("off_one")["notes"]["user_notes"] == "my note"
    with pytest.raises(ValueError):
        store.get("off_one", old["source_version"])
    assert (store.official.root / "test1" / "catalog.json").is_file()
    with pytest.raises(ValueError):
        store.save_official_notes("off_one", 0, ExampleNotes())


def test_corrupt_pack_and_reused_id_do_not_switch_active_pointer(tmp_path):
    manager = OfficialPack(tmp_path / "installed")
    manager.install(pack(tmp_path / "good"))
    pointer = (manager.root / "current.json").read_bytes()
    bad = pack(tmp_path / "bad", "test2")
    (bad / "NOTICE.txt").write_text("corrupted")
    with pytest.raises(ValueError):
        manager.install(bad)
    with pytest.raises(ValueError):
        manager.install(pack(tmp_path / "changed", "test1", "different content"))
    assert (manager.root / "current.json").read_bytes() == pointer
    assert not list(manager.root.glob(".install-*"))


def test_combined_catalog_cursor_changes_on_upgrade(tmp_path):
    store = ExampleStore(tmp_path / "app" / "examples.db")
    store.create(picture(), "用户参考", ExampleMetadata())
    store.official.install(pack(tmp_path / "source1"))
    first = store.list(limit=1)
    assert first["items"][0]["id"] == "off_one"
    assert store.list(limit=1, cursor=first["next_cursor"])["items"][0]["origin"] == "upload"
    store.official.install(pack(tmp_path / "source2", "test2"))
    with pytest.raises(ValueError):
        store.list(limit=1, cursor=first["next_cursor"])


def test_active_pack_corruption_does_not_disable_user_library(tmp_path):
    store = ExampleStore(tmp_path / "app" / "examples.db")
    store.create(picture(), "my reference", ExampleMetadata())
    store.official.install(pack(tmp_path / "source"))
    assert store.list()["official_pack"]["ready"]
    (store.official.root / "test1" / "NOTICE.txt").write_text("corrupt")
    result = store.list()
    assert not result["official_pack"]["ready"]
    assert len(result["items"]) == 1 and result["items"][0]["origin"] == "upload"


@pytest.mark.parametrize("path", ["../outside", "/absolute", "C:/secret", "media\\bad", "media//bad"])
def test_pack_rejects_unsafe_paths(tmp_path, path):
    source = pack(tmp_path / "source")
    manifest_path = source / "examples-pack.json"
    data = json.loads(manifest_path.read_bytes())
    data["files"][0]["path"] = path
    manifest_path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        OfficialPack.validate(source)
