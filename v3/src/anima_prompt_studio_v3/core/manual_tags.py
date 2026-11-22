"""Explicit user tags; no dictionary lookup or model calls."""
from __future__ import annotations

import re
from uuid import uuid4


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


def _weighted_tag_key(value: str, known: set[str]) -> str | None:
    # Match only a complete tag entry, including nested ComfyUI emphasis. A
    # character name inside prose must never turn that whole sentence into a tag.
    for _ in range(32):
        match = re.fullmatch(r"\((.*?)(?::\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+))?\)|\[(.*)\]", value)
        if match is None:
            return None
        value = (match[1] if match[1] is not None else match[2]).strip()
        key = normalize_tag(value)
        if key in known:
            return key
    return None


def sync_tag_selection(positive: str, tags: list[str], previous: list[str], *, preserved: str = "") -> str:
    """Change explicit picker tokens without reformatting the reviewed body."""
    marker = "manualtagpreset" + uuid4().hex
    while marker in positive or marker in preserved:
        marker = "manualtagpreset" + uuid4().hex
    if preserved:
        positive = positive.replace(preserved, marker)
    current = {normalize_tag(tag) for tag in tags}
    known = current | {normalize_tag(tag) for tag in previous}
    entries, preferred = [], {}
    segments = list(re.finditer(r"([^,\n]*)([,\n]|$)", positive))
    for match in segments:
        value = match[1].strip()
        key = normalize_tag(value)
        weighted = key not in known
        if weighted:
            key = _weighted_tag_key(value, known)
        if key not in known:
            continue
        entry = (match, key, weighted)
        entries.append(entry)
        if key in current and (key not in preferred or weighted and not preferred[key][2]):
            preferred[key] = entry
    removed_starts = {match.start() for match, key, _ in entries
                      if key not in preferred or preferred[key][0].start() != match.start()}
    kept = [match for match in segments if match[1].strip() and match.start() not in removed_starts]
    removals = []
    for match, key, weighted in entries:
        if key in preferred and preferred[key][0].start() == match.start():
            continue
        start, end = match.span()
        has_prior = any(part.end() <= start for part in kept)
        has_following = any(part.start() >= end for part in kept)
        if not has_following:
            before = [part for part in kept if part.end() <= start]
            start = max((part.start() + len(part[1]) for part in before), default=0)
            end = len(positive)
        elif match[2] == "," and not has_prior and positive[end:end + 1] == " ":
            end += 1
        removals.append((start, end))
    cursor, body = 0, []
    for start, end in sorted(removals):
        if start > cursor:
            body.append(positive[cursor:start])
        cursor = max(cursor, end)
    body.append(positive[cursor:])
    text = "".join(body)
    # An unrelated picker edit must not undo an explicit manual text deletion.
    # Only the selections added by this edit own a new insertion. A subsequent
    # LLM rewrite still treats all selected tags as binding and reviews conflicts.
    old = {normalize_tag(tag) for tag in previous}
    missing = [tag for tag in tags if normalize_tag(tag) not in old and normalize_tag(tag) not in preferred]
    if missing:
        text = ", ".join(missing) + (", " + text if text else "")
    return text.replace(marker, preserved) if preserved else text


def render_manual_tags(positive: str, tags: list[str], previous: list[str]) -> str:
    # Only remove complete comma/newline-delimited tag entries. Never erase a
    # name embedded in a sentence, which could break ownership or negation.
    known = {normalize_tag(tag) for tag in tags + previous}
    parts = [part.strip() for part in re.split(r"[,\n]", positive)]
    current = {normalize_tag(tag) for tag in tags}
    keys = [normalize_tag(part) if normalize_tag(part) in known else _weighted_tag_key(part, known)
            for part in parts]
    # When every binding is already satisfied exactly once, there is nothing to
    # render. Preserve reviewed order, weights and whitespace, including on a
    # negative-only edit. Missing/obsolete/duplicate tags still use reconciliation.
    literal_bindings = all(any(key == normalize_tag(tag) and (part == tag or
        _weighted_tag_key(part, known) == key and tag in part) for part, key in zip(parts, keys)) for tag in tags)
    if literal_bindings and all(keys.count(key) == 1 for key in current) and not any(
            key in known - current for key in keys if key is not None):
        return positive
    weighted, body = {}, []
    for part in parts:
        key = normalize_tag(part)
        if key in known:
            continue
        key = _weighted_tag_key(part, known)
        if key is not None:
            weighted.setdefault(key, part)
        elif part:
            body.append(part)
    rendered = [weighted.get(normalize_tag(tag), tag) for tag in tags]
    return ", ".join([*rendered, *body]) if known else positive
