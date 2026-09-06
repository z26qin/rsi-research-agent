from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from momentum_research_agent.eval.policy_suite import (
    CaseResult,
    FileEvalCaseProvider,
    RecordedTrajectoryCase,
    SuiteResult,
    compare_for_promotion,
    evaluate_policy,
    evaluate_trajectory_case,
)
from momentum_research_agent.models.schemas import MomentumCapability
from momentum_research_agent.state.policies import (
    PolicyPatch,
    PolicyStore,
    ToolPolicy,
    merge_policy_patch,
)


def suite_from_bools(results: dict[str, bool]) -> SuiteResult:
    return SuiteResult(
        cases=[
            CaseResult(
                case_id="engine:guard",
                layer="engine",
                passed=True,
                score=1.0,
            ),
            *[
            CaseResult(
                case_id=case_id,
                layer="trajectory",
                passed=passed,
                score=1.0 if passed else 0.0,
            )
            for case_id, passed in results.items()
            ],
        ]
    )


def test_empty_policy_fails_recorded_engine_freshness_checkpoint(tmp_path: Path) -> None:
    policy = PolicyStore(tmp_path).load_active()
    case = RecordedTrajectoryCase(
        case_id="trajectory:stale-engine",
        profile="momentum_analyst",
        capability=MomentumCapability.ENGINE_FRESHNESS,
        required_overlay_terms=["explicit as-of"],
        required_task_terms=["do not retry"],
        required_tools=["engine_query"],
    )

    result = evaluate_trajectory_case(policy, case)

    assert result.passed is False
    assert set(result.failures) == {
        "overlay:explicit as-of",
        "task:do not retry",
        "tool:engine_query",
    }
    assert result.score == 0.0


def test_matching_policy_passes_recorded_checkpoint(tmp_path: Path) -> None:
    base = PolicyStore(tmp_path).load_active()
    policy = merge_policy_patch(
        base,
        PolicyPatch(
            prompt_overlays={"momentum_analyst": "Use an explicit as-of date."},
            task_templates={
                MomentumCapability.ENGINE_FRESHNESS: "Do not retry the failed call."
            },
            tool_policies=[
                ToolPolicy(
                    profile="momentum_analyst",
                    capability=MomentumCapability.ENGINE_FRESHNESS,
                    preferred_tools=["engine_query"],
                )
            ],
        ),
        trigger_ids=["trajectory:stale-engine"],
    )
    case = RecordedTrajectoryCase(
        case_id="trajectory:stale-engine",
        profile="momentum_analyst",
        capability=MomentumCapability.ENGINE_FRESHNESS,
        required_overlay_terms=["explicit as-of"],
        required_task_terms=["do not retry"],
        required_tools=["engine_query"],
    )

    result = evaluate_trajectory_case(policy, case)

    assert result.passed is True
    assert result.score == 1.0
    assert result.failures == []


def test_trajectory_checkpoints_normalize_terms_and_reject_forbidden_guidance(
    tmp_path: Path,
) -> None:
    base = PolicyStore(tmp_path).load_active()
    policy = merge_policy_patch(
        base,
        PolicyPatch(prompt_overlays={"flow_analyst": "Prefer PRIMARY source evidence."}),
        trigger_ids=["trajectory:source-quality"],
    )
    case = RecordedTrajectoryCase(
        case_id="trajectory:source-quality",
        profile="flow_analyst",
        capability=MomentumCapability.SOURCE_QUALITY,
        required_overlay_terms=["primary source"],
        forbidden_overlay_terms=["secondary commentary"],
    )

    result = evaluate_trajectory_case(policy, case)

    assert result.passed is True

    forbidden = policy.model_copy(
        update={
            "prompt_overlays": {
                "flow_analyst": "Prefer primary source evidence, not secondary commentary."
            }
        }
    )
    forbidden_result = evaluate_trajectory_case(forbidden, case)
    assert forbidden_result.passed is False
    assert forbidden_result.failures == ["overlay-forbidden:secondary commentary"]


