from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from ..core.validation import CandidateSetValidationReport
from ..domain import IntentDocument, IntentElementType, IntentState, PromptCandidate, RelationKind


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _canonical_tag_list(values: list[str], *, field_name: str) -> list[str]:
    normalized: list[str] = []
    for value in values:
        tag = value.strip().lower().replace(" ", "_")
        if not tag or any(character.isspace() for character in tag):
            raise ValueError(f"{field_name} 必须是非空 canonical tag。")
        if tag not in normalized:
            normalized.append(tag)
    return normalized


class SessionExchangeRequest(ApiModel):
    bootstrap_token: str = Field(min_length=20, max_length=256)


class RelatedTagsRequest(ApiModel):
    tags: list[str] = Field(min_length=1, max_length=50)
    excluded: list[str] = Field(default_factory=list, max_length=200)
    categories: list[str] = Field(default_factory=list, max_length=5)
    limit: int = Field(default=20, ge=1, le=100)


class ArtistRecommendRequest(ApiModel):
    tags: list[str] = Field(min_length=1, max_length=50)
    limit: int = Field(default=20, ge=1, le=100)
    ranking: Literal["tag_fit", "volume", "balanced"] | None = None


class ArtistRankingSettingsRequest(ApiModel):
    ranking: Literal["tag_fit", "volume", "balanced"]


class WorkbenchElementInput(ApiModel):
    id: str = Field(pattern=r"^e_[A-Za-z0-9._-]+$")
    text: str = Field(min_length=1, max_length=200)
    canonical_tag: str | None = Field(default=None, max_length=200)
    type: IntentElementType = IntentElementType.OTHER
    state: IntentState = IntentState.REQUIRED


class WorkbenchRelationInput(ApiModel):
    id: str = Field(pattern=r"^c_[A-Za-z0-9._-]+$")
    source_element_id: str = Field(pattern=r"^e_[A-Za-z0-9._-]+$")
    target_element_id: str = Field(pattern=r"^e_[A-Za-z0-9._-]+$")
    relation: RelationKind
    custom_relation: str | None = Field(default=None, min_length=1, max_length=200)
    reason: str = Field(default="用户明确指定关系", min_length=1, max_length=500)


class WorkbenchCandidateRequest(ApiModel):
    source_text: str = Field(min_length=1, max_length=10_000)
    source_language: str = Field(default="mixed", pattern=r"^(zh|en|mixed)$")
    model_profile: str = Field(default="anima_base_v1", min_length=1, max_length=100)
    elements: list[WorkbenchElementInput] = Field(min_length=1, max_length=100)
    relations: list[WorkbenchRelationInput] = Field(default_factory=list, max_length=100)
    selected_tags: list[str] = Field(default_factory=list, max_length=40)
    suppressed_tags: list[str] = Field(default_factory=list, max_length=80)
    translated_text: str | None = Field(default=None, min_length=1, max_length=20_000)

    @field_validator("selected_tags")
    @classmethod
    def selected_tags_are_canonical(cls, values: list[str]) -> list[str]:
        return _canonical_tag_list(values, field_name="selected_tags")

    @field_validator("suppressed_tags")
    @classmethod
    def suppressed_tags_are_canonical(cls, values: list[str]) -> list[str]:
        return _canonical_tag_list(values, field_name="suppressed_tags")


class IntentParseRequest(ApiModel):
    source_text: str = Field(min_length=1, max_length=50_000)
    source_language: str = Field(default="zh", pattern=r"^(zh|en|mixed)$")


class TranslationRequest(ApiModel):
    source_text: str = Field(min_length=1, max_length=10_000)
    direction: Literal["zh_en", "en_zh"] = "zh_en"


class DirectPromptPreviewRequest(ApiModel):
    positive_prompt: str = Field(min_length=1, max_length=20_000)
    negative_prompt: str = Field(default="", max_length=20_000)


class LocalNaturalRelationInput(ApiModel):
    source_entity_id: str = Field(pattern=r"^entity_[A-Za-z0-9._-]+$", max_length=240)
    target_element_id: str = Field(pattern=r"^e_[A-Za-z0-9._-]+$", max_length=200)
    relation: Literal["wearing"]


