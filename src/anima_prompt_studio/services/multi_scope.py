from __future__ import annotations

import json
import re
from pathlib import Path

from anima_prompt_studio.domain.models import EnhancementItem


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

    def _describe(self, position: str, text: str) -> str:
        features = []
        actions = []
        for trigger, output in sorted(self.features, key=lambda x: len(x[0]), reverse=True):
            if trigger in text and output not in features:
                features.append(output)
        for trigger, output in sorted(self.actions, key=lambda x: len(x[0]), reverse=True):
            if trigger in text and output not in actions:
                actions.append(output)
        prefix = {"left": "On the left", "center": "In the center", "right": "On the right"}[position]
        parts = ["a girl"]
        if features:
            parts.append("with " + " and ".join(features))
        if actions:
            parts.append(" and ".join(actions))
        return prefix + ", " + ", ".join(parts) + "."

    def build(self, chinese: str, people_count: int) -> EnhancementItem | None:
        if people_count < 2:
            return None
        segments = self._segments(chinese)
        if len(segments) >= 2:
            content = " ".join(self._describe(position, text) for position, text in segments[:3])
            return EnhancementItem(id="multi_scope", type="人物作用域", source_rule="position_segments", content=content, replaces_translation=True)
        if "前面" in chinese and "后面" in chinese:
            return EnhancementItem(id="multi_scope", type="人物作用域", source_rule="front_back", content="One person stands in front, while the other stands behind.", replaces_translation=True)
        return None
