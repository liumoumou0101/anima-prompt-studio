from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, Query, Request, Response as FastAPIResponse
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import __version__
try:
    from ..adapters.v2 import (
        BRIDGE_SCHEMA,
        CandidateToV2PromptJobAdapter,
        GenerationQueueError,
        GenerationQueueFullError,
        GenerationRunActionError,
        GenerationRunNotFoundError,
        GalleryUpscaleError,
        IntentParseError,
        IntentParserUnavailableError,
        V2GenerationSettings,
    )
except ModuleNotFoundError as exc:
    if exc.name != "anima_prompt_studio" and not (exc.name or "").startswith("anima_prompt_studio."):
        raise
    BRIDGE_SCHEMA = "v3-v2-generation-bridge/1"
    CandidateToV2PromptJobAdapter = None  # type: ignore[assignment,misc]
    V2GenerationSettings = None  # type: ignore[assignment,misc]
    GenerationQueueError = RuntimeError  # type: ignore[assignment,misc]
    GenerationQueueFullError = RuntimeError  # type: ignore[assignment,misc]
    GenerationRunActionError = RuntimeError  # type: ignore[assignment,misc]
    GenerationRunNotFoundError = KeyError  # type: ignore[assignment,misc]
    IntentParseError = RuntimeError  # type: ignore[assignment,misc]
    IntentParserUnavailableError = RuntimeError  # type: ignore[assignment,misc]
    GalleryUpscaleError = RuntimeError  # type: ignore[assignment,misc]
from ..core import (
    CandidateValidationError,
    CandidateValidator,
    HybridLaneGenerator,
    LiteralCandidateGenerator,
    LiteralGenerationError,
    ModelProfileRegistry,
    RecommendationLaneGenerator,
)
from ..data import DataContractError, ReferenceDataStore
from ..domain import (
    ConstraintEdge,
    ConstraintGraph,
    ConstraintKind,
    ElementProvenance,
    IntentDocument,
    IntentElement,
    ProvenanceKind,
)
from .models import (
    ArtistRecommendRequest,
    GenerationBridgePreviewRequest,
    GalleryPathsRequest,
    GalleryProcessActionRequest,
    GalleryProcessRequest,
    GalleryStateRequest,
    GenerationRunActionRequest,
    GenerationSubmitRequest,
    IntentCandidateRequest,
    IntentParseRequest,
    PrivateKeyPassphraseRequest,
    RelatedTagsRequest,
    SessionExchangeRequest,
    TranslationRequest,
    WorkbenchCandidateRequest,
    WorkspaceCreateRequest,
    WorkspaceDeleteRequest,
    WorkspaceUpdateRequest,
)
from .security import SessionInvalidError, SessionManager
from .workspace_store import WorkspaceNotFoundError, WorkspaceRevisionConflictError, WorkspaceStore


API_PREFIX = "/api/v3"
MAX_JSON_BODY = 1024 * 1024
TAG_CATEGORIES = {"general", "artist", "copyright", "character", "meta"}
LOGGER = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        details: dict[str, object] | None = None,
        retryable: bool = False,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}
        self.retryable = retryable
        super().__init__(message)


@dataclass(frozen=True)
class ApiRuntime:
    app: FastAPI
    bootstrap_token: str


