"""Persistent personal tag library contracts."""

import json
import sqlite3

import pytest

from anima_prompt_studio_v3.core.personal_tags import (
    CategoryWrite,
    CompositionItem,
    CompositionWrite,
    TagWrite,
)
from anima_prompt_studio_v3.storage.personal_tag_compositions import PersonalTagCompositions
from anima_prompt_studio_v3.storage.personal_tags import (
    PersonalTagConflictError,
    PersonalTagNotFoundError,
    PersonalTagStore,
)


def tag(name: str, content: str, *, category_id: str | None = None, aliases=None) -> TagWrite:
    return TagWrite(
        display_name=name, content=content, aliases=aliases or [],
        category_id=category_id, kind="tag", notes="", default_weight=1.0,
    )


def item(tag_id: str | None, content: str, *, polarity="positive") -> CompositionItem:
    return CompositionItem(
        id=f"selection-{polarity}", source_tag_id=tag_id, display_name="快照",
        content=content, kind="fragment", polarity=polarity, weight=1.25,
    )


def test_search_keeps_raw_variants_and_literal_wildcards(tmp_path):
    store = PersonalTagStore(tmp_path / "personal-tags.db")
    first = store.create_tag(tag("长发", "long hair", aliases=["长头发"]))
    second = store.create_tag(tag("长发", "long_hair", aliases=["长头发"]))
    literal = store.create_tag(tag("百分号", "100% real"))
    store.create_tag(tag("普通", "1000 real"))

    assert first.id != second.id
    assert [x.id for x in store.list_tags(q="长头发")["items"]] == sorted([first.id, second.id])
    assert {x.id for x in store.list_tags(q="LONG HAIR")["items"]} == {first.id, second.id}
    assert [x.id for x in store.list_tags(q="%")["items"]] == [literal.id]
    assert store.get_tag(first.id).content == "long hair"
    assert store.get_tag(second.id).content == "long_hair"


def test_category_cycle_nonempty_delete_and_bulk_move_are_atomic(tmp_path):
    store = PersonalTagStore(tmp_path / "personal-tags.db")
    root = store.create_category(CategoryWrite(name="根", parent_id=None, position=0))
    child = store.create_category(CategoryWrite(name="子", parent_id=root.id, position=0))
    first = store.create_tag(tag("甲", "first", category_id=child.id))
    second = store.create_tag(tag("乙", "second"))

    with pytest.raises(ValueError):
        store.update_category(root.id, CategoryWrite(name="根", parent_id=child.id, position=0), expected_revision=root.revision)
    with pytest.raises(ValueError):
        store.set_category_deleted(child.id, True, expected_revision=child.revision)
    with pytest.raises(PersonalTagConflictError):
        store.move_tags([{"id": second.id, "revision": second.revision}, {"id": first.id, "revision": 0}], root.id)

    assert store.get_tag(first.id).category_id == child.id
    assert store.get_tag(second.id).category_id is None
    categories = {x.id: x for x in store.list_categories()}
    assert categories[root.id].parent_id is None
    assert categories[child.id].deleted_at is None
    assert store.list_tags(category_id=root.id)["total"] == 1


def test_stale_edit_preserves_saved_value(tmp_path):
    store = PersonalTagStore(tmp_path / "personal-tags.db")
    original = store.create_tag(tag("名字", "  Raw,\nCase  "))
    saved = store.update_tag(original.id, tag("新名", "  Saved,\nCase  "), expected_revision=original.revision)

    with pytest.raises(PersonalTagConflictError):
        store.update_tag(original.id, tag("过期", "lost"), expected_revision=original.revision)

    assert store.get_tag(original.id).content == "  Saved,\nCase  "
    assert store.get_tag(original.id).display_name == "新名"
    assert store.get_tag(original.id).revision == saved.revision


def test_trash_restore_keeps_source_metadata(tmp_path):
    path = tmp_path / "personal-tags.db"
    store = PersonalTagStore(path)
    created = store.create_tag(tag("来源", "raw"))
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE personal_tags SET source_key=?, source_id=?, source_metadata=?, needs_review=? WHERE id=?",
            ("legacy", "77", json.dumps({"global_weight": 1.6}), json.dumps(["category"]), created.id),
        )

    deleted = store.set_tag_deleted(created.id, True, expected_revision=created.revision)
    assert store.list_tags()["total"] == 0
    assert [x.id for x in store.list_tags(trash=True)["items"]] == [created.id]
    assert store.get_tag(created.id).deleted_at is not None
    restored = store.set_tag_deleted(created.id, False, expected_revision=deleted.revision)
    assert restored.source_key == "legacy"
    assert restored.source_id == "77"
    assert restored.source_metadata == {"global_weight": 1.6}
    assert restored.needs_review == ["category"]
    assert restored.deleted_at is None


def test_composition_snapshots_survive_source_edit_delete_and_reload(tmp_path):
    path = tmp_path / "personal-tags.db"
    store = PersonalTagStore(path)
    source = store.create_tag(tag("来源", "old,\nraw"))
    compositions = PersonalTagCompositions(path)
    saved = compositions.create(CompositionWrite(name="组合", items=[item(source.id, "old,\nraw")]))
    store.update_tag(source.id, tag("来源", "new"), expected_revision=source.revision)
    current = store.get_tag(source.id)
    store.set_tag_deleted(source.id, True, expected_revision=current.revision)

    reloaded = PersonalTagCompositions(path).get(saved.id)
    assert reloaded.items[0].source_tag_id == source.id
    assert reloaded.items[0].content == "old,\nraw"
    assert reloaded.items[0].weight == 1.25
    assert [x.id for x in compositions.list()] == [saved.id]


