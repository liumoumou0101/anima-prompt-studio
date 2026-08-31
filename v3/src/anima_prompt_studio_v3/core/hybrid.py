from __future__ import annotations

from ..data import ReferenceDataStore
from ..domain import (
    CandidateLane,
    CandidateSet,
    CandidateVersions,
    CandidateWarning,
    ConstraintKind,
    IntentState,
    PromptCandidate,
    RelationKind,
)
from .literal import LiteralMapper
from .profiles import ModelProfile


HYBRID_ALGORITHM_VERSION = "hybrid-lane-v2"


class HybridLaneGenerator:
    """Add reviewed scene-plan prose and explicit relation phrases to a tag baseline."""

    def __init__(self, store: ReferenceDataStore) -> None:
        self.store = store
        self.mapper = LiteralMapper(store)

    def add_hybrid(self, bundle: CandidateSet, profile: ModelProfile) -> CandidateSet:
        if any(candidate.lane == CandidateLane.HYBRID for candidate in bundle.candidates):
            return bundle
        expected_profile = bundle.candidates[0].versions.model_profile
        if profile.id != expected_profile:
            raise ValueError(f"候选模型配置为 {expected_profile}，不能使用 {profile.id} 渲染。")

        elements = {element.id: element for element in bundle.intent.graph.elements}
        phrases: list[str] = []
        phrase_element_ids: list[str] = []
        for edge in bundle.intent.graph.edges:
            if edge.kind != ConstraintKind.RELATION or edge.relation is None:
                continue
            if (
                elements[edge.source_element_id].state == IntentState.EXCLUDED
                or elements[edge.target_element_id].state == IntentState.EXCLUDED
            ):
                continue
            source_mapping = self.mapper.map_element(elements[edge.source_element_id])
            target_mapping = self.mapper.map_element(elements[edge.target_element_id])
            if source_mapping is None or target_mapping is None:
                continue
            phrase = _render_relation(
                source_mapping.rendered,
                target_mapping.rendered,
                edge.relation,
                edge.custom_relation,
            )
            if phrase not in phrases:
                phrases.append(phrase)
                phrase_element_ids.extend([edge.source_element_id, edge.target_element_id])

        scene_plan = (bundle.intent.scene_plan_en or "").strip()
        if not phrases and not scene_plan:
            return bundle
        base = next(
            (candidate for candidate in bundle.candidates if candidate.lane == CandidateLane.CONSERVATIVE),
            next(candidate for candidate in bundle.candidates if candidate.lane == CandidateLane.LITERAL),
        )
        if scene_plan and base.score_breakdown.get("prose_baseline"):
            return bundle
        relation_text = "; ".join(phrases)
        prose_parts = [part for part in (scene_plan, relation_text) if part]
        warnings = [warning.model_copy(deep=True) for warning in base.warnings]
        if scene_plan:
            warnings.append(CandidateWarning(
                code="hybrid_scene_plan",
                message="保留自然语言抽取器给出的英文画面计划；该内容不会改写 literal 候选。",
            ))
        if relation_text:
            warnings.append(CandidateWarning(
                code="hybrid_relation_phrase",
                message=f"使用自然语言明确表达关系：{relation_text}",
                element_ids=list(dict.fromkeys(phrase_element_ids)),
            ))
        candidate = PromptCandidate(
            id="candidate_hybrid",
            lane=CandidateLane.HYBRID,
            title="画面计划混合表达" if scene_plan else "关系混合表达",
            positive_prompt=f"{base.positive_prompt}. {'; '.join(prose_parts)}",
            negative_prompt=base.negative_prompt,
            tags=[tag.model_copy(deep=True) for tag in base.tags],
            preserved_element_ids=list(dict.fromkeys([*base.preserved_element_ids, *phrase_element_ids])),
            unresolved_element_ids=[
                element_id
                for element_id in base.unresolved_element_ids
                if element_id not in phrase_element_ids
            ],
            warnings=warnings,
            score_breakdown={
                **base.score_breakdown,
                "scene_plan": float(bool(scene_plan)),
                "relation_phrases": float(len(phrases)),
            },
            versions=CandidateVersions(
                data_pack=base.versions.data_pack,
                algorithm=HYBRID_ALGORITHM_VERSION,
                templates=base.versions.templates,
                model_profile=base.versions.model_profile,
            ),
        )
        return CandidateSet(intent=bundle.intent, candidates=[*bundle.candidates, candidate])


def _render_relation(
    source: str,
    target: str,
    relation: RelationKind,
    custom_relation: str | None,
) -> str:
    templates = {
        RelationKind.WEARING: "{source} wearing {target}",
        RelationKind.HOLDING: "{source} holding {target}",
        RelationKind.LOOKING_AT: "{source} looking at {target}",
        RelationKind.INTERACTING_WITH: "{source} interacting with {target}",
        RelationKind.LEFT_OF: "{source} to the left of {target}",
        RelationKind.RIGHT_OF: "{source} to the right of {target}",
        RelationKind.IN_FRONT_OF: "{source} in front of {target}",
        RelationKind.BEHIND: "{source} behind {target}",
        RelationKind.INSIDE: "{source} inside {target}",
    }
    if relation == RelationKind.CUSTOM:
        if not custom_relation:
            raise ValueError("custom relation 缺少文本。")
        return f"{source} and {target} {custom_relation}"
    return templates[relation].format(source=source, target=target)
