"""Shared Chinese/English negation detection.

Substring triggers such as ``裸体`` and ``看镜头`` must not fire inside
``没有裸体`` / ``没有看镜头``.  Every matcher uses this module so the
rule stays in one place.
"""
from __future__ import annotations

import re

# Longer tokens first so 没有 wins over 没 and 不要 wins over 不.
_ZH_NEGATORS = ("不要", "不是", "并非", "没有", "没", "未", "无", "别", "不")
_ZH_NEGATOR_RE = "|".join(map(re.escape, _ZH_NEGATORS))
_ZH_PREFIX_WINDOW = 8
_ZH_GAP = 6

_EN_NEGATOR_RE = r"(?:\bwithout\b|\bno\b|\bnot\b|n't\b|\bnever\b|\binstead of\b)"
_EN_PREFIX_WINDOW = 45
_EN_GAP = 35


def span_negated_zh(text: str, start: int) -> bool:
    """True when a Chinese negation particle immediately precedes ``start``."""
    if start < 0 or start > len(text):
        return False
    prefix = text[max(0, start - _ZH_PREFIX_WINDOW):start]
    return re.search(rf"(?:{_ZH_NEGATOR_RE})[^，。；！？]{{0,{_ZH_GAP}}}$", prefix) is not None


def phrase_starts_zh(text: str, phrase: str) -> list[int]:
    if not phrase:
        return []
    starts: list[int] = []
    start = text.find(phrase)
    while start >= 0:
        starts.append(start)
        start = text.find(phrase, start + 1)
    return starts


def phrase_has_unnegated_zh(text: str, phrase: str) -> bool:
    """True when ``phrase`` occurs at least once without a negation prefix."""
    return any(not span_negated_zh(text, start) for start in phrase_starts_zh(text, phrase))


def phrase_all_negated_zh(text: str, phrase: str) -> bool:
    starts = phrase_starts_zh(text, phrase)
    return bool(starts) and all(span_negated_zh(text, start) for start in starts)


def phrase_any_negated_zh(text: str, phrase: str) -> bool:
    return any(span_negated_zh(text, start) for start in phrase_starts_zh(text, phrase))


def span_negated_en(text: str, start: int) -> bool:
    """True when an English negator immediately precedes ``start``."""
    if start < 0 or start > len(text):
        return False
    prefix = text.lower()[max(0, start - _EN_PREFIX_WINDOW):start]
    return re.search(rf"{_EN_NEGATOR_RE}[^.!?,;]{{0,{_EN_GAP}}}$", prefix) is not None


def phrase_negated_en(text: str, phrase: str) -> bool:
    """True when any occurrence of the phrase's last word is negated.

    Matches the historical tag-matcher rule so ``without a hat`` still
    blocks the ``hat`` tag.
    """
    words = re.findall(r"[a-z0-9]+", phrase.lower())
    if not words:
        return False
    target = words[-1]
    lower = text.lower()
    return any(
        span_negated_en(lower, match.start())
        for match in re.finditer(rf"\b{re.escape(target)}\b", lower)
    )
