from __future__ import annotations

from pathlib import Path
from typing import Protocol

from anima_prompt_studio.domain.models import PromptJob
from anima_prompt_studio.domain.execution_models import EnvironmentReport, GenerationRun


class ExecutionTarget(Protocol):
    """Execution boundary shared by local and remote generation targets."""

    def validate_environment(self) -> EnvironmentReport: ...
    def submit(self, job: PromptJob) -> str: ...
    def get_progress(self, remote_job_id: str) -> GenerationRun: ...
    def cancel(self, remote_job_id: str) -> None: ...
    def download_results(self, remote_job_id: str, target_dir: Path) -> list[Path]: ...

