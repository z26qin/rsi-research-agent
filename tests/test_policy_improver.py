from __future__ import annotations

from pathlib import Path

import pytest

from momentum_research_agent.eval.policy_improver import (
    FailureBundle,
    run_improvement_cycle,
)
from momentum_research_agent.eval.policy_suite import (
    CaseResult,
    RecordedTrajectoryCase,
)
from momentum_research_agent.models.schemas import MomentumCapability
from momentum_research_agent.state.policies import PolicyPatch, PolicyStore


class FakeGenerator:
    model = "fake-policy-model"

    def __init__(self, patch: PolicyPatch) -> None:
        self.patch = patch
        self.calls = 0
        self.last_bundle: FailureBundle | None = None

    async def generate(self, bundle: FailureBundle) -> PolicyPatch:
        self.calls += 1
        self.last_bundle = bundle
        return self.patch


class FakeProvider:
    def __init__(self, cases: list[RecordedTrajectoryCase]) -> None:
        self.cases = cases

    def load(self) -> list[RecordedTrajectoryCase]:
        return self.cases


def passing_engine_results() -> list[CaseResult]:
    return [
        CaseResult(
            case_id="engine:dm-normal",
            layer="engine",
            passed=True,
            score=1.0,
        )
    ]


def stale_engine_case() -> RecordedTrajectoryCase:
    return RecordedTrajectoryCase(
        case_id="trajectory:stale-engine",
        profile="momentum_analyst",
        capability=MomentumCapability.ENGINE_FRESHNESS,
        observation="engine_query was called without an explicit end date",
        observation_sha256="stale-fixture-sha256",
        required_overlay_terms=["explicit as-of"],
    )


def passing_guard_case() -> RecordedTrajectoryCase:
    return RecordedTrajectoryCase(
        case_id="trajectory:source-guard",
        profile="momentum_analyst",
        capability=MomentumCapability.SOURCE_QUALITY,
        observation="primary evidence must remain required",
        observation_sha256="guard-fixture-sha256",
        forbidden_overlay_terms=["skip primary evidence"],
    )


def regressing_patch() -> PolicyPatch:
    return PolicyPatch(
        prompt_overlays={
            "momentum_analyst": "Use an explicit as-of date; skip primary evidence."
        }
    )


@pytest.mark.asyncio
async def test_cycle_rejects_target_fix_with_per_case_regression(
    tmp_path: Path,
) -> None:
    store = PolicyStore(tmp_path)
    baseline_id = store.load_active().version_id

    outcome = await run_improvement_cycle(
        tmp_path,
        generator=FakeGenerator(regressing_patch()),
        engine_results=passing_engine_results(),
        provider=FakeProvider([stale_engine_case(), passing_guard_case()]),
    )

    assert outcome.status == "rejected"
    assert "regressed: trajectory:source-guard" in outcome.reason
    assert store.load_active().version_id == baseline_id
    assert (store.experiments_path / f"{outcome.experiment_id}.json").exists()
