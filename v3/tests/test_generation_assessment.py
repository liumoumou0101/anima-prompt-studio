from types import SimpleNamespace

from test_conversation import conversation_client, reference_db, edit
from test_reference_examples import picture
from anima_prompt_studio_v3.core.requirements import Requirements


def test_run_assessment_notes_and_frozen_provenance_are_saved_together(conversation_client, tmp_path):
    client, calls = conversation_client
    image = tmp_path / "review.png"
    image.write_bytes(picture())
    requirements = Requirements(**edit()).model_dump(mode="json", by_alias=True)
    provenance = {"requirements": requirements, "positive": "original tags", "negative": "", "model_profile": "animayume_v1_5_base",
                  "settings": {"seed": 123, "steps": 30, "cfg": 5.5}, "workflow_snapshot_ref": "run_review"}
    client.app.state.gallery_service = SimpleNamespace(resolve_content=lambda path: image if path == "review.png" else None)
    client.app.state.submission_service = SimpleNamespace(
        store=SimpleNamespace(for_runs=lambda ids: [{"snapshot": {"provenance": provenance}}]),
        queue=SimpleNamespace(artifacts=lambda run_id: [SimpleNamespace(local_path=image)]))
    notes = "人工实测记录（单图观察）\n角色辨识：符合预期\n结构：不符合预期"
    response = client.post("/api/v3/reference-examples/from-run", json={"run_id": "run_review", "path": "review.png", "user_notes": notes})
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["revision"] == 1
    assert item["notes"]["user_notes"] == notes
    assert item["notes"]["external_prompt"] == "正向：original tags\n负向："
    assert item["provenance"]["model_profile"] == "animayume_v1_5_base"
    assert item["provenance"]["settings"] == provenance["settings"]
    assert item["provenance"]["run_id"] == "run_review"
    assert item["provenance"]["workflow_snapshot_ref"] == "run_review"
    assert item["requirements"] == requirements
    assert client.app.state.example_store.get(item["id"])["notes"]["user_notes"] == notes
    assert calls == []


def test_oversized_assessment_is_rejected_before_creating_reference(conversation_client):
    client, _ = conversation_client
    response = client.post("/api/v3/reference-examples/from-run", json={"run_id": "run_review", "path": "review.png", "user_notes": "x" * 20001})
    assert response.status_code == 422
    assert client.get("/api/v3/reference-examples").json()["items"] == []
