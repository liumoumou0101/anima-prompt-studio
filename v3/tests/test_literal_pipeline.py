from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from anima_prompt_studio_v3.core import (
    LiteralCandidateGenerator,
    LiteralGenerationError,
    HybridLaneGenerator,
    LiteralMapper,
    LiteralMatchKind,
    ModelProfile,
    ModelProfileRegistry,
    RecommendationLaneGenerator,
    RecommendationPolicy,
    CandidateValidationError,
    CandidateValidator,
    StaticBenchmarkRunner,
    StaticBenchmarkSuite,
    render_canonical_tag,
)
from anima_prompt_studio_v3.data import (
    DataPackSnapshot,
    ReferenceBuildInputs,
    ReferenceDatabaseBuilder,
    ReferenceDataStore,
    UpstreamSource,
)
from anima_prompt_studio_v3.domain import (
    ConstraintGraph,
    ConstraintEdge,
    ConstraintKind,
    ElementProvenance,
    IntentDocument,
    IntentElement,
    IntentElementType,
    IntentState,
    ProvenanceKind,
    RelationKind,
    TagSource,
)


FIXTURES = Path(__file__).parent / "fixtures" / "upstream_current"
BENCHMARKS = Path(__file__).parent.parent / "benchmarks"
SEARCH_COMMIT = "0636f762694fc436b4ac472cf59b85d172eaaac4"


@pytest.fixture
def store(tmp_path: Path):
    builder = ReferenceDatabaseBuilder(
        ReferenceBuildInputs(
            tags=FIXTURES / "tags_enhanced.csv",
            aliases=FIXTURES / "tag_aliases.csv",
            tag_cooccurrence=FIXTURES / "cooccurrence_clean.csv",
            artist_cooccurrence=FIXTURES / "tag_artist_cooc.csv",
            tag_groups=FIXTURES / "tag_groups.json",
        ),
        pack_id="anima-v3-literal-test-r1",
        snapshot=DataPackSnapshot(
            target_cutoff=date(2025, 9, 30),
            cutoff_mode="approximate",
            source_observed_at=date(2026, 8, 25),
            corpus_size=100_000,
            corpus_size_mode="estimated",
        ),
        sources=[
            UpstreamSource(
                name="DanbooruSearchOnline",
                repository="https://github.com/SuzumiyaAkizuki/DanbooruSearchOnline",
                commit=SEARCH_COMMIT,
                license="GPL-3.0",
            )
        ],
    )
    database = tmp_path / "reference.db"
    builder.build(database, tmp_path / "data-pack.json")
    with ReferenceDataStore(database) as opened:
        yield opened


def element(
    element_id: str,
    text: str,
    *,
    canonical: str | None = None,
    state: IntentState = IntentState.REQUIRED,
) -> IntentElement:
    return IntentElement(
        id=element_id,
        original_text=text,
        canonical_tag=canonical,
        type=IntentElementType.CLOTHING,
        state=state,
        confidence=1.0,
        provenance=ElementProvenance(kind=ProvenanceKind.USER),
    )


def intent() -> IntentDocument:
    return IntentDocument(
        source_text="女仆装、双马尾，不要金发，并保留复杂左右互动",
        source_language="zh",
        graph=ConstraintGraph(
            elements=[
                element("e_maid", "女仆装", canonical="maid_uniform", state=IntentState.LOCKED),
                element("e_hair", "双马尾"),
                element("e_excluded", "不要金发", canonical="blonde_hair", state=IntentState.EXCLUDED),
                element("e_relation", "复杂左右互动"),
            ]
        ),
    )