def create_api_runtime(
    reference_db: Path,
    *,
    frontend_dist: Path | None = None,
    workspace_db: Path | None = None,
    generation_queue: object | None = None,
    intent_parser: object | None = None,
    gallery_service: object | None = None,
    translation_service: object | None = None,
    app_version: str | None = None,
    allowed_hosts: set[str] | None = None,
    bootstrap_ttl: int = 120,
    session_ttl: int = 3600,
) -> ApiRuntime:
    reference_db = reference_db.resolve()
    frontend_dist = frontend_dist.resolve() if frontend_dist is not None else None
    workspace_db = workspace_db.resolve() if workspace_db is not None else None
    hosts = {item.lower() for item in (allowed_hosts or {"127.0.0.1", "localhost", "::1"})}
    sessions = SessionManager(bootstrap_ttl=bootstrap_ttl, session_ttl=session_ttl)
    bootstrap_token = sessions.issue_bootstrap_token()
    app = FastAPI(title="ANIMA Prompt Studio V3", version="v3", docs_url=None, redoc_url=None)
    app.state.reference_db = reference_db
    app.state.frontend_dist = frontend_dist
    app.state.sessions = sessions
    app.state.workspace_store = WorkspaceStore(workspace_db) if workspace_db is not None else None
    app.state.generation_queue = generation_queue
    app.state.intent_parser = intent_parser
    app.state.gallery_service = gallery_service
    app.state.translation_service = translation_service
    profiles = ModelProfileRegistry.built_in()
    generation_bridge = CandidateToV2PromptJobAdapter() if CandidateToV2PromptJobAdapter is not None else None

    @app.middleware("http")
    async def local_request_guard(request: Request, call_next):
        request.state.request_id = f"req_{uuid4().hex}"
        hostname = _hostname(request.headers.get("host", ""))
        if hostname not in hosts:
            return _error_response(request, 400, "invalid_request", "Host 不在本地服务允许列表中。")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith(API_PREFIX):
            content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                return _error_response(request, 415, "invalid_request", "写请求必须使用 application/json。")
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    parsed_length = int(content_length)
                    if parsed_length < 0:
                        return _error_response(request, 400, "invalid_request", "Content-Length 无效。")
                    if parsed_length > MAX_JSON_BODY:
                        return _error_response(request, 413, "invalid_request", "请求体超过允许大小。")
                except ValueError:
                    return _error_response(request, 400, "invalid_request", "Content-Length 无效。")
            origin = request.headers.get("origin")
            if not origin or not _allowed_loopback_origin(origin, hosts):
                return _error_response(request, 403, "invalid_request", "写请求 Origin 无效。")
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return _error_response(
            request,
            exc.status_code,
            exc.code,
            exc.message,
            details=exc.details,
            retryable=exc.retryable,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"location": list(item["loc"]), "message": item["msg"], "type": item["type"]}
            for item in exc.errors()
        ]
        return _error_response(
            request,
            422,
            "invalid_request",
            "请求参数校验失败。",
            details={"errors": errors},
        )

    @app.exception_handler(Exception)
    async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
        LOGGER.exception(
            "Unhandled API error request_id=%s path=%s",
            getattr(request.state, "request_id", "unknown"),
            request.url.path,
            exc_info=exc,
        )
        return _error_response(request, 500, "internal_error", "服务内部错误。", retryable=False)

    def require_session(
        request: Request,
        x_anima_session: str | None = Header(default=None),
    ) -> None:
        token = x_anima_session or request.cookies.get("anima_v3_gallery_session")
        if not token or not sessions.validate(token):
            raise ApiError(401, "session_invalid", "会话无效或已过期。")

    def require_reference_db() -> Path:
        if not reference_db.is_file():
            raise ApiError(503, "data_pack_missing", "参考数据包尚未安装。", retryable=True)
        try:
            with ReferenceDataStore(reference_db):
                pass
        except DataContractError as exc:
            raise ApiError(503, "data_pack_incompatible", "参考数据包不兼容。") from exc
        return reference_db

    def require_workspace_store() -> WorkspaceStore:
        store = app.state.workspace_store
        if store is None:
            raise ApiError(503, "workspace_store_missing", "工作台状态库尚未配置。", retryable=True)
        return store

    def candidate_response(
        intent: IntentDocument,
        model_profile: str,
        database: Path,
    ) -> dict[str, object]:
        try:
            profile = profiles.get(model_profile)
        except KeyError as exc:
            raise ApiError(
                422,
                "model_profile_unknown",
                f"未知模型配置：{model_profile}",
                details={"available": [item.id for item in profiles.all()]},
            ) from exc

        try:
            with ReferenceDataStore(database) as store:
                bundle = LiteralCandidateGenerator(store).generate(intent, profile)
                recommendations = RecommendationLaneGenerator(store)
                bundle = recommendations.add_conservative(bundle, profile)
                bundle = recommendations.add_artist(bundle, profile)
                bundle = HybridLaneGenerator(store).add_hybrid(bundle, profile)
                validation = CandidateValidator(store).validate_or_raise(bundle, profile)
                return {
                    "intent": bundle.intent.model_dump(mode="json"),
                    "candidates": [item.model_dump(mode="json") for item in bundle.candidates],
                    "validation": validation.model_dump(mode="json"),
                    "data_pack_id": store.pack_id,
                }
        except LiteralGenerationError as exc:
            code = "constraint_conflict" if "冲突" in str(exc) else "candidate_generation_failed"
            status_code = 409 if code == "constraint_conflict" else 422
            raise ApiError(status_code, code, str(exc)) from exc
        except CandidateValidationError as exc:
            raise ApiError(
                500,
                "candidate_validation_failed",
                "候选未通过内部安全校验。",
                details={"validation": exc.report.model_dump(mode="json")},
            ) from exc

    @app.get("/health")
    def health() -> dict[str, object]:
        return {"status": "ok", "api_version": "v3", "data_pack_ready": reference_db.is_file()}

    @app.post(f"{API_PREFIX}/session/exchange")
    def exchange_session(
        payload: SessionExchangeRequest,
        response: FastAPIResponse,
    ) -> dict[str, object]:
        try:
            exchange = sessions.exchange(payload.bootstrap_token)
        except SessionInvalidError as exc:
            raise ApiError(401, "session_invalid", "Bootstrap token 无效、已使用或已过期。") from exc
        response.set_cookie(
            "anima_v3_gallery_session",
            exchange.token,
            max_age=exchange.expires_in,
            httponly=True,
            samesite="strict",
            secure=False,
            path=f"{API_PREFIX}/gallery/",
        )
        return {"session_token": exchange.token, "expires_in": exchange.expires_in}

    @app.get(f"{API_PREFIX}/bootstrap", dependencies=[Depends(require_session)])
    def bootstrap() -> dict[str, object]:
        data_pack = _data_pack_summary(reference_db)
        ready = bool(data_pack["ready"])
        return {
            "app_version": app_version or __version__,
            "api_version": "v3",
            "data_pack": data_pack,
            "features": {
                "semantic_search": False,
                "cooccurrence": ready,
                "artist_recommendation": ready,
                "workspace_persistence": app.state.workspace_store is not None,
                "online_preview": False,
                "remote_generation": app.state.generation_queue is not None,
                "v2_generation_bridge": generation_bridge is not None,
                "natural_language_parse": bool(
                    app.state.intent_parser is not None
                    and getattr(app.state.intent_parser, "available", False)
                ),
                "local_translation": app.state.translation_service is not None,
                "gallery": app.state.gallery_service is not None,
            },
            "model_profiles": ["anima_base_v1", "anima_aesthetic_v1", "anima_turbo_v1"],
            "settings_summary": {},
        }

    @app.get(f"{API_PREFIX}/tags/search", dependencies=[Depends(require_session)])
    def search_tags(
        q: str = Query(min_length=1, max_length=200),
        category: list[str] = Query(default=[]),
        nsfw: bool | None = None,
        sort: str = Query(default="relevance", pattern=r"^(relevance|popularity)$"),
        limit: int = Query(default=50, ge=1, le=100),
        database: Path = Depends(require_reference_db),
    ) -> dict[str, object]:
        invalid_categories = set(category) - TAG_CATEGORIES
        if invalid_categories:
            raise ApiError(422, "invalid_request", f"未知标签分类：{sorted(invalid_categories)}")
        with ReferenceDataStore(database) as store:
            rows = store.search(q, categories=set(category) or None, limit=min(limit * 4, 400))
            if nsfw is not None:
                rows = [row for row in rows if row["nsfw"] is nsfw]
            if sort == "popularity":
                rows.sort(key=lambda row: row["post_count"], reverse=True)
            items = [_tag_search_item(row) for row in rows[:limit]]
            return {"items": items, "next_cursor": None, "data_pack_id": store.pack_id}

    @app.get(f"{API_PREFIX}/tags/{{canonical_name:path}}", dependencies=[Depends(require_session)])
    def tag_detail(
        canonical_name: str,
        database: Path = Depends(require_reference_db),
    ) -> dict[str, object]:
        with ReferenceDataStore(database) as store:
            detail = store.get_tag(canonical_name)
            if detail is None:
                raise ApiError(404, "tag_not_found", "标签不存在。", details={"name": canonical_name})
            payload = {key: value for key, value in detail.items() if key != "render_name"}
            return {
                **payload,
                "display_name": detail["render_name"],
                "related": store.related_tags([detail["name"]], limit=12),
                "preview": {"available": False, "online": False},
                "data_pack_id": store.pack_id,
            }

    @app.post(f"{API_PREFIX}/related-tags", dependencies=[Depends(require_session)])
    def related_tags(
        payload: RelatedTagsRequest,
        database: Path = Depends(require_reference_db),
    ) -> dict[str, object]:
        invalid_categories = set(payload.categories) - TAG_CATEGORIES
        if invalid_categories:
            raise ApiError(422, "invalid_request", f"未知标签分类：{sorted(invalid_categories)}")
        with ReferenceDataStore(database) as store:
            items = store.related_tags(
                payload.tags,
                excluded=set(payload.excluded),
                categories=set(payload.categories) or None,
                limit=payload.limit,
            )
            return {"items": items, "data_pack_id": store.pack_id}

    @app.post(f"{API_PREFIX}/artists/recommend", dependencies=[Depends(require_session)])
    def recommend_artists(
        payload: ArtistRecommendRequest,
        database: Path = Depends(require_reference_db),
    ) -> dict[str, object]:
        with ReferenceDataStore(database) as store:
            return {
                "items": store.recommend_artists(payload.tags, limit=payload.limit),
                "data_pack_id": store.pack_id,
            }

    @app.post(f"{API_PREFIX}/workbench/candidates", dependencies=[Depends(require_session)])
    def generate_workbench_candidates(
        payload: WorkbenchCandidateRequest,
        database: Path = Depends(require_reference_db),
    ) -> dict[str, object]:
        try:
            intent = _workbench_intent(payload)
        except ValueError as exc:
            raise ApiError(422, "invalid_workbench_intent", str(exc)) from exc
        return candidate_response(intent, payload.model_profile, database)

    @app.post(f"{API_PREFIX}/intent/parse", dependencies=[Depends(require_session)])
    def parse_intent(payload: IntentParseRequest) -> dict[str, object]:
        parser = app.state.intent_parser
        if parser is None or not getattr(parser, "available", False):
            raise ApiError(
                503,
                "intent_parser_unavailable",
                "V2 自然语言抽取器尚未配置可用的 AI API Key。",
            )
        try:
            result = parser.parse(payload.source_text, source_language=payload.source_language)
        except IntentParserUnavailableError as exc:
            raise ApiError(503, "intent_parser_unavailable", str(exc)) from exc
        except IntentParseError as exc:
            raise ApiError(502, "intent_parse_failed", str(exc), retryable=True) from exc
        except ValueError as exc:
            raise ApiError(422, "intent_no_visual_facts", str(exc)) from exc
        extraction = result.extraction
        return {
            "intent": result.intent.model_dump(mode="json"),
            "extraction": {
                "summary_zh": extraction.summary_zh,
                "people_count": extraction.people_count,
                "subject_mode": extraction.subject_mode,
                "content_rating": extraction.content_rating,
                "scene_type": extraction.scene_type,
                "truncated_source": extraction.truncated_source,
            },
            "parser": {"name": result.parser_name, "source": "v2_ai_extract"},
        }

    @app.post(f"{API_PREFIX}/translation", dependencies=[Depends(require_session)])
    def translate_locally(payload: TranslationRequest) -> dict[str, object]:
        translator = app.state.translation_service
        if translator is None:
            raise ApiError(503, "translation_unavailable", "本地翻译服务未安装。")
        try:
            result = translator.translate(payload.source_text, direction=payload.direction)
        except (RuntimeError, ValueError) as exc:
            raise ApiError(422, "translation_failed", str(exc)) from exc
        return {
            "translated_text": result.translated_text,
            "direction": result.direction,
            "engine": result.engine_name,
            "local_only": True,
            "model_ready": bool(getattr(translator, "model_ready", False)),
        }

    @app.post(f"{API_PREFIX}/prompt-candidates", dependencies=[Depends(require_session)])
    def generate_intent_candidates(
        payload: IntentCandidateRequest,
        database: Path = Depends(require_reference_db),
    ) -> dict[str, object]:
        """Generate V3 candidates from a reviewed IntentDocument."""
        return candidate_response(payload.intent, payload.model_profile, database)

    @app.get(f"{API_PREFIX}/workspaces", dependencies=[Depends(require_session)])
    def list_workspaces(
        limit: int = Query(default=50, ge=1, le=100),
        store: WorkspaceStore = Depends(require_workspace_store),
    ) -> dict[str, object]:
        return {"items": store.list(limit=limit)}

    @app.post(f"{API_PREFIX}/generation-requests/preview", dependencies=[Depends(require_session)])
    def preview_generation_request(payload: GenerationBridgePreviewRequest) -> dict[str, object]:
        if generation_bridge is None or V2GenerationSettings is None:
            raise ApiError(
                503,
                "v2_runtime_missing",
                "当前安装不包含 V2 兼容运行时，无法准备远程生成请求。",
            )
        try:
            prepared = generation_bridge.prepare(
                payload.candidate,
                payload.intent,
                project_name=payload.project_name,
                settings=V2GenerationSettings(**payload.settings.model_dump()),
                workspace_id=payload.workspace_id,
                workspace_revision=payload.workspace_revision,
            )
        except ValueError as exc:
            raise ApiError(422, "generation_bridge_incompatible", str(exc)) from exc
        job = prepared.job
        return {
            "compatible": True,
            "bridge_schema": BRIDGE_SCHEMA,
            "prompt_job": {
                "id": job.id,
                "project_name": job.project_name,
                "model_profile_id": job.model_profile_id,
                "workflow_template_id": job.workflow_template_id,
                "positive_prompt": job.positive_prompt,
                "negative_prompt": job.negative_prompt,
                "generation_params": job.generation_params.model_dump(mode="json"),
                "locked_tags": job.locked_tags,
                "excluded_tags": job.excluded_tags,
                "artists": job.artist_selection,
            },
            "checkpoint_logical_name": prepared.checkpoint_logical_name,
            "candidate_snapshot": {
                "id": payload.candidate.id,
                "lane": payload.candidate.lane.value,
                "versions": payload.candidate.versions.model_dump(mode="json"),
            },
        }

    @app.post(
        f"{API_PREFIX}/generation-runs",
        dependencies=[Depends(require_session)],
        status_code=202,
    )
    def submit_generation_run(
        payload: GenerationSubmitRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, object]:
        queue = app.state.generation_queue
        if queue is None:
            raise ApiError(503, "remote_not_configured", "远程生成队列尚未配置。")
        if generation_bridge is None or V2GenerationSettings is None:
            raise ApiError(503, "v2_runtime_missing", "当前安装不包含 V2 兼容运行时。")
        if not idempotency_key or not idempotency_key.strip():
            raise ApiError(422, "invalid_request", "生成任务必须提供 Idempotency-Key。")
        try:
            prepared = generation_bridge.prepare(
                payload.candidate,
                payload.intent,
                project_name=payload.project_name,
                settings=V2GenerationSettings(**payload.settings.model_dump()),
                workspace_id=payload.workspace_id,
                workspace_revision=payload.workspace_revision,
            )
            run = queue.submit(
                prepared,
                remote_profile_id=payload.remote_profile_id,
                workflow_profile_id=payload.workflow_profile_id,
                idempotency_key=idempotency_key,
            )
        except GenerationQueueFullError as exc:
            raise ApiError(429, "rate_limited", str(exc), retryable=True) from exc
        except KeyError as exc:
            raise ApiError(422, "remote_not_configured", str(exc)) from exc
        except (ValueError, GenerationQueueError) as exc:
            raise ApiError(422, "workflow_incompatible", str(exc)) from exc
        return _generation_run_response(run, queue)

    @app.get(f"{API_PREFIX}/generation-runs/{{run_id}}", dependencies=[Depends(require_session)])
    def get_generation_run(run_id: str) -> dict[str, object]:
        queue = app.state.generation_queue
        if queue is None:
            raise ApiError(503, "remote_not_configured", "远程生成队列尚未配置。")
        try:
            return _generation_run_response(queue.get(run_id), queue)
        except GenerationRunNotFoundError as exc:
            raise ApiError(404, "generation_run_not_found", "生成任务不存在。") from exc

    @app.get(f"{API_PREFIX}/generation-runs", dependencies=[Depends(require_session)])
    def list_generation_runs(limit: int = Query(default=50, ge=1, le=100)) -> dict[str, object]:
        queue = app.state.generation_queue
        if queue is None:
            raise ApiError(503, "remote_not_configured", "远程生成队列尚未配置。")
        return {"items": [_generation_run_response(run, queue) for run in queue.list(limit=limit)]}

    @app.get(f"{API_PREFIX}/generation-targets", dependencies=[Depends(require_session)])
    def list_generation_targets() -> dict[str, object]:
        queue = app.state.generation_queue
        if queue is None:
            raise ApiError(503, "remote_not_configured", "远程生成队列尚未配置。")
        return {"items": queue.targets()}

    @app.post(
        f"{API_PREFIX}/generation-credentials/private-key-passphrase",
        dependencies=[Depends(require_session)],
    )
    def set_private_key_passphrase(payload: PrivateKeyPassphraseRequest) -> dict[str, object]:
        queue = app.state.generation_queue
        if queue is None:
            raise ApiError(503, "remote_not_configured", "远程生成队列尚未配置。")
        try:
            profiles = [
                item for item in queue.targets()
                if item.get("remote_profile_id") == payload.remote_profile_id
            ]
            if not profiles:
                raise ValueError("云主机配置不存在或没有可用工作流。")
            if any(item.get("auth_type") != "private_key" for item in profiles):
                raise ValueError("所选云主机未使用私钥认证。")
            queue.set_private_key_passphrase(
                payload.remote_profile_id,
                payload.passphrase.get_secret_value(),
            )
        except (ValueError, GenerationQueueError) as exc:
            raise ApiError(422, "credential_input_failed", str(exc)) from exc
        return {"configured": bool(payload.passphrase.get_secret_value())}

    @app.post(
        f"{API_PREFIX}/generation-runs/{{run_id}}/actions",
        dependencies=[Depends(require_session)],
    )
    def generation_run_action(run_id: str, payload: GenerationRunActionRequest) -> dict[str, object]:
        queue = app.state.generation_queue
        if queue is None:
            raise ApiError(503, "remote_not_configured", "远程生成队列尚未配置。")
        try:
            run = queue.cancel_queued(run_id) if payload.action == "cancel_queued" else queue.resume(run_id)
            return _generation_run_response(run, queue)
        except GenerationQueueFullError as exc:
            raise ApiError(429, "rate_limited", str(exc), retryable=True) from exc
        except GenerationRunNotFoundError as exc:
            raise ApiError(404, "generation_run_not_found", "生成任务不存在。") from exc
        except GenerationRunActionError as exc:
            raise ApiError(409, "generation_action_invalid", str(exc)) from exc
        except KeyError as exc:
            raise ApiError(422, "remote_not_configured", str(exc)) from exc
        except ValueError as exc:
            raise ApiError(422, "workflow_incompatible", str(exc)) from exc

    @app.get(f"{API_PREFIX}/gallery/assets", dependencies=[Depends(require_session)])
    def list_gallery_assets(limit: int = Query(default=500, ge=1, le=1000)) -> dict[str, object]:
        service = app.state.gallery_service
        if service is None:
            raise ApiError(503, "gallery_not_configured", "画廊尚未连接 V2 图片目录。")
        return service.list_assets(limit=limit)

    @app.get(f"{API_PREFIX}/gallery/assets/content", dependencies=[Depends(require_session)])
    def gallery_asset_content(path: str = Query(min_length=1, max_length=2000)) -> FileResponse:
        service = app.state.gallery_service
        if service is None:
            raise ApiError(503, "gallery_not_configured", "画廊尚未连接 V2 图片目录。")
        resolved = service.resolve_content(path)
        if resolved is None:
            raise ApiError(404, "gallery_asset_not_found", "图片不存在或路径不在画廊目录中。")
        return FileResponse(resolved)

    @app.get(f"{API_PREFIX}/gallery/assets/thumbnail", dependencies=[Depends(require_session)])
    def gallery_asset_thumbnail(
        path: str = Query(min_length=1, max_length=2000),
        size: int = Query(default=640, ge=160, le=1440),
    ) -> FileResponse:
        service = app.state.gallery_service
        if service is None:
            raise ApiError(503, "gallery_not_configured", "画廊尚未连接 V2 图片目录。")
        resolved = service.resolve_thumbnail(path, size)
        if resolved is None:
            raise ApiError(404, "gallery_asset_not_found", "图片不存在或路径不在画廊目录中。")
        return FileResponse(resolved)

    @app.post(f"{API_PREFIX}/gallery/assets/state", dependencies=[Depends(require_session)])
    def set_gallery_asset_state(payload: GalleryStateRequest) -> dict[str, object]:
        service = app.state.gallery_service
        if service is None:
            raise ApiError(503, "gallery_not_configured", "画廊尚未连接 V2 图片目录。")
        return service.set_state(payload.paths, payload.state)

    @app.post(f"{API_PREFIX}/gallery/assets/trash", dependencies=[Depends(require_session)])
    def trash_gallery_assets(payload: GalleryPathsRequest) -> dict[str, object]:
        service = app.state.gallery_service
        if service is None:
            raise ApiError(503, "gallery_not_configured", "画廊尚未连接 V2 图片目录。")
        return service.move_to_trash(payload.paths)

    @app.get(f"{API_PREFIX}/gallery/trash", dependencies=[Depends(require_session)])
    def list_gallery_trash(limit: int = Query(default=500, ge=1, le=1000)) -> dict[str, object]:
        service = app.state.gallery_service
        if service is None:
            raise ApiError(503, "gallery_not_configured", "画廊尚未连接 V2 图片目录。")
        return service.list_trash(limit=limit)

    @app.get(f"{API_PREFIX}/gallery/trash/content", dependencies=[Depends(require_session)])
    def gallery_trash_content(path: str = Query(min_length=1, max_length=2000)) -> FileResponse:
        service = app.state.gallery_service
        if service is None:
            raise ApiError(503, "gallery_not_configured", "画廊尚未连接 V2 图片目录。")
        resolved = service.resolve_trash_content(path)
        if resolved is None:
            raise ApiError(404, "gallery_asset_not_found", "回收站图片不存在或路径无效。")
        return FileResponse(resolved)

    @app.get(f"{API_PREFIX}/gallery/trash/thumbnail", dependencies=[Depends(require_session)])
    def gallery_trash_thumbnail(
        path: str = Query(min_length=1, max_length=2000),
        size: int = Query(default=640, ge=160, le=1440),
    ) -> FileResponse:
        service = app.state.gallery_service
        if service is None:
            raise ApiError(503, "gallery_not_configured", "画廊尚未连接 V2 图片目录。")
        resolved = service.resolve_trash_thumbnail(path, size)
        if resolved is None:
            raise ApiError(404, "gallery_asset_not_found", "回收站图片不存在或路径无效。")
        return FileResponse(resolved)

    @app.post(f"{API_PREFIX}/gallery/trash/restore", dependencies=[Depends(require_session)])
    def restore_gallery_trash(payload: GalleryPathsRequest) -> dict[str, object]:
        service = app.state.gallery_service
        if service is None:
            raise ApiError(503, "gallery_not_configured", "画廊尚未连接 V2 图片目录。")
        return service.restore_from_trash(payload.paths)

    @app.get(f"{API_PREFIX}/gallery/process", dependencies=[Depends(require_session)])
    def list_gallery_process_jobs() -> dict[str, object]:
        service = app.state.gallery_service
        if service is None:
            raise ApiError(503, "gallery_not_configured", "画廊尚未连接 V2 图片目录。")
        return service.list_process_jobs()

    @app.post(f"{API_PREFIX}/gallery/process", dependencies=[Depends(require_session)], status_code=202)
    def submit_gallery_process(payload: GalleryProcessRequest) -> dict[str, object]:
        service = app.state.gallery_service
        if service is None:
            raise ApiError(503, "gallery_not_configured", "画廊尚未连接 V2 图片目录。")
        try:
            result = service.submit_process(payload.paths, payload.operation, payload.count)
        except GalleryUpscaleError as exc:
            raise ApiError(422, "gallery_process_unavailable", str(exc)) from exc
        if not result["jobs"] and result["failed"]:
            raise ApiError(422, "gallery_process_rejected", result["failed"][0]["error"], details=result)
        return result

    @app.post(f"{API_PREFIX}/gallery/process/action", dependencies=[Depends(require_session)])
    def gallery_process_action(payload: GalleryProcessActionRequest) -> dict[str, object]:
        service = app.state.gallery_service
        if service is None:
            raise ApiError(503, "gallery_not_configured", "画廊尚未连接 V2 图片目录。")
        try:
            return service.process_action(payload.job_id, payload.action)
        except (GalleryUpscaleError, ValueError) as exc:
            raise ApiError(409, "gallery_process_action_invalid", str(exc)) from exc

    @app.post(f"{API_PREFIX}/workspaces", dependencies=[Depends(require_session)], status_code=201)
    def create_workspace(
        payload: WorkspaceCreateRequest,
        store: WorkspaceStore = Depends(require_workspace_store),
    ) -> dict[str, object]:
        return store.create(
            payload.title,
            payload.draft.model_dump(mode="json"),
            payload.candidate_snapshot.model_dump(mode="json") if payload.candidate_snapshot else None,
        )

    @app.get(f"{API_PREFIX}/workspaces/{{workspace_id}}", dependencies=[Depends(require_session)])
    def get_workspace(
        workspace_id: str,
        store: WorkspaceStore = Depends(require_workspace_store),
    ) -> dict[str, object]:
        try:
            return store.get(workspace_id)
        except WorkspaceNotFoundError as exc:
            raise ApiError(404, "workspace_not_found", "工作台不存在。") from exc

    @app.put(f"{API_PREFIX}/workspaces/{{workspace_id}}", dependencies=[Depends(require_session)])
    def update_workspace(
        workspace_id: str,
        payload: WorkspaceUpdateRequest,
        store: WorkspaceStore = Depends(require_workspace_store),
    ) -> dict[str, object]:
        try:
            return store.update(
                workspace_id,
                expected_revision=payload.revision,
                title=payload.title,
                draft=payload.draft.model_dump(mode="json"),
                candidate_snapshot=(
                    payload.candidate_snapshot.model_dump(mode="json")
                    if payload.candidate_snapshot else None
                ),
            )
        except WorkspaceNotFoundError as exc:
            raise ApiError(404, "workspace_not_found", "工作台不存在。") from exc
        except WorkspaceRevisionConflictError as exc:
            raise ApiError(
                409,
                "workspace_revision_conflict",
                "工作台已在另一个标签页中更新。",
                details={"current_revision": exc.current_revision},
            ) from exc

    @app.delete(f"{API_PREFIX}/workspaces/{{workspace_id}}", dependencies=[Depends(require_session)])
    def delete_workspace(
        workspace_id: str,
        payload: WorkspaceDeleteRequest,
        store: WorkspaceStore = Depends(require_workspace_store),
    ) -> Response:
        try:
            store.delete(workspace_id, expected_revision=payload.revision)
        except WorkspaceNotFoundError as exc:
            raise ApiError(404, "workspace_not_found", "工作台不存在。") from exc
        except WorkspaceRevisionConflictError as exc:
            raise ApiError(
                409,
                "workspace_revision_conflict",
                "工作台已在另一个标签页中更新。",
                details={"current_revision": exc.current_revision},
            ) from exc
        return Response(status_code=204)

    if frontend_dist is not None and (frontend_dist / "index.html").is_file():
        assets = frontend_dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

        @app.get("/{frontend_path:path}", include_in_schema=False)
        def frontend(frontend_path: str, request: Request):
            if request.url.path.startswith("/api/") or request.url.path == "/health":
                return _error_response(request, 404, "not_found", "接口不存在。")

            requested = (frontend_dist / frontend_path).resolve()
            try:
                requested.relative_to(frontend_dist)
            except ValueError:
                return _error_response(request, 404, "not_found", "资源不存在。")
            if requested.is_file():
                return FileResponse(requested)
            return FileResponse(frontend_dist / "index.html")

    return ApiRuntime(app=app, bootstrap_token=bootstrap_token)


