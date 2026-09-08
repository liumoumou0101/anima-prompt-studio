"""Read-only audit of saved V3 recipes through the real submission renderer."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "v3" / "src")]

from anima_prompt_studio.domain.execution_models import RemoteProfile, WorkflowProfile, SUPPORTED_GENERATION_WORKFLOW_KINDS
from anima_prompt_studio.repositories import default_data_dir
from anima_prompt_studio.services.remote.workflow_renderer import WorkflowRenderer
from anima_prompt_studio_v3.adapters.v2.generation import CandidateToV2PromptJobAdapter, V2GenerationSettings
from anima_prompt_studio_v3.core.generation_recipes import build_workflow_recipe_contract, validate_job_recipe


def verify_completed_report(report_path: Path) -> None:
    """Compare persisted submitted nodes and downloaded dimensions to requests."""
    from PySide6.QtGui import QImage

    report = json.loads(report_path.read_text(encoding="utf-8"))
    database = default_data_dir() / "anima_prompt_studio.db"
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as conn:
        runs = [json.loads(row[0]) for row in conn.execute(
            "SELECT payload_json FROM generation_runs WHERE remote_profile_id=? ORDER BY updated_at DESC",
            (report["remote_profile_id"],),
        )]
        workflows = {w.id: w for w in (
            WorkflowProfile.model_validate_json(row[0]) for row in conn.execute("SELECT payload_json FROM workflow_profiles")
        )}
    verified = []
    for entry in report["results"]:
        run = next(r for r in runs if
            r["request_json"].get("prompt_job", {}).get("project_name") == "V3 配方验收 " + entry["label"]
            and r["request_json"].get("resolved_seed") == report["seed"])
        assert run["state"] == "completed", entry["label"]
        workflow = workflows[entry["workflow_profile_id"]]
        actual = run["actual_workflow"]
        job = run["request_json"]["prompt_job"]
        expected = {**job["generation_params"], "positive_prompt": job["positive_prompt"], "negative_prompt": job["negative_prompt"]}
        for field in ("steps", "cfg", "sampler", "scheduler", "width", "height", "batch_size", "positive_prompt", "negative_prompt"):
            binding = workflow.bindings[field]
            assert actual[binding.node_id]["inputs"][binding.input_name] == expected[field], (entry["label"], field)
        binding = workflow.bindings["seed"]
        assert actual[binding.node_id]["inputs"][binding.input_name] == report["seed"]
        sizes = []
        for path in entry["image_paths"]:
            image = QImage(str(path))
            assert not image.isNull(), path
            size = (image.width(), image.height())
            metadata = run["request_json"]["render_metadata"]
            assert size == (metadata.get("output_width", expected["width"]), metadata.get("output_height", expected["height"]))
            sizes.append(size)
        assert len(sizes) == expected["batch_size"]
        verified.append({"label": entry["label"], "run_id": run["id"], "remote_prompt_id": run["remote_prompt_id"], "sizes": sizes, "passed": True})
    output = report_path.parent / "submitted_parameter_verification.json"
    output.write_text(json.dumps(verified, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"verified_completed_runs": len(verified), "output": str(output)}, ensure_ascii=True))


def main() -> None:
    database = default_data_dir() / "anima_prompt_studio.db"
    report = {"remote_generation": "not_performed", "workflows": [], "errors": []}
    renderer = WorkflowRenderer()
    adapter = CandidateToV2PromptJobAdapter()
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as conn:
        workflows = [WorkflowProfile.model_validate_json(row[0]) for row in conn.execute("SELECT payload_json FROM workflow_profiles")]
        remotes = [RemoteProfile.model_validate_json(row[0]) for row in conn.execute("SELECT payload_json FROM remote_profiles")]
    for workflow in workflows:
        row = {"id": workflow.id, "kind": workflow.workflow_kind, "models": workflow.compatible_model_profiles, "recipes": []}
        report["workflows"].append(row)
        if workflow.workflow_kind not in SUPPORTED_GENERATION_WORKFLOW_KINDS or not workflow.compatible_model_profiles:
            row["status"] = "not_exposed_in_v3_generation"
            continue
        try:
            contract = build_workflow_recipe_contract(workflow)
            row["default_recipe"] = contract["default_recipe_id"]
            for model in workflow.compatible_model_profiles:
                for recipe in contract["generation_recipes"]:
                    prepared = adapter.prepare_direct(positive_prompt="1girl, solo, adult woman, standing in a garden", negative_prompt="blurry, text", model_profile_id=model, settings=V2GenerationSettings(preset_id=recipe["id"], seed=20260908, **recipe["parameters"]))
                    validate_job_recipe(prepared.job, workflow)
                    for remote in remotes:
                        result = renderer.render(prepared.job, workflow, remote, prepared.checkpoint_logical_name, "parameter-audit")
                        actual = {}
                        for field in ("steps", "cfg", "sampler", "scheduler", "width", "height", "seed", "batch_size", "positive_prompt", "negative_prompt"):
                            binding = workflow.bindings[field]
                            actual[field] = result.workflow[binding.node_id]["inputs"][binding.input_name]
                        for field, expected in recipe["parameters"].items():
                            assert actual[field] == expected, (field, actual[field], expected)
                        assert actual["width"] == 896 and actual["height"] == 1152
                        assert actual["seed"] == 20260908 and actual["batch_size"] == 1
                        assert actual["positive_prompt"] == prepared.job.positive_prompt
                        assert actual["negative_prompt"] == prepared.job.negative_prompt
                        row["recipes"].append({"model": model, "remote_id": remote.id, "recipe": recipe["id"], "evidence": recipe["evidence"], "actual": actual, "checkpoint": result.checkpoint_name, "runtime": result.metadata})
            row["status"] = "render_passed"
        except Exception as exc:
            row["status"] = "failed"
            report["errors"].append({"workflow": workflow.id, "error": str(exc)})
    output = ROOT / "reports" / "parameter_audit_20260908"
    output.mkdir(parents=True, exist_ok=True)
    (output / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"workflows": len(workflows), "supported": sum(w["status"] == "render_passed" for w in report["workflows"]), "rendered_requests": sum(len(w["recipes"]) for w in report["workflows"]), "errors": report["errors"]}, ensure_ascii=False))
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    if len(sys.argv) == 2:
        verify_completed_report(Path(sys.argv[1]))
    else:
        main()
