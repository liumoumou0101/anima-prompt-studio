"""Reference library routes. Uploads accept bytes, never client filesystem paths."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
import re
from threading import Lock
from typing import Literal

from fastapi import Depends, Header, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import Field, ValidationError
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.datastructures import UploadFile

from .conversation import WorkspaceCommand
from .reference_ingest import IngestRequest, IngestService
from ..core.requirements import ContractModel, PinRole, Requirements, apply_pin, dump
from ..core.requirements import GallerySource, PromptEdit, WorkspaceOrigin, compile_prompt
from ..core.runtime_profiles import V3RuntimeProfiles
from ..core.seeds import display_seed
from ..core.workflow_parameters import BASE_FIELDS, build_workflow_parameter_schema, resolve_workflow_parameters
from .workspace_store import WorkspaceNotFoundError, WorkspaceVersionNotFoundError
from .models import CreationConfiguration, WorkspaceDraft, WorkbenchGenerationSettings
from ..storage.reference_examples import (
    ExampleMetadata, ExampleNotes, ExamplePatch, ExampleStore, MAX_IMAGE_BYTES, fail, now,
)


def _fresh_generation_settings(model_profile):
    """Model defaults apply only to new prompt/requirements-based workspaces."""
    defaults = V3RuntimeProfiles().profiles.get(model_profile)
    if defaults is None:
        return WorkbenchGenerationSettings()
    settings = WorkbenchGenerationSettings(
        steps=defaults.steps, cfg=defaults.cfg,
        sampler=defaults.sampler, scheduler=defaults.scheduler,
        width=defaults.default_width, height=defaults.default_height, aspect="custom",
    )
    values = {key: getattr(settings, key) for key in
              ("steps", "cfg", "sampler", "scheduler", "width", "height", "batch_size")}
    configuration = CreationConfiguration(
        modelProfile=model_profile, workflow={"id": "", "revision": ""},
        baseRecipeId=settings.preset_id, recipeValues={**values, "seed": "-1"},
        parameterOverrides={}, resourceRequirements=[], seedMode="random",
    )
    return settings.model_copy(update={"creation_configuration": configuration})


def _source_model(model):
    if model not in V3RuntimeProfiles().profiles:
        fail("model_profile_unknown", "来源未记录可用的模型，无法确定应打开哪个工作台。")
    return model


def source_generation_settings(model, explicit):
    """Use this model's defaults for missing fields and preserve recorded controls."""
    defaults = _fresh_generation_settings(model)
    values = defaults.model_dump(mode="json", exclude={"creation_configuration", "model_configurations"})
    settings = WorkbenchGenerationSettings.model_validate({**values, **explicit})
    if settings.creation_configuration or settings.parameter_schema or not defaults.creation_configuration:
        return settings
    overrides = {key: getattr(settings, key) for key in BASE_FIELDS if key in explicit and getattr(settings, key) is not None}
    overrides.update(settings.workflow_parameter_overrides)
    if "seed" in overrides:
        overrides["seed"] = str(overrides["seed"])
    config = defaults.creation_configuration.model_copy(update={
        "workflow": defaults.creation_configuration.workflow.model_copy(update={"id": settings.workflow_profile_id or ""}),
        "baseRecipeId": settings.preset_id, "parameterOverrides": overrides, "seedMode": "random" if settings.seed == -1 else "fixed"})
    return settings.model_copy(update={"creation_configuration": config, "workflow_parameter_overrides": overrides})


def _selected_image_seed(path):
    """Only explicitly recorded image metadata identifies a seed for one item in a batch."""
    from PIL import Image
    try:
        with Image.open(path) as image:
            if image.format != "PNG":
                return None
            value = image.info.get("Seed", image.info.get("seed"))
            if value is None:
                line = str(image.info.get("parameters", "")).rstrip().rsplit("\n", 1)[-1]
                match = re.search(r",\s*Seed:\s*(\d{1,19})(?=,|$)", line) if line.startswith("Steps:") else None
                value = match.group(1) if match else None
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
    if re.fullmatch(r"[0-9]{1,19}", str(value)) and int(value) < 2**63:
        return int(value)
    return None


