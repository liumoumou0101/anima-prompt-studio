"""Session-protected artist preset library, including portable local sample backup."""
from __future__ import annotations

import asyncio
from hashlib import sha256
import json
from pathlib import Path

from fastapi import Depends, Query, Request, Response
from pydantic import Field, ValidationError
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from ..core.requirements import WorkbenchError
from ..storage.artist_presets import (
    ArtistPresetStore, MAX_BUNDLE_BYTES, PREFIX, Payload, PresetConflict,
    PresetNotFound, PresetWrite, SampleMetadata,
)
from ..storage.reference_examples import MAX_IMAGE_BYTES


# Exact contiguous excerpts verified against original full prompts. Normalized
# artist search metadata loses weights/disambiguators and must not create presets.
CURATED_REFERENCES = {
    "ex_fc7df32675a913b8907f36a4c570cb66": {
        "name": "Poco × Aoi Tori · 双画师",
        "positive": r"@poco \(asahi age\), @aoi tori", "source_url": "https://civitai.com/images/139696184"},
    "ex_9ccae91daf0d7551042360b5f729e1e3": {
        "name": "Koi × Neoki Ohae · 双画师",
        "positive": r"@koi \(koisan\), @neoki ohae", "source_url": "https://civitai.com/images/139693572"},
    "ex_29038b14f266637bfd5bb361b2cdcfcb": {
        "name": "Junbuug × Bbybluemochi × Sainttufa × Neytirix",
        "positive": "@junbuug  @bbybluemochi @sainttufa @neytirix", "source_url": "https://civitai.com/images/127126595"},
    "ex_cb6e216fee35e856d17825e0e37b2b41": {
        "name": "Karasu Raven × Kaamin · 原文交替语法",
        "positive": r"[@karasu raven | realistic | @kaamin \(mariarose753\)]", "source_url": "https://civitai.com/images/127584865",
        "special": True},
    "ex_2e9566766851ea247afeb767292c8749": {
        "name": "Quasarcake × Sumiyao 等 · 五画师权重串",
        "positive": r"(@quasarcake:1.1), (@sumiyao \(amam\):0.5):, (poruserin:0.5), (@senapops:0.5), (@kanzarin:1.1)",
        "source_url": "https://civitai.com/images/130798367", "special": True},
}


class PresetUpdate(PresetWrite):
    expected_revision: int = Field(ge=1)


class SampleUpload(SampleMetadata):
    expected_revision: int = Field(ge=1)


class ReferenceCopy(Payload):
    reference_id: str = Field(max_length=100)


class ImportPreview(Payload):
    document: dict


class ImportCommit(ImportPreview):
    token: str = Field(pattern=r"^[a-f0-9]{64}$")


def reference_candidate(reference_store, reference_id):
    """Return a defensible candidate or fail if its source no longer matches."""
    candidate = CURATED_REFERENCES.get(reference_id)
    if not candidate:
        raise PresetNotFound("此参考图不在已核对的画师串候选中。")
    record = reference_store.get(reference_id)
    provenance = record.get("provenance") or {}
    metadata = provenance.get("reference_metadata") or {}
    model = metadata.get("checkpoint") or ""
    source = metadata.get("source_url") or (record.get("notes") or {}).get("source_url") or ""
    if (candidate["positive"] not in (provenance.get("positive") or "")
            or metadata.get("content_level") != "safe" or source != candidate["source_url"]
            or not model.lower().startswith("anima")):
        raise PresetConflict("参考图提示词、模型或来源已改变，不能直接收藏为原候选。")
    # Presence matters: suggestions should never promise an unavailable sample.
    reference_store.content(reference_id)
    notes = "来源声明适用此模型；样品由原完整提示词生成，尚未在本机复现。种子、工作流及 LoRA 依赖未完整提供。"
    if candidate.get("special"):
        notes += "原文含特殊语法，已逐字保留，解析行为未验证。"
    return {"reference_id": reference_id, "name": candidate["name"], "positive": candidate["positive"],
        "model_label": model, "source_url": source, "notes": notes,
        "thumbnail_url": f"/api/v3/gallery/reference-examples/{reference_id}/thumbnail"}, provenance


