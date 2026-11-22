from anima_prompt_studio_v3.storage.reference_examples import ExampleMetadata, ExampleStore
from test_official_examples import pack
from test_reference_examples import picture


def create_example(store, title, *, origin="upload", model="anima_base_v1", artist="sample_artist",
                   dependency="lora", content="safe"):
    return store.create(
        picture(), title, ExampleMetadata(), origin=origin,
        provenance={
            "model_profile": model,
            "reference_metadata": {
                "checkpoint": model, "artists": [artist],
                "lora_dependency": dependency, "content_level": content,
            },
        },
    )


def test_total_stays_constant_across_mixed_official_and_user_pages(tmp_path):
    store = ExampleStore(tmp_path / "state/examples.db")
    users = [create_example(store, f"用户参考 {index}") for index in range(2)]
    store.official.install(pack(tmp_path / "official-source"))

    first = store.list(limit=1)
    second = store.list(limit=1, cursor=first["next_cursor"])
    third = store.list(limit=1, cursor=second["next_cursor"])

    assert first["total"] == second["total"] == third["total"] == 3
    assert [first["items"][0]["id"], second["items"][0]["id"], third["items"][0]["id"]] == [
        "off_one", users[1]["id"], users[0]["id"],
    ]
    assert first["next_cursor"] and second["next_cursor"] and third["next_cursor"] is None


def test_total_uses_every_filter_and_returns_zero_for_empty_match(tmp_path):
    store = ExampleStore(tmp_path / "state/examples.db")
    expected = create_example(store, "needle exact", origin="gallery_keep")
    create_example(store, "needle wrong origin", origin="upload")
    create_example(store, "needle wrong model", origin="gallery_keep", model="other")
    create_example(store, "needle wrong artist", origin="gallery_keep", artist="other")
    create_example(store, "needle wrong dependency", origin="gallery_keep", dependency="none")
    create_example(store, "needle wrong content", origin="gallery_keep", content="explicit")
    create_example(store, "different text", origin="gallery_keep")
    filters = {
        "q": "needle", "origin": "gallery_keep", "model": "anima_base_v1",
        "artist": "@Sample Artist", "lora_dependency": "lora", "content": "safe",
    }

    result = store.list(limit=1, **filters)
    empty = store.list(q="absent", origin="gallery_keep")

    assert result["total"] == 1
    assert [item["id"] for item in result["items"]] == [expected["id"]]
    assert result["next_cursor"] is None
    assert empty["total"] == 0 and empty["items"] == [] and empty["next_cursor"] is None


def test_total_excludes_deleted_records(tmp_path):
    store = ExampleStore(tmp_path / "state/examples.db")
    first = create_example(store, "first")
    create_example(store, "second")
    assert store.list()["total"] == 2

    store.delete(first["id"], first["revision"])

    assert store.list()["total"] == 1
