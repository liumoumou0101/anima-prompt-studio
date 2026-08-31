from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ..data import ReferenceDataStore
from ..domain import CandidateLane, CandidateSet, IntentState, PromptCandidate, TagSource
from .hybrid import HYBRID_ALGORITHM_VERSION
from .literal import LITERAL_ALGORITHM_VERSION, LiteralMapper, render_canonical_tag
from .profiles import ModelProfile, NegativePromptMode
from .recommendation import ARTIST_ALGORITHM_VERSION, CONSERVATIVE_ALGORITHM_VERSION


class ValidationSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    severity: ValidationSeverity
    message: str = Field(min_length=1)
    candidate_id: str | None = None
    element_ids: tuple[str, ...] = ()
    tag_names: tuple[str, ...] = ()


class CandidateValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    valid: bool
    issues: tuple[ValidationIssue, ...] = ()


class CandidateSetValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    candidate_reports: tuple[CandidateValidationReport, ...]
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def error_count(self) -> int:
        candidate_errors = sum(
            issue.severity == ValidationSeverity.ERROR
            for report in self.candidate_reports
            for issue in report.issues
        )
        global_errors = sum(issue.severity == ValidationSeverity.ERROR for issue in self.issues)
        return candidate_errors + global_errors


class CandidateValidationError(ValueError):
    def __init__(self, report: CandidateSetValidationReport) -> None:
        self.report = report
        super().__init__(f"候选验证失败，共 {report.error_count} 个错误。")


