"""Paired behavioral shadow comparison over bounded replay runs."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from momentum_research_agent.agents.budget import LoopBudget
from momentum_research_agent.eval.replay_runner import (
    LLMRequestBudget,
    ReplayRunResult,
    case_content_sha256,
    run_replay_case,
)
from momentum_research_agent.eval.session_cases import SessionEvalCase
from momentum_research_agent.eval.session_cases import load_session_eval_cases
from momentum_research_agent.models.schemas import ResearchReport, UsageSummary, new_session_id, utcnow
from momentum_research_agent.state.policies import PolicyStore, ResearchPolicy, _expected_version_id


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


class ExpectedToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: Literal["engine_query", "web_search"]
    arguments: dict[str, Any]
    as_of: str | None = None

    @model_validator(mode="after")
    def validate_as_of(self) -> ExpectedToolCall:
        if self.as_of is not None:
            if self.tool != "engine_query":
                raise ValueError("as_of applies only to engine_query")
            if self.arguments.get("end") != self.as_of:
                raise ValueError("engine_query as_of must equal its end argument")
        _canonical_json(self.arguments)
        return self


class ExpectedEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_url: str | None = None
    excerpt: str | None = None
    source_name: Literal["engine_query", "web_search"] | None = None

    @model_validator(mode="after")
    def require_provenance(self) -> ExpectedEvidence:
        if not self.source_url and not self.excerpt:
            raise ValueError("expected evidence needs a source URL or excerpt")
        return self


class BehavioralExpectation(BaseModel):
    """Reviewer-authored behavioral assertions bound to exact case content."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    case_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal["target", "guard"]
    reviewer: str = Field(min_length=1)
    provenance: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    required_calls: list[ExpectedToolCall] = Field(min_length=1)
    allowed_report_statuses: list[
        Literal["complete", "partial", "insufficient_evidence"]
    ] = Field(min_length=1)
    required_evidence: list[ExpectedEvidence] = Field(default_factory=list)
    require_no_findings: bool = False

    @field_validator("allowed_report_statuses")
    @classmethod
    def unique_statuses(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("allowed report statuses must be unique")
        return value

    @model_validator(mode="after")
    def reject_vacuous_or_conflicting_claim_assertions(self) -> BehavioralExpectation:
        if not self.required_evidence and not self.require_no_findings:
            raise ValueError("expectation needs required evidence or explicit withholding")
        if self.required_evidence and self.require_no_findings:
            raise ValueError("withholding cannot also require evidence")
        return self


class BehavioralExpectationSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_kind: Literal["behavioral_expectations_v1"] = "behavioral_expectations_v1"
    expectations: list[BehavioralExpectation] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_case_ids(self) -> BehavioralExpectationSet:
        ids = [item.case_id for item in self.expectations]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate behavioral expectation case ids")
        return self

    def bind_cases(
        self, cases: list[SessionEvalCase]
    ) -> dict[str, BehavioralExpectation]:
        indexed = {item.case_id: item for item in self.expectations}
        for case in cases:
            expectation = indexed.get(case.case_id)
            if expectation is None:
                raise ValueError(f"missing expectation for case {case.case_id}")
            if expectation.case_sha256 != case_content_sha256(case):
                raise ValueError(f"expectation content hash differs for case {case.case_id}")
        return indexed


class BehavioralRunAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    unscorable: bool = False
    violations: list[str] = Field(default_factory=list)


class ShadowRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant: Literal["baseline", "candidate"]
    repeat: int = Field(ge=1)
    result: ReplayRunResult
    assessment: BehavioralRunAssessment


class CaseComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    kind: Literal["target", "guard"]
    complete: bool
    baseline_passes: int = Field(ge=0)
    candidate_passes: int = Field(ge=0)
    repeats: int = Field(ge=1)
    target_improved: bool = False
    guard_no_regression: bool = False


class LiveComparisonReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_kind: Literal["live_behavioral_shadow_v1"] = "live_behavioral_shadow_v1"
    run_id: str
    created_at: Any = Field(default_factory=utcnow)
    outcome: Literal["completed", "failed"]
    reasons: list[str] = Field(default_factory=list)
    requested_model: str
    model_fairness: bool
    repeats: int
    max_cases: int
    max_llm_calls: int
    attempted_llm_calls: int
    max_output_tokens: int
    loop_budget: dict[str, float | int]
    baseline_policy: ResearchPolicy
    candidate_policy: ResearchPolicy
    cases: list[SessionEvalCase]
    expectations: BehavioralExpectationSet
    expectations_sha256: str
    runs: list[ShadowRun]
    case_results: list[CaseComparison]
    observed_no_regression: bool
    target_improvements: list[str] = Field(default_factory=list)
    total_usage: UsageSummary = Field(default_factory=UsageSummary)


def expectations_content_sha256(expectations: BehavioralExpectationSet) -> str:
    payload = _canonical_json(expectations.model_dump(mode="json"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_expectations(path: Path) -> BehavioralExpectationSet:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return BehavioralExpectationSet.model_validate(payload)


def load_policy_reference(project_root: Path, reference: str) -> ResearchPolicy:
    """Load an immutable version ID or a content-addressed policy JSON file."""
    candidate = Path(reference).expanduser()
    if candidate.is_file():
        policy = ResearchPolicy.model_validate_json(candidate.read_text(encoding="utf-8"))
        if policy.version_id != _expected_version_id(policy):
            raise ValueError("policy file content does not match its version_id")
        return policy
    return PolicyStore(Path(project_root)).load_version(reference)


def load_cases_reference(project_root: Path, path: Path) -> list[SessionEvalCase]:
    """Load explicitly selected cases from a file, directory, or case-id manifest."""
    source = Path(path).expanduser()
    if source.is_dir():
        cases = sorted(
            [
                SessionEvalCase.model_validate_json(item.read_text(encoding="utf-8"))
                for item in source.glob("*.json")
            ],
            key=lambda case: case.case_id,
        )
        if not cases:
            raise ValueError("no replay cases found in selected directory")
        return cases
    payload = json.loads(source.read_text(encoding="utf-8"))
    items = payload.get("cases") if isinstance(payload, dict) and "cases" in payload else payload
    if not isinstance(items, list) or not items:
        raise ValueError("cases file must contain a non-empty list")
    if all(isinstance(item, dict) and item.get("schema_kind") == "session_eval_case_v1" for item in items):
        cases = [SessionEvalCase.model_validate(item) for item in items]
    else:
        requested_ids = [
            item if isinstance(item, str) else item.get("case_id") if isinstance(item, dict) else None
            for item in items
        ]
        if any(not isinstance(case_id, str) or not case_id for case_id in requested_ids):
            raise ValueError("case manifest entries must provide case_id")
        available = {case.case_id: case for case in load_session_eval_cases(project_root)}
        missing = [case_id for case_id in requested_ids if case_id not in available]
        if missing:
            raise ValueError(f"selected case is not present in reports/eval_cases: {missing[0]}")
        cases = [available[case_id] for case_id in requested_ids]
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("cases selection contains duplicate case ids")
    return cases


def _call_present(run: ReplayRunResult, expected: ExpectedToolCall) -> bool:
    canonical = _canonical_json(expected.arguments)
    return any(
        call.matched_trace_id is not None
        and call.tool == expected.tool
        and call.canonical_arguments == canonical
        and (expected.as_of is None or call.arguments.get("end") == expected.as_of)
        for call in run.calls
    )


def _finding_is_grounded(finding: Any, run: ReplayRunResult) -> bool:
    if not finding.source_url and not finding.excerpt:
        return False
    for call in run.calls:
        if call.matched_trace_id is None:
            continue
        if finding.source_name in {"engine_query", "web_search"} and finding.source_name != call.tool:
            continue
        if finding.source_url and finding.source_url not in call.result:
            continue
        if finding.excerpt and finding.excerpt not in call.result:
            continue
        return True
    return False


def _required_evidence_present(expected: ExpectedEvidence, report: ResearchReport) -> bool:
    return any(
        (expected.source_url is None or finding.source_url == expected.source_url)
        and (expected.excerpt is None or finding.excerpt == expected.excerpt)
        and (expected.source_name is None or finding.source_name == expected.source_name)
        for finding in report.findings
    )


def assess_replay_run(
    run: ReplayRunResult,
    expectation: BehavioralExpectation,
) -> BehavioralRunAssessment:
    if run.outcome != "success" or run.report is None:
        return BehavioralRunAssessment(
            passed=False,
            unscorable=True,
            violations=[*run.reasons] or ["replay_run_incomplete"],
        )
    violations: list[str] = []
    if run.case_id != expectation.case_id or run.case_sha256 != expectation.case_sha256:
        violations.append("run_case_binding_mismatch")
    if any(not _call_present(run, expected) for expected in expectation.required_calls):
        violations.append("missing_required_call")
    if run.report.status not in expectation.allowed_report_statuses:
        violations.append("unexpected_report_status")
    if expectation.require_no_findings and run.report.findings:
        violations.append("expected_claim_withholding")
    if any(
        not _required_evidence_present(expected, run.report)
        for expected in expectation.required_evidence
    ):
        violations.append("missing_required_evidence")
    if any(not _finding_is_grounded(finding, run) for finding in run.report.findings):
        violations.append("finding_not_grounded_in_consumed_observation")
    return BehavioralRunAssessment(passed=not violations, violations=violations)


def _failed_result(
    case: SessionEvalCase,
    policy: ResearchPolicy,
    requested_model: str,
    max_output_tokens: int,
    reason: str,
) -> ReplayRunResult:
    return ReplayRunResult(
        case_id=case.case_id,
        case_sha256=case_content_sha256(case),
        policy_version_id=policy.version_id,
        requested_model=requested_model,
        max_output_tokens=max_output_tokens,
        outcome="failed",
        reasons=[reason],
    )


async def run_live_compare(
    *,
    client: Any,
    requested_model: str,
    project_root: Path,
    baseline_policy: ResearchPolicy,
    candidate_policy: ResearchPolicy,
    cases: list[SessionEvalCase],
    expectations: BehavioralExpectationSet,
    repeats: int,
    max_cases: int,
    request_budget: LLMRequestBudget,
    max_output_tokens: int,
    budget: LoopBudget,
) -> tuple[LiveComparisonReport, Path]:
    """Run paired shadows and persist an auditable report without promotion writes."""
    for label, value in (
        ("repeats", repeats),
        ("max_cases", max_cases),
        ("max_output_tokens", max_output_tokens),
    ):
        if value <= 0:
            raise ValueError(f"{label} must be positive")
    if baseline_policy.version_id == candidate_policy.version_id:
        raise ValueError("baseline and candidate policies must differ")
    if baseline_policy.version_id != _expected_version_id(baseline_policy):
        raise ValueError("baseline policy content is invalid")
    if candidate_policy.version_id != _expected_version_id(candidate_policy):
        raise ValueError("candidate policy content is invalid")
    if not cases:
        raise ValueError("no replay cases selected")
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("duplicate replay case ids")
    selected = list(cases[:max_cases])
    bound = expectations.bind_cases(selected)
    kinds = {bound[case.case_id].kind for case in selected}
    if "target" not in kinds or "guard" not in kinds:
        raise ValueError("selected comparison requires at least one target and one guard")

    run_id = new_session_id()
    run_dir = Path(project_root) / "reports" / "live_evals" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    shadow_runs: list[ShadowRun] = []
    total_usage = UsageSummary()

    for case in selected:
        expectation = bound[case.case_id]
        for repeat in range(1, repeats + 1):
            for variant, policy in (
                ("baseline", baseline_policy),
                ("candidate", candidate_policy),
            ):
                try:
                    result = await run_replay_case(
                        client=client,
                        requested_model=requested_model,
                        project_root=project_root,
                        case=case,
                        policy=policy,
                        budget=budget,
                        request_budget=request_budget,
                        max_output_tokens=max_output_tokens,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    result = _failed_result(
                        case,
                        policy,
                        requested_model,
                        max_output_tokens,
                        f"replay_failed:{type(exc).__name__}",
                    )
                total_usage.extend(result.usage)
                shadow_runs.append(
                    ShadowRun(
                        variant=variant,
                        repeat=repeat,
                        result=result,
                        assessment=assess_replay_run(result, expectation),
                    )
                )

    all_runs_complete = all(item.result.outcome == "success" for item in shadow_runs)
    run_index = {
        (item.result.case_id, item.repeat, item.variant): item for item in shadow_runs
    }
    model_fairness = all_runs_complete
    for case in selected:
        for repeat in range(1, repeats + 1):
            baseline_run = run_index[(case.case_id, repeat, "baseline")]
            candidate_run = run_index[(case.case_id, repeat, "candidate")]
            baseline_models = set(baseline_run.result.response_model_ids)
            candidate_models = set(candidate_run.result.response_model_ids)
            if (
                not baseline_models
                or "unknown" in baseline_models
                or baseline_models != candidate_models
            ):
                model_fairness = False

    case_results: list[CaseComparison] = []
    for case in selected:
        expectation = bound[case.case_id]
        relevant = [item for item in shadow_runs if item.result.case_id == case.case_id]
        baseline_runs = [item for item in relevant if item.variant == "baseline"]
        candidate_runs = [item for item in relevant if item.variant == "candidate"]
        complete = (
            model_fairness
            and len(baseline_runs) == repeats
            and len(candidate_runs) == repeats
            and all(not item.assessment.unscorable for item in relevant)
        )
        baseline_passes = sum(item.assessment.passed for item in baseline_runs)
        candidate_passes = sum(item.assessment.passed for item in candidate_runs)
        case_results.append(
            CaseComparison(
                case_id=case.case_id,
                kind=expectation.kind,
                complete=complete,
                baseline_passes=baseline_passes,
                candidate_passes=candidate_passes,
                repeats=repeats,
                target_improved=(
                    expectation.kind == "target"
                    and complete
                    and candidate_passes > baseline_passes
                ),
                guard_no_regression=(
                    expectation.kind == "guard"
                    and complete
                    and candidate_passes >= baseline_passes
                ),
            )
        )

    complete_comparison = all(item.complete for item in case_results)
    guard_results = [item for item in case_results if item.kind == "guard"]
    observed_no_regression = (
        complete_comparison
        and bool(guard_results)
        and all(item.guard_no_regression for item in guard_results)
    )
    target_improvements = sorted(
        item.case_id for item in case_results if item.target_improved
    )
    reasons: list[str] = []
    if not all_runs_complete:
        reasons.append("incomplete_paired_runs")
    if not model_fairness:
        reasons.append("resolved_model_mismatch")
    selected_expectations = BehavioralExpectationSet(
        expectations=[bound[case.case_id] for case in selected]
    )

    report = LiveComparisonReport(
        run_id=run_id,
        outcome="completed" if complete_comparison else "failed",
        reasons=reasons,
        requested_model=requested_model,
        model_fairness=model_fairness,
        repeats=repeats,
        max_cases=max_cases,
        max_llm_calls=request_budget.max_attempts,
        attempted_llm_calls=request_budget.attempts,
        max_output_tokens=max_output_tokens,
        loop_budget={
            "max_turns": budget.max_turns,
            "overall_deadline_s": budget.overall_deadline_s,
            "llm_timeout_s": budget.llm_timeout_s,
            "tool_timeout_s": budget.tool_timeout_s,
        },
        baseline_policy=baseline_policy,
        candidate_policy=candidate_policy,
        cases=selected,
        expectations=selected_expectations,
        expectations_sha256=expectations_content_sha256(selected_expectations),
        runs=shadow_runs,
        case_results=case_results,
        observed_no_regression=observed_no_regression,
        target_improvements=target_improvements,
        total_usage=total_usage,
    )
    report_path = run_dir / "comparison.json"
    temp_path = run_dir / "comparison.json.tmp"
    temp_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(report_path)
    return report, report_path
