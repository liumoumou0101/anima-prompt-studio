"""Lossless import and export of personal tags."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from anima_prompt_studio_v3.core.personal_tags import CompositionItem, CompositionWrite, TagWrite
from anima_prompt_studio_v3.storage.personal_tag_compositions import PersonalTagCompositions
from anima_prompt_studio_v3.storage.personal_tag_import import (
    ImportOptions, backup_database, commit_import, export_bundle, preview_import,
)
from anima_prompt_studio_v3.storage.personal_tags import PersonalTagConflictError, PersonalTagStore
from anima_prompt_studio_v3.tools import export_legacy_tags


FIXTURE = Path(__file__).parent / "fixtures" / "personal_tags_legacy.json"


def legacy():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def import_document(store, document, options=ImportOptions()):
    preview = preview_import(store, document, options)
    return commit_import(store, document, options, digest=preview["digest"],
                         expected_library_revision=preview["library_revision"])


def test_legacy_import_preserves_variants_fragments_weights_and_unmapped_paths(tmp_path):
    store = PersonalTagStore(tmp_path / "personal-tags.db")
    source = legacy()
    options = ImportOptions(fragment_ids=["12"])
    preview = preview_import(store, source, options)
    assert preview["counts"] == {"new": 6, "existing": 0, "invalid": 0,
                                  "similar": 1, "unmapped": 1, "fragment_candidates": 1,
                                  "legacy_weights": 2}
    assert preview["issues"]
    result = import_document(store, source, options)
    assert result["counts"]["new"] == 6
    tags = {tag.source_id: tag for tag in store.list_tags(limit=20)["items"]}
    assert len(tags) == 3
    assert {tags["10"].content, tags["11"].content} == {"long hair", "long_hair"}
    assert tags["12"].content == "first, second\nthird"
    assert tags["12"].kind == "fragment"
    assert tags["12"].default_weight == 1.0
    assert tags["12"].source_metadata == source["tags"][2]
    assert "category_unmapped" in tags["12"].needs_review
    categories = {category.source_id: category for category in store.list_categories()}
    assert tags["12"].category_id == categories["1"].id
    assert tags["10"].category_id == categories["2"].id
    assert categories["3"].parent_id == categories["2"].id


def test_reimport_does_not_overwrite_local_edits(tmp_path):
    store = PersonalTagStore(tmp_path / "personal-tags.db")
    source = legacy()
    import_document(store, source)
    tag = next(tag for tag in store.list_tags(limit=20)["items"] if tag.source_id == "10")
    edited = store.update_tag(tag.id, TagWrite(display_name="用户修改", content="user raw",
                                             aliases=tag.aliases, category_id=tag.category_id),
                              expected_revision=tag.revision)
    again = import_document(store, source)
    assert again["counts"]["new"] == 0
    assert again["counts"]["existing"] == 6
    assert store.get_tag(tag.id).content == "user raw"
    assert store.get_tag(tag.id).revision == edited.revision


def test_invalid_or_stale_import_rolls_back_all_records(tmp_path):
    store = PersonalTagStore(tmp_path / "personal-tags.db")
    document = legacy()
    document["tags"][2]["content"] = " \n "
    before = export_bundle(store)
    preview = preview_import(store, document, ImportOptions())
    assert preview["counts"]["invalid"] == 1
    with pytest.raises(ValueError, match="invalid"):
        commit_import(store, document, ImportOptions(), digest=preview["digest"],
                      expected_library_revision=preview["library_revision"])
    assert export_bundle(store) == before

    valid = legacy()
    stale = preview_import(store, valid, ImportOptions())
    store.create_tag(TagWrite(display_name="本地", content="local"))
    changed = export_bundle(store)
    with pytest.raises(PersonalTagConflictError):
        commit_import(store, valid, ImportOptions(), digest=stale["digest"],
                      expected_library_revision=stale["library_revision"])
    assert export_bundle(store) == changed
    with pytest.raises(ValueError, match="digest"):
        commit_import(store, valid, ImportOptions(), digest="wrong",
                      expected_library_revision=store.library_revision)


def test_export_roundtrip_keeps_ids_trash_and_snapshots(tmp_path):
    source_store = PersonalTagStore(tmp_path / "source" / "personal-tags.db")
    import_document(source_store, legacy())
    source_tag = next(tag for tag in source_store.list_tags(limit=20)["items"] if tag.source_id == "10")
    item = CompositionItem(id="one", source_tag_id=source_tag.id, display_name="快照",
                           content="unchanged,\nraw", kind="fragment", polarity="negative", weight=1.25)
    compositions = PersonalTagCompositions(source_store.path)
    saved = compositions.create(CompositionWrite(name="保存", items=[item]))
    compositions.save_draft([item], expected_revision=0)
    source_store.set_tag_deleted(source_tag.id, True, expected_revision=source_tag.revision)
    bundle = export_bundle(source_store)
    assert bundle["format"] == "anima-personal-tags"
    assert bundle["draft"]["items"][0]["content"] == "unchanged,\nraw"
    backup = backup_database(source_store)
    assert backup.parent.name == "personal-tags-backups"
    assert PersonalTagStore(backup).get_tag(source_tag.id).deleted_at

    destination = PersonalTagStore(tmp_path / "destination" / "personal-tags.db")
    import_document(destination, bundle)
    assert export_bundle(destination)["categories"] == bundle["categories"]
    assert export_bundle(destination)["tags"] == bundle["tags"]
    assert export_bundle(destination)["combinations"] == bundle["combinations"]
    assert export_bundle(destination)["draft"] == bundle["draft"]
    assert PersonalTagCompositions(destination.path).get(saved.id).items[0].content == "unchanged,\nraw"


def test_opt_in_invalid_legacy_weight_is_reported_without_clamping(tmp_path):
    store = PersonalTagStore(tmp_path / "personal-tags.db")
    source = legacy()
    preview = preview_import(store, source, ImportOptions(use_legacy_weights=True))
    assert any(issue["code"] == "legacy_weight_invalid" and issue["source_id"] == "12"
               for issue in preview["issues"])
    import_document(store, source, ImportOptions(use_legacy_weights=True))
    tags = {tag.source_id: tag for tag in store.list_tags(limit=20)["items"]}
    assert tags["10"].default_weight == 1.5
    assert tags["12"].default_weight == 1.0
    assert tags["12"].source_metadata["global_weight"] == 9.0
    assert "legacy_weight_invalid" in tags["12"].needs_review


def test_read_only_legacy_cli_writes_utf8_json_from_fixed_tables(tmp_path, monkeypatch):
    output = tmp_path / "导出.json"
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "categories": legacy()["categories"], "tags": legacy()["tags"]}, ensure_ascii=False), stderr="")

    monkeypatch.setattr(export_legacy_tags.subprocess, "run", fake_run)
    assert export_legacy_tags.main(["--container", "pg-local", "--database", "postgres",
                                    "--output", str(output)]) == 0
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["format"] == "anima-legacy-tags"
    assert saved["tags"][0]["display_name"] == "长发"
    assert saved["source_key"] == "postgres:pg-local/postgres"
    argv, kwargs = calls[0]
    assert argv[:4] == ["docker", "exec", "-i", "pg-local"]
    assert "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY" in argv[-1]
    assert "public.sys_categories" in argv[-1] and "public.sys_tags" in argv[-1]
    assert "pg-local" not in argv[-1] and "postgres" not in argv[-1]
    assert kwargs["encoding"] == "utf-8"


def test_import_rejects_missing_parent_cycle_and_duplicate_source_ids(tmp_path):
    store = PersonalTagStore(tmp_path / "personal-tags.db")
    for mutate in (
        lambda doc: doc["categories"][1].update(parent_id=99),
        lambda doc: doc["categories"][0].update(parent_id=3),
        lambda doc: doc["tags"][1].update(id=10),
    ):
        document = legacy()
        mutate(document)
        preview = preview_import(store, document, ImportOptions())
        assert preview["counts"]["invalid"] > 0
        with pytest.raises(ValueError, match="invalid"):
            commit_import(store, document, ImportOptions(), digest=preview["digest"],
                          expected_library_revision=preview["library_revision"])
        assert store.library_revision == 0
        assert store.list_tags()["total"] == 0


def test_unique_full_subcategory_path_maps_to_grandchild_and_long_alias_survives(tmp_path):
    store = PersonalTagStore(tmp_path / "personal-tags.db")
    document = legacy()
    document["tags"][0]["sub_category"] = "头发/卷发"
    document["tags"][0]["aliases"] = ["旧" * 419]
    import_document(store, document)
    categories = {category.source_id: category for category in store.list_categories()}
    tag = next(tag for tag in store.list_tags(limit=20)["items"] if tag.source_id == "10")
    assert tag.category_id == categories["3"].id
    assert tag.aliases == ["旧" * 419]


def test_angle_bracket_prompt_is_a_fragment_candidate_only(tmp_path):
    store = PersonalTagStore(tmp_path / "personal-tags.db")
    document = legacy()
    document["tags"][2]["content"] = "<lora:portrait:1>"
    preview = preview_import(store, document, ImportOptions())
    assert preview["counts"]["fragment_candidates"] == 1
    import_document(store, document)
    tag = next(tag for tag in store.list_tags(limit=20)["items"] if tag.source_id == "12")
    assert tag.kind == "tag"
    assert tag.content == "<lora:portrait:1>"


def test_unsupported_version_is_rejected_without_writing(tmp_path):
    store = PersonalTagStore(tmp_path / "personal-tags.db")
    document = legacy()
    document["version"] = True
    with pytest.raises(ValueError, match="Unsupported"):
        preview_import(store, document, ImportOptions())
    assert store.library_revision == 0


def test_draft_only_import_changes_library_revision_and_keeps_local_draft(tmp_path):
    source = PersonalTagStore(tmp_path / "source" / "personal-tags.db")
    selection = CompositionItem(id="draft-item", display_name="独立草稿", content="raw,\ntext",
                                kind="fragment", polarity="positive", weight=1.0)
    PersonalTagCompositions(source.path).save_draft([selection], expected_revision=0)
    bundle = export_bundle(source)
    destination = PersonalTagStore(tmp_path / "destination" / "personal-tags.db")
    first = import_document(destination, bundle)
    assert first["counts"]["new"] == 1
    assert destination.library_revision == 1
    assert PersonalTagCompositions(destination.path).get_draft()["items"][0].content == "raw,\ntext"
    second = import_document(destination, bundle)
    assert second["counts"]["new"] == 0
    assert destination.library_revision == 1


def test_bundle_deduplicates_matching_source_ids_despite_different_row_ids(tmp_path):
    source = PersonalTagStore(tmp_path / "source" / "personal-tags.db")
    import_document(source, legacy())
    bundle = export_bundle(source)
    category_ids = {row["id"]: f"other-{row['id']}" for row in bundle["categories"]}
    for row in bundle["categories"]:
        row["id"] = category_ids[row["id"]]
        if row["parent_id"] is not None:
            row["parent_id"] = category_ids[row["parent_id"]]
    for row in bundle["tags"]:
        row["id"] = f"other-{row['id']}"
        row["category_id"] = category_ids[row["category_id"]]
    destination = PersonalTagStore(tmp_path / "destination" / "personal-tags.db")
    import_document(destination, legacy())
    preview = preview_import(destination, bundle, ImportOptions())
    assert preview["counts"]["new"] == 0
    assert preview["counts"]["existing"] == 6
    import_document(destination, bundle)
    assert len(destination.list_categories()) == 3
    assert destination.list_tags(limit=20)["total"] == 3
