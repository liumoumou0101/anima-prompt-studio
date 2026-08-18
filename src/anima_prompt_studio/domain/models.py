from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ItemState(StrEnum):
    AUTO = "auto"
    USER_EDITED = "user_edited"
    LOCKED = "locked"
    EXCLUDED = "excluded"


class WarningLevel(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class SubjectMode(StrEnum):
    AUTO = "auto"
    CHARACTER = "character"
    SCENE = "scene"
    MIXED = "mixed"


class CompositionFieldState(StrEnum):
    AUTO = "auto"
    USER_SELECTED = "user_selected"
    LOCKED = "locked"


class GenerationFieldState(StrEnum):
    AUTO = "auto"
    USER_SELECTED = "user_selected"
    LOCKED = "locked"


class ProtectedEntity(BaseModel):
    placeholder: str
    original: str
    entity_type: str


class SemanticWarning(BaseModel):
    level: WarningLevel
    concept: str
    message: str


class ExcludedConcept(BaseModel):
    concept_id: str
    canonical_tag: str
    source_text: str = ""
    reason: str = "explicit_negation"


class SemanticFrame(BaseModel):
    subject_mode: SubjectMode = SubjectMode.CHARACTER
    people_count: int | None = Field(default=None, ge=0)
    final_attributes: dict[str, str] = Field(default_factory=dict)
    gaze_intent: Literal["viewer", "away", "object", "person", "none"] = "none"
    angle_intent: Literal["front", "side", "back", "three_quarter", "none"] = "none"
    scene_facts: list[str] = Field(default_factory=list)
    # Canonical visual concepts extracted before machine translation.  These
    # slots are shared by translation, tag matching, enhancement and framing so
    # the four stages cannot silently disagree about the same source phrase.
    visual_slots: dict[str, str] = Field(default_factory=dict)
    visual_tags: list[str] = Field(default_factory=list)
    visual_spans: dict[str, str] = Field(default_factory=dict)
    excluded_concepts: list[ExcludedConcept] = Field(default_factory=list)
    artist_mentions: list[str] = Field(default_factory=list)
    lora_mentions: list[str] = Field(default_factory=list)
    unresolved_lora_mentions: list[str] = Field(default_factory=list)


class MatchedTag(BaseModel):
    tag: str
    category: str = "general"
    source_type: Literal["direct", "synonym", "character_card", "artist", "parameter", "derived", "user_added"] = "direct"
    source_text: str = ""
    confidence: float = Field(default=1.0, ge=0, le=1)
    state: ItemState = ItemState.AUTO
    character_slot_id: str | None = None


class CharacterCard(BaseModel):
    id: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    entity_type: str = "original_character"
    gender_tag: str = "1girl"
    identity_tags: list[str] = Field(default_factory=list)
    default_appearance_tags: list[str] = Field(default_factory=list)
    default_clothing_tags: list[str] = Field(default_factory=list)
    optional_tags: list[str] = Field(default_factory=list)
    anima_character_tag: str | None = None
    copyright_tag: str | None = None
    lora_profile_ids: list[str] = Field(default_factory=list)
    notes: str = ""


class CharacterSlot(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    position: str = "center"
    character_id: str | None = None
    display_name: str = ""
    gender_tag: str = ""
    identity_tags: list[str] = Field(default_factory=list)
    appearance_tags: list[str] = Field(default_factory=list)
    clothing_tags: list[str] = Field(default_factory=list)
    action_text: str = ""
    locked: bool = False


class ArtistProfile(BaseModel):
    id: str
    display_name: str
    canonical_tag: str
    output_tag: str
    aliases: list[str] = Field(default_factory=list)
    historical_tags: list[str] = Field(default_factory=list)
    anima_tested_tag: str | None = None
    style_keywords: list[str] = Field(default_factory=list)
    model_compatibility: dict[str, str] = Field(default_factory=dict)
    user_rating: int | None = None
    notes: str = ""


class LoRAProfile(BaseModel):
    id: str
    display_name: str
    file_name: str
    default_weight: float = 0.8
    trigger_words: list[str] = Field(default_factory=list)
    type: Literal["character", "style", "pose", "detail"] = "style"
    model_compatibility: list[str] = Field(default_factory=list)
    linked_character_id: str | None = None
    conflicts_with_artist_style: bool = False
    notes: str = ""


class LoRASelection(BaseModel):
    logical_id: str
    file_name: str = ""
    weight: float = 0.8
    trigger_words: list[str] = Field(default_factory=list)
    source: Literal["manual", "text_derived", "locked"] = "manual"


class GenerationParams(BaseModel):
    width: int = 896
    height: int = 1152
    steps: int = 28
    cfg: float = 4.5
    sampler: str = "euler"
    scheduler: str = "normal"
    seed: int = -1
    batch_size: int = 1
    locked_fields: list[str] = Field(default_factory=list)
    field_states: dict[str, GenerationFieldState] = Field(default_factory=dict)

    @model_validator(mode="after")
    def migrate_legacy_locks(self):
        for field in self.locked_fields:
            self.field_states[field] = GenerationFieldState.LOCKED
        self.locked_fields = [
            field for field, state in self.field_states.items()
            if state == GenerationFieldState.LOCKED
        ]
        return self

    def state(self, field: str) -> GenerationFieldState:
        if field in self.locked_fields:
            return GenerationFieldState.LOCKED
        return self.field_states.get(field, GenerationFieldState.AUTO)

    def set_state(self, field: str, state: GenerationFieldState) -> None:
        self.field_states[field] = state
        if state == GenerationFieldState.LOCKED:
            if field not in self.locked_fields:
                self.locked_fields.append(field)
        elif field in self.locked_fields:
            self.locked_fields.remove(field)

    def is_automatic(self, field: str) -> bool:
        return self.state(field) == GenerationFieldState.AUTO


class ModelProfile(BaseModel):
    id: str
    display_name: str
    family: str = "anima"
    variant: str
    version: str = "1.0"
    checkpoint_logical_name: str
    prompt_order_profile: str = "anima_default"
    default_quality_profile_id: str = "standard"
    default_steps: int
    default_cfg: float
    default_sampler: str
    default_scheduler: str
    negative_prompt_mode: Literal["enabled", "disabled", "optional"] = "enabled"
    negative_prompt: list[str] = Field(default_factory=list)
    positive_prefix: list[str] = Field(default_factory=list)
    default_width: int = 896
    default_height: int = 1152
    workflow_template_id: str
    status: Literal["experimental", "tested"] = "experimental"
    notes: str = "推荐默认值，请根据本地工作流实测调整。"


class QualityProfile(BaseModel):
    id: str
    display_name: str
    notes: str = ""
    base_quality_tags: list[str] = Field(default_factory=list)
    rendering_style_tags: list[str] = Field(default_factory=list)
    detail_tags: list[str] = Field(default_factory=list)
    composition_tags: list[str] = Field(default_factory=list)
    atmosphere_tags: list[str] = Field(default_factory=list)

    def all_tags(self) -> list[str]:
        return self.base_quality_tags + self.rendering_style_tags + self.detail_tags + self.composition_tags + self.atmosphere_tags


class GenerationPreset(BaseModel):
    id: str
    display_name: str
    steps: int = Field(ge=1, le=200)
    cfg: float = Field(ge=0, le=30)
    sampler: str
    scheduler: str
    notes: str = ""


class CompositionPreset(BaseModel):
    id: str
    display_name: str
    values: dict[str, str]
    notes: str = ""


class CompositionDecision(BaseModel):
    state: CompositionFieldState = CompositionFieldState.AUTO
    reason: str | None = None
    source_rule_ids: list[str] = Field(default_factory=list)
    score: float = 0.0


class CompositionContext(BaseModel):
    movement_direction: Literal["left", "right", "up", "down", "none"] = "none"
    gaze_direction: Literal["left", "right", "up", "down", "object", "viewer", "none"] = "none"
    explicit_subject_position: Literal["left", "center", "right", "none"] = "none"
    dynamic_action: bool = False
    composition_meta_spans: list[str] = Field(default_factory=list)
    motion_relation_spans: list[str] = Field(default_factory=list)


COMPOSITION_FIELDS = ("shot", "camera_height", "angle", "gaze", "aspect", "subject_position")


def default_composition_decisions() -> dict[str, CompositionDecision]:
    return {field: CompositionDecision() for field in COMPOSITION_FIELDS}


class Composition(BaseModel):
    people_count: int = Field(default=1, ge=0)
    shot: str = "半身"
    camera_height: str = "平视"
    angle: str = "正面"
    gaze: str = "看镜头"
    aspect: str = "竖图"
    subject_position: str = "中"
    mode: Literal["smart", "mixed", "manual"] = "smart"
    decisions: dict[str, CompositionDecision] = Field(default_factory=default_composition_decisions)

    @model_validator(mode="before")
    @classmethod
    def preserve_legacy_manual_values(cls, value):
        if isinstance(value, dict) and value and "decisions" not in value:
            value = dict(value)
            value["decisions"] = {
                field: CompositionDecision(state=CompositionFieldState.USER_SELECTED).model_dump(mode="json")
                for field in COMPOSITION_FIELDS
            }
        return value

    def decision(self, field: str) -> CompositionDecision:
        if field not in self.decisions:
            self.decisions[field] = CompositionDecision()
        return self.decisions[field]


class EnhancementItem(BaseModel):
    id: str
    type: str
    source_rule: str
    content: str
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True
    state: ItemState = ItemState.AUTO
    suppress_tags: list[str] = Field(default_factory=list)
    suppress_patterns: list[str] = Field(default_factory=list)
    canonical_phrases: list[str] = Field(default_factory=list)
    replaces_translation: bool = False


class ResolvedConcept(BaseModel):
    id: str
    source_text: str
    canonical_en: str
    tags: list[str] = Field(default_factory=list)
    category: str = "general"
    priority: int = 0
    suppresses_tags: list[str] = Field(default_factory=list)


class PromptJob(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    project_name: str = "未命名项目"
    original_zh: str = ""
    normalized_zh: str = ""
    translated_en: str = ""
    back_translated_zh: str = ""
    translation_state: ItemState = ItemState.AUTO
    subject_mode: SubjectMode = SubjectMode.AUTO
    semantic_frame: SemanticFrame = Field(default_factory=SemanticFrame)
    canonical_prose: str = ""
    canonical_prose_ready: bool = False
    protected_entities: list[ProtectedEntity] = Field(default_factory=list)
    semantic_warnings: list[SemanticWarning] = Field(default_factory=list)
    consistency_failures: list[str] = Field(default_factory=list)
    cleanliness_failures: list[str] = Field(default_factory=list)
    matched_tags: list[MatchedTag] = Field(default_factory=list)
    excluded_tags: list[str] = Field(default_factory=list)
    locked_tags: list[str] = Field(default_factory=list)
    character_slots: list[CharacterSlot] = Field(default_factory=list)
    artist_selection: list[str] = Field(default_factory=list)
    artist_selection_sources: dict[str, Literal["manual", "text_derived", "locked"]] = Field(default_factory=dict)
    lora_selection: list[LoRASelection] = Field(default_factory=list)
    model_profile_id: str = "anima_turbo_v1"
    generation_preset_id: str = "balanced"
    quality_profile_id: str = "standard"
    composition: Composition = Field(default_factory=Composition)
    composition_context: CompositionContext = Field(default_factory=CompositionContext)
    enhancements: list[EnhancementItem] = Field(default_factory=list)
    resolved_concepts: list[ResolvedConcept] = Field(default_factory=list)
    positive_prompt: str = ""
    negative_prompt: str = ""
    compiled_prompt_state: ItemState = ItemState.AUTO
    generation_params: GenerationParams = Field(default_factory=GenerationParams)
    workflow_template_id: str | None = None
    user_rating: int | None = None
    notes: str = ""

    def touch(self) -> None:
        self.updated_at = utc_now()

    def task_package(self) -> dict[str, Any]:
        return {
            "schema_version": "1.4",
            "job_id": self.id,
            "model_profile": self.model_profile_id,
            "positive_prompt": self.positive_prompt,
            "negative_prompt": self.negative_prompt,
            "generation_preset": self.generation_preset_id,
            "quality_profile": self.quality_profile_id,
            **self.generation_params.model_dump(exclude={"locked_fields", "field_states"}),
            "loras": [x.model_dump() for x in self.lora_selection],
            "characters": (
                [] if self.effective_subject_mode() == SubjectMode.SCENE
                else [x.model_dump() for x in self.character_slots[:self.composition.people_count]]
            ),
            "artists": self.artist_selection,
            "artist_sources": {
                artist: self.artist_selection_sources.get(artist, "manual")
                for artist in self.artist_selection
            },
            "subject_mode": self.effective_subject_mode().value,
            "canonical_prose": self.canonical_prose,
            "excluded_concepts": [x.model_dump() for x in self.semantic_frame.excluded_concepts],
            "composition": self.composition.model_dump(mode="json"),
            "source": {
                "original_zh": self.original_zh,
                "translated_en": self.translated_en,
                "back_translated_zh": self.back_translated_zh,
            },
            "workflow_template_id": self.workflow_template_id,
        }

    def effective_subject_mode(self) -> SubjectMode:
        return self.semantic_frame.subject_mode if self.subject_mode == SubjectMode.AUTO else self.subject_mode

    def uses_english_authority(self) -> bool:
        return self.translation_state in (ItemState.USER_EDITED, ItemState.LOCKED) and bool(self.translated_en.strip())

    def authoritative_text(self) -> str:
        return self.translated_en.strip() if self.uses_english_authority() else (self.normalized_zh or self.original_zh)
