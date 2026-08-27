from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
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
)
from ..data import DataContractError, ReferenceDataStore
from ..domain import (
    CandidateArtist,
    CandidateLane,
    ConstraintEdge,
    ConstraintGraph,
    ConstraintKind,
    ElementProvenance,
    IntentDocument,
    IntentElement,
    IntentElementType,
    IntentState,
    ProvenanceKind,
    SourceSpan,
)
from .models import (
    ArtistRecommendRequest,
    GenerationBridgePreviewRequest,
    GalleryPathsRequest,
    GalleryProcessActionRequest,
    GalleryProcessRequest,
    GalleryStateRequest,
    ArtistComparisonRequest,
    GenerationRunActionRequest,
    GenerationSubmitRequest,
    IntentCandidateRequest,
    IntentParseRequest,
    LocalNaturalCandidateRequest,
    PrivateKeyPassphraseRequest,
    RemoteProfileSettingsRequest,
    RemoteHostFingerprintRequest,
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
    v2_database: Path | None = None,
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
    app.state.v2_database = v2_database.resolve() if v2_database is not None else None
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

    def require_v2_settings_database() -> Path:
        database = app.state.v2_database
        if database is None or not database.is_file():
            raise ApiError(503, "v2_settings_unavailable", "未连接 V2 配置库，无法管理远程连接。", retryable=True)
        return database

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
                bundle = HybridLaneGenerator(store).add_hybrid(bundle, profile)
                validation = CandidateValidator(store).validate_or_raise(bundle, profile)
                literal = bundle.candidates[0]
                return {
                    "intent": bundle.intent.model_dump(mode="json"),
                    "candidates": [item.model_dump(mode="json") for item in bundle.candidates],
                    "validation": validation.model_dump(mode="json"),
                    "tag_suggestions": store.related_tags(
                        [tag.name for tag in literal.tags],
                        categories={"general", "meta"},
                        limit=10,
                    ),
                    "artist_suggestions": store.recommend_artists(
                        [tag.name for tag in literal.tags],
                        limit=10,
                    ),
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
        translator = app.state.translation_service
        if _workbench_uses_local_mapping(payload, translator):
            positive_text = "，".join(
                item.text for item in payload.elements if item.state != IntentState.EXCLUDED
            )
            if payload.translated_text:
                translated_text = payload.translated_text
                translation_engine = "当前工作台译文"
            else:
                try:
                    translated = translator.translate(positive_text, direction="zh_en")
                except (RuntimeError, ValueError) as exc:
                    raise ApiError(422, "translation_failed", str(exc)) from exc
                translated_text = translated.translated_text
                translation_engine = translated.engine_name
            with ReferenceDataStore(database) as store:
                intent, scene_draft = _local_natural_intent(
                    positive_text,
                    translated_text,
                    store,
                    selected_tags=payload.selected_tags,
                )
                intent = _apply_workbench_exclusions(intent, payload, store, scene_draft)
            response = candidate_response(intent, payload.model_profile, database)
            response["local_translation"] = {
                "translated_text": translated_text,
                "engine": translation_engine,
                "local_only": True,
            }
            response["scene_draft"] = scene_draft
            return response
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

    @app.post(f"{API_PREFIX}/local-natural/candidates", dependencies=[Depends(require_session)])
    def generate_local_natural_candidates(
        payload: LocalNaturalCandidateRequest,
        database: Path = Depends(require_reference_db),
    ) -> dict[str, object]:
        """Default natural-language route: local translation plus deterministic tag lookup.

        This deliberately avoids the V2 AI extractor.  The complete local
        translation is retained as the scene plan, while only exact local index
        matches become tags, so the user can see what was inferred.
        """
        translator = app.state.translation_service
        if translator is None:
            raise ApiError(503, "translation_unavailable", "本地翻译服务未安装。")
        if payload.translated_text:
            translated_text = payload.translated_text
            translation_engine = "当前工作台译文"
        else:
            try:
                translated = translator.translate(payload.source_text, direction="zh_en")
            except (RuntimeError, ValueError) as exc:
                raise ApiError(422, "translation_failed", str(exc)) from exc
            translated_text = translated.translated_text
            translation_engine = translated.engine_name
        with ReferenceDataStore(database) as store:
            intent, scene_draft = _local_natural_intent(
                payload.source_text,
                translated_text,
                store,
                selected_tags=payload.selected_tags,
            )
            response = candidate_response(intent, payload.model_profile, database)
        response["local_translation"] = {
            "translated_text": translated_text,
            "engine": translation_engine,
            "local_only": True,
        }
        response["scene_draft"] = scene_draft
        return response

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

    @app.post(
        f"{API_PREFIX}/artist-comparisons",
        dependencies=[Depends(require_session)],
        status_code=202,
    )
    def submit_artist_comparison(
        payload: ArtistComparisonRequest,
        database: Path = Depends(require_reference_db),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, object]:
        """Queue one comparable generation per selected recommendation.

        The baseline candidate is intentionally immutable here.  Every prepared
        job receives the same V2 generation settings; its only prompt delta is
        exactly one explicitly selected artist tag.
        """
        queue = app.state.generation_queue
        if queue is None:
            raise ApiError(503, "remote_not_configured", "远程生成队列尚未配置。")
        if generation_bridge is None or V2GenerationSettings is None:
            raise ApiError(503, "v2_runtime_missing", "当前安装不包含 V2 兼容运行时。")
        if not idempotency_key or not idempotency_key.strip():
            raise ApiError(422, "invalid_request", "画师对照任务必须提供 Idempotency-Key。")
        try:
            profile = profiles.get(payload.candidate.versions.model_profile)
        except KeyError as exc:
            raise ApiError(422, "model_profile_unknown", "画师对照基准使用了未知模型配置。") from exc

        with ReferenceDataStore(database) as store:
            recommended = {
                item["name"]: item
                for item in store.recommend_artists(
                    [tag.name for tag in payload.candidate.tags],
                    limit=100,
                )
            }
        unavailable = [name for name in payload.artist_names if name not in recommended]
        if unavailable:
            raise ApiError(
                422,
                "artist_not_recommended",
                "所选画师不在当前基准提示词的可追溯推荐池中。",
                details={"unavailable_artists": unavailable},
            )

        source_element_ids = list(payload.candidate.preserved_element_ids)
        if not source_element_ids:
            source_element_ids = [payload.intent.graph.elements[0].id]
        project_name = f"{payload.project_name} · 画师对照 {payload.comparison_id[-8:]}"
        submitted: list[dict[str, object]] = []
        failed: list[dict[str, str]] = []
        settings = V2GenerationSettings(**payload.settings.model_dump())

        for position, name in enumerate(payload.artist_names, start=1):
            recommendation = recommended[name]
            artist = CandidateArtist(
                name=name,
                rendered=str(recommendation["render_name"]),
                source_element_ids=source_element_ids,
                reason=f"用户选择的画师对照；匹配标签：{', '.join(recommendation['sources'])}",
                raw_score=float(recommendation["raw_score"]),
                display_score=float(recommendation["display_score"]),
                data_pack_id=str(recommendation["data_pack_id"]),
                algorithm_version=str(recommendation["algorithm_version"]),
            )
            values = [payload.candidate.positive_prompt, artist.rendered]
            positive_prompt = profile.tag_separator.join(dict.fromkeys(value for value in values if value))
            comparison = {
                "id": payload.comparison_id,
                "artist": artist.name,
                "rendered_artist": artist.rendered,
                "position": position,
                "total": len(payload.artist_names),
                "seed": payload.settings.seed,
            }
            candidate = payload.candidate.model_copy(
                update={
                    "id": f"candidate_comparison_{payload.comparison_id.removeprefix('comparison_')}_{position}",
                    "lane": CandidateLane.ARTIST,
                    "title": f"画师对照 · {artist.rendered}",
                    "positive_prompt": positive_prompt,
                    "artists": [artist],
                    "score_breakdown": {
                        **payload.candidate.score_breakdown,
                        "artist_score": artist.raw_score or 0.0,
                        "comparison_position": float(position),
                    },
                    "versions": payload.candidate.versions.model_copy(update={"algorithm": "artist-comparison-v1"}),
                },
            )
            try:
                prepared = generation_bridge.prepare(
                    candidate,
                    payload.intent,
                    project_name=project_name,
                    settings=settings,
                    workspace_id=payload.workspace_id,
                    workspace_revision=payload.workspace_revision,
                )
                job = prepared.job.model_copy(
                    update={
                        "integration_metadata": {
                            **prepared.job.integration_metadata,
                            "artist_comparison": comparison,
                        }
                    }
                )
                prepared = type(prepared)(job=job, checkpoint_logical_name=prepared.checkpoint_logical_name)
                run = queue.submit(
                    prepared,
                    remote_profile_id=payload.remote_profile_id,
                    workflow_profile_id=payload.workflow_profile_id,
                    idempotency_key=f"{idempotency_key.strip()}:{name}",
                )
                submitted.append({"artist": artist.rendered, "run": _generation_run_response(run, queue)})
            except GenerationQueueFullError as exc:
                failed.append({"artist": artist.rendered, "error": str(exc)})
            except KeyError as exc:
                failed.append({"artist": artist.rendered, "error": str(exc)})
            except (ValueError, GenerationQueueError) as exc:
                failed.append({"artist": artist.rendered, "error": str(exc)})

        if not submitted:
            message = failed[0]["error"] if failed else "画师对照任务未能进入生成队列。"
            raise ApiError(429 if failed else 422, "artist_comparison_rejected", message, details={"failed": failed}, retryable=True)
        return {
            "comparison_id": payload.comparison_id,
            "project_name": project_name,
            "seed": payload.settings.seed,
            "requested_count": len(payload.artist_names),
            "submitted": submitted,
            "failed": failed,
        }

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

    @app.get(f"{API_PREFIX}/settings/remote-profiles", dependencies=[Depends(require_session)])
    def list_remote_profiles_for_settings(
        database: Path = Depends(require_v2_settings_database),
    ) -> dict[str, object]:
        """Expose V2 connection metadata without ever exposing a secret."""
        from anima_prompt_studio.repositories.sqlite_repository import SQLiteRepository
        from anima_prompt_studio.services.remote.credential_store import CredentialStore

        repository = SQLiteRepository(database)
        try:
            credentials = CredentialStore()
            profiles = repository.list_remote_profiles()
            workflows = repository.list_workflow_profiles()
            return {
                "items": [_remote_profile_settings_response(item, credentials) for item in profiles],
                "workflows": [
                    {
                        "id": item.id,
                        "display_name": item.display_name,
                        "workflow_kind": item.workflow_kind,
                        "notes": item.notes,
                    }
                    for item in workflows
                ],
                "credential_store_available": credentials.available,
            }
        finally:
            repository.close()

    @app.post(
        f"{API_PREFIX}/settings/remote-profiles",
        dependencies=[Depends(require_session)],
        status_code=201,
    )
    def create_remote_profile_for_settings(
        payload: RemoteProfileSettingsRequest,
        database: Path = Depends(require_v2_settings_database),
    ) -> dict[str, object]:
        return _save_remote_profile_settings(database, payload)

    @app.put(
        f"{API_PREFIX}/settings/remote-profiles/{{profile_id}}",
        dependencies=[Depends(require_session)],
    )
    def update_remote_profile_for_settings(
        profile_id: str,
        payload: RemoteProfileSettingsRequest,
        database: Path = Depends(require_v2_settings_database),
    ) -> dict[str, object]:
        return _save_remote_profile_settings(database, payload, profile_id=profile_id)

    @app.post(
        f"{API_PREFIX}/settings/remote-profiles/{{profile_id}}/probe-host-key",
        dependencies=[Depends(require_session)],
    )
    def probe_remote_profile_host_key(
        profile_id: str,
        database: Path = Depends(require_v2_settings_database),
    ) -> dict[str, object]:
        profile = _get_v2_remote_profile(database, profile_id)
        try:
            from anima_prompt_studio.services.remote.ssh_tunnel import SshTunnel
            fingerprint = SshTunnel(profile).probe_fingerprint()
        except (OSError, RuntimeError) as exc:
            raise ApiError(502, "ssh_host_key_probe_failed", f"无法读取 SSH 主机指纹：{exc}", retryable=True) from exc
        return {"fingerprint": fingerprint}

    @app.post(
        f"{API_PREFIX}/settings/remote-profiles/{{profile_id}}/confirm-host-key",
        dependencies=[Depends(require_session)],
    )
    def confirm_remote_profile_host_key(
        profile_id: str,
        payload: RemoteHostFingerprintRequest,
        database: Path = Depends(require_v2_settings_database),
    ) -> dict[str, object]:
        profile = _get_v2_remote_profile(database, profile_id)
        try:
            from anima_prompt_studio.services.remote.ssh_tunnel import SshTunnel
            actual = SshTunnel(profile).probe_fingerprint()
        except (OSError, RuntimeError) as exc:
            raise ApiError(502, "ssh_host_key_probe_failed", f"无法读取 SSH 主机指纹：{exc}", retryable=True) from exc
        if actual != payload.fingerprint:
            raise ApiError(409, "ssh_host_key_changed", "SSH 主机指纹在确认前发生变化，请重新检测。")
        from anima_prompt_studio.repositories.sqlite_repository import SQLiteRepository
        from anima_prompt_studio.services.remote.credential_store import CredentialStore
        repository = SQLiteRepository(database)
        try:
            repository.save_remote_profile(profile.model_copy(update={"known_host_fingerprint": actual}))
            return _remote_profile_settings_response(profile.model_copy(update={"known_host_fingerprint": actual}), CredentialStore())
        finally:
            repository.close()

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
    prompt_job = run.request_json.get("prompt_job", {}) if isinstance(run.request_json, dict) else {}
    integration = prompt_job.get("integration_metadata", {}) if isinstance(prompt_job, dict) else {}
    comparison = integration.get("artist_comparison") if isinstance(integration, dict) else None
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
        "artist_comparison": comparison if isinstance(comparison, dict) else None,
    }


def _remote_profile_settings_response(profile, credentials) -> dict[str, object]:
    return {
        "id": profile.id,
        "display_name": profile.display_name,
        "ssh_host": profile.ssh_host,
        "ssh_port": profile.ssh_port,
        "ssh_user": profile.ssh_user,
        "auth_type": profile.auth_type.value,
        "private_key_path": profile.private_key_path,
        "enabled": profile.enabled,
        "has_saved_password": bool(credentials.read_password(profile.id)),
        "host_fingerprint_confirmed": bool(profile.known_host_fingerprint.strip()),
        "comfy_endpoint": f"{profile.comfy_host}:{profile.comfy_port}",
    }


def _get_v2_remote_profile(database: Path, profile_id: str):
    from anima_prompt_studio.repositories.sqlite_repository import SQLiteRepository

    repository = SQLiteRepository(database)
    try:
        return repository.get_remote_profile(profile_id)
    except KeyError as exc:
        raise ApiError(404, "remote_profile_not_found", "云主机配置不存在。") from exc
    finally:
        repository.close()


def _save_remote_profile_settings(database: Path, payload: RemoteProfileSettingsRequest, *, profile_id: str | None = None) -> dict[str, object]:
    """Update only V2's supported configuration store and Windows credentials.

    A new SSH endpoint must be trusted again: carrying a fingerprint across host,
    port, user, authentication or key changes would weaken host-key verification.
    """
    from anima_prompt_studio.domain.execution_models import RemoteAuthType, RemoteProfile
    from anima_prompt_studio.repositories.sqlite_repository import SQLiteRepository
    from anima_prompt_studio.services.remote.credential_store import CredentialStore, CredentialStoreError

    repository = SQLiteRepository(database)
    credentials = CredentialStore()
    try:
        existing = None
        if profile_id is not None:
            try:
                existing = repository.get_remote_profile(profile_id)
            except KeyError as exc:
                raise ApiError(404, "remote_profile_not_found", "云主机配置不存在。") from exc
        changes = {
            "display_name": payload.display_name,
            "ssh_host": payload.ssh_host,
            "ssh_port": payload.ssh_port,
            "ssh_user": payload.ssh_user,
            "auth_type": RemoteAuthType(payload.auth_type),
            "private_key_path": payload.private_key_path,
            "enabled": payload.enabled,
        }
        if existing is None:
            profile = RemoteProfile(**changes)
        else:
            endpoint_changed = (
                existing.ssh_host,
                existing.ssh_port,
                existing.ssh_user,
                existing.auth_type.value,
                existing.private_key_path,
            ) != (
                payload.ssh_host,
                payload.ssh_port,
                payload.ssh_user,
                payload.auth_type,
                payload.private_key_path,
            )
            if endpoint_changed:
                changes["known_host_fingerprint"] = ""
            profile = existing.model_copy(update=changes)
        repository.save_remote_profile(profile)

        entered_password = payload.password.get_secret_value() if payload.password is not None else ""
        if entered_password and payload.remember_password:
            try:
                credentials.save_password(profile.id, profile.ssh_user, entered_password)
            except CredentialStoreError as exc:
                raise ApiError(503, "credential_store_unavailable", str(exc), retryable=True) from exc
        elif not payload.remember_password:
            credentials.delete_password(profile.id)
        return _remote_profile_settings_response(profile, credentials)
    finally:
        repository.close()


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


def _workbench_uses_local_mapping(payload: WorkbenchCandidateRequest, translator: object | None) -> bool:
    """Use the same resolver for user-entered concept text, not only prose mode.

    The structured editor is for manually separated *concepts*, not for asking
    users to memorize canonical Danbooru spelling.  Explicit canonical input and
    graph relations retain the original low-level API path.
    """
    return bool(
        translator is not None
        and not payload.relations
        and not any(item.canonical_tag for item in payload.elements)
        and any("\u3400" <= character <= "\u9fff" for character in payload.source_text)
    )


def _apply_workbench_exclusions(
    intent: IntentDocument,
    payload: WorkbenchCandidateRequest,
    store: ReferenceDataStore,
    scene_draft: dict[str, object],
) -> IntentDocument:
    """Map explicit structured exclusions without treating them as positive prose."""
    elements = list(intent.graph.elements)
    unresolved = list(scene_draft["unresolved"])
    for item in payload.elements:
        if item.state != IntentState.EXCLUDED:
            continue
        resolved: list[_LocalIndexMatch] = []
        if item.canonical_tag:
            detail = store.get_tag(item.canonical_tag)
            if detail is not None:
                resolved = [_LocalIndexMatch(
                    text=item.text,
                    origin="source",
                    canonical_tag=str(detail["name"]),
                    match_kind="canonical",
                    post_count=int(detail["post_count"]),
                )]
        else:
            exclusion_matches = _local_index_matches(store, _local_lookup_terms(item.text, ""))
            resolved, _ambiguous = _confirmed_source_matches(exclusion_matches)
        if not resolved:
            unresolved.append(_scene_draft_item(
                f"u_{item.id}",
                item.text,
                None,
                "unresolved",
                "未找到可安全写入负向提示词的排除标签；原文仍保留供人工处理。",
            ))
            continue
        for index, match in enumerate(resolved, 1):
            elements.append(IntentElement(
                id=item.id if index == 1 else f"{item.id}_{index}",
                original_text=match.text,
                canonical_tag=match.canonical_tag,
                type=item.type,
                state=IntentState.EXCLUDED,
                confidence=1.0,
                provenance=ElementProvenance(kind=ProvenanceKind.EXACT, detail="local_structured_exclusion"),
            ))
    scene_draft["unresolved"] = unresolved
    return intent.model_copy(update={"graph": ConstraintGraph(elements=elements, edges=intent.graph.edges)})


@dataclass(frozen=True)
class _LocalLookupTerm:
    text: str
    origin: str
    start: int | None = None
    end: int | None = None


def _local_natural_intent(
    source_text: str,
    translated_text: str,
    store: ReferenceDataStore,
    *,
    selected_tags: list[str],
) -> tuple[IntentDocument, dict[str, object]]:
    """Build a reviewable local draft without treating every index hit as required.

    Source-text index hits are deterministic local evidence.  Translation hits
    stay in the suggestion pool until the user explicitly selects them.  The
    complete translation remains a prose fallback so an empty tag match can
    never erase a natural-language draft.
    """
    matches = _local_index_matches(store, _local_lookup_terms(source_text, translated_text))
    source_matches, ambiguous_source_terms = _confirmed_source_matches(matches)
    selected = list(dict.fromkeys(selected_tags))
    selected_set = set(selected)
    elements: list[IntentElement] = []
    confirmed: list[dict[str, object]] = []

    for index, match in enumerate(source_matches, 1):
        element_id = f"e_local_confirmed_{index}"
        elements.append(IntentElement(
            id=element_id,
            original_text=match.text,
            canonical_tag=match.canonical_tag,
            type=IntentElementType.OTHER,
            state=IntentState.REQUIRED,
            confidence=1.0,
            source_span=SourceSpan(start=match.start, end=match.end) if match.start is not None and match.end is not None else None,
            provenance=ElementProvenance(kind=ProvenanceKind.EXACT, detail="local_source_index_exact"),
        ))
        confirmed.append(_scene_draft_item(
            element_id,
            match.text,
            match.canonical_tag,
            "source_exact",
            "中文原文与本地标签索引精确匹配",
            match.start,
            match.end,
        ))

    confirmed_tags = {match.canonical_tag for match in source_matches}
    for index, tag in enumerate(selected, 1):
        detail = store.get_tag(tag)
        if detail is None or tag in confirmed_tags:
            continue
        element_id = f"e_local_selected_{index}"
        rendered = str(detail["render_name"])
        elements.append(IntentElement(
            id=element_id,
            original_text=rendered,
            canonical_tag=tag,
            type=IntentElementType.OTHER,
            state=IntentState.USER_SELECTED,
            confidence=1.0,
            provenance=ElementProvenance(kind=ProvenanceKind.MANUAL, detail="local_draft_user_selected"),
        ))
        confirmed.append(_scene_draft_item(
            element_id,
            rendered,
            tag,
            "user_selected",
            "用户从建议池确认加入",
        ))

    translation_matches = [
        match
        for match in _confirmed_translation_matches(matches)
        if match.canonical_tag not in confirmed_tags and match.canonical_tag not in selected_set
    ]
    suggestions = [
        _scene_draft_item(
            f"s_local_translation_{index}",
            match.text,
            match.canonical_tag,
            "translation_exact",
            "英文译文直接命中本地标签；需要确认后才会加入候选",
        )
        for index, match in enumerate(translation_matches[:12], 1)
    ]

    unresolved: list[dict[str, object]] = []
    if not source_matches:
        unresolved.append(_scene_draft_item(
            "u_local_scene",
            source_text.strip(),
            None,
            "unresolved",
            "未找到可直接确认的中文标签；完整译文会保留为可编辑 prose baseline。",
        ))

    if not elements:
        elements.append(IntentElement(
            id="e_local_scene",
            original_text="local scene description",
            type=IntentElementType.SCENE,
            state=IntentState.REQUIRED,
            confidence=1.0,
            provenance=ElementProvenance(kind=ProvenanceKind.TRANSLATION, detail="local_prose_baseline"),
            notes=["local_prose_baseline"],
        ))

    intent = IntentDocument(
        source_text=source_text.strip(),
        source_language="zh",
        translated_text=translated_text.strip(),
        scene_plan_en=translated_text.strip() or None,
        graph=ConstraintGraph(elements=elements),
    )
    scene_draft = {
        "source_text": source_text.strip(),
        "translated_text": translated_text.strip(),
        "confirmed": confirmed,
        "suggestions": suggestions,
        "unresolved": unresolved,
        "risk_notes": [
            *(
                [f"{', '.join(f'“{item}”' for item in ambiguous_source_terms[:3])} 可关联多条标签；已只确认唯一的主标签，其余仅通过建议池提供。"]
                if ambiguous_source_terms
                else []
            ),
            "当前仅自动确认唯一的主标签或英文 canonical/alias 命中；人物归属、复杂动作、空间关系和构图仍需人工检查。",
        ],
    }
    return intent, scene_draft


@dataclass(frozen=True)
class _LocalIndexMatch:
    text: str
    origin: str
    canonical_tag: str
    match_kind: str
    post_count: int
    start: int | None = None
    end: int | None = None


def _local_lookup_terms(source_text: str, translated_text: str) -> list[_LocalLookupTerm]:
    terms: list[_LocalLookupTerm] = []
    seen: set[tuple[str, str, int | None, int | None]] = set()

    def add(text: str, origin: str, start: int | None = None, end: int | None = None) -> None:
        normalized = text.strip().lower()
        if len(normalized) < 2 or len(terms) >= 2_000:
            return
        key = (origin, normalized, start, end)
        if key not in seen:
            seen.add(key)
            terms.append(_LocalLookupTerm(normalized, origin, start, end))

    def add_chinese(text: str, origin: str) -> None:
        for segment in re.finditer(r"[\u3400-\u9fff]{2,}", text):
            value = segment.group(0)
            for start_index in range(len(value)):
                max_end = min(len(value), start_index + 12)
                for end_index in range(max_end, start_index + 1, -1):
                    add(
                        value[start_index:end_index],
                        origin,
                        segment.start() + start_index if origin == "source" else None,
                        segment.start() + end_index if origin == "source" else None,
                    )

    def add_english(text: str, origin: str) -> None:
        words = list(re.finditer(r"[a-z0-9_]+", text.lower()))
        for index, word in enumerate(words):
            add(word.group(0), origin, word.start() if origin == "source" else None, word.end() if origin == "source" else None)
            for width in range(2, min(4, len(words) - index) + 1):
                chunk = words[index:index + width]
                phrase = " ".join(item.group(0) for item in chunk)
                add(phrase, origin, chunk[0].start() if origin == "source" else None, chunk[-1].end() if origin == "source" else None)

    add_chinese(source_text, "source")
    add_english(source_text, "source")
    add_chinese(translated_text, "translation")
    add_english(translated_text, "translation")
    return terms


def _local_index_matches(store: ReferenceDataStore, terms: list[_LocalLookupTerm]) -> list[_LocalIndexMatch]:
    if not terms:
        return []
    by_text: dict[str, list[_LocalLookupTerm]] = {}
    for term in terms:
        by_text.setdefault(term.text, []).append(term)
    matches: list[_LocalIndexMatch] = []
    ordered_terms = sorted(by_text)
    for offset in range(0, len(ordered_terms), 500):
        batch = ordered_terms[offset:offset + 500]
        placeholders = ",".join("?" for _ in batch)
        rows = store.connection.execute(
            f"""SELECT s.term,s.canonical,t.render_name,t.cn_name,t.cn_terms,t.post_count
                FROM tag_search s JOIN tags t ON t.name=s.canonical
                WHERE s.term IN ({placeholders}) AND t.deprecated=0""",
            batch,
        ).fetchall()
        for row in rows:
            term = str(row["term"])
            canonical_tag = str(row["canonical"])
            match_kind = _local_match_kind(row, term)
            for occurrence in by_text.get(term, []):
                matches.append(_LocalIndexMatch(
                    text=occurrence.text,
                    origin=occurrence.origin,
                    canonical_tag=canonical_tag,
                    match_kind=match_kind,
                    post_count=int(row["post_count"]),
                    start=occurrence.start,
                    end=occurrence.end,
                ))
    return matches


def _local_match_kind(row: object, term: str) -> str:
    """State how a tag-search row earned its term, not merely that it matched."""
    name = str(row["canonical"])
    render_name = str(row["render_name"])
    if term == name:
        return "canonical"
    if term == render_name:
        return "render"
    if term == (row["cn_name"] or ""):
        return "cn_name"
    try:
        if term in json.loads(row["cn_terms"] or "[]"):
            return "cn_term"
    except (TypeError, ValueError):
        pass
    return "alias"


def _confirmed_source_matches(matches: list[_LocalIndexMatch]) -> tuple[list[_LocalIndexMatch], list[str]]:
    """Resolve Chinese evidence without promoting every shared keyword to fact.

    Chinese search terms in the reference pack intentionally include broad related
    words.  For example, “天使” occurs on named characters, halos, statues and
    the generic ``angel`` tag.  Only a unique canonical/render/alias/CN primary
    name may be confirmed; broad ``cn_terms`` remain discovery metadata.
    """
    by_occurrence: dict[tuple[str, int | None, int | None], list[_LocalIndexMatch]] = {}
    for match in matches:
        if match.origin == "source":
            by_occurrence.setdefault((match.text, match.start, match.end), []).append(match)

    resolved: list[_LocalIndexMatch] = []
    ambiguous_terms: list[str] = []
    primary_kinds = {"canonical", "render", "alias", "cn_name"}
    for (text, _start, _end), candidates in by_occurrence.items():
        unique = _unique_canonical_matches(candidates)
        primaries = _unique_canonical_matches([item for item in unique if item.match_kind in primary_kinds])
        selected: _LocalIndexMatch | None = None
        if len(primaries) == 1:
            selected = primaries[0]
        if len(unique) > 1:
            ambiguous_terms.append(text)
        if selected is not None:
            resolved.append(selected)

    # Prefer the most specific non-overlapping phrase: “堕天使” must win over
    # the nested “天使”, while repeated independent phrases may both survive.
    accepted: list[_LocalIndexMatch] = []
    for match in sorted(resolved, key=lambda item: (-len(item.text), _match_priority(item), -item.post_count, item.canonical_tag)):
        if any(_spans_overlap(match, existing) for existing in accepted):
            continue
        accepted.append(match)
    accepted.sort(key=lambda item: (item.start if item.start is not None else 0, -len(item.text), item.canonical_tag))
    return _dedupe_canonical_matches(accepted), list(dict.fromkeys(ambiguous_terms))


def _confirmed_translation_matches(matches: list[_LocalIndexMatch]) -> list[_LocalIndexMatch]:
    """Only direct English canonical/render/alias hits are translation evidence."""
    direct_kinds = {"canonical", "render", "alias"}
    candidates = [item for item in matches if item.origin == "translation" and item.match_kind in direct_kinds]
    return _dedupe_canonical_matches(sorted(candidates, key=lambda item: (_match_priority(item), -len(item.text), -item.post_count, item.canonical_tag)))


def _unique_canonical_matches(matches: list[_LocalIndexMatch]) -> list[_LocalIndexMatch]:
    best: dict[str, _LocalIndexMatch] = {}
    for item in matches:
        existing = best.get(item.canonical_tag)
        if existing is None or (_match_priority(item), -item.post_count, item.canonical_tag) < (_match_priority(existing), -existing.post_count, existing.canonical_tag):
            best[item.canonical_tag] = item
    return sorted(best.values(), key=lambda item: (_match_priority(item), -item.post_count, item.canonical_tag))


def _dedupe_canonical_matches(matches: list[_LocalIndexMatch]) -> list[_LocalIndexMatch]:
    return _unique_canonical_matches(matches)


def _match_priority(match: _LocalIndexMatch) -> int:
    return {"canonical": 0, "render": 1, "alias": 2, "cn_name": 3, "cn_term": 4}.get(match.match_kind, 5)


def _spans_overlap(left: _LocalIndexMatch, right: _LocalIndexMatch) -> bool:
    if None in {left.start, left.end, right.start, right.end}:
        return False
    return left.start < right.end and right.start < left.end


def _scene_draft_item(
    item_id: str,
    text: str,
    canonical_tag: str | None,
    source: str,
    reason: str,
    source_start: int | None = None,
    source_end: int | None = None,
) -> dict[str, object]:
    return {
        "id": item_id,
        "text": text,
        "canonical_tag": canonical_tag,
        "source": source,
        "reason": reason,
        "source_start": source_start,
        "source_end": source_end,
    }


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
