from __future__ import annotations

import json
import re
from pathlib import Path

from anima_prompt_studio.domain.models import MatchedTag, ResolvedConcept


class ConceptResolver:
    def __init__(self, path: Path | None = None) -> None:
        source = path or Path(__file__).resolve().parent.parent / "configs" / "concept_mappings.json"
        self.rules: list[dict] = json.loads(source.read_text(encoding="utf-8"))

    def resolve(self, chinese: str) -> list[ResolvedConcept]:
        matches: list[ResolvedConcept] = []
        occupied_categories: set[str] = set()
        candidates = []
        for rule in self.rules:
            if any(x in chinese for x in rule.get("exclude_triggers", [])):
                continue
            trigger = next((x for x in sorted(rule["triggers"], key=len, reverse=True) if x in chinese), None)
            if trigger:
                candidates.append((rule.get("priority", 0), len(trigger), chinese.rfind(trigger), trigger, rule))
        for _, _, _, trigger, rule in sorted(candidates, key=lambda item: item[:4], reverse=True):
            category = rule.get("category", "general")
            # Single-valued appearance slots keep one winner (highest priority / longest trigger).
            if category in {"race", "body", "hair", "eyes"} and category in occupied_categories:
                continue
            occupied_categories.add(category)
            matches.append(ResolvedConcept(
                id=rule["id"], source_text=trigger, canonical_en=rule["canonical_en"], tags=rule.get("tags", []),
                category=category, priority=rule.get("priority", 0), suppresses_tags=rule.get("suppresses_tags", []),
            ))
        return sorted(matches, key=lambda x: x.priority, reverse=True)

    def apply_translation(self, chinese: str, translated: str, concepts: list[ResolvedConcept]) -> str:
        active_ids = {x.id for x in concepts}
        for rule in sorted(self.rules, key=lambda x: x.get("priority", 0), reverse=True):
            if rule["id"] not in active_ids:
                continue
            for pattern, replacement in rule.get("translation_replacements", []):
                updated, count = re.subn(pattern, replacement, translated, count=1, flags=re.I)
                if count:
                    translated = updated
                    break
            canonical = rule["canonical_en"]
            ensure_tokens = list(rule.get("ensure_en") or [])
            if not ensure_tokens:
                ensure_tokens = [canonical]
            present = any(self._token_present(translated, token) for token in ensure_tokens)
            if rule.get("category") == "hair" and canonical.endswith(" hair"):
                colour = re.escape(canonical.removesuffix(" hair"))
                present = present or bool(re.search(rf"\b{colour}(?: hair|-haired)\b", translated, flags=re.I))
            if present:
                continue
            if rule.get("category") in {"race", "body", "hair", "eyes"}:
                translated = translated.rstrip(". ") + f". The character has {canonical}."
            elif rule.get("ensure_phrase") or rule.get("ensure_en"):
                phrase = rule.get("ensure_phrase") or f"{canonical}."
                translated = translated.rstrip(". ") + f" {phrase}"
        return self._clean(translated)

    @staticmethod
    def _token_present(text: str, token: str) -> bool:
        token = token.strip()
        if not token:
            return False
        if re.search(r"[\u4e00-\u9fff]", token):
            return token in text
        return bool(re.search(rf"(?<!\w){re.escape(token)}(?!\w)", text, flags=re.I))

    @staticmethod
    def _clean(text: str) -> str:
        text = re.sub(
            r"\b(dark|white|black|blue|red|green|golden|silver|long|short|large|small|petite)\s+\1\b",
            r"\1", text, flags=re.I,
        )
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\s+([,.;!?])", r"\1", text)
        return text.strip()

    @staticmethod
    def as_tags(concepts: list[ResolvedConcept]) -> list[MatchedTag]:
        seen: set[str] = set()
        result: list[MatchedTag] = []
        for concept in concepts:
            for tag in concept.tags:
                if tag in seen:
                    continue
                seen.add(tag)
                result.append(MatchedTag(
                    tag=tag, category=concept.category, source_type="derived",
                    source_text=concept.source_text, confidence=1.0,
                ))
        return result
