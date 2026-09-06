from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from momentum_research_agent.coordinator.coordinator import Coordinator
from momentum_research_agent.coordinator.gap_seed import (
    append_gaps,
    classify_capability,
    gap_task_fields,
    load_rows,
)
from momentum_research_agent.models.schemas import (
    GapEntry,
    GapKind,
    GapLedgerStatus,
    MomentumCapability,
    TaskKind,
    VerificationReport,
)
from momentum_research_agent.state.reports import persist_verification_report
from momentum_research_agent.state.policies import PolicyPatch, PolicyStore, merge_policy_patch


def _coordinator(tmp_path: Path) -> Coordinator:
    session_dir = tmp_path / "session"
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace()))
    return Coordinator(
        session_dir=session_dir,
        client=client,  # type: ignore[arg-type]
        question="Is the NVDA selloff a crash?",
        project_root=tmp_path,
    )


def _engine_mock_report() -> VerificationReport:
    return VerificationReport(
        question="Is the NVDA selloff a crash?",
        overall_status="pass_with_caveats",
        summary="engine returned labeled mock",
        gaps=[
            GapEntry(
                kind=GapKind.ENGINE_MOCK,
                claim="engine_query(NVDA) returned labeled mock data.",
                notes="Replay uses the stored observation; no live snapshot was attached.",
                evidence_id="engine_mock:NVDA",
            )
        ],
    )


def test_classify_momentum_capabilities() -> None:
    mock = GapEntry(
        kind=GapKind.ENGINE_MOCK,
        claim="engine_query(NVDA) returned labeled mock data.",
        evidence_id="engine_mock:NVDA",
    )
    crowding = GapEntry(
        kind=GapKind.UNCHECKED_EVIDENCE,
        claim="FINRA short interest does not confirm crowding.",
        evidence_id="ev-crowd",
    )
    unwind = GapEntry(
        kind=GapKind.REJECTED_EVIDENCE,
        claim="Mechanical unwind / fragility is already a crash.",
        evidence_id="ev-unwind",
    )
    quality = GapEntry(
        kind=GapKind.MISSING_EVIDENCE,
        claim="Primary filing excerpt was not retrieved.",
        evidence_id="ev-source",
    )
    assert classify_capability(mock) is MomentumCapability.ENGINE_FRESHNESS
    assert classify_capability(crowding) is MomentumCapability.CROWDING
    assert classify_capability(unwind) is MomentumCapability.UNWIND_CRASH
    assert classify_capability(quality) is MomentumCapability.SOURCE_QUALITY


def test_gap_task_appends_active_capability_template(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path)
    candidate = merge_policy_patch(
        store.load_active(),
        PolicyPatch(
            task_templates={
                MomentumCapability.SOURCE_QUALITY: "Retrieve a primary filing before secondary commentary."
            }
        ),
        trigger_ids=["trajectory:source-quality"],
    )
    store.write_version(candidate)
    store.activate(candidate.version_id)
    from momentum_research_agent.models.schemas import GapLedgerRow

    row = GapLedgerRow(
        evidence_id="ev-source",
        capability=MomentumCapability.SOURCE_QUALITY,
        gap_kind=GapKind.MISSING_EVIDENCE,
        claim="Primary filing was not retrieved.",
    )

    _title, assignment, profile = gap_task_fields(row, candidate)

    assert "primary filing" in assignment
    assert profile == "technicals_analyst"


def test_seed_from_ledger_consumes_engine_mock(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    persist_verification_report(coordinator.session_dir, _engine_mock_report())

    planted = coordinator.seed_from_ledger()

    assert len(planted) == 1
    assert planted[0].kind is TaskKind.GAP
    assert planted[0].profile == "momentum_analyst"
    gap_tasks = [task for task in coordinator.board.tasks if task.kind is TaskKind.GAP]
    assert len(gap_tasks) == 1
    rows = load_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0].evidence_id == "engine_mock:NVDA"
    assert rows[0].capability is MomentumCapability.ENGINE_FRESHNESS
    assert rows[0].status is GapLedgerStatus.CONSUMED
    assert rows[0].consumed_session_id == coordinator.board.session_id
    assert rows[0].consumed_task_id == planted[0].id
    ledger_text = (tmp_path / "reports" / "gap_ledger.jsonl").read_text(encoding="utf-8")
    assert '"status":"CONSUMED"' in ledger_text


