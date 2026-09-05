"""Deterministic contract checks for policy candidates.

Recorded trajectory cases verify that a policy compiles to the explicit
guidance and tool choices required by prior observations.  They are offline
contract checks, not measurements of model reasoning quality.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from momentum_research_agent.models.schemas import MomentumCapability
from momentum_research_agent.state.policies import (
    ResearchPolicy,
    compiled_overlay,
    task_template_addition,
)


class RecordedTrajectoryCase(BaseModel):
    """An offline policy contract checkpoint with recorded context."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    profile: str = Field(min_length=1)
    capability: MomentumCapability
    observation: str = ""
    observation_provenance: str = ""
    source_trace_id: str = ""
    observation_sha256: str = ""
    required_overlay_terms: list[str] = Field(default_factory=list)
    forbidden_overlay_terms: list[str] = Field(default_factory=list)
    required_task_terms: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)


class EvalCaseProvider(Protocol):
    def load(self) -> list[RecordedTrajectoryCase]: ...


class FileEvalCaseProvider:
    """Load recorded contract checkpoints from a versioned JSON fixture."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[RecordedTrajectoryCase]:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("trajectory case fixture must contain a JSON list")
        return [RecordedTrajectoryCase.model_validate(item) for item in payload]


class CaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    layer: Literal["engine", "trajectory"]
    passed: bool
    score: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    failures: list[str] = Field(default_factory=list)


class SuiteResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[CaseResult]

    @property
    def aggregate_score(self) -> float:
        return sum(case.score for case in self.cases) / len(self.cases) if self.cases else 1.0


class PromotionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    promote: bool
    reason: str
    target_fixes: list[str] = Field(default_factory=list)


def _normalized_contains(text: str, term: str) -> bool:
    return term.lower() in text.lower()


def _matching_tools(policy: ResearchPolicy, case: RecordedTrajectoryCase) -> set[str]:
    tools: set[str] = set()
    for rule in policy.tool_policies:
        if rule.profile == case.profile and rule.capability is case.capability:
            tools.update(rule.required_tools)
            tools.update(rule.preferred_tools)
    return tools


def evaluate_trajectory_case(
    policy: ResearchPolicy, case: RecordedTrajectoryCase
) -> CaseResult:
    """Evaluate only declared policy checkpoints against a recorded case."""
    overlay = compiled_overlay(policy, case.profile, case.capability)
    task = task_template_addition(policy, case.capability)
    tools = _matching_tools(policy, case)
    failures: list[str] = []

    failures.extend(
        f"overlay:{term}"
        for term in case.required_overlay_terms
        if not _normalized_contains(overlay, term)
    )
    failures.extend(
        f"overlay-forbidden:{term}"
        for term in case.forbidden_overlay_terms
        if _normalized_contains(overlay, term)
    )
    failures.extend(
        f"task:{term}"
        for term in case.required_task_terms
        if not _normalized_contains(task, term)
    )
    failures.extend(f"tool:{tool}" for tool in case.required_tools if tool not in tools)
    return CaseResult(
        case_id=case.case_id,
        layer="trajectory",
        passed=not failures,
        score=1.0 if not failures else 0.0,
        failures=failures,
    )


def evaluate_policy(
    policy: ResearchPolicy,
    *,
    engine_results: list[CaseResult],
    trajectory_cases: list[RecordedTrajectoryCase],
) -> SuiteResult:
    """Combine invariant engine guards with policy-specific contract checks."""
    if any(result.layer != "engine" for result in engine_results):
        raise ValueError("engine_results must contain only engine-layer results")
    return SuiteResult(
        cases=[
            *engine_results,
            *(evaluate_trajectory_case(policy, case) for case in trajectory_cases),
        ]
    )


def _case_index(suite: SuiteResult, label: str) -> tuple[dict[str, CaseResult] | None, str | None]:
    if not suite.cases:
        return None, f"{label} suite is empty"
    indexed = {case.case_id: case for case in suite.cases}
    if len(indexed) != len(suite.cases):
        return None, f"{label} suite has duplicate case ids"
    return indexed, None


def compare_for_promotion(
    baseline: SuiteResult,
    candidate: SuiteResult,
    *,
    trigger_ids: set[str],
) -> PromotionDecision:
    """Fail closed unless a candidate fixes targets without any regression."""
    baseline_cases, baseline_error = _case_index(baseline, "baseline")
    if baseline_error:
        return PromotionDecision(promote=False, reason=baseline_error)
    candidate_cases, candidate_error = _case_index(candidate, "candidate")
    if candidate_error:
        return PromotionDecision(promote=False, reason=candidate_error)
    assert baseline_cases is not None and candidate_cases is not None

    if set(baseline_cases) != set(candidate_cases):
        return PromotionDecision(promote=False, reason="baseline and candidate case sets differ")
    for case_id, baseline_case in baseline_cases.items():
        if candidate_cases[case_id].layer != baseline_case.layer:
            return PromotionDecision(promote=False, reason=f"case layer differs: {case_id}")

    for case in [*baseline.cases, *candidate.cases]:
        if case.layer == "engine" and not case.passed:
            return PromotionDecision(
                promote=False,
                reason=f"engine guard failed: {case.case_id}",
            )

    regressions = [
        case_id
        for case_id, baseline_case in baseline_cases.items()
        if baseline_case.passed and not candidate_cases[case_id].passed
    ]
    if regressions:
        return PromotionDecision(promote=False, reason=f"regressed: {', '.join(sorted(regressions))}")

    score_regressions = [
        case_id
        for case_id, baseline_case in baseline_cases.items()
        if candidate_cases[case_id].score < baseline_case.score
    ]
    if score_regressions:
        return PromotionDecision(
            promote=False,
            reason=f"score regressed: {', '.join(sorted(score_regressions))}",
        )

    target_fixes = sorted(
        case_id
        for case_id in trigger_ids
        if case_id in baseline_cases
        and not baseline_cases[case_id].passed
        and candidate_cases[case_id].passed
    )
    if not target_fixes:
        return PromotionDecision(promote=False, reason="no triggering case was fixed")
    if candidate.aggregate_score <= baseline.aggregate_score:
        return PromotionDecision(
            promote=False,
            reason="aggregate score did not increase",
            target_fixes=target_fixes,
        )
    return PromotionDecision(
        promote=True,
        reason="target cases fixed without regressions",
        target_fixes=target_fixes,
    )
