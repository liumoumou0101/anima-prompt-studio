from __future__ import annotations

import json
import re
from pathlib import Path

from anima_prompt_studio.domain.models import CharacterSlot, EnhancementItem


class MultiScopeService:
    def __init__(self, path: Path | None = None) -> None:
        source = path or Path(__file__).resolve().parent.parent / "configs" / "multi_scope_lexicon.json"
        data = json.loads(source.read_text(encoding="utf-8"))
        self.features = data["features"]
        self.actions = data["actions"]

    @staticmethod
    def _segments(text: str) -> list[tuple[str, str]]:
        positions = [("left", "左边"), ("center", "中间"), ("right", "右边")]
        found: list[tuple[int, str, str]] = []
        for position, marker in positions:
            start = text.find(marker)
            if start >= 0:
                found.append((start, position, marker))
        found.sort()
        result = []
        for index, (start, position, marker) in enumerate(found):
            end = found[index + 1][0] if index + 1 < len(found) else len(text)
            value = text[start + len(marker):end].strip("，,；;。 ")
            result.append((position, value))
        return result

    @staticmethod
    def _ordinal_segments(text: str) -> list[tuple[str, str]]:
        match = re.search(
            r"(?:^|[，,；;。])\s*(?:一个|一名)(?:女孩|男孩|男人|女人|人物|角色|人)?"
            r"(?P<first>.*?)[，,；;。]\s*(?:另一个|另一名)(?:女孩|男孩|男人|女人|人物|角色|人)?"
            r"(?P<second>.+)",
            text,
        )
        if not match:
            return []
        return [
            ("left", match.group("first").strip("，,；;。 ")),
            ("right", match.group("second").strip("，,；;。 ")),
        ]

    def _details(self, text: str) -> tuple[str, list[str], list[str]]:
        features: list[str] = []
        actions: list[str] = []
        for trigger, output in sorted(self.features, key=lambda x: len(x[0]), reverse=True):
            if trigger in text and output not in features:
                features.append(output)
        for trigger, output in sorted(self.actions, key=lambda x: len(x[0]), reverse=True):
            if trigger in text and output not in actions:
                actions.append(output)
        male = any(token in text for token in ("男孩", "男人", "男性", "少年"))
        female = any(token in text for token in ("女孩", "女人", "女性", "少女"))
        gender = "1boy" if male and not female else ("1girl" if female and not male else "1other")
        return gender, features, actions

    def extract_slots(self, chinese: str, people_count: int) -> list[CharacterSlot]:
        if people_count < 2:
            return []
        segments = self._segments(chinese) or self._ordinal_segments(chinese)
        slots: list[CharacterSlot] = []
        for position, text in segments[:min(people_count, 3)]:
            gender, features, actions = self._details(text)
            slots.append(CharacterSlot(
                position=position,
                gender_tag=gender,
                appearance_tags=features,
                action_text=", ".join(actions),
            ))
        if slots and any(phrase in chinese for phrase in (
            "两人看向彼此", "两人看着彼此", "互相看着", "互相看向", "看向彼此", "看着彼此",
        )):
            for slot in slots:
                actions = [item for item in slot.action_text.split(", ") if item]
                if "looking at each other" not in actions:
                    actions.append("looking at each other")
                slot.action_text = ", ".join(actions)
        return slots

    @staticmethod
    def translation_scope_failures(english: str, slots: list[CharacterSlot]) -> list[str]:
        """Detect AI translations that move scoped facts between characters."""
        text = re.sub(r"\s+", " ", english).strip().casefold()
        markers: list[tuple[int, str, int]] = []
        for position in ("left", "center", "right"):
            match = re.search(rf"\b(?:on the |the )?{position}(?: one| girl| person)?\b", text)
            if match:
                markers.append((match.start(), position, match.end()))
        markers.sort()
        segments: dict[str, str] = {}
        for index, (start, position, _end) in enumerate(markers):
            finish = markers[index + 1][0] if index + 1 < len(markers) else len(text)
            segments[position] = text[start:finish]

        failures: list[str] = []
        for slot in slots:
            position = slot.position.casefold()
            segment = segments.get(position, "")
            if not segment:
                failures.append(f"AI 翻译缺少 {position} 人物的独立描述")
                continue
            expected = list(slot.appearance_tags)
            expected.extend(
                action for action in slot.action_text.split(", ")
                if action and action != "looking at each other"
            )
            missing = [value for value in expected if not MultiScopeService._english_term_present(value, segment)]
            if missing:
                failures.append(f"AI 翻译中 {position} 人物缺少或串位：{', '.join(missing)}")
        return failures

    @staticmethod
    def _english_term_present(term: str, text: str) -> bool:
        variants = {term.casefold()}
        if term.endswith(" hair"):
            colour = term.removesuffix(" hair")
            variants.update({f"{colour}-haired", f"{colour} haired"})
        return any(value in text for value in variants)

    def _describe(self, position: str, text: str) -> str:
        gender, features, actions = self._details(text)
        prefix = {"left": "On the left", "center": "In the center", "right": "On the right"}[position]
        parts = [{"1girl": "a girl", "1boy": "a boy"}.get(gender, "a person")]
        if features:
            parts.append("with " + " and ".join(features))
        if actions:
            parts.append(" and ".join(actions))
        return prefix + ", " + ", ".join(parts) + "."

    def build(self, chinese: str, people_count: int) -> EnhancementItem | None:
        if people_count < 2:
            return None
        segments = self._segments(chinese) or self._ordinal_segments(chinese)
        if len(segments) >= 2:
            content = " ".join(self._describe(position, text) for position, text in segments[:3])
            return EnhancementItem(id="multi_scope", type="人物作用域", source_rule="position_segments", content=content, replaces_translation=True)
        if "前面" in chinese and "后面" in chinese:
            return EnhancementItem(id="multi_scope", type="人物作用域", source_rule="front_back", content="One person stands in front, while the other stands behind.", replaces_translation=True)
        return None
