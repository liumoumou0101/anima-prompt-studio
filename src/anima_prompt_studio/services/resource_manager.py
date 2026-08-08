from __future__ import annotations

import json
from pathlib import Path

from anima_prompt_studio.repositories import default_data_dir


MODEL_REPOSITORIES = {
    "zh_en": "Helsinki-NLP/opus-mt-zh-en",
    "en_zh": "Helsinki-NLP/opus-mt-en-zh",
}


class ResourceManager:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_data_dir() / "resources"

    @property
    def model_dir(self) -> Path:
        return self.root / "models"

    @property
    def tag_db_path(self) -> Path:
        return self.root / "tags" / "anima_tags.db"

    def model_path(self, direction: str) -> Path:
        return self.model_dir / MODEL_REPOSITORIES[direction].replace("/", "--")

    def models_available(self) -> bool:
        return all(
            (self.model_path(key) / "config.json").is_file()
            and (self.model_path(key) / "pytorch_model.bin").is_file()
            and (self.model_path(key) / "pytorch_model.bin").stat().st_size > 100_000_000
            for key in MODEL_REPOSITORIES
        )

    def manifest(self) -> dict:
        path = self.root / "resource_manifest.json"
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