class LocalNaturalCandidateRequest(ApiModel):
    source_text: str = Field(min_length=1, max_length=10_000)
    excluded_text: str = Field(default="", max_length=10_000)
    model_profile: str = Field(default="anima_aesthetic_v1", min_length=1, max_length=100)
    translated_text: str | None = Field(default=None, min_length=1, max_length=20_000)
    selected_tags: list[str] = Field(default_factory=list, max_length=40)
    suppressed_tags: list[str] = Field(default_factory=list, max_length=80)
    fact_owners: dict[str, str] = Field(default_factory=dict, max_length=100)
    confirmed_relations: list[LocalNaturalRelationInput] = Field(default_factory=list, max_length=100)

    @field_validator("selected_tags")
    @classmethod
    def selected_tags_are_canonical(cls, values: list[str]) -> list[str]:
        return _canonical_tag_list(values, field_name="selected_tags")

    @field_validator("suppressed_tags")
    @classmethod
    def suppressed_tags_are_canonical(cls, values: list[str]) -> list[str]:
        return _canonical_tag_list(values, field_name="suppressed_tags")

    @field_validator("fact_owners")
    @classmethod
    def fact_owners_use_stable_ids(cls, values: dict[str, str]) -> dict[str, str]:
        for fact_id, entity_id in values.items():
            if re.fullmatch(r"e_[A-Za-z0-9._-]+", fact_id) is None:
                raise ValueError("fact_owners 的 key 必须是稳定 element ID。")
            if re.fullmatch(r"entity_[A-Za-z0-9._-]+", entity_id) is None:
                raise ValueError("fact_owners 的 value 必须是稳定 entity ID。")
        return values


class IntentCandidateRequest(ApiModel):
    intent: IntentDocument
    model_profile: str = Field(default="anima_base_v1", min_length=1, max_length=100)


class WorkbenchGenerationSettings(ApiModel):
    preset_id: str = Field(default="stable_baseline", min_length=1, max_length=100)
    aspect: Literal["portrait", "landscape", "square", "custom", "model_default"] = "portrait"
    width: int | None = Field(default=896, ge=64, le=8192)
    height: int | None = Field(default=1152, ge=64, le=8192)
    steps: int | None = Field(default=30, ge=1, le=200)
    cfg: float | None = Field(default=4.0, ge=0, le=30)
    sampler: str | None = Field(default="er_sde", min_length=1, max_length=100)
    scheduler: str | None = Field(default="simple", min_length=1, max_length=100)
    seed: int = Field(default=-1, ge=-1)
    batch_size: int = Field(default=1, ge=1, le=100)
    remote_profile_id: str | None = Field(default=None, max_length=200)
    workflow_profile_id: str | None = Field(default=None, max_length=200)


class WorkspaceDraft(ApiModel):
    positive_text: str = Field(default="", max_length=10_000)
    excluded_text: str = Field(default="", max_length=10_000)
    model_profile: str = Field(default="anima_aesthetic_v1", min_length=1, max_length=100)
    input_mode: Literal["concepts", "natural"] = "concepts"
    natural_text: str = Field(default="", max_length=50_000)
    selected_tags: list[str] = Field(default_factory=list, max_length=40)
    suppressed_tags: list[str] = Field(default_factory=list, max_length=80)
    generation_settings: WorkbenchGenerationSettings = Field(default_factory=WorkbenchGenerationSettings)

    @field_validator("selected_tags", "suppressed_tags")
    @classmethod
    def workspace_tag_lists_are_canonical(cls, values: list[str]) -> list[str]:
        return _canonical_tag_list(values, field_name="tags")


class SceneEntitySnapshot(ApiModel):
    """A visible entity anchor backed by a reviewed character or subject tag."""

    id: str = Field(pattern=r"^entity_[A-Za-z0-9._-]+$", max_length=240)
    label: str = Field(min_length=1, max_length=500)
    canonical_tag: str = Field(min_length=1, max_length=200)
    source_element_id: str = Field(pattern=r"^e_[A-Za-z0-9._-]+$", max_length=200)
    source_start: int | None = Field(default=None, ge=0)
    source_end: int | None = Field(default=None, ge=1)


