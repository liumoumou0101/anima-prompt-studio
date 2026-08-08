from __future__ import annotations

from pathlib import Path
from typing import Protocol

from anima_prompt_studio.domain.models import PromptJob


class ExecutionTarget(Protocol):
    """V2 extension boundary. V1 deliberately provides no implementation."""

    def validate_environment(self) -> object: ...
    def submit(self, job: PromptJob) -> str: ...
    def get_progress(self, remote_job_id: str) -> object: ...
    def cancel(self, remote_job_id: str) -> None: ...
    def download_results(self, remote_job_id: str, target_dir: Path) -> list[Path]: ...

