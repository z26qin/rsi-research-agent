from __future__ import annotations

from pathlib import Path

from momentum_research_agent.coordinator.gap_seed import (
    append_gaps,
    load_rows,
)
from momentum_research_agent.models.schemas import (
    GapEntry,
    GapKind,
    GapLedgerStatus,
)


def test_distinct_session_failure_preserves_occurrence_and_reopens_gap(
    tmp_path: Path,
) -> None:
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
