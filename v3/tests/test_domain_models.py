from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from anima_prompt_studio_v3.domain import (
    CandidateArtist,
    CandidateLane,
    CandidateSet,
    CandidateTag,
    CandidateTagState,
    CandidateVersions,
    ConstraintEdge,
    ConstraintGraph,
    ConstraintKind,
    ElementProvenance,
    IntentDocument,
    IntentElement,
    IntentElementType,
    IntentState,
    PromptCandidate,
    ProvenanceKind,
    RelationKind,
    TagSource,
    intent_state_priority,
    model_json_schema_bundle,
)


def element(
    element_id: str,
    text: str,
    tag: str | None,
    element_type: IntentElementType,
    state: IntentState = IntentState.REQUIRED,
) -> IntentElement:
    return IntentElement(
        id=element_id,
        original_text=text,
        canonical_tag=tag,
        type=element_type,
        state=state,
        confidence=1.0,
        provenance=ElementProvenance(kind=ProvenanceKind.USER),
    )


def intent_document() -> IntentDocument:
    graph = ConstraintGraph(
        elements=[
            element("e_subject", "一个女孩", "1girl", IntentElementType.SUBJECT),
            element("e_maid", "女仆装", "maid", IntentElementType.CLOTHING),
            element("e_hat", "不要帽子", "hat", IntentElementType.CLOTHING, IntentState.EXCLUDED),
        ],
        edges=[
            ConstraintEdge(
                id="c_wearing",
                source_element_id="e_subject",
                target_element_id="e_maid",
                kind=ConstraintKind.RELATION,
                relation=RelationKind.WEARING,
                reason="女孩穿着女仆装",
            )
        ],
    )
    return IntentDocument(source_text="一个穿女仆装的女孩，不要帽子", source_language="zh", graph=graph)


def versions(algorithm: str = "literal-v1") -> CandidateVersions:
    return CandidateVersions(
        data_pack="anima-v3-test-r1",
        algorithm=algorithm,
        templates="anima-template-v1",
        model_profile="anima-base-v1",
    )


def literal_candidate() -> PromptCandidate:
    return PromptCandidate(
        id="candidate_literal",
        lane=CandidateLane.LITERAL,
        title="高保真基准",
        positive_prompt="1girl, maid",
        negative_prompt="hat",
        tags=[
            CandidateTag(
                name="1girl",
                rendered="1girl",
                state=CandidateTagState.REQUIRED,
                source=TagSource.EXACT,
                source_element_ids=["e_subject"],
                reason="用户明确要求单个女孩",
            ),
            CandidateTag(
                name="maid",
                rendered="maid",
                state=CandidateTagState.REQUIRED,
                source=TagSource.EXACT,
                source_element_ids=["e_maid"],
                reason="用户明确要求女仆装",
            ),
        ],
        preserved_element_ids=["e_subject", "e_maid"],
        versions=versions(),
    )


def conservative_candidate() -> PromptCandidate:
    return PromptCandidate(
        id="candidate_conservative",
        lane=CandidateLane.CONSERVATIVE,
        title="保守增强",
        positive_prompt="1girl, maid, maid apron",
        negative_prompt="hat",
        tags=[
            *deepcopy(literal_candidate().tags),
            CandidateTag(
                name="maid_apron",
                rendered="maid apron",
                state=CandidateTagState.AUTOMATIC,
                source=TagSource.COOCCURRENCE,
                source_element_ids=["e_maid"],
                reason="与 maid 高置信共现",
                raw_score=0.73,
                display_score=1.0,
                data_pack_id="anima-v3-test-r1",
                algorithm_version="npmi-v1",
            ),
        ],
        preserved_element_ids=["e_subject", "e_maid"],
        score_breakdown={"fidelity": 1.0, "recommendation": 0.73},
        versions=versions("conservative-v1"),
    )


