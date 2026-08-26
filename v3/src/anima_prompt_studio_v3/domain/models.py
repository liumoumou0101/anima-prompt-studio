from __future__ import annotations

import math
import re
from collections import defaultdict
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ElementId = Annotated[str, Field(pattern=r"^e_[A-Za-z0-9._-]+$")]
ConstraintId = Annotated[str, Field(pattern=r"^c_[A-Za-z0-9._-]+$")]
CandidateId = Annotated[str, Field(pattern=r"^candidate_[A-Za-z0-9._-]+$")]


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class IntentElementType(StrEnum):
    SUBJECT = "subject"
    CHARACTER = "character"
    APPEARANCE = "appearance"
    CLOTHING = "clothing"
    ACTION = "action"
    OBJECT = "object"
    SCENE = "scene"
    COMPOSITION = "composition"
    STYLE = "style"
    QUALITY = "quality"
    RELATION = "relation"
    OTHER = "other"


class IntentState(StrEnum):
    LOCKED = "locked"
    EXCLUDED = "excluded"
    REQUIRED = "required"
    USER_SELECTED = "user_selected"
    SUGGESTED = "suggested"
    AUTOMATIC = "automatic"


INTENT_STATE_PRIORITY: dict[IntentState, int] = {
    IntentState.LOCKED: 600,
    IntentState.EXCLUDED: 500,
    IntentState.REQUIRED: 400,
    IntentState.USER_SELECTED: 300,
    IntentState.SUGGESTED: 200,
    IntentState.AUTOMATIC: 100,
}


class ProvenanceKind(StrEnum):
    USER = "user"
    EXACT = "exact"
    ALIAS = "alias"
    TRANSLATION = "translation"
    SEMANTIC = "semantic"
    MANUAL = "manual"


class ConstraintKind(StrEnum):
    REQUIRES = "requires"
    EXCLUDES = "excludes"
    CONFLICTS_WITH = "conflicts_with"
    RELATION = "relation"


class RelationKind(StrEnum):
    WEARING = "wearing"
    HOLDING = "holding"
    LOOKING_AT = "looking_at"
    INTERACTING_WITH = "interacting_with"
    LEFT_OF = "left_of"
    RIGHT_OF = "right_of"
    IN_FRONT_OF = "in_front_of"
    BEHIND = "behind"
    INSIDE = "inside"
    CUSTOM = "custom"


class CandidateLane(StrEnum):
    LITERAL = "literal"
    CONSERVATIVE = "conservative"
    ARTIST = "artist"
    HYBRID = "hybrid"


class CandidateTagState(StrEnum):
    LOCKED = "locked"
    REQUIRED = "required"
    USER_SELECTED = "user_selected"
    SUGGESTED = "suggested"
    AUTOMATIC = "automatic"


class TagSource(StrEnum):
    USER = "user"
    EXACT = "exact"
    ALIAS = "alias"
    TRANSLATION = "translation"
    SEMANTIC = "semantic"
    COOCCURRENCE = "cooccurrence"
    ARTIST = "artist"


