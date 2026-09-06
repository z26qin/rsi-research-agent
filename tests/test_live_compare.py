from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from momentum_research_agent.agents.budget import LoopBudget
from momentum_research_agent.eval.live_compare import (
    BehavioralExpectation,
    BehavioralExpectationSet,
    ExpectedEvidence,
    ExpectedToolCall,
    assess_replay_run,
    expectations_content_sha256,
    load_cases_reference,
    load_expectations,
    load_policy_reference,
    run_live_compare,
)
from momentum_research_agent.eval.replay_runner import (
    LLMRequestBudget,
    ReplayCall,
    ReplayRunResult,
    case_content_sha256,
)
from momentum_research_agent.eval.session_cases import SessionEvalCase
from momentum_research_agent.models.schemas import (
    Evidence,
    EvidenceCategory,
    EvidenceStance,
    GapEntry,
    GapKind,
    MomentumCapability,
    ReplayHint,
    ResearchReport,
    ToolTrace,
)
from momentum_research_agent.state.policies import (
    PolicyPatch,
    PolicyStore,
    merge_policy_patch,
)


def _case(tmp_path: Path, case_name: str, observation: str) -> SessionEvalCase:
    trace = ToolTrace(
        id=f"trace-{case_name}",
        tool="web_search",
        arguments={"query": f"synthetic {case_name}"},
        observation=observation,
        observation_sha256=hashlib.sha256(observation.encode()).hexdigest(),
        agent_id=f"task-{case_name}",
        agent_role="flow_analyst",
        replay=ReplayHint(method="stored_observation", query=f"synthetic {case_name}"),
    )
    source_hash = ("a" if case_name == "target" else "b") * 64
    policy = PolicyStore(tmp_path).load_active()
    return SessionEvalCase(
        case_id=f"session:synthetic-{case_name}:{source_hash}:gap-{case_name}",
        source_session_id=f"synthetic-{case_name}",
        source_directory_sha256=source_hash,
        source_task_id=f"task-{case_name}",
        source_trace_ids=[trace.id],
        profile="flow_analyst",
        capability=MomentumCapability.SOURCE_QUALITY,
        task_title=f"Synthetic {case_name}",
        task_input=f"Use synthetic {case_name} evidence.",
        failing_evidence=GapEntry(
            id=f"gap-{case_name}",
            kind=GapKind.UNCHECKED_EVIDENCE,
            claim="Synthetic claim",
            task_id=f"task-{case_name}",
            trace_ids=[trace.id],
        ),
        tool_traces=[trace],
        source_artifact_hashes={"synthetic.json": "c" * 64},
        policy_version_id=policy.version_id,
        replayable=True,
    )


def _expectation(
    case: SessionEvalCase,
    *,
    kind: str,
    withhold: bool = False,
) -> BehavioralExpectation:
    evidence = []
    if not withhold:
        evidence = [
            ExpectedEvidence(
                source_url="https://example.test/filing",
                excerpt="Synthetic filing evidence.",
            )
        ]
    return BehavioralExpectation(
        case_id=case.case_id,
        case_sha256=case_content_sha256(case),
        kind=kind,
        reviewer="synthetic-test-reviewer",
        provenance="Locally authored synthetic fixture.",
        rationale="Checks replay grounding without asserting general research truth.",
        required_calls=[
            ExpectedToolCall(
                tool="web_search",
                arguments={"query": f"synthetic {kind}"},
            )
        ],
        allowed_report_statuses=[
            "insufficient_evidence" if withhold else "complete"
        ],
        required_evidence=evidence,
        require_no_findings=withhold,
    )


