from __future__ import annotations

from enum import StrEnum
from importlib.resources import files
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelVariant(StrEnum):
    BASE = "base"
    AESTHETIC = "aesthetic"
    TURBO = "turbo"


class NegativePromptMode(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class ModelProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    family: str = Field(pattern=r"^anima$")
    variant: ModelVariant
    positive_prefix: tuple[str, ...] = ()
    negative_prompt: tuple[str, ...] = ()
    negative_prompt_mode: NegativePromptMode
    tag_separator: str = Field(min_length=1)
    renderer_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def variant_rules_are_consistent(self) -> "ModelProfile":
        quality_tokens = [item for item in self.positive_prefix if item.startswith("score_")]
        if self.variant == ModelVariant.AESTHETIC and quality_tokens:
            raise ValueError("Aesthetic profile 不能默认加入 score_*。")
        if self.variant == ModelVariant.TURBO:
            if self.negative_prompt_mode != NegativePromptMode.DISABLED or self.negative_prompt:
                raise ValueError("Turbo profile 必须关闭默认 negative prompt。")
        elif self.negative_prompt_mode != NegativePromptMode.ENABLED:
            raise ValueError("Base/Aesthetic profile 必须启用 negative prompt。")
        return self


class ModelProfileRegistry:
    def __init__(self, profiles: list[ModelProfile]) -> None:
        self._profiles = {profile.id: profile for profile in profiles}
        if len(self._profiles) != len(profiles):
            raise ValueError("ModelProfile id 必须唯一。")

    @classmethod
    def built_in(cls) -> "ModelProfileRegistry":
        root = files("anima_prompt_studio_v3").joinpath("configs", "model_profiles")
        profiles = [
            ModelProfile.model_validate_json(resource.read_text(encoding="utf-8"))
            for resource in sorted(root.iterdir(), key=lambda item: item.name)
            if resource.name.endswith(".json")
        ]
        return cls(profiles)

    @classmethod
    def from_directory(cls, directory: Path) -> "ModelProfileRegistry":
        profiles = [
            ModelProfile.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("*.json"))
        ]
        return cls(profiles)

    def get(self, profile_id: str) -> ModelProfile:
        try:
            return self._profiles[profile_id]
        except KeyError as exc:
            raise KeyError(f"未知 ModelProfile：{profile_id}") from exc

    def all(self) -> list[ModelProfile]:
        return list(self._profiles.values())
