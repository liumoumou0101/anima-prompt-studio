"""Pure V3 prompt mapping and candidate-generation services."""

from .benchmark import (
    BenchmarkCaseReport,
    BenchmarkExpectations,
    StaticBenchmarkCase,
    StaticBenchmarkReport,
    StaticBenchmarkRunner,
    StaticBenchmarkSuite,
)

from .literal import (
    LITERAL_ALGORITHM_VERSION,
    LiteralCandidateGenerator,
    LiteralGenerationError,
    LiteralMapper,
    LiteralMapping,
    LiteralMatchKind,
    render_canonical_tag,
)
from .hybrid import HYBRID_ALGORITHM_VERSION, HybridLaneGenerator
from .profiles import (
    ModelProfile,
    ModelProfileRegistry,
    ModelVariant,
    NegativePromptMode,
)
from .recommendation import (
    ARTIST_ALGORITHM_VERSION,
    CONSERVATIVE_ALGORITHM_VERSION,
    RecommendationLaneGenerator,
    RecommendationPolicy,
)
from .validation import (
    CandidateSetValidationReport,
    CandidateValidationError,
    CandidateValidationReport,
    CandidateValidator,
    ValidationIssue,
    ValidationSeverity,
)

__all__ = [
    "BenchmarkCaseReport",
    "BenchmarkExpectations",
    "StaticBenchmarkCase",
    "StaticBenchmarkReport",
    "StaticBenchmarkRunner",
    "StaticBenchmarkSuite",
    "LITERAL_ALGORITHM_VERSION",
    "HYBRID_ALGORITHM_VERSION",
    "ARTIST_ALGORITHM_VERSION",
    "CONSERVATIVE_ALGORITHM_VERSION",
    "LiteralCandidateGenerator",
    "LiteralGenerationError",
    "LiteralMapper",
    "LiteralMapping",
    "LiteralMatchKind",
    "HybridLaneGenerator",
    "ModelProfile",
    "ModelProfileRegistry",
    "ModelVariant",
    "NegativePromptMode",
    "RecommendationLaneGenerator",
    "RecommendationPolicy",
    "CandidateSetValidationReport",
    "CandidateValidationError",
    "CandidateValidationReport",
    "CandidateValidator",
    "ValidationIssue",
    "ValidationSeverity",
    "render_canonical_tag",
]