def _run(
    case: SessionEvalCase,
    policy_version_id: str,
    *,
    passed_shape: str,
    model: str | list[str] = "resolved-model",
) -> ReplayRunResult:
    observation = case.tool_traces[0].observation
    call = ReplayCall(
        tool="web_search",
        arguments=case.tool_traces[0].arguments,
        canonical_arguments=json.dumps(
            case.tool_traces[0].arguments,
            sort_keys=True,
            separators=(",", ":"),
        ),
        matched_trace_id=case.tool_traces[0].id,
        observation_sha256=case.tool_traces[0].observation_sha256,
        result=observation,
    )
    if passed_shape == "withhold":
        report = ResearchReport(
            task_id=case.source_task_id or "",
            title=case.task_title or "",
            agent_role=case.profile or "",
            summary="No supported claim.",
            status="insufficient_evidence",
            findings=[],
        )
    elif passed_shape == "grounded":
        report = ResearchReport(
            task_id=case.source_task_id or "",
            title=case.task_title or "",
            agent_role=case.profile or "",
            summary="Grounded.",
            status="complete",
            findings=[
                Evidence(
                    claim="The synthetic filing was observed.",
                    category=EvidenceCategory.OTHER,
                    stance=EvidenceStance.NEUTRAL,
                    source_url="https://example.test/filing",
                    source_name="web_search",
                    excerpt="Synthetic filing evidence.",
                )
            ],
        )
    else:
        report = ResearchReport(
            task_id=case.source_task_id or "",
            title=case.task_title or "",
            agent_role=case.profile or "",
            summary="Unsupported.",
            status="complete",
            findings=[
                Evidence(
                    claim="Unsupported synthetic claim.",
                    category=EvidenceCategory.OTHER,
                    stance=EvidenceStance.SUPPORTING,
                    source_url="https://invented.test",
                    excerpt="Not in the observation.",
                )
            ],
        )
    return ReplayRunResult(
        case_id=case.case_id,
        case_sha256=case_content_sha256(case),
        policy_version_id=policy_version_id,
        requested_model="requested",
        response_model_ids=[model] if isinstance(model, str) else model,
        max_output_tokens=128,
        completed=True,
        outcome="success",
        raw_output="{}",
        report=report,
        calls=[call],
        consumed_trace_ids=[case.tool_traces[0].id],
        llm_requests=1,
    )


def test_expectations_reject_vacuous_or_candidate_authored_assertions(tmp_path: Path) -> None:
    case = _case(tmp_path, "target", "No support in this synthetic observation.")
    common = {
        "case_id": case.case_id,
        "case_sha256": case_content_sha256(case),
        "kind": "target",
        "reviewer": "reviewer",
        "provenance": "manual curation",
        "rationale": "known unsupported case",
        "allowed_report_statuses": ["insufficient_evidence"],
        "require_no_findings": True,
    }

    with pytest.raises(ValidationError):
        BehavioralExpectation.model_validate(common)
    with pytest.raises(ValidationError):
        BehavioralExpectation.model_validate(
            {**common, "required_calls": [], "authored_by_policy": True}
        )


def test_explicit_input_loaders_validate_cases_expectations_and_policy(tmp_path: Path) -> None:
    case = _case(tmp_path, "target", "No support.")
    expectation_set = BehavioralExpectationSet(
        expectations=[_expectation(case, kind="target", withhold=True)]
    )
    cases_dir = tmp_path / "selected-cases"
    cases_dir.mkdir()
    (cases_dir / "case.json").write_text(case.model_dump_json(), encoding="utf-8")
    expectations_path = tmp_path / "expectations.json"
    expectations_path.write_text(expectation_set.model_dump_json(), encoding="utf-8")
    policy = PolicyStore(tmp_path).load_active()

    assert load_cases_reference(tmp_path, cases_dir) == [case]
    assert load_expectations(expectations_path) == expectation_set
    assert load_policy_reference(tmp_path, policy.version_id) == policy

    empty_dir = tmp_path / "empty-cases"
    empty_dir.mkdir()
    with pytest.raises(ValueError, match="no replay cases"):
        load_cases_reference(tmp_path, empty_dir)


