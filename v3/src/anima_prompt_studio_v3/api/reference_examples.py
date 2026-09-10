"""Reference library routes. Uploads accept bytes, never client filesystem paths."""
from __future__ import annotations

import asyncio
from pathlib import Path
from threading import Lock
from typing import Literal

from fastapi import Depends, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import Field, ValidationError
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.datastructures import UploadFile

from .conversation import WorkspaceCommand
from .reference_ingest import IngestRequest, IngestService
from ..core.requirements import ContractModel, PinRole, Requirements, apply_pin, dump
from ..storage.reference_examples import (
    ExampleMetadata, ExampleNotes, ExamplePatch, ExampleStore, MAX_IMAGE_BYTES, fail, now,
)


class ExampleDelete(ContractModel):
    revision: int = Field(ge=1)


class InstallBundledExamples(ContractModel):
    pass


class OfficialNotes(ContractModel):
    override_revision: int = Field(ge=0)
    notes: ExampleNotes


class OfficialCopy(ContractModel):
    source_version: str = Field(min_length=1, max_length=200)


class PinRequest(WorkspaceCommand):
    example_id: str = Field(pattern=r"^(ex_[a-f0-9]+|off_[A-Za-z0-9_]+)$")
    source_version: str = Field(min_length=1, max_length=200)
    role: PinRole


class GalleryCopy(ContractModel):
    path: str = Field(min_length=1, max_length=2000)


class RunCopy(GalleryCopy):
    run_id: str = Field(min_length=1, max_length=200)


