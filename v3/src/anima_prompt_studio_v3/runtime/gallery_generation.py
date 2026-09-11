"""Gallery variations use the same durable submission path as the workbench."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from anima_prompt_studio.domain.models import PromptJob
from ..api.models import DirectPromptSubmitRequest
from ..core.requirements import WorkbenchError, digest
from .generation import PreparedGeneration


class GalleryGenerationService:
    def __init__(self, submissions):
        self.submissions = submissions
        self.queue = submissions.queue

    def submit(self, asset, count, key):
        if not 1 <= count <= 4:
            raise ValueError("每张再出数量必须为 1–4。")
        entries = self.submissions.store.for_runs([asset["batch_id"]])
        if not entries:
            raise WorkbenchError("gallery_snapshot_missing",
                "原图缺少完整生成快照，无法沿用原条件。请复制提示词到会话工作台，明确选择模型和工作流后生成。")
        snapshot = entries[0]["snapshot"]
        original = PromptJob.model_validate(snapshot["job"])
        source_run = snapshot["run"]
        params = original.generation_params.model_dump(mode="json")
        settings = {name: params[name] for name in
                    ("width", "height", "steps", "cfg", "sampler", "scheduler")}
        request = DirectPromptSubmitRequest(
            positive_prompt=original.positive_prompt, negative_prompt=original.negative_prompt,
            model_profile=original.model_profile_id, project_name=original.project_name,
            settings={**settings, "seed": -1, "batch_size": count},
            remote_profile_id=source_run["remote_profile_id"],
            workflow_profile_id=source_run["workflow_profile_id"],
            workflow_snapshot_run_id=source_run["id"],
            lora_selection=[{k: resource[k] for k in ("logical_id", "file_name", "weight", "trigger_words")}
                            for resource in snapshot["resources"]],
        )

        def prepare():
            job = original.model_copy(deep=True)
            job.id = str(uuid4())
            job.created_at = job.updated_at = datetime.now(timezone.utc)
            job.generation_params.seed = -1
            job.generation_params.batch_size = count
            job.integration_metadata["gallery_regenerate"] = {
                "source_run_id": source_run["id"], "source_image": asset["path"],
                "source_seed": original.generation_params.seed, "count": count,
            }
            # A new random seed is not part of the old fixed-seed comparison.
            comparison = job.integration_metadata.get("artist_comparison")
            if comparison:
                job.integration_metadata["artist_comparison"] = {
                    k: v for k, v in comparison.items() if k not in {"id", "position", "total", "seed"}}
                job.integration_metadata["artist_comparison"].update(
                    id=job.id, derived_from="gallery_regenerate", source_comparison_id=comparison.get("id", ""))
            return PreparedGeneration(job=job, checkpoint_logical_name=snapshot["checkpoint_logical_name"])

        response = self.submissions.submit(request, "gallery:" + digest({"key": key, "path": asset["path"]}),
            "gallery_regenerate:" + asset["path"], prepare, expected_snapshot=snapshot)
        return self.payload(self.queue.get(response["id"]))

    @staticmethod
    def origin(run):
        return run.request_json.get("prompt_job", {}).get("integration_metadata", {}).get("gallery_regenerate")

    def payload(self, run):
        origin = self.origin(run) or {}
        return {"id": run.id, "operation": "gallery_txt2img_more", "state": run.state.value,
                "message": run.status_message, "progress": run.progress,
                "sourceName": Path(origin.get("source_image", "")).name,
                "sourcePath": origin.get("source_image", ""), "error": run.error_message}

    def list_jobs(self):
        return [self.payload(run) for run in self.queue.list(limit=1000) if self.origin(run)]

    def cancel(self, job_id):
        run = self.queue.get(job_id)
        if not self.origin(run):
            raise ValueError("不是画廊再生成任务。")
        return self.payload(self.queue.cancel_queued(job_id))
