"""Value contracts for the independent personal tag library."""

from __future__ import annotations

import math
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_search(value: str) -> str:
    """Build a search key without changing the stored source text."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().replace("_", " ").split())


def _text(value: str, maximum: int, label: str) -> str:
    if not value.strip() or len(value) > maximum:
        raise ValueError(f"{label} must be nonempty and at most {maximum} characters")
    return value


def _weight(value: float) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or not (0.1 <= value <= 2.0) or abs(value * 20 - round(value * 20)) > 1e-8:
        raise ValueError("weight must be between 0.1 and 2.0 in steps of 0.05")
    return value


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TagWrite(_Model):
    display_name: str
    content: str
    aliases: list[str] = Field(default_factory=list)
    category_id: str | None = None
    kind: Literal["tag", "fragment"] = "tag"
    notes: str = ""
    default_weight: float = 1.0

    @field_validator("display_name")
    @classmethod
    def name_valid(cls, value: str) -> str:
        return _text(value, 200, "display_name")

    @field_validator("content")
    @classmethod
    def content_valid(cls, value: str) -> str:
        return _text(value, 20_000, "content")

    @field_validator("aliases")
    @classmethod
    def aliases_valid(cls, value: list[str]) -> list[str]:
        for alias in value:
            _text(alias, 200, "alias")
        return value

    @field_validator("notes")
    @classmethod
    def notes_valid(cls, value: str) -> str:
        if len(value) > 4_000:
            raise ValueError("notes must be at most 4000 characters")
        return value

    @field_validator("default_weight")
    @classmethod
    def weight_valid(cls, value: float) -> float:
        return _weight(value)


class TagRecord(TagWrite):
    id: str
    revision: int
    created_at: str
    updated_at: str
    deleted_at: str | None = None
    source_key: str | None = None
    source_id: str | None = None
    source_metadata: dict = Field(default_factory=dict)
    needs_review: list[str] = Field(default_factory=list)


class CategoryWrite(_Model):
    name: str
    parent_id: str | None = None
    position: int = 0

    @field_validator("name")
    @classmethod
    def name_valid(cls, value: str) -> str:
        return _text(value, 200, "name")


class CategoryRecord(CategoryWrite):
    id: str
    revision: int
    created_at: str
    updated_at: str
    deleted_at: str | None = None
    source_key: str | None = None
    source_id: str | None = None
    source_metadata: dict = Field(default_factory=dict)
    needs_review: list[str] = Field(default_factory=list)


class CompositionItem(_Model):
    id: str
    source_tag_id: str | None = None
    display_name: str
    content: str
    kind: Literal["tag", "fragment"]
    polarity: Literal["positive", "negative"]
    weight: float = 1.0

    @field_validator("id", "display_name")
    @classmethod
    def name_valid(cls, value: str) -> str:
        return _text(value, 200, "item name")

    @field_validator("content")
    @classmethod
    def content_valid(cls, value: str) -> str:
        return _text(value, 20_000, "content")

    @field_validator("weight")
    @classmethod
    def weight_valid(cls, value: float) -> float:
        return _weight(value)


class CompositionWrite(_Model):
    name: str
    items: list[CompositionItem]

    @field_validator("name")
    @classmethod
    def name_valid(cls, value: str) -> str:
        return _text(value, 200, "name")

    @field_validator("items")
    @classmethod
    def items_valid(cls, value: list[CompositionItem]) -> list[CompositionItem]:
        return validate_composition_items(value)


def validate_composition_items(items: list[CompositionItem]) -> list[CompositionItem]:
    if len(items) > 300:
        raise ValueError("composition cannot exceed 300 items")
    lengths = {"positive": 0, "negative": 0}
    counts = {"positive": 0, "negative": 0}
    for item in items:
        extra = 0 if item.weight == 1.0 else 3 + len(f"{item.weight:g}")
        lengths[item.polarity] += len(item.content) + extra + (2 if counts[item.polarity] else 0)
        counts[item.polarity] += 1
        if lengths[item.polarity] > 20_000:
            raise ValueError(f"{item.polarity} output cannot exceed 20000 characters")
    return items


class CompositionRecord(CompositionWrite):
    id: str
    revision: int
    created_at: str
    updated_at: str
    deleted_at: str | None = None
