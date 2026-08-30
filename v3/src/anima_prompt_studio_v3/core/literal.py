from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..data import ReferenceDataStore
from ..domain import (
    CandidateLane,
    CandidateSet,
    CandidateTag,
    CandidateTagState,
    CandidateVersions,
    CandidateWarning,
    IntentDocument,
    IntentElement,
    IntentState,
    PromptCandidate,
    TagSource,
    intent_state_priority,
)
from .profiles import ModelProfile, NegativePromptMode


LITERAL_ALGORITHM_VERSION = "literal-mapper-v2"


_PROMPT_FACT_ORDER = {
    "quality": 0,
    "character": 10,
    "subject": 20,
    "appearance": 30,
    "clothing": 40,
    "action": 50,
    "relation": 55,
    "object": 60,
    "scene": 70,
    "composition": 80,
    "style": 90,
    "other": 100,
}


class LiteralGenerationError(ValueError):
    """Raised when a safe literal baseline cannot be generated."""


class LiteralMatchKind(StrEnum):
    EXACT = "exact"
    ALIAS = "alias"
    CHINESE = "chinese"


class LiteralMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    element_id: str
    canonical_name: str
    rendered: str
    match_kind: LiteralMatchKind
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    data_pack_id: str


class LiteralMapper:
    """Resolve only deterministic exact, alias, and exact Chinese terms."""

    def __init__(self, store: ReferenceDataStore) -> None:
        self.store = store

    def map_element(self, element: IntentElement) -> LiteralMapping | None:
        attempted: set[str] = set()
        if element.canonical_tag:
            attempted.add(element.canonical_tag)
            detail = self.store.get_tag(element.canonical_tag)
            if detail is not None:
                kind = LiteralMatchKind.EXACT if detail["name"] == element.canonical_tag else LiteralMatchKind.ALIAS
                return self._mapping(element, detail, kind)

        normalized_original = _query_to_canonical(element.original_text)
        if normalized_original and normalized_original not in attempted:
            detail = self.store.get_tag(normalized_original)
            if detail is not None:
                kind = LiteralMatchKind.EXACT if detail["name"] == normalized_original else LiteralMatchKind.ALIAS
                return self._mapping(element, detail, kind)

        query = element.original_text.strip()
        if not query:
            return None
        for summary in self.store.search(query, limit=20):
            detail = self.store.get_tag(summary["name"])
            if detail is None:
                continue
            chinese_terms = {detail.get("cn_name")}
            chinese_terms.update(detail.get("cn_terms") or [])
            if query in {term.strip() for term in chinese_terms if term}:
                return self._mapping(element, detail, LiteralMatchKind.CHINESE)
        return None

    def _mapping(
        self,
        element: IntentElement,
        detail: dict[str, Any],
        kind: LiteralMatchKind,
    ) -> LiteralMapping:
        reasons = {
            LiteralMatchKind.EXACT: "canonical tag 精确匹配",
            LiteralMatchKind.ALIAS: "通过有效别名解析为 canonical tag",
            LiteralMatchKind.CHINESE: "本地中文标签词精确匹配",
        }
        confidence = {
            LiteralMatchKind.EXACT: 1.0,
            LiteralMatchKind.ALIAS: 0.99,
            LiteralMatchKind.CHINESE: 0.98,
        }
        return LiteralMapping(
            element_id=element.id,
            canonical_name=detail["name"],
            rendered=render_canonical_tag(detail["name"]),
            match_kind=kind,
            confidence=confidence[kind],
            reason=reasons[kind],
            data_pack_id=self.store.pack_id,
        )