class SceneDraftItem(ApiModel):
    """One transparent local finding shown before prompt rendering."""

    id: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=500)
    canonical_tag: str | None = Field(default=None, max_length=200)
    source: Literal[
        "source_exact",
        "source_excluded",
        "translation_exact",
        "user_selected",
        "unresolved",
        "suppressed",
        "identity_candidate",
        "identity_exclusion",
        "exclusion_candidate",
    ]
    fact_type: IntentElementType = IntentElementType.OTHER
    owner_entity_id: str | None = Field(default=None, pattern=r"^entity_[A-Za-z0-9._-]+$", max_length=240)
    suggested_owner_entity_id: str | None = Field(default=None, pattern=r"^entity_[A-Za-z0-9._-]+$", max_length=240)
    reason: str = Field(min_length=1, max_length=500)
    source_start: int | None = Field(default=None, ge=0)
    source_end: int | None = Field(default=None, ge=1)
    cn_name: str | None = Field(default=None, max_length=240)


class SceneRelationSnapshot(ApiModel):
    id: str = Field(pattern=r"^c_[A-Za-z0-9._-]+$", max_length=240)
    source_entity_id: str = Field(pattern=r"^entity_[A-Za-z0-9._-]+$", max_length=240)
    target_element_id: str = Field(pattern=r"^e_[A-Za-z0-9._-]+$", max_length=200)
    relation: Literal["wearing"]
    state: Literal["suggested", "confirmed"]
    phrase: str = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=500)


class SceneDraftAmbiguousOption(ApiModel):
    canonical_tag: str = Field(min_length=1, max_length=200)
    render_name: str = Field(min_length=1, max_length=240)
    cn_name: str | None = Field(default=None, max_length=240)
    match_kind: str = Field(min_length=1, max_length=50)
    post_count: int = Field(default=0, ge=0)


class SceneDraftAmbiguousGroup(ApiModel):
    text: str = Field(min_length=1, max_length=200)
    options: list[SceneDraftAmbiguousOption] = Field(min_length=1, max_length=8)
    side: Literal["positive", "excluded"] = "positive"


class SceneDraftBackTranslationSegment(ApiModel):
    en: str = Field(min_length=1, max_length=2000)
    zh: str = Field(default="", max_length=2000)


class SceneDraftBackTranslation(ApiModel):
    text: str = Field(default="", max_length=20_000)
    engine: str = Field(default="", max_length=200)
    segments: list[SceneDraftBackTranslationSegment] = Field(default_factory=list, max_length=24)
    negative_text: str = Field(default="", max_length=20_000)


class CompositionChipSnapshot(ApiModel):
    axis: Literal["shot", "gaze", "camera_height", "angle"]
    canonical_tag: str = Field(min_length=1, max_length=200)
    label_zh: str = Field(min_length=1, max_length=40)
    render_name: str = Field(min_length=1, max_length=240)
    state: Literal["available", "suggested", "confirmed", "selected", "excluded"]
    side: Literal["positive", "excluded"] = "positive"
    reason: str = Field(default="可选构图芯片，不会自动勾选", min_length=1, max_length=500)
    notes: dict[str, str] = Field(default_factory=dict, max_length=8)


class CompositionPresetSnapshot(ApiModel):
    id: str = Field(min_length=1, max_length=40)
    label_zh: str = Field(min_length=1, max_length=40)
    tags: list[str] = Field(default_factory=list, max_length=4)
    note: str = Field(min_length=1, max_length=200)
    group_zh: str = Field(default="", max_length=40)


