from io import BytesIO
import json

from PIL import Image
import pytest

from test_conversation import conversation_client, reference_db, edit
from anima_prompt_studio_v3.storage.reference_examples import ExampleStore, ExampleMetadata


def picture(fmt="PNG"):
    output = BytesIO()
    Image.new("RGB", (40, 30), "navy").save(output, fmt)
    return output.getvalue()


def upload(client, metadata=None, data=None, mime="image/png"):
    return client.post("/api/v3/reference-examples", files={"file": ("../../outside.png", data or picture(), mime)},
                       data={"title": "雨后街道", "metadata": json.dumps(metadata or {})})


def test_media_copy_edit_cas_and_delete(conversation_client):
    client, _ = conversation_client
    response = upload(client)
    assert response.status_code == 201, response.text
    record = response.json()
    path = "/api/v3/reference-examples/" + record["id"]
    assert not record["requirements_valid"]
    assert client.get(path + "/content").content == picture()
    thumbnail = client.get(path + "/thumbnail")
    assert thumbnail.status_code == 200
    with Image.open(BytesIO(thumbnail.content)) as img:
        assert img.size == (40, 30)
    changed = client.patch(path, json={"revision": 1, "notes": {"user_notes": "保留人物"}})
    assert changed.status_code == 200, changed.text
    assert changed.json()["revision"] == 2
    assert changed.json()["title"] == record["title"]
    assert client.patch(path, json={"revision": 1, "title": "过期写入"}).status_code == 409
    assert client.request("DELETE", path, json={"revision": 1}).status_code == 409
    assert client.request("DELETE", path, json={"revision": 2}).status_code == 204
    assert client.get(path).status_code == 404
    assert client.get(path + "/content").status_code == 404


@pytest.mark.parametrize("metadata", [{"provenance": {"run_id": "fake"}}, {"origin": "session_pin"},
    {"compat": {"workflow_snapshot_ref": "fake"}}, {"requirements_edit": {"layers": {}}}])
def test_upload_cannot_forge_authority(conversation_client, metadata):
    client, _ = conversation_client
    assert upload(client, metadata).status_code == 422
    assert client.get("/api/v3/reference-examples").json()["items"] == []


def test_bad_image_and_mime_leave_no_record(conversation_client):
    client, _ = conversation_client
    assert upload(client, data=b"not an image").status_code == 422
    assert upload(client, mime="image/jpeg").status_code == 422
    assert upload(client, data=picture("GIF"), mime="image/gif").status_code == 422
    assert client.get("/api/v3/reference-examples").json()["items"] == []


def test_list_cursor_rejects_mixed_revision_and_query(conversation_client):
    client, _ = conversation_client
    upload(client)
    upload(client)
    first = client.get("/api/v3/reference-examples?limit=1").json()
    cursor = first["next_cursor"]
    second = client.get("/api/v3/reference-examples", params={"limit": 1, "cursor": cursor})
    assert second.status_code == 200
    assert second.json()["items"][0]["id"] != first["items"][0]["id"]
    assert client.get("/api/v3/reference-examples", params={"cursor": cursor, "q": "雨"}).status_code == 409
    upload(client)
    assert client.get("/api/v3/reference-examples", params={"cursor": cursor}).status_code == 409