def copy_reference(store, reference_store, reference_id):
    candidate, provenance = reference_candidate(reference_store, reference_id)
    path, _ = reference_store.content(reference_id)
    with path.open("rb") as stream:
        data = stream.read(MAX_IMAGE_BYTES + 1)
    declared_hash = provenance.get("source_image_sha256")
    if declared_hash and sha256(data).hexdigest() != declared_hash:
        raise PresetConflict("参考样品文件与保存的来源哈希不同，请重新核对。")
    value = PresetWrite(name=candidate["name"], positive=candidate["positive"], model_family="anima",
        model_label=candidate["model_label"], syntax="comfy", source_url=candidate["source_url"], notes=candidate["notes"])
    unknown = list(dict.fromkeys([*(provenance.get("unknown_fields") or []), "lora_dependencies"]))
    parameters = {**(provenance.get("settings") or {}), "checkpoint": candidate["model_label"],
        "unknown_fields": unknown, "reproducibility": provenance.get("reproducibility") or "partial",
        "validation": "source_declared"}
    sample = SampleMetadata(caption="原完整提示词生成样品；画师片段不代表独立复现配方。",
        model_label=candidate["model_label"], source_url=candidate["source_url"],
        full_positive=provenance.get("positive") or "", full_negative=provenance.get("negative") or "", parameters=parameters)
    return store.create_from_reference(value, reference_id, data, sample)


