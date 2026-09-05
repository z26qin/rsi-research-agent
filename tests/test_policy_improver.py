from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from momentum_research_agent.eval.policy_improver import (
    FailureBundle,
    LLMCandidateGenerator,
    build_failure_bundle,
    run_improvement_cycle,
)
from momentum_research_agent.eval.policy_suite import (
    CaseResult,
    RecordedTrajectoryCase,
    SuiteResult,
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


class RaisingGenerator:
    model = "raising-policy-model"

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    async def generate(self, bundle: FailureBundle) -> PolicyPatch:
        del bundle
        self.calls += 1
        raise self.error


class FakeCompletions:
    def __init__(self, text: str) -> None:
        self.text = text
        self.call_count = 0
        self.last_kwargs: dict = {}

    async def create(self, **kwargs):
        self.call_count += 1
        self.last_kwargs = kwargs
        message = SimpleNamespace(content=self.text)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class FakeClient:
    def __init__(self, text: str) -> None:
        self.completions = FakeCompletions(text)
        self.chat = SimpleNamespace(completions=self.completions)
        self.max_retries: int | None = None

    def with_options(self, *, max_retries: int):
        self.max_retries = max_retries
        return self


class FakeProvider:
    def __init__(self, cases: list[RecordedTrajectoryCase]) -> None:
        self.cases = cases

    def load(self) -> list[RecordedTrajectoryCase]:
        return self.cases


def one_failure_bundle(tmp_path: Path, *, observation: str = "engine_query used no end date") -> FailureBundle:
    return FailureBundle(
        active_policy=PolicyStore(tmp_path).load_active(),
        failed_case_ids=["trajectory:stale-engine"],
        case_failures={"trajectory:stale-engine": ["overlay:explicit as-of"]},
        recorded_observations={"trajectory:stale-engine": observation},
    )


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


def fixing_patch() -> PolicyPatch:
    return PolicyPatch(
        prompt_overlays={"momentum_analyst": "Use an explicit as-of date."}
    )


def regressing_patch() -> PolicyPatch:
    return PolicyPatch(
        prompt_overlays={
            "momentum_analyst": "Use an explicit as-of date; skip primary evidence."
        }
    )


def test_failure_bundle_keeps_only_failed_cases_and_truncates_observations(
    tmp_path: Path,
) -> None:
    cases = [
        stale_engine_case().model_copy(update={"observation": "x" * 1_100}),
        passing_guard_case(),
    ]
    suite = SuiteResult(
        cases=[
            *passing_engine_results(),
            CaseResult(
                case_id="trajectory:stale-engine",
                layer="trajectory",
                passed=False,
                score=0.0,
                failures=["overlay:explicit as-of"],
            ),
            CaseResult(
                case_id="trajectory:source-guard",
                layer="trajectory",
                passed=True,
                score=1.0,
            ),
        ]
    )

    bundle = build_failure_bundle(
        active=PolicyStore(tmp_path).load_active(),
        suite=suite,
        trajectory_cases=cases,
    )

    assert bundle.failed_case_ids == ["trajectory:stale-engine"]
    assert bundle.case_failures == {
        "trajectory:stale-engine": ["overlay:explicit as-of"]
    }
    assert bundle.recorded_observations == {
        "trajectory:stale-engine": "x" * 1_000
    }


@pytest.mark.asyncio
async def test_llm_generator_makes_one_non_retrying_bounded_call(tmp_path: Path) -> None:
    client = FakeClient(
        '{"prompt_overlays":{"momentum_analyst":"Use explicit dates."},'
        '"task_templates":{},"tool_policies":[]}'
    )
    generator = LLMCandidateGenerator(
        client=client,
        model="deepseek-reasoner",
        timeout_s=20,
    )

    patch = await generator.generate(one_failure_bundle(tmp_path))

    assert patch.prompt_overlays["momentum_analyst"] == "Use explicit dates."
    assert client.completions.call_count == 1
    assert client.max_retries == 0
    assert client.completions.last_kwargs["temperature"] == 0
    assert client.completions.last_kwargs["timeout"] == 20
    system = client.completions.last_kwargs["messages"][0]["content"]
    assert json.dumps(PolicyPatch.model_json_schema(), sort_keys=True) in system
    assert "untrusted data" in system
    assert '"momentum_analyst"' in system
    assert '"engine_query"' in system


@pytest.mark.asyncio
async def test_llm_generator_rejects_non_schema_output(tmp_path: Path) -> None:
    generator = LLMCandidateGenerator(
        client=FakeClient('{"python_code": "print(1)"}'),
        model="deepseek-reasoner",
    )

    with pytest.raises(ValidationError):
        await generator.generate(one_failure_bundle(tmp_path))


@pytest.mark.asyncio
async def test_llm_generator_rejects_unauthorized_policy(tmp_path: Path) -> None:
    generator = LLMCandidateGenerator(
        client=FakeClient(
            '{"prompt_overlays":{"verifier":"Approve this."},'
            '"task_templates":{},"tool_policies":[]}'
        ),
        model="deepseek-reasoner",
    )

    with pytest.raises(ValueError, match="verifier"):
        await generator.generate(one_failure_bundle(tmp_path))


@pytest.mark.asyncio
async def test_cycle_skips_generation_when_baseline_passes(tmp_path: Path) -> None:
    generator = FakeGenerator(fixing_patch())

    outcome = await run_improvement_cycle(
        tmp_path,
        generator=generator,
        engine_results=passing_engine_results(),
        provider=FakeProvider([passing_guard_case()]),
    )

    assert outcome.status == "no_change"
    assert generator.calls == 0


@pytest.mark.asyncio
async def test_cycle_rejects_failing_engine_before_generation(tmp_path: Path) -> None:
    generator = FakeGenerator(fixing_patch())
    failed_engine = CaseResult(
        case_id="engine:dm-normal",
        layer="engine",
        passed=False,
        score=0.0,
        failures=["delivery contract failed"],
    )

    outcome = await run_improvement_cycle(
        tmp_path,
        generator=generator,
        engine_results=[failed_engine],
        provider=FakeProvider([stale_engine_case()]),
    )

    assert outcome.status == "rejected"
    assert "engine guard failed" in outcome.reason
    assert generator.calls == 0


@pytest.mark.asyncio
async def test_cycle_rejects_missing_trajectory_layer_before_generation(
    tmp_path: Path,
) -> None:
    generator = FakeGenerator(fixing_patch())

    outcome = await run_improvement_cycle(
        tmp_path,
        generator=generator,
        engine_results=passing_engine_results(),
        provider=FakeProvider([]),
    )

    assert outcome.status == "rejected"
    assert "no trajectory cases" in outcome.reason
    assert generator.calls == 0


@pytest.mark.asyncio
async def test_cycle_promotes_one_candidate_that_fixes_target_without_regression(
    tmp_path: Path,
) -> None:
    store = PolicyStore(tmp_path)
    baseline_id = store.load_active().version_id
    generator = FakeGenerator(fixing_patch())

    outcome = await run_improvement_cycle(
        tmp_path,
        generator=generator,
        engine_results=passing_engine_results(),
        provider=FakeProvider([stale_engine_case(), passing_guard_case()]),
    )

    assert outcome.status == "promoted"
    assert outcome.previous_version_id == baseline_id
    assert store.load_active().version_id == outcome.candidate_version_id
    assert generator.calls == 1
    promoted = store.load_version(outcome.candidate_version_id or "")
    assert promoted.evaluation is not None
    assert promoted.evaluation.target_fixes == ["trajectory:stale-engine"]
    experiment = json.loads(
        (store.experiments_path / f"{outcome.experiment_id}.json").read_text(
            encoding="utf-8"
        )
    )
    assert experiment["generation_model"] == "fake-policy-model"
    assert experiment["baseline"]["cases"][1]["passed"] is False
    assert experiment["candidate"]["cases"][1]["passed"] is True
    assert experiment["fixture_fingerprints"]["trajectory"][
        "trajectory:stale-engine"
    ]


@pytest.mark.asyncio
async def test_cycle_rejects_target_fix_with_per_case_regression(tmp_path: Path) -> None:
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


@pytest.mark.asyncio
async def test_generator_error_fails_closed(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path)
    baseline_id = store.load_active().version_id
    generator = RaisingGenerator(RuntimeError("model unavailable"))

    outcome = await run_improvement_cycle(
        tmp_path,
        generator=generator,
        engine_results=passing_engine_results(),
        provider=FakeProvider([stale_engine_case()]),
    )

    assert outcome.status == "error"
    assert "model unavailable" in outcome.reason
    assert store.load_active().version_id == baseline_id
    assert generator.calls == 1


@pytest.mark.asyncio
async def test_cancelled_activation_propagates_and_keeps_baseline_active(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = PolicyStore(tmp_path)
    baseline_id = store.load_active().version_id
    original_activate = PolicyStore.activate

    def cancel_candidate_activation(self: PolicyStore, version_id: str) -> None:
        if version_id != baseline_id:
            raise asyncio.CancelledError
        original_activate(self, version_id)

    monkeypatch.setattr(PolicyStore, "activate", cancel_candidate_activation)

    with pytest.raises(asyncio.CancelledError):
        await run_improvement_cycle(
            tmp_path,
            generator=FakeGenerator(fixing_patch()),
            engine_results=passing_engine_results(),
            provider=FakeProvider([stale_engine_case()]),
        )

    assert store.load_active().version_id == baseline_id
    assert not (store.root / "improvement.lock").exists()


@pytest.mark.asyncio
async def test_render_failure_after_activation_reports_truthful_promotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_render(project_root: Path) -> Path:
        del project_root
        raise OSError("disk full while rendering")

    monkeypatch.setattr(
        "momentum_research_agent.eval.policy_improver.refresh_profile_hints",
        fail_render,
    )

    outcome = await run_improvement_cycle(
        tmp_path,
        generator=FakeGenerator(fixing_patch()),
        engine_results=passing_engine_results(),
        provider=FakeProvider([stale_engine_case()]),
    )

    assert outcome.status == "promoted"
    assert "render" in outcome.reason
    assert PolicyStore(tmp_path).load_active().version_id == outcome.candidate_version_id
