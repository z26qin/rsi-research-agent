"""Cross-session gap ledger: append after verify, plant kind=gap before dispatch,
then write CONSUMED rows to CLOSED or back to OPEN from this session's verdicts.

This is not a second follow-up round and not AgentBus. Follow-up stays one
in-session pass (max 2). Gap seed reads prior OPEN rows from
`reports/gap_ledger.jsonl` and plants at most two TaskBoard tasks.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from momentum_research_agent.config import reports_root
from momentum_research_agent.coordinator.task_board import TaskBoard
from momentum_research_agent.models.schemas import (
    GapEntry,
    GapKind,
    GapLedgerRow,
    GapLedgerStatus,
    MomentumCapability,
    Task,
    TaskKind,
    TaskStatus,
    VerificationReport,
    VerificationStatus,
)
from momentum_research_agent.state.reports import load_verification_report
from momentum_research_agent.state.policies import PolicyStore, ResearchPolicy, task_template_addition

MAX_GAP_SEED_TASKS = 2

CAPABILITY_PROFILE: dict[MomentumCapability, str] = {
    MomentumCapability.CROWDING: "flow_analyst",
    MomentumCapability.UNWIND_CRASH: "momentum_analyst",
    MomentumCapability.ENGINE_FRESHNESS: "momentum_analyst",
    MomentumCapability.SOURCE_QUALITY: "technicals_analyst",
}

_PLANT_ORDER = (
    MomentumCapability.CROWDING,
    MomentumCapability.UNWIND_CRASH,
    MomentumCapability.ENGINE_FRESHNESS,
    MomentumCapability.SOURCE_QUALITY,
)

_CROWDING_HITS = (
    "crowd",
    "positioning",
    "finra",
    "short interest",
    "days-to-cover",
    "si print",
)
_UNWIND_HITS = (
    "unwind",
    "crash",
    "fragility",
    "panic_elevated",
    "bear_low",
    "mechanical",
)
_ENGINE_HITS = ("mock", "stale", "snapshot", "as_of", "freshness")

_LOCK = threading.RLock()


def ledger_path(project_root: Path) -> Path:
    return reports_root(project_root) / "gap_ledger.jsonl"


def is_gap_task(task: Task) -> bool:
    return task.kind is TaskKind.GAP


def already_gap_seeded(tasks: list[Task]) -> bool:
    return any(is_gap_task(task) for task in tasks)


def classify_capability(gap: GapEntry) -> MomentumCapability:
    if gap.kind is GapKind.ENGINE_MOCK:
        return MomentumCapability.ENGINE_FRESHNESS
    text = f"{gap.claim} {gap.notes} {gap.kind.value}".lower()
    if any(hit in text for hit in _CROWDING_HITS):
        return MomentumCapability.CROWDING
    if any(hit in text for hit in _UNWIND_HITS):
        return MomentumCapability.UNWIND_CRASH
    if any(hit in text for hit in _ENGINE_HITS):
        return MomentumCapability.ENGINE_FRESHNESS
    return MomentumCapability.SOURCE_QUALITY


def evidence_key(gap: GapEntry) -> str:
    return gap.evidence_id or gap.id


def load_rows(project_root: Path) -> list[GapLedgerRow]:
    path = ledger_path(project_root)
    if not path.exists():
        return []
    loaded: list[GapLedgerRow] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        loaded.append(GapLedgerRow.model_validate(json.loads(line)))
    return loaded


def write_rows(project_root: Path, rows: list[GapLedgerRow]) -> Path:
    path = ledger_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(row.model_dump_json() + "\n")
    tmp.replace(path)
    return path


def append_gaps(
    project_root: Path,
    gaps: list[GapEntry],
    *,
    session_id: str,
) -> list[GapLedgerRow]:
    """Append new gaps. Duplicate `evidence_id` (any status) is skipped."""
    if not gaps:
        return []
    with _LOCK:
        rows = load_rows(project_root)
        known = {row.evidence_id for row in rows}
        added: list[GapLedgerRow] = []
        for gap in gaps:
            key = evidence_key(gap)
            if key in known:
                continue
            row = GapLedgerRow(
                evidence_id=key,
                capability=classify_capability(gap),
                gap_kind=gap.kind,
                claim=gap.claim,
                notes=gap.notes,
                source_session_id=session_id,
            )
            rows.append(row)
            known.add(key)
            added.append(row)
        if added:
            write_rows(project_root, rows)
        return added


def select_open_rows(rows: list[GapLedgerRow]) -> list[GapLedgerRow]:
    """At most one crowding (flow) and one unwind/engine (momentum). Max 2."""
    open_rows = [
        row
        for row in rows
        if row.status is GapLedgerStatus.OPEN and row.capability in CAPABILITY_PROFILE
    ]
    chosen: list[GapLedgerRow] = []
    used_profiles: set[str] = set()
    for capability in _PLANT_ORDER:
        profile = CAPABILITY_PROFILE[capability]
        if profile in used_profiles:
            continue
        match = next((row for row in open_rows if row.capability is capability), None)
        if match is None:
            continue
        chosen.append(match)
        used_profiles.add(profile)
        if len(chosen) >= MAX_GAP_SEED_TASKS:
            break
    return chosen


def gap_task_fields(row: GapLedgerRow, policy: ResearchPolicy) -> tuple[str, str, str]:
    profile = CAPABILITY_PROFILE[row.capability]
    title = f"Gap: {row.capability.value}"
    assignment = (
        f"Close a prior-session {row.capability.value} gap "
        f"(evidence_id={row.evidence_id}).\n"
        f"Claim: {row.claim}\n"
        f"Notes: {row.notes or '(none)'}\n"
        "This is a planted gap-ledger task, not an in-session follow-up. "
        "Use allowlisted tools and return Evidence[]."
    )
    addition = task_template_addition(policy, row.capability)
    if addition:
        assignment = f"{assignment}\n\nPolicy guidance: {addition}"
    return title, assignment, profile


def record_session_gaps(
    project_root: Path,
    session_dir: Path,
    session_id: str,
    report_gaps: list[GapEntry] | None = None,
) -> list[GapLedgerRow]:
    gaps = report_gaps
    if gaps is None:
        report = load_verification_report(session_dir)
        gaps = report.gaps if report is not None else []
    return append_gaps(project_root, gaps, session_id=session_id)


def seed_open_gaps(
    board: TaskBoard,
    project_root: Path,
    policy: ResearchPolicy | None = None,
) -> list[Task]:
    """Plant at most 2 kind=gap tasks from OPEN rows; mark those rows CONSUMED."""
    if already_gap_seeded(board.tasks):
        return []
    with _LOCK:
        selected_policy = policy or PolicyStore(project_root).load_active()
        rows = load_rows(project_root)
        chosen = select_open_rows(rows)
        if not chosen:
            return []
        planted: list[Task] = []
        for row in chosen:
            title, assignment, profile = gap_task_fields(row, selected_policy)
            task = board.add_task(title, assignment, profile, kind=TaskKind.GAP)
            row.status = GapLedgerStatus.CONSUMED
            row.consumed_session_id = board.session_id
            row.consumed_task_id = task.id
            planted.append(task)
        write_rows(project_root, rows)
        return planted


_STILL_OPEN_GAP_KINDS = frozenset(
    {GapKind.ENGINE_MOCK, GapKind.REJECTED_EVIDENCE, GapKind.UNCHECKED_EVIDENCE}
)
_STILL_OPEN_VERDICTS = frozenset(
    {VerificationStatus.REJECTED, VerificationStatus.UNCHECKED}
)
_CLOSED_VERDICTS = frozenset(
    {VerificationStatus.VERIFIED, VerificationStatus.WEAK}
)


def planted_gap_still_open(
    row: GapLedgerRow,
    verification: VerificationReport,
    tasks: list[Task],
) -> bool:
    """True when this session did not actually close the planted gap."""
    task = next((item for item in tasks if item.id == row.consumed_task_id), None)
    if task is None or task.status is not TaskStatus.COMPLETED:
        return True
    related_gaps = [
        gap
        for gap in verification.gaps
        if gap.task_id == row.consumed_task_id or gap.evidence_id == row.evidence_id
    ]
    if any(gap.kind in _STILL_OPEN_GAP_KINDS for gap in related_gaps):
        return True
    related_verdicts = [
        verdict
        for verdict in verification.verdicts
        if verdict.task_id == row.consumed_task_id
    ]
    if any(verdict.status in _STILL_OPEN_VERDICTS for verdict in related_verdicts):
        return True
    if row.capability is MomentumCapability.ENGINE_FRESHNESS:
        return False
    if not related_verdicts:
        return True
    return not any(verdict.status in _CLOSED_VERDICTS for verdict in related_verdicts)


def resolve_consumed_gaps(
    project_root: Path,
    board: TaskBoard,
    verification: VerificationReport,
) -> list[GapLedgerRow]:
    """Write this session's planted rows to CLOSED or back to OPEN.

    CONSUMED means we asked; CLOSED means the gap is actually gone. Follow-up
    is unchanged. Rows planted by other sessions are left alone.
    """
    tasks = board.tasks
    with _LOCK:
        rows = load_rows(project_root)
        changed: list[GapLedgerRow] = []
        for row in rows:
            if row.consumed_session_id != board.session_id:
                continue
            still_open = planted_gap_still_open(row, verification, tasks)
            target = GapLedgerStatus.OPEN if still_open else GapLedgerStatus.CLOSED
            if row.status is target:
                continue
            row.status = target
            changed.append(row)
        if changed:
            write_rows(project_root, rows)
        return changed