def test_candidate_set_round_trip_and_schema_export() -> None:
    bundle = CandidateSet(intent=intent_document(), candidates=[literal_candidate(), conservative_candidate()])

    loaded = CandidateSet.model_validate_json(bundle.model_dump_json())
    schemas = model_json_schema_bundle()

    assert loaded == bundle
    assert loaded.candidates[0].lane == CandidateLane.LITERAL
    assert "intent_document" in schemas
    assert "candidate_set" in schemas


def test_constraint_priority_is_frozen() -> None:
    ordered = [
        IntentState.LOCKED,
        IntentState.EXCLUDED,
        IntentState.REQUIRED,
        IntentState.USER_SELECTED,
        IntentState.SUGGESTED,
        IntentState.AUTOMATIC,
    ]
    assert [intent_state_priority(item) for item in ordered] == sorted(
        [intent_state_priority(item) for item in ordered], reverse=True
    )


def test_constraint_graph_reports_required_excluded_conflicts() -> None:
    graph = ConstraintGraph(
        elements=[
            element("e_required", "帽子", "hat", IntentElementType.CLOTHING),
            element("e_excluded", "不要帽子", "hat", IntentElementType.CLOTHING, IntentState.EXCLUDED),
        ]
    )

    assert graph.find_conflicts()[0].code == "same_tag_required_and_excluded"
    with pytest.raises(ValidationError, match="未解决的约束冲突"):
        CandidateSet(intent=IntentDocument(source_text="帽子但不要帽子", source_language="zh", graph=graph), candidates=[literal_candidate()])


def test_constraint_graph_rejects_dangling_edges() -> None:
    with pytest.raises(ValidationError, match="不存在的 element"):
        ConstraintGraph(
            elements=[element("e_subject", "女孩", "1girl", IntentElementType.SUBJECT)],
            edges=[
                ConstraintEdge(
                    id="c_missing",
                    source_element_id="e_subject",
                    target_element_id="e_missing",
                    kind=ConstraintKind.REQUIRES,
                    reason="测试悬空引用",
                )
            ],
        )


def test_literal_candidate_rejects_recommendations_and_artists() -> None:
    payload = literal_candidate().model_dump()
    payload["tags"].append(conservative_candidate().tags[-1].model_dump())
    with pytest.raises(ValidationError, match="推荐扩展标签"):
        PromptCandidate.model_validate(payload)

    payload = literal_candidate().model_dump()
    payload["artists"] = [
        CandidateArtist(
            name="sample_artist",
            rendered="@sample artist",
            source_element_ids=["e_maid"],
            reason="推荐画师",
            raw_score=0.5,
            display_score=1.0,
            data_pack_id="anima-v3-test-r1",
            algorithm_version="npmi-v1",
        ).model_dump()
    ]
    with pytest.raises(ValidationError, match="不能自动包含画师"):
        PromptCandidate.model_validate(payload)


def test_candidate_set_blocks_excluded_leaks_and_missing_required_elements() -> None:
    leaked = literal_candidate().model_copy(
        update={
            "tags": [
                *literal_candidate().tags,
                CandidateTag(
                    name="hat",
                    rendered="hat",
                    state=CandidateTagState.AUTOMATIC,
                    source=TagSource.SEMANTIC,
                    source_element_ids=["e_maid"],
                    reason="错误扩展",
                ),
            ]
        }
    )
    with pytest.raises(ValidationError, match="excluded 标签"):
        CandidateSet(intent=intent_document(), candidates=[leaked])

    missing = literal_candidate().model_copy(update={"preserved_element_ids": ["e_subject"]})
    with pytest.raises(ValidationError, match="未保留或报告必需 element"):
        CandidateSet(intent=intent_document(), candidates=[missing])


def test_automatic_tags_require_traceability() -> None:
    with pytest.raises(ValidationError, match="source_element_ids"):
        CandidateTag(
            name="maid_apron",
            rendered="maid apron",
            state=CandidateTagState.AUTOMATIC,
            source=TagSource.COOCCURRENCE,
            reason="缺少来源",
            raw_score=0.7,
            data_pack_id="pack",
            algorithm_version="npmi-v1",
        )
