"""Explicit user tags; no dictionary lookup or model calls."""
from __future__ import annotations

import re


def normalize_tag(value: str, *, artist: bool = False) -> str:
    value = value.strip()
    if artist:
        value = value.lstrip("@").strip()
    return " ".join(value.lower().replace("_", " ").replace("\\(", "(").replace("\\)", ")").split())


def literal_tag(value: str) -> str:
    return value.replace("(", "\\(").replace(")", "\\)")


def declared_tags(requirements: dict | None) -> list[str]:
    layers = (requirements or {}).get("layers", {})
    subject = layers.get("subject", {})
    result = [normalize_tag(tag) for key in ("character_tags", "series_tags", "general_tags")
              for tag in subject.get(key, [])]
    result += ["@" + normalize_tag(tag, artist=True) for key in ("artists", "manual_artist_tags")
               for tag in layers.get("style", {}).get(key, [])]
    return list(dict.fromkeys(literal_tag(tag) for tag in result if tag and tag != "@"))


def render_manual_tags(positive: str, tags: list[str], previous: list[str]) -> str:
    # Only remove complete comma/newline-delimited tag entries. Never erase a
    # name embedded in a sentence, which could break ownership or negation.
    known = {normalize_tag(tag) for tag in tags + previous}
    parts = [part.strip() for part in re.split(r"[,\n]", positive)]
    body = ", ".join(part for part in parts if part and normalize_tag(part) not in known)
    return ", ".join([*tags, body] if body else tags) if known else positive
