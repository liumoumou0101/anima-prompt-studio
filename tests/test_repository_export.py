import json

from anima_prompt_studio.domain.models import CompositionFieldState, PromptJob
from anima_prompt_studio.repositories.sqlite_repository import SQLiteRepository
from anima_prompt_studio.services.export_service import ExportService


def test_history_round_trip(tmp_path):
    repo = SQLiteRepository(tmp_path / "test.db")
    job = PromptJob(project_name="测试", original_zh="白发女孩", positive_prompt="1girl, white hair")
    repo.save_job(job, favorite=True)
    loaded = repo.load_job(job.id)
    assert loaded.positive_prompt == job.positive_prompt
    assert repo.list_jobs()[0]["favorite"] == 1
    repo.close()


def test_history_round_trip_preserves_composition_decisions(tmp_path):
    repo = SQLiteRepository(tmp_path / "composition.db")
    job = PromptJob(original_zh="女孩读书")
    job.composition.gaze = "看物体"
    decision = job.composition.decision("gaze")
    decision.state = CompositionFieldState.LOCKED; decision.reason = "阅读时看书"; decision.source_rule_ids = ["reading"]
    repo.save_job(job)
    loaded = repo.load_job(job.id)
    assert loaded.composition.gaze == "看物体"
    assert loaded.composition.decision("gaze").state == CompositionFieldState.LOCKED
    assert loaded.composition.decision("gaze").source_rule_ids == ["reading"]
    repo.close()


def test_json_export(tmp_path):
    job = PromptJob(
        original_zh="测试",
        positive_prompt="safe",
        generation_preset_id="quality",
        quality_profile_id="portrait_detail",
    )
    path = ExportService().export_task(job, tmp_path / "job.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.4"
    assert data["generation_preset"] == "quality"
    assert data["quality_profile"] == "portrait_detail"
    assert data["composition"]["mode"] == "smart"
    assert data["positive_prompt"] == "safe"
