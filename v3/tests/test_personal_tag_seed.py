"""Automatic, one-time packaged baseline for pristine personal libraries."""

import json
from concurrent.futures import ThreadPoolExecutor
from importlib import resources

import pytest

from anima_prompt_studio_v3.api import create_api_runtime
from anima_prompt_studio_v3.core.personal_tags import CategoryWrite, CompositionWrite, TagWrite
from anima_prompt_studio_v3.storage import personal_tag_seed
from anima_prompt_studio_v3.storage.personal_tag_compositions import PersonalTagCompositions
from anima_prompt_studio_v3.storage.personal_tag_import import export_bundle
from anima_prompt_studio_v3.storage.personal_tags import PersonalTagStore


def test_api_startup_installs_packaged_baseline_without_reference_pack(tmp_path):
    workspace = tmp_path / "workspaces.db"
    runtime = create_api_runtime(tmp_path / "missing-reference.db", workspace_db=workspace)
    assert runtime.app.state.personal_tag_store.path == tmp_path / "personal-tags.db"
    store = PersonalTagStore(tmp_path / "personal-tags.db")
    bundle = export_bundle(store)
    assert len(bundle["categories"]) == 174
    assert len(bundle["tags"]) == 11473
    assert bundle["combinations"] == []
    assert bundle["draft"]["items"] == []
    assert store.library_revision == 1
    source = personal_tag_seed._load_seed_document()
    assert bundle == source
    assert not (tmp_path / "personal-tags-backups").exists()


def test_repeat_and_concurrent_initialization_install_once(tmp_path, monkeypatch):
    path = tmp_path / "personal-tags.db"
    store = PersonalTagStore(path)

    def start(_):
        return personal_tag_seed.initialize_bundled_personal_tags(PersonalTagStore(path))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(start, range(2)))
    assert results == [True, False] or results == [False, True]
    assert store.library_revision == 1
    with store._connect() as db:
        assert db.execute("SELECT count(*) FROM personal_tags").fetchone()[0] == 11473
        assert db.execute("SELECT version FROM personal_seed_meta WHERE id=1").fetchone()[0] == personal_tag_seed.SEED_VERSION
    monkeypatch.setattr(personal_tag_seed, "_load_seed_document", lambda: pytest.fail("seed read on repeat"))
    assert personal_tag_seed.initialize_bundled_personal_tags(store) is False


def test_failed_insert_rolls_back_marker_and_all_rows_then_retry_succeeds(tmp_path, monkeypatch):
    store = PersonalTagStore(tmp_path / "personal-tags.db")
    original = personal_tag_seed._insert_prepared

    def fail_after_insertion(db, prepared):
        original(db, prepared)
        raise RuntimeError("injected insertion failure")

    monkeypatch.setattr(personal_tag_seed, "_insert_prepared", fail_after_insertion)
    with pytest.raises(RuntimeError, match="injected insertion failure"):
        personal_tag_seed.initialize_bundled_personal_tags(store)
    assert store.library_revision == 0
    with store._connect() as db:
        assert db.execute("SELECT count(*) FROM personal_tags").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM personal_categories").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM personal_seed_meta").fetchone()[0] == 0
    monkeypatch.setattr(personal_tag_seed, "_insert_prepared", original)
    assert personal_tag_seed.initialize_bundled_personal_tags(store) is True


@pytest.mark.parametrize("existing", ["tag", "trash", "category", "composition", "draft", "empty_revision", "marker"])
def test_existing_library_never_reads_or_installs_baseline(tmp_path, monkeypatch, existing):
    store = PersonalTagStore(tmp_path / "personal-tags.db")
    if existing in ("tag", "trash"):
        tag = store.create_tag(TagWrite(display_name="local", content="local"))
        if existing == "trash":
            store.set_tag_deleted(tag.id, True, expected_revision=tag.revision)
        else:
            store.update_tag(tag.id, TagWrite(display_name="edited", content="edited"), expected_revision=tag.revision)
    elif existing == "category":
        store.create_category(CategoryWrite(name="local"))
    elif existing == "composition":
        PersonalTagCompositions(store.path).create(CompositionWrite(name="local", items=[]))
    elif existing == "draft":
        PersonalTagCompositions(store.path).save_draft([], expected_revision=0)
    elif existing == "empty_revision":
        with store._connect(write=True) as db:
            store._bump(db)
    else:
        with store._connect(write=True) as db:
            db.execute("INSERT INTO personal_seed_meta (id,version) VALUES (1,'earlier-seed')")
    before = export_bundle(store)
    revision = store.library_revision
    monkeypatch.setattr(personal_tag_seed, "_load_seed_document", lambda: pytest.fail("existing library read seed"))
    assert personal_tag_seed.initialize_bundled_personal_tags(store) is False
    assert export_bundle(store) == before
    assert store.library_revision == revision


def test_malformed_resource_cannot_modify_pristine_library(tmp_path, monkeypatch):
    store = PersonalTagStore(tmp_path / "personal-tags.db")
    document = personal_tag_seed._load_seed_document()
    document["tags"][0]["id"] = ""
    monkeypatch.setattr(personal_tag_seed, "_load_seed_document", lambda: document)
    with pytest.raises(ValueError, match="invalid"):
        personal_tag_seed.initialize_bundled_personal_tags(store)
    assert store.library_revision == 0
    with store._connect() as db:
        assert db.execute("SELECT count(*) FROM personal_tags").fetchone()[0] == 0


def test_user_write_during_resource_load_wins_over_seed(tmp_path, monkeypatch):
    store = PersonalTagStore(tmp_path / "personal-tags.db")
    original = personal_tag_seed._load_seed_document

    def load_after_user_write():
        document = original()
        store.create_tag(TagWrite(display_name="user", content="user"))
        return document

    monkeypatch.setattr(personal_tag_seed, "_load_seed_document", load_after_user_write)
    assert personal_tag_seed.initialize_bundled_personal_tags(store) is False
    assert [row.content for row in store.list_tags()["items"]] == ["user"]
    assert store.library_revision == 1
    with store._connect() as db:
        assert db.execute("SELECT count(*) FROM personal_seed_meta").fetchone()[0] == 0


def test_bundled_json_is_available_as_package_resource():
    resource = resources.files("anima_prompt_studio_v3").joinpath("seed_data", personal_tag_seed.SEED_FILENAME)
    payload = json.loads(resource.read_text(encoding="utf-8"))
    assert payload["format"] == "anima-personal-tags"
    assert len(payload["categories"]) == 174
    assert len(payload["tags"]) == 11473
