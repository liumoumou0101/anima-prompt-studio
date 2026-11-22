"""Literal source limits and conservative script checks for MOSS suggestions.

These do not infer a scene or replace semantic review. They prevent two losses
that a reviewer can overlook: translating the whole body and dropping an
explicit source prohibition. Scope stays intact because commas never split a
source sentence, and no source exclusion is moved into a global negative.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter


_PAIRS = {"“": "”", "‘": "’", "「": "」", "『": "』", '"': '"', "'": "'"}
_LIMIT = re.compile(
    r"不(?:要|得|能|允许|增加|新增|出现|包含|戴|穿|使用|改变|裁|画|加|多|可|要求)"
    r"|没有|无(?!论|法|比|意)|只能|只有|只许|只保留|只用|仅|禁止|严禁|必须|恰好"
    r"|\b(?:no|not|never|without|only|exactly|must|cannot|can't|don't)\b|\bdo\s+not\b"
    r"|ない|ません|なし|だけ|のみ|不可|必ず", re.I)
_META = re.compile(
    r"引号|名称|标注|称为|术语|强调|不要求.*(?:画|文字)|"
    r"\b(?:quotes?|quotation|labels?|terms?|names?)\b|"
    r"(?:do not|does not|not a).{0,20}(?:mean|request|instruction).{0,30}(?:text|print|letter)|"
    r"引用符|かぎ括弧|呼び名|強調|指示ではない", re.I)
_VISUAL_LIMIT = re.compile(
    r"不要(?!求)|禁止|严禁|不得|不允许|不增加|不新增|不出现|不包含|没有|只能|必须"
    r"|\b(?:no|never|without|cannot|can't|must)\b"
    r"|\bdo\s+not\b(?!\s+(?:mean|request|ask|indicate|refer))"
    r"|ません|禁止|不可|必ず|(?<!では)ない", re.I)
_SUBJECTLESS_LIMIT = re.compile(
    r"^(?:\b(?:no|not|never|without|only|cannot|can't|don't)\b|do\s+not\b"
    r"|不|没有|无|只能|只有|只许|只保留|只用|仅|禁止|严禁|必须)", re.I)


def _quoted_ranges(text: str) -> list[tuple[int, int]]:
    stack: list[tuple[int, str]] = []
    ranges = []
    for index, char in enumerate(text):
        if char in {'"', "'"} and index and text[index - 1] == "\\":
            continue
        if char == "'" and index and index + 1 < len(text) and text[index - 1].isalnum() and text[index + 1].isalnum():
            continue
        if stack and char == stack[-1][1]:
            start, _ = stack.pop()
            if not stack:
                ranges.append((start, index + 1))
        elif char in _PAIRS:
            stack.append((index, _PAIRS[char]))
    if stack:
        ranges.append((stack[0][0], len(text)))
    return ranges


def _unquoted(text: str) -> str:
    parts, cursor = [], 0
    for start, end in _quoted_ranges(text):
        parts.extend((text[cursor:start], " "))
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def _scripts(text: str) -> Counter:
    counts = Counter()
    for char in _unquoted(text):
        code = ord(char)
        if "LATIN" in unicodedata.name(char, "") and char.isalpha():
            counts["latin"] += 1
        elif 0x3040 <= code <= 0x30FF or 0x31F0 <= code <= 0x31FF or 0xFF66 <= code <= 0xFF9D:
            counts["kana"] += 1
        elif 0x3400 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF or 0x20000 <= code <= 0x3FFFF:
            counts["han"] += 1
        elif 0xAC00 <= code <= 0xD7AF or 0x1100 <= code <= 0x11FF:
            counts["hangul"] += 1
    return counts


def _source_script(counts: Counter) -> str:
    total = sum(counts.values())
    if total < 4:
        return "mixed"
    if counts["kana"] >= 2 and (counts["kana"] + counts["han"]) / total >= .55:
        return "japanese"
    if counts["han"] >= 3 and counts["han"] / total >= .55:
        return "han"
    if counts["latin"] >= 8 and counts["latin"] / total >= .7:
        return "latin"
    if counts["hangul"] >= 3 and counts["hangul"] / total >= .55:
        return "hangul"
    return "mixed"


def source_language_contract(source: str) -> dict[str, str]:
    script = _source_script(_scripts(source))
    instructions = {
        "latin": "Positive must stay in the original Latin-script language. For an English source, positive must be English, not Chinese. Keep intentional names and picture lettering unchanged.",
        "han": "positive正文必须保持原文中文，不要翻成英文；保留原有专名和图片文字。",
        "japanese": "positive正文必须保持原文日文，不要翻成中文或英文；保留原有专名和图片文字。",
        "hangul": "positive正文必须保持原文韩文，不要整段翻译；保留原有专名和图片文字。",
        "mixed": "positive保留原文有意混合的语言和专名，不要将整段统一翻译成另一种语言。",
    }
    return {"source_script": script, "positive_instruction": instructions[script], "notes_language": "free"}


def language_issue(source: str, positive: str) -> str | None:
    """Reject obvious script-family translation, allowing names and quoted text.

    Deliberately mixed or tiny sources are left to semantic review. Ratios are
    computed before any source constraints are copied into the candidate.
    """
    before, after = _scripts(source), _scripts(positive)
    source_total, output_total = sum(before.values()), sum(after.values())
    if source_total < 4 or output_total < 3:
        return None
    source_share = {key: before[key] / source_total for key in ("latin", "han", "kana", "hangul")}
    output_share = {key: after[key] / output_total for key in ("latin", "han", "kana", "hangul")}
    script = _source_script(before)
    if script == "japanese":
        if (output_share["kana"] + output_share["han"] < .55
                or output_share["kana"] < max(.08, source_share["kana"] * .25)):
            return "原文主体是日文，建议正文必须继续使用日文；保留其中的专名和图片文字，不要整段翻译。"
    elif script == "han":
        if output_share["han"] < .45 or output_share["kana"] > .2:
            return "原文主体是中文，建议正文必须继续以中文描述；不能仅在英文正文后附加少量汉字。"
    elif script == "latin":
        if output_share["latin"] < .55:
            return "原文主体使用拉丁字母，建议正文必须保留原语言，不要整段翻译成中文、日文或其他文字。"
    elif script == "hangul":
        if output_share["hangul"] < .45:
            return "原文主体是韩文，建议正文必须继续使用原语言，不要整段翻译。"
    return None


def _constraint_blocks(source: str) -> list[tuple[str, str]]:
    """Keep full restrictive sentences, including local ownership and exceptions."""
    ranges = iter(_quoted_ranges(source))
    quoted = next(ranges, None)
    pieces, start = [], 0
    for index, char in enumerate(source):
        while quoted and index >= quoted[1]:
            quoted = next(ranges, None)
        if quoted and quoted[0] <= index < quoted[1]:
            continue
        # A line break or semicolon may separate a person heading from that
        # person's restriction. Preserve that layout as one source block.
        boundary = char in "。！？!?" or (char == "." and (index + 1 == len(source) or source[index + 1].isspace()))
        if boundary:
            pieces.append((start, index + 1))
            start = index + 1
    pieces.append((start, len(source)))
    constraints = []
    for piece_index, (start, end) in enumerate(pieces):
        sentence = source[start:end].strip()
        unquoted = _unquoted(sentence)
        if not sentence or not _LIMIT.search(unquoted):
            continue
        if _META.search(unquoted) and not _VISUAL_LIMIT.search(unquoted):
            continue
        original_sentence = sentence
        if piece_index and _SUBJECTLESS_LIMIT.match(unquoted):
            previous_start = pieces[piece_index - 1][0]
            previous = _unquoted(source[previous_start:start])
            # "Left woman wears red. No hat." has the same scope as a titled
            # block. Carry its original preceding context, never a bare ban.
            if previous.strip() and not (_META.search(previous) and not _VISUAL_LIMIT.search(previous)):
                sentence = source[previous_start:end].strip()
        if not any(sentence == block for block, _ in constraints):
            constraints.append((sentence, original_sentence))
    return constraints


def constraint_sentences(source: str) -> list[str]:
    return [block for block, _ in _constraint_blocks(source)]


def preserve_constraints(source: str, positive: str) -> str:
    # When an independent restriction already survives verbatim, no repair is
    # needed. Recopying its preceding context could repeat actual sign lettering.
    missing = [block for block, original in _constraint_blocks(source)
               if original not in positive]
    return "\n".join([positive.rstrip(), *missing]) if missing else positive
