from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ..data import ReferenceDataStore
from ..domain import CandidateLane, IntentDocument, TagSource
from .hybrid import HybridLaneGenerator
from .literal import LiteralCandidateGenerator
from .profiles import ModelProfileRegistry
from .recommendation import RecommendationLaneGenerator
from .validation import CandidateValidator


class BenchmarkExpectations(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    required_tags: frozenset[str] = frozenset()
    excluded_tags: frozenset[str] = frozenset()
    required_lanes: frozenset[CandidateLane] = frozenset({CandidateLane.LITERAL})


class StaticBenchmarkCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    profile_ids: tuple[str, ...] = Field(min_length=1)
    intent: IntentDocument
    expectations: BenchmarkExpectations


class StaticBenchmarkSuite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    cases: tuple[StaticBenchmarkCase, ...] = Field(min_length=1)

    @classmethod
    def load(cls, path: Path) -> "StaticBenchmarkSuite":
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


class BenchmarkCaseReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    profile_id: str
    passed: bool
    lanes: tuple[CandidateLane, ...]
    required_total: int
    required_retained: int
    excluded_leaks: tuple[str, ...] = ()
    protected_category_leaks: tuple[str, ...] = ()
    missing_lanes: tuple[CandidateLane, ...] = ()
    validation_errors: int = 0
    error: str | None = None


class StaticBenchmarkReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite_version: str
    data_pack_id: str
    passed: bool
    required_total: int
    required_retained: int
    excluded_leak_count: int
    protected_category_leak_count: int
    validation_error_count: int
    cases: tuple[BenchmarkCaseReport, ...]

    @property
    def required_retention(self) -> float:
        return self.required_retained / self.required_total if self.required_total else 1.0


class StaticBenchmarkRunner:
    def __init__(self, store: ReferenceDataStore, profiles: ModelProfileRegistry | None = None) -> None:
        self.store = store
        self.profiles = profiles or ModelProfileRegistry.built_in()

    def run(self, suite: StaticBenchmarkSuite) -> StaticBenchmarkReport:
        reports: list[BenchmarkCaseReport] = []
        for case in suite.cases:
            for profile_id in case.profile_ids:
                reports.append(self._run_case(case, profile_id))
        required_total = sum(report.required_total for report in reports)
        required_retained = sum(report.required_retained for report in reports)
        excluded_leaks = sum(len(report.excluded_leaks) for report in reports)
        protected_leaks = sum(len(report.protected_category_leaks) for report in reports)
        validation_errors = sum(report.validation_errors for report in reports)
        return StaticBenchmarkReport(
            suite_version=suite.version,
            data_pack_id=self.store.pack_id,
            passed=all(report.passed for report in reports),
            required_total=required_total,
            required_retained=required_retained,
            excluded_leak_count=excluded_leaks,
            protected_category_leak_count=protected_leaks,
            validation_error_count=validation_errors,
            cases=tuple(reports),
        )

    def _run_case(self, case: StaticBenchmarkCase, profile_id: str) -> BenchmarkCaseReport:
        try:
            profile = self.profiles.get(profile_id)
            bundle = LiteralCandidateGenerator(self.store).generate(case.intent, profile)
            recommendation = RecommendationLaneGenerator(self.store)
            bundle = recommendation.add_conservative(bundle, profile)
            bundle = recommendation.add_artist(bundle, profile)
            bundle = HybridLaneGenerator(self.store).add_hybrid(bundle, profile)
            validation = CandidateValidator(self.store).validate(bundle, profile)

            literal = next(candidate for candidate in bundle.candidates if candidate.lane == CandidateLane.LITERAL)
            literal_tags = {tag.name for tag in literal.tags}
            required_retained = len(case.expectations.required_tags & literal_tags)
            all_tags = {tag.name for candidate in bundle.candidates for tag in candidate.tags}
            excluded_leaks = tuple(sorted(case.expectations.excluded_tags & all_tags))
            protected_leaks = tuple(sorted(self._protected_automatic_leaks(bundle)))
            lanes = tuple(candidate.lane for candidate in bundle.candidates)
            missing_lanes = tuple(sorted(case.expectations.required_lanes - set(lanes), key=lambda lane: lane.value))
            passed = (
                required_retained == len(case.expectations.required_tags)
                and not excluded_leaks
                and not protected_leaks
                and not missing_lanes
                and validation.valid
            )
            return BenchmarkCaseReport(
                case_id=case.id,
                profile_id=profile_id,
                passed=passed,
                lanes=lanes,
                required_total=len(case.expectations.required_tags),
                required_retained=required_retained,
                excluded_leaks=excluded_leaks,
                protected_category_leaks=protected_leaks,
                missing_lanes=missing_lanes,
                validation_errors=validation.error_count,
            )
        except Exception as exc:  # A benchmark must report one bad case without hiding the remaining cases.
            return BenchmarkCaseReport(
                case_id=case.id,
                profile_id=profile_id,
                passed=False,
                lanes=(),
                required_total=len(case.expectations.required_tags),
                required_retained=0,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _protected_automatic_leaks(self, bundle: object) -> set[str]:
        from ..domain import CandidateSet

        assert isinstance(bundle, CandidateSet)
        leaked: set[str] = set()
        for candidate in bundle.candidates:
            for tag in candidate.tags:
                if tag.source != TagSource.COOCCURRENCE:
                    continue
                detail = self.store.get_tag(tag.name)
                if detail and detail["category_name"] in {"character", "copyright", "artist"}:
                    leaked.add(tag.name)
        return leaked