def test_builtin_profiles_are_packaged_and_variant_safe() -> None:
    registry = ModelProfileRegistry.built_in()

    assert [profile.id for profile in registry.all()] == [
        "anima_aesthetic_v1",
        "anima_base_v1",
        "anima_turbo_v1",
    ]
    assert registry.get("anima_base_v1").positive_prefix == ("score_7",)
    assert registry.get("anima_aesthetic_v1").positive_prefix == ()
    assert registry.get("anima_turbo_v1").negative_prompt == ()

    invalid = registry.get("anima_aesthetic_v1").model_dump()
    invalid["positive_prefix"] = ["score_7"]
    with pytest.raises(ValidationError, match="不能默认加入 score"):
        ModelProfile.model_validate(invalid)


def test_literal_mapper_resolves_alias_and_exact_chinese(store: ReferenceDataStore) -> None:
    mapper = LiteralMapper(store)

    alias = mapper.map_element(element("e_alias", "女仆装", canonical="maid_uniform"))
    chinese = mapper.map_element(element("e_chinese", "双马尾"))

    assert alias is not None
    assert alias.canonical_name == "maid"
    assert alias.match_kind == LiteralMatchKind.ALIAS
    assert chinese is not None
    assert chinese.canonical_name == "twintails"
    assert chinese.match_kind == LiteralMatchKind.CHINESE


def test_base_literal_candidate_is_deterministic_and_traceable(store: ReferenceDataStore) -> None:
    profile = ModelProfileRegistry.built_in().get("anima_base_v1")
    generator = LiteralCandidateGenerator(store)

    first = generator.generate(intent(), profile)
    second = generator.generate(intent(), profile)
    candidate = first.candidates[0]

    assert first == second
    assert candidate.positive_prompt == "score_7, maid, twintails"
    assert candidate.negative_prompt.endswith("blonde hair")
    assert [tag.name for tag in candidate.tags] == ["maid", "twintails"]
    assert candidate.tags[0].source == TagSource.ALIAS
    assert candidate.tags[0].removable is False
    assert candidate.tags[1].source == TagSource.EXACT
    assert candidate.preserved_element_ids == ["e_maid", "e_hair"]
    assert candidate.unresolved_element_ids == ["e_relation"]
    assert candidate.warnings[0].code == "required_tag_unresolved"
    assert candidate.versions.data_pack == store.pack_id


def test_aesthetic_and_turbo_render_model_specific_templates(store: ReferenceDataStore) -> None:
    registry = ModelProfileRegistry.built_in()
    generator = LiteralCandidateGenerator(store)

    aesthetic = generator.generate(intent(), registry.get("anima_aesthetic_v1")).candidates[0]
    turbo = generator.generate(intent(), registry.get("anima_turbo_v1")).candidates[0]

    assert aesthetic.positive_prompt == "maid, twintails"
    assert "score_" not in aesthetic.positive_prompt
    assert aesthetic.negative_prompt.endswith("blonde hair")
    assert turbo.positive_prompt == "score_7, maid, twintails"
    assert turbo.negative_prompt == ""
    assert any(warning.code == "negative_prompt_unsupported" for warning in turbo.warnings)
    assert "blonde hair" not in turbo.positive_prompt


def test_canonical_renderer_preserves_only_model_tokens() -> None:
    assert render_canonical_tag("school_uniform") == "school uniform"
    assert render_canonical_tag("score_7") == "score_7"
    assert render_canonical_tag("score_7_up") == "score_7_up"


def test_conservative_lane_adds_only_safe_traceable_tags(store: ReferenceDataStore) -> None:
    profile = ModelProfileRegistry.built_in().get("anima_base_v1")
    literal = LiteralCandidateGenerator(store).generate(intent(), profile)

    bundle = RecommendationLaneGenerator(store).add_conservative(literal, profile)
    conservative = bundle.candidates[-1]

    assert conservative.lane.value == "conservative"
    assert conservative.positive_prompt == "score_7, maid, twintails, frilled apron"
    assert [tag.name for tag in conservative.tags] == ["maid", "twintails", "frilled_apron"]
    added = conservative.tags[-1]
    assert added.source == TagSource.COOCCURRENCE
    assert added.source_element_ids == ["e_maid"]
    assert added.data_pack_id == store.pack_id
    assert "blonde_hair" not in {tag.name for tag in conservative.tags}
    assert not {"hakurei_reimu", "touhou"} & {tag.name for tag in conservative.tags}


