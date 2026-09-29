"""Gallery continuation creates a new workspace without AI or image copies."""
from types import SimpleNamespace

import pytest

from test_conversation import conversation_client, reference_db
from test_reference_examples import picture
from anima_prompt_studio.services.gallery_assets import resolve_gallery_image
from anima_prompt_studio_v3.core.runtime_profiles import V3RuntimeProfiles


ROUTE = "/api/v3/gallery/assets/workspace"


def gallery(client, tmp_path, *, model="anima_base_v1", positive="  original garden  "):
    root = tmp_path / "originals"
    root.mkdir()
    for name in ("one.png", "two.png", "unindexed.png"):
        (root / name).write_bytes(picture())
    assets = [dict(path=name, name=name, batch_id="run1", model_profile=model,
                   positive_prompt=positive, negative_prompt="text, watermark",
                   generation_params={"seed": "8798399215689017476", "cfg": 9, "steps": 99})
              for name in ("one.png", "two.png")]
    client.app.state.gallery_service = SimpleNamespace(
        resolve_content=lambda path: resolve_gallery_image(path, root),
        list_assets=lambda **kwargs: {"items": assets})
    return root, assets


def generation(client, root, *, workflow=True, belongs=True):
    snapshot = {"provenance": {"positive": "exact generated prompt", "negative": "exact negative",
                "model_profile": "anima_base_v1", "requirements": None,
                "settings": {"seed": 8798399215689017476, "width": 1280, "height": 960}},
                "run": {"remote_profile_id": "remote1", "workflow_profile_id": "wf1"},
                "workflow": {"id": "wf1"} if workflow else None,
                "resources": [{"logical_id": "paint", "file_name": "paint.safetensors", "weight": 0.7}]}
    client.app.state.submission_service = SimpleNamespace(
        store=SimpleNamespace(for_runs=lambda ids: [{"snapshot": snapshot}]),
        queue=SimpleNamespace(artifacts=lambda run: [SimpleNamespace(local_path=str(root / name))
            for name in (("one.png", "two.png") if belongs else ("other.png",))]))


def test_full_snapshot_keeps_image_seed_resources_and_original_workspace(conversation_client, tmp_path):
    client, calls = conversation_client
    root, _ = gallery(client, tmp_path)
    generation(client, root)
    store = client.app.state.workspace_store
    old = store.create("已有草稿", {"natural_text": "保留草稿"})
    examples = client.app.state.example_store.list()
    before_files = sorted(root.iterdir())
    response = client.post(ROUTE, json={"path": "one.png"}, headers={"Idempotency-Key": "gallery-one"})
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["draft"]["gallery_source"] == {"path": "one.png", "name": "one.png", "mode": "generation"}
    assert record["draft"]["generation_source"]["run_id"] == "run1"
    assert record["draft"]["compiled"]["positive"] == "exact generated prompt"
    assert record["draft"]["generation_settings"]["seed"] == "8798399215689017476"
    assert record["draft"]["generation_settings"]["width"] == 1280
    assert record["draft"]["requirements"]["loras"][0]["logical_id"] == "paint"
    assert client.get(f"/api/v3/workspaces/{record['id']}").json() == record
    assert store.get(old["id"]) == old
    assert client.app.state.example_store.list() == examples
    assert sorted(root.iterdir()) == before_files
    assert calls == []


@pytest.mark.parametrize("model,expected", [("anima_base_v1", "anima_base_v1"),
                                             ("anima_turbo_v1_1", "anima_turbo_v1_1"),
                                             ("old-custom-model", "anima_aesthetic_v1_1")])
def test_legacy_fallback_keeps_prompt_and_uses_explicit_model_defaults(conversation_client, tmp_path, model, expected):
    client, calls = conversation_client
    gallery(client, tmp_path, model=model)
    response = client.post(ROUTE, json={"path": "one.png"})
    assert response.status_code == 201, response.text
    draft = response.json()["draft"]
    assert draft["gallery_source"] == {"path": "one.png", "name": "one.png", "mode": "prompt"}
    assert draft["compiled"]["positive"] == "  original garden  "
    assert draft["compiled"]["negative"] == "text, watermark"
    assert draft["generation_source"] is None
    assert draft["requirements"]["loras"] == []
    assert draft["model_profile"] == expected
    defaults = V3RuntimeProfiles().get_model(expected)
    settings = draft["generation_settings"]
    assert settings["seed"] == -1
    assert settings["cfg"] == defaults.cfg and settings["steps"] == defaults.steps
    assert settings["sampler"] == defaults.sampler and settings["scheduler"] == defaults.scheduler
    assert settings["width"] == defaults.default_width and settings["height"] == defaults.default_height
    assert settings["remote_profile_id"] is None and settings["workflow_profile_id"] is None
    assert draft["compile_state"] == "fresh"
    assert calls == []


