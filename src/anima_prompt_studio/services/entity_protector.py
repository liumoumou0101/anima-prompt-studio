from __future__ import annotations

import re
from collections.abc import Iterable

from anima_prompt_studio.domain.models import ProtectedEntity


class EntityProtector:
    def protect(self, text: str, known_entities: Iterable[tuple[str, str]] = ()) -> tuple[str, list[ProtectedEntity]]:
        candidates = list(known_entities)
        candidates.extend((m.group(0), "artist") for m in re.finditer(r"(?<!\w)@[\w.-]+", text))
        candidates.extend((m.group(1), "locked") for m in re.finditer(r"\[\[([^\]]+)\]\]", text))
        seen: set[str] = set()
        entities: list[ProtectedEntity] = []
        protected = text
        for value, entity_type in sorted(candidates, key=lambda x: len(x[0]), reverse=True):
            if not value or value in seen or value not in protected:
                continue
            seen.add(value)
            # Marian preserves this alphanumeric shape much more reliably than
            # underscore-delimited placeholders, which it may silently drop.
            placeholder = f"ZXQ{len(entities) + 1:04d}QXZ"
            protected = protected.replace(f"[[{value}]]", f" {placeholder} ").replace(value, f" {placeholder} ")
            protected = re.sub(r"[ \t]+", " ", protected).strip()
            entities.append(ProtectedEntity(placeholder=placeholder, original=value, entity_type=entity_type))
        return protected, entities

    def restore(self, text: str, entities: Iterable[ProtectedEntity]) -> str:
        for entity in entities:
            text = text.replace(entity.placeholder, entity.original)
            text = text.replace(entity.placeholder.lower(), entity.original)
            digits = "".join(re.findall(r"\d", entity.placeholder))
            if digits:
                # Marian occasionally drops one or more suffix letters while
                # preserving the unique numeric id. Recover that safe variant.
                text = re.sub(rf"ZXQ{re.escape(digits)}[A-Z]*", entity.original, text, flags=re.I)
        return re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", text)
