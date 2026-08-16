from __future__ import annotations

import json
import re
from pathlib import Path

from anima_prompt_studio.domain.models import EnhancementItem, SemanticFrame


SCENE_RULES = [
    ("morning", ["清晨", "早晨"], "Soft morning light enters through the window, creating a warm and gentle atmosphere.", ["soft morning light", "warm sunlight"]),
    ("rain", ["雨天", "雨夜", "下雨"], "The rainy atmosphere and wet reflections create a calm and moody feeling.", ["rain", "wet reflections", "cool tones"]),
    ("sunset", ["黄昏", "夕阳"], "Golden sunset light casts a warm glow around her.", ["golden sunset light", "warm backlighting"]),
    ("night", ["夜晚", "月光"], "Cool moonlight creates a quiet night atmosphere.", ["moonlight", "cool lighting"]),
]


class PromptEnhancer:
    def __init__(self, config_dir: Path | None = None) -> None:
        root = config_dir or Path(__file__).resolve().parent.parent / "configs" / "enhancement_rules"
        self.rules: list[dict] = []
        for name in ("actions.json", "relations.json"):
            self.rules.extend(json.loads((root / name).read_text(encoding="utf-8")))

    @staticmethod
    def _matches(rule: dict, chinese: str) -> bool:
        if any(value in chinese for value in rule.get("forbidden_context", [])):
            return False
        groups = rule.get("triggers_all", [])
        if groups and not all(any(trigger in chinese for trigger in group) for group in groups):
            return False
        triggers = rule.get("triggers", [])
        return bool(groups) or any(trigger in chinese for trigger in triggers)

    def normalize_translation(self, chinese: str, english: str) -> str:
        text = english
        for rule in sorted(self.rules, key=lambda x: x.get("priority", 0), reverse=True):
            if not self._matches(rule, chinese):
                continue
            for pattern, replacement in rule.get("natural_replacements", []):
                text = re.sub(pattern, replacement, text, flags=re.I)
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\s+([,.;!?])", r"\1", text)
        text = re.sub(r",\s*(?:and\s*)?with\s+", " with ", text, flags=re.I)
        return text.strip()

    def enhance(self, chinese: str, english: str = "", semantic_frame: SemanticFrame | None = None) -> list[EnhancementItem]:
        items: list[EnhancementItem] = []
        english_lower = english.lower()
        for rule in sorted(self.rules, key=lambda x: x.get("priority", 0), reverse=True):
            if not self._matches(rule, chinese):
                continue
            canonical = rule.get("canonical_phrases", [])
            canonical_present = canonical and any(phrase in english_lower for phrase in canonical)
            if canonical_present and not rule.get("emit_tags_when_canonical", False):
                # The relation is already correctly preserved by translation.
                continue
            items.append(EnhancementItem(
                id=rule["id"], type=rule["type"], source_rule=rule["id"],
                content=(rule.get("content", "") if rule.get("replaces_translation", False)
                         else ("" if canonical_present else rule.get("content", ""))),
                tags=rule.get("tags", []), suppress_tags=rule.get("suppress_tags", []),
                suppress_patterns=rule.get("suppress_patterns", []), canonical_phrases=canonical,
                replaces_translation=rule.get("replaces_translation", False),
            ))
        for rule_id, triggers, sentence, tags in SCENE_RULES:
            if any(t in chinese for t in triggers):
                items.append(EnhancementItem(id=rule_id, type="场景", source_rule=rule_id, content=sentence, tags=tags))
        explicit_emotion = bool(semantic_frame and semantic_frame.visual_slots.get("emotion")) or any(
            x in chinese for x in ("悲伤", "生气", "愤怒", "害怕", "开心", "兴奋", "哭", "大笑")
        )
        if not explicit_emotion and any(x in chinese for x in ("窗边", "抱膝", "低头", "撩头发", "看镜头", "探出窗外")):
            items.append(EnhancementItem(id="weak_emotion", type="情绪", source_rule="weak_emotion", content="She has a calm, soft expression.", tags=["soft expression"]))
        hand_scope = self._hand_scope(chinese)
        if hand_scope:
            items = [item for item in items if item.id not in {"hair_tuck", "weak_emotion"}]
            items.append(hand_scope)
        # Preserve order but avoid duplicate rule ids triggered by overlapping scenes.
        unique: dict[str, EnhancementItem] = {}
        for item in items:
            unique.setdefault(item.id, item)
        return list(unique.values())

    @staticmethod
    def _hand_scope(chinese: str) -> EnhancementItem | None:
        """Build one canonical sentence when both hands have independently scoped actions."""
        if "左手" not in chinese or "右手" not in chinese:
            return None
        clauses: list[str] = []
        for hand in ("右手", "左手"):
            segment = next((part for part in re.split(r"[,，;；。]", chinese) if hand in part), "")
            side = "right" if hand == "右手" else "left"
            if any(trigger in segment for trigger in ("把头发拨到耳后", "拨到耳后", "将发丝别到耳后", "别到耳后")):
                clauses.append(f"tucks a strand of hair behind her ear with her {side} hand")
            elif any(trigger in segment for trigger in ("撩头发", "拨头发", "摸头发", "手放在头发上", "整理头发")):
                clauses.append(f"touches her hair with her {side} hand")
            if "拿书" in segment or "拿着书" in segment:
                clauses.append(f"holds a book in her {side} hand")
            if "拿花" in segment or "拿着花" in segment:
                clauses.append(f"holds a flower in her {side} hand")
        if len(clauses) < 2:
            return None
        if "窗外" in chinese:
            clauses.append("looks out the window")
        content = "She " + ", ".join(clauses[:-1]) + (", and " if len(clauses) > 1 else "") + clauses[-1] + "."
        return EnhancementItem(
            id="hand_scope", type="人物作用域", source_rule="left_right_hands",
            content=content, tags=[], replaces_translation=True,
        )
