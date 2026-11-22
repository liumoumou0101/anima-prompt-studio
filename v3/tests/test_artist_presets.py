from io import BytesIO
import copy
import sqlite3

from PIL import Image
import pytest

from anima_prompt_studio_v3.storage.artist_presets import ArtistPresetStore, PresetWrite, SampleMetadata, PresetConflict
from test_conversation import conversation_client, reference_db


def picture():
    output = BytesIO()
    Image.new("RGB", (40, 30), "navy").save(output, "PNG")
    return output.getvalue()


def value(**updates):
    return PresetWrite(name="Two artists", positive="  (@one:1.2), @two \\(name\\)\n", model_family="anima", model_label="Anima base v1", **updates)


def test_literal_roundtrip_sample_revision_and_staleness(tmp_path):
    store = ArtistPresetStore(tmp_path / "personal-tags.db")
    row = store.create(value())
    assert row["positive"] == value().positive
    assert not row["ready"]
    row = store.add_sample(row["id"], 1, picture(), SampleMetadata(full_positive="scene, " + row["positive"], parameters={"seed": None}))
    assert row["ready"] and row["revision"] == 2
    assert store.sample_content(row["id"], row["samples"][0]["id"])[0] == picture()
    with pytest.raises(PresetConflict):
        store.update(row["id"], 1, value())
    changed = store.update(row["id"], 2, value(favorite=True))
    assert changed["ready"]
    changed = store.update(row["id"], 3, value().model_copy(update={"positive": "@changed"}))
    assert not changed["ready"] and len(changed["samples"]) == 1
    assert ArtistPresetStore(store.path).get(row["id"])["positive"] == "@changed"
    with sqlite3.connect(store.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0


def test_portable_export_import_keeps_images_and_exact_text_and_is_idempotent(tmp_path):
    source = ArtistPresetStore(tmp_path / "source.db")
    row = source.create(value())
    source.add_sample(row["id"], 1, picture(), SampleMetadata(full_positive="original full prompt", model_label="Anima base v1"))
    document = source.export()
    destination = ArtistPresetStore(tmp_path / "dest.db")
    preview = destination.preview_import(document)
    assert len(preview["items"]) == 1 and preview["duplicates"] == 0
    result = destination.import_document(document, preview["token"])
    assert result == destination.import_document(document, preview["token"])
    imported = result["items"][0]
    assert imported["positive"] == row["positive"] and imported["ready"]
    assert destination.sample_content(imported["id"], imported["samples"][0]["id"])[0] == picture()
    preview = destination.preview_import(document)
    assert preview["duplicates"] == 1
    assert destination.import_document(document, preview["token"])["skipped"] == 1


def test_import_atomic_conflicts_and_invalid_bytes(tmp_path):
    store = ArtistPresetStore(tmp_path / "presets.db")
    source = ArtistPresetStore(tmp_path / "source.db")
    row = source.create(value())
    source.add_sample(row["id"], 1, picture(), SampleMetadata())
    document = source.export()
    preview = store.preview_import(document)
    store.create(PresetWrite(name="Other", positive="@other"))
    with pytest.raises(PresetConflict):
        store.import_document(document, preview["token"])
    bad = copy.deepcopy(document)
    bad["items"][0]["samples"][0]["image_base64"] = "aW52YWxpZA=="
    with pytest.raises(ValueError):
        store.preview_import(bad)
    assert len(store.list()) == 1


def test_selected_export_and_receipt_bound_to_exact_document(tmp_path):
    store = ArtistPresetStore(tmp_path / "presets.db")
    first = store.create(value())
    store.create(PresetWrite(name="Other", positive="@other"))
    assert [item["name"] for item in store.export(first["id"])["items"]] == [first["name"]]
    destination = ArtistPresetStore(tmp_path / "destination.db")
    document = store.export(first["id"])
    token = destination.preview_import(document)["token"]
    destination.import_document(document, token)
    changed = copy.deepcopy(document)
    changed["items"][0]["positive"] = "@different"
    with pytest.raises(PresetConflict):
        destination.import_document(changed, token)


def test_unknown_models_not_assumed_and_invalid_url_rejected():
    assert PresetWrite(name="Unknown", positive="@one").model_family == "unknown"
    with pytest.raises(ValueError):
        PresetWrite(name="Unsafe link", positive="@one", source_url="javascript:alert(1)")
    with pytest.raises(ValueError):
        PresetWrite(name="Blank", positive="  ")


def test_api_upload_cookie_sample_and_cas(conversation_client):
    import json
    client, _ = conversation_client
    result = client.post("/api/v3/artist-presets", json=value().model_dump())
    assert result.status_code == 201, result.text
    row = result.json()
    url = f"/api/v3/artist-presets/{row['id']}"
    uploaded = client.post(url + "/samples", files={"file": ("sample.png", picture(), "image/png")},
        data={"metadata": json.dumps({"expected_revision": 1, "full_positive": "source whole prompt"})})
    assert uploaded.status_code == 200, uploaded.text
    current = uploaded.json()
    assert current["ready"] and current["samples"][0]["full_positive"] == "source whole prompt"
    assert client.put(url, json={**value().model_dump(), "expected_revision": 1}).status_code == 409
    client.headers.pop("x-anima-session")
    assert client.get(current["samples"][0]["image_url"]).content == picture()
    assert client.get("/api/v3/artist-presets").status_code == 401
    client.cookies.clear()
    assert client.get(current["samples"][0]["image_url"]).status_code == 401


def test_api_rejects_bad_media_and_unknown_fields_without_touching_record(conversation_client):
    import json
    client, _ = conversation_client
    row = client.post("/api/v3/artist-presets", json=value().model_dump()).json()
    url = f"/api/v3/artist-presets/{row['id']}"
    metadata = {"expected_revision": 1}
    bad = client.post(url + "/samples", files={"file": ("sample.png", b"not an image", "image/png")}, data={"metadata": json.dumps(metadata)})
    assert bad.status_code == 422
    metadata["local_path"] = "C:/private/file.png"
    bad = client.post(url + "/samples", files={"file": ("sample.png", picture(), "image/png")}, data={"metadata": json.dumps(metadata)})
    assert bad.status_code == 422
    current = client.get(url).json()
    assert current["revision"] == 1 and current["samples"] == []
    assert client.post("/api/v3/artist-presets/from-reference", json={"reference_id": "ex_fc7df32675a913b8907f36a4c570cb66"}).status_code == 404


def test_sample_upload_preserves_64bit_seed_as_string_through_storage_and_export(conversation_client):
    import json
    client, _ = conversation_client
    row = client.post("/api/v3/artist-presets", json=value().model_dump()).json()
    raw_seed = 18446744073709551615
    metadata = {"expected_revision": 1, "parameters": {"seed": raw_seed, "steps": 28, "cfg": 4.5, "other": raw_seed}}
    result = client.post(f"/api/v3/artist-presets/{row['id']}/samples",
        files={"file": ("sample.png", picture(), "image/png")}, data={"metadata": json.dumps(metadata)})
    assert result.status_code == 200, result.text
    expected = {"seed": str(raw_seed), "steps": 28, "cfg": 4.5, "other": raw_seed}
    assert result.json()["samples"][0]["parameters"] == expected
    assert client.app.state.artist_preset_store.get(row["id"])["samples"][0]["parameters"] == expected
    exported = client.get(f"/api/v3/artist-presets/export?preset_id={row['id']}")
    assert exported.json()["items"][0]["samples"][0]["parameters"] == expected
    assert SampleMetadata(parameters={"seed": 9007199254740991}).parameters["seed"] == 9007199254740991
    assert SampleMetadata(parameters={"seed": -9007199254740992}).parameters["seed"] == "-9007199254740992"
    assert SampleMetadata(parameters={"seed": None}).parameters["seed"] is None


def test_delete_is_revision_protected_and_images_cannot_cross_parents(conversation_client):
    client, _ = conversation_client
    store = client.app.state.artist_preset_store
    row = store.create(value())
    row = store.add_sample(row["id"], 1, picture(), SampleMetadata())
    other = store.create(PresetWrite(name="Other", positive="@other"))
    sample = row["samples"][0]
    wrong_parent = sample["image_url"].replace(row["id"], other["id"])
    assert client.get(wrong_parent).status_code == 404
    url = f"/api/v3/artist-presets/{row['id']}"
    headers = {"Content-Type": "application/json"}
    assert client.delete(url + "?expected_revision=1", headers=headers).status_code == 409
    assert client.get(sample["image_url"]).status_code == 200
    deleted = client.delete(url + f"/samples/{sample['id']}?expected_revision=2", headers=headers)
    assert deleted.status_code == 200 and not deleted.json()["ready"]
    assert client.get(sample["image_url"]).status_code == 404
    assert client.delete(url + "?expected_revision=3", headers=headers).status_code == 204
    assert client.get(url).status_code == 404


def test_reference_candidate_copies_sample_without_mutating_reference(conversation_client):
    from anima_prompt_studio_v3.storage.reference_examples import ExampleMetadata
    client, _ = conversation_client
    reference_id = "ex_fc7df32675a913b8907f36a4c570cb66"
    fragment = r"@poco \(asahi age\), @aoi tori"
    refs = client.app.state.example_store
    ref = refs.create(picture(), "Original", ExampleMetadata(), example_id=reference_id,
        origin="research_import", provenance={"positive": "scene, " + fragment, "negative": "text", "settings": {"seed": None, "steps": 28},
            "unknown_fields": ["seed", "workflow"], "reference_metadata": {"checkpoint": "anima-2.9b-preview-v1-int8-convrot", "content_level": "safe",
                "source_url": "https://civitai.com/images/139696184"}})
    assert len(client.get("/api/v3/artist-presets/suggestions").json()["items"]) == 1
    result = client.post("/api/v3/artist-presets/from-reference", json={"reference_id": reference_id})
    assert result.status_code == 201, result.text
    saved = result.json()
    assert saved["positive"] == fragment and saved["ready"]
    assert saved["samples"][0]["full_positive"] == "scene, " + fragment
    assert saved["samples"][0]["parameters"]["unknown_fields"] == ["seed", "workflow", "lora_dependencies"]
    assert refs.get(reference_id)["revision"] == ref["revision"]
    assert client.post("/api/v3/artist-presets/from-reference", json={"reference_id": reference_id}).json()["id"] == saved["id"]
    path, _ = refs.content(reference_id)
    path.unlink()
    assert client.get(saved["samples"][0]["image_url"]).content == picture()


def test_import_api_preview_commit_and_tampering(conversation_client):
    client, _ = conversation_client
    document = {"format": "anima.artist-presets", "version": 1, "items": [value().model_dump()]}
    preview = client.post("/api/v3/artist-presets/import-preview", json={"document": document})
    assert preview.status_code == 200, preview.text
    modified = copy.deepcopy(document)
    modified["items"][0]["positive"] = "@different"
    payload = {"document": modified, "token": preview.json()["token"]}
    assert client.post("/api/v3/artist-presets/import", json=payload).status_code == 409
    payload["document"] = document
    saved = client.post("/api/v3/artist-presets/import", json=payload)
    assert saved.status_code == 200, saved.text
    assert len(saved.json()["items"]) == 1
    assert client.get("/api/v3/artist-presets/export").json()["items"][0]["positive"] == value().positive
