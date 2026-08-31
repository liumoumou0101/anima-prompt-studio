from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..data import ReferenceDataStore
from ..domain import (
    CandidateArtist,
    CandidateLane,
    CandidateSet,
    CandidateTag,
    CandidateTagState,
    CandidateVersions,
    IntentElement,
    IntentState,
    PromptCandidate,
    TagSource,
)
from .literal import LiteralMapper, render_canonical_tag
from .profiles import ModelProfile


CONSERVATIVE_ALGORITHM_VERSION = "conservative-lane-v1"
ARTIST_ALGORITHM_VERSION = "artist-lane-v1"


class RecommendationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_tag_additions: int = Field(default=3, ge=0, le=20)
    min_tag_cooc_count: int = Field(default=20, ge=1)
    min_tag_raw_score: float = Field(default=0.1, ge=-1.0, le=1.0)
    allowed_tag_categories: frozenset[str] = frozenset({"general", "meta"})
    max_artists: int = Field(default=1, ge=0, le=1)
    min_artist_cooc_count: int = Field(default=5, ge=1)

    @model_validator(mode="after")
    def character_and_copyright_are_not_automatic(self) -> "RecommendationPolicy":
        forbidden = {"character", "copyright", "artist"} & self.allowed_tag_categories
        if forbidden:
            raise ValueError(f"自动推荐类别不允许包含：{sorted(forbidden)}")
        return self


