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
                                             ("moss_image_sft_int8", "moss_image_sft_int8")])
def test_legacy_fallback_keeps_prompt_recorded_parameters_and_model_defaults(conversation_client, tmp_path, model, expected):
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
    assert settings["seed"] == "8798399215689017476"
    assert settings["cfg"] == 9 and settings["steps"] == 99
    assert settings["creation_configuration"]["parameterOverrides"] == {"cfg":9,"steps":99,"seed":"8798399215689017476"}
    assert settings["sampler"] == defaults.sampler and settings["scheduler"] == defaults.scheduler
    assert settings["width"] == defaults.default_width and settings["height"] == defaults.default_height
    assert settings["aspect"] == "custom"
    assert settings["remote_profile_id"] is None and settings["workflow_profile_id"] is None
    assert draft["compile_state"] == "fresh"
    assert calls == []


@pytest.mark.parametrize("model", ["old-custom-model", ""])
def test_unidentified_gallery_model_does_not_create_an_aesthetic_workspace(conversation_client, tmp_path, model):
    client, _ = conversation_client
    gallery(client, tmp_path, model=model)
    before = client.get("/api/v3/workspaces").json()
    rejected = client.post(ROUTE, json={"path":"one.png"})
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"]["code"] == "model_profile_unknown"
    assert client.get("/api/v3/workspaces").json() == before


def test_missing_workflow_uses_prompt_fallback(conversation_client, tmp_path):
    client, _ = conversation_client
    root, _ = gallery(client, tmp_path)
    generation(client, root, workflow=False)
    snapshot=client.app.state.submission_service.store.for_runs(["run1"])[0]["snapshot"]
    snapshot["job"]={"model_profile_id":"moss_image_sft_int8","positive_prompt":"来自已验证任务的中文", "negative_prompt":"裁切",
                     "generation_params":{"steps":21,"seed":42}}
    response = client.post(ROUTE, json={"path": "one.png"})
    assert response.status_code == 201, response.text
    draft=response.json()["draft"]
    assert draft["gallery_source"]["mode"] == "prompt" and draft["generation_source"] is None
    assert draft["model_profile"] == "moss_image_sft_int8"
    assert (draft["compiled"]["positive"], draft["compiled"]["negative"]) == ("来自已验证任务的中文","裁切")
    assert (draft["generation_settings"]["steps"],draft["generation_settings"]["seed"])==(21,42)


