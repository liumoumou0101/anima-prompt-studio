"""Session protected HTTP routes for the independent personal tag library."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, TypeVar

from fastapi import Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..core.personal_tags import CategoryWrite, CompositionItem, CompositionWrite, TagWrite
from ..storage.personal_tag_compositions import PersonalTagCompositions
from ..storage.personal_tag_import import ImportOptions, commit_import, export_bundle, preview_import
from ..storage.personal_tags import PersonalTagConflictError, PersonalTagNotFoundError, PersonalTagStore


PREFIX = "/api/v3/personal-tags"
MAX_IMPORT_BYTES = 50 * 1024 * 1024
T = TypeVar("T")


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TagUpdate(_Payload):
    value: TagWrite
    expected_revision: int = Field(ge=1)


class CategoryUpdate(_Payload):
    value: CategoryWrite
    expected_revision: int = Field(ge=1)


class CombinationUpdate(_Payload):
    value: CompositionWrite
    expected_revision: int = Field(ge=1)


class RevisionRequest(_Payload):
    expected_revision: int = Field(ge=1)


class DraftUpdate(_Payload):
    items: list[CompositionItem]
    expected_revision: int = Field(ge=0)


class MoveItem(_Payload):
    id: str = Field(min_length=1)
    revision: int = Field(ge=1)


class BulkMove(_Payload):
    items: list[MoveItem]
    category_id: str | None = None


class ImportOptionsRequest(_Payload):
    use_legacy_weights: bool = False
    fragment_ids: list[str] = Field(default_factory=list)


class ImportPreviewRequest(_Payload):
    document: dict
    options: ImportOptionsRequest = Field(default_factory=ImportOptionsRequest)


class ImportCommitRequest(ImportPreviewRequest):
    digest: str = Field(min_length=1)
    expected_library_revision: int = Field(ge=0)


def register_personal_tag_routes(app, workspace_db: Path, require_session):
    """Attach routes without opening or requiring the reference data pack."""
    from .app import ApiError

    store = PersonalTagStore(Path(workspace_db).with_name("personal-tags.db"))
    compositions = PersonalTagCompositions(store.path)
    app.state.personal_tag_store = store
    dependencies = [Depends(require_session)]

    def category_record(category_id: str):
        return next((row for row in [*store.list_categories(), *store.list_categories(trash=True)]
                     if row.id == category_id), None)

    def perform(action: Callable[[], T], current: Callable[[], object | None] | None = None) -> T:
        try:
            return action()
        except PersonalTagNotFoundError as exc:
            raise ApiError(404, "personal_tag_not_found", "记录不存在。") from exc
        except PersonalTagConflictError as exc:
            latest = current() if current else None
            if isinstance(latest, dict) and "revision" in latest:
                details = {"current_revision": latest["revision"], "current": jsonable_encoder(latest)}
            else:
                details = {"current_revision": latest.revision if hasattr(latest, "revision") else latest}
            if hasattr(latest, "model_dump"):
                details["current"] = latest.model_dump(mode="json")
            raise ApiError(409, "revision_conflict", str(exc), details=details) from exc
        except (ValueError, ValidationError, TypeError) as exc:
            raise ApiError(422, "invalid_request", str(exc)) from exc

    def revision_query(table: str, record_id: str) -> int | None:
        with store._connect() as db:
            row = db.execute(f"SELECT revision FROM {table} WHERE id=?", (record_id,)).fetchone()
        return row["revision"] if row else None

    def import_options(value: ImportOptionsRequest) -> ImportOptions:
        return ImportOptions(use_legacy_weights=value.use_legacy_weights,
                             fragment_ids=value.fragment_ids)

    async def import_payload(request: Request, model):
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                size = int(content_length)
            except ValueError as exc:
                raise ApiError(422, "invalid_request", "Content-Length 无效。") from exc
            if size < 0:
                raise ApiError(422, "invalid_request", "Content-Length 无效。")
            if size > MAX_IMPORT_BYTES:
                raise ApiError(413, "import_too_large", "导入文件不能超过 50 MiB。")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_IMPORT_BYTES:
                raise ApiError(413, "import_too_large", "导入文件不能超过 50 MiB。")
            body.extend(chunk)
        try:
            parsed = json.loads(body)
            return model.model_validate(parsed)
        except (ValueError, TypeError, UnicodeError, ValidationError) as exc:
            raise ApiError(422, "invalid_request", "导入请求 JSON 格式无效。") from exc

    @app.get(PREFIX + "/categories", dependencies=dependencies)
    def list_categories(trash: bool = False):
        return store.list_categories(trash=trash)

    @app.post(PREFIX + "/categories", dependencies=dependencies)
    def create_category(value: CategoryWrite):
        return perform(lambda: store.create_category(value))

    @app.put(PREFIX + "/categories/{category_id}", dependencies=dependencies)
    def update_category(category_id: str, payload: CategoryUpdate):
        return perform(lambda: store.update_category(category_id, payload.value,
                                                     expected_revision=payload.expected_revision),
                       lambda: category_record(category_id))

    @app.delete(PREFIX + "/categories/{category_id}", dependencies=dependencies)
    def delete_category(category_id: str, expected_revision: int = Query(ge=1)):
        return perform(lambda: store.set_category_deleted(category_id, True,
                                                          expected_revision=expected_revision),
                       lambda: category_record(category_id))

    @app.post(PREFIX + "/categories/{category_id}/restore", dependencies=dependencies)
    def restore_category(category_id: str, payload: RevisionRequest):
        return perform(lambda: store.set_category_deleted(category_id, False,
                                                          expected_revision=payload.expected_revision),
                       lambda: category_record(category_id))

    @app.get(PREFIX + "/tags", dependencies=dependencies)
    def list_tags(q: str = Query(default="", max_length=20_000), category_id: str | None = None,
                  include_descendants: bool = True, trash: bool = False,
                  offset: int = Query(default=0, ge=0), limit: int = Query(default=60, ge=1, le=200)):
        return perform(lambda: store.list_tags(q=q, category_id=category_id,
                                               include_descendants=include_descendants, trash=trash,
                                               offset=offset, limit=limit))

    @app.post(PREFIX + "/tags", dependencies=dependencies)
    def create_tag(value: TagWrite):
        return perform(lambda: store.create_tag(value))

    @app.get(PREFIX + "/tags/similar", dependencies=dependencies)
    def similar_tags(content: str = Query(min_length=1, max_length=20_000),
                     exclude_id: str | None = None, limit: int = Query(default=20, ge=1, le=200)):
        return perform(lambda: store.find_similar(content, exclude_id=exclude_id, limit=limit))

    @app.post(PREFIX + "/tags/bulk-move", dependencies=dependencies)
    def bulk_move(payload: BulkMove):
        items = [item.model_dump() for item in payload.items]
        try:
            return {"moved": store.move_tags(items, payload.category_id)}
        except PersonalTagConflictError as exc:
            latest = {item.id: revision_query("personal_tags", item.id) for item in payload.items}
            raise ApiError(409, "revision_conflict", str(exc), details={"current_revisions": latest}) from exc
        except PersonalTagNotFoundError as exc:
            raise ApiError(404, "personal_tag_not_found", "记录不存在。") from exc
        except (ValueError, ValidationError, TypeError) as exc:
            raise ApiError(422, "invalid_request", str(exc)) from exc

    @app.get(PREFIX + "/tags/{tag_id}", dependencies=dependencies)
    def get_tag(tag_id: str):
        return perform(lambda: store.get_tag(tag_id))

    @app.put(PREFIX + "/tags/{tag_id}", dependencies=dependencies)
    def update_tag(tag_id: str, payload: TagUpdate):
        return perform(lambda: store.update_tag(tag_id, payload.value,
                                                expected_revision=payload.expected_revision),
                       lambda: store.get_tag(tag_id))

    @app.delete(PREFIX + "/tags/{tag_id}", dependencies=dependencies)
    def delete_tag(tag_id: str, expected_revision: int = Query(ge=1)):
        return perform(lambda: store.set_tag_deleted(tag_id, True,
                                                     expected_revision=expected_revision),
                       lambda: store.get_tag(tag_id))

    @app.post(PREFIX + "/tags/{tag_id}/restore", dependencies=dependencies)
    def restore_tag(tag_id: str, payload: RevisionRequest):
        return perform(lambda: store.set_tag_deleted(tag_id, False,
                                                     expected_revision=payload.expected_revision),
                       lambda: store.get_tag(tag_id))

    @app.get(PREFIX + "/combinations", dependencies=dependencies)
    def list_combinations(trash: bool = False):
        return compositions.list(trash=trash)

    @app.post(PREFIX + "/combinations", dependencies=dependencies)
    def create_combination(value: CompositionWrite):
        return perform(lambda: compositions.create(value))

    @app.get(PREFIX + "/combinations/{combination_id}", dependencies=dependencies)
    def get_combination(combination_id: str):
        return perform(lambda: compositions.get(combination_id))

    @app.put(PREFIX + "/combinations/{combination_id}", dependencies=dependencies)
    def update_combination(combination_id: str, payload: CombinationUpdate):
        return perform(lambda: compositions.update(combination_id, payload.value,
                                                   expected_revision=payload.expected_revision),
                       lambda: compositions.get(combination_id))

    @app.delete(PREFIX + "/combinations/{combination_id}", dependencies=dependencies)
    def delete_combination(combination_id: str, expected_revision: int = Query(ge=1)):
        return perform(lambda: compositions.set_deleted(combination_id, True,
                                                       expected_revision=expected_revision),
                       lambda: compositions.get(combination_id))

    @app.post(PREFIX + "/combinations/{combination_id}/restore", dependencies=dependencies)
    def restore_combination(combination_id: str, payload: RevisionRequest):
        return perform(lambda: compositions.set_deleted(combination_id, False,
                                                       expected_revision=payload.expected_revision),
                       lambda: compositions.get(combination_id))

    @app.get(PREFIX + "/draft", dependencies=dependencies)
    def get_draft():
        return compositions.get_draft()

    @app.put(PREFIX + "/draft", dependencies=dependencies)
    def save_draft(payload: DraftUpdate):
        return perform(lambda: compositions.save_draft(payload.items,
                                                       expected_revision=payload.expected_revision),
                       compositions.get_draft)

    @app.post(PREFIX + "/imports/preview", dependencies=dependencies)
    async def preview(request: Request):
        payload = await import_payload(request, ImportPreviewRequest)
        return perform(lambda: preview_import(store, payload.document, import_options(payload.options)))

    @app.post(PREFIX + "/imports/commit", dependencies=dependencies)
    async def commit(request: Request):
        payload = await import_payload(request, ImportCommitRequest)
        return perform(lambda: commit_import(store, payload.document, import_options(payload.options),
                                             digest=payload.digest,
                                             expected_library_revision=payload.expected_library_revision),
                       lambda: store.library_revision)

    @app.get(PREFIX + "/export", dependencies=dependencies)
    def export():
        return JSONResponse(export_bundle(store),
                            headers={"Content-Disposition": 'attachment; filename="personal-tags.json"'})


__all__ = ["register_personal_tag_routes"]
