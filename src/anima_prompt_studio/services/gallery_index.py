from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from anima_prompt_studio.repositories import SQLiteRepository
from anima_prompt_studio.services.gallery_assets import IMAGE_SUFFIXES, is_in_gallery_trash


@dataclass
class GalleryBatch:
    run_id: str
    output_dir: Path
    created_at: datetime
    project_name: str = "未命名项目"
    model_profile_id: str = ""
    positive_prompt: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    image_paths: list[Path] = field(default_factory=list)

    @property
    def title(self) -> str:
        stamp = self.created_at.astimezone().strftime("%m-%d %H:%M")
        model = self.model_profile_id.replace("anima_", "").replace("_v1", "") or "未知模型"
        return f"{stamp} · {self.project_name} · {model} · {len(self.image_paths)} 张"


def load_gallery_batches(
    repository: SQLiteRepository,
    output_root: Path,
    limit: int = 200,
) -> list[GalleryBatch]:
    """Load tracked batches, manifests, and untracked images under the configured root."""
    batches: dict[str, GalleryBatch] = {}
    for run in repository.list_generation_runs(limit=limit):
        paths = _existing_image_paths(
            Path(artifact.local_path) for artifact in repository.list_generation_artifacts(run.id)
        )
        batch = gallery_batch_from_run(run, paths)
        if batch is None:
            continue
        batches[run.id] = batch

    root = output_root.expanduser()
    if root.is_dir():
        try:
            manifests = sorted(
                (path for path in root.rglob("manifest.json") if not is_in_gallery_trash(path, root)),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )[:limit]
        except OSError:
            manifests = []
        for manifest_path in manifests:
            recovered = _batch_from_manifest(manifest_path, root)
            if recovered and recovered.run_id not in batches:
                batches[recovered.run_id] = recovered

        tracked = {
            str(path.resolve()).casefold()
            for batch in batches.values()
            for path in batch.image_paths
        }
        orphan_folders: dict[Path, list[Path]] = {}
        try:
            candidates = (path for path in root.rglob("*") if path.suffix.casefold() in IMAGE_SUFFIXES)
            for index, path in enumerate(candidates):
                if index >= 3000:
                    break
                if is_in_gallery_trash(path, root):
                    continue
                if not path.is_file() or str(path.resolve()).casefold() in tracked:
                    continue
                orphan_folders.setdefault(path.parent, []).append(path)
        except OSError:
            orphan_folders = {}
        for folder, paths in orphan_folders.items():
            try:
                relative = folder.relative_to(root)
                project = relative.parts[0] if relative.parts else "未分类"
                model = next((part for part in relative.parts if part.startswith("anima_")), "")
                created = datetime.fromtimestamp(max(path.stat().st_mtime for path in paths)).astimezone()
            except (OSError, ValueError):
                continue
            run_id = "folder:" + str(folder.resolve())
            batches[run_id] = GalleryBatch(
                run_id=run_id,
                output_dir=folder,
                created_at=created,
                project_name=project,
                model_profile_id=model,
                image_paths=_existing_image_paths(paths),
            )

    return sorted(batches.values(), key=lambda batch: batch.created_at, reverse=True)[:limit]