def test_append_gaps_is_idempotent_within_a_session(tmp_path: Path) -> None:
    gap = GapEntry(
        kind=GapKind.ENGINE_MOCK,
        claim="engine_query(NVDA) returned labeled mock data.",
        evidence_id="engine_mock:NVDA",
    )
    first = append_gaps(tmp_path, [gap], session_id="session-a")
    second = append_gaps(tmp_path, [gap], session_id="session-a")
    assert len(first) == 1
    assert second == []
    rows = load_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0].source_session_id == "session-a"
    assert rows[0].status is GapLedgerStatus.OPEN


def test_distinct_session_failure_preserves_occurrence_and_reopens_gap(tmp_path: Path) -> None:
    gap = GapEntry(
        kind=GapKind.REJECTED_EVIDENCE,
        claim="Crowding evidence remains unsupported.",
        evidence_id="ev-crowd",
    )
    first = append_gaps(tmp_path, [gap], session_id="session-a")[0]
    first.status = GapLedgerStatus.CLOSED
    from momentum_research_agent.coordinator.gap_seed import write_rows

    write_rows(tmp_path, [first])

    reopened = append_gaps(tmp_path, [gap], session_id="session-b")

    assert len(reopened) == 1
    rows = load_rows(tmp_path)
    assert len(rows) == 2
    assert rows[0].status is GapLedgerStatus.CLOSED
    assert rows[0].source_session_id == "session-a"
    assert rows[1].status is GapLedgerStatus.OPEN
    assert rows[1].source_session_id == "session-b"
    assert rows[0].evidence_id == rows[1].evidence_id == "ev-crowd"

    assert append_gaps(tmp_path, [gap], session_id="session-b") == []
    assert len(load_rows(tmp_path)) == 2


def test_seed_plants_at_most_two_and_skips_source_quality(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    append_gaps(
        tmp_path,
        [
            GapEntry(
                kind=GapKind.UNCHECKED_EVIDENCE,
                claim="FINRA SI crowding is still open.",
                evidence_id="ev-crowd",
            ),
            GapEntry(
                kind=GapKind.ENGINE_MOCK,
                claim="engine_query(NVDA) returned labeled mock data.",
                evidence_id="engine_mock:NVDA",
            ),
            GapEntry(
                kind=GapKind.REJECTED_EVIDENCE,
                claim="Unwind crash print was overstated.",
                evidence_id="ev-unwind",
            ),
            GapEntry(
                kind=GapKind.MISSING_EVIDENCE,
                claim="Primary filing excerpt was not retrieved.",
                evidence_id="ev-source",
            ),
        ],
        session_id="prior",
    )

    planted = coordinator.seed_from_ledger()

    assert len(planted) == 2
    by_profile = {task.profile: task for task in planted}
    assert set(by_profile) == {"flow_analyst", "momentum_analyst"}
    assert by_profile["flow_analyst"].kind is TaskKind.GAP
    rows = {row.evidence_id: row for row in load_rows(tmp_path)}
    assert rows["ev-crowd"].status is GapLedgerStatus.CONSUMED
    assert rows["ev-unwind"].status is GapLedgerStatus.CONSUMED
    assert rows["engine_mock:NVDA"].status is GapLedgerStatus.OPEN
    assert rows["ev-source"].status is GapLedgerStatus.OPEN
    assert rows["ev-source"].capability is MomentumCapability.SOURCE_QUALITY


def test_seed_from_ledger_is_noop_without_ledger(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    planted = coordinator.seed_from_ledger()
    assert planted == []
    assert coordinator.board.tasks == []
    assert not (tmp_path / "reports" / "gap_ledger.jsonl").exists()


def test_second_seed_does_not_replant(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    persist_verification_report(coordinator.session_dir, _engine_mock_report())
    first = coordinator.seed_from_ledger()
    second = coordinator.seed_from_ledger()
    assert len(first) == 1
    assert second == []
    assert sum(1 for task in coordinator.board.tasks if task.kind is TaskKind.GAP) == 1
    payload = json.loads((coordinator.session_dir / "task_board.json").read_text(encoding="utf-8"))
    assert payload["tasks"][0]["kind"] == "gap"
