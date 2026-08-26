from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from anima_prompt_studio.services.resource_manager import ResourceManager
from anima_prompt_studio.services.translation_service import (
    BuiltinOfflineEngine,
    LazyLocalMarianEngine,
    TranslationService,
    marian_runtime_available,
)


@dataclass(frozen=True)
class V2TranslationResult:
    translated_text: str
    engine_name: str
    direction: str


class V2LocalTranslationAdapter:
    """Thin, local-only adapter around V2's reviewed translation service.

    Translation is intentionally separate from V3 intent extraction and prompt
    compilation. Local Marian models are selected only when they already exist;
    this adapter never downloads resources.
    """

    def __init__(self, service: TranslationService, *, model_ready: bool) -> None:
        self._service = service
        self.model_ready = model_ready
        self.available = True

    @property
    def engine_name(self) -> str:
        return self._service.engine_name

    def translate(self, text: str, *, direction: str) -> V2TranslationResult:
        if direction not in {"zh_en", "en_zh"}:
            raise ValueError("翻译方向必须是 zh_en 或 en_zh。")
        translated = self._service.zh_to_en(text) if direction == "zh_en" else self._service.en_to_zh(text)
        return V2TranslationResult(
            translated_text=translated,
            engine_name=self.engine_name,
            direction=direction,
        )


def build_v2_local_translation_adapter(
    resource_root: Path | None = None,
) -> V2LocalTranslationAdapter:
    resources = ResourceManager(resource_root)
    model_ready = resources.models_available() and marian_runtime_available()
    engine = (
        LazyLocalMarianEngine(resources.model_path("zh_en"), resources.model_path("en_zh"))
        if model_ready
        else BuiltinOfflineEngine()
    )
    return V2LocalTranslationAdapter(TranslationService(engine), model_ready=model_ready)
