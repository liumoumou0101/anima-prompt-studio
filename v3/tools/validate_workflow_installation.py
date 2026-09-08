"""Opt-in real GPU smoke test using an empty database and public test prompt.

Reads credentials from the existing OS store. Does not install server dependencies.
"""
import argparse
import json
from pathlib import Path
import tempfile
import time

from anima_prompt_studio.repositories import SQLiteRepository
from anima_prompt_studio.domain.models import PromptJob, GenerationParams
from anima_prompt_studio.services.config_service import ConfigService
from anima_prompt_studio_v3.adapters.v2.workflow_catalog import WorkflowCatalog, catalog
from anima_prompt_studio_v3.adapters.v2.generation_queue import build_v2_generation_queue
from anima_prompt_studio_v3.adapters.v2.generation import V2PreparedGeneration
from anima_prompt_studio_v3.core.generation_recipes import build_workflow_recipe_contract


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--remote-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--auto-inspect-on-submit", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    repo = SQLiteRepository(args.database)
    try:
        remote = repo.get_remote_profile(args.remote_id)
    finally:
        repo.close()
    with tempfile.TemporaryDirectory(prefix="anima-fresh-install-") as temporary:
        database = Path(temporary) / "user.db"
        repo = SQLiteRepository(database)
        repo.save_remote_profile(remote)
        repo.set_setting("generation_output_root", str(args.output.resolve()))
        assert repo.list_workflow_profiles() == []
        repo.close()
        manager = WorkflowCatalog(database)
        if not args.auto_inspect_on_submit:
            manager.inspect(remote.id)
        report = manager.report(remote.id)
        print("Cached devices before submission:", report["devices"], flush=True)
        results = []
        queue = build_v2_generation_queue(database)
        try:
            for item in report["items"]:
                if item["origin"] != "official" or item["experimental"]:
                    continue
                if item["state"] != "ready" and not args.auto_inspect_on_submit:
                    raise RuntimeError(item["errors"])
                if args.auto_inspect_on_submit:
                    # First request has no snapshot; later requests have expired
                    # snapshots. Neither path invokes settings inspection first.
                    manager.invalidate(remote.id)
                    workflow = next(p for p, _ in catalog(database) if p.id == item["workflow_id"])
                else:
                    workflow = manager.resolve(remote.id, item["workflow_id"])
                recipe = build_workflow_recipe_contract(workflow)
                default = next(r for r in recipe["generation_recipes"] if r["id"] == recipe["default_recipe_id"])
                model = item["model_profiles"][0]
                job = PromptJob(project_name="Workflow installation acceptance", model_profile_id=model,
                    positive_prompt="a small wooden cabin beside a lake, mountains, clear sky, anime background illustration, no people",
                    negative_prompt="low quality, blurry", generation_preset_id=default["id"],
                    generation_params=GenerationParams(width=640, height=832, batch_size=1, seed=20260905, **default["parameters"]))
                if model == "anima_turbo_v1_1":
                    job.negative_prompt = ""
                prepared = V2PreparedGeneration(job, ConfigService().get_model(model).checkpoint_logical_name)
                start = time.monotonic()
                run = queue.submit(prepared, remote_profile_id=remote.id, workflow_profile_id=workflow.id, idempotency_key=job.id)
                print("Submitted", workflow.id, flush=True)
                while time.monotonic() - start < 240:
                    current = next(r for r in queue.list() if r.id == run.id)
                    if current.state.value in {"completed", "failed", "canceled"}:
                        break
                    time.sleep(1)
                if current.state.value != "completed":
                    raise RuntimeError(f"{workflow.id}: {current.state.value}: {current.error_message}")
                artifacts = queue.artifacts(run.id)
                assert len(artifacts) == 1 and Path(artifacts[0].local_path).is_file()
                results.append({"workflow": workflow.id, "revision": item["revision"], "state": current.state.value,
                                "seconds": round(time.monotonic() - start, 2), "image": artifacts[0].local_path})
                print("Completed", workflow.id, results[-1]["seconds"], flush=True)
        finally:
            queue.shutdown(cancel_active=True, timeout=40)
        (args.output / "acceptance.json").write_text(json.dumps({"empty_workflow_database": True, "auto_inspect_on_submit": args.auto_inspect_on_submit, "devices": manager.report(remote.id)["devices"], "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
