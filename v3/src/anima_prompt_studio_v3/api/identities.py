"""Classified identity lookup and explicit personal shortcuts; no model calls."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import Depends, Query
from pydantic import Field, field_validator

from ..core.requirements import ContractModel
from ..data.store import ReferenceDataStore
from ..storage.identity_preferences import IdentityPreferences, normalize_alias, normalize_name

IdentityKind = Literal["character", "series", "artist"]
CATEGORIES = {"character": "character", "series": "copyright", "artist": "artist"}


class IdentityValue(ContractModel):
    kind: IdentityKind
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value):
        normalized = normalize_name(value)
        if not normalized or any(char in value for char in "\n\r,，;；"):
            raise ValueError("请填写单个有效 tag。")
        return normalized


class FavoriteRequest(IdentityValue):
    enabled: bool


class AliasRequest(IdentityValue):
    alias: str = Field(min_length=1, max_length=200)


class DeleteAliasRequest(ContractModel):
    kind: IdentityKind
    alias: str = Field(min_length=1, max_length=200)


class UsedRequest(ContractModel):
    kind: IdentityKind
    names: list[str] = Field(max_length=50)

    @field_validator("names")
    @classmethod
    def validate_names(cls, values):
        return [IdentityValue(kind="character", name=value).name for value in values]


def register_identity_routes(app, reference_db: Path, workspace_db: Path, require_session):
    personal = IdentityPreferences(Path(workspace_db).with_name("identity-preferences.db"))
    app.state.identity_preferences = personal
    dependencies = [Depends(require_session)]
    prefix = "/api/v3/identities"

    def enrich(store, item, kind, preferences, model_profile_id):
        name = str(item["name"])
        related = []
        if kind == "character" and item.get("id") is not None:
            # Co-occurrence is only a suggestion: crossovers and multi-series tags exist.
            for series in store.related_tags([name], categories={"copyright"}, limit=3):
                related.append({"name": series["name"], "cn_name": series["cn_name"],
                                "render_name": series["render_name"], "source": "data_pack_cooccurrence",
                                "cooc_count": series["cooc_count"]})
        return {**item, "kind": kind,
            "favorite": any(row["name"] == name for row in preferences["favorites"]),
            "user_aliases": [row["alias"] for row in preferences["aliases"] if row["name"] == name],
            "related_series": related,
            "knowledge": {"status": "unknown", "model_profile_id": model_profile_id,
                          "reason": "词库收录与投稿量不能证明当前模型认识该角色或画师，尚无逐项生成验证。"}}

    def resolve(store, name, kind):
        if kind == "artist":
            artist = store.get_artist(name)
            if artist:
                return {**artist, "cn_name": None, "category_name": "artist"}
        item = store.get_tag(name)
        if item is not None and item["category_name"] != CATEGORIES[kind]:
            item = None
        return item or {"id": None, "name": name, "render_name": name.replace("_", " "),
                       "cn_name": None, "category_name": CATEGORIES[kind], "post_count": None,
                       "match_kind": "custom", "match_source": "user"}

    def validate_category(store, name, kind):
        if kind == "artist" and store.get_artist(name) is not None:
            return str(store.get_artist(name)["name"])
        detail = store.get_tag(name)
        if detail is not None and detail["category_name"] != CATEGORIES[kind]:
            from .app import ApiError
            raise ApiError(422, "invalid_request", "该 tag 在词库中属于其他分类，请在对应栏选择。")
        return str(detail["name"]) if detail else name

    @app.get(prefix + "/search", dependencies=dependencies)
    def search(kind: IdentityKind, q: str = Query(default="", max_length=200),
               model_profile_id: str | None = Query(default=None, max_length=200), limit: int = Query(default=12, ge=1, le=30)):
        preferences = personal.list(kind)
        with ReferenceDataStore(reference_db) as store:
            items = store.search_identities(q, category=CATEGORIES[kind], limit=limit)
            by_name = {item["name"]: item for item in items}
            normalized = normalize_alias(q.lstrip("@"))
            if normalized:
                for alias in preferences["aliases"]:
                    if not alias["normalized_alias"].startswith(normalized):
                        continue
                    rank = 2 if alias["normalized_alias"] == normalized else 12
                    previous = by_name.get(alias["name"])
                    if previous is not None and previous.get("match_rank", 99) <= rank:
                        continue
                    by_name[alias["name"]] = {**resolve(store, alias["name"], kind), "match_rank": rank,
                        "match_kind": "user_alias", "match_text": alias["alias"], "match_source": "user"}
            ordered = sorted(by_name.values(), key=lambda item: (item.get("match_rank", 99),
                            -(item.get("post_count") or 0), item["name"]))[:limit]
            return {"items": [enrich(store, item, kind, preferences, model_profile_id) for item in ordered],
                    "data_pack_id": store.pack_id, "knowledge_status": "unknown"}

    @app.get(prefix + "/preferences", dependencies=dependencies)
    def preferences(kind: IdentityKind, model_profile_id: str | None = Query(default=None, max_length=200)):
        values = personal.list(kind)
        with ReferenceDataStore(reference_db) as store:
            return {**values, **{key: [enrich(store, resolve(store, row["name"], kind), kind, values, model_profile_id)
                                     for row in values[key]] for key in ("recent", "favorites")}}

    @app.post(prefix + "/used", dependencies=dependencies)
    def used(payload: UsedRequest):
        with ReferenceDataStore(reference_db) as store:
            names = [validate_category(store, name, payload.kind) for name in payload.names]
        personal.use(payload.kind, names)
        return {"saved": True}

    @app.put(prefix + "/favorite", dependencies=dependencies)
    def favorite(payload: FavoriteRequest):
        with ReferenceDataStore(reference_db) as store:
            name = validate_category(store, payload.name, payload.kind)
        personal.favorite(payload.kind, name, payload.enabled)
        return {"saved": True}

    @app.put(prefix + "/alias", dependencies=dependencies)
    def alias(payload: AliasRequest):
        with ReferenceDataStore(reference_db) as store:
            name = validate_category(store, payload.name, payload.kind)
        try:
            personal.save_alias(payload.kind, name, payload.alias)
        except ValueError as error:
            from .app import ApiError
            raise ApiError(409, "identity_alias_conflict", str(error)) from error
        return {"saved": True, "source": "user"}

    @app.delete(prefix + "/alias", dependencies=dependencies)
    def delete_alias(payload: DeleteAliasRequest):
        personal.delete_alias(payload.kind, payload.alias)
        return {"saved": True}
