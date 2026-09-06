from __future__ import annotations

import hashlib
import json
import shutil
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
from momentum_research_agent.state.policies import PolicyStore


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
    policy = PolicyStore(project_root).load_active()
    _write_json(session_dir / "policy_snapshot.json", {"version_id": policy.version_id})
    return session_dir, trace.id


def test_import_session_case_is_stable_pending_and_preserves_source_schema(tmp_path: Path) -> None:
    session_dir, trace_id = _write_session(tmp_path)

    first = import_session_cases(tmp_path, session_dir)
    second = import_session_cases(tmp_path, session_dir)

    assert first == second
    assert len(first) == 1
    case = first[0]
    assert isinstance(case, SessionEvalCase)
    source_fingerprint = hashlib.sha256(str(session_dir.resolve()).encode()).hexdigest()
    assert case.case_id == (
        f"session:20260905_120000_deadbeef:{source_fingerprint}:gap00001"
    )
    assert case.source_directory_sha256 == source_fingerprint
    assert case.curation_status == "pending"
    assert case.source_session_id == "20260905_120000_deadbeef"
    assert case.source_trace_ids == [trace_id]
    assert case.profile == "flow_analyst"
    assert case.capability.value == "crowding"
    assert case.task_input == "Check the May 29 NVDA crowding evidence with engine_query."
    assert case.failing_evidence.evidence_id == "ev-crowd"
    assert case.tool_traces[0].arguments == {"ticker": "NVDA", "end": "2026-05-29"}
    assert '"crowding_score": 96' in case.tool_traces[0].observation
    policy_version_id = PolicyStore(tmp_path).load_active().version_id
    assert case.policy_version_id == policy_version_id
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
        f"reports/policies/versions/{policy_version_id}.json",
    }
    assert set(case.source_artifact_hashes) == expected_sources
    for relative in expected_sources:
        source_path = (
            tmp_path / relative
            if relative.startswith("reports/policies/")
            else session_dir / relative
        )
        assert case.source_artifact_hashes[relative] == _sha256(source_path)

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


def test_schema_rejects_replay_trace_owned_by_another_task(tmp_path: Path) -> None:
    session_dir, _ = _write_session(tmp_path, session_id="schema-owner-guard")
    payload = import_session_cases(tmp_path, session_dir)[0].model_dump(mode="json")
    payload["tool_traces"][0]["agent_id"] = "another-task"

    with pytest.raises(ValidationError, match="source task"):
        SessionEvalCase.model_validate(payload)


def test_schema_binds_entire_case_identity_and_allows_colons_in_gap_id(
    tmp_path: Path,
) -> None:
    session_dir, _ = _write_session(tmp_path, session_id="identity-binding")
    payload = import_session_cases(tmp_path, session_dir)[0].model_dump(mode="json")
    source_hash = payload["source_directory_sha256"]

    mismatched_session = dict(payload)
    mismatched_session["case_id"] = (
        f"session:other-session:{source_hash}:{payload['failing_evidence']['id']}"
    )
    with pytest.raises(ValidationError, match="case_id"):
        SessionEvalCase.model_validate(mismatched_session)

    colon_gap = json.loads(json.dumps(payload))
    colon_gap["failing_evidence"]["id"] = "gap:with:colons"
    colon_gap["case_id"] = (
        f"session:{colon_gap['source_session_id']}:{source_hash}:gap:with:colons"
    )

    case = SessionEvalCase.model_validate(colon_gap)

    assert case.failing_evidence.id == "gap:with:colons"
    assert case.case_id == colon_gap["case_id"]


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


