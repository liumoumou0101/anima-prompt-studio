from __future__ import annotations

from pathlib import Path

from anima_prompt_studio.domain.models import PromptJob


class ExportService:
    def export_task(self, job: PromptJob, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(__import__("json").dumps(job.task_package(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

