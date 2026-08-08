from __future__ import annotations

import json
from pathlib import Path

from anima_prompt_studio.domain.models import ModelProfile, QualityProfile


class ConfigService:
    def __init__(self, config_dir: Path | None = None) -> None:
        packaged = Path(__file__).resolve().parent.parent / "configs"
        requested = config_dir or packaged
        self.config_dir = requested if (requested / "model_profiles").is_dir() and (requested / "quality_profiles.json").is_file() else packaged
        self.model_profiles = self._load_models()
        self.quality_profiles = self._load_quality()

    def _load_models(self) -> dict[str, ModelProfile]:
        profiles: dict[str, ModelProfile] = {}
        for path in sorted((self.config_dir / "model_profiles").glob("*.json")):
            profile = ModelProfile.model_validate_json(path.read_text(encoding="utf-8"))
            profiles[profile.id] = profile
        if not profiles:
            raise RuntimeError("没有找到可用的 ANIMA Model Profile。")
        return profiles

    def _load_quality(self) -> dict[str, QualityProfile]:
        raw = json.loads((self.config_dir / "quality_profiles.json").read_text(encoding="utf-8"))
        return {item.id: item for item in map(QualityProfile.model_validate, raw)}

    def get_model(self, profile_id: str) -> ModelProfile:
        try:
            return self.model_profiles[profile_id]
        except KeyError as exc:
            raise ValueError(f"未知模型配置：{profile_id}") from exc

    def get_quality(self, profile_id: str) -> QualityProfile:
        try:
            return self.quality_profiles[profile_id]
        except KeyError as exc:
            raise ValueError(f"未知质量预设：{profile_id}") from exc
