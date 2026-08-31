from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from anima_prompt_studio.repositories.sqlite_repository import SQLiteRepository
from anima_prompt_studio.services.ai_extract_service import AIExtractService, ExtractedPrompt
from anima_prompt_studio.services.ai_prompt_service import (
    AIAPIError,
    AIClient,
    AIEngineConfig,
    OPENCODE_GO_BASE_URL,
)
from anima_prompt_studio.services.remote.credential_store import CredentialStore

from ...domain import (
    ConstraintGraph,
    ElementProvenance,
    IntentDocument,
    IntentElement,
    IntentElementType,
    IntentState,
    IntentWarning,
    ProvenanceKind,
)


class IntentParserUnavailableError(RuntimeError):
    pass


class IntentParseError(RuntimeError):
    pass


@dataclass(frozen=True)
class V2ParsedIntent:
    intent: IntentDocument
    extraction: ExtractedPrompt
    parser_name: str


class V2NaturalLanguageIntentAdapter:
    """Reuse V2 visual-fact extraction and emit only V3 intent contracts."""

    def __init__(
        self,
        client: AIClient | None,
        *,
        service: AIExtractService | None = None,
        parser_name: str | None = None,
    ) -> None:
        self.client = client
        self.service = service or AIExtractService()
        self.parser_name = parser_name or (client.name if client is not None else "V2 AI Extract")

    @property
    def available(self) -> bool:
        return self.client is not None

    def parse(self, source_text: str, *, source_language: str = "zh") -> V2ParsedIntent:
        if self.client is None:
            raise IntentParserUnavailableError("尚未在 V2 配置可用的 AI API Key。")
        try:
            extraction = self.service.extract(source_text, self.client)
        except AIAPIError as exc:
            raise IntentParseError(str(exc)) from exc
        intent = self._to_intent(source_text, source_language, extraction)
        return V2ParsedIntent(intent=intent, extraction=extraction, parser_name=self.parser_name)

    def _to_intent(
        self,
        source_text: str,
        source_language: str,
        extraction: ExtractedPrompt,
    ) -> IntentDocument:
        elements: list[IntentElement] = []

        def add(
            text: str,
            element_type: IntentElementType,
            *,
            state: IntentState = IntentState.REQUIRED,
            notes: list[str] | None = None,
            confidence: float = 0.85,
        ) -> None:
            normalized = str(text or "").strip()
            if not normalized:
                return
            element_id = f"e_ai_{len(elements) + 1}"
            elements.append(IntentElement(
                id=element_id,
                original_text=normalized,
                type=element_type,
                state=state,
                confidence=confidence,
                provenance=ElementProvenance(
                    kind=ProvenanceKind.SEMANTIC,
                    detail="v2_ai_extract_to_v3_intent",
                ),
                notes=list(notes or []),
            ))

        for index, character in enumerate(extraction.selected_characters(), 1):
            scope = character.label.strip() or f"人物{index}"
            add(character.identity or scope, IntentElementType.CHARACTER, notes=[f"scope:{scope}"])
            for fact in [*character.appearance, *character.body]:
                add(fact, IntentElementType.APPEARANCE, notes=[f"scope:{scope}"])
            for fact in [*character.clothing, *character.accessories, *character.footwear]:
                add(fact, IntentElementType.CLOTHING, notes=[f"scope:{scope}"])
            for fact in (character.expression, character.gaze, character.pose, character.action):
                add(fact, IntentElementType.ACTION, notes=[f"scope:{scope}"])

        for fact in (
            extraction.interaction_zh,
            extraction.key_event_zh,
            extraction.spatial_layout_zh,
        ):
            add(fact, IntentElementType.RELATION)

        scene = extraction.scene
        if scene.included:
            for fact in (scene.location, scene.time, scene.weather, scene.lighting, scene.atmosphere):
                add(fact, IntentElementType.SCENE)
            for fact in scene.objects:
                add(fact, IntentElementType.OBJECT)

        camera = extraction.camera
        if camera.included:
            for fact in (camera.shot, camera.angle, camera.camera_height, camera.subject_position):
                add(fact, IntentElementType.COMPOSITION)

        if extraction.include_negatives:
            for fact in extraction.negatives:
                add(fact, IntentElementType.OTHER, state=IntentState.EXCLUDED, confidence=0.95)

        if not elements:
            raise ValueError("自然语言抽取结果不包含可转换的 V3 Intent 元素。")
        warnings = [
            IntentWarning(
                code="ai_extraction_requires_review",
                message="AI 抽取结果已转为 V3 Intent；提交生图前请检查人物归属、动作和排除项。",
            )
        ]
        if extraction.truncated_source:
            warnings.append(IntentWarning(
                code="source_truncated",
                message="原文超过 V2 抽取上限，本次只处理了前 8000 个字符。",
            ))
        warnings.extend(
            IntentWarning(code="extractor_note", message=note)
            for note in extraction.notes if note.strip()
        )
        return IntentDocument(
            source_text=source_text.strip(),
            source_language=source_language,
            translated_text=None,
            scene_plan_en=extraction.direct_anima_prompt() or None,
            scene_negative_en=list(extraction.anima_negative_en),
            graph=ConstraintGraph(elements=elements),
            warnings=warnings,
        )


def build_v2_intent_parser(
    v2_database: Path,
    *,
    credential_store: CredentialStore | None = None,
) -> V2NaturalLanguageIntentAdapter:
    database = Path(v2_database).expanduser().resolve()
    repository = SQLiteRepository(database)
    try:
        payload = repository.get_setting("ai_engine_config")
        if payload:
            config = AIEngineConfig.model_validate(payload)
        else:
            old_base = repository.get_setting("ai_api_base_url", OPENCODE_GO_BASE_URL)
            provider = "opencode_go" if "opencode.ai/zen/go" in old_base else "openai_compatible"
            config = AIEngineConfig(
                provider_id=provider,
                base_url=old_base,
                model=repository.get_setting("ai_api_model", "mimo-v2.5") or "mimo-v2.5",
                timeout_seconds=int(repository.get_setting("ai_api_timeout", 60)),
            )
    finally:
        repository.close()
    secrets = credential_store or CredentialStore()
    api_key = secrets.read_ai_api_key(config.provider_id) or secrets.read_ai_api_key("default")
    client = AIClient(config, api_key) if api_key else None
    return V2NaturalLanguageIntentAdapter(
        client,
        parser_name=f"V2 AI Extract · {config.provider_id} · {config.model}",
    )
