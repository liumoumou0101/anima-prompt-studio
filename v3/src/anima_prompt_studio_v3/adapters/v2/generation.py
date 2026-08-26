from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from anima_prompt_studio.domain.models import (
    GenerationParams,
    ItemState,
    MatchedTag,
    PromptJob,
)
from anima_prompt_studio.services.config_service import ConfigService

from ...domain import CandidateTagState, IntentDocument, IntentState, PromptCandidate, TagSource


BRIDGE_SCHEMA = "v3-v2-generation-bridge/1"


class V2GenerationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    preset_id: str = "balanced"
    width: int | None = Field(default=None, ge=64, le=8192)
    height: int | None = Field(default=None, ge=64, le=8192)
    seed: int = Field(default=-1, ge=-1)
    batch_size: int = Field(default=1, ge=1, le=100)


@dataclass(frozen=True)
class V2PreparedGeneration:
    job: PromptJob
    checkpoint_logical_name: str


class CandidateToV2PromptJobAdapter:
    """Convert a validated V3 candidate into the stable V2 execution DTO."""

    def __init__(self, config: ConfigService | None = None) -> None:
        self.config = config or ConfigService()

    def prepare(
        self,
        candidate: PromptCandidate,
        intent: IntentDocument,
        *,
        project_name: str = "V3 工作台",
        settings: V2GenerationSettings | None = None,
        workspace_id: str | None = None,
        workspace_revision: int | None = None,
    ) -> V2PreparedGeneration:
        settings = settings or V2GenerationSettings()
        model = self.config.get_model(candidate.versions.model_profile)
        preset = self.config.get_generation_preset(model.id, settings.preset_id)
        if not candidate.positive_prompt.strip():
            raise ValueError("V3 候选缺少正向提示词。")

        generation_params = GenerationParams(
            width=settings.width or model.default_width,
            height=settings.height or model.default_height,
            steps=preset.steps,
            cfg=preset.cfg,
            sampler=preset.sampler,
            scheduler=preset.scheduler,
            seed=settings.seed,
            batch_size=settings.batch_size,
        )
        excluded = [
            element.canonical_tag
            for element in intent.graph.elements
            if element.state == IntentState.EXCLUDED and element.canonical_tag
        ]
        matched = [
            MatchedTag(
                tag=tag.name,
                source_type="derived" if tag.source == TagSource.COOCCURRENCE else "direct",
                source_text=tag.reason,
                confidence=tag.display_score if tag.display_score is not None else 1.0,
                state=ItemState.LOCKED if tag.state == CandidateTagState.LOCKED else ItemState.AUTO,
            )
            for tag in candidate.tags
        ]
        bridge = {
            "schema": BRIDGE_SCHEMA,
            "candidate": candidate.model_dump(mode="json"),
            "intent": intent.model_dump(mode="json"),
            "workspace": {"id": workspace_id, "revision": workspace_revision},
        }
        job = PromptJob(
            project_name=project_name,
            original_zh=intent.source_text,
            normalized_zh=intent.source_text,
            translated_en=intent.translated_text or "",
            matched_tags=matched,
            excluded_tags=list(dict.fromkeys(item for item in excluded if item)),
            locked_tags=[tag.name for tag in candidate.tags if tag.state == CandidateTagState.LOCKED],
            artist_selection=[artist.name for artist in candidate.artists],
            artist_selection_sources={artist.name: "manual" for artist in candidate.artists},
            model_profile_id=model.id,
            generation_preset_id=settings.preset_id,
            positive_prompt=candidate.positive_prompt,
            negative_prompt=candidate.negative_prompt,
            compiled_prompt_state=ItemState.LOCKED,
            prompt_origin="deterministic",
            generation_params=generation_params,
            workflow_template_id=model.workflow_template_id,
            integration_metadata=bridge,
        )
        return V2PreparedGeneration(job=job, checkpoint_logical_name=model.checkpoint_logical_name)
