from io import BytesIO
import json

from PIL import Image
import pytest

from test_conversation import conversation_client, reference_db
from anima_prompt_studio_v3.storage.reference_examples import ExampleNotes, ExamplePatch, ExampleStore
from anima_prompt_studio_v3.storage.reference_import import import_collection


def collection(tmp_path, rows=None):
    root = tmp_path / "research"
    (root / "batches").mkdir(parents=True)
    (root / "images").mkdir()
    image = BytesIO()
    Image.new("RGB", (32, 48), "navy").save(image, "PNG")
    (root / "images/a.png").write_bytes(image.getvalue())
    base = {"id": "civitai:123", "title": "画师水彩参考", "image_file": "images/a.png",
        "checkpoint": "anima-2.9b-preview-v1", "artist_tag": "@Sample Artist", "lora": "",
        "prompt": "@Sample Artist, watercolor portrait\nblue sky", "negative": "",
        "steps": 50, "cfg": 4, "sampler": "euler", "scheduler": "beta", "size": "896x1152",
        "nsfw": False, "unet_pure": True, "source_url": "https://civitai.com/images/123"}
    values = [{**base, **row} for row in (rows or [{}])]
    (root / "batches/01.json").write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
    return root, values


def rewrite(root, values):
    (root / "batches/01.json").write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")


def test_import_is_idempotent_retains_originals_and_preserves_user_edits(tmp_path):
    root, values = collection(tmp_path)
    store = ExampleStore(tmp_path / "state/examples.db")
    dry = import_collection(store, root, dry_run=True)
    assert dry["counts"]["created"] == 1 and store.list()["items"] == []
    receipt = import_collection(store, root)
    item = store.get(receipt["items"][0]["id"])
    assert item["provenance"]["positive"] == values[0]["prompt"]
    assert item["provenance"]["settings"]["seed"] is None
    assert item["provenance"]["workflow_snapshot_ref"] is None
    assert item["provenance"]["unknown_fields"] == ["seed", "workflow"]
    assert item["provenance"]["reference_metadata"]["source_record"] == values[0]
    assert item["requirements_valid"] is False
    changed = store.patch(item["id"], ExamplePatch(revision=item["revision"], title="我的标题",
        notes=ExampleNotes(user_notes="保留笔记", external_prompt="我改过的文字")))
    assert import_collection(store, root)["counts"]["unchanged"] == 1
    assert store.get(item["id"]) == changed
    values[0]["why"] = "补充来源说明"
    rewrite(root, values)
    assert import_collection(store, root)["counts"]["updated"] == 1
    updated = store.get(item["id"])
    assert updated["title"] == "我的标题"
    assert updated["notes"] == changed["notes"]
    assert updated["provenance"]["reference_metadata"]["why"] == "补充来源说明"
    store.delete(item["id"], updated["revision"])
    assert import_collection(store, root)["counts"]["deleted_preserved"] == 1
    assert store.list()["items"] == []


@pytest.mark.parametrize("invalid", [{"image_file": "../outside.png"}, {"image_file": "C:/outside.png"}, {"id": "../../escape"}])
def test_import_validates_every_record_before_writing(tmp_path, invalid):
    root, _ = collection(tmp_path, [{}, {"id": "civitai:456", **invalid}])
    store = ExampleStore(tmp_path / "state/examples.db")
    with pytest.raises(ValueError):
        import_collection(store, root)
    assert store.list()["items"] == []
    assert list(store.root.iterdir()) == []


@pytest.mark.parametrize("field", ["style_axis", "why", "copy_tip", "lora_url", "stats"])
def test_import_rejects_non_string_display_metadata_before_writing(tmp_path, field):
    root, _ = collection(tmp_path, [{}, {"id": "civitai:456", field: {"unexpected": "object"}}])
    store = ExampleStore(tmp_path / "state/examples.db")

    with pytest.raises(ValueError, match=field):
        import_collection(store, root)

    assert store.list()["items"] == []
    assert list(store.root.iterdir()) == []


def test_duplicate_source_ids_and_changed_images_are_rejected(tmp_path):
    root, values = collection(tmp_path, [{}, {}])
    store = ExampleStore(tmp_path / "state/examples.db")
    with pytest.raises(ValueError, match="重复"):
        import_collection(store, root)
    rewrite(root, values[:1])
    import_collection(store, root)
    Image.new("RGB", (32, 48), "red").save(root / "images/a.png")
    with pytest.raises(ValueError, match="图片内容已变化"):
        import_collection(store, root)


def test_filters_distinguish_explicit_pure_from_unknown_and_bind_cursor(conversation_client, tmp_path):
    client, _ = conversation_client
    root, _ = collection(tmp_path, [{}, {"id": "civitai:456", "unet_pure": False, "lora": "style:0.8"},
        {"id": "civitai:789", "unet_pure": False},
        {"id": "civitai:890", "unet_pure": False, "lora": "style:1", "nsfw": True, "nsfw_level": "explicit"}])
    store = client.app.state.example_store
    import_collection(store, root)
    prefix = "/api/v3/reference-examples"
    assert len(client.get(prefix, params={"lora_dependency": "none"}).json()["items"]) == 1
    assert len(client.get(prefix, params={"lora_dependency": "lora"}).json()["items"]) == 2
    assert len(client.get(prefix, params={"lora_dependency": "unknown"}).json()["items"]) == 1
    assert len(client.get(prefix, params={"model": "anima_2_9b_preview_v1", "content": "safe"}).json()["items"]) == 3
    page = client.get(prefix, params={"artist": "@Sample Artist", "limit": 1}).json()
    assert page["next_cursor"]
    assert client.get(prefix, params={"artist": "other", "cursor": page["next_cursor"]}).status_code == 409
    facets = client.get(prefix + "/facets").json()
    assert facets == {"models": ["anima-2.9b-preview-v1"], "artists": ["sample_artist"], "count": 4}
    samples = client.get(prefix + "/by-artist", params={"artist": "sample_artist"}).json()["items"]
    assert len(samples) == 3 and all(item["content_level"] == "safe" for item in samples)
    assert {item["lora_dependency"] for item in samples} == {"none", "lora", "unknown"}
    assert client.get(samples[0]["thumbnail_url"]).status_code == 200


def test_borrow_original_prompt_needs_no_llm_or_requirements_and_uses_model_defaults(conversation_client, tmp_path):
    client, calls = conversation_client
    root, values = collection(tmp_path)
    store = client.app.state.example_store
    receipt = import_collection(store, root)
    item = store.get(receipt["items"][0]["id"])
    response = client.post(f"/api/v3/reference-examples/{item['id']}/workspace",
        json={"source_version": item["source_version"], "mode": "prompt"})
    assert response.status_code == 201, response.text
    draft = response.json()["draft"]
    assert draft["compiled"]["positive"] == values[0]["prompt"]
    assert draft["compiled"]["negative"] == ""
    assert draft["compile_state"] == "fresh"
    assert draft["model_profile"] == "anima_2_9b_preview_v1"
    assert draft["generation_settings"]["steps"] == 30
    assert draft["generation_settings"]["seed"] in (-1, "-1")
    assert draft["generation_settings"]["workflow_profile_id"] is None
    assert draft["generation_source"] is None
    assert draft["requirements"]["loras"] == []
    assert calls == []
    assert client.post(f"/api/v3/reference-examples/{item['id']}/workspace",
        json={"source_version": "999", "mode": "prompt"}).status_code == 409