def test_artist_lane_adds_one_removable_artist_and_preserves_conservative_tags(
    store: ReferenceDataStore,
) -> None:
    profile = ModelProfileRegistry.built_in().get("anima_base_v1")
    generator = RecommendationLaneGenerator(store)
    bundle = LiteralCandidateGenerator(store).generate(intent(), profile)
    bundle = generator.add_conservative(bundle, profile)

    bundle = generator.add_artist(bundle, profile)
    artist_candidate = bundle.candidates[-1]

    assert [candidate.lane.value for candidate in bundle.candidates] == ["literal", "conservative", "artist"]
    assert len(artist_candidate.artists) == 1
    assert artist_candidate.artists[0].name == "sample_artist_a"
    assert artist_candidate.artists[0].rendered == "@sample artist a"
    assert artist_candidate.artists[0].source_element_ids == ["e_maid", "e_hair"]
    assert artist_candidate.artists[0].removable is True
    assert artist_candidate.positive_prompt.endswith("@sample artist a")
    assert [tag.name for tag in artist_candidate.tags] == ["maid", "twintails", "frilled_apron"]


def test_recommendation_policy_forbids_character_and_copyright_leaks() -> None:
    with pytest.raises(ValidationError, match="自动推荐类别不允许"):
        RecommendationPolicy(allowed_tag_categories={"general", "character", "copyright"})


def test_literal_detects_conflict_after_alias_resolution(store: ReferenceDataStore) -> None:
    conflicting = IntentDocument(
        source_text="需要女仆，但排除女仆制服",
        source_language="zh",
        graph=ConstraintGraph(
            elements=[
                element("e_required_maid", "女仆", canonical="maid"),
                element(
                    "e_excluded_alias",
                    "女仆制服",
                    canonical="maid_uniform",
                    state=IntentState.EXCLUDED,
                ),
            ]
        ),
    )
    profile = ModelProfileRegistry.built_in().get("anima_base_v1")

    with pytest.raises(LiteralGenerationError, match="别名解析后"):
        LiteralCandidateGenerator(store).generate(conflicting, profile)


def relation_intent() -> IntentDocument:
    return IntentDocument(
        source_text="Hakurei Reimu wearing a maid outfit",
        source_language="en",
        graph=ConstraintGraph(
            elements=[
                element("e_reimu", "Hakurei Reimu", canonical="hakurei_reimu"),
                element("e_maid_relation", "maid outfit", canonical="maid"),
            ],
            edges=[
                ConstraintEdge(
                    id="c_reimu_wearing_maid",
                    source_element_id="e_reimu",
                    target_element_id="e_maid_relation",
                    kind=ConstraintKind.RELATION,
                    relation=RelationKind.WEARING,
                    reason="Reimu 穿着女仆装",
                )
            ],
        ),
    )


def test_hybrid_lane_is_created_only_for_explicit_relations(store: ReferenceDataStore) -> None:
    profile = ModelProfileRegistry.built_in().get("anima_base_v1")
    literal_generator = LiteralCandidateGenerator(store)
    hybrid_generator = HybridLaneGenerator(store)

    plain = literal_generator.generate(intent(), profile)
    assert hybrid_generator.add_hybrid(plain, profile) == plain

    related = literal_generator.generate(relation_intent(), profile)
    hybrid = hybrid_generator.add_hybrid(related, profile)
    candidate = hybrid.candidates[-1]

    assert candidate.lane.value == "hybrid"
    assert candidate.positive_prompt == (
        "score_7, hakurei reimu, maid. hakurei reimu wearing maid"
    )
    assert candidate.score_breakdown["relation_phrases"] == 1.0
    assert candidate.warnings[-1].code == "hybrid_relation_phrase"


