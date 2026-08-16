from __future__ import annotations

import re

from anima_prompt_studio.domain.models import SemanticFrame, SemanticWarning, WarningLevel


class PromptComplexityService:
    """Heuristic-only advisory; it never rewrites or removes user text."""

    ABSTRACT_TERMS = (
        "命运", "灵魂", "意识", "内心", "象征", "隐喻", "哲学", "永恒", "虚无",
        "孤独感", "压迫感", "宿命", "希望与绝望", "无法言说", "仿佛", "似乎",
    )
    TRANSITIONS = ("因为", "所以", "但是", "然而", "同时", "尽管", "虽然", "而且", "并且", "从而", "仿佛")
    ACTION_TERMS = ("站", "坐", "跑", "跳", "看", "拿", "抱", "骑", "冲", "转身", "回头", "伸手", "挥手", "行走")

    def analyze(self, text: str) -> SemanticWarning | None:
        compact = re.sub(r"\s+", "", text)
        if not compact:
            return None
        length = len(compact)
        sentences = len([x for x in re.split(r"[。！？!?]+", text) if x.strip()])
        clauses = len(re.findall(r"[，,；;：:]", text)) + sentences
        abstract_count = sum(term in text for term in self.ABSTRACT_TERMS)
        transition_count = sum(text.count(term) for term in self.TRANSITIONS)
        action_count = sum(text.count(term) for term in self.ACTION_TERMS)

        score = 0
        score += int(length >= 180) + int(length >= 300)
        score += int(sentences >= 6)
        score += int(clauses >= 14)
        score += int(abstract_count >= 3)
        score += int(transition_count >= 4)
        score += int(action_count >= 8)
        if score < 2:
            return None
        return SemanticWarning(
            level=WarningLevel.YELLOW,
            concept="长提示词",
            message=(
                "当前描述较长或较复杂。ANIMA 更适合结构化标签和简短视觉描述；"
                "建议优先保留人物外观、动作、场景、光线和构图，减少文学化、抽象或重复描述。"
                "程序仍会继续处理，原文不会被自动删改。"
            ),
        )

    @staticmethod
    def analyze_model_fit(model_profile_id: str, frame: SemanticFrame) -> list[SemanticWarning]:
        """Warn when a model profile is a poor fit for a normalized pose."""
        warnings: list[SemanticWarning] = []
        if model_profile_id != "anima_turbo_v1":
            return warnings
        if frame.visual_slots.get("limb_relation"):
            warnings.append(SemanticWarning(
                level=WarningLevel.YELLOW,
                concept="复杂肢体关系",
                message=(
                    "当前动作包含左右肢体之间的精确接触关系。ANIMA Turbo 容易简化姿势、"
                    "混淆左右或生成额外肢体；实测建议切换 ANIMA Base，必要时再使用姿势控制。"
                ),
            ))
        return warnings
