from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from ..core.validation import CandidateSetValidationReport
from ..domain import IntentDocument, IntentElementType, IntentState, PromptCandidate, RelationKind


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


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


class IntentParseRequest(ApiModel):
    source_text: str = Field(min_length=1, max_length=50_000)
    source_language: str = Field(default="zh", pattern=r"^(zh|en|mixed)$")


class TranslationRequest(ApiModel):
    source_text: str = Field(min_length=1, max_length=10_000)
    direction: Literal["zh_en", "en_zh"] = "zh_en"


class IntentCandidateRequest(ApiModel):
    intent: IntentDocument
    model_profile: str = Field(default="anima_base_v1", min_length=1, max_length=100)


class WorkspaceDraft(ApiModel):
    positive_text: str = Field(default="", max_length=10_000)
    excluded_text: str = Field(default="", max_length=10_000)
    model_profile: str = Field(default="anima_base_v1", min_length=1, max_length=100)
    input_mode: Literal["concepts", "natural"] = "concepts"
    natural_text: str = Field(default="", max_length=50_000)


class WorkspaceCandidateSnapshot(ApiModel):
    intent: IntentDocument
    candidates: list[PromptCandidate] = Field(min_length=1, max_length=4)
    validation: CandidateSetValidationReport
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


class GenerationRunActionRequest(ApiModel):
    action: Literal["cancel_queued", "retry_check", "continue_download"]


class PrivateKeyPassphraseRequest(ApiModel):
    remote_profile_id: str = Field(min_length=1, max_length=200)
    passphrase: SecretStr = Field(max_length=4096)


class GalleryPathsRequest(ApiModel):
    paths: list[str] = Field(min_length=1, max_length=100)


class GalleryStateRequest(GalleryPathsRequest):
    state: Literal["", "kept", "rejected"]


class GalleryProcessRequest(GalleryPathsRequest):
    operation: Literal["regenerate", "upscale"]
    count: int = Field(default=1, ge=1, le=4)


class GalleryProcessActionRequest(ApiModel):
    job_id: str = Field(min_length=1, max_length=100)
    action: Literal["cancel", "retry", "clear_completed"]