def test_missing_workflow_uses_prompt_fallback(conversation_client, tmp_path):
    client, _ = conversation_client
    root, _ = gallery(client, tmp_path)
    generation(client, root, workflow=False)
    response = client.post(ROUTE, json={"path": "one.png"})
    assert response.status_code == 201, response.text
    assert response.json()["draft"]["gallery_source"]["mode"] == "prompt"
    assert response.json()["draft"]["generation_source"] is None


@pytest.mark.parametrize("full", [False, True])
def test_replay_and_different_image_conflict(conversation_client, tmp_path, full):
    client, _ = conversation_client
    root, _ = gallery(client, tmp_path)
    if full:
        generation(client, root)
    headers = {"Idempotency-Key": "same-gallery-request"}
    first = client.post(ROUTE, json={"path": "one.png"}, headers=headers)
    assert first.status_code == 201, first.text
    assert client.post(ROUTE, json={"path": "one.png"}, headers=headers).json() == first.json()
    other = client.post(ROUTE, json={"path": "two.png"}, headers=headers)
    assert other.status_code == 409, other.text
    assert len(client.app.state.workspace_store.list()) == 1


@pytest.mark.parametrize("path", ["missing.png", "../outside.png", "unindexed.png", ".trash/one.png"])
def test_unavailable_or_unauthorized_image_never_creates(conversation_client, tmp_path, path):
    client, calls = conversation_client
    gallery(client, tmp_path)
    before = client.app.state.workspace_store.list()
    response = client.post(ROUTE, json={"path": path})
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "reference_preset_not_found"
    assert client.app.state.workspace_store.list() == before
    assert calls == []


def test_empty_prompt_and_wrong_run_membership_never_create(conversation_client, tmp_path):
    client, _ = conversation_client
    root, assets = gallery(client, tmp_path, positive=" \n ")
    response = client.post(ROUTE, json={"path": "one.png"})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "empty_requirements"
    assets[0]["positive_prompt"] = "known prompt"
    generation(client, root, belongs=False)
    assert client.post(ROUTE, json={"path": "one.png"}).status_code == 404
    assert client.app.state.workspace_store.list() == []


def test_mutation_requires_session_same_origin_and_strict_body(conversation_client, tmp_path):
    client, _ = conversation_client
    gallery(client, tmp_path)
    assert client.post(ROUTE, json={"path": "one.png", "positive": "forged"}).status_code == 422
    assert client.post(ROUTE, json={"path": "one.png"}, headers={"Origin": "http://localhost"}).status_code == 403
    del client.headers["X-Anima-Session"]
    assert client.post(ROUTE, json={"path": "one.png"}).status_code == 401
    assert client.app.state.workspace_store.list() == []


def test_gallery_source_is_server_owned_and_survives_normal_save(conversation_client, tmp_path):
    client, _ = conversation_client
    gallery(client, tmp_path)
    record = client.post(ROUTE, json={"path": "one.png"}).json()
    source = record["draft"]["gallery_source"]
    saved = client.put(f"/api/v3/workspaces/{record['id']}", json={
        "revision": record["revision"], "draft": {}})
    assert saved.status_code == 200, saved.text
    assert saved.json()["draft"]["gallery_source"] == source
    forged = client.put(f"/api/v3/workspaces/{record['id']}", json={
        "revision": saved.json()["revision"], "draft": {
            "gallery_source": {**source, "path": "two.png"}}})
    assert forged.status_code == 422, forged.text
    assert forged.json()["error"]["code"] == "read_only_field"
    assert client.get(f"/api/v3/workspaces/{record['id']}").json() == saved.json()
