from __future__ import annotations

import json
import re
from pathlib import Path

from anima_prompt_studio.domain.models import EnhancementItem, SemanticFrame
from .negation import phrase_has_unnegated_zh


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
        if groups and not all(
            any(phrase_has_unnegated_zh(chinese, trigger) for trigger in group)
            for group in groups
        ):
            return False
        triggers = rule.get("triggers", [])
        return bool(groups) or any(phrase_has_unnegated_zh(chinese, trigger) for trigger in triggers)

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
        if not explicit_emotion and any(
            phrase_has_unnegated_zh(chinese, x)
            for x in ("窗边", "抱膝", "低头", "撩头发", "看镜头", "探出窗外")
        ):
            items.append(EnhancementItem(id="weak_emotion", type="情绪", source_rule="weak_emotion", content="She has a calm, soft expression.", tags=["soft expression"]))
        hand_scope = self._hand_scope(chinese)
        if hand_scope:
            items = [
                item for item in items
                if item.id not in {"hair_tuck", "touching_hair", "weak_emotion"}
            ]
            items.append(hand_scope)
        # Preserve order but avoid duplicate rule ids triggered by overlapping scenes.
        unique: dict[str, EnhancementItem] = {}
        for item in items:
            unique.setdefault(item.id, item)
        return list(unique.values())

    @staticmethod
    def _hand_scope(chinese: str) -> EnhancementItem | None:
        """Bind left/right hands to distinct actions, objects, or an empty hang."""
        sentence = canonical_split_hands_sentence(chinese)
        if not sentence:
            return None
        return EnhancementItem(
            id="hand_scope", type="人物作用域", source_rule="left_right_hands",
            content=sentence, tags=[], replaces_translation=True,
        )


_HAND_HANGING = ("垂下", "垂在", "自然垂", "放在身侧", "垂在身侧")
_HAND_OBJECTS = (
    (("合上的书", "闭合的书", "合上的一本"), "a closed book", "book"),
    (("书",), "a book", "book"),
    (("马克杯",), "a mug", "mug"),
    (("茶壶", "水壶"), "a teapot", "teapot"),
    (("杯子", "茶杯", "咖啡杯"), "a cup", "cup"),
    (("合上的伞", "闭合的雨伞", "合上的雨伞", "收起的伞", "收起的雨伞"), "a closed umbrella", "umbrella"),
    (("雨伞", "伞"), "an umbrella", "umbrella"),
    (("手机",), "a phone", "phone"),
    (("花",), "a flower", "flower"),
)
_HAND_ACTIONS = (
    (("把头发拨到耳后", "拨到耳后", "将发丝别到耳后", "别到耳后"), "tucks a strand of hair behind her ear with her {side} hand"),
    (("撩头发", "拨头发", "摸头发", "手放在头发上", "整理头发"), "touches her hair with her {side} hand"),
    (("裙摆", "掀裙", "提裙", "提起裙", "把裙"), "lifts her skirt with her {side} hand"),
    (("胸口", "胸前"), "rests her {side} hand on her chest"),
    (("下巴", "托腮"), "supports her chin with her {side} hand"),
    (("挥手", "招手"), "waves with her {side} hand"),
)


def _hand_segment(chinese: str, hand: str) -> str:
    return next((part for part in re.split(r"[,，;；。]", chinese) if hand in part), "")


def _object_in_segment(segment: str) -> tuple[str, str] | None:
    for triggers, english, key in _HAND_OBJECTS:
        if any(trigger in segment for trigger in triggers):
            return english, key
    return None


def parse_hand_roles(chinese: str) -> dict[str, dict[str, object]] | None:
    """Map 左手/右手 clauses to hanging, object, or action roles."""
    if "左手" not in chinese or "右手" not in chinese:
        return None
    roles: dict[str, dict[str, object]] = {}
    for hand, side in (("右手", "right"), ("左手", "left")):
        segment = _hand_segment(chinese, hand)
        if not segment:
            return None
        hanging = any(token in segment for token in _HAND_HANGING)
        action = next(
            (template.format(side=side) for triggers, template in _HAND_ACTIONS if any(token in segment for token in triggers)),
            "",
        )
        found = _object_in_segment(segment)
        object_en, object_key = found if found else ("", "")
        if not action and not object_en and not hanging:
            return None
        roles[side] = {
            "side": side,
            "hanging": hanging and not action and not object_en,
            "object_en": object_en,
            "object_key": object_key,
            "action_en": action,
            "segment": segment,
        }
    return roles


def canonical_split_hands_sentence(chinese: str) -> str | None:
    """One shared sentence for split left/right roles. None if the source is not split."""
    roles = parse_hand_roles(chinese)
    if not roles:
        return None
    pour = _pour_sentence(chinese, roles)
    if pour:
        return pour
    clauses: list[str] = []
    for side in ("right", "left"):
        role = roles[side]
        if role["action_en"]:
            clauses.append(str(role["action_en"]))
        elif role["object_en"]:
            clauses.append(f"holds {role['object_en']} in her {side} hand")
        elif role["hanging"]:
            clauses.append(f"her {side} hand hangs empty at her side")
    if len(clauses) < 2:
        return None
    if "窗外" in chinese:
        clauses.append("looks out the window")
    return "She " + ", ".join(clauses[:-1]) + ", and " + clauses[-1] + "."


def _pour_sentence(chinese: str, roles: dict[str, dict[str, object]]) -> str | None:
    if "倒" not in chinese:
        return None
    teapot_side = next((side for side, role in roles.items() if role["object_key"] == "teapot"), "")
    cup_side = next((side for side, role in roles.items() if role["object_key"] in {"cup", "mug"}), "")
    if not teapot_side or not cup_side or teapot_side == cup_side:
        return None
    return (
        f"She pours from the teapot in her {teapot_side} hand "
        f"into the cup in her {cup_side} hand."
    )
