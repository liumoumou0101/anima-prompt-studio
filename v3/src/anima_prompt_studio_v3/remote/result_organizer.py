from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
from pathlib import Path

from anima_prompt_studio.domain.execution_models import GenerationArtifact, GenerationRun, RemoteArtifact
from anima_prompt_studio.domain.models import PromptJob


WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def default_output_root() -> Path:
    pictures = Path.home() / "Pictures"
    return pictures / "AnimaPromptStudio"


def sanitize_path_segment(value: str, fallback: str = "未分类", max_length: int = 80) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).rstrip(" .")
    if not cleaned:
        cleaned = fallback
    if cleaned.upper() in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned[:max_length].rstrip(" .") or fallback


class ResultOrganizer:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_output_root()).expanduser()

    def output_directory(self, job: PromptJob, run: GenerationRun) -> Path:
        if run.output_dir:
            output = Path(run.output_dir)
            output.mkdir(parents=True, exist_ok=True)
            return output
        subject = job.effective_subject_mode().value
        created = run.created_at.astimezone()
        output = self.root.joinpath(
            sanitize_path_segment(job.project_name, "未命名项目"),
            sanitize_path_segment(subject),
            sanitize_path_segment(job.model_profile_id),
            created.strftime("%Y-%m-%d"),
            f"{created.strftime('%H%M%S')}_{run.id[:8]}",
        )
        root_resolved = self.root.resolve()
        output_resolved = output.resolve()
        if root_resolved != output_resolved and root_resolved not in output_resolved.parents:
            raise ValueError("输出目录超出配置的图片根目录。")
        output.mkdir(parents=True, exist_ok=True)
        run.output_dir = str(output)
        return output

    def save_artifact(
        self,
        job: PromptJob,
        run: GenerationRun,
        remote: RemoteArtifact,
        content: bytes,
        index: int,
        mime_type: str = "",
    ) -> GenerationArtifact:
        output_dir = self.output_directory(job, run)
        suffix = Path(remote.filename).suffix.lower()
        if not suffix or len(suffix) > 10:
            suffix = mimetypes.guess_extension(mime_type.split(";", 1)[0]) or ".bin"
        seed = run.request_json.get("resolved_seed", job.generation_params.seed)
        stem = sanitize_path_segment(job.project_name, "anima", 48)
        filename = f"{stem}_{run.created_at.astimezone().strftime('%H%M%S')}_seed{seed}_{index:02d}{suffix}"
        target = output_dir / filename
        digest = hashlib.sha256(content).hexdigest()
        collision = 1
        while target.exists():
            if self._sha256_file(target) == digest:
                return GenerationArtifact(
                    generation_run_id=run.id,
                    node_id=remote.node_id,
                    remote_filename=remote.filename,
                    remote_subfolder=remote.subfolder,
                    remote_type=remote.folder_type,
                    local_path=str(target),
                    sha256=digest,
                    byte_size=len(content),
                    mime_type=mime_type or mimetypes.guess_type(target.name)[0] or "application/octet-stream",
                    download_state="completed",
                )
            target = output_dir / f"{Path(filename).stem}_{collision}{suffix}"
            collision += 1
        part = target.with_name(target.name + ".part")
        part.write_bytes(content)
        os.replace(part, target)
        return GenerationArtifact(
            generation_run_id=run.id,
            node_id=remote.node_id,
            remote_filename=remote.filename,
            remote_subfolder=remote.subfolder,
            remote_type=remote.folder_type,
            local_path=str(target),
            sha256=digest,
            byte_size=len(content),
            mime_type=mime_type or mimetypes.guess_type(target.name)[0] or "application/octet-stream",
            download_state="completed",
        )

    def write_sidecars(
        self,
        job: PromptJob,
        run: GenerationRun,
        artifacts: list[GenerationArtifact],
    ) -> None:
        output_dir = self.output_directory(job, run)
        manifest = {
            "schema_version": "2.0",
            "generation_run": run.model_dump(mode="json", exclude={"actual_workflow"}),
            "prompt_job": job.task_package(),
            "artifacts": [artifact.model_dump(mode="json") for artifact in artifacts],
        }
        self._atomic_json(output_dir / "manifest.json", manifest)
        self._atomic_json(output_dir / "workflow_api.json", run.actual_workflow)

    @staticmethod
    def _atomic_json(path: Path, payload: dict) -> None:
        temporary = path.with_name(path.name + ".part")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
