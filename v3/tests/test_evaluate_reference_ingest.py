import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from anima_prompt_studio_v3.core.requirements import WorkbenchError, Requirements, dump
from anima_prompt_studio_v3.tools import evaluate_reference_ingest as evaluation


SOURCE = Path(__file__).resolve().parents[1] / "example-packs/cma-styles-20260910-v1"


def test_blind_capture_keeps_expected_separate_and_never_marks_quality_passed(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation, "configured_model", lambda: (True, {"model": "fake-vision"}))
    calls = []

    async def fake(self, example_id, request):
        record = self.store.get(example_id)
        assert record["requirements"] is None
        assert record["notes"]["external_prompt"] == ""
        assert record["title"] == "视觉验收图片"
        assert not request.use_external_prompt_notes
        calls.append(example_id)
        return {"requirements": dump(Requirements.empty()), "warnings": ["review image"]}

    monkeypatch.setattr(evaluation.IngestService, "ingest", fake)
    output = tmp_path / "capture"
    report = asyncio.run(evaluation.evaluate(SOURCE, output))
    assert len(calls) == 3
    assert report["status"] == "completed"
    assert report["quality_verdict"] == "pending_manual_review"
    saved = json.loads((output / "report.json").read_bytes())
    assert saved == report
    assert all(row["expected_requirements"] != row["actual_requirements"] for row in saved["results"])
    with pytest.raises(FileExistsError):
        asyncio.run(evaluation.evaluate(SOURCE, output))
    assert len(calls) == 3


def test_failure_is_recorded_without_retry_or_raw_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation, "configured_model", lambda: (True, {"model": "fake-vision"}))
    calls = []

    async def fail(self, example_id, request):
        calls.append(example_id)
        raise WorkbenchError("llm_generation_failed", "Bearer secret-must-not-be-recorded")

    monkeypatch.setattr(evaluation.IngestService, "ingest", fail)
    output = tmp_path / "capture"
    report = asyncio.run(evaluation.evaluate(SOURCE, output))
    assert len(calls) == 1
    assert report["status"] == "stopped"
    assert report["results"][0]["error_code"] == "llm_generation_failed"
    assert "secret-must-not-be-recorded" not in (output / "report.json").read_text(encoding="utf-8")


def test_missing_configuration_creates_no_capture(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation, "configured_model", lambda: (False, {}))
    output = tmp_path / "capture"
    with pytest.raises(ValueError, match="Configure"):
        asyncio.run(evaluation.evaluate(SOURCE, output))
    assert not output.exists()


def test_cli_selects_explicit_application_config_before_preflight(tmp_path, monkeypatch, capsys):
    config = tmp_path / "portable-prompt-assistant"
    (config / "config").mkdir(parents=True)
    (config / "config/config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ANIMA_PROMPT_ASSISTANT_DIR", "previous-default")
    monkeypatch.setattr(sys, "argv", ["evaluate", str(SOURCE), "--config-dir", str(config)])

    def configured():
        assert Path(os.environ["ANIMA_PROMPT_ASSISTANT_DIR"]) == config.resolve()
        return False, {"model": "configured-model"}

    monkeypatch.setattr(evaluation, "configured_model", configured)
    evaluation.main()
    result = json.loads(capsys.readouterr().out)
    assert result["model"]["model"] == "configured-model"
    assert result["executed"] is False