def test_pin_freezes_source_preserves_locks_and_unpin_keeps_content(conversation_client):
    client, _ = conversation_client
    source = edit()
    source["layers"]["style"].update(text="水彩", medium="watercolor", locked=True)
    source["layers"]["lighting"].update(text="晨光", include_with_style_pin=True)
    example = upload(client, {"requirements_edit": source}).json()
    target = edit()
    target["layers"]["lighting"].update(text="侧光", locked=True)
    workspace = client.post("/api/v3/workspaces", json={"draft": {"requirements_edit": target}}).json()
    command = {"workspace_id": workspace["id"], "revision": 1, "example_id": example["id"], "source_version": "1", "role": "style"}
    response = client.post("/api/v3/workbench/pins", json=command)
    assert response.status_code == 200, response.text
    pinned = response.json()
    layers = pinned["draft"]["requirements"]["layers"]
    assert layers["style"]["text"] == "水彩" and not layers["style"]["locked"]
    assert layers["lighting"]["text"] == "侧光"
    assert client.patch("/api/v3/reference-examples/" + example["id"], json={"revision": 1, "title": "新标题"}).status_code == 200
    assert client.post("/api/v3/workbench/pins", json={**command, "revision": 2}).status_code == 409
    assert client.request("DELETE", "/api/v3/reference-examples/" + example["id"], json={"revision": 2}).status_code == 204
    retained = client.get("/api/v3/workspaces/" + workspace["id"]).json()
    assert retained["draft"]["reference_pin"]["source_snapshot"]["requirements"] == example["requirements"]
    unpinned = client.request("DELETE", "/api/v3/workbench/pins", json={"workspace_id": workspace["id"], "revision": 2}).json()
    assert unpinned["draft"]["reference_pin"] is None
    assert unpinned["draft"]["requirements"] == pinned["draft"]["requirements"]


def test_pin_into_empty_workspace(conversation_client):
    client, _ = conversation_client
    example = upload(client, {"requirements_edit": edit()}).json()
    workspace = client.post("/api/v3/workspaces", json={"draft": {}}).json()
    response = client.post("/api/v3/workbench/pins", json={"workspace_id": workspace["id"], "revision": 1,
        "example_id": example["id"], "source_version": "1", "role": "whole_scene"})
    assert response.status_code == 200, response.text


def test_registered_path_cannot_escape_media_root(tmp_path):
    store = ExampleStore(tmp_path / "examples.db")
    record = store.create(picture(), "test", ExampleMetadata())
    outside = tmp_path / "outside.png"
    outside.write_bytes(picture())
    with store.connect() as db:
        db.execute("UPDATE example_files SET image_relpath=?", (str(outside),))
    with pytest.raises(ValueError):
        store.content(record["id"])


def test_upload_requires_session_and_origin(conversation_client):
    client, _ = conversation_client
    client.headers.pop("Origin")
    assert upload(client).status_code == 403
    client.headers["Origin"] = "http://127.0.0.1"
    client.headers.pop("X-Anima-Session")
    client.cookies.clear()
    assert upload(client).status_code == 401


def ingest_setup(client, monkeypatch, *, vision=True, response=None):
    from anima_prompt_studio_v3.prompt_assistant.config_manager import config_manager
    from anima_prompt_studio_v3.prompt_assistant.services.llm import LLMService
    from anima_prompt_studio_v3.core.requirements import dump, CONTENT_MODELS

    monkeypatch.setattr(LLMService, "_get_config", lambda: {"provider": "test"})
    monkeypatch.setattr(config_manager, "get_service", lambda _: {"supports_vision": vision})
    calls = []
    layers = edit()["layers"]
    layers["style"].update(text="铅笔", medium="pencil")
    updates = {name: {key: value for key, value in content.items() if key in CONTENT_MODELS[name].model_fields or key == "global"}
               for name, content in layers.items()}
    async def complete(**kwargs):
        calls.append(kwargs)
        return {"text": json.dumps(response or {"layer_updates": updates, "include_with_style_pin": {"lighting": True}, "warnings": []})}
    monkeypatch.setattr(LLMService, "complete", complete)
    return calls


def test_ingest_vision_gate_and_success(conversation_client, monkeypatch):
    client, _ = conversation_client
    example = upload(client, {"notes": {"external_prompt": "private external prompt"}}).json()
    path = "/api/v3/reference-examples/" + example["id"]
    calls = ingest_setup(client, monkeypatch, vision=False)
    assert client.post(path + "/ingest", json={"revision": 1}).status_code == 422
    assert not calls and client.get(path).json()["revision"] == 1
    calls = ingest_setup(client, monkeypatch)
    response = client.post(path + "/ingest", json={"revision": 1})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["revision"] == 3 and result["ingest_state"] == "ready"
    assert result["requirements"]["revision"] == 1
    assert result["requirements"]["layers"]["lighting"]["include_with_style_pin"]
    assert "private external prompt" not in json.dumps(calls[0]["messages"])
    assert calls[0]["images"][0].startswith(b"\xff\xd8")