class CandidateValidator:
    def __init__(self, store: ReferenceDataStore) -> None:
        self.store = store
        self.mapper = LiteralMapper(store)

    def validate(self, bundle: CandidateSet, profile: ModelProfile) -> CandidateSetValidationReport:
        excluded_names, expected_negative = self._expected_exclusions(bundle, profile)
        reports: list[CandidateValidationReport] = []
        for candidate in bundle.candidates:
            issues: list[ValidationIssue] = []
            self._validate_candidate(
                candidate,
                bundle,
                profile,
                excluded_names,
                expected_negative,
                issues,
            )
            reports.append(
                CandidateValidationReport(
                    candidate_id=candidate.id,
                    valid=not any(issue.severity == ValidationSeverity.ERROR for issue in issues),
                    issues=tuple(issues),
                )
            )

        global_issues = self._validate_lane_differences(bundle)
        valid = all(report.valid for report in reports) and not any(
            issue.severity == ValidationSeverity.ERROR for issue in global_issues
        )
        return CandidateSetValidationReport(
            valid=valid,
            candidate_reports=tuple(reports),
            issues=tuple(global_issues),
        )

    def validate_or_raise(self, bundle: CandidateSet, profile: ModelProfile) -> CandidateSetValidationReport:
        report = self.validate(bundle, profile)
        if not report.valid:
            raise CandidateValidationError(report)
        return report

    def _validate_candidate(
        self,
        candidate: PromptCandidate,
        bundle: CandidateSet,
        profile: ModelProfile,
        excluded_names: set[str],
        expected_negative: str,
        issues: list[ValidationIssue],
    ) -> None:
        if candidate.versions.model_profile != profile.id:
            issues.append(_error(candidate, "model_profile_mismatch", "候选记录的模型配置与当前 renderer 不一致。"))
        if candidate.versions.data_pack != self.store.pack_id:
            issues.append(_error(candidate, "data_pack_mismatch", "候选数据包版本与当前 reference.db 不一致。"))

        expected_algorithms = {
            CandidateLane.LITERAL: LITERAL_ALGORITHM_VERSION,
            CandidateLane.CONSERVATIVE: CONSERVATIVE_ALGORITHM_VERSION,
            CandidateLane.ARTIST: ARTIST_ALGORITHM_VERSION,
            CandidateLane.HYBRID: HYBRID_ALGORITHM_VERSION,
        }
        if candidate.versions.algorithm != expected_algorithms[candidate.lane]:
            issues.append(_error(candidate, "algorithm_version_mismatch", "候选 lane 与算法版本不一致。"))

        for tag in candidate.tags:
            detail = self.store.get_tag(tag.name)
            if detail is None or detail["name"] != tag.name:
                issues.append(
                    _error(
                        candidate,
                        "tag_not_resolvable",
                        f"canonical tag 无法在当前数据包解析：{tag.name}",
                        tag_names=(tag.name,),
                    )
                )
                continue
            if tag.rendered != render_canonical_tag(tag.name):
                issues.append(
                    _error(
                        candidate,
                        "tag_render_mismatch",
                        f"标签渲染不符合 ANIMA 规则：{tag.name}",
                        tag_names=(tag.name,),
                    )
                )
            if tag.data_pack_id and tag.data_pack_id != self.store.pack_id:
                issues.append(
                    _error(
                        candidate,
                        "tag_data_pack_mismatch",
                        f"标签来源数据包不一致：{tag.name}",
                        tag_names=(tag.name,),
                    )
                )
            if tag.source == TagSource.COOCCURRENCE and detail["category_name"] not in {"general", "meta"}:
                issues.append(
                    _error(
                        candidate,
                        "automatic_category_leak",
                        f"自动推荐不能加入 {detail['category_name']} 标签：{tag.name}",
                        tag_names=(tag.name,),
                    )
                )

        leaked = excluded_names & {tag.name for tag in candidate.tags}
        if leaked:
            issues.append(
                _error(
                    candidate,
                    "excluded_tag_leak",
                    f"候选重新引入 excluded 标签：{sorted(leaked)}",
                    tag_names=tuple(sorted(leaked)),
                )
            )

        tag_prompt = _render_tag_prompt(candidate, profile)
        local_prose_baseline = (
            candidate.lane == CandidateLane.LITERAL
            and bool(candidate.score_breakdown.get("prose_baseline"))
            and not candidate.tags
        )
        if candidate.lane == CandidateLane.HYBRID:
            if not candidate.positive_prompt.startswith(tag_prompt + ". "):
                issues.append(
                    _error(
                        candidate,
                        "hybrid_format_invalid",
                        "hybrid 必须以可复现的标签段开头，并追加画面计划或关系短语。",
                    )
                )
        elif not local_prose_baseline and candidate.positive_prompt != tag_prompt:
            issues.append(
                _error(candidate, "positive_prompt_mismatch", "正向提示词与候选标签/画师快照不一致。")
            )
        if candidate.negative_prompt != expected_negative:
            issues.append(
                _error(candidate, "negative_prompt_mismatch", "负向提示词与模型配置或排除项不一致。")
            )
        if profile.variant.value == "aesthetic" and "score_" in candidate.positive_prompt:
            issues.append(_error(candidate, "aesthetic_score_token", "Aesthetic 候选不能包含 score_* token。"))
        if profile.negative_prompt_mode == NegativePromptMode.DISABLED and candidate.negative_prompt:
            issues.append(_error(candidate, "negative_prompt_disabled", "当前模型配置已禁用 negative prompt。"))

        by_id = {element.id: element for element in bundle.intent.graph.elements}
        for element_id in candidate.unresolved_element_ids:
            element = by_id[element_id]
            if element.state in {IntentState.LOCKED, IntentState.REQUIRED} and self.mapper.map_element(element):
                issues.append(
                    _error(
                        candidate,
                        "resolvable_required_marked_unresolved",
                        f"必需项可解析却被标记为 unresolved：{element.original_text}",
                        element_ids=(element_id,),
                    )
                )

    def _expected_exclusions(self, bundle: CandidateSet, profile: ModelProfile) -> tuple[set[str], str]:
        excluded_names: set[str] = set()
        rendered: list[str] = []
        for element in bundle.intent.graph.elements:
            if element.state != IntentState.EXCLUDED:
                continue
            mapping = self.mapper.map_element(element)
            if mapping is not None:
                excluded_names.add(mapping.canonical_name)
                rendered.append(mapping.rendered)
        if profile.negative_prompt_mode == NegativePromptMode.DISABLED:
            return excluded_names, ""
        values = list(dict.fromkeys([*profile.negative_prompt, *rendered]))
        return excluded_names, profile.tag_separator.join(values)

    @staticmethod
    def _validate_lane_differences(bundle: CandidateSet) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        signatures: dict[tuple[str, str, tuple[str, ...]], str] = {}
        for candidate in bundle.candidates:
            signature = (
                candidate.positive_prompt,
                candidate.negative_prompt,
                tuple(artist.name for artist in candidate.artists),
            )
            if signature in signatures:
                issues.append(
                    ValidationIssue(
                        code="duplicate_lane_output",
                        severity=ValidationSeverity.ERROR,
                        message=f"{candidate.id} 与 {signatures[signature]} 没有结构差异。",
                        candidate_id=candidate.id,
                    )
                )
            else:
                signatures[signature] = candidate.id
        return issues


def _error(
    candidate: PromptCandidate,
    code: str,
    message: str,
    *,
    element_ids: tuple[str, ...] = (),
    tag_names: tuple[str, ...] = (),
) -> ValidationIssue:
    return ValidationIssue(
        code=code,
        severity=ValidationSeverity.ERROR,
        message=message,
        candidate_id=candidate.id,
        element_ids=element_ids,
        tag_names=tag_names,
    )


def _render_tag_prompt(candidate: PromptCandidate, profile: ModelProfile) -> str:
    values = [*profile.positive_prefix, *(tag.rendered for tag in candidate.tags)]
    values.extend(artist.rendered for artist in candidate.artists)
    return profile.tag_separator.join(dict.fromkeys(values))
