"""Bounded dictionary phrase recognition, deliberately not semantic prompt analysis."""
from __future__ import annotations

import re

from ..data.store import ReferenceDataStore

MAX_PHRASE_WORDS = 12
MAX_PHRASE_CHARS = 200
WORDS = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*|[()]", re.UNICODE)


def normalized(text: str) -> str:
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    return re.sub(r"\s+", "_", text.strip().lower())


def prompt_tag_matches(store: ReferenceDataStore, prompt: str, *, limit=50):
    limit = min(50, max(1, limit))
    # Preserve positions while masking directive segments. Artist clauses end at
    # the same explicit delimiters used by the prompt editor, not guessed names.
    text = re.sub(r"<(?:lora|lyco):[^>]*(?:>|$)|@[^,;，；\n\r]+", lambda match: " " * len(match[0]), prompt, flags=re.I)
    text = text.replace("_", " ").replace("\\(", " (").replace("\\)", " )")
    candidates = {}
    for clause in re.finditer(r"[^,;，；.!?。！？\n\r]+", text):
        words = list(WORDS.finditer(clause[0]))
        for start in range(len(words)):
            if words[start][0] in {"(", ")"}:
                continue
            for end in range(start, min(len(words), start + MAX_PHRASE_WORDS)):
                fragment = clause[0][words[start].start():words[end].end()]
                if len(fragment) > MAX_PHRASE_CHARS:
                    break
                # Weights and unrelated syntax cannot join words into a tag.
                if re.search(r"[^\w\s()'\-]", fragment):
                    continue
                key = normalized(fragment)
                span = (clause.start() + words[start].start(), clause.start() + words[end].end(), fragment)
                candidates.setdefault(key, []).append(span)
    known = {}
    keys = list(candidates)
    for offset in range(0, len(keys), 400):
        chunk = keys[offset:offset + 400]
        slots = ",".join("?" for _ in chunk)
        for row in store.connection.execute(f"SELECT name FROM tags WHERE name IN ({slots}) AND category_name!='artist' AND deprecated=0", chunk):
            known[row["name"]] = (row["name"], "canonical")
        for row in store.connection.execute(f"""SELECT a.alias,t.name FROM tag_aliases a JOIN tags t ON t.id=a.tag_id
            WHERE a.alias IN ({slots}) AND a.status='active' AND t.category_name!='artist' AND t.deprecated=0""", chunk):
            known.setdefault(row["alias"], (row["name"], "alias"))
    possible = [(start, end, fragment, *known[key]) for key, spans in candidates.items() if key in known
                for start, end, fragment in spans]
    # The longest explicit phrase wins over constituent tags; ties prefer exact
    # canonical spellings. Results are then returned in the prompt's text order.
    possible.sort(key=lambda item: (-(item[1] - item[0]), item[4] != "canonical", item[0], item[3]))
    selected = []
    for candidate in possible:
        if not any(candidate[0] < old[1] and candidate[1] > old[0] for old in selected):
            selected.append(candidate)
    selected.sort(key=lambda item: item[0])
    matches, seen = [], set()
    for start, end, fragment, name, kind in selected:
        if name in seen:
            continue
        seen.add(name)
        matches.append({"name": name, "text": fragment, "match_kind": kind})
    return {"tags": [item["name"] for item in matches[:limit]], "matches": matches[:limit],
        "method": "dictionary_phrases", "data_pack_id": store.pack_id, "truncated": len(matches) > limit,
        "max_phrase_words": MAX_PHRASE_WORDS}