def test_verifier_trace_provenance_is_preserved_but_not_replayed(tmp_path: Path) -> None:
    session_dir, task_trace_id = _write_session(tmp_path, session_id="verifier-mixture")
    verifier_trace = record_trace(
        "web_search",
        {"query": "independent verification"},
        "stored verifier observation",
        agent_role="verifier",
    )
    assert verifier_trace is not None
    with (session_dir / "traces.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(verifier_trace.model_dump_json() + "\n")
    verification_path = session_dir / "verification.json"
    payload = json.loads(verification_path.read_text(encoding="utf-8"))
    payload["traces"].append(verifier_trace.model_dump(mode="json"))
    payload["gaps"][0]["trace_ids"].append(verifier_trace.id)
    _write_json(verification_path, payload)

    case = import_session_cases(tmp_path, session_dir)[0]

    assert case.replayable is True
    assert case.failing_evidence.trace_ids == [task_trace_id, verifier_trace.id]
    assert case.source_trace_ids == [task_trace_id]
    assert [trace.id for trace in case.tool_traces] == [task_trace_id]


def test_omitted_task_owned_trace_makes_case_non_replayable(tmp_path: Path) -> None:
    session_dir, _ = _write_session(tmp_path, session_id="omitted-task-trace")
    omitted = record_trace(
        "web_search",
        {"query": "omitted task observation"},
        "stored task observation",
        agent_id="task0001",
        agent_role="flow_analyst",
    )
    assert omitted is not None
    with (session_dir / "traces.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(omitted.model_dump_json() + "\n")
    verification_path = session_dir / "verification.json"
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    verification["traces"].append(omitted.model_dump(mode="json"))
    _write_json(verification_path, verification)
    board_path = session_dir / "task_board.json"
    board = json.loads(board_path.read_text(encoding="utf-8"))
    board["tasks"][0]["tool_calls"] = 2
    _write_json(board_path, board)

    case = import_session_cases(tmp_path, session_dir)[0]

    assert case.replayable is False
    assert any("task-owned trace is not referenced" in item for item in case.replay_blockers)


def test_foreign_research_task_trace_is_rejected_and_not_replayed(tmp_path: Path) -> None:
    session_dir, task_trace_id = _write_session(tmp_path, session_id="foreign-task-trace")
    foreign = record_trace(
        "web_search",
        {"query": "foreign task observation"},
        "stored foreign observation",
        agent_id="task0002",
        agent_role="momentum_analyst",
    )
    assert foreign is not None
    with (session_dir / "traces.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(foreign.model_dump_json() + "\n")
    verification_path = session_dir / "verification.json"
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    verification["traces"].append(foreign.model_dump(mode="json"))
    verification["gaps"][0]["trace_ids"].append(foreign.id)
    _write_json(verification_path, verification)

    case = import_session_cases(tmp_path, session_dir)[0]

    assert case.replayable is False
    assert any("foreign research-task trace" in item for item in case.replay_blockers)
    assert case.source_trace_ids == [task_trace_id]
    assert [trace.id for trace in case.tool_traces] == [task_trace_id]


def test_duplicate_gap_trace_reference_is_rejected(tmp_path: Path) -> None:
    session_dir, trace_id = _write_session(tmp_path, session_id="duplicate-gap-trace")
    verification_path = session_dir / "verification.json"
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    verification["gaps"][0]["trace_ids"].append(trace_id)
    _write_json(verification_path, verification)

    case = import_session_cases(tmp_path, session_dir)[0]

    assert case.replayable is False
    assert any("duplicate trace reference" in item for item in case.replay_blockers)


@pytest.mark.parametrize("mode", ["missing", "tampered"])
def test_missing_or_tampered_policy_version_is_not_replayable(
    tmp_path: Path,
    mode: str,
) -> None:
    session_dir, _ = _write_session(tmp_path, session_id=f"policy-{mode}")
    store = PolicyStore(tmp_path)
    version_id = json.loads(
        (session_dir / "policy_snapshot.json").read_text(encoding="utf-8")
    )["version_id"]
    version_path = store.version_path(version_id)
    if mode == "missing":
        version_path.unlink()
    else:
        payload = json.loads(version_path.read_text(encoding="utf-8"))
        payload["prompt_overlays"] = {"flow_analyst": "tampered"}
        _write_json(version_path, payload)

    case = import_session_cases(tmp_path, session_dir)[0]

    assert case.replayable is False
    assert case.policy_version_id == version_id
    assert any("policy version" in item for item in case.replay_blockers)


def test_policy_validation_does_not_recreate_active_pointer(tmp_path: Path) -> None:
    session_dir, _ = _write_session(tmp_path, session_id="policy-read-only")
    active_path = PolicyStore(tmp_path).active_path
    active_path.unlink()

    case = import_session_cases(tmp_path, session_dir)[0]

    assert case.replayable is True
    assert not active_path.exists()


def test_duplicate_gap_ids_are_rejected_before_any_case_write(tmp_path: Path) -> None:
    session_dir, _ = _write_session(tmp_path, session_id="duplicate-gaps")
    verification_path = session_dir / "verification.json"
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    verification["gaps"].append(dict(verification["gaps"][0]))
    _write_json(verification_path, verification)

    with pytest.raises(ValueError, match="duplicate gap ids"):
        import_session_cases(tmp_path, session_dir)

    assert not (tmp_path / "reports" / "eval_cases").exists()


def test_same_session_id_in_different_directories_does_not_overwrite(
    tmp_path: Path,
) -> None:
    first_dir, _ = _write_session(tmp_path, session_id="shared-board-id")
    second_dir = tmp_path / "import-source" / "custom-session-directory"
    shutil.copytree(first_dir, second_dir)

    first = import_session_cases(tmp_path, first_dir)
    second = import_session_cases(tmp_path, second_dir)
    loaded = load_session_eval_cases(tmp_path)

    assert len(first) == len(second) == 1
    assert first[0].source_session_id == second[0].source_session_id == "shared-board-id"
    assert first[0].source_directory_sha256 != second[0].source_directory_sha256
    assert first[0].case_id != second[0].case_id
    assert len(loaded) == 2
    assert {case.case_id for case in loaded} == {first[0].case_id, second[0].case_id}


def test_import_return_order_matches_loaded_case_order(tmp_path: Path) -> None:
    session_dir, _ = _write_session(tmp_path, session_id="return-load-parity")
    verification_path = session_dir / "verification.json"
    verification = json.loads(verification_path.read_text(encoding="utf-8"))
    second_gap = dict(verification["gaps"][0])
    second_gap["id"] = "aaa-first-when-sorted"
    verification["gaps"].append(second_gap)
    _write_json(verification_path, verification)

    imported = import_session_cases(tmp_path, session_dir)

    assert imported == load_session_eval_cases(tmp_path)