class RecommendationLaneGenerator:
    def __init__(self, store: ReferenceDataStore, policy: RecommendationPolicy | None = None) -> None:
        self.store = store
        self.policy = policy or RecommendationPolicy()

    def add_conservative(self, bundle: CandidateSet, profile: ModelProfile) -> CandidateSet:
        self._validate_profile(bundle, profile)
        if any(candidate.lane == CandidateLane.CONSERVATIVE for candidate in bundle.candidates):
            return bundle
        if self.policy.max_tag_additions == 0:
            return bundle

        literal = _candidate_for_lane(bundle, CandidateLane.LITERAL)
        excluded: set[str] = set()
        for element in bundle.intent.graph.elements:
            if element.state != IntentState.EXCLUDED:
                continue
            mapping = self._literal_mapping(element)
            if mapping is not None:
                excluded.add(mapping)
            elif element.canonical_tag:
                excluded.add(element.canonical_tag)
        seed_names = [tag.name for tag in literal.tags]
        existing_names = {tag.name for tag in literal.tags}
        source_elements = _tag_source_elements(literal)
        related = self.store.related_tags(
            seed_names,
            excluded=excluded,
            categories=set(self.policy.allowed_tag_categories),
            limit=200,
        )

        additions: list[CandidateTag] = []
        for result in related:
            if len(additions) >= self.policy.max_tag_additions:
                break
            if result["name"] in existing_names or result["name"] in excluded:
                continue
            if result["cooc_count"] < self.policy.min_tag_cooc_count:
                continue
            if result["raw_score"] < self.policy.min_tag_raw_score:
                continue
            element_ids = _element_ids_for_sources(result["sources"], source_elements)
            if not element_ids:
                continue
            additions.append(
                CandidateTag(
                    name=result["name"],
                    rendered=render_canonical_tag(result["name"]),
                    state=CandidateTagState.AUTOMATIC,
                    source=TagSource.COOCCURRENCE,
                    source_element_ids=element_ids,
                    reason=f"与 {', '.join(result['sources'])} 保守共现",
                    raw_score=result["raw_score"],
                    display_score=result["display_score"],
                    data_pack_id=result["data_pack_id"],
                    algorithm_version=result["algorithm_version"],
                )
            )

        if not additions:
            return bundle
        tags = [tag.model_copy(deep=True) for tag in literal.tags] + additions
        candidate = PromptCandidate(
            id="candidate_conservative",
            lane=CandidateLane.CONSERVATIVE,
            title="保守增强",
            positive_prompt=_render_positive(profile, tags),
            negative_prompt=literal.negative_prompt,
            tags=tags,
            preserved_element_ids=list(literal.preserved_element_ids),
            unresolved_element_ids=list(literal.unresolved_element_ids),
            warnings=[warning.model_copy(deep=True) for warning in literal.warnings],
            score_breakdown={
                **literal.score_breakdown,
                "recommended_tags": float(len(additions)),
                "recommendation_score": round(sum(tag.raw_score or 0.0 for tag in additions), 6),
            },
            versions=CandidateVersions(
                data_pack=literal.versions.data_pack,
                algorithm=CONSERVATIVE_ALGORITHM_VERSION,
                templates=literal.versions.templates,
                model_profile=literal.versions.model_profile,
            ),
        )
        return CandidateSet(intent=bundle.intent, candidates=[*bundle.candidates, candidate])

    def add_artist(self, bundle: CandidateSet, profile: ModelProfile) -> CandidateSet:
        self._validate_profile(bundle, profile)
        if any(candidate.lane == CandidateLane.ARTIST for candidate in bundle.candidates):
            return bundle
        if self.policy.max_artists == 0:
            return bundle

        base = next(
            (candidate for candidate in bundle.candidates if candidate.lane == CandidateLane.CONSERVATIVE),
            _candidate_for_lane(bundle, CandidateLane.LITERAL),
        )
        source_elements = _tag_source_elements(base)
        results = self.store.recommend_artists([tag.name for tag in base.tags], limit=50)
        selected = next(
            (
                result
                for result in results
                if result["cooc_count"] >= self.policy.min_artist_cooc_count
                and _element_ids_for_sources(result["sources"], source_elements)
            ),
            None,
        )
        if selected is None:
            return bundle
        element_ids = _element_ids_for_sources(selected["sources"], source_elements)
        artist = CandidateArtist(
            name=selected["name"],
            rendered=selected["render_name"],
            source_element_ids=element_ids,
            reason=f"匹配标签：{', '.join(selected['sources'])}",
            raw_score=selected["raw_score"],
            display_score=selected["display_score"],
            data_pack_id=selected["data_pack_id"],
            algorithm_version=selected["algorithm_version"],
        )
        candidate = PromptCandidate(
            id="candidate_artist",
            lane=CandidateLane.ARTIST,
            title="单画师风格",
            positive_prompt=_render_positive(profile, base.tags, [artist]),
            negative_prompt=base.negative_prompt,
            artists=[artist],
            tags=[tag.model_copy(deep=True) for tag in base.tags],
            preserved_element_ids=list(base.preserved_element_ids),
            unresolved_element_ids=list(base.unresolved_element_ids),
            warnings=[warning.model_copy(deep=True) for warning in base.warnings],
            score_breakdown={
                **base.score_breakdown,
                "artist_score": selected["raw_score"],
                "artist_hit_count": float(selected["hit_count"]),
            },
            versions=CandidateVersions(
                data_pack=base.versions.data_pack,
                algorithm=ARTIST_ALGORITHM_VERSION,
                templates=base.versions.templates,
                model_profile=base.versions.model_profile,
            ),
        )
        return CandidateSet(intent=bundle.intent, candidates=[*bundle.candidates, candidate])

    @staticmethod
    def _validate_profile(bundle: CandidateSet, profile: ModelProfile) -> None:
        expected = bundle.candidates[0].versions.model_profile
        if expected != profile.id:
            raise ValueError(f"候选模型配置为 {expected}，不能使用 {profile.id} 渲染。")

    def _literal_mapping(self, element: IntentElement) -> str | None:
        mapping = LiteralMapper(self.store).map_element(element)
        return mapping.canonical_name if mapping is not None else None


def _candidate_for_lane(bundle: CandidateSet, lane: CandidateLane) -> PromptCandidate:
    try:
        return next(candidate for candidate in bundle.candidates if candidate.lane == lane)
    except StopIteration as exc:
        raise ValueError(f"CandidateSet 缺少 {lane.value} lane。") from exc


def _tag_source_elements(candidate: PromptCandidate) -> dict[str, list[str]]:
    return {tag.name: list(tag.source_element_ids) for tag in candidate.tags}


def _element_ids_for_sources(sources: list[str], source_elements: dict[str, list[str]]) -> list[str]:
    return list(
        dict.fromkeys(
            element_id
            for source in sources
            for element_id in source_elements.get(source, [])
        )
    )


def _render_positive(
    profile: ModelProfile,
    tags: list[CandidateTag],
    artists: list[CandidateArtist] | None = None,
) -> str:
    values = [*profile.positive_prefix, *(tag.rendered for tag in tags)]
    values.extend(artist.rendered for artist in (artists or []))
    return profile.tag_separator.join(dict.fromkeys(values))