def test_assessment_checks_exact_calls_withholding_and_consumed_provenance(
    tmp_path: Path,
) -> None:
    target = _case(tmp_path, "target", "No support in this synthetic observation.")
    guard = _case(
        tmp_path,
        "guard",
        json.dumps(
            {
                "url": "https://example.test/filing",
                "snippet": "Synthetic filing evidence.",
            }
        ),
    )
    baseline_id = target.policy_version_id or ""

    withheld = assess_replay_run(
        _run(target, baseline_id, passed_shape="withhold"),
        _expectation(target, kind="target", withhold=True),
    )
    grounded = assess_replay_run(
        _run(guard, baseline_id, passed_shape="grounded"),
        _expectation(guard, kind="guard"),
    )
    unsupported = assess_replay_run(
        _run(guard, baseline_id, passed_shape="unsupported"),
        _expectation(guard, kind="guard"),
    )

    assert withheld.passed is True
    assert grounded.passed is True
    assert unsupported.passed is False
    assert "finding_not_grounded_in_consumed_observation" in unsupported.violations
    assert "missing_required_evidence" in unsupported.violations


@pytest.mark.asyncio
async def test_shadow_comparison_persists_self_contained_paired_runs_and_aggregates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _case(tmp_path, "target", "No support in this synthetic observation.")
    guard = _case(
        tmp_path,
        "guard",
        '{"url":"https://example.test/filing","snippet":"Synthetic filing evidence."}',
    )
    store = PolicyStore(tmp_path)
    baseline = store.load_active()
    candidate = merge_policy_patch(
        baseline,
        PolicyPatch(prompt_overlays={"flow_analyst": "Withhold unsupported claims."}),
        trigger_ids=[target.case_id],
    )
    store.write_version(candidate)
    expectations = BehavioralExpectationSet(
        expectations=[
            _expectation(target, kind="target", withhold=True),
            _expectation(guard, kind="guard"),
            _expectation(
                _case(tmp_path, "extra", "No support in unused case."),
                kind="target",
                withhold=True,
            ),
        ]
    )

    async def fake_run_replay_case(**kwargs):
        case = kwargs["case"]
        policy = kwargs["policy"]
        kwargs["request_budget"].claim()
        if case.case_id == target.case_id:
            shape = "withhold" if policy.version_id == candidate.version_id else "unsupported"
        else:
            shape = "grounded"
        return _run(case, policy.version_id, passed_shape=shape)

    monkeypatch.setattr(
        "momentum_research_agent.eval.live_compare.run_replay_case",
        fake_run_replay_case,
    )

    report, report_path = await run_live_compare(
        client=object(),
        requested_model="requested",
        project_root=tmp_path,
        baseline_policy=baseline,
        candidate_policy=candidate,
        cases=[target, guard],
        expectations=expectations,
        repeats=2,
        max_cases=2,
        request_budget=LLMRequestBudget(max_attempts=8),
        max_output_tokens=128,
        budget=LoopBudget(max_turns=3),
    )

    assert report.outcome == "completed"
    assert report.observed_no_regression is True
    assert report.target_improvements == [target.case_id]
    assert all(item.complete for item in report.case_results)
    assert len(report.runs) == 8
    assert report.attempted_llm_calls == 8
    assert report.requested_model == "requested"
    assert report.baseline_policy.version_id == baseline.version_id
    assert report.candidate_policy.version_id == candidate.version_id
    assert {case.case_id for case in report.cases} == {target.case_id, guard.case_id}
    assert report.expectations.expectations == expectations.expectations[:2]
    assert report.expectations_sha256 == expectations_content_sha256(report.expectations)
    assert report_path.parent.parent.name == "live_evals"
    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    assert persisted["observed_no_regression"] is True
    assert persisted["target_improvements"] == [target.case_id]


