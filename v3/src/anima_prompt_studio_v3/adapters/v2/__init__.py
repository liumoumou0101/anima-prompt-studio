"""Explicit boundary for stable behavior reused from V2.

V3 modules must not import V2 UI classes through this package.
"""

from .generation import (
    BRIDGE_SCHEMA,
    CandidateToV2PromptJobAdapter,
    V2GenerationSettings,
    V2PreparedGeneration,
)
from .generation_queue import (
    GenerationQueueError,
    GenerationQueueFullError,
    GenerationRunActionError,
    GenerationRunNotFoundError,
    V2GenerationQueueService,
    V2GenerationTarget,
    build_v2_generation_queue,
)
from .natural_language import (
    IntentParseError,
    IntentParserUnavailableError,
    V2NaturalLanguageIntentAdapter,
    V2ParsedIntent,
    build_v2_intent_parser,
)
from .gallery import GalleryUpscaleError, V2GalleryReadService, build_v2_gallery_service
from .translation import (
    V2LocalTranslationAdapter,
    V2TranslationResult,
    build_v2_local_translation_adapter,
)
from .comfy_access import COMFY_ACCESS_URL, ManagedComfyAccess
from .packaged_workflows import ensure_packaged_workflow_profiles

__all__ = [
    "BRIDGE_SCHEMA",
    "CandidateToV2PromptJobAdapter",
    "V2GenerationSettings",
    "V2PreparedGeneration",
    "GenerationQueueError",
    "GenerationQueueFullError",
    "GenerationRunActionError",
    "GenerationRunNotFoundError",
    "V2GenerationQueueService",
    "V2GenerationTarget",
    "build_v2_generation_queue",
    "IntentParseError",
    "IntentParserUnavailableError",
    "V2NaturalLanguageIntentAdapter",
    "V2ParsedIntent",
    "build_v2_intent_parser",
    "V2GalleryReadService",
    "build_v2_gallery_service",
    "GalleryUpscaleError",
    "V2LocalTranslationAdapter",
    "V2TranslationResult",
    "build_v2_local_translation_adapter",
    "COMFY_ACCESS_URL",
    "ManagedComfyAccess",
    "ensure_packaged_workflow_profiles",
]
