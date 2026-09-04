from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..data import ReferenceDataStore
from .literal import render_canonical_tag


DIRECT_ALGORITHM_VERSION = "direct-passthrough-v1"
DIRECT_BRIDGE_ORIGIN = "direct_prompt"

_TOKEN_SPLIT = re.compile(r"[,\n;，；]+")
_WRAP = re.compile(r"^[\(\[{<]+|[\)\]}>]+$")
_TRAILING_WEIGHT = re.compile(r":[\d.]+$")


class DirectPromptToken(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    original: str = Field(min_length=1)
    zh: str = Field(min_length=1)
    matched: bool
    canonical_tag: str | None = None
    render_name: str | None = None
    cn_name: str | None = None
    category_name: str | None = None


class DirectPromptInspection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    positive_prompt: str
    negative_prompt: str
    positive_tokens: tuple[DirectPromptToken, ...]
    negative_tokens: tuple[DirectPromptToken, ...]
    chinese_positive: str
    chinese_negative: str
    matched_count: int
    unmatched_count: int
    translation_engine: str
    algorithm: str = DIRECT_ALGORITHM_VERSION


def split_prompt_tokens(text: str) -> list[str]:
    """Keep comma-separated English tags intact. Do not n-gram split them."""

    return [item.strip() for item in _TOKEN_SPLIT.split(text or "") if item.strip()]


def inspect_direct_prompt(
    store: ReferenceDataStore,
    *,
    positive_prompt: str,
    negative_prompt: str = "",
    translator: object | None = None,
) -> DirectPromptInspection:
    positive_tokens = tuple(
        _inspect_token(store, token, translator) for token in split_prompt_tokens(positive_prompt)
    )
    negative_tokens = tuple(
        _inspect_token(store, token, translator) for token in split_prompt_tokens(negative_prompt)
    )
    engine = ""
    if translator is not None:
        engine = str(getattr(translator, "engine_name", "") or "")
        if not engine and hasattr(translator, "translate"):
            engine = "local_translation"
    matched = sum(1 for token in (*positive_tokens, *negative_tokens) if token.matched)
    unmatched = sum(1 for token in (*positive_tokens, *negative_tokens) if not token.matched)
    return DirectPromptInspection(
        positive_prompt=positive_prompt.strip(),
        negative_prompt=negative_prompt.strip(),
        positive_tokens=positive_tokens,
        negative_tokens=negative_tokens,
        chinese_positive=_join_zh(positive_tokens),
        chinese_negative=_join_zh(negative_tokens),
        matched_count=matched,
        unmatched_count=unmatched,
        translation_engine=engine,
    )


def _inspect_token(store: ReferenceDataStore, original: str, translator: object | None) -> DirectPromptToken:
    detail = _lookup_tag(store, original)
    if detail is not None:
        cn_name = _primary_cn_name(detail)
        return DirectPromptToken(
            original=original,
            zh=cn_name or original,
            matched=True,
            canonical_tag=str(detail["name"]),
            render_name=str(detail.get("render_name") or render_canonical_tag(detail["name"])),
            cn_name=cn_name,
            category_name=str(detail.get("category_name") or "") or None,
        )
    return DirectPromptToken(
        original=original,
        zh=_translate_unmatched(original, translator),
        matched=False,
    )


def _lookup_tag(store: ReferenceDataStore, token: str) -> dict[str, Any] | None:
    cleaned = _clean_token(token)
    if not cleaned:
        return None
    detail = store.get_tag(cleaned)
    if detail is not None:
        return detail
    underscored = cleaned.replace("-", "_")
    if underscored != cleaned:
        return store.get_tag(underscored)
    return None


def _clean_token(token: str) -> str:
    value = token.strip()
    if value.startswith("@"):
        return value
    value = _WRAP.sub("", value).strip()
    value = _TRAILING_WEIGHT.sub("", value).strip()
    return value


def _primary_cn_name(detail: dict[str, Any]) -> str | None:
    raw = str(detail.get("cn_name") or "").strip()
    if raw:
        return raw.split(",")[0].strip() or None
    terms = detail.get("cn_terms") or []
    if isinstance(terms, list):
        for item in terms:
            value = str(item or "").strip()
            if value:
                return value.split(",")[0].strip() or None
    return None


def _translate_unmatched(token: str, translator: object | None) -> str:
    if translator is None or not hasattr(translator, "translate"):
        return token
    try:
        result = translator.translate(token, direction="en_zh")
    except (RuntimeError, ValueError, TypeError):
        return token
    translated = str(getattr(result, "translated_text", "") or "").strip()
    return translated or token


def _join_zh(tokens: tuple[DirectPromptToken, ...]) -> str:
    return "，".join(token.zh for token in tokens)
