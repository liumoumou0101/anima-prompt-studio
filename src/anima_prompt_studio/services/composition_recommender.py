from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from anima_prompt_studio.domain.models import (
    COMPOSITION_FIELDS, CompositionFieldState, PromptJob, SubjectMode,
)
from .config_service import ConfigService
from .composition_context import CompositionContextExtractor


@dataclass
class CandidateEvidence:
    score: float = 0.0
    reasons: list[tuple[float, str]] = field(default_factory=list)
    source_rule_ids: list[str] = field(default_factory=list)

    def add(self, score: float, reason: str, source_rule_id: str) -> None:
        self.score += score
        if reason:
            self.reasons.append((score, reason))
        if source_rule_id not in self.source_rule_ids:
            self.source_rule_ids.append(source_rule_id)

    @property
    def best_reason(self) -> str | None:
        return max(self.reasons, default=(0, None), key=lambda item: item[0])[1]


@dataclass
class CompositionRecommendationResult:
    applied_fields: list[str] = field(default_factory=list)
    alternative_fields: list[str] = field(default_factory=list)
    matched_rule_ids: list[str] = field(default_factory=list)


class CompositionRecommendationService:
    """Config-driven, deterministic composition recommendations for offline use."""

    VALID_VALUES = {
        "shot": {"头像", "胸像", "半身", "膝上", "全身", "远景"},
        "camera_height": {"平视", "高机位", "低机位"},
        "angle": {"正面", "侧面", "背面", "三分之四", "无"},
        "gaze": {"看镜头", "看人物", "看物体", "看向画外", "无"},
        "aspect": {"方形", "竖图", "横图"},
        "subject_position": {"左", "中", "右", "无"},
    }

    def __init__(self, configs: ConfigService, path: Path | None = None) -> None:
        source = path or Path(__file__).resolve().parent.parent / "configs" / "composition_rules.json"
        self.rules = json.loads(source.read_text(encoding="utf-8"))
        enhancement_root = source.parent / "enhancement_rules"
        for filename in ("actions.json", "relations.json"):
            for rule in json.loads((enhancement_root / filename).read_text(encoding="utf-8")):
                recommendations = rule.get("composition_recommendations")
                if recommendations:
                    self.rules["rules"].append({
                        "id": f"enhancement_{rule['id']}", "zh_any": rule.get("triggers", []),
                        "recommendations": recommendations,
                    })
        self.configs = configs
        self.context_extractor = CompositionContextExtractor()

    @staticmethod
    def _contains_any(text: str, phrases: list[str]) -> bool:
        lowered = text.casefold()
        return any(phrase.casefold() in lowered for phrase in phrases)

    @staticmethod
    def _negated_chinese(text: str, phrase: str) -> bool:
        start = text.find(phrase)
        if start < 0:
            return False
        prefix = text[max(0, start - 5):start]
        return re.search(r"(?:不|不要|不是|没有|并非|别)[^，。；！？]{0,4}$", prefix) is not None

    def _rule_matches(self, rule: dict, chinese: str, english: str, people_count: int, job: PromptJob) -> bool:
        if people_count < rule.get("people_min", 1):
            return False
        if "people_max" in rule and people_count > rule["people_max"]:
            return False
        if rule.get("movement_direction") and job.composition_context.movement_direction != rule["movement_direction"]:
            return False
        if rule.get("gaze_direction") and job.composition_context.gaze_direction != rule["gaze_direction"]:
            return False
        if "dynamic_action" in rule and job.composition_context.dynamic_action != bool(rule["dynamic_action"]):
            return False
        zh, en = rule.get("zh_any", []), rule.get("en_any", [])
        zh_all = rule.get("zh_all", [])
        en_all = rule.get("en_all", [])
        zh_all_match = bool(zh_all) and all(self._contains_any(chinese, group) for group in zh_all)
        en_all_match = bool(en_all) and all(self._contains_any(english, group) for group in en_all)
        if not zh and not en and not zh_all and not en_all:
            return True
        return self._contains_any(chinese, zh) or self._contains_any(english, en) or zh_all_match or en_all_match

    @staticmethod
    def _add_candidate(
        candidates: dict[str, dict[str, CandidateEvidence]], field_name: str, value: str,
        score: float, reason: str, source_rule_id: str,
    ) -> None:
        evidence = candidates[field_name].setdefault(value, CandidateEvidence())
        evidence.add(float(score), reason, source_rule_id)

    def _collect_candidates(self, job: PromptJob) -> tuple[dict[str, dict[str, CandidateEvidence]], list[str]]:
        candidates: dict[str, dict[str, CandidateEvidence]] = {field: {} for field in COMPOSITION_FIELDS}
        matched_rules: list[str] = []
        chinese = "" if job.uses_english_authority() else (job.normalized_zh or job.original_zh)
        english = job.canonical_prose or job.translated_en

        for field_name, default in self.rules["defaults"].items():
            self._add_candidate(candidates, field_name, default["value"], default["score"], default["reason"], "default")

        for rule in self.rules.get("rules", []):
            if not self._rule_matches(rule, chinese, english, job.composition.people_count, job):
                continue
            matched_rules.append(rule["id"])
            for field_name, recommendations in rule.get("recommendations", {}).items():
                for value, score, reason in recommendations:
                    if value in self.VALID_VALUES[field_name]:
                        self._add_candidate(candidates, field_name, value, score, reason, rule["id"])

        # Explicit source/edited-English composition terms outrank every automatic rule.
        for field_name, terms in self.rules.get("explicit_terms", {}).items():
            for term in terms:
                zh_match = next((phrase for phrase in term.get("zh", [])
                                 if phrase in chinese and not self._negated_chinese(chinese, phrase)), None)
                en_match = next((phrase for phrase in term.get("en", []) if phrase.casefold() in english.casefold()), None)
                if zh_match or en_match:
                    source_id = f"explicit_{field_name}"
                    self._add_candidate(candidates, field_name, term["value"], 1000, term["reason"], source_id)
                    if source_id not in matched_rules:
                        matched_rules.append(source_id)
        explicit_position = job.composition_context.explicit_subject_position
        if explicit_position != "none":
            value = {"left":"左", "center":"中", "right":"右"}[explicit_position]
            self._add_candidate(candidates, "subject_position", value, 1200, "用户明确指定主体在画面中的位置", "explicit_subject_position")
            matched_rules.append("explicit_subject_position")
        if job.effective_subject_mode() == SubjectMode.SCENE:
            self._add_candidate(candidates, "shot", "远景", 500, "纯场景输入使用远景展示环境", "semantic_scene")
            self._add_candidate(candidates, "aspect", "横图", 350, "横图更适合纯场景展开", "semantic_scene")
            matched_rules.append("semantic_scene")
        gaze_map = {"viewer":"看镜头", "away":"看向画外", "object":"看物体", "person":"看人物"}
        gaze = gaze_map.get(job.semantic_frame.gaze_intent)
        if gaze:
            self._add_candidate(candidates, "gaze", gaze, 500, "语义事实明确指定视线目标", "semantic_gaze")
            matched_rules.append("semantic_gaze")
        angle_map = {"front":"正面", "side":"侧面", "back":"背面", "three_quarter":"三分之四"}
        angle = angle_map.get(job.semantic_frame.angle_intent)
        if angle:
            self._add_candidate(candidates, "angle", angle, 500, "语义事实明确指定观察角度", "semantic_angle")
            matched_rules.append("semantic_angle")
        return candidates, matched_rules

    @staticmethod
    def _is_semantically_fixed(evidence: CandidateEvidence) -> bool:
        return any(
            source.startswith("explicit_") or source in {"semantic_gaze", "semantic_angle", "semantic_scene"}
            for source in evidence.source_rule_ids
        )

    def recommend(self, job: PromptJob, alternative_index: int = 0) -> CompositionRecommendationResult:
        result = CompositionRecommendationResult()
        if job.composition.mode == "manual":
            return result
        job.composition_context = self.context_extractor.extract(job)
        candidates, result.matched_rule_ids = self._collect_candidates(job)
        rankings = {
            field_name: sorted(
                candidates[field_name].items(), key=lambda item: (item[1].score, item[0]), reverse=True,
            )
            for field_name in COMPOSITION_FIELDS
        }
        alternative_field: str | None = None
        if alternative_index > 0:
            eligible = [
                field_name for field_name in COMPOSITION_FIELDS
                if field_name != "gaze"
                and job.composition.decision(field_name).state == CompositionFieldState.AUTO
                and len(rankings[field_name]) > 1
                and not self._is_semantically_fixed(rankings[field_name][0][1])
            ]

            def alternative_priority(field_name: str) -> tuple[int, int]:
                second_is_meaningful = any(
                    source != "default" for source in rankings[field_name][1][1].source_rule_ids
                )
                fallback_order = {
                    "angle": 0, "camera_height": 1, "subject_position": 2,
                    "aspect": 3, "shot": 4,
                }
                return (0 if second_is_meaningful else 1, fallback_order.get(field_name, 9))

            eligible.sort(key=alternative_priority)
            if eligible:
                alternative_field = eligible[(alternative_index - 1) % len(eligible)]
        for field_name in COMPOSITION_FIELDS:
            decision = job.composition.decision(field_name)
            if decision.state != CompositionFieldState.AUTO:
                continue
            ranked = rankings[field_name]
            if not ranked:
                continue
            selected_index = 1 if field_name == alternative_field else 0
            value, evidence = ranked[selected_index]
            setattr(job.composition, field_name, value)
            decision.reason = evidence.best_reason
            if selected_index:
                decision.reason = f"备选构图 {selected_index + 1}：{decision.reason or '采用次优候选'}"
                result.alternative_fields.append(field_name)
            decision.source_rule_ids = evidence.source_rule_ids
            decision.score = round(evidence.score, 3)
            result.applied_fields.append(field_name)
        if job.effective_subject_mode() == SubjectMode.SCENE:
            job.composition.people_count = 0
            for field_name in ("angle", "gaze", "subject_position"):
                decision = job.composition.decision(field_name)
                if decision.state == CompositionFieldState.AUTO:
                    setattr(job.composition, field_name, "无")
                    decision.reason = "纯场景不使用人物构图参数"
                    decision.source_rule_ids = ["semantic_scene_clear"]
                    decision.score = 1000
        self.apply_aspect_dimensions(job)
        return result

    def apply_aspect_dimensions(self, job: PromptJob) -> None:
        params = job.generation_params
        if not params.is_automatic("width") or not params.is_automatic("height"):
            return
        profile = self.configs.get_model(job.model_profile_id)
        short, long = sorted((profile.default_width, profile.default_height))
        if job.composition.aspect == "竖图":
            params.width, params.height = short, long
        elif job.composition.aspect == "横图":
            params.width, params.height = long, short
        else:
            side = int(round(math.sqrt(profile.default_width * profile.default_height) / 64) * 64)
            params.width = params.height = side