def _frozen_generation_settings(snapshot, actual):
    """Restore accepted values against their frozen declaration, including actual Seed."""
    job = snapshot.get("job") or {}
    integration = job.get("integration_metadata") or {}
    frozen = integration.get("workflow_parameters") or {}
    schema = frozen.get("schema") or integration.get("parameter_schema")
    resolved = frozen.get("values")
    if not schema and snapshot.get("workflow"):
        from anima_prompt_studio.domain.execution_models import WorkflowProfile
        try:
            profile = WorkflowProfile.model_validate(snapshot["workflow"])
        except ValidationError:
            return {}  # Older records may identify a workflow without storing its declaration.
        schema = build_workflow_parameter_schema(profile)
    if isinstance(schema, dict) and not isinstance(resolved, dict):
        resolved = resolve_workflow_parameters(schema, integration.get("workflow_parameter_overrides") or {})["values"]
    if not isinstance(schema, dict) or not isinstance(resolved, dict):
        return {}
    values = deepcopy(resolved)
    original = snapshot.get("provenance") or {}
    for key in BASE_FIELDS.keys() & values.keys() & actual.keys():
        values[key] = str(actual[key]) if key == "seed" else actual[key]
    if "seed" in values:
        values["seed"] = str(values["seed"])
    configuration = {
        "modelProfile": job.get("model_profile_id") or original.get("model_profile"),
        "workflow": {"id": schema["workflowId"], "revision": schema["templateRevision"]},
        "baseRecipeId": (integration.get("generation_recipe") or {}).get("id") or "custom",
        "recipeValues": {field["key"]: deepcopy(field["default"]) for field in schema.get("fields", [])},
        # Resolved values freeze all accepted fields; original random overrides must not replace actual Seed.
        "parameterOverrides": deepcopy(values),
        "resourceRequirements": deepcopy(snapshot.get("resources") or []),
        "seedMode": "random" if str(values.get("seed", "-1")) == "-1" else "fixed",
    }
    return {**{key: value for key, value in values.items() if key in BASE_FIELDS},
            "parameter_schema": deepcopy(schema), "workflow_parameter_overrides": values,
            "creation_configuration": configuration}


def workspace_run_source(snapshot, image_seed=None):
    if snapshot is None:
        return None
    job = snapshot.get("job") or {}
    original = snapshot.get("provenance") or {}
    actual = {**(original.get("settings") or {}), **(job.get("generation_params") or {})}
    resolved_seed = ((snapshot.get("run") or {}).get("request_json") or {}).get("resolved_seed")
    if actual.get("seed") in (None, -1, "-1") and re.fullmatch(r"[0-9]{1,19}", str(resolved_seed)) and int(resolved_seed) < 2**63:
        actual["seed"] = int(resolved_seed)
    if image_seed is not None:
        actual.update(seed=image_seed, batch_size=1)
    settings = {key: value for key, value in actual.items() if key in BASE_FIELDS or key in {"denoise", "clip_skip"}}
    settings.update(_frozen_generation_settings(snapshot, actual))
    if re.fullmatch(r"-?[0-9]{1,19}", str(settings.get("seed"))):
        settings["seed"] = display_seed(int(settings["seed"]))
    return {"workspace_revision": snapshot.get("workspace_revision"),
            "positive_prompt": job.get("positive_prompt", original.get("positive", "")),
            "negative_prompt": job.get("negative_prompt", original.get("negative", "")),
            "model_profile": job.get("model_profile_id") or original.get("model_profile"), "settings": settings}


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
    user_notes: str = Field(default="", max_length=20_000)


class StartExample(OfficialCopy):
    mode: Literal["requirements", "generation", "prompt"]
    role: PinRole = "whole_scene"


class ContinueGeneration(ContractModel):
    pass