def test_ingest_failure_retains_valid_requirements(conversation_client, monkeypatch):
    client, _ = conversation_client
    example = upload(client, {"requirements_edit": edit()}).json()
    path = "/api/v3/reference-examples/" + example["id"]
    ingest_setup(client, monkeypatch, response={"layer_updates": {"style": {"artists": ["invented"]}}})
    assert client.post(path + "/ingest", json={"revision": 1}).status_code == 502
    failed = client.get(path).json()
    assert failed["ingest_state"] == "failed" and failed["requirements_valid"]
    assert failed["requirements"] == example["requirements"]


def test_prompt_ingest_without_vision_never_reads_image(conversation_client, monkeypatch):
    from anima_prompt_studio_v3.storage.reference_examples import ExampleStore
    client, _ = conversation_client
    example = upload(client, {"notes": {"external_prompt": "positive: charcoal portrait; negative: text"}}).json()
    calls = ingest_setup(client, monkeypatch, vision=False)
    monkeypatch.setattr(ExampleStore, "thumbnail", lambda *_: pytest.fail("text extraction must not read images"))
    path = "/api/v3/reference-examples/" + example["id"]
    response = client.post(path + "/ingest", json={"revision": 1, "source": "prompt"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["analysis_source"] == "prompt"
    assert client.get(path).json()["analysis_source"] == "prompt"
    assert calls[0]["images"] is None and calls[0]["task"] == "prompt_ingest"
    context = json.loads(calls[0]["messages"][-1]["content"])
    assert context["external_prompt_notes"] == example["notes"]["external_prompt"]
    assert not result["requirements"]["layers"]["lighting"]["include_with_style_pin"]
    assert any("未核对图片" in warning for warning in result["warnings"])


def test_prompt_ingest_empty_or_stale_does_not_call_model(conversation_client, monkeypatch):
    client, _ = conversation_client
    example = upload(client).json()
    calls = ingest_setup(client, monkeypatch, vision=False)
    path = "/api/v3/reference-examples/" + example["id"]
    assert client.post(path + "/ingest", json={"revision": 1, "source": "prompt"}).status_code == 422
    assert client.get(path).json()["revision"] == 1
    other = upload(client, {"notes": {"external_prompt": "watercolor"}}).json()
    assert client.post("/api/v3/reference-examples/" + other["id"] + "/ingest",
                       json={"revision": 2, "source": "prompt"}).status_code == 409
    assert not calls


def test_ingest_cannot_remove_confirmed_artists(conversation_client, monkeypatch):
    client, _ = conversation_client
    requirements = edit()
    requirements["layers"]["style"]["artists"] = ["confirmed artist"]
    example = upload(client, {"requirements_edit": requirements}).json()
    ingest_setup(client, monkeypatch)  # Vision returns an empty artists list.
    result = client.post("/api/v3/reference-examples/" + example["id"] + "/ingest", json={"revision": 1})
    assert result.status_code == 200, result.text
    assert result.json()["requirements"]["layers"]["style"]["artists"] == ["confirmed artist"]


def test_ingest_edit_supersedes_and_restart_recovers(tmp_path):
    from anima_prompt_studio_v3.storage.reference_examples import ExamplePatch
    from anima_prompt_studio_v3.api.reference_ingest import IngestService

    store = ExampleStore(tmp_path / "examples.db")
    example = store.create(picture(), "test", ExampleMetadata())
    pending = store.start_ingest(example["id"], 1)
    store.patch(example["id"], ExamplePatch(revision=2, title="edited"))
    with pytest.raises(ValueError, match="修改"):
        store.finish_ingest(pending, error="failed")
    assert store.get(example["id"])["ingest_state"] == "none"
    store.start_ingest(example["id"], 3)
    IngestService(ExampleStore(tmp_path / "examples.db"))
    recovered = store.get(example["id"])
    assert recovered["ingest_state"] == "failed" and recovered["ingest_error_code"] == "ingest_interrupted"


def test_from_run_uses_frozen_provenance_and_checks_artifact(conversation_client, tmp_path):
    from types import SimpleNamespace
    from anima_prompt_studio_v3.core.requirements import Requirements

    client, _ = conversation_client
    image = tmp_path / "run.png"
    image.write_bytes(picture())
    frozen = Requirements(**edit()).model_dump(mode="json", by_alias=True)
    provenance = {"requirements": frozen, "positive": "original prompt", "negative": "", "model_profile": "anima_base_v1",
                  "settings": {"seed": 12}, "workflow_snapshot_ref": "run1", "secret_should_not_cross": "internal"}
    client.app.state.gallery_service = SimpleNamespace(resolve_content=lambda path: image if path == "run.png" else None)
    client.app.state.submission_service = SimpleNamespace(
        store=SimpleNamespace(for_runs=lambda ids: [{"snapshot": {"provenance": provenance}}]),
        queue=SimpleNamespace(artifacts=lambda run_id: [SimpleNamespace(local_path=image)] if run_id == "run1" else []))
    response = client.post("/api/v3/reference-examples/from-run", json={"run_id": "run1", "path": "run.png"})
    assert response.status_code == 201, response.text
    example = response.json()
    assert example["requirements"] == frozen
    assert example["provenance"]["positive"] == "original prompt"
    assert "secret_should_not_cross" not in example["provenance"]
    assert client.post("/api/v3/reference-examples/from-run", json={"run_id": "other", "path": "run.png"}).status_code == 404
    assert client.post("/api/v3/reference-examples/from-gallery", json={"path": "../run.png"}).status_code == 404
    image.unlink()
    assert client.get("/api/v3/reference-examples/" + example["id"] + "/content").content == picture()


def test_presets_hide_notes_and_bind_pagination_filters(conversation_client):
    client, _ = conversation_client
    source = upload(client, {"requirements_edit": edit(), "notes": {"external_prompt": "must stay private"}}).json()
    upload(client, {"requirements_edit": edit()})
    first = client.get("/api/v3/reference-presets?limit=1").json()
    assert first["catalog_version"] == "anima-ref-1"
    assert "must stay private" not in json.dumps(first)
    assert client.get("/api/v3/reference-presets", params={"cursor": first["next_cursor"], "model_profile": "other"}).status_code == 409
    path = "/api/v3/reference-presets/" + source["id"]
    assert client.get(path + "/availability", params={"source_version": "1"}).json()["availability"] == "unknown"
    client.patch("/api/v3/reference-examples/" + source["id"], json={"revision": 1, "title": "changed"})
    assert client.get(path, params={"source_version": "1"}).status_code == 409


def test_official_routes_notes_copy_and_pin(conversation_client, tmp_path):
    from test_official_examples import pack
    client, _ = conversation_client
    client.app.state.example_store.official.install(pack(tmp_path / "official-source"))
    path = "/api/v3/reference-examples/off_one"
    official = client.get(path).json()
    assert "media_path" not in official
    assert client.get(path + "/content").status_code == 200
    assert client.patch(path + "/notes", json={"override_revision": 0, "notes": {"user_notes": "mine"}}).status_code == 200
    assert client.patch(path + "/notes", json={"override_revision": 0, "notes": {}}).status_code == 409
    copied = client.post(path + "/copy", json={"source_version": official["source_version"]})
    assert copied.status_code == 201, copied.text
    assert copied.json()["id"].startswith("ex_") and copied.json()["notes"]["user_notes"] == "mine"
    workspace = client.post("/api/v3/workspaces", json={"draft": {}}).json()
    pinned = client.post("/api/v3/workbench/pins", json={"workspace_id": workspace["id"], "revision": 1,
        "example_id": "off_one", "source_version": official["source_version"], "role": "style"})
    assert pinned.status_code == 200, pinned.text