def test_file_provider_loads_three_provenanced_contract_checkpoints() -> None:
    fixture_path = (
        Path(__file__).parents[1]
        / "src"
        / "momentum_research_agent"
        / "eval"
        / "fixtures"
        / "trajectory_cases.json"
    )

    cases = FileEvalCaseProvider(fixture_path).load()

    assert {case.case_id for case in cases} == {
        "trajectory:stale-engine",
        "trajectory:source-quality",
        "trajectory:crowding-web-search",
    }
    assert all(case.observation_provenance for case in cases)
    assert all("examples/nvda_momentum_gap_ledger.json" in case.observation_provenance for case in cases)
    assert any("synthetic checkpoint" in case.observation_provenance for case in cases)
    recorded = json.loads(
        (Path(__file__).parents[1] / "examples" / "nvda_momentum_gap_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    traces = {trace["id"]: trace for trace in recorded["traces"]}
    assert all(case.observation == traces[case.source_trace_id]["observation"] for case in cases)
    assert all(
        case.observation_sha256 == traces[case.source_trace_id]["observation_sha256"]
        for case in cases
    )


def test_evaluate_policy_preserves_engine_guards_and_adds_trajectory_results(
    tmp_path: Path,
) -> None:
    policy = PolicyStore(tmp_path).load_active()
    engine = CaseResult(case_id="dm-2026-05-29", layer="engine", passed=True, score=1.0)
    trajectory = RecordedTrajectoryCase(
        case_id="trajectory:empty-policy",
        profile="momentum_analyst",
        capability=MomentumCapability.ENGINE_FRESHNESS,
        required_overlay_terms=["explicit as-of"],
    )

    suite = evaluate_policy(policy, engine_results=[engine], trajectory_cases=[trajectory])

    assert suite.cases[0] == engine
    assert suite.cases[1].case_id == "trajectory:empty-policy"
    assert suite.cases[1].passed is False


def test_case_result_rejects_non_finite_or_out_of_range_score() -> None:
    for score in (-0.1, 1.1, float("nan"), float("inf")):
        with pytest.raises(ValidationError):
            CaseResult(case_id="case", layer="engine", passed=False, score=score)


def test_promotion_requires_target_fix_and_zero_regressions() -> None:
    baseline = suite_from_bools({"target": False, "guard": True})
    improved = suite_from_bools({"target": True, "guard": True})

    decision = compare_for_promotion(baseline, improved, trigger_ids={"target"})

    assert decision.promote is True
    assert decision.target_fixes == ["target"]


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        ({"target": False, "guard": True}, "no triggering case was fixed"),
        ({"target": True, "guard": False}, "regressed: guard"),
    ],
)
def test_promotion_rejects_ties_and_per_case_regressions(
    candidate: dict[str, bool], reason: str
) -> None:
    baseline = suite_from_bools({"target": False, "guard": True})

    decision = compare_for_promotion(
        baseline,
        suite_from_bools(candidate),
        trigger_ids={"target"},
    )

    assert decision.promote is False
    assert reason in decision.reason


@pytest.mark.parametrize(
    ("baseline", "candidate", "reason"),
    [
        (SuiteResult(cases=[]), SuiteResult(cases=[]), "empty"),
        (
            suite_from_bools({"target": False, "guard": True}),
            suite_from_bools({"target": True, "other": True}),
            "case sets differ",
        ),
        (
            suite_from_bools({"target": False, "guard": True}),
            SuiteResult(
                cases=[
                    CaseResult(case_id="engine:guard", layer="engine", passed=True, score=1.0),
                    CaseResult(case_id="target", layer="trajectory", passed=True, score=1.0),
                    CaseResult(case_id="target", layer="trajectory", passed=True, score=1.0),
                ]
            ),
            "duplicate",
        ),
    ],
)
def test_promotion_rejects_invalid_or_incomparable_case_sets(
    baseline: SuiteResult, candidate: SuiteResult, reason: str
) -> None:
    decision = compare_for_promotion(baseline, candidate, trigger_ids={"target"})

    assert decision.promote is False
    assert reason in decision.reason


@pytest.mark.parametrize(
    ("baseline", "candidate", "reason"),
    [
        (
            SuiteResult(
                cases=[CaseResult(case_id="engine:guard", layer="engine", passed=True, score=1.0)]
            ),
            SuiteResult(
                cases=[CaseResult(case_id="engine:guard", layer="engine", passed=True, score=1.0)]
            ),
            "no trajectory cases",
        ),
        (
            SuiteResult(
                cases=[CaseResult(case_id="target", layer="trajectory", passed=False, score=0.0)]
            ),
            SuiteResult(
                cases=[CaseResult(case_id="target", layer="trajectory", passed=True, score=1.0)]
            ),
            "no engine guard",
        ),
    ],
)
def test_promotion_requires_engine_and_trajectory_layers(
    baseline: SuiteResult, candidate: SuiteResult, reason: str
) -> None:
    decision = compare_for_promotion(baseline, candidate, trigger_ids={"target"})

    assert decision.promote is False
    assert reason in decision.reason


def test_promotion_rejects_failing_engine_guard_and_score_decrease() -> None:
    baseline = SuiteResult(
        cases=[
            CaseResult(case_id="target", layer="trajectory", passed=False, score=0.5),
            CaseResult(case_id="engine", layer="engine", passed=True, score=1.0),
            CaseResult(case_id="guard", layer="trajectory", passed=False, score=0.5),
        ]
    )
    candidate = SuiteResult(
        cases=[
            CaseResult(case_id="target", layer="trajectory", passed=True, score=1.0),
            CaseResult(case_id="engine", layer="engine", passed=False, score=0.0),
            CaseResult(case_id="guard", layer="trajectory", passed=False, score=0.4),
        ]
    )

    decision = compare_for_promotion(baseline, candidate, trigger_ids={"target"})

    assert decision.promote is False
    assert "engine guard failed: engine" in decision.reason

    healthy_engine_candidate = candidate.model_copy(
        update={
            "cases": [
                *candidate.cases[:1],
                CaseResult(case_id="engine", layer="engine", passed=True, score=1.0),
                *candidate.cases[2:],
            ]
        }
    )
    decision = compare_for_promotion(baseline, healthy_engine_candidate, trigger_ids={"target"})
    assert decision.promote is False
    assert "score regressed: guard" in decision.reason