def register_reference_routes(app, workspace_db, require_session):
    store = ExampleStore(Path(workspace_db).with_name("examples.db"))
    app.state.example_store = store
    from .reference_sync import register_local_sync_routes
    register_local_sync_routes(app, store, workspace_db, require_session)
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
                      origin: Literal["upload", "session_pin", "gallery_keep", "grok_dump", "official", "research_import"] | None = None,
                      model: str | None = Query(default=None, max_length=200),
                      artist: str | None = Query(default=None, max_length=200),
                      lora_dependency: Literal["none", "lora", "unknown"] | None = None,
                      content: Literal["safe", "sensitive", "nsfw", "explicit", "unknown"] | None = None,
                      limit: int = Query(default=40, ge=1, le=100),
                      cursor: str | None = Query(default=None, max_length=2000)):
        return store.list(q=q, origin=origin, limit=limit, cursor=cursor,
            model=model, artist=artist, lora_dependency=lora_dependency, content=content)

    @app.get(prefix + "/facets", dependencies=dependencies)
    def reference_facets():
        return store.facets()

    @app.get(prefix + "/by-artist", dependencies=dependencies)
    def examples_by_artist(artist: str = Query(min_length=1, max_length=200), limit: int = Query(default=4, ge=1, le=12)):
        page = store.list(artist=artist, content="safe", limit=limit)
        items = []
        for item in page["items"]:
            metadata = store.catalog_metadata(item)
            items.append({"id": item["id"], "title": item["title"], "artists": metadata.get("artists", []),
                "model": metadata.get("checkpoint", ""), "content_level": metadata.get("content_level", "unknown"),
                "lora_dependency": metadata.get("lora_dependency", "unknown"),
                "thumbnail_url": f"/api/v3/gallery/reference-examples/{item['id']}/thumbnail",
                "reference_url": f"/references?example={item['id']}"})
        return {"items": items}

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
        gallery = app.state.gallery_service
        assets = gallery.list_assets(limit=1000)["items"] if hasattr(gallery, "list_assets") else []
        asset = next((item for item in assets if item["path"] == payload.path), {})
        service = app.state.submission_service
        if asset.get("batch_id") and service and service.store.for_runs([asset["batch_id"]]):
            return from_run(RunCopy(path=payload.path, run_id=asset["batch_id"]))
        positive, negative = asset.get("positive_prompt", ""), asset.get("negative_prompt", "")
        notes = ExampleNotes(external_prompt=(f"正向：{positive}\n负向：{negative}" if positive or negative else "")[:20000])
        return store.create(data, path.stem[:200], ExampleMetadata(notes=notes), origin="gallery_keep", origin_ref=payload.path,
            provenance={"positive": positive, "negative": negative, "model_profile": asset.get("model_profile", ""),
                        "settings": asset.get("generation_params", {}), "source": "gallery_metadata"})

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
        snapshot = entries[0]["snapshot"]
        provenance = snapshot.get("provenance") or {}
        # Only explicitly selected fields cross the API boundary; snapshots may contain local paths.
        selected_seed = _selected_image_seed(path)
        source = workspace_run_source(snapshot, selected_seed)
        model = source["model_profile"]
        verified = {"positive":source["positive_prompt"], "negative":source["negative_prompt"], "model_profile":model,
                    "settings":{key:value for key,value in source["settings"].items() if key in BASE_FIELDS},
                    "workflow_snapshot_ref":provenance.get("workflow_snapshot_ref"), "run_id":payload.run_id}
        if selected_seed is not None:
            verified["image_seed"] = display_seed(selected_seed)
        notes = ExampleNotes(external_prompt=f"正向：{verified.get('positive') or ''}\n负向：{verified.get('negative') or ''}"[:20000],
                             user_notes=payload.user_notes)
        return store.create(data, path.stem[:200], ExampleMetadata(notes=notes), origin="session_pin", origin_ref=payload.run_id,
            requirements=provenance.get("requirements"), provenance=verified,
            compat={"model_profiles": [model] if model else [], "workflow_snapshot_ref": payload.run_id})

    @app.get(prefix + "/{example_id}", dependencies=dependencies)
    def get_example(example_id: str):
        return store.get(example_id)

    def verified_workspace_origin(snapshot, run_id, source):
        original = snapshot.get("provenance") or {}
        workspace_id = snapshot.get("workspace_id", original.get("workspace_id"))
        revision = snapshot.get("workspace_revision", original.get("workspace_revision"))
        if (original.get("workspace_id", workspace_id) != workspace_id
                or original.get("workspace_revision", revision) != revision):
            return None
        try:
            origin = WorkspaceOrigin(workspace_id=workspace_id, revision=revision, run_id=run_id)
            parent = app.state.workspace_store.get_version(workspace_id, revision, include_archived=True)
        except (ValidationError, WorkspaceNotFoundError, WorkspaceVersionNotFoundError):
            return None
        compiled = parent["draft"].get("compiled") or {}
        if (parent["draft"].get("model_profile") != source["model_profile"]
                or compiled.get("positive") != source["positive_prompt"]
                or compiled.get("negative") != source["negative_prompt"]):
            return None
        return dump(origin)

    def create_generation_workspace(run_id, title=None, idempotency_key=None, *,
                                    gallery_source=None, request_identity=None, image_seed=None):
        service = app.state.submission_service
        entries = service.store.for_runs([run_id]) if service and run_id else []
        if not entries:
            fail("reference_preset_unavailable", "没有可用的原始生成快照。")
        snapshot = entries[0]["snapshot"]
        original, run = snapshot.get("provenance") or {}, snapshot.get("run") or {}
        if not snapshot.get("workflow") or not run.get("workflow_profile_id") or not run.get("remote_profile_id"):
            fail("workflow_snapshot_missing", "原始工作流快照缺失。")
        source = workspace_run_source(snapshot, image_seed)
        model = _source_model(source["model_profile"])
        values = {k: v for k, v in source["settings"].items() if k in WorkbenchGenerationSettings.model_fields}
        values.update(preset_id=(values.get("creation_configuration") or {}).get("baseRecipeId", "custom"),
                      aspect="custom", remote_profile_id=run["remote_profile_id"], workflow_profile_id=run["workflow_profile_id"])
        try:
            settings = WorkbenchGenerationSettings.model_validate(values)
        except ValidationError:
            fail("workflow_snapshot_missing", "原任务的参数记录不完整，无法恢复生成条件。")
        requirements = Requirements.model_validate(original["requirements"]) if original.get("requirements") else Requirements.empty()
        # Direct-prompt runs can have LoRAs without structured creative requirements.
        if "resources" in snapshot:
            requirements = Requirements.model_validate({**dump(requirements), "loras": snapshot["resources"]})
        if not source["positive_prompt"].strip():
            fail("empty_requirements", "原任务没有已记录的正向提示词。")
        prompt = PromptEdit(positive=source["positive_prompt"], negative=source["negative_prompt"])
        draft = WorkspaceDraft(model_profile=model, generation_settings=settings).persistence_payload()
        draft["requirements"] = dump(requirements)
        draft["generation_source"] = dict(run_id=run_id, remote_profile_id=run["remote_profile_id"], workflow_profile_id=run["workflow_profile_id"], model_profile=model)
        draft["workspace_origin"] = verified_workspace_origin(snapshot, run_id, source)
        if gallery_source is not None:
            draft["gallery_source"] = dump(GallerySource.model_validate(gallery_source))
        draft["compiled"] = compile_prompt(draft, prompt, source="user")
        resolved_title = title or "继续 · " + (requirements.layers.subject.text or prompt.positive)[:40]
        return app.state.workspace_store.create_snapshot(resolved_title[:200], draft,
            request_identity=request_identity if request_identity is not None else {
                "kind": "generation_run", "run_id": run_id, "title": title}, idempotency_key=idempotency_key)

    @app.post("/api/v3/gallery/assets/workspace", dependencies=dependencies, status_code=201)
    def continue_gallery(payload: GalleryCopy,
                         idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        from ..runtime import GenerationRunNotFoundError

        gallery = app.state.gallery_service
        path = gallery.resolve_content(payload.path) if gallery is not None else None
        if path is None:
            fail("reference_preset_not_found", "原图不存在或路径不在画廊目录中。")
        relative = Path(payload.path).as_posix()
        assets = gallery.list_assets(limit=1000)["items"]
        asset = next((item for item in assets if item["path"] == relative), None)
        if asset is None:
            fail("reference_preset_not_found", "画廊中没有这张图片的记录，请刷新画廊后重试。")
        source = {"path": asset["path"], "name": asset.get("name") or path.name}
        # Identity follows the requested image, including two images from one run.
        # It stays stable if legacy metadata later acquires a generation snapshot.
        identity = {"kind": "gallery_asset", "path": source["path"]}
        run_id = asset.get("batch_id")
        service = app.state.submission_service
        entries = service.store.for_runs([run_id]) if service and run_id else []
        selected_seed = _selected_image_seed(path)
        prior = None
        if entries:
            try:
                artifacts = service.queue.artifacts(run_id)
            except GenerationRunNotFoundError:
                fail("reference_preset_not_found", "原始生成任务不存在。")
            if not any(Path(item.local_path).resolve() == path.resolve() for item in artifacts):
                fail("reference_preset_not_found", "这张图片不属于记录中的生成任务。")
            snapshot = entries[0]["snapshot"]
            if snapshot.get("workflow"):
                return create_generation_workspace(run_id, idempotency_key=idempotency_key,
                    gallery_source={**source, "mode": "generation"}, request_identity=identity, image_seed=selected_seed)
            prior = workspace_run_source(snapshot, selected_seed)

        positive = prior["positive_prompt"] if prior else asset.get("positive_prompt") or ""
        negative = prior["negative_prompt"] if prior else asset.get("negative_prompt") or ""
        if not positive.strip():
            fail("empty_requirements", "这张图片没有已记录的正向提示词，无法直接转入工作台。")
        model = _source_model(prior["model_profile"] if prior else asset.get("model_profile"))
        recorded = {}
        parameters = prior["settings"] if prior else asset.get("generation_params") or {}
        for key, value in parameters.items():
            if key not in BASE_FIELDS or value is None:
                continue
            try:
                recorded[key] = getattr(WorkbenchGenerationSettings.model_validate({key:value}), key)
            except ValidationError:
                continue  # A malformed legacy field does not invalidate its other recorded values.
        if selected_seed is not None:
            recorded.update(seed=selected_seed,batch_size=1)
        settings = source_generation_settings(model, recorded)
        draft = WorkspaceDraft(model_profile=model, generation_settings=settings).persistence_payload()
        draft["requirements"] = dump(Requirements.empty())
        draft["gallery_source"] = dump(GallerySource(**source, mode="prompt"))
        draft["compiled"] = compile_prompt(draft, PromptEdit(positive=positive,negative=negative), source="user")
        return app.state.workspace_store.create_snapshot(("图片提示词 · " + source["name"])[:200], draft,
            request_identity=identity, idempotency_key=idempotency_key)

    @app.post("/api/v3/generation-runs/{run_id}/workspace", dependencies=dependencies, status_code=201)
    def continue_generation(run_id: str, payload: ContinueGeneration,
                            idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        return create_generation_workspace(run_id, idempotency_key=idempotency_key)

    @app.post(prefix + "/{example_id}/workspace", dependencies=dependencies, status_code=201)
    def start_workspace(example_id: str, payload: StartExample,
                        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        source = store.get(example_id, payload.source_version)
        if payload.mode == "generation":
            provenance = source.get("provenance") or {}
            return create_generation_workspace(provenance.get("run_id"), "参考 · " + source["title"], idempotency_key=idempotency_key,
                image_seed=provenance.get("image_seed"),request_identity={"kind":"reference_generation","example_id":example_id,"source_version":payload.source_version})
        if payload.mode == "prompt":
            original = source.get("provenance") or {}
            if not original.get("positive") or not original["positive"].strip():
                fail("empty_requirements", "此案例没有已记录的原始正向提示词。")
            model = _source_model(original.get("model_profile"))
            settings = _fresh_generation_settings(model)
            draft = WorkspaceDraft(model_profile=model, generation_settings=settings).persistence_payload()
            record = app.state.workspace_store.create(("提示词参考 · " + source["title"])[:200], draft)
            def populate_prompt(draft):
                draft["requirements"] = dump(Requirements.empty())
                draft["compiled"] = compile_prompt(draft, PromptEdit(positive=original["positive"],
                    negative=original.get("negative") or ""), source="user")
                return draft
            return app.state.workspace_store.transform(record["id"], expected_revision=record["revision"], operation=populate_prompt)
        if not source["requirements_valid"]:
            fail("empty_requirements", "请先编辑或提取参考要求。")
        requirements = apply_pin(Requirements.empty(), Requirements.model_validate(source["requirements"]), payload.role)
        model = source["compat"]["model_profiles"][0] if source["compat"]["model_profiles"] else "anima_aesthetic_v1_1"
        draft = WorkspaceDraft(model_profile=model, generation_settings=_fresh_generation_settings(model)).persistence_payload()
        record = app.state.workspace_store.create(("参考 · " + source["title"])[:200], draft)
        def populate(draft):
            draft["requirements"] = dump(requirements)
            draft["reference_pin"] = dict(example_id=example_id, source_version=payload.source_version, role=payload.role,
                pinned_at=now(), source_snapshot={"requirements": source["requirements"], "compat": source["compat"]})
            return draft
        return app.state.workspace_store.transform(record["id"], expected_revision=record["revision"], operation=populate)

    @app.delete("/api/v3/workbench/generation-source", dependencies=dependencies)
    def detach_generation_source(payload: WorkspaceCommand):
        def operation(draft):
            draft["generation_source"] = None
            return draft
        return app.state.workspace_store.transform(payload.workspace_id, expected_revision=payload.revision, operation=operation)

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

    # Browser image requests use the existing gallery-scoped HttpOnly session cookie.
    @app.get("/api/v3/gallery/reference-examples/{example_id}/content", dependencies=dependencies)
    @app.get(prefix + "/{example_id}/content", dependencies=dependencies)
    def example_content(example_id: str):
        path, mime = store.content(example_id)
        return FileResponse(path, media_type=mime, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @app.get("/api/v3/gallery/reference-examples/{example_id}/thumbnail", dependencies=dependencies)
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