class SceneDraftSnapshot(ApiModel):
    source_text: str = Field(min_length=1, max_length=10_000)
    translated_text: str = Field(default="", max_length=20_000)
    scene_plan_enabled: bool = True
    entities: list[SceneEntitySnapshot] = Field(default_factory=list, max_length=20)
    relations: list[SceneRelationSnapshot] = Field(default_factory=list, max_length=100)
    confirmed: list[SceneDraftItem] = Field(default_factory=list, max_length=100)
    exclusions: list[SceneDraftItem] = Field(default_factory=list, max_length=100)
    suggestions: list[SceneDraftItem] = Field(default_factory=list, max_length=100)
    unresolved: list[SceneDraftItem] = Field(default_factory=list, max_length=20)
    suppressed: list[SceneDraftItem] = Field(default_factory=list, max_length=80)
    ambiguous: list[SceneDraftAmbiguousGroup] = Field(default_factory=list, max_length=20)
    ambiguous_exclusions: list[SceneDraftAmbiguousGroup] = Field(default_factory=list, max_length=20)
    composition_palette: list[CompositionChipSnapshot] = Field(default_factory=list, max_length=20)
    composition_presets: list[CompositionPresetSnapshot] = Field(default_factory=list, max_length=24)
    back_translation: SceneDraftBackTranslation = Field(default_factory=SceneDraftBackTranslation)
    risk_notes: list[str] = Field(default_factory=list, max_length=24)


class TagSuggestionSnapshot(ApiModel):
    id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)
    render_name: str = Field(min_length=1, max_length=240)
    cn_name: str | None = Field(default=None, max_length=240)
    category: int = Field(ge=0)
    category_name: str = Field(min_length=1, max_length=50)
    post_count: int = Field(ge=0)
    nsfw: bool | None = None
    deprecated: bool = False
    raw_score: float
    display_score: float = Field(ge=0.0, le=1.0)
    cooc_count: int = Field(ge=0)
    sources: list[str] = Field(max_length=100)
    algorithm_version: str = Field(min_length=1, max_length=200)
    data_pack_id: str = Field(min_length=1, max_length=200)


class ArtistSuggestionSnapshot(ApiModel):
    """A transparent, data-pack-bound artist recommendation shown with a snapshot."""

    name: str = Field(min_length=1, max_length=200)
    render_name: str = Field(min_length=1, max_length=240)
    post_count: int = Field(ge=0)
    raw_score: float
    display_score: float = Field(ge=0.0, le=1.0)
    cooc_count: int = Field(ge=0)
    sources: list[str] = Field(max_length=100)
    hit_count: int = Field(ge=0)
    algorithm_version: str = Field(min_length=1, max_length=200)
    data_pack_id: str = Field(min_length=1, max_length=200)


class WorkspaceCandidateSnapshot(ApiModel):
    intent: IntentDocument
    candidates: list[PromptCandidate] = Field(min_length=1, max_length=4)
    validation: CandidateSetValidationReport
    artist_suggestions: list[ArtistSuggestionSnapshot] = Field(default_factory=list, max_length=10)
    artist_ranking: Literal["tag_fit", "volume", "balanced"] | None = None
    tag_suggestions: list[TagSuggestionSnapshot] = Field(default_factory=list, max_length=20)
    scene_draft: SceneDraftSnapshot | None = None
    data_pack_id: str = Field(min_length=1, max_length=200)


class WorkspaceCreateRequest(ApiModel):
    title: str = Field(default="未命名工作台", min_length=1, max_length=200)
    draft: WorkspaceDraft
    candidate_snapshot: WorkspaceCandidateSnapshot | None = None


class WorkspaceUpdateRequest(WorkspaceCreateRequest):
    revision: int = Field(ge=1)


class WorkspaceDeleteRequest(ApiModel):
    revision: int = Field(ge=1)


class GenerationBridgeSettings(ApiModel):
    preset_id: str = Field(default="balanced", min_length=1, max_length=100)
    width: int | None = Field(default=None, ge=64, le=8192)
    height: int | None = Field(default=None, ge=64, le=8192)
    steps: int | None = Field(default=None, ge=1, le=200)
    cfg: float | None = Field(default=None, ge=0, le=30)
    sampler: str | None = Field(default=None, min_length=1, max_length=100)
    scheduler: str | None = Field(default=None, min_length=1, max_length=100)
    seed: int = Field(default=-1, ge=-1)
    batch_size: int = Field(default=1, ge=1, le=100)


class GenerationBridgePreviewRequest(ApiModel):
    candidate: PromptCandidate
    intent: IntentDocument
    project_name: str = Field(default="V3 工作台", min_length=1, max_length=200)
    settings: GenerationBridgeSettings = Field(default_factory=GenerationBridgeSettings)
    workspace_id: str | None = Field(default=None, pattern=r"^workspace_[A-Za-z0-9]+$")
    workspace_revision: int | None = Field(default=None, ge=1)