@pytest.mark.asyncio
async def test_comparison_fails_closed_on_hash_mismatch_missing_guard_or_model_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _case(tmp_path, "target", "No support.")
    store = PolicyStore(tmp_path)
    baseline = store.load_active()
    candidate = merge_policy_patch(
        baseline,
        PolicyPatch(prompt_overlays={"flow_analyst": "Withhold."}),
        trigger_ids=[target.case_id],
    )
    expectation = _expectation(target, kind="target", withhold=True)

    with pytest.raises(ValueError, match="guard"):
        await run_live_compare(
            client=object(), requested_model="requested", project_root=tmp_path,
            baseline_policy=baseline, candidate_policy=candidate, cases=[target],
            expectations=BehavioralExpectationSet(expectations=[expectation]),
            repeats=1, max_cases=1, request_budget=LLMRequestBudget(max_attempts=2),
            max_output_tokens=64, budget=LoopBudget(max_turns=2),
        )

    bad = expectation.model_copy(update={"case_sha256": "0" * 64})
    with pytest.raises(ValueError, match="content hash"):
        BehavioralExpectationSet(expectations=[bad]).bind_cases([target])

    guard = _case(
        tmp_path,
        "guard",
        '{"url":"https://example.test/filing","snippet":"Synthetic filing evidence."}',
    )

    async def drifting_run(**kwargs):
        kwargs["request_budget"].claim()
        is_baseline = kwargs["policy"].version_id == baseline.version_id
        model = ["model-a", "model-b"] if is_baseline else ["model-b", "model-a"]
        shape = "withhold" if kwargs["case"].case_id == target.case_id else "grounded"
        return _run(kwargs["case"], kwargs["policy"].version_id, passed_shape=shape, model=model)

    monkeypatch.setattr(
        "momentum_research_agent.eval.live_compare.run_replay_case", drifting_run
    )
    report, _path = await run_live_compare(
        client=object(), requested_model="requested", project_root=tmp_path,
        baseline_policy=baseline, candidate_policy=candidate, cases=[target, guard],
        expectations=BehavioralExpectationSet(
            expectations=[expectation, _expectation(guard, kind="guard")]
        ),
        repeats=1, max_cases=2, request_budget=LLMRequestBudget(max_attempts=4),
        max_output_tokens=64, budget=LoopBudget(max_turns=2),
    )

    assert report.outcome == "failed"
    assert report.model_fairness is False
    assert report.observed_no_regression is False
    assert "resolved_model_mismatch" in report.reasons


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repeats", True),
        ("repeats", 1.5),
        ("max_cases", float("nan")),
        ("max_cases", float("inf")),
        ("max_output_tokens", 1.5),
    ],
)
@pytest.mark.asyncio
async def test_direct_comparison_rejects_non_integral_bounds_before_requests(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    target = _case(tmp_path, "target", "No support.")
    guard = _case(
        tmp_path,
        "guard",
        '{"url":"https://example.test/filing","snippet":"Synthetic filing evidence."}',
    )
    store = PolicyStore(tmp_path)
    baseline = store.load_active()
    candidate = merge_policy_patch(
        baseline,
        PolicyPatch(prompt_overlays={"flow_analyst": "Withhold."}),
        trigger_ids=[target.case_id],
    )
    values = {"repeats": 1, "max_cases": 2, "max_output_tokens": 64}
    values[field] = value
    request_budget = LLMRequestBudget(max_attempts=4)

    with pytest.raises(ValueError, match="positive integer"):
        await run_live_compare(
            client=object(),
            requested_model="requested",
            project_root=tmp_path,
            baseline_policy=baseline,
            candidate_policy=candidate,
            cases=[target, guard],
            expectations=BehavioralExpectationSet(
                expectations=[
                    _expectation(target, kind="target", withhold=True),
                    _expectation(guard, kind="guard"),
                ]
            ),
            request_budget=request_budget,
            budget=LoopBudget(max_turns=2),
            **values,
        )

    assert request_budget.attempts == 0