@pytest.mark.parametrize("model,workflow", [("moss_image_sft_int8","v3_moss_image_sft_int8"), ("anima_base_v1","v3_base_v1")])
def test_task_gallery_and_reference_continue_the_accepted_job_and_selected_image(conversation_client, tmp_path, model, workflow):
    from PIL import Image, PngImagePlugin
    from anima_prompt_studio_v3.runtime.packaged_workflows import packaged_workflow_profiles
    from anima_prompt_studio_v3.core.workflow_parameters import build_workflow_parameter_schema
    from anima_prompt_studio_v3.core.requirements import Requirements, dump
    from anima_prompt_studio_v3.storage.generation_submissions import SubmissionStore
    client, calls = conversation_client
    root, _ = gallery(client, tmp_path, model=model)
    profile = next(item for item in packaged_workflow_profiles() if item.id == workflow)
    schema = build_workflow_parameter_schema(profile)
    batch_seed, image_seed = 9223372036854775805, 9223372036854775807
    params = {key: value for key,value in ((field['key'],field['default']) for field in schema['fields'])}
    params.update(seed=batch_seed,batch_size=2,width=1024,height=1024,steps=27,cfg=2.75)
    positive, negative = "  第一段，\n第二段。  ", " 裁切，模糊\n"
    snapshot = {"job":{"model_profile_id":model,"positive_prompt":positive,"negative_prompt":negative,
        "generation_params":params,"integration_metadata":{}},
        "provenance":{"model_profile":"anima_aesthetic_v1_1","positive":"stale metadata","negative":"stale",
                      "requirements":dump(Requirements.empty()),"settings":{"seed":-1,"steps":35}},
        "workflow":profile.model_dump(mode="json"),"run":{"workflow_profile_id":workflow,"remote_profile_id":"source-cloud"},"resources":[]}
    submissions = SubmissionStore(client.app.state.workspace_store)
    submissions.accept(submission_id="sub_test",key="source-key",payload_hash="original",run_id="run1",snapshot=snapshot,response={"id":"run1"})
    artifacts = [SimpleNamespace(local_path=str(root/name)) for name in ("one.png","two.png")]
    client.app.state.submission_service = SimpleNamespace(store=submissions,queue=SimpleNamespace(artifacts=lambda _run: artifacts))
    png = PngImagePlugin.PngInfo(); png.add_text("Seed",str(image_seed))
    Image.new("RGB",(8,8)).save(root/"two.png",pnginfo=png)

    def check(response, seed, batch):
        assert response.status_code == 201, response.text
        draft = response.json()["draft"]
        assert draft["model_profile"] == model
        assert draft["compiled"]["positive"] == positive and draft["compiled"]["negative"] == negative
        assert draft["generation_source"] == {"run_id":"run1","model_profile":model,"workflow_profile_id":workflow,"remote_profile_id":"source-cloud"}
        settings = draft["generation_settings"]
        assert (settings["seed"],settings["batch_size"],settings["steps"],settings["cfg"]) == (str(seed),batch,27,2.75)
        assert settings["parameter_schema"] == schema
        config = settings["creation_configuration"]
        assert config["workflow"] == {"id":workflow,"revision":schema["templateRevision"]}
        assert config["parameterOverrides"]["seed"] == str(seed) and config["parameterOverrides"]["batch_size"] == batch
        assert client.get(f"/api/v3/workspaces/{response.json()['id']}").json()["draft"] == draft

    check(client.post("/api/v3/generation-runs/run1/workspace",json={}),batch_seed,2)
    check(client.post(ROUTE,json={"path":"one.png"}),batch_seed,2)
    check(client.post(ROUTE,json={"path":"two.png"}),image_seed,1)
    example = client.post("/api/v3/reference-examples/from-run",json={"run_id":"run1","path":"two.png"})
    assert example.status_code == 201, example.text
    item = example.json()
    assert item["compat"]["model_profiles"] == [model]
    borrowed=client.post(f"/api/v3/reference-examples/{item['id']}/workspace",json={"source_version":item['source_version'],"mode":"prompt"})
    assert borrowed.status_code == 201, borrowed.text
    assert borrowed.json()["draft"]["model_profile"] == model
    assert borrowed.json()["draft"]["compiled"]["positive"] == positive
    assert borrowed.json()["draft"]["compiled"]["negative"] == negative
    requirements=client.post(f"/api/v3/reference-examples/{item['id']}/workspace",json={"source_version":item['source_version'],"mode":"requirements"})
    assert requirements.status_code == 201, requirements.text
    assert requirements.json()["draft"]["model_profile"] == model
    check(client.post(f"/api/v3/reference-examples/{item['id']}/workspace",json={"source_version":item['source_version'],"mode":"generation"}),image_seed,1)
    assert calls == []


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


def test_atomic_template_adoption_preserves_snapshot_on_conflict_and_saves_literal_conditions(conversation_client, tmp_path):
    client, _ = conversation_client
    root, _ = gallery(client, tmp_path)
    generation(client, root)
    record = client.post(ROUTE, json={"path": "one.png"}).json()
    path = "/api/v3/workspaces/" + record["id"]
    draft = record["draft"]
    assert draft["generation_source"]["run_id"] == "run1"
    conditions = {"model_profile": draft["model_profile"], "detach_generation_source": True,
                  "prompt_edit": {"positive": "  cafe\n  portrait  ", "negative": "  no text  "},
                  "generation_settings": {**draft["generation_settings"], "workflow_profile_id": "live-template",
                                          "seed": "9223372036854775806"}}
    payload = {"revision": record["revision"], "title": record["title"], "draft": conditions}
    stale = client.put(path, json={**payload, "revision": record["revision"] + 1})
    assert stale.status_code == 409, stale.text
    assert client.get(path).json()["draft"] == draft
    invalid = client.put(path, json={**payload, "draft": {**conditions, "detach_generation_source": "yes"}})
    assert invalid.status_code == 422
    assert client.get(path).json()["draft"] == draft
    updated = client.put(path, json=payload)
    assert updated.status_code == 200, updated.text
    saved = updated.json()["draft"]
    assert saved["generation_source"] is None and "detach_generation_source" not in saved
    assert saved["generation_settings"]["workflow_profile_id"] == "live-template"
    assert str(saved["generation_settings"]["seed"]) == "9223372036854775806"
    assert saved["compiled"]["positive"] == "  cafe\n  portrait  " and saved["compiled"]["negative"] == "  no text  "
    assert updated.json()["revision"] == record["revision"] + 1
    previous = client.app.state.workspace_store.get_version(record["id"], record["revision"])
    assert previous["draft"]["generation_source"] == draft["generation_source"]
    assert previous["draft"]["compiled"]["positive"] == draft["compiled"]["positive"]


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