def _generation_run_response(run, queue) -> dict[str, object]:
    try:
        artifact_count = len(queue.artifacts(run.id))
    except GenerationRunNotFoundError:
        artifact_count = 0
    return {
        "id": run.id,
        "prompt_job_id": run.prompt_job_id,
        "remote_profile_id": run.remote_profile_id,
        "workflow_profile_id": run.workflow_profile_id,
        "state": run.state.value,
        "progress": run.progress,
        "status_message": run.status_message,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "artifact_count": artifact_count,
        "available_actions": queue.available_actions(run.id),
        "error": {
            "code": run.error_code,
            "message": run.error_message,
        } if run.error_code or run.error_message else None,
    }


def _workbench_intent(payload: WorkbenchCandidateRequest) -> IntentDocument:
    elements = [
        IntentElement(
            id=item.id,
            original_text=item.text,
            canonical_tag=item.canonical_tag,
            type=item.type,
            state=item.state,
            confidence=1.0,
            provenance=ElementProvenance(kind=ProvenanceKind.USER, detail="workbench"),
        )
        for item in payload.elements
    ]
    edges = [
        ConstraintEdge(
            id=item.id,
            source_element_id=item.source_element_id,
            target_element_id=item.target_element_id,
            kind=ConstraintKind.RELATION,
            relation=item.relation,
            custom_relation=item.custom_relation,
            reason=item.reason,
        )
        for item in payload.relations
    ]
    return IntentDocument(
        source_text=payload.source_text,
        source_language=payload.source_language,
        graph=ConstraintGraph(elements=elements, edges=edges),
    )