def test_stale_draft_save_returns_conflict(tmp_path):
    path = tmp_path / "personal-tags.db"
    drafts = PersonalTagCompositions(path)
    assert drafts.get_draft()["revision"] == 0
    first = drafts.save_draft([item(None, "first")], expected_revision=0)
    with pytest.raises(PersonalTagConflictError):
        PersonalTagCompositions(path).save_draft([item(None, "lost")], expected_revision=0)
    assert drafts.get_draft()["items"][0].content == "first"
    assert drafts.get_draft()["revision"] == first["revision"]


def test_validation_paging_and_library_revision(tmp_path):
    path = tmp_path / "personal-tags.db"
    store = PersonalTagStore(path)
    assert store.library_revision == 0
    with pytest.raises(ValueError):
        store.create_tag(tag("空", " \n "))
    with pytest.raises(ValueError):
        store.create_tag(tag("太长", "x" * 20_001))
    with pytest.raises(ValueError):
        store.create_tag(TagWrite(display_name="坏权重", content="ok", aliases=[], category_id=None, kind="tag", notes="", default_weight=float("nan")))
    names = ["丙", "甲", "乙"]
    records = [store.create_tag(tag(name, name)) for name in names]
    page = store.list_tags(limit=2)
    assert [x.display_name for x in page["items"]] == ["丙", "乙"]
    assert page["total"] == 3
    assert page["has_more"] is True
    assert {x.id for x in page["items"] + store.list_tags(limit=2, offset=2)["items"]} == {x.id for x in records}
    assert store.library_revision == 3
    with pytest.raises(ValueError):
        store.list_tags(limit=201)
    with pytest.raises(PersonalTagNotFoundError):
        store.get_tag("missing")


def test_paging_orders_by_normalized_name_then_raw_name(tmp_path):
    store = PersonalTagStore(tmp_path / "personal-tags.db")
    store.create_tag(tag("Ｂ", "wide"))
    store.create_tag(tag("B", "ascii"))
    store.create_tag(tag("Ａ", "first"))
    assert [x.display_name for x in store.list_tags()["items"]] == ["Ａ", "B", "Ｂ"]


def test_malformed_bulk_move_is_rejected_without_changing_rows(tmp_path):
    store = PersonalTagStore(tmp_path / "personal-tags.db")
    original = store.create_tag(tag("原名", "raw"))
    with pytest.raises(ValueError):
        store.move_tags([None], None)
    assert store.get_tag(original.id).revision == original.revision


def test_composition_rejects_output_over_twenty_thousand_characters(tmp_path):
    compositions = PersonalTagCompositions(tmp_path / "personal-tags.db")
    first = item(None, "a" * 12_000)
    second = item(None, "b" * 12_000)
    with pytest.raises(ValueError):
        compositions.create(CompositionWrite(name="过长", items=[first, second]))
    with pytest.raises(ValueError):
        compositions.save_draft([first, second], expected_revision=0)
    assert compositions.list() == []
    assert compositions.get_draft()["revision"] == 0


def test_find_similar_matches_only_live_exact_normalized_content(tmp_path):
    store = PersonalTagStore(tmp_path / "personal-tags.db")
    first = store.create_tag(tag("甲", "long hair"))
    second = store.create_tag(tag("乙", "long_hair"))
    store.create_tag(tag("long hair", "different", aliases=["long hair"]))
    store.create_tag(tag("丙", "long hair, extra"))

    assert [x.id for x in store.find_similar("LONG_HAIR")] == [second.id, first.id]
    assert [x.id for x in store.find_similar("long hair", exclude_id=first.id)] == [second.id]
    store.set_tag_deleted(second.id, True, expected_revision=second.revision)
    assert [x.id for x in store.find_similar("long hair")] == [first.id]
    assert store.find_similar("long hair", exclude_id=first.id) == []


def test_malformed_bulk_move_field_types_preserve_rows(tmp_path):
    store = PersonalTagStore(tmp_path / "personal-tags.db")
    original = store.create_tag(tag("原名", "raw"))
    for malformed in ({"id": [], "revision": 1}, {"id": original.id, "revision": "1"}):
        with pytest.raises(ValueError):
            store.move_tags([malformed], None)
    assert store.get_tag(original.id).revision == original.revision
    assert store.get_tag(original.id).content == "raw"


def test_long_import_alias_is_preserved_and_searchable(tmp_path):
    store = PersonalTagStore(tmp_path / "personal-tags.db")
    alias = "旧" * 418 + "名"
    created = store.create_tag(tag("中文", "raw", aliases=[alias]))
    assert store.get_tag(created.id).aliases == [alias]
    assert [x.id for x in store.list_tags(q="旧名")["items"]] == [created.id]
    assert [x.id for x in store.list_tags(q=alias[-20:])["items"]] == [created.id]
    with pytest.raises(ValueError):
        store.create_tag(tag("过长", "raw", aliases=["x" * 20_001]))