class GenerationSubmitRequest(GenerationBridgePreviewRequest):
    remote_profile_id: str = Field(min_length=1, max_length=200)
    workflow_profile_id: str = Field(min_length=1, max_length=200)


class DirectPromptSubmitRequest(ApiModel):
    positive_prompt: str = Field(min_length=1, max_length=20_000)
    negative_prompt: str = Field(default="", max_length=20_000)
    model_profile: str = Field(default="anima_aesthetic_v1", min_length=1, max_length=100)
    project_name: str = Field(default="英文提示词直出", min_length=1, max_length=200)
    settings: GenerationBridgeSettings = Field(default_factory=GenerationBridgeSettings)
    remote_profile_id: str = Field(min_length=1, max_length=200)
    workflow_profile_id: str = Field(min_length=1, max_length=200)


class ArtistComparisonRequest(GenerationBridgePreviewRequest):
    """One locked candidate rendered once for every explicitly chosen artist."""

    comparison_id: str = Field(pattern=r"^comparison_[A-Za-z0-9_-]{8,100}$")
    artist_names: list[str] = Field(min_length=1, max_length=20)
    remote_profile_id: str = Field(min_length=1, max_length=200)
    workflow_profile_id: str = Field(min_length=1, max_length=200)

    @field_validator("artist_names")
    @classmethod
    def artist_names_are_canonical(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            name = value.strip().lower().replace(" ", "_")
            if not name or any(character.isspace() for character in name):
                raise ValueError("artist_names 必须是非空 canonical artist name。")
            if name not in normalized:
                normalized.append(name)
        return normalized

    @model_validator(mode="after")
    def comparison_requires_a_fixed_seed(self) -> "ArtistComparisonRequest":
        if self.settings.seed < 0:
            raise ValueError("画师对照必须指定固定 Seed。")
        if self.settings.batch_size != 1:
            raise ValueError("画师对照每位画师只能生成 1 个 batch item。")
        if self.candidate.artists:
            raise ValueError("画师对照基准不能预先包含画师标签。")
        return self


class GenerationRunActionRequest(ApiModel):
    action: Literal["cancel_queued", "retry_check", "continue_download"]


class PrivateKeyPassphraseRequest(ApiModel):
    remote_profile_id: str = Field(min_length=1, max_length=200)
    passphrase: SecretStr = Field(max_length=4096)


class PreferredRemoteProfileRequest(ApiModel):
    remote_profile_id: str = Field(min_length=1, max_length=200)


class RemoteProfileSettingsRequest(ApiModel):
    """The editable, non-secret part of a V2 remote profile.

    Passwords deliberately remain outside SQLite: an entered password is written to
    the operating system credential store, and is never returned by this API.
    """

    display_name: str = Field(min_length=1, max_length=200)
    ssh_host: str = Field(min_length=1, max_length=253)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_user: str = Field(default="root", min_length=1, max_length=128)
    auth_type: Literal["password", "private_key", "agent"] = "password"
    private_key_path: str = Field(default="", max_length=4096)
    enabled: bool = True
    password: SecretStr | None = Field(default=None, max_length=4096)
    remember_password: bool = True


class RemoteHostFingerprintRequest(ApiModel):
    fingerprint: str = Field(min_length=8, max_length=512)


class RemoteConnectionTestRequest(ApiModel):
    password: SecretStr | None = Field(default=None, max_length=4096)
    passphrase: SecretStr | None = Field(default=None, max_length=4096)


class GalleryPathsRequest(ApiModel):
    paths: list[str] = Field(min_length=1, max_length=1000)


class GalleryStateRequest(GalleryPathsRequest):
    state: Literal["", "kept", "rejected"]


class GalleryProcessRequest(GalleryPathsRequest):
    operation: Literal["regenerate", "upscale"]
    count: int = Field(default=1, ge=1, le=4)


class GalleryProcessActionRequest(ApiModel):
    job_id: str = Field(min_length=1, max_length=100)
    action: Literal["cancel", "retry", "clear_completed"]
