from __future__ import annotations

import json
import math
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from anima_prompt_studio.domain.models import CharacterCard, ResolvedCharacter
from anima_prompt_studio.repositories.tag_database import TagDatabase
from anima_prompt_studio.services.ai_prompt_service import AIClient


CHARACTER_RECOGNITION_SYSTEM = """You identify established named anime and game characters explicitly mentioned in Chinese text.
Return one JSON object with a `characters` array. Each item must contain:
- source_text: the exact name span copied from the input
- name_en: the best-known English/romanized character name
- series_en: the best-known English/romanized franchise or game title
- gender: one of girl, boy, other, unknown
Do not return generic roles, unnamed people, original characters, guesses from appearance, artists, or real people.
Do not invent Danbooru tags. A local database will validate every suggestion.
If no established character is explicit, return {"characters": []}."""


class RecognizedMention(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_text: str
    name_en: str
    series_en: str = ""
    gender: str = "unknown"

    @field_validator("source_text", "name_en", "series_en", mode="before")
    @classmethod
    def clean_text(cls, value: Any) -> str:
        return str(value or "").strip()


class RecognitionPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    characters: list[RecognizedMention] = Field(default_factory=list)


class LocalTagCandidate(BaseModel):
    canonical_name: str
    output_name: str
    category: int
    post_count: int = 0
    score: float = 0.0


class CharacterSuggestion(BaseModel):
    mention: RecognizedMention
    character_candidates: list[LocalTagCandidate] = Field(default_factory=list)
    copyright_candidates: list[LocalTagCandidate] = Field(default_factory=list)


class CharacterResolver:
    """Resolve saved aliases offline and validate AI suggestions against the local tag DB."""

    def __init__(self, database: TagDatabase | None = None) -> None:
        self.database = database

    def resolve(
        self,
        text: str,
        cards: list[CharacterCard],
        selected_card_ids: set[str] | None = None,
    ) -> list[ResolvedCharacter]:
        selected_card_ids = selected_card_ids or set()
        matches: list[tuple[int, int, str, CharacterCard]] = []
        for card in cards:
            if not card.anima_character_tag:
                continue
            names = sorted(
                {name.strip() for name in [card.display_name, *card.aliases] if name.strip()},
                key=len,
                reverse=True,
            )
            for name in names:
                for start, end in self._find_name(text, name):
                    matches.append((start, end, text[start:end], card))

        # Longest match wins at the same location; overlapping aliases are one entity.
        accepted: list[tuple[int, int, str, CharacterCard]] = []
        occupied: set[int] = set()
        for item in sorted(matches, key=lambda value: (value[0], -(value[1] - value[0]))):
            start, end, _, _ = item
            if any(index in occupied for index in range(start, end)):
                continue
            accepted.append(item)
            occupied.update(range(start, end))

        resolved: list[ResolvedCharacter] = []
        seen_cards: set[str] = set()
        for _, _, source, card in accepted:
            if card.id in seen_cards:
                continue
            resolved.append(self._from_card(card, source))
            seen_cards.add(card.id)
        for card in cards:
            if card.id in selected_card_ids and card.id not in seen_cards and card.anima_character_tag:
                resolved.append(self._from_card(card, card.display_name))
        return resolved

    @staticmethod
    def _find_name(text: str, name: str):
        if re.search(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]", name):
            start = 0
            while True:
                index = text.find(name, start)
                if index < 0:
                    return
                yield index, index + len(name)
                start = index + len(name)
        else:
            pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", re.I)
            yield from ((match.start(), match.end()) for match in pattern.finditer(text))

    @staticmethod
    def _from_card(card: CharacterCard, source: str) -> ResolvedCharacter:
        return ResolvedCharacter(
            source_text=source,
            display_name=card.display_name,
            character_tag=card.anima_character_tag or "",
            copyright_tag=card.copyright_tag,
            gender_tag=card.gender_tag,
            card_id=card.id,
        )

    @staticmethod
    def natural_name(character_tag: str) -> str:
        base = re.sub(r"_\([^)]*\)$", "", character_tag.strip())
        return base.replace("_", " ").strip().title()

    def replace_source_names(self, translated: str, resolved: list[ResolvedCharacter]) -> str:
        result = translated
        for item in sorted(resolved, key=lambda value: len(value.source_text), reverse=True):
            if item.source_text:
                result = re.sub(
                    re.escape(item.source_text), self.natural_name(item.character_tag), result, flags=re.I,
                )
        return result

    def candidates(self, mention: RecognizedMention, limit: int = 8) -> CharacterSuggestion:
        if self.database is None:
            return CharacterSuggestion(mention=mention)
        rows = self.database.search(mention.name_en, limit=50, categories={4})
        character_candidates = [self._candidate(row, mention) for row in rows]
        character_candidates.sort(key=lambda item: item.score, reverse=True)
        copyrights = self.database.search(mention.series_en, limit=12, categories={3}) if mention.series_en else []
        copyright_candidates = [
            LocalTagCandidate(**row, score=self._copyright_score(row, mention.series_en)) for row in copyrights
        ]
        copyright_candidates.sort(key=lambda item: item.score, reverse=True)
        return CharacterSuggestion(
            mention=mention,
            character_candidates=character_candidates[:limit],
            copyright_candidates=copyright_candidates[:limit],
        )

    @classmethod
    def _candidate(cls, row: dict, mention: RecognizedMention) -> LocalTagCandidate:
        canonical = row["canonical_name"]
        base, _, parenthetical = canonical.partition("_(")
        name_key = cls._key(mention.name_en)
        series_key = cls._key(mention.series_en)
        base_key = cls._key(base)
        parent_key = cls._key(parenthetical.rstrip(")"))
        score = math.log10(max(1, int(row.get("post_count", 0))))
        if base_key == name_key:
            score += 100
            if canonical == base:
                score += 35
        elif name_key and (name_key in base_key or base_key in name_key):
            score += 45
        if series_key and parent_key:
            if series_key == parent_key:
                score += 40
            elif series_key in parent_key or parent_key in series_key:
                score += 20
        return LocalTagCandidate(**row, score=score)

    @classmethod
    def _copyright_score(cls, row: dict, series: str) -> float:
        score = math.log10(max(1, int(row.get("post_count", 0))))
        if cls._key(row["canonical_name"]) == cls._key(series):
            score += 100
        return score

    @staticmethod
    def _key(value: str) -> str:
        return "_".join(re.findall(r"[a-z0-9]+", value.casefold()))


class CharacterRecognitionService:
    def __init__(self, database: TagDatabase) -> None:
        self.database = database
        self.resolver = CharacterResolver(database)

    def recognize(self, source_text: str, client: AIClient) -> list[CharacterSuggestion]:
        text = source_text.strip()
        if not text:
            raise ValueError("请先输入包含角色名的中文描述。")
        raw = client.complete_json(
            CHARACTER_RECOGNITION_SYSTEM,
            json.dumps({"source_text": text}, ensure_ascii=False),
        )
        payload = RecognitionPayload.model_validate(raw)
        suggestions: list[CharacterSuggestion] = []
        seen: set[str] = set()
        for mention in payload.characters:
            if not mention.source_text or mention.source_text not in text or not mention.name_en:
                continue
            key = mention.source_text.casefold()
            if key in seen:
                continue
            seen.add(key)
            suggestions.append(self.resolver.candidates(mention))
        return suggestions