def register_artist_preset_routes(app, workspace_db, require_session):
    from .app import ApiError

    store = ArtistPresetStore(Path(workspace_db).with_name("personal-tags.db"))
    app.state.artist_preset_store = store
    dependencies = [Depends(require_session)]

    def perform(action, preset_id=None):
        try:
            return action()
        except PresetNotFound as exc:
            raise ApiError(404, "artist_preset_not_found", str(exc)) from exc
        except PresetConflict as exc:
            details = {}
            if preset_id:
                try:
                    current = store.get(preset_id)
                    details = {"current": current, "current_revision": current["revision"]}
                except PresetNotFound:
                    pass
            raise ApiError(409, "revision_conflict", str(exc), details=details) from exc
        except WorkbenchError as exc:
            status = 404 if exc.code == "reference_preset_not_found" else 422
            raise ApiError(status, exc.code, str(exc)) from exc
        except (ValueError, TypeError, ValidationError) as exc:
            raise ApiError(422, "invalid_request", str(exc)) from exc
        except OSError as exc:
            raise ApiError(422, "reference_image_unavailable", "参考图片无法读取，请刷新后重试。") from exc

    async def import_payload(request, model):
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_BUNDLE_BYTES:
                raise ApiError(413, "import_too_large", "导入文件不能超过 50 MiB。")
            body.extend(chunk)
        try:
            return model.model_validate_json(body)
        except (ValueError, TypeError, ValidationError) as exc:
            raise ApiError(422, "invalid_request", "导入请求 JSON 格式无效。") from exc

    @app.get(PREFIX, dependencies=dependencies)
    def list_presets(q: str = Query(default="", max_length=200), model: str = Query(default="", max_length=200), favorite: bool = False):
        query = q.casefold()
        return {"items": [item for item in store.list() if (not favorite or item["favorite"])
            and (not model or model in {item["model_family"], item["model_label"]})
            and (not query or query in " ".join(str(item[key]) for key in (
                "name", "positive", "negative", "model_label", "notes", "source_author")).casefold())]}

    @app.post(PREFIX, dependencies=dependencies, status_code=201)
    def create_preset(payload: PresetWrite):
        return perform(lambda: store.create(payload))

    @app.get(PREFIX + "/suggestions", dependencies=dependencies)
    def suggestions():
        items = []
        for reference_id in CURATED_REFERENCES:
            try:
                item, _ = reference_candidate(app.state.example_store, reference_id)
                items.append(item)
            except (WorkbenchError, ValueError, OSError):
                continue
        return {"items": items}

    @app.post(PREFIX + "/from-reference", dependencies=dependencies, status_code=201)
    def from_reference(payload: ReferenceCopy):
        return perform(lambda: copy_reference(store, app.state.example_store, payload.reference_id))

    @app.get(PREFIX + "/export", dependencies=dependencies)
    def export_presets(preset_id: str | None = Query(default=None, max_length=100)):
        return perform(lambda: store.export(preset_id))

    @app.post(PREFIX + "/import-preview", dependencies=dependencies)
    async def import_preview(request: Request):
        payload = await import_payload(request, ImportPreview)
        return await asyncio.to_thread(perform, lambda: store.preview_import(payload.document))

    @app.post(PREFIX + "/import", dependencies=dependencies)
    async def import_commit(request: Request):
        payload = await import_payload(request, ImportCommit)
        return await asyncio.to_thread(perform, lambda: store.import_document(payload.document, payload.token))

    @app.get(PREFIX + "/{preset_id}", dependencies=dependencies)
    def get_preset(preset_id: str):
        return perform(lambda: store.get(preset_id))

    @app.put(PREFIX + "/{preset_id}", dependencies=dependencies)
    def update_preset(preset_id: str, payload: PresetUpdate):
        value = PresetWrite.model_validate(payload.model_dump(exclude={"expected_revision"}))
        return perform(lambda: store.update(preset_id, payload.expected_revision, value), preset_id)

    @app.delete(PREFIX + "/{preset_id}", dependencies=dependencies, status_code=204)
    def delete_preset(preset_id: str, expected_revision: int = Query(ge=1)):
        perform(lambda: store.delete(preset_id, expected_revision), preset_id)
        return Response(status_code=204)

    @app.post(PREFIX + "/{preset_id}/samples", dependencies=dependencies)
    async def upload_sample(preset_id: str, request: Request):
        async def bounded_stream():
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_IMAGE_BYTES + 1024 * 1024:
                    raise MultiPartException("样品上传超过大小限制。")
                yield chunk
        try:
            form = await MultiPartParser(request.headers, bounded_stream(), max_files=1, max_fields=1).parse()
        except MultiPartException as exc:
            raise ApiError(422, "invalid_request", "上传表单无效或超过大小限制。") from exc
        try:
            keys = [key for key, _ in form.multi_items()]
            if len(keys) != len(set(keys)) or set(keys) != {"file", "metadata"}:
                raise ApiError(422, "invalid_request", "上传必须提供 file 和 metadata，且不能包含重复或未知字段。")
            file = form.get("file")
            if not isinstance(file, UploadFile):
                raise ApiError(422, "invalid_request", "请选择样品图片。")
            try:
                payload = SampleUpload.model_validate_json(form["metadata"])
                metadata = SampleMetadata.model_validate(payload.model_dump(exclude={"expected_revision"}))
            except (ValueError, TypeError, ValidationError) as exc:
                raise ApiError(422, "invalid_request", "样品元数据无效。") from exc
            data = await file.read(MAX_IMAGE_BYTES + 1)
            return await asyncio.to_thread(perform, lambda: store.add_sample(preset_id, payload.expected_revision,
                data, metadata, content_type=file.content_type), preset_id)
        finally:
            await form.close()

    @app.delete(PREFIX + "/{preset_id}/samples/{sample_id}", dependencies=dependencies)
    def delete_sample(preset_id: str, sample_id: str, expected_revision: int = Query(ge=1)):
        return perform(lambda: store.delete_sample(preset_id, sample_id, expected_revision), preset_id)

    @app.get(PREFIX + "/{preset_id}/samples/{sample_id}/content", dependencies=dependencies)
    @app.get("/api/v3/gallery/artist-presets/{preset_id}/samples/{sample_id}/content", dependencies=dependencies)
    def sample_content(preset_id: str, sample_id: str):
        data, mime = perform(lambda: store.sample_content(preset_id, sample_id))
        return Response(data, media_type=mime, headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})