def test_hybrid_lane_preserves_extracted_scene_plan_without_changing_literal(
    store: ReferenceDataStore,
) -> None:
    profile = ModelProfileRegistry.built_in().get("anima_base_v1")
    parsed_intent = intent().model_copy(update={
        "scene_plan_en": "A maid with twintails stands beneath warm window light."
    })
    literal_bundle = LiteralCandidateGenerator(store).generate(parsed_intent, profile)
    hybrid_bundle = HybridLaneGenerator(store).add_hybrid(literal_bundle, profile)

    literal, hybrid = hybrid_bundle.candidates[0], hybrid_bundle.candidates[-1]
    assert literal.positive_prompt == "score_7, maid, twintails"
    assert hybrid.lane.value == "hybrid"
    assert hybrid.positive_prompt == (
        "score_7, maid, twintails. "
        "A maid with twintails stands beneath warm window light."
    )
    assert hybrid.score_breakdown["scene_plan"] == 1.0
    assert hybrid.warnings[-1].code == "hybrid_scene_plan"
    assert CandidateValidator(store).validate_or_raise(hybrid_bundle, profile).valid is True


def test_validator_accepts_generated_lanes_and_rejects_tampered_prompt(store: ReferenceDataStore) -> None:
    profile = ModelProfileRegistry.built_in().get("anima_base_v1")
    bundle = LiteralCandidateGenerator(store).generate(relation_intent(), profile)
    bundle = RecommendationLaneGenerator(store).add_conservative(bundle, profile)
    bundle = HybridLaneGenerator(store).add_hybrid(bundle, profile)
    validator = CandidateValidator(store)

    report = validator.validate_or_raise(bundle, profile)
    assert report.valid is True
    assert report.error_count == 0

    bad_literal = bundle.candidates[0].model_copy(update={"positive_prompt": "score_7, wrong"})
    tampered = bundle.model_copy(update={"candidates": [bad_literal, *bundle.candidates[1:]]})
    report = validator.validate(tampered, profile)

    assert report.valid is False
    assert report.candidate_reports[0].issues[0].code == "positive_prompt_mismatch"
    with pytest.raises(CandidateValidationError, match="候选验证失败"):
        validator.validate_or_raise(tampered, profile)


def test_validator_blocks_automatic_character_leak(store: ReferenceDataStore) -> None:
    profile = ModelProfileRegistry.built_in().get("anima_base_v1")
    bundle = LiteralCandidateGenerator(store).generate(intent(), profile)
    bundle = RecommendationLaneGenerator(store).add_conservative(bundle, profile)
    conservative = bundle.candidates[-1]
    leaked_tag = conservative.tags[-1].model_copy(
        update={"name": "hakurei_reimu", "rendered": "hakurei reimu"}
    )
    leaked_candidate = conservative.model_copy(
        update={
            "tags": [*conservative.tags[:-1], leaked_tag],
            "positive_prompt": "score_7, maid, twintails, hakurei reimu",
        }
    )
    tampered = bundle.model_copy(update={"candidates": [bundle.candidates[0], leaked_candidate]})

    report = CandidateValidator(store).validate(tampered, profile)
    codes = {issue.code for issue in report.candidate_reports[-1].issues}

    assert report.valid is False
    assert "automatic_category_leak" in codes


def test_static_benchmark_hard_gates_pass_fixture(store: ReferenceDataStore) -> None:
    suite = StaticBenchmarkSuite.load(BENCHMARKS / "static_v1.json")

    report = StaticBenchmarkRunner(store).run(suite)

    assert report.passed is True
    assert report.required_retention == 1.0
    assert report.excluded_leak_count == 0
    assert report.protected_category_leak_count == 0
    assert report.validation_error_count == 0
    assert len(report.cases) == 4
