"""Single-run reads retain the same accepted provenance as workspace history."""

from fastapi.testclient import TestClient

from anima_prompt_studio_v3.api import create_api_runtime
from test_api import reference_db
from test_generation_submissions import harness, workspace_payload


def test_single_run_retains_accepted_source_outside_recent_workspace_page(harness, reference_db):
    store, start, _, executed, _, _ = harness
    queue, _ = start()
    workspace, request = workspace_payload(store)
    runtime = create_api_runtime(reference_db, workspace_db=store.path, generation_queue=queue)
    runtime.app.state.submission_service.close()
    with TestClient(runtime.app, base_url="http://127.0.0.1") as client:
        client.headers["Origin"] = "http://127.0.0.1"
        exchange = client.post("/api/v3/session/exchange", json={"bootstrap_token": runtime.bootstrap_token})
        client.headers["X-Anima-Session"] = exchange.json()["session_token"]
        data = request.model_dump(exclude_unset=True)
        data.update(positive_prompt="woman, blue coat", negative_prompt="blurry")
        data["settings"] = {"seed": "8798399215689017476", "width": 896, "height": 1152,
                            "steps": 31, "cfg": 5.5, "sampler": "euler", "scheduler": "normal"}
        first = client.post("/api/v3/direct-prompt/runs", json=data, headers={"Idempotency-Key": "old-blue"})
        assert first.status_code == 202, first.text
        accepted = first.json()
        data.update(workspace_revision=accepted["workspace_revision"], compiled_token=accepted["compiled_token"],
                    positive_prompt="woman, red coat")
        data["settings"]["seed"] = 42
        newer = client.post("/api/v3/direct-prompt/runs", json=data, headers={"Idempotency-Key": "new-red"})
        assert newer.status_code == 202, newer.text
        recent = client.get(f"/api/v3/workspaces/{workspace['id']}/runs", params={"limit": 1}).json()
        assert [item["id"] for item in recent["items"]] == [newer.json()["id"]]

        response = client.get(f"/api/v3/generation-runs/{accepted['id']}")
        assert response.status_code == 200, response.text
        source = response.json().get("source")
        assert source is not None, "Single-run restore must carry the accepted submission snapshot"
        assert source["workspace_revision"] == accepted["workspace_revision"]
        assert source["workspace_revision"] < newer.json()["workspace_revision"]
        assert source["positive_prompt"] == "woman, blue coat"
        assert source["negative_prompt"] == "blurry"
        assert source["model_profile"] == "anima_base_v1"
        assert {field: source["settings"][field] for field in (
            "seed", "width", "height", "steps", "cfg", "sampler", "scheduler")
        } == {"seed": "8798399215689017476", "width": 896, "height": 1152,
              "steps": 31, "cfg": 5.5, "sampler": "euler", "scheduler": "normal"}
        assert set(source) == {"workspace_revision", "positive_prompt", "negative_prompt", "model_profile", "settings"}
        older_page = client.get(f"/api/v3/workspaces/{workspace['id']}/runs", params={"limit": 1, "offset": 1}).json()
        assert source == older_page["items"][0]["source"]
        assert not executed


def test_single_run_without_submission_service_keeps_unknown_source(harness, reference_db):
    store, start, _, executed, _, _ = harness
    queue, _ = start()
    _, request = workspace_payload(store)
    runtime = create_api_runtime(reference_db, workspace_db=store.path, generation_queue=queue)
    runtime.app.state.submission_service.close()
    with TestClient(runtime.app, base_url="http://127.0.0.1") as client:
        client.headers["Origin"] = "http://127.0.0.1"
        exchange = client.post("/api/v3/session/exchange", json={"bootstrap_token": runtime.bootstrap_token})
        client.headers["X-Anima-Session"] = exchange.json()["session_token"]
        submitted = client.post("/api/v3/direct-prompt/runs", json=request.model_dump(exclude_unset=True),
                                headers={"Idempotency-Key": "legacy"})
        assert submitted.status_code == 202, submitted.text
        runtime.app.state.submission_service = None
        response = client.get(f"/api/v3/generation-runs/{submitted.json()['id']}")
        assert response.status_code == 200, response.text
        assert response.json()["source"] is None
        assert client.get("/api/v3/generation-runs/missing").status_code == 404
        assert not executed