class LiteralCandidateGenerator:
    def __init__(self, store: ReferenceDataStore) -> None:
        self.store = store
        self.mapper = LiteralMapper(store)

    def generate(self, intent: IntentDocument, profile: ModelProfile) -> CandidateSet:
        conflicts = intent.graph.find_conflicts()
        if conflicts:
            ids = sorted({item for conflict in conflicts for item in conflict.element_ids})
            raise LiteralGenerationError(f"存在未解决的约束冲突：{ids}")

        positive: OrderedDict[str, dict[str, Any]] = OrderedDict()
        negative: list[str] = []
        excluded_canonical: set[str] = set()
        preserved: list[str] = []
        unresolved: list[str] = []
        warnings: list[CandidateWarning] = []
        prose_baseline_ids: list[str] = []

        for element_index, element in enumerate(intent.graph.elements):
            mapping = self.mapper.map_element(element)
            if mapping is None:
                if _uses_local_prose_baseline(element, intent):
                    preserved.append(element.id)
                    prose_baseline_ids.append(element.id)
                    continue
                unresolved.append(element.id)
                warnings.append(_unresolved_warning(element))
                continue
            if element.state == IntentState.EXCLUDED:
                excluded_canonical.add(mapping.canonical_name)
                if profile.negative_prompt_mode == NegativePromptMode.ENABLED:
                    negative.append(mapping.rendered)
                else:
                    warnings.append(
                        CandidateWarning(
                            code="negative_prompt_unsupported",
                            message=f"{profile.display_name} 已关闭 negative prompt；仍会阻止 {mapping.canonical_name} 进入正向提示词。",
                            element_ids=[element.id],
                        )
                    )
                continue

            preserved.append(element.id)
            existing = positive.get(mapping.canonical_name)
            if existing is None:
                positive[mapping.canonical_name] = {
                    "mapping": mapping,
                    "state": _candidate_state(element.state),
                    "fact_type": element.type,
                    "source_order": element_index,
                    "element_ids": [element.id],
                    "reasons": [mapping.reason],
                    "removable": element.state != IntentState.LOCKED,
                }
            else:
                existing["element_ids"].append(element.id)
                existing["reasons"].append(mapping.reason)
                if intent_state_priority(element.state) > _candidate_state_priority(existing["state"]):
                    existing["state"] = _candidate_state(element.state)
                if element.state == IntentState.LOCKED:
                    existing["removable"] = False
                if _prompt_fact_priority(element.type.value) < _prompt_fact_priority(existing["fact_type"].value):
                    existing["fact_type"] = element.type

        mapped_conflicts = set(positive) & excluded_canonical
        if mapped_conflicts:
            raise LiteralGenerationError(f"别名解析后标签同时被要求和排除：{sorted(mapped_conflicts)}")

        tags = [
            CandidateTag(
                name=name,
                rendered=entry["mapping"].rendered,
                state=entry["state"],
                source=TagSource.ALIAS if entry["mapping"].match_kind == LiteralMatchKind.ALIAS else TagSource.EXACT,
                source_element_ids=list(dict.fromkeys(entry["element_ids"])),
                reason="；".join(dict.fromkeys(entry["reasons"])),
                data_pack_id=self.store.pack_id,
                algorithm_version=LITERAL_ALGORITHM_VERSION,
                removable=entry["removable"],
            )
            for name, entry in sorted(
                positive.items(),
                key=lambda item: (
                    _prompt_fact_priority(item[1]["fact_type"].value),
                    item[1]["source_order"],
                ),
            )
        ]

        positive_parts = _deduplicate([*profile.positive_prefix, *(tag.rendered for tag in tags)])
        if not tags and prose_baseline_ids and intent.scene_plan_en:
            positive_parts.append(intent.scene_plan_en.strip())
            warnings.append(CandidateWarning(
                code="local_prose_baseline",
                message="本地索引没有可确认标签；保留完整本地译文作为可编辑的基准表达。",
                element_ids=prose_baseline_ids,
            ))
        if not positive_parts:
            raise LiteralGenerationError("literal 没有可安全渲染的正向内容。")
        negative_parts = (
            _deduplicate([*profile.negative_prompt, *negative])
            if profile.negative_prompt_mode == NegativePromptMode.ENABLED
            else []
        )
        candidate = PromptCandidate(
            id="candidate_literal",
            lane=CandidateLane.LITERAL,
            title="高保真基准",
            positive_prompt=profile.tag_separator.join(positive_parts),
            negative_prompt=profile.tag_separator.join(negative_parts),
            tags=tags,
            preserved_element_ids=list(dict.fromkeys(preserved)),
            unresolved_element_ids=list(dict.fromkeys(unresolved)),
            warnings=warnings,
            score_breakdown={
                "mapped_elements": float(len(preserved) - len(prose_baseline_ids)),
                "unresolved_elements": float(len(unresolved)),
                "prose_baseline": float(bool(prose_baseline_ids)),
            },
            versions=CandidateVersions(
                data_pack=self.store.pack_id,
                algorithm=LITERAL_ALGORITHM_VERSION,
                templates=profile.renderer_version,
                model_profile=profile.id,
            ),
        )
        return CandidateSet(intent=intent, candidates=[candidate])


def render_canonical_tag(name: str) -> str:
    if name.startswith("score_") and name.removeprefix("score_").removesuffix("_up").isdigit():
        return name
    return name.replace("_", " ")


def _query_to_canonical(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "_")
    if not normalized or any(character in normalized for character in "\r\n\t"):
        return ""
    return normalized


def _candidate_state(state: IntentState) -> CandidateTagState:
    mapping = {
        IntentState.LOCKED: CandidateTagState.LOCKED,
        IntentState.REQUIRED: CandidateTagState.REQUIRED,
        IntentState.USER_SELECTED: CandidateTagState.USER_SELECTED,
        IntentState.SUGGESTED: CandidateTagState.SUGGESTED,
        IntentState.AUTOMATIC: CandidateTagState.AUTOMATIC,
    }
    try:
        return mapping[state]
    except KeyError as exc:
        raise LiteralGenerationError(f"excluded element 不能进入正向候选：{state}") from exc


def _candidate_state_priority(state: CandidateTagState) -> int:
    mapping = {
        CandidateTagState.LOCKED: 600,
        CandidateTagState.REQUIRED: 400,
        CandidateTagState.USER_SELECTED: 300,
        CandidateTagState.SUGGESTED: 200,
        CandidateTagState.AUTOMATIC: 100,
    }
    return mapping[state]


def _prompt_fact_priority(value: str) -> int:
    """Order reviewed facts without inventing any additional prompt content."""

    return _PROMPT_FACT_ORDER.get(value, _PROMPT_FACT_ORDER["other"])


def _unresolved_warning(element: IntentElement) -> CandidateWarning:
    if element.state == IntentState.EXCLUDED:
        code = "excluded_tag_unresolved"
        message = f"无法把排除项“{element.original_text}”解析为 canonical tag；未将其加入正向提示词。"
    elif element.state in {IntentState.LOCKED, IntentState.REQUIRED}:
        code = "required_tag_unresolved"
        message = f"无法把必需项“{element.original_text}”安全解析为 canonical tag。"
    else:
        code = "suggested_tag_unresolved"
        message = f"无法解析建议项“{element.original_text}”，已跳过。"
    return CandidateWarning(code=code, message=message, element_ids=[element.id])


def _uses_local_prose_baseline(element: IntentElement, intent: IntentDocument) -> bool:
    return (
        element.type.value == "scene"
        and "local_prose_baseline" in element.notes
        and element.state in {IntentState.LOCKED, IntentState.REQUIRED}
        and bool((intent.scene_plan_en or "").strip())
    )


def _deduplicate(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))