class SourceSpan(DomainModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def end_must_follow_start(self) -> "SourceSpan":
        if self.end <= self.start:
            raise ValueError("source span 的 end 必须大于 start。")
        return self


class ElementProvenance(DomainModel):
    kind: ProvenanceKind
    detail: str | None = None


class IntentElement(DomainModel):
    id: ElementId
    source_span: SourceSpan | None = None
    original_text: str = Field(min_length=1)
    canonical_tag: str | None = None
    entity_id: str | None = None
    type: IntentElementType
    cardinality: int | None = Field(default=None, ge=1)
    state: IntentState = IntentState.REQUIRED
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: ElementProvenance
    notes: list[str] = Field(default_factory=list)

    @field_validator("canonical_tag")
    @classmethod
    def validate_canonical_tag(cls, value: str | None) -> str | None:
        return _canonical_tag(value) if value is not None else None


class ConstraintEdge(DomainModel):
    id: ConstraintId
    source_element_id: ElementId
    target_element_id: ElementId
    kind: ConstraintKind
    relation: RelationKind | None = None
    custom_relation: str | None = None
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def relation_fields_match_kind(self) -> "ConstraintEdge":
        if self.source_element_id == self.target_element_id:
            raise ValueError("constraint 不能指向同一个 element。")
        if self.kind == ConstraintKind.RELATION and self.relation is None:
            raise ValueError("relation constraint 必须声明 relation。")
        if self.kind != ConstraintKind.RELATION and (self.relation is not None or self.custom_relation is not None):
            raise ValueError("非 relation constraint 不能携带 relation 字段。")
        if self.relation == RelationKind.CUSTOM and not self.custom_relation:
            raise ValueError("custom relation 必须提供 custom_relation。")
        if self.relation != RelationKind.CUSTOM and self.custom_relation is not None:
            raise ValueError("只有 custom relation 可以提供 custom_relation。")
        return self


class ConstraintConflict(DomainModel):
    code: str
    element_ids: list[ElementId] = Field(min_length=1)
    message: str


class ConstraintGraph(DomainModel):
    elements: list[IntentElement]
    edges: list[ConstraintEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def ids_are_unique_and_edges_are_resolved(self) -> "ConstraintGraph":
        element_ids = [element.id for element in self.elements]
        if len(element_ids) != len(set(element_ids)):
            raise ValueError("IntentElement id 必须唯一。")
        edge_ids = [edge.id for edge in self.edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("ConstraintEdge id 必须唯一。")
        known = set(element_ids)
        for edge in self.edges:
            missing = {edge.source_element_id, edge.target_element_id} - known
            if missing:
                raise ValueError(f"constraint 引用了不存在的 element：{sorted(missing)}")
        return self

    def find_conflicts(self) -> list[ConstraintConflict]:
        conflicts: list[ConstraintConflict] = []
        by_tag: dict[str, list[IntentElement]] = defaultdict(list)
        by_id = {element.id: element for element in self.elements}
        for element in self.elements:
            if element.canonical_tag:
                by_tag[element.canonical_tag].append(element)

        positive_states = {
            IntentState.LOCKED,
            IntentState.REQUIRED,
            IntentState.USER_SELECTED,
            IntentState.SUGGESTED,
            IntentState.AUTOMATIC,
        }
        for tag, elements in by_tag.items():
            excluded = [element for element in elements if element.state == IntentState.EXCLUDED]
            positive = [element for element in elements if element.state in positive_states]
            if excluded and positive:
                ids = [element.id for element in excluded + positive]
                conflicts.append(
                    ConstraintConflict(
                        code="same_tag_required_and_excluded",
                        element_ids=list(dict.fromkeys(ids)),
                        message=f"标签 {tag} 同时被要求和排除。",
                    )
                )

        for edge in self.edges:
            source = by_id[edge.source_element_id]
            target = by_id[edge.target_element_id]
            source_active = source.state in positive_states
            target_active = target.state in positive_states
            target_excluded = target.state == IntentState.EXCLUDED
            if edge.kind == ConstraintKind.REQUIRES and source_active and target_excluded:
                conflicts.append(
                    ConstraintConflict(
                        code="required_dependency_excluded",
                        element_ids=[source.id, target.id],
                        message=edge.reason,
                    )
                )
            elif edge.kind in {ConstraintKind.EXCLUDES, ConstraintKind.CONFLICTS_WITH} and source_active and target_active:
                conflicts.append(
                    ConstraintConflict(
                        code="active_elements_conflict",
                        element_ids=[source.id, target.id],
                        message=edge.reason,
                    )
                )
        return conflicts


class IntentWarning(DomainModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    element_ids: list[ElementId] = Field(default_factory=list)


class IntentDocument(DomainModel):
    source_text: str = Field(min_length=1)
    source_language: str = Field(pattern=r"^(zh|en|mixed)$")
    translated_text: str | None = None
    scene_plan_en: str | None = Field(default=None, max_length=2400)
    scene_negative_en: list[str] = Field(default_factory=list, max_length=100)
    graph: ConstraintGraph
    warnings: list[IntentWarning] = Field(default_factory=list)

    @model_validator(mode="after")
    def source_spans_fit_source_text(self) -> "IntentDocument":
        for element in self.graph.elements:
            if element.source_span and element.source_span.end > len(self.source_text):
                raise ValueError(f"source span 超出输入长度：{element.id}")
        return self


class CandidateVersions(DomainModel):
    data_pack: str = Field(min_length=1)
    algorithm: str = Field(min_length=1)
    templates: str = Field(min_length=1)
    model_profile: str = Field(min_length=1)


class CandidateTag(DomainModel):
    name: str
    rendered: str = Field(min_length=1)
    state: CandidateTagState
    source: TagSource
    source_element_ids: list[ElementId] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    raw_score: float | None = None
    display_score: float | None = Field(default=None, ge=0.0, le=1.0)
    data_pack_id: str | None = None
    algorithm_version: str | None = None
    removable: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _canonical_tag(value)

    @field_validator("raw_score")
    @classmethod
    def raw_score_must_be_finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("raw_score 必须是有限数值。")
        return value

    @model_validator(mode="after")
    def traceability_is_complete(self) -> "CandidateTag":
        if self.source != TagSource.USER and not self.source_element_ids:
            raise ValueError("自动或映射标签必须记录 source_element_ids。")
        if self.source == TagSource.COOCCURRENCE:
            if self.raw_score is None or not self.data_pack_id or not self.algorithm_version:
                raise ValueError("共现标签必须记录分数、数据包和算法版本。")
        if self.state == CandidateTagState.LOCKED and self.removable:
            raise ValueError("locked 标签不能标记为 removable。")
        return self


class CandidateArtist(DomainModel):
    name: str
    rendered: str
    source: TagSource = TagSource.ARTIST
    source_element_ids: list[ElementId] = Field(min_length=1)
    reason: str = Field(min_length=1)
    raw_score: float | None = None
    display_score: float | None = Field(default=None, ge=0.0, le=1.0)
    data_pack_id: str | None = None
    algorithm_version: str | None = None
    removable: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _canonical_tag(value)

    @model_validator(mode="after")
    def artist_fields_are_consistent(self) -> "CandidateArtist":
        if self.source not in {TagSource.ARTIST, TagSource.USER}:
            raise ValueError("画师来源只能是 artist 或 user。")
        if not self.rendered.startswith("@") or len(self.rendered) == 1:
            raise ValueError("画师 rendered 必须使用 @name 格式。")
        if self.raw_score is not None and not math.isfinite(self.raw_score):
            raise ValueError("raw_score 必须是有限数值。")
        if self.source == TagSource.ARTIST and (
            self.raw_score is None or not self.data_pack_id or not self.algorithm_version
        ):
            raise ValueError("推荐画师必须记录分数、数据包和算法版本。")
        return self


class CandidateWarning(DomainModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    element_ids: list[ElementId] = Field(default_factory=list)


class PromptCandidate(DomainModel):
    id: CandidateId
    lane: CandidateLane
    title: str = Field(min_length=1)
    positive_prompt: str = Field(min_length=1)
    negative_prompt: str = ""
    artists: list[CandidateArtist] = Field(default_factory=list)
    tags: list[CandidateTag]
    preserved_element_ids: list[ElementId] = Field(default_factory=list)
    unresolved_element_ids: list[ElementId] = Field(default_factory=list)
    warnings: list[CandidateWarning] = Field(default_factory=list)
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    versions: CandidateVersions

    @model_validator(mode="after")
    def candidate_invariants(self) -> "PromptCandidate":
        tag_names = [tag.name for tag in self.tags]
        if len(tag_names) != len(set(tag_names)):
            raise ValueError("候选中 canonical tag 不能重复。")
        artist_names = [artist.name for artist in self.artists]
        if len(artist_names) != len(set(artist_names)):
            raise ValueError("候选中画师不能重复。")
        if set(self.preserved_element_ids) & set(self.unresolved_element_ids):
            raise ValueError("同一个 element 不能既 preserved 又 unresolved。")
        if any(not math.isfinite(value) for value in self.score_breakdown.values()):
            raise ValueError("score_breakdown 必须只包含有限数值。")
        if self.lane == CandidateLane.LITERAL:
            if self.artists:
                raise ValueError("literal 候选不能自动包含画师。")
            forbidden_sources = {TagSource.COOCCURRENCE, TagSource.ARTIST}
            if any(tag.source in forbidden_sources for tag in self.tags):
                raise ValueError("literal 候选不能包含推荐扩展标签。")
        return self


class CandidateSet(DomainModel):
    intent: IntentDocument
    candidates: list[PromptCandidate] = Field(min_length=1)

    @model_validator(mode="after")
    def candidate_set_invariants(self) -> "CandidateSet":
        conflicts = self.intent.graph.find_conflicts()
        if conflicts:
            ids = sorted({item for conflict in conflicts for item in conflict.element_ids})
            raise ValueError(f"存在未解决的约束冲突：{ids}")

        candidate_ids = [candidate.id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("PromptCandidate id 必须唯一。")
        literal_candidates = [candidate for candidate in self.candidates if candidate.lane == CandidateLane.LITERAL]
        if len(literal_candidates) != 1:
            raise ValueError("每个 CandidateSet 必须且只能包含一个 literal 候选。")

        known_ids = {element.id for element in self.intent.graph.elements}
        excluded_tags = {
            element.canonical_tag
            for element in self.intent.graph.elements
            if element.state == IntentState.EXCLUDED and element.canonical_tag
        }
        required_ids = {
            element.id
            for element in self.intent.graph.elements
            if element.state in {IntentState.LOCKED, IntentState.REQUIRED}
        }
        for candidate in self.candidates:
            references = set(candidate.preserved_element_ids) | set(candidate.unresolved_element_ids)
            references.update(item for tag in candidate.tags for item in tag.source_element_ids)
            references.update(item for artist in candidate.artists for item in artist.source_element_ids)
            references.update(item for warning in candidate.warnings for item in warning.element_ids)
            missing = references - known_ids
            if missing:
                raise ValueError(f"候选引用了不存在的 element：{sorted(missing)}")
            leaked = excluded_tags & {tag.name for tag in candidate.tags}
            if leaked:
                raise ValueError(f"候选重新引入了 excluded 标签：{sorted(leaked)}")

        literal = literal_candidates[0]
        accounted = set(literal.preserved_element_ids) | set(literal.unresolved_element_ids)
        missing_required = required_ids - accounted
        if missing_required:
            raise ValueError(f"literal 未保留或报告必需 element：{sorted(missing_required)}")

        version_keys = {
            (
                candidate.versions.data_pack,
                candidate.versions.templates,
                candidate.versions.model_profile,
            )
            for candidate in self.candidates
        }
        if len(version_keys) != 1:
            raise ValueError("同一 CandidateSet 的数据包、模板和模型配置版本必须一致。")
        return self


def intent_state_priority(state: IntentState) -> int:
    return INTENT_STATE_PRIORITY[state]


def _canonical_tag(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("canonical tag 不能为空。")
    if normalized != normalized.lower() or normalized.startswith("@"):
        raise ValueError("canonical tag 必须小写且不包含 @。")
    if re.search(r"\s", normalized) or any(character in normalized for character in "\r\n\t"):
        raise ValueError("canonical tag 不能包含空白字符。")
    return normalized


def model_json_schema_bundle() -> dict[str, Any]:
    """Expose stable schemas for later API DTO and frontend generation work."""

    return {
        "intent_document": IntentDocument.model_json_schema(),
        "candidate_set": CandidateSet.model_json_schema(),
    }