def gallery_batch_from_run(run, image_paths) -> GalleryBatch | None:
    """Build one gallery batch from an already-known completed run.

    This intentionally performs no output-root scan.  The generation UI can use
    it to display freshly downloaded artifacts without walking the entire image
    library on the GUI thread.
    """
    paths = _existing_image_paths(image_paths)
    if not paths:
        return None
    snapshot = run.request_json.get("prompt_job", {})
    params = snapshot.get("generation_params", {}) if isinstance(snapshot, dict) else {}
    params = dict(params) if isinstance(params, dict) else {}
    if isinstance(snapshot, dict):
        integration_metadata = snapshot.get("integration_metadata")
        if isinstance(integration_metadata, dict):
            params["integration_metadata"] = integration_metadata
        for key, aliases in (
            ("negative_prompt", ("negative_prompt",)),
            ("generation_preset_id", ("generation_preset_id", "generation_preset")),
            ("quality_profile_id", ("quality_profile_id", "quality_profile")),
            ("original_zh", ("original_zh",)),
            ("translated_en", ("translated_en",)),
        ):
            if params.get(key):
                continue
            value = next((snapshot.get(alias) for alias in aliases if snapshot.get(alias)), None)
            if value not in (None, ""):
                params[key] = value
        source = snapshot.get("source")
        if isinstance(source, dict):
            params.setdefault("original_zh", source.get("original_zh") or "")
            params.setdefault("translated_en", source.get("translated_en") or "")
    params = _with_rendered_dimensions(params, run.request_json.get("render_metadata"))
    return GalleryBatch(
        run_id=run.id,
        output_dir=Path(run.output_dir) if run.output_dir else paths[0].parent,
        created_at=run.completed_at or run.created_at,
        project_name=str(snapshot.get("project_name") or "未命名项目"),
        model_profile_id=str(snapshot.get("model_profile_id") or ""),
        positive_prompt=str(snapshot.get("positive_prompt") or ""),
        parameters=params,
        image_paths=paths,
    )


def _batch_from_manifest(manifest_path: Path, output_root: Path) -> GalleryBatch | None:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        run = payload.get("generation_run", {})
        job = payload.get("prompt_job", {})
        run_id = str(run.get("id") or manifest_path.parent)
        raw_paths = []
        for artifact in payload.get("artifacts", []):
            path = Path(str(artifact.get("local_path") or ""))
            if not path.is_absolute():
                path = manifest_path.parent / path
            raw_paths.append(path)
        paths = _existing_image_paths(raw_paths)
        if not paths:
            paths = _existing_image_paths(manifest_path.parent.iterdir())
        if not paths:
            return None
        created_at = _parse_datetime(run.get("completed_at") or run.get("created_at"), manifest_path)
        request_json = run.get("request_json", {}) if isinstance(run, dict) else {}
        parameters = _with_rendered_dimensions(
            job if isinstance(job, dict) else {},
            request_json.get("render_metadata") if isinstance(request_json, dict) else None,
        )
        try:
            relative = manifest_path.parent.relative_to(output_root)
            project_name = relative.parts[0] if relative.parts else "未命名项目"
        except ValueError:
            project_name = "未命名项目"
        return GalleryBatch(
            run_id=run_id,
            output_dir=manifest_path.parent,
            created_at=created_at,
            project_name=str(job.get("project_name") or project_name),
            model_profile_id=str(job.get("model_profile") or job.get("model_profile_id") or ""),
            positive_prompt=str(job.get("positive_prompt") or ""),
            parameters=parameters,
            image_paths=paths,
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _existing_image_paths(paths) -> list[Path]:
    unique: dict[str, Path] = {}
    for path in paths:
        candidate = Path(path)
        if candidate.suffix.casefold() not in IMAGE_SUFFIXES or not candidate.is_file():
            continue
        try:
            key = str(candidate.resolve()).casefold()
        except OSError:
            key = str(candidate).casefold()
        unique[key] = candidate
    return sorted(unique.values(), key=lambda path: path.name.casefold())


def _parse_datetime(value: Any, fallback_path: Path) -> datetime:
    if value:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone()
        except ValueError:
            pass
    return datetime.fromtimestamp(fallback_path.stat().st_mtime).astimezone()


def _with_rendered_dimensions(parameters: Any, render_metadata: Any) -> dict[str, Any]:
    result = dict(parameters) if isinstance(parameters, dict) else {}
    if not isinstance(render_metadata, dict):
        return result
    output_width = render_metadata.get("output_width")
    output_height = render_metadata.get("output_height")
    if output_width and output_height:
        result["base_width"] = render_metadata.get("base_width")
        result["base_height"] = render_metadata.get("base_height")
        result["width"] = output_width
        result["height"] = output_height
        result["scale"] = render_metadata.get("scale")
        result["workflow_kind"] = render_metadata.get("workflow_kind")
        result["operation"] = render_metadata.get("operation")
        result["source_image"] = render_metadata.get("source_image")
    return result
