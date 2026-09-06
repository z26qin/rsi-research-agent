from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from momentum_research_agent.agents.ledger import record_trace
from momentum_research_agent.eval.session_cases import (
    SessionEvalCase,
    import_session_cases,
    load_session_eval_cases,
)
from momentum_research_agent.models.schemas import (
    Evidence,
    EvidenceCategory,
    EvidenceStance,
    GapEntry,
    GapKind,
    ResearchReport,
    Task,
    TaskStatus,
    VerificationReport,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_session(
    project_root: Path,
    *,
    session_id: str = "20260905_120000_deadbeef",
    trace_hash: str | None = None,
    truncated: bool = False,
    tool_calls: int = 1,
    evidence_source: str = "engine_query",
) -> tuple[Path, str]:
    session_dir = project_root / "reports" / session_id
    session_dir.mkdir(parents=True)
    task = Task(
        id="task0001",
        title="Check crowding",
        assignment="Check the May 29 NVDA crowding evidence with engine_query.",
        profile="flow_analyst",
        status=TaskStatus.COMPLETED,
        tool_calls=tool_calls,
    )
    _write_json(
        session_dir / "task_board.json",
        {
            "session_id": session_id,
            "question": "Is the NVDA selloff a momentum crash?",
            "tasks": [task.model_dump(mode="json")],
        },
    )
    report = ResearchReport(
        task_id=task.id,
        title=task.title,
        agent_role=task.profile,
        findings=[
            Evidence(
                id="ev-crowd",
                claim="Crowding was elevated.",
                category=EvidenceCategory.CROWDED_POSITIONING,
                stance=EvidenceStance.SUPPORTING,
                source_name=evidence_source,
                excerpt="crowding_score=96",
                agent_id=task.id,
            )
        ],
        summary="The claim was not independently verified.",
        status="partial",
    )
    report_path = session_dir / "sub_reports" / f"{task.id}_{task.profile}.json"
    _write_json(report_path, report.model_dump(mode="json"))
    trace = record_trace(
        "engine_query",
        {"ticker": "NVDA", "end": "2026-05-29"},
        json.dumps(
            {
                "ticker": "NVDA",
                "source": "mock",
                "as_of": "2026-05-29",
                "crowding_score": 96,
            }
        ),
        agent_id=task.id,
        agent_role=task.profile,
    )
    assert trace is not None
    trace = trace.model_copy(
        update={
            "observation_sha256": trace_hash or trace.observation_sha256,
            "truncated": truncated,
        }
    )
    traces_path = session_dir / "traces.jsonl"
    traces_path.write_text(trace.model_dump_json() + "\n", encoding="utf-8")
    gap = GapEntry(
        id="gap00001",
        kind=GapKind.UNCHECKED_EVIDENCE,
        claim="Crowding was elevated.",
        notes="Verifier could not independently confirm the observation.",
        evidence_id="ev-crowd",
        task_id=task.id,
        trace_ids=[trace.id],
    )
    verification = VerificationReport(
        question="Is the NVDA selloff a momentum crash?",
        overall_status="pass_with_caveats",
        summary="One unchecked claim.",
        gaps=[gap],
        traces=[trace],
    )
    _write_json(session_dir / "verification.json", verification.model_dump(mode="json"))
    _write_json(session_dir / "policy_snapshot.json", {"version_id": "0123456789ab"})
    return session_dir, trace.id


def test_import_session_case_is_stable_pending_and_preserves_source_schema(tmp_path: Path) -> None:
    session_dir, trace_id = _write_session(tmp_path)

    first = import_session_cases(tmp_path, session_dir)
    second = import_session_cases(tmp_path, session_dir)

    assert first == second
    assert len(first) == 1
    case = first[0]
    assert isinstance(case, SessionEvalCase)
    assert case.case_id == "session:20260905_120000_deadbeef:gap00001"
    assert case.curation_status == "pending"
    assert case.source_session_id == "20260905_120000_deadbeef"
    assert case.source_trace_ids == [trace_id]
    assert case.profile == "flow_analyst"
    assert case.capability.value == "crowding"
    assert case.task_input == "Check the May 29 NVDA crowding evidence with engine_query."
    assert case.failing_evidence.evidence_id == "ev-crowd"
    assert case.tool_traces[0].arguments == {"ticker": "NVDA", "end": "2026-05-29"}
    assert '"crowding_score": 96' in case.tool_traces[0].observation
    assert case.policy_version_id == "0123456789ab"
    assert case.replayable is True
    assert case.replay_blockers == []

    case_files = list((tmp_path / "reports" / "eval_cases").glob("*.json"))
    assert len(case_files) == 1
    payload = json.loads(case_files[0].read_text(encoding="utf-8"))
    assert "ground_truth" not in payload
    expected_sources = {
        "verification.json",
        "traces.jsonl",
        "task_board.json",
        "policy_snapshot.json",
        "sub_reports/task0001_flow_analyst.json",
    }
    assert set(case.source_artifact_hashes) == expected_sources
    for relative in expected_sources:
        assert case.source_artifact_hashes[relative] == _sha256(session_dir / relative)

    assert load_session_eval_cases(tmp_path) == first


def test_hash_mismatched_and_truncated_traces_are_not_replayable(tmp_path: Path) -> None:
    mismatched, _ = _write_session(
        tmp_path,
        session_id="hash-mismatch",
        trace_hash="0" * 64,
    )
    truncated, _ = _write_session(
        tmp_path,
        session_id="truncated",
        truncated=True,
    )

    mismatch_case = import_session_cases(tmp_path, mismatched)[0]
    truncated_case = import_session_cases(tmp_path, truncated)[0]

    assert mismatch_case.replayable is False
    assert any("observation hash mismatch" in item for item in mismatch_case.replay_blockers)
    assert truncated_case.replayable is False
    assert any("truncated observation" in item for item in truncated_case.replay_blockers)


def test_missing_trace_and_unsupported_tool_dependency_fail_closed(tmp_path: Path) -> None:
    session_dir, _trace_id = _write_session(
        tmp_path,
        session_id="unsupported-tool",
        tool_calls=2,
        evidence_source="market_data",
    )
    verification_path = session_dir / "verification.json"
    payload = json.loads(verification_path.read_text(encoding="utf-8"))
    payload["gaps"][0]["trace_ids"].append("missing-trace")
    _write_json(verification_path, payload)

    case = import_session_cases(tmp_path, session_dir)[0]

    assert case.replayable is False
    assert any("missing trace reference" in item for item in case.replay_blockers)
    assert any("unsupported tool dependency market_data" in item for item in case.replay_blockers)
    assert any("tool-call count differs" in item for item in case.replay_blockers)


def test_incomplete_session_imports_pending_case_but_never_marks_it_replayable(
    tmp_path: Path,
) -> None:
    session_dir, _ = _write_session(tmp_path, session_id="incomplete")
    (session_dir / "policy_snapshot.json").unlink()
    for path in (session_dir / "sub_reports").glob("*.json"):
        path.unlink()

    case = import_session_cases(tmp_path, session_dir)[0]

    assert case.curation_status == "pending"
    assert case.replayable is False
    assert case.policy_version_id is None
    assert any("missing policy_snapshot.json" in item for item in case.replay_blockers)
    assert any("missing sub-report" in item for item in case.replay_blockers)


def test_schema_rejects_replayable_claim_for_truncated_trace(tmp_path: Path) -> None:
    session_dir, _ = _write_session(tmp_path, session_id="schema-guard")
    payload = import_session_cases(tmp_path, session_dir)[0].model_dump(mode="json")
    payload["tool_traces"][0]["truncated"] = True

    with pytest.raises(ValidationError, match="truncated trace"):
        SessionEvalCase.model_validate(payload)


def test_import_without_verification_fails_clearly(tmp_path: Path) -> None:
    session_dir = tmp_path / "reports" / "empty-session"
    session_dir.mkdir(parents=True)

    with pytest.raises(FileNotFoundError, match="missing verification.json"):
        import_session_cases(tmp_path, session_dir)


def test_import_errors_do_not_echo_arbitrary_source_content(tmp_path: Path) -> None:
    session_dir, _ = _write_session(tmp_path, session_id="safe-errors")
    secret = "sk-do-not-repeat-this-value"
    _write_json(
        session_dir / "task_board.json",
        {
            "session_id": "safe-errors",
            "tasks": [{"status": secret}],
        },
    )
    (session_dir / "traces.jsonl").write_text(
        json.dumps({"api_key": secret}) + "\n",
        encoding="utf-8",
    )
    report_path = next((session_dir / "sub_reports").glob("*.json"))
    _write_json(report_path, {"api_key": secret})
    _write_json(session_dir / "policy_snapshot.json", {"version_id": secret})

    case = import_session_cases(tmp_path, session_dir)[0]

    assert case.replayable is False
    assert secret not in " ".join(case.replay_blockers)


def test_inconsistent_task_tool_count_is_not_replayable(tmp_path: Path) -> None:
    session_dir, _ = _write_session(
        tmp_path,
        session_id="inconsistent-tool-count",
        tool_calls=0,
    )

    case = import_session_cases(tmp_path, session_dir)[0]

    assert case.replayable is False
    assert any("tool-call count differs" in item for item in case.replay_blockers)