def _data_pack_summary(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"id": None, "ready": False, "cutoff_mode": None}
    try:
        with ReferenceDataStore(path) as store:
            return {
                "id": store.pack_id,
                "ready": True,
                "cutoff_mode": store.metadata("cutoff_mode"),
            }
    except DataContractError:
        return {"id": None, "ready": False, "cutoff_mode": None}


def _tag_search_item(row: dict[str, object]) -> dict[str, object]:
    return {
        "id": row["id"],
        "name": row["name"],
        "display_name": row["render_name"],
        "cn_name": row["cn_name"],
        "category": row["category_name"],
        "post_count": row["post_count"],
        "nsfw": row["nsfw"],
        "match": {"kind": "search", "score": None},
    }


def _hostname(host_header: str) -> str:
    try:
        return (urlsplit(f"//{host_header}").hostname or "").lower()
    except ValueError:
        return ""


def _allowed_loopback_origin(origin: str, allowed_hosts: set[str]) -> bool:
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return (
        parsed.scheme == "http"
        and (parsed.hostname or "").lower() in allowed_hosts
        and parsed.username is None
        and parsed.password is None
    )


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    *,
    details: dict[str, object] | None = None,
    retryable: bool = False,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", f"req_{uuid4().hex}")
    response = JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": request_id,
                "retryable": retryable,
            }
        },
    )
    response.headers["X-Request-ID"] = request_id
    return response
