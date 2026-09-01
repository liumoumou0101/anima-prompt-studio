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
from ..core.composition import (
    COMPOSITION_CHIP_TAGS,
    COMPOSITION_WEAK_META_TERMS,
    auto_exclude_gaze_spans,
    build_composition_palette,
    clothing_crop_needed,
    composition_preset_snapshots,
    coerce_selected_composition,
    composition_fact_type,
    composition_phrase_occupiers,
    composition_prose_conflicts,
    divert_untrusted_composition_matches,
    filter_weak_meta_matches,
    positive_composition_hints,
    prior_risk_notes,
    strip_focus_leftover_tags,
)
from ..data import DataContractError, ReferenceDataStore
from ..data.store import ARTIST_RANKING_MODES, ARTIST_RANKING_TAG_FIT
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
    RelationKind,
    SourceSpan,
)
from .models import (
    ArtistRankingSettingsRequest,
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
    PreferredRemoteProfileRequest,
    RemoteConnectionTestRequest,
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
TAG_BROWSE_CATEGORIES = {"general", "copyright", "character", "meta"}
TAG_SENSITIVE_GROUPS = {
    "ass",
    "bdsm_and_torture",
    "breasts_tags",
    "nudity",
    "pussy",
    "sex_acts",
    "sex_objects",
    "sexual_attire",
    "sexual_positions",
}
TAG_BROWSE_GROUPS = [
    ("hair_color", "发色", "从基础发色开始组合人物外观"),
    ("hair_styles", "发型", "长度、扎法与轮廓"),
    ("eyes_tags", "眼睛", "颜色、形态与视线"),
    ("face_tags", "表情与面部", "情绪、妆容和面部细节"),
    ("attire", "服装", "常见服装与角色着装"),
    ("fashion_style", "穿搭风格", "整体造型与时代风格"),
    ("accessories", "配饰", "首饰、随身装饰与点缀"),
    ("posture", "姿势", "站、坐、卧与身体状态"),
    ("gestures", "动作手势", "手部动作与人物互动"),
    ("holding_tags", "手持物", "人物与道具的关系"),
    ("image_composition", "构图", "景别、视角与画面组织"),
    ("lighting", "光线", "时间、方向与照明氛围"),
    ("backgrounds", "背景", "环境复杂度与背景处理"),
    ("locations", "地点", "室内、户外与幻想场所"),
    ("flowers", "花卉植物", "自然物与装饰性植物"),
    ("food_tags", "食物", "餐饮、甜点与料理"),
    ("jobs", "职业身份", "制服、职业与人物设定"),
    ("legendary_creatures", "幻想生物", "传说生物与非人角色"),
]
LOGGER = logging.getLogger(__name__)
ARTIST_RANKING_SETTING = "v3_artist_ranking"


def _artist_ranking_from_database(database: Path | None) -> str:
    if database is None or not Path(database).is_file():
        return ARTIST_RANKING_TAG_FIT
    from anima_prompt_studio.repositories.sqlite_repository import SQLiteRepository

    repository = SQLiteRepository(database)
    try:
        value = str(repository.get_setting(ARTIST_RANKING_SETTING, ARTIST_RANKING_TAG_FIT) or ARTIST_RANKING_TAG_FIT)
    finally:
        repository.close()
    return value if value in ARTIST_RANKING_MODES else ARTIST_RANKING_TAG_FIT


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
                candidates = []
                for item in bundle.candidates:
                    candidate = item.model_dump(mode="json")
                    for tag in candidate["tags"]:
                        tag["cn_name"] = _tag_cn_name(store.get_tag(str(tag["name"])))
                    candidates.append(candidate)
                return {
                    "intent": bundle.intent.model_dump(mode="json"),
                    "candidates": candidates,
                    "validation": validation.model_dump(mode="json"),
                    "tag_suggestions": [
                        item for item in store.related_tags(
                            [tag.name for tag in literal.tags],
                            categories={"general", "meta"},
                            limit=10,
                        )
                        if item["name"] not in COMPOSITION_CHIP_TAGS
                    ],
                    "artist_suggestions": store.recommend_artists(
                        [tag.name for tag in literal.tags],
                        limit=10,
                        ranking=_artist_ranking_from_database(app.state.v2_database),
                    ),
                    "artist_ranking": _artist_ranking_from_database(app.state.v2_database),
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

    @app.get(f"{API_PREFIX}/tags/browse", dependencies=[Depends(require_session)])
    def browse_tags(
        category: list[str] = Query(default=[]),
        include_nsfw: bool = False,
        featured_limit: int = Query(default=24, ge=6, le=60),
        tags_per_group: int = Query(default=12, ge=4, le=30),
        database: Path = Depends(require_reference_db),
    ) -> dict[str, object]:
        invalid_categories = set(category) - TAG_BROWSE_CATEGORIES
        if invalid_categories:
            raise ApiError(422, "invalid_request", f"未知标签分类：{sorted(invalid_categories)}")
        categories = set(category) or TAG_BROWSE_CATEGORIES
        group_meta = {name: (title, description) for name, title, description in TAG_BROWSE_GROUPS}
        with ReferenceDataStore(database) as store:
            featured = store.popular_tags(
                categories=categories,
                include_nsfw=include_nsfw,
                limit=featured_limit,
            )
            groups = store.browse_groups(
                [name for name, _title, _description in TAG_BROWSE_GROUPS],
                categories=categories,
                include_nsfw=include_nsfw,
                limit_per_group=tags_per_group,
            )
            other_groups = store.list_groups(
                excluded_names=[
                    *[name for name, _title, _description in TAG_BROWSE_GROUPS],
                    *([] if include_nsfw else TAG_SENSITIVE_GROUPS),
                ],
                categories=categories,
                include_nsfw=include_nsfw,
            )
            ungrouped = store.ungrouped_tags(
                categories=categories,
                safety="all" if include_nsfw else "safe",
                limit=12,
            )
            return {
                "featured": [_tag_search_item(row, match_kind="popular") for row in featured],
                "groups": [
                    {
                        **{key: value for key, value in group.items() if key != "items"},
                        "title": group_meta[group["name"]][0],
                        "description": group_meta[group["name"]][1],
                        "items": [_tag_search_item(row, match_kind="group") for row in group["items"]],
                    }
                    for group in groups
                ],
                "other_groups": other_groups,
                "ungrouped": {
                    **store.ungrouped_summary(categories=categories),
                    "items": [_tag_search_item(row, match_kind="ungrouped") for row in ungrouped["items"]],
                },
                "data_pack_id": store.pack_id,
            }

    @app.get(f"{API_PREFIX}/tags/ungrouped", dependencies=[Depends(require_session)])
    def ungrouped_tags(
        q: str = Query(default="", max_length=200),
        category: list[str] = Query(default=[]),
        safety: str = Query(default="safe", pattern=r"^(safe|nsfw|all)$"),
        heat: str = Query(default="all", pattern=r"^(all|100k|10k|1k|longtail)$"),
        sort: str = Query(default="popularity", pattern=r"^(popularity|name)$"),
        limit: int = Query(default=80, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        database: Path = Depends(require_reference_db),
    ) -> dict[str, object]:
        invalid_categories = set(category) - TAG_BROWSE_CATEGORIES
        if invalid_categories:
            raise ApiError(422, "invalid_request", f"未知标签分类：{sorted(invalid_categories)}")
        categories = set(category) or TAG_BROWSE_CATEGORIES
        with ReferenceDataStore(database) as store:
            result = store.ungrouped_tags(
                query=q,
                categories=categories,
                safety=safety,
                heat=heat,
                sort=sort,
                limit=limit,
                offset=offset,
            )
            items = [_tag_search_item(row, match_kind="ungrouped") for row in result["items"]]
            return {
                "summary": store.ungrouped_summary(),
                "items": items,
                "total": result["total"],
                "offset": offset,
                "limit": limit,
                "has_more": offset + len(items) < result["total"],
                "data_pack_id": store.pack_id,
            }

    @app.get(f"{API_PREFIX}/tag-groups/{{group_name}}", dependencies=[Depends(require_session)])
    def tag_group(
        group_name: str,
        q: str = Query(default="", max_length=200),
        category: list[str] = Query(default=[]),
        include_nsfw: bool = False,
        has_cn_name: bool = False,
        sort: str = Query(default="popularity", pattern=r"^(popularity|name)$"),
        limit: int = Query(default=80, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        database: Path = Depends(require_reference_db),
    ) -> dict[str, object]:
        invalid_categories = set(category) - TAG_BROWSE_CATEGORIES
        if invalid_categories:
            raise ApiError(422, "invalid_request", f"未知标签分类：{sorted(invalid_categories)}")
        categories = set(category) or TAG_BROWSE_CATEGORIES
        group_meta = {name: (title, description) for name, title, description in TAG_BROWSE_GROUPS}
        with ReferenceDataStore(database) as store:
            result = store.group_tags(
                group_name,
                query=q,
                categories=categories,
                include_nsfw=include_nsfw,
                has_cn_name=has_cn_name,
                sort=sort,
                limit=limit,
                offset=offset,
            )
            if result is None:
                raise ApiError(404, "tag_group_not_found", "标签分组不存在。", details={"name": group_name})
            title, description = group_meta.get(
                result["name"],
                (result["cn_name"] or str(result["name"]).replace("_", " "), "浏览这个分组中的全部本地标签"),
            )
            items = [_tag_search_item(row, match_kind="group") for row in result["items"]]
            return {
                "group": {
                    "id": result["id"],
                    "name": result["name"],
                    "cn_name": result["cn_name"],
                    "title": title,
                    "description": description,
                },
                "items": items,
                "total": result["total"],
                "offset": offset,
                "limit": limit,
                "has_more": offset + len(items) < result["total"],
                "data_pack_id": store.pack_id,
            }

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

    @app.get(f"{API_PREFIX}/artists/search", dependencies=[Depends(require_session)])
    def search_artists(
        q: str = Query(default="", max_length=200),
        sort: str = Query(default="popularity", pattern=r"^(popularity|name)$"),
        limit: int = Query(default=48, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        database: Path = Depends(require_reference_db),
    ) -> dict[str, object]:
        with ReferenceDataStore(database) as store:
            result = store.search_artists(q, sort=sort, limit=limit, offset=offset)
            items = result["items"]
            return {
                "summary": store.artist_summary(),
                "items": items,
                "total": result["total"],
                "offset": offset,
                "limit": limit,
                "has_more": offset + len(items) < result["total"],
                "data_pack_id": store.pack_id,
            }

    @app.post(f"{API_PREFIX}/artists/recommend", dependencies=[Depends(require_session)])
    def recommend_artists(
        payload: ArtistRecommendRequest,
        database: Path = Depends(require_reference_db),
    ) -> dict[str, object]:
        ranking = payload.ranking or _artist_ranking_from_database(app.state.v2_database)
        with ReferenceDataStore(database) as store:
            return {
                "items": store.recommend_artists(payload.tags, limit=payload.limit, ranking=ranking),
                "ranking": ranking,
                "data_pack_id": store.pack_id,
            }

    @app.get(f"{API_PREFIX}/artists/{{canonical_name:path}}", dependencies=[Depends(require_session)])
    def artist_detail(
        canonical_name: str,
        database: Path = Depends(require_reference_db),
    ) -> dict[str, object]:
        with ReferenceDataStore(database) as store:
            artist = store.get_artist(canonical_name)
            contexts = store.artist_contexts(canonical_name)
            if artist is None or contexts is None:
                raise ApiError(404, "artist_not_found", "画师标签不存在。", details={"name": canonical_name})
            dimension_counts: dict[str, int] = {}
            safe_count = 0
            nsfw_count = 0
            unknown_count = 0
            for item in contexts:
                for dimension in item["dimensions"]:
                    dimension_counts[dimension] = dimension_counts.get(dimension, 0) + 1
                if item["nsfw"] is True:
                    nsfw_count += 1
                elif item["nsfw"] is False:
                    safe_count += 1
                else:
                    unknown_count += 1
            return {
                **artist,
                "contexts": contexts,
                "dimension_counts": dimension_counts,
                "safety_summary": {
                    "safe_count": safe_count,
                    "nsfw_count": nsfw_count,
                    "unknown_count": unknown_count,
                },
                "analysis_note": "关联强度来自历史标签共现，不是 ANIMA 生成质量评分。",
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
            excluded_text = "，".join(
                item.text for item in payload.elements if item.state == IntentState.EXCLUDED
            )
            contains_cjk = _contains_cjk(positive_text)
            if payload.translated_text:
                translated_text = payload.translated_text
                translation_engine = "当前工作台译文"
            elif not contains_cjk:
                translated_text = positive_text
                translation_engine = "英文原文与本地标签索引"
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
                    suppressed_tags=payload.suppressed_tags,
                    include_scene_plan=contains_cjk,
                    explicit_excluded_text=excluded_text,
                )
            response = candidate_response(intent, payload.model_profile, database)
            if contains_cjk:
                scene_draft["back_translation"] = _back_translate_scene_plan(
                    translator,
                    translated_text,
                    negative=_candidate_negative_prompt(response),
                )
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
        evidence = _split_local_natural_evidence(payload.source_text)
        if payload.translated_text:
            translated_text = payload.translated_text
            translation_engine = "当前工作台译文"
        else:
            try:
                translated = translator.translate(evidence.positive_text, direction="zh_en")
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
                suppressed_tags=payload.suppressed_tags,
                fact_owners=payload.fact_owners,
                confirmed_relations=[item.model_dump() for item in payload.confirmed_relations],
                explicit_excluded_text=payload.excluded_text,
                evidence=evidence,
            )
            response = candidate_response(intent, payload.model_profile, database)
        scene_draft["back_translation"] = _back_translate_scene_plan(
            translator,
            translated_text,
            negative=_candidate_negative_prompt(response),
        )
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
                    limit=200,
                    ranking=ARTIST_RANKING_TAG_FIT,
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
        preferred_remote_profile_id = ""
        database = app.state.v2_database
        if database is not None:
            from anima_prompt_studio.repositories.sqlite_repository import SQLiteRepository
            repository = SQLiteRepository(database)
            try:
                preferred_remote_profile_id = str(repository.get_setting("last_remote_profile_id", "") or "")
            finally:
                repository.close()
        return {
            "items": queue.targets(),
            "preferred_remote_profile_id": preferred_remote_profile_id or None,
        }

    @app.put(
        f"{API_PREFIX}/settings/default-remote-profile",
        dependencies=[Depends(require_session)],
    )
    def set_default_remote_profile(
        payload: PreferredRemoteProfileRequest,
        database: Path = Depends(require_v2_settings_database),
    ) -> dict[str, object]:
        from anima_prompt_studio.repositories.sqlite_repository import SQLiteRepository

        repository = SQLiteRepository(database)
        try:
            try:
                profile = repository.get_remote_profile(payload.remote_profile_id)
            except KeyError as exc:
                raise ApiError(404, "remote_profile_not_found", "云主机配置不存在。") from exc
            if not profile.enabled:
                raise ApiError(409, "remote_profile_disabled", "不能将已停用的云主机设为默认连接。")
            repository.set_setting("last_remote_profile_id", profile.id)
            return {"remote_profile_id": profile.id}
        finally:
            repository.close()

    @app.get(f"{API_PREFIX}/settings/artist-ranking", dependencies=[Depends(require_session)])
    def get_artist_ranking(database: Path = Depends(require_v2_settings_database)) -> dict[str, object]:
        return {"ranking": _artist_ranking_from_database(database)}

    @app.put(f"{API_PREFIX}/settings/artist-ranking", dependencies=[Depends(require_session)])
    def set_artist_ranking(
        payload: ArtistRankingSettingsRequest,
        database: Path = Depends(require_v2_settings_database),
    ) -> dict[str, object]:
        from anima_prompt_studio.repositories.sqlite_repository import SQLiteRepository

        repository = SQLiteRepository(database)
        try:
            repository.set_setting(ARTIST_RANKING_SETTING, payload.ranking)
            return {"ranking": payload.ranking}
        finally:
            repository.close()

    @app.get(f"{API_PREFIX}/settings/remote-profiles", dependencies=[Depends(require_session)])
    def list_remote_profiles_for_settings(
        database: Path = Depends(require_v2_settings_database),
    ) -> dict[str, object]:
        """Expose V2 connection metadata without ever exposing a secret."""
        from anima_prompt_studio.repositories.sqlite_repository import SQLiteRepository
        from anima_prompt_studio.services.remote.credential_store import CredentialStore, CredentialStoreError

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
        f"{API_PREFIX}/settings/remote-profiles/{{profile_id}}/test-connection",
        dependencies=[Depends(require_session)],
    )
    def test_remote_profile_connection(
        profile_id: str,
        payload: RemoteConnectionTestRequest,
        database: Path = Depends(require_v2_settings_database),
    ) -> dict[str, object]:
        """Validate SSH authentication, the tunnel and the remote ComfyUI API."""
        from anima_prompt_studio.domain.execution_models import RemoteAuthType, RemoteCredentials
        from anima_prompt_studio.services.remote.comfy_client import ComfyUIClient
        from anima_prompt_studio.services.remote.credential_store import CredentialStore
        from anima_prompt_studio.services.remote.ssh_tunnel import SshTunnel

        profile = _get_v2_remote_profile(database, profile_id)
        if not profile.known_host_fingerprint.strip():
            raise ApiError(409, "ssh_host_key_unconfirmed", "请先检测并确认 SSH 主机指纹。")
        password = payload.password.get_secret_value() if payload.password is not None else ""
        if profile.auth_type == RemoteAuthType.PASSWORD and not password:
            try:
                password = CredentialStore().read_password(profile.id)
            except CredentialStoreError as exc:
                raise ApiError(503, "credential_store_unavailable", str(exc), retryable=True) from exc
        passphrase = payload.passphrase.get_secret_value() if payload.passphrase is not None else ""
        if profile.auth_type == RemoteAuthType.PASSWORD and not password:
            raise ApiError(409, "ssh_credentials_missing", "没有可用的 SSH 密码；请填写并保存密码后再测试。")
        tunnel = SshTunnel(profile)
        try:
            tunnel.open(RemoteCredentials(password=password, passphrase=passphrase))
            report = ComfyUIClient(tunnel.base_url).validate_environment()
        except Exception as exc:
            raise ApiError(502, "remote_connection_test_failed", f"远程连接测试失败：{exc}", retryable=True) from exc
        finally:
            tunnel.close()
        return {
            "ok": True,
            "devices": report.devices,
            "queue_running": report.queue_running,
            "queue_pending": report.queue_pending,
            "comfy_endpoint": f"{profile.comfy_host}:{profile.comfy_port}",
        }

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

    @app.post(f"{API_PREFIX}/gallery/assets/delete", dependencies=[Depends(require_session)])
    def delete_gallery_assets_permanently(payload: GalleryPathsRequest) -> dict[str, object]:
        service = app.state.gallery_service
        if service is None:
            raise ApiError(503, "gallery_not_configured", "画廊尚未连接 V2 图片目录。")
        return service.delete_permanently(payload.paths)

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

    @app.post(f"{API_PREFIX}/gallery/trash/delete", dependencies=[Depends(require_session)])
    def delete_gallery_trash(payload: GalleryPathsRequest) -> dict[str, object]:
        service = app.state.gallery_service
        if service is None:
            raise ApiError(503, "gallery_not_configured", "画廊尚未连接 V2 图片目录。")
        return service.delete_from_trash(payload.paths)

    @app.post(f"{API_PREFIX}/gallery/assets/reveal", dependencies=[Depends(require_session)])
    def reveal_gallery_asset(payload: GalleryPathsRequest) -> dict[str, object]:
        service = app.state.gallery_service
        if service is None:
            raise ApiError(503, "gallery_not_configured", "画廊尚未连接 V2 图片目录。")
        if not service.reveal(payload.paths[0]):
            raise ApiError(404, "gallery_asset_not_found", "无法在文件夹中显示图片。")
        return {"ok": True}

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
        if existing is None and profile.enabled:
            repository.set_setting("last_remote_profile_id", profile.id)

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
    if payload.relations or any(item.canonical_tag for item in payload.elements):
        return False
    return translator is not None or not _contains_cjk(payload.source_text)


def _contains_cjk(text: str) -> bool:
    return any("\u3400" <= character <= "\u9fff" for character in text)


@dataclass(frozen=True)
class _LocalLookupTerm:
    text: str
    origin: str
    start: int | None = None
    end: int | None = None


@dataclass(frozen=True)
class _LocalExclusionEvidence:
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class _LocalNaturalEvidence:
    positive_text: str
    exclusions: tuple[_LocalExclusionEvidence, ...]


_LOCAL_EXCLUSION_MARKER = re.compile(r"(?:不要|不需要|无需|避免|排除|禁止|去掉|移除|不含|不带)")
_LOCAL_CLAUSE = re.compile(r"[^，,。；;！!？?\n]+")
_LOCAL_EXCLUSION_CONCEPT_TAGS: dict[str, tuple[str, ...]] = {
    # “文字”是用户意图，不是 reference.db 中唯一的 canonical tag。
    # V3 将它透明展开成可审阅的负向标签，而不是伪装成一次精确命中。
    "文字": ("english_text", "speech_bubble", "signature", "artist_name", "character_name", "copyright_name", "web_address", "watermark"),
    "文本": ("english_text", "speech_bubble", "signature", "artist_name", "character_name", "copyright_name", "web_address", "watermark"),
}

_LOCAL_SOURCE_GLOSSARY: dict[str, str] = {
    "人鱼": "mermaid",
    "美人鱼": "mermaid",
}
_PROTECTED_IDENTITY_CATEGORIES = frozenset({"character", "copyright"})
_EXPLICIT_IDENTITY_MATCH_KINDS = frozenset({"canonical", "render"})

_LOCAL_FACT_TYPE_GROUPS: dict[IntentElementType, frozenset[str]] = {
    IntentElementType.SUBJECT: frozenset({"character_count", "groups", "people", "legendary_creatures"}),
    IntentElementType.APPEARANCE: frozenset({
        "body_parts", "breasts_tags", "ears_tags", "eyes_tags", "face_tags", "feet", "hair",
        "hair_color", "hair_styles", "hands", "makeup", "shoulders", "skin_color", "wings",
    }),
    IntentElementType.CLOTHING: frozenset({
        "accessories", "attire", "embellishment", "eyewear", "fashion_style", "handwear",
        "headwear", "legwear", "neck_and_neckwear", "patterns", "sleeves",
    }),
    IntentElementType.ACTION: frozenset({"dances", "gestures", "holding_tags", "posture", "sports", "verbs_and_gerunds"}),
    IntentElementType.SCENE: frozenset({
        "backgrounds", "fire", "flowers", "holidays_and_celebrations", "lighting", "locations",
        "real_world_locations", "water",
    }),
    IntentElementType.COMPOSITION: frozenset({"focus_tags", "image_composition"}),
    IntentElementType.STYLE: frozenset({"artistic_license", "fine_art_parody", "prints", "theme", "visual_aesthetic"}),
}


def _split_local_natural_evidence(source_text: str) -> _LocalNaturalEvidence:
    """Split explicit exclusions before translation or tag lookup.

    This is a deliberately small V3 evidence rule, not a resurrection of V2's
    prompt pipeline. It recognizes only explicit user language and preserves
    source spans so every exclusion remains reviewable.
    """

    exclusions: list[_LocalExclusionEvidence] = []
    removed_ranges: list[tuple[int, int]] = []
    for clause in _LOCAL_CLAUSE.finditer(source_text):
        marker = _LOCAL_EXCLUSION_MARKER.search(clause.group(0))
        if marker is None:
            continue
        clause_text = clause.group(0)
        tail = clause_text[marker.end():]
        content = tail.strip()
        if not content:
            continue
        content_start = clause.start() + marker.end() + (len(tail) - len(tail.lstrip()))
        content_end = content_start + len(content)
        exclusions.append(_LocalExclusionEvidence(content, content_start, content_end))
        removed_ranges.append((clause.start() + marker.start(), clause.end()))

    if not removed_ranges:
        return _LocalNaturalEvidence(source_text.strip(), ())

    pieces: list[str] = []
    cursor = 0
    for start, end in removed_ranges:
        pieces.append(source_text[cursor:start])
        cursor = end
    pieces.append(source_text[cursor:])
    positive_text = "".join(pieces)
    positive_text = re.sub(r"[，,。；;！!？?\s]+$", "", positive_text).strip()
    positive_text = re.sub(r"^[，,。；;！!？?\s]+", "", positive_text).strip()
    return _LocalNaturalEvidence(positive_text, tuple(exclusions))


def _local_natural_intent(
    source_text: str,
    translated_text: str,
    store: ReferenceDataStore,
    *,
    selected_tags: list[str],
    suppressed_tags: list[str] | None = None,
    fact_owners: dict[str, str] | None = None,
    confirmed_relations: list[dict[str, str]] | None = None,
    explicit_excluded_text: str = "",
    evidence: _LocalNaturalEvidence | None = None,
    include_scene_plan: bool = True,
) -> tuple[IntentDocument, dict[str, object]]:
    """Build a reviewable local draft without treating every index hit as required.

    Source-text index hits are deterministic local evidence.  Translation hits
    stay in the suggestion pool until the user explicitly selects them.  The
    complete translation remains a prose fallback so an empty tag match can
    never erase a natural-language draft.
    """
    evidence = evidence or _split_local_natural_evidence(source_text)
    matches = _local_index_matches(store, _local_lookup_terms(source_text, translated_text))
    source_candidates = filter_weak_meta_matches([
        match for match in matches
        if match.origin == "source" and not _match_in_exclusion_evidence(match, evidence.exclusions)
    ])
    excluded_candidates = filter_weak_meta_matches([
        match for match in matches
        if match.origin == "source" and _match_in_exclusion_evidence(match, evidence.exclusions)
    ])
    source_candidates, diverted_under_shot = divert_untrusted_composition_matches(source_candidates)
    excluded_candidates, diverted_under_shot_excluded = divert_untrusted_composition_matches(excluded_candidates)
    exclusion_span_tuples = [(item.text, item.start, item.end) for item in evidence.exclusions]
    phrase_occupiers = _composition_span_matches(composition_phrase_occupiers(source_text, exclusion_span_tuples))
    source_matches, ambiguous_source_terms = _confirmed_source_matches(
        source_candidates,
        extra_occupiers=phrase_occupiers,
    )
    source_matches = _merge_glossary_source_matches(evidence.positive_text, source_matches, store)
    source_matches, identity_matches = _divert_protected_identity_matches(source_matches, store)
    excluded_matches, ambiguous_exclusion_terms = _confirmed_source_matches(
        excluded_candidates,
        extra_occupiers=phrase_occupiers,
    )
    excluded_matches.extend(_local_exclusion_concept_matches(store, evidence.exclusions, ""))
    excluded_matches, identity_exclusion_matches = _divert_protected_identity_matches(excluded_matches, store)
    explicit_raw: list[_LocalIndexMatch] = []
    explicit_exclusion_matches: list[_LocalIndexMatch] = []
    if explicit_excluded_text.strip():
        explicit_raw = filter_weak_meta_matches(
            _local_index_matches(store, _local_lookup_terms(explicit_excluded_text, ""))
        )
        explicit_confirmed, explicit_ambiguous = _confirmed_source_matches(explicit_raw)
        explicit_exclusion_matches = [
            _LocalIndexMatch(
                text=item.text,
                origin="explicit_exclusion",
                canonical_tag=item.canonical_tag,
                match_kind=item.match_kind,
                post_count=item.post_count,
            )
            for item in explicit_confirmed
        ]
        explicit_exclusion_matches.extend(_local_exclusion_concept_matches(store, (), explicit_excluded_text))
        ambiguous_exclusion_terms.extend(explicit_ambiguous)
    explicit_exclusion_matches, explicit_identity_exclusions = _divert_protected_identity_matches(
        explicit_exclusion_matches,
        store,
    )
    identity_exclusion_matches = _dedupe_canonical_matches(
        [*identity_exclusion_matches, *explicit_identity_exclusions]
    )
    excluded_matches = _dedupe_canonical_matches([*excluded_matches, *explicit_exclusion_matches])
    for span in auto_exclude_gaze_spans(source_text, exclusion_span_tuples):
        mapped = _composition_auto_exclude_match(span, store)
        if mapped is not None:
            excluded_matches.append(mapped)
    excluded_matches = _dedupe_canonical_matches(excluded_matches)
    excluded_matches, leftover_exclusion_matches = _demote_partial_exclusion_matches(
        excluded_matches,
        evidence.exclusions,
        explicit_excluded_text,
    )
    suppressed = {item.strip().lower().replace(" ", "_") for item in (suppressed_tags or []) if item.strip()}
    suppressed_source_matches = [match for match in source_matches if match.canonical_tag in suppressed]
    suppressed_exclusion_matches = [match for match in excluded_matches if match.canonical_tag in suppressed]
    source_matches = [match for match in source_matches if match.canonical_tag not in suppressed]
    excluded_matches = [match for match in excluded_matches if match.canonical_tag not in suppressed]
    leftover_exclusion_matches = [match for match in leftover_exclusion_matches if match.canonical_tag not in suppressed]
    identity_exclusion_matches = [match for match in identity_exclusion_matches if match.canonical_tag not in suppressed]
    mapped_exclusion_texts = {match.text for match in excluded_matches}
    ambiguous_exclusion_terms = [item for item in ambiguous_exclusion_terms if item not in mapped_exclusion_texts]
    excluded_tags = {match.canonical_tag for match in excluded_matches}
    positive_exclusion_conflicts = {match.canonical_tag for match in source_matches} & excluded_tags
    source_matches = [match for match in source_matches if match.canonical_tag not in excluded_tags]
    selected = coerce_selected_composition([tag for tag in dict.fromkeys(selected_tags) if tag not in suppressed])
    if "looking_away" in {match.canonical_tag for match in source_matches} | set(selected):
        gaze_negative = _composition_tag_match("looking_at_viewer", "looking_at_viewer", store)
        if gaze_negative is not None:
            excluded_matches = _dedupe_canonical_matches([*excluded_matches, gaze_negative])
            excluded_tags = {match.canonical_tag for match in excluded_matches}
            source_matches = [match for match in source_matches if match.canonical_tag not in excluded_tags]
            selected = [tag for tag in selected if tag not in excluded_tags]
    requested_fact_owners = fact_owners or {}
    requested_relation_keys = {
        (str(item["source_entity_id"]), str(item["target_element_id"]), str(item["relation"]))
        for item in (confirmed_relations or [])
    }
    selected_set = set(selected)
    covering_exclusion_matches = [
        *excluded_matches,
        *identity_exclusion_matches,
        *leftover_exclusion_matches,
    ]
    identity_exclusion_matches = [
        match for match in identity_exclusion_matches if match.canonical_tag not in excluded_tags
    ]
    leftover_exclusion_matches = [
        match for match in leftover_exclusion_matches if match.canonical_tag not in excluded_tags
    ]
    elements: list[IntentElement] = []
    confirmed: list[dict[str, object]] = []
    exclusions: list[dict[str, object]] = []
    entities: list[dict[str, object]] = []

    for index, match in enumerate(source_matches, 1):
        element_id = f"e_local_confirmed_{index}"
        fact_type = _local_fact_type(store, match.canonical_tag)
        detail = store.get_tag(match.canonical_tag)
        entity_id = _local_entity_id(element_id) if detail is not None and _local_entity_anchor(detail) else None
        elements.append(IntentElement(
            id=element_id,
            original_text=match.text,
            canonical_tag=match.canonical_tag,
            entity_id=entity_id,
            type=fact_type,
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
            fact_type,
        ))
        if entity_id is not None:
            entities.append(_scene_entity_item(entity_id, element_id, match.text, match.canonical_tag, match.start, match.end))

    confirmed_tags = {match.canonical_tag for match in source_matches}
    for index, tag in enumerate(selected, 1):
        detail = store.get_tag(tag)
        if detail is None or tag in confirmed_tags or tag in excluded_tags:
            continue
        element_id = f"e_local_selected_{index}"
        rendered = str(detail["render_name"])
        label = _tag_cn_name(detail) or rendered
        fact_type = _local_fact_type_from_detail(detail)
        entity_id = _local_entity_id(element_id) if _local_entity_anchor(detail) else None
        elements.append(IntentElement(
            id=element_id,
            original_text=label,
            canonical_tag=tag,
            entity_id=entity_id,
            type=fact_type,
            state=IntentState.USER_SELECTED,
            confidence=1.0,
            provenance=ElementProvenance(kind=ProvenanceKind.MANUAL, detail="local_draft_user_selected"),
        ))
        confirmed.append(_scene_draft_item(
            element_id,
            label,
            tag,
            "user_selected",
            "用户从建议池确认加入",
            fact_type=fact_type,
            cn_name=_tag_cn_name(detail),
        ))
        if entity_id is not None:
            entities.append(_scene_entity_item(entity_id, element_id, label, tag))

    for index, match in enumerate(excluded_matches, 1):
        element_id = f"e_local_excluded_{index}"
        fact_type = _local_fact_type(store, match.canonical_tag)
        elements.append(IntentElement(
            id=element_id,
            original_text=match.text,
            canonical_tag=match.canonical_tag,
            type=fact_type,
            state=IntentState.EXCLUDED,
            confidence=1.0,
            source_span=SourceSpan(start=match.start, end=match.end) if match.start is not None and match.end is not None else None,
            provenance=ElementProvenance(kind=ProvenanceKind.EXACT, detail="local_source_explicit_exclusion"),
        ))
        exclusions.append(_scene_draft_item(
            element_id,
            match.text,
            match.canonical_tag,
            "source_excluded",
            (
                "广义排除概念展开；只进入负向提示词，可在生成前复核"
                if match.match_kind == "exclusion_concept"
                else "用户明确排除；不会进入正向提示词"
            ),
            match.start,
            match.end,
            fact_type,
        ))

    unresolved_exclusion_index = 0
    for item in evidence.exclusions:
        if _inline_exclusion_covered(item, covering_exclusion_matches):
            continue
        unresolved_exclusion_index += 1
        element_id = f"e_local_exclusion_unresolved_{unresolved_exclusion_index}"
        elements.append(IntentElement(
            id=element_id,
            original_text=item.text,
            type=IntentElementType.OTHER,
            state=IntentState.EXCLUDED,
            confidence=1.0,
            source_span=SourceSpan(start=item.start, end=item.end),
            provenance=ElementProvenance(kind=ProvenanceKind.EXACT, detail="local_source_unresolved_exclusion"),
        ))
        exclusions.append(_scene_draft_item(
            element_id,
            item.text,
            None,
            "source_excluded",
            "已识别为排除内容，但尚未找到可安全使用的本地标签",
            item.start,
            item.end,
        ))
    for phrase in _split_exclusion_phrases(explicit_excluded_text):
        if _explicit_exclusion_phrase_covered(phrase, covering_exclusion_matches, excluded_tags):
            continue
        unresolved_exclusion_index += 1
        element_id = f"e_local_exclusion_unresolved_{unresolved_exclusion_index}"
        elements.append(IntentElement(
            id=element_id,
            original_text=phrase,
            type=IntentElementType.OTHER,
            state=IntentState.EXCLUDED,
            confidence=1.0,
            provenance=ElementProvenance(kind=ProvenanceKind.EXACT, detail="local_source_unresolved_exclusion"),
        ))
        exclusions.append(_scene_draft_item(
            element_id,
            phrase,
            None,
            "source_excluded",
            "已识别为排除内容，但尚未找到可安全使用的本地标签",
        ))

    translation_candidates = [
        match
        for match in _confirmed_translation_matches(matches)
        if match.canonical_tag not in confirmed_tags
        and match.canonical_tag not in selected_set
        and match.canonical_tag not in suppressed
        and match.canonical_tag not in excluded_tags
    ]
    translation_matches = [
        match for match in translation_candidates if not _is_protected_identity_match(match, store)
    ]
    identity_matches = [
        match
        for match in [*identity_matches, *(
            item for item in translation_candidates if _is_protected_identity_match(item, store)
        )]
        if match.canonical_tag not in selected_set
        and match.canonical_tag not in suppressed
        and match.canonical_tag not in excluded_tags
    ]
    identity_suggestions = [
        _scene_draft_item(
            f"s_local_identity_{index}",
            match.text,
            match.canonical_tag,
            "identity_candidate",
            "匹配到角色或作品标签；名字可能很生僻，确认前请核对其英文 tag，点选后才会加入候选",
            match.start,
            match.end,
            _local_fact_type(store, match.canonical_tag),
        )
        for index, match in enumerate(_dedupe_canonical_matches(identity_matches), 1)
    ]
    identity_exclusion_suggestions = [
        _scene_draft_item(
            f"s_local_identity_exclusion_{index}",
            match.text,
            match.canonical_tag,
            "identity_exclusion",
            "匹配到角色或作品标签；不会自动写入负向提示词。请核对其英文 tag 后再点选排除",
            match.start,
            match.end,
            _local_fact_type(store, match.canonical_tag),
        )
        for index, match in enumerate(_dedupe_canonical_matches(identity_exclusion_matches), 1)
    ]
    leftover_exclusion_suggestions = [
        _scene_draft_item(
            f"s_local_exclusion_candidate_{index}",
            match.text,
            match.canonical_tag,
            "exclusion_candidate",
            "排除短语比该标签更具体，未自动把更宽的标签写入负向；点选后才会排除",
            match.start,
            match.end,
            _local_fact_type(store, match.canonical_tag),
        )
        for index, match in enumerate(_dedupe_canonical_matches(leftover_exclusion_matches), 1)
    ]
    confirmed_positive_tags = {match.canonical_tag for match in source_matches} | selected_set | excluded_tags | suppressed
    ambiguous_source_terms = [term for term in ambiguous_source_terms if term not in COMPOSITION_WEAK_META_TERMS]
    ambiguous_exclusion_terms = [term for term in ambiguous_exclusion_terms if term not in COMPOSITION_WEAK_META_TERMS]
    ambiguous_groups = _strip_composition_ambiguous_groups(
        _ambiguous_source_groups(
            source_candidates,
            store,
            confirmed_tags=confirmed_positive_tags,
        ),
        store,
        confirmed={match.canonical_tag for match in source_matches} | selected_set,
    )
    ambiguous_exclusion_groups = _strip_composition_ambiguous_groups(
        [
            {**group, "side": "excluded"}
            for group in _ambiguous_source_groups(
                [*excluded_candidates, *explicit_raw],
                store,
                confirmed_tags=excluded_tags | suppressed,
            )
            if group["text"] not in mapped_exclusion_texts and group["text"] not in COMPOSITION_WEAK_META_TERMS
        ],
        store,
        confirmed=excluded_tags,
    )
    composition_confirmed = {match.canonical_tag for match in source_matches if match.canonical_tag in COMPOSITION_CHIP_TAGS}
    composition_hinted = set(positive_composition_hints(evidence.positive_text, excluded_tags, composition_confirmed))
    if diverted_under_shot or diverted_under_shot_excluded:
        composition_hinted.add("from_below")
    crop_needed = clothing_crop_needed({match.canonical_tag for match in source_matches} | selected_set)
    composition_palette = build_composition_palette(
        confirmed_tags=composition_confirmed,
        selected_tags=selected,
        excluded_tags=excluded_tags,
        hinted_tags=composition_hinted,
        crop_needed=crop_needed,
    )
    composition_notes = prior_risk_notes(
        gaze_present=bool(({match.canonical_tag for match in source_matches} | selected_set) & {"looking_at_viewer", "looking_away"}),
        looking_away="looking_away" in ({match.canonical_tag for match in source_matches} | selected_set),
        looking_at_viewer_excluded="looking_at_viewer" in excluded_tags,
        crop_needed=crop_needed,
    )
    if include_scene_plan:
        composition_notes.extend(composition_prose_conflicts(
            translated_text,
            {match.canonical_tag for match in source_matches} | selected_set,
            excluded_tags,
        ))
    general_specific_conflicts = _general_specific_tag_conflicts(
        {match.canonical_tag for match in source_matches} | selected_set,
        excluded_tags,
    )
    leftover_suppressed = (
        _suppressed_terms_left_in_text(translated_text, suppressed, store)
        if include_scene_plan
        else []
    )
    suggestions = [
        *identity_suggestions,
        *identity_exclusion_suggestions,
        *leftover_exclusion_suggestions,
        *[
            _scene_draft_item(
                f"s_local_translation_{index}",
                match.text,
                match.canonical_tag,
                "translation_exact",
                "英文译文直接命中本地标签；需要确认后才会加入候选",
                fact_type=_local_fact_type(store, match.canonical_tag),
            )
            for index, match in enumerate(translation_matches[:12], 1)
        ],
    ]

    valid_entity_ids = {str(item["id"]) for item in entities}
    entity_source_ids = {str(item["source_element_id"]) for item in entities}
    assignable_types = {
        IntentElementType.APPEARANCE.value,
        IntentElementType.CLOTHING.value,
        IntentElementType.ACTION.value,
        IntentElementType.RELATION.value,
        IntentElementType.OBJECT.value,
    }
    element_indexes = {element.id: index for index, element in enumerate(elements)}
    stale_owner_assignments: list[str] = []
    for item in confirmed:
        item_id = str(item["id"])
        if item_id in entity_source_ids or str(item["fact_type"]) not in assignable_types:
            continue
        requested_owner = requested_fact_owners.get(item_id)
        if requested_owner:
            if requested_owner not in valid_entity_ids:
                stale_owner_assignments.append(item_id)
                continue
            item["owner_entity_id"] = requested_owner
            element_index = element_indexes.get(item_id)
            if element_index is not None:
                elements[element_index] = elements[element_index].model_copy(update={"entity_id": requested_owner})
        elif len(entities) == 1:
            item["suggested_owner_entity_id"] = str(entities[0]["id"])

    entity_by_id = {str(item["id"]): item for item in entities}
    relations: list[dict[str, object]] = []
    relation_edges: list[ConstraintEdge] = []
    available_relation_keys: set[tuple[str, str, str]] = set()
    for item in confirmed:
        if str(item["fact_type"]) != IntentElementType.CLOTHING.value or not item.get("owner_entity_id"):
            continue
        source_entity_id = str(item["owner_entity_id"])
        source_entity = entity_by_id.get(source_entity_id)
        if source_entity is None:
            continue
        target_element_id = str(item["id"])
        relation_key = (source_entity_id, target_element_id, RelationKind.WEARING.value)
        available_relation_keys.add(relation_key)
        state = "confirmed" if relation_key in requested_relation_keys else "suggested"
        relation_id = f"c_local_relation_{len(relations) + 1}"
        phrase = (
            f"{str(source_entity['canonical_tag']).replace('_', ' ')} wearing "
            f"{str(item['canonical_tag']).replace('_', ' ')}"
        )
        relations.append({
            "id": relation_id,
            "source_entity_id": source_entity_id,
            "target_element_id": target_element_id,
            "relation": RelationKind.WEARING.value,
            "state": state,
            "phrase": phrase,
            "reason": (
                "用户已确认实体与服装归属，并进一步确认穿着关系"
                if state == "confirmed"
                else "已确认服装归属；穿着关系仍需单独确认"
            ),
        })
        if state == "confirmed":
            relation_edges.append(ConstraintEdge(
                id=relation_id,
                source_element_id=str(source_entity["source_element_id"]),
                target_element_id=target_element_id,
                kind=ConstraintKind.RELATION,
                relation=RelationKind.WEARING,
                reason="用户在 Scene Draft 中确认穿着关系",
            ))
    stale_relation_assignments = requested_relation_keys - available_relation_keys

    unresolved: list[dict[str, object]] = []
    has_uncovered_source = _has_uncovered_source_evidence(evidence.positive_text, source_matches)
    if include_scene_plan and has_uncovered_source:
        unresolved.append(_scene_draft_item(
            "u_local_scene",
            evidence.positive_text,
            None,
            "unresolved",
            (
                "未找到可直接确认的中文标签；完整译文会保留为可编辑 prose baseline。"
                if not source_matches
                else "只有部分原文获得确定标签；其余人物、动作、关系、场景或风格继续保留在可编辑画面计划中。"
            ),
        ))

    if include_scene_plan and not source_matches and evidence.positive_text:
        elements.append(IntentElement(
            id="e_local_scene",
            original_text="local scene description",
            type=IntentElementType.SCENE,
            state=IntentState.REQUIRED,
            confidence=1.0,
            provenance=ElementProvenance(kind=ProvenanceKind.TRANSLATION, detail="local_prose_baseline"),
            notes=["local_prose_baseline"],
        ))
    elif include_scene_plan and has_uncovered_source:
        elements.append(IntentElement(
            id="e_local_unresolved_scene",
            original_text=evidence.positive_text,
            type=IntentElementType.SCENE,
            state=IntentState.REQUIRED,
            confidence=1.0,
            provenance=ElementProvenance(kind=ProvenanceKind.TRANSLATION, detail="local_partial_prose_evidence"),
            notes=["local_partial_prose_evidence"],
        ))

    intent = IntentDocument(
        source_text=source_text.strip(),
        source_language="zh" if _contains_cjk(source_text) else "en",
        translated_text=translated_text.strip(),
        scene_plan_en=(translated_text.strip() or None) if include_scene_plan else None,
        scene_negative_en=[match.canonical_tag.replace("_", " ") for match in excluded_matches],
        graph=ConstraintGraph(elements=elements, edges=relation_edges),
    )
    scene_draft = {
        "source_text": source_text.strip(),
        "translated_text": translated_text.strip(),
        "scene_plan_enabled": include_scene_plan,
        "entities": entities,
        "relations": relations,
        "confirmed": confirmed,
        "exclusions": exclusions,
        "suggestions": suggestions,
        "unresolved": unresolved,
        "suppressed": _suppressed_scene_items(
            [*suppressed_source_matches, *suppressed_exclusion_matches],
            suppressed - {match.canonical_tag for match in [*suppressed_source_matches, *suppressed_exclusion_matches]},
            store,
        ),
        "ambiguous": ambiguous_groups,
        "ambiguous_exclusions": ambiguous_exclusion_groups,
        "composition_palette": composition_palette,
        "composition_presets": composition_preset_snapshots(),
        "back_translation": {"text": "", "engine": "", "segments": [], "negative_text": ""},
        "risk_notes": [
            *composition_notes,
            *(
                [f"{', '.join(f'“{item}”' for item in ambiguous_source_terms[:3])} 可关联多条标签；已只确认唯一的主标签，其余请在待确认或一对多列表中点选。"]
                if ambiguous_source_terms
                else []
            ),
            *(
                [f"排除内容 {', '.join(f'“{item}”' for item in ambiguous_exclusion_terms[:3])} 可关联多条标签；请在排除一对多列表中点选后才会写入负向。"]
                if ambiguous_exclusion_terms
                else []
            ),
            *(
                ["部分排除内容尚未映射为本地标签；提交前请检查负向提示词。"]
                if any(item["canonical_tag"] is None for item in exclusions)
                else []
            ),
            *(
                ["已确认或已选择的标签与明确排除冲突；本次按排除优先，未加入正向候选。"]
                if positive_exclusion_conflicts or (selected_set & excluded_tags)
                else []
            ),
            *(
                [
                    "正向 "
                    + "、".join(f"{positive.replace('_', ' ')} / 负向 {negative.replace('_', ' ')}" for positive, negative in general_specific_conflicts[:3])
                    + " 存在包含关系；提交前请确认不会互相抵消。"
                ]
                if general_specific_conflicts
                else []
            ),
            *(
                [
                    "排除短语 "
                    + "、".join(f"“{item.text}”" for item in leftover_exclusion_matches[:3])
                    + " 只命中了更宽的标签，未自动写入负向，避免把更具体的描述升成整类排除。"
                ]
                if leftover_exclusion_matches
                else []
            ),
            *(
                ["部分属性归属引用了已不存在的实体；本次未应用，请重新确认。"]
                if stale_owner_assignments
                else []
            ),
            *(
                ["部分已确认关系不再对应当前实体与事实；本次未应用，请重新确认。"]
                if stale_relation_assignments
                else []
            ),
            *(
                [f"已移除的标签仍出现在英文画面计划中：{', '.join(leftover_suppressed[:4])}。请直接改英文，否则 Hybrid 仍可能带上它们。"]
                if leftover_suppressed
                else []
            ),
            *(
                ["发现疑似角色或作品标签，不会自动加入提示词。这些名字可能很生僻，请核对其英文 tag 后再点选。"]
                if identity_suggestions
                else []
            ),
            *(
                ["发现要从画面中排除的疑似角色或作品，不会自动写入负向提示词。请核对其英文 tag 后再点选。"]
                if identity_exclusion_suggestions
                else []
            ),
            "当前仅自动确认普通标签的唯一主名，或用户直接输入的英文 canonical；角色卡和作品标签需要单独确认。排除词会写入负向提示词。",
        ][:24],
    }
    _attach_cn_names(store, scene_draft)
    return intent, scene_draft


def _match_in_exclusion_evidence(
    match: _LocalIndexMatch,
    exclusions: tuple[_LocalExclusionEvidence, ...],
) -> bool:
    if match.start is None or match.end is None:
        return False
    return any(item.start <= match.start and match.end <= item.end for item in exclusions)


def _local_fact_type(store: ReferenceDataStore, canonical_tag: str) -> IntentElementType:
    detail = store.get_tag(canonical_tag)
    fallback = _local_fact_type_from_detail(detail) if detail is not None else IntentElementType.OTHER
    return composition_fact_type(canonical_tag, fallback)


def _local_fact_type_from_detail(detail: dict[str, object]) -> IntentElementType:
    category = str(detail.get("category_name") or "")
    if category == "character":
        return IntentElementType.CHARACTER
    if category == "copyright":
        return IntentElementType.CHARACTER
    group_names = {
        str(group.get("name") or "").removeprefix("tag_group:")
        for group in detail.get("groups", [])
        if isinstance(group, dict)
    }
    matches = [fact_type for fact_type, names in _LOCAL_FACT_TYPE_GROUPS.items() if group_names & names]
    return matches[0] if len(matches) == 1 else IntentElementType.OTHER


def _local_entity_anchor(detail: dict[str, object]) -> bool:
    if str(detail.get("category_name") or "") == "character":
        return True
    group_names = {
        str(group.get("name") or "").removeprefix("tag_group:")
        for group in detail.get("groups", [])
        if isinstance(group, dict)
    }
    return bool(group_names & {"people", "legendary_creatures"})


def _local_entity_id(element_id: str) -> str:
    return f"entity_{element_id.removeprefix('e_')}"


def _local_exclusion_concept_matches(
    store: ReferenceDataStore,
    inline_exclusions: tuple[_LocalExclusionEvidence, ...],
    explicit_excluded_text: str,
) -> list[_LocalIndexMatch]:
    matches: list[_LocalIndexMatch] = []
    sources: list[tuple[str, int | None]] = [
        (item.text, item.start) for item in inline_exclusions
    ]
    if explicit_excluded_text.strip():
        sources.append((explicit_excluded_text, None))
    for text, source_start in sources:
        for concept, canonical_tags in _LOCAL_EXCLUSION_CONCEPT_TAGS.items():
            offset = text.find(concept)
            if offset < 0:
                continue
            for canonical_tag in canonical_tags:
                detail = store.get_tag(canonical_tag)
                if detail is None:
                    continue
                start = source_start + offset if source_start is not None else None
                matches.append(_LocalIndexMatch(
                    text=concept,
                    origin="exclusion_concept",
                    canonical_tag=canonical_tag,
                    match_kind="exclusion_concept",
                    post_count=int(detail["post_count"]),
                    start=start,
                    end=start + len(concept) if start is not None else None,
                ))
    return matches


def _has_uncovered_source_evidence(
    positive_text: str,
    confirmed_matches: list[_LocalIndexMatch],
) -> bool:
    """Return whether meaningful source evidence remains outside exact matches.

    The check intentionally errs toward showing an unresolved draft.  A partial
    draft is safer than claiming a sentence is fully understood because two
    nouns happened to match the tag index.
    """

    remaining = positive_text
    for match in sorted(confirmed_matches, key=lambda item: -len(item.text)):
        remaining = remaining.replace(match.text, "", 1)
    remaining = re.sub(r"[，,。；;：:！!？?、()（）\[\]{}\s]+", "", remaining)
    remaining = re.sub(r"^(?:一个|一位|一名|的|和|与|及|在|从|向|穿|着|有)+", "", remaining)
    for term in sorted(COMPOSITION_WEAK_META_TERMS, key=len, reverse=True):
        remaining = remaining.replace(term, "")
    return bool(re.search(r"[\u3400-\u9fffA-Za-z0-9]", remaining))


def _composition_span_matches(spans: list) -> list[_LocalIndexMatch]:
    occupiers: list[_LocalIndexMatch] = []
    for span in spans:
        if span.start is None or span.end is None:
            continue
        occupiers.append(_LocalIndexMatch(
            text=span.text,
            origin="source",
            canonical_tag=span.canonical_tag or "composition_span",
            match_kind="cn_name",
            post_count=0,
            start=span.start,
            end=span.end,
        ))
    return occupiers


def _composition_auto_exclude_match(span: object, store: ReferenceDataStore) -> _LocalIndexMatch | None:
    canonical = str(getattr(span, "canonical_tag", "") or "")
    detail = store.get_tag(canonical)
    if detail is None:
        return None
    return _LocalIndexMatch(
        text=str(getattr(span, "text", canonical)),
        origin="source",
        canonical_tag=canonical,
        match_kind="cn_name",
        post_count=int(detail["post_count"]),
        start=getattr(span, "start", None),
        end=getattr(span, "end", None),
    )


def _composition_tag_match(canonical: str, text: str, store: ReferenceDataStore) -> _LocalIndexMatch | None:
    detail = store.get_tag(canonical)
    if detail is None:
        return None
    return _LocalIndexMatch(
        text=text,
        origin="explicit_exclusion",
        canonical_tag=canonical,
        match_kind="canonical",
        post_count=int(detail["post_count"]),
    )


def _strip_composition_ambiguous_groups(
    groups: list[dict[str, object]],
    store: ReferenceDataStore,
    *,
    confirmed: set[str],
) -> list[dict[str, object]]:
    cleaned: list[dict[str, object]] = []
    for group in groups:
        text = str(group.get("text") or "")
        if text in COMPOSITION_WEAK_META_TERMS:
            continue
        options = [option for option in list(group.get("options") or []) if isinstance(option, dict)]
        leftover = [str(option["canonical_tag"]) for option in options]
        groups_for = {
            tag: {
                str(item.get("name") or "").removeprefix("tag_group:")
                for item in (store.get_tag(tag) or {}).get("groups", [])
                if isinstance(item, dict)
            }
            for tag in leftover
        }
        primary = "close-up" if text == "特写" else None
        kept_tags = set(strip_focus_leftover_tags(primary, leftover, groups_for))
        if primary == "close-up":
            continue
        new_options = [option for option in options if option.get("canonical_tag") in kept_tags]
        if len(new_options) < 2:
            continue
        cleaned.append({**group, "options": new_options})
    return cleaned


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


_PRIMARY_MATCH_KINDS = frozenset({"canonical", "render", "alias", "cn_name"})


def _source_occurrence_map(
    matches: list[_LocalIndexMatch],
) -> dict[tuple[str, int | None, int | None], list[_LocalIndexMatch]]:
    by_occurrence: dict[tuple[str, int | None, int | None], list[_LocalIndexMatch]] = {}
    for match in matches:
        if match.origin == "source":
            by_occurrence.setdefault((match.text, match.start, match.end), []).append(match)
    return by_occurrence


def _primary_matches(candidates: list[_LocalIndexMatch]) -> tuple[list[_LocalIndexMatch], list[_LocalIndexMatch]]:
    unique = _unique_canonical_matches(candidates)
    primaries = _unique_canonical_matches([item for item in unique if item.match_kind in _PRIMARY_MATCH_KINDS])
    return unique, primaries


def _primary_occupying_spans(matches: list[_LocalIndexMatch]) -> list[_LocalIndexMatch]:
    """Spans whose Chinese text fully hits at least one tag primary name.

    These spans occupy their source range even when the hit is one-to-many.
    Nested shorter unique hits inside them are splitting byproducts, not more
    specific answers. Related-word ``cn_term`` hits do not occupy a span.
    """
    occupiers: list[_LocalIndexMatch] = []
    for (_text, start, end), candidates in _source_occurrence_map(matches).items():
        if start is None or end is None:
            continue
        _unique, primaries = _primary_matches(candidates)
        if primaries:
            occupiers.append(primaries[0])
    return occupiers


def _nested_in_longer_occupier(match: _LocalIndexMatch, occupiers: list[_LocalIndexMatch]) -> bool:
    if match.start is None or match.end is None:
        return False
    return any(
        occupier.start is not None
        and occupier.end is not None
        and len(occupier.text) > len(match.text)
        and _spans_overlap(match, occupier)
        for occupier in occupiers
    )


def _confirmed_source_matches(
    matches: list[_LocalIndexMatch],
    extra_occupiers: list[_LocalIndexMatch] | None = None,
) -> tuple[list[_LocalIndexMatch], list[str]]:
    """Resolve Chinese evidence without promoting every shared keyword to fact.

    Chinese search terms in the reference pack intentionally include broad related
    words.  For example, “天使” occurs on named characters, halos, statues and
    the generic ``angel`` tag.  Only a unique canonical/render/alias/CN primary
    name may be confirmed; broad ``cn_terms`` remain discovery metadata.

    A longer span that fully hits a primary name occupies its range even when
    that hit is ambiguous. Nested shorter unique names inside it are not
    confirmed automatically. Adjacent independent phrases may both survive.
    """
    occupiers = [*_primary_occupying_spans(matches), *(extra_occupiers or [])]
    resolved: list[_LocalIndexMatch] = []
    ambiguous_terms: list[str] = []
    for (text, _start, _end), candidates in _source_occurrence_map(matches).items():
        unique, primaries = _primary_matches(candidates)
        selected = primaries[0] if len(primaries) == 1 else None
        span = selected or candidates[0]
        nested = _nested_in_longer_occupier(span, occupiers)
        if len(unique) > 1 and not nested:
            ambiguous_terms.append(text)
        if selected is not None and not nested:
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


def _is_protected_identity_match(match: _LocalIndexMatch, store: ReferenceDataStore) -> bool:
    """Character/copyright tags auto-enter only when the user typed the English tag."""
    if match.match_kind in _EXPLICIT_IDENTITY_MATCH_KINDS:
        return False
    detail = store.get_tag(match.canonical_tag)
    return bool(detail) and str(detail.get("category_name") or "") in _PROTECTED_IDENTITY_CATEGORIES


def _divert_protected_identity_matches(
    matches: list[_LocalIndexMatch],
    store: ReferenceDataStore,
) -> tuple[list[_LocalIndexMatch], list[_LocalIndexMatch]]:
    kept: list[_LocalIndexMatch] = []
    diverted: list[_LocalIndexMatch] = []
    for match in matches:
        if _is_protected_identity_match(match, store):
            diverted.append(match)
        else:
            kept.append(match)
    return kept, diverted


_EXCLUSION_PHRASE_SPLIT = re.compile(r"[，,。；;！!？?\n]+")
_EXCLUSION_REMAINDER_NOISE = re.compile(r"[，,。；;：:！!？?、()（）\[\]{}\s和与及的]+")


def _split_exclusion_phrases(text: str) -> list[str]:
    return [part.strip() for part in _EXCLUSION_PHRASE_SPLIT.split(text) if part.strip()]


def _match_key(match: _LocalIndexMatch) -> tuple[str, str, int | None, int | None]:
    return (match.canonical_tag, match.text, match.start, match.end)


def _phrase_uncovered_remainder(phrase: str, matches: list[_LocalIndexMatch]) -> str:
    remaining = phrase
    for match in sorted(matches, key=lambda item: -len(item.text)):
        if match.text and match.text in remaining:
            remaining = remaining.replace(match.text, "", 1)
    return _EXCLUSION_REMAINDER_NOISE.sub("", remaining)


def _matches_for_inline_exclusion(
    item: _LocalExclusionEvidence,
    matches: list[_LocalIndexMatch],
) -> list[_LocalIndexMatch]:
    covering: list[_LocalIndexMatch] = []
    for match in matches:
        if match.start is not None and match.end is not None:
            if item.start <= match.start and match.end <= item.end:
                covering.append(match)
        elif match.origin != "source" and match.text and match.text in item.text:
            covering.append(match)
    return covering


def _matches_for_explicit_phrase(phrase: str, matches: list[_LocalIndexMatch]) -> list[_LocalIndexMatch]:
    return [
        match for match in matches
        if match.start is None and match.text and match.text in phrase
    ]


def _demote_partial_exclusion_matches(
    matches: list[_LocalIndexMatch],
    inline_exclusions: tuple[_LocalExclusionEvidence, ...],
    explicit_excluded_text: str,
) -> tuple[list[_LocalIndexMatch], list[_LocalIndexMatch]]:
    """Keep auto-exclusions only when the phrase is fully accounted for.

    Nested generics inside a more specific exclusion phrase, such as 袜子 in
    黑色袜子, must not silently become a whole-class negative tag.
    """
    demote_keys: set[tuple[str, str, int | None, int | None]] = set()
    leftover: list[_LocalIndexMatch] = []

    def consider(phrase: str, covering: list[_LocalIndexMatch]) -> None:
        if not covering or not _phrase_uncovered_remainder(phrase, covering):
            return
        for match in covering:
            key = _match_key(match)
            if key in demote_keys:
                continue
            demote_keys.add(key)
            leftover.append(match)

    for item in inline_exclusions:
        consider(item.text, _matches_for_inline_exclusion(item, matches))
    for phrase in _split_exclusion_phrases(explicit_excluded_text):
        consider(phrase, _matches_for_explicit_phrase(phrase, matches))
    kept = [match for match in matches if _match_key(match) not in demote_keys]
    return kept, leftover


def _inline_exclusion_covered(
    item: _LocalExclusionEvidence,
    matches: list[_LocalIndexMatch],
) -> bool:
    return bool(_matches_for_inline_exclusion(item, matches))


def _explicit_exclusion_phrase_covered(
    phrase: str,
    matches: list[_LocalIndexMatch],
    excluded_tags: set[str],
) -> bool:
    if phrase.lower().replace(" ", "_") in excluded_tags:
        return True
    return bool(_matches_for_explicit_phrase(phrase, matches)) or any(
        match.text and match.text in phrase for match in matches
    )


def _tag_tokens(tag: str) -> tuple[str, ...]:
    return tuple(part for part in tag.split("_") if part)


def _is_token_suffix(general: str, specific: str) -> bool:
    if general == specific:
        return False
    general_tokens = _tag_tokens(general)
    specific_tokens = _tag_tokens(specific)
    width = len(general_tokens)
    return bool(width) and len(specific_tokens) > width and specific_tokens[-width:] == general_tokens


def _general_specific_tag_conflicts(positives: set[str], negatives: set[str]) -> list[tuple[str, str]]:
    conflicts: list[tuple[str, str]] = []
    for positive in sorted(positives):
        for negative in sorted(negatives):
            if _is_token_suffix(negative, positive) or _is_token_suffix(positive, negative):
                conflicts.append((positive, negative))
    return conflicts


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
    return {"canonical": 0, "render": 1, "alias": 2, "cn_name": 3, "cn_term": 4, "exclusion_concept": 5}.get(match.match_kind, 6)


def _spans_overlap(left: _LocalIndexMatch, right: _LocalIndexMatch) -> bool:
    if None in {left.start, left.end, right.start, right.end}:
        return False
    return left.start < right.end and right.start < left.end


def _merge_glossary_source_matches(
    positive_text: str,
    source_matches: list[_LocalIndexMatch],
    store: ReferenceDataStore,
) -> list[_LocalIndexMatch]:
    extra: list[_LocalIndexMatch] = []
    existing = {match.canonical_tag for match in source_matches}
    for phrase, canonical in _LOCAL_SOURCE_GLOSSARY.items():
        if canonical in existing:
            continue
        detail = store.get_tag(canonical)
        if detail is None:
            continue
        start = 0
        while True:
            index = positive_text.find(phrase, start)
            if index < 0:
                break
            extra.append(_LocalIndexMatch(
                text=phrase,
                origin="source",
                canonical_tag=canonical,
                match_kind="cn_name",
                post_count=int(detail["post_count"]),
                start=index,
                end=index + len(phrase),
            ))
            start = index + len(phrase)
    if not extra:
        return source_matches
    merged: list[_LocalIndexMatch] = []
    for match in sorted(
        [*source_matches, *extra],
        key=lambda item: (-len(item.text), _match_priority(item), -(item.post_count), item.canonical_tag),
    ):
        if any(_spans_overlap(match, existing_match) for existing_match in merged):
            continue
        merged.append(match)
    merged.sort(key=lambda item: (item.start if item.start is not None else 0, -len(item.text), item.canonical_tag))
    return _dedupe_canonical_matches(merged)


def _ambiguous_source_groups(
    matches: list[_LocalIndexMatch],
    store: ReferenceDataStore,
    *,
    confirmed_tags: set[str],
) -> list[dict[str, object]]:
    occupiers = _primary_occupying_spans(matches)
    groups: list[dict[str, object]] = []
    seen_texts: set[str] = set()
    for (text, _start, _end), candidates in _source_occurrence_map(matches).items():
        if _nested_in_longer_occupier(candidates[0], occupiers):
            continue
        unique = [
            item for item in _unique_canonical_matches(candidates)
            if item.canonical_tag not in confirmed_tags
        ]
        if len(unique) < 2 or text in seen_texts:
            continue
        options: list[dict[str, object]] = []
        for item in unique[:8]:
            detail = store.get_tag(item.canonical_tag)
            if detail is None:
                continue
            options.append({
                "canonical_tag": item.canonical_tag,
                "render_name": str(detail["render_name"]),
                "cn_name": detail.get("cn_name"),
                "match_kind": item.match_kind,
                "post_count": item.post_count,
            })
        if len(options) < 2:
            continue
        seen_texts.add(text)
        groups.append({"text": text, "options": options})
        if len(groups) >= 20:
            break
    return groups


def _suppressed_scene_items(
    matches: list[_LocalIndexMatch],
    leftover_tags: set[str],
    store: ReferenceDataStore,
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, match in enumerate(matches, 1):
        if match.canonical_tag in seen:
            continue
        seen.add(match.canonical_tag)
        items.append(_scene_draft_item(
            f"e_local_suppressed_{index}",
            match.text,
            match.canonical_tag,
            "suppressed",
            "用户已移除；重编译不会自动恢复",
            match.start,
            match.end,
            _local_fact_type(store, match.canonical_tag),
        ))
    for index, tag in enumerate(sorted(leftover_tags), 1):
        if tag in seen:
            continue
        detail = store.get_tag(tag)
        text = str(detail["cn_name"] or detail["render_name"]) if detail else tag.replace("_", " ")
        items.append(_scene_draft_item(
            f"e_local_suppressed_manual_{index}",
            text,
            tag,
            "suppressed",
            "用户已移除；重编译不会自动恢复",
            fact_type=_local_fact_type_from_detail(detail) if detail else IntentElementType.OTHER,
        ))
    return items


def _suppressed_terms_left_in_text(
    translated_text: str,
    suppressed: set[str],
    store: ReferenceDataStore,
) -> list[str]:
    haystack = translated_text.lower()
    leftovers: list[str] = []
    for tag in suppressed:
        needles = {tag, tag.replace("_", " ")}
        detail = store.get_tag(tag)
        if detail is not None:
            render_name = str(detail.get("render_name") or "").lower()
            if render_name:
                needles.add(render_name)
            cn_name = str(detail.get("cn_name") or "").strip()
            if cn_name:
                needles.add(cn_name.lower())
        if any(needle and needle in haystack for needle in needles):
            leftovers.append(tag)
    return leftovers


def _back_translate_scene_plan(
    translator: object | None,
    english: str,
    *,
    negative: str = "",
) -> dict[str, object]:
    text = english.strip()
    empty = {"text": "", "engine": "", "segments": [], "negative_text": ""}
    if translator is None or not hasattr(translator, "translate"):
        return empty
    engine = ""
    full_text = ""
    segments: list[dict[str, str]] = []
    if text:
        try:
            full = translator.translate(text, direction="en_zh")
            full_text = full.translated_text.strip()
            engine = full.engine_name
        except (RuntimeError, ValueError):
            full_text = ""
        segments.append({"en": text, "zh": full_text})
    negative_text = ""
    if negative.strip():
        try:
            negative_result = translator.translate(negative.strip(), direction="en_zh")
            negative_text = negative_result.translated_text.strip()
            engine = engine or negative_result.engine_name
        except (RuntimeError, ValueError):
            negative_text = ""
    return {
        "text": full_text,
        "engine": engine,
        "segments": segments,
        "negative_text": negative_text,
    }


def _candidate_negative_prompt(response: dict[str, object]) -> str:
    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    first = candidates[0]
    if not isinstance(first, dict):
        return ""
    return str(first.get("negative_prompt") or "")


def _tag_cn_name(detail: dict[str, object] | None) -> str | None:
    if not detail:
        return None
    cn_name = str(detail.get("cn_name") or "").strip()
    if cn_name:
        return cn_name
    terms = detail.get("cn_terms") or []
    if isinstance(terms, list):
        for item in terms:
            value = str(item or "").strip()
            if value:
                return value
    return None


def _attach_cn_names(store: ReferenceDataStore, scene_draft: dict[str, object]) -> None:
    groups = [
        scene_draft.get("confirmed"),
        scene_draft.get("exclusions"),
        scene_draft.get("suggestions"),
        scene_draft.get("suppressed"),
    ]
    for group in groups:
        if not isinstance(group, list):
            continue
        for item in group:
            if not isinstance(item, dict) or item.get("cn_name"):
                continue
            tag = item.get("canonical_tag")
            if not isinstance(tag, str) or not tag:
                continue
            cn_name = _tag_cn_name(store.get_tag(tag))
            if cn_name:
                item["cn_name"] = cn_name
    for entity in scene_draft.get("entities") or []:
        if not isinstance(entity, dict) or not str(entity.get("label") or "").isascii():
            continue
        cn_name = _tag_cn_name(store.get_tag(str(entity.get("canonical_tag") or "")))
        if cn_name:
            entity["label"] = cn_name


def _scene_draft_item(
    item_id: str,
    text: str,
    canonical_tag: str | None,
    source: str,
    reason: str,
    source_start: int | None = None,
    source_end: int | None = None,
    fact_type: IntentElementType = IntentElementType.OTHER,
    cn_name: str | None = None,
) -> dict[str, object]:
    return {
        "id": item_id,
        "text": text,
        "canonical_tag": canonical_tag,
        "source": source,
        "fact_type": fact_type.value,
        "owner_entity_id": None,
        "suggested_owner_entity_id": None,
        "reason": reason,
        "source_start": source_start,
        "source_end": source_end,
        "cn_name": cn_name,
    }


def _scene_entity_item(
    entity_id: str,
    source_element_id: str,
    label: str,
    canonical_tag: str,
    source_start: int | None = None,
    source_end: int | None = None,
) -> dict[str, object]:
    return {
        "id": entity_id,
        "label": label,
        "canonical_tag": canonical_tag,
        "source_element_id": source_element_id,
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


def _tag_search_item(row: dict[str, object], *, match_kind: str = "search") -> dict[str, object]:
    return {
        "id": row["id"],
        "name": row["name"],
        "display_name": row["render_name"],
        "cn_name": row["cn_name"],
        "category": row["category_name"],
        "post_count": row["post_count"],
        "nsfw": row["nsfw"],
        "match": {"kind": match_kind, "score": None},
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
