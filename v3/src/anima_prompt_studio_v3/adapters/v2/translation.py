from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from anima_prompt_studio.services.translation_service import (
    BuiltinOfflineEngine,
    TranslationService,
)
from ...core.prompt_translation import translate_prompt


@dataclass(frozen=True)
class V2TranslationResult:
    translated_text: str
    engine_name: str
    direction: str
    segments: tuple[dict, ...] = ()


class V2LocalTranslationAdapter:
    """Thin, local-only adapter around V2's reviewed translation service.

    Translation is intentionally separate from V3 intent extraction and prompt
    compilation. V3 uses the lightweight built-in dictionary only;
    it never discovers, loads, or downloads local neural translation models.
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

    def translate_prompt(self, text: str, *, extra_terms: dict[str, str] | None = None) -> V2TranslationResult:
        translated, segments = translate_prompt(text, self._service.zh_to_en, extra_terms=extra_terms)
        return V2TranslationResult(translated, self.engine_name + " · 领域锚点保护", "zh_en", tuple(segments))


def build_v2_local_translation_adapter(
    resource_root: Path | None = None,
) -> V2LocalTranslationAdapter:
    # Keep the argument for callers using the old factory signature. Existing
    # model directories remain untouched and are no longer inspected by V3.
    return V2LocalTranslationAdapter(TranslationService(BuiltinOfflineEngine()), model_ready=False)