def register_reference_routes(app, workspace_db, require_session):
    store = ExampleStore(Path(workspace_db).with_name("examples.db"))
    app.state.example_store = store
    from .reference_presets import register_preset_routes
    register_preset_routes(app, store, require_session)
    if app.state.submission_service is not None:
        app.state.submission_service.reference_get = store.get
    ingest_service = IngestService(store)
    dependencies = [Depends(require_session)]
    prefix = "/api/v3/reference-examples"
    install_lock = Lock()

    @app.post(prefix + "/install-bundled", dependencies=dependencies)
    def install_bundled(payload: InstallBundledExamples):
        from ..storage.bundled_examples import bundled_example_source

        with install_lock:
            current = store.official.current()
            if current is not None:
                return {"ready": True, "id": current[1].pack_id, "count": len(current[2])}
            try:
                return store.official.install(bundled_example_source())
            except FileNotFoundError:
                fail("bundled_examples_missing", "当前安装缺少内置样例文件，请使用完整安装包后重试。")
            except (OSError, ValueError):
                fail("bundled_examples_install_failed", "内置样例安装失败，请检查安装文件完整性与目录写入权限。")

    @app.get(prefix, dependencies=dependencies)
    def list_examples(q: str = Query(default="", max_length=200),
                      origin: Literal["upload", "session_pin", "gallery_keep", "grok_dump", "official"] | None = None,
                      limit: int = Query(default=40, ge=1, le=100),
                      cursor: str | None = Query(default=None, max_length=2000)):
        return store.list(q=q, origin=origin, limit=limit, cursor=cursor)

    @app.post(prefix, dependencies=dependencies, status_code=201)
    async def upload_example(request: Request):
        async def bounded_stream():
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_IMAGE_BYTES + 1024 * 1024:
                    # MultiPartException lets the parser close temporary files.
                    raise MultiPartException("上传请求超过允许大小。")
                yield chunk
        try:
            form = await MultiPartParser(request.headers, bounded_stream(), max_files=1, max_fields=2).parse()
        except MultiPartException:
            fail("invalid_reference_image", "上传表单无效或超过大小限制。")
        try:
            keys = [key for key, _ in form.multi_items()]
            if len(keys) != len(set(keys)) or set(keys) - {"file", "title", "metadata"}:
                fail("invalid_request", "上传字段重复或包含未知字段。")
            file, title = form.get("file"), form.get("title")
            if not isinstance(file, UploadFile) or not isinstance(title, str) or not 1 <= len(title.strip()) <= 200:
                fail("invalid_request", "必须提供图片与 1～200 字的标题。")
            try:
                metadata = ExampleMetadata.model_validate_json(form.get("metadata", "{}"))
            except (ValidationError, TypeError):
                fail("invalid_request", "参考图元数据不符合合同。")
            data = await file.read(MAX_IMAGE_BYTES + 1)
            return await asyncio.to_thread(store.create, data, title.strip(), metadata, content_type=file.content_type)
        finally:
            await form.close()

    def gallery_bytes(relative):
        gallery = app.state.gallery_service
        if gallery is None:
            fail("reference_preset_not_found", "图片目录尚未连接。")
        path = gallery.resolve_content(relative)
        if path is None:
            fail("reference_preset_not_found", "原图不存在或已移除。")
        try:
            with path.open("rb") as stream:
                data = stream.read(MAX_IMAGE_BYTES + 1)
        except OSError:
            fail("reference_preset_not_found", "原图不存在或已移除。")
        return path, data

    @app.post(prefix + "/from-gallery", dependencies=dependencies, status_code=201)
    def from_gallery(payload: GalleryCopy):
        path, data = gallery_bytes(payload.path)
        return store.create(data, path.stem[:200], ExampleMetadata(), origin="gallery_keep", origin_ref=payload.path)

    @app.post(prefix + "/from-run", dependencies=dependencies, status_code=201)
    def from_run(payload: RunCopy):
        from ..runtime import GenerationRunNotFoundError

        service = app.state.submission_service
        if service is None:
            fail("reference_preset_not_found", "生成提交记录不存在。")
        entries = service.store.for_runs([payload.run_id])
        if not entries:
            fail("reference_preset_not_found", "生成提交记录不存在。")
        path, data = gallery_bytes(payload.path)
        try:
            artifacts = service.queue.artifacts(payload.run_id)
        except GenerationRunNotFoundError:
            fail("reference_preset_not_found", "生成任务不存在。")
        if not any(Path(item.local_path).resolve() == path.resolve() for item in artifacts):
            fail("reference_preset_not_found", "该图片不属于指定生成任务。")
        provenance = entries[0]["snapshot"]["provenance"]
        # Only explicitly selected fields cross the API boundary; snapshots may contain local paths.
        verified = {key: provenance.get(key) for key in ("positive", "negative", "model_profile", "settings", "workflow_snapshot_ref")}
        verified["run_id"] = payload.run_id
        return store.create(data, path.stem[:200], ExampleMetadata(), origin="session_pin", origin_ref=payload.run_id,
            requirements=provenance.get("requirements"), provenance=verified,
            compat={"model_profiles": [provenance["model_profile"]], "workflow_snapshot_ref": payload.run_id})

    @app.get(prefix + "/{example_id}", dependencies=dependencies)
    def get_example(example_id: str):
        return store.get(example_id)

    @app.patch(prefix + "/{example_id}/notes", dependencies=dependencies)
    def official_notes(example_id: str, payload: OfficialNotes):
        return store.save_official_notes(example_id, payload.override_revision, payload.notes)

    @app.post(prefix + "/{example_id}/copy", dependencies=dependencies, status_code=201)
    def official_copy(example_id: str, payload: OfficialCopy):
        frozen = store.official.get(example_id, payload.source_version)
        source = store.get(example_id, payload.source_version)
        return store.create(frozen["media_path"].read_bytes(), source["title"],
            ExampleMetadata(notes=ExampleNotes.model_validate(source["notes"])),
            origin="upload", origin_ref=example_id, requirements=source["requirements"], compat=source["compat"])

    @app.patch(prefix + "/{example_id}", dependencies=dependencies)
    def patch_example(example_id: str, payload: ExamplePatch):
        return store.patch(example_id, payload)

    @app.delete(prefix + "/{example_id}", dependencies=dependencies, status_code=204)
    def delete_example(example_id: str, payload: ExampleDelete):
        store.delete(example_id, payload.revision)
        return Response(status_code=204)

    @app.get(prefix + "/{example_id}/content", dependencies=dependencies)
    def example_content(example_id: str):
        path, mime = store.content(example_id)
        return FileResponse(path, media_type=mime, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @app.get(prefix + "/{example_id}/thumbnail", dependencies=dependencies)
    def example_thumbnail(example_id: str, size: int = Query(default=320, ge=64, le=1024)):
        return Response(store.thumbnail(example_id, size), media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.post(prefix + "/{example_id}/ingest", dependencies=dependencies)
    async def ingest_example(example_id: str, payload: IngestRequest):
        return await ingest_service.ingest(example_id, payload)

    @app.post("/api/v3/workbench/pins", dependencies=dependencies)
    def pin_example(payload: PinRequest):
        source = store.get(payload.example_id, payload.source_version)
        if not source["requirements_valid"]:
            fail("empty_requirements", "参考图尚无可复制的要求，请先编辑或分析。")
        def operation(draft):
            draft["requirements"] = dump(apply_pin(Requirements.model_validate(draft["requirements"]) if draft.get("requirements") else Requirements.empty(),
                Requirements.model_validate(source["requirements"]), payload.role))
            draft["reference_pin"] = dict(example_id=payload.example_id, source_version=payload.source_version,
                role=payload.role, pinned_at=now(), source_snapshot={"requirements": source["requirements"], "compat": source["compat"]})
            return draft
        return app.state.workspace_store.transform(payload.workspace_id, expected_revision=payload.revision, operation=operation)

    @app.delete("/api/v3/workbench/pins", dependencies=dependencies)
    def unpin_example(payload: WorkspaceCommand):
        def operation(draft):
            draft["reference_pin"] = None
            return draft
        return app.state.workspace_store.transform(payload.workspace_id, expected_revision=payload.revision, operation=operation)
