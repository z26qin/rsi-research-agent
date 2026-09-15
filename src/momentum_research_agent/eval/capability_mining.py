"""Deterministically mine bounded capability cases from production failures.

Cases are immutable observations.  They can point only at separately approved
frozen worlds and never mutate the gap ledger or active research policy.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from momentum_research_agent.coordinator.gap_seed import load_rows
from momentum_research_agent.models.schemas import (
    GapEntry,
    GapKind,
    GapLedgerRow,
    GapLedgerStatus,
    MomentumCapability,
    ResearchReport,
    ToolTrace,
    VerificationReport,
)

MAX_MINED_CASES = 8
MAX_TARGET_WORLDS = 2


class Capability(str, Enum):
    SOURCE_DISCOVERY = "SOURCE_DISCOVERY"
    SOURCE_QUALITY = "SOURCE_QUALITY"
    CONTRADICTION_SEARCH = "CONTRADICTION_SEARCH"
    ENGINE_GROUNDING = "ENGINE_GROUNDING"
    CLAIM_WITHHOLDING = "CLAIM_WITHHOLDING"
    AS_OF_DISCIPLINE = "AS_OF_DISCIPLINE"
    CROWDING_CONFIRMATION = "CROWDING_CONFIRMATION"
    REPLAN_FAILURE = "REPLAN_FAILURE"


_POLICY_CAPABILITY: dict[Capability, MomentumCapability] = {
    Capability.SOURCE_DISCOVERY: MomentumCapability.SOURCE_QUALITY,
    Capability.SOURCE_QUALITY: MomentumCapability.SOURCE_QUALITY,
    Capability.CONTRADICTION_SEARCH: MomentumCapability.SOURCE_QUALITY,
    Capability.ENGINE_GROUNDING: MomentumCapability.ENGINE_FRESHNESS,
    Capability.CLAIM_WITHHOLDING: MomentumCapability.UNWIND_CRASH,
    Capability.AS_OF_DISCIPLINE: MomentumCapability.ENGINE_FRESHNESS,
    Capability.CROWDING_CONFIRMATION: MomentumCapability.CROWDING,
    Capability.REPLAN_FAILURE: MomentumCapability.UNWIND_CRASH,
}


class MinedCapabilityCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_kind: Literal["mined_capability_case_v1"] = "mined_capability_case_v1"
    case_id: str = Field(min_length=1)
    source_session_id: str = Field(min_length=1)
    triggering_gap_ids: list[str] = Field(min_length=1, max_length=MAX_MINED_CASES)
    source_evidence_ids: list[str] = Field(min_length=1, max_length=MAX_MINED_CASES)
    capabilities: list[Capability] = Field(min_length=1, max_length=len(Capability))
    policy_capability: MomentumCapability
    approved_world_ids: list[str] = Field(default_factory=list)
    approved_world_hashes: dict[str, str] = Field(default_factory=dict)
    status: Literal["mapped", "pending_world_candidate"]
    source_artifact_hashes: dict[str, str] = Field(default_factory=dict)
    source_artifact_references: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_mapping(self) -> MinedCapabilityCase:
        if len(self.triggering_gap_ids) != len(set(self.triggering_gap_ids)):
            raise ValueError("triggering_gap_ids must be unique")
        if len(self.source_evidence_ids) != len(set(self.source_evidence_ids)):
            raise ValueError("source_evidence_ids must be unique")
        if len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("capabilities must be unique")
        if len(self.approved_world_ids) != len(set(self.approved_world_ids)):
            raise ValueError("approved_world_ids must be unique")
        if self.status == "mapped" and not self.approved_world_ids:
            raise ValueError("mapped cases require an approved world")
        if self.status == "pending_world_candidate" and self.approved_world_ids:
            raise ValueError("pending cases cannot reference an approved world")
        if set(self.approved_world_hashes) != set(self.approved_world_ids):
            raise ValueError("approved world hashes must bind every approved world id")
        if set(self.source_artifact_hashes) != set(self.source_artifact_references):
            raise ValueError(
                "artifact hashes and references must describe the same files"
            )
        if any(len(value) != 64 for value in self.source_artifact_hashes.values()):
            raise ValueError("source artifact hashes must be SHA-256 digests")
        return self


@runtime_checkable
class ResearchWorld(Protocol):
    world_id: str
    capability: MomentumCapability
    capabilities: list[str]
    guard: bool
    content_hash: str


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _source_artifacts(session_dir: Path) -> tuple[list[str], dict[str, str]]:
    paths = [
        session_dir / "verification.json",
        session_dir / "task_board.json",
        session_dir / "traces.jsonl",
    ]
    paths.extend(sorted((session_dir / "sub_reports").glob("*.json")))
    references: list[str] = []
    hashes: dict[str, str] = {}
    for path in paths:
        if not path.is_file():
            continue
        relative = path.relative_to(session_dir).as_posix()
        references.append(relative)
        hashes[relative] = _sha256_bytes(path.read_bytes())
    return references, hashes


def _case_id(session_id: str, gap_ids: list[str]) -> str:
    identity = json.dumps(
        {"source_session_id": session_id, "triggering_gap_ids": gap_ids},
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        f"capability:{session_id}:{hashlib.sha256(identity.encode()).hexdigest()[:16]}"
    )


def _occurrence_id(session_id: str, gap_id: str) -> str:
    return f"gap:{session_id}:{gap_id}"


def _load_worlds(worlds: list[ResearchWorld] | None) -> list[ResearchWorld]:
    if worlds is not None:
        return list(worlds)
    # Lazy import prevents the fixture layer from becoming a production-runtime
    # dependency and avoids a capability-mining/research-world import cycle.
    from momentum_research_agent.eval.research_world import load_approved_worlds

    return list(load_approved_worlds())


def _valid_worlds(worlds: list[ResearchWorld]) -> list[ResearchWorld]:
    valid: list[ResearchWorld] = []
    seen: set[str] = set()
    for world in worlds:
        if not isinstance(world.world_id, str) or not world.world_id:
            raise ValueError("approved world has an invalid world_id")
        if world.world_id in seen:
            raise ValueError("approved world ids must be unique")
        if not isinstance(world.content_hash, str) or len(world.content_hash) != 64:
            raise ValueError(
                f"approved world {world.world_id} has an invalid content hash"
            )
        seen.add(world.world_id)
        valid.append(world)
    return valid


def _task_is_failed_replan(gap: GapEntry, board: dict[str, Any]) -> bool:
    if not gap.task_id:
        return False
    for task in board.get("tasks", []):
        if not isinstance(task, dict) or task.get("id") != gap.task_id:
            continue
        return task.get("kind") == "replan" and task.get("status") != "completed"
    return False


def _bound_context(session_dir: Path, gap: GapEntry, board: dict[str, Any]) -> str:
    parts = [gap.claim, gap.notes]
    for task in board.get("tasks", []):
        if isinstance(task, dict) and gap.task_id and task.get("id") == gap.task_id:
            parts.extend(
                str(task.get(key) or "")
                for key in (
                    "title",
                    "assignment",
                    "kind",
                    "status",
                    "error",
                    "error_type",
                )
            )
    for path in sorted((session_dir / "sub_reports").glob("*.json")):
        try:
            report = ResearchReport.model_validate(_read_json(path))
        except (OSError, ValueError, TypeError):
            continue
        bound_findings = [
            evidence
            for evidence in report.findings
            if evidence.id == gap.evidence_id or report.task_id == gap.task_id
        ]
        if not bound_findings and report.task_id != gap.task_id:
            continue
        parts.extend(
            [
                report.summary,
                report.status,
                str(report.as_of or ""),
                *report.limitations,
                *report.unanswered_questions,
                *report.contradictions,
            ]
        )
        for evidence in bound_findings:
            parts.extend(
                [
                    evidence.claim,
                    evidence.category.value,
                    evidence.stance.value,
                    evidence.source_url or "",
                    evidence.source_name or "",
                    str(evidence.published_at or ""),
                    evidence.excerpt or "",
                ]
            )
    trace_ids = set(gap.trace_ids)
    trace_path = session_dir / "traces.jsonl"
    if trace_path.is_file():
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                trace = ToolTrace.model_validate(json.loads(line))
            except (ValueError, TypeError):
                continue
            if trace.id not in trace_ids and trace.agent_id != gap.task_id:
                continue
            parts.extend(
                [
                    trace.tool,
                    json.dumps(trace.arguments, sort_keys=True),
                    trace.observation,
                    trace.replay.source or "",
                    trace.replay.as_of or "",
                ]
            )
    return " ".join(parts)


def _classify(
    gap: GapEntry, board: dict[str, Any], context: str
) -> tuple[list[Capability], bool, str]:
    text = context.lower()
    reason_text = f"{gap.claim} {gap.notes}".lower()
    if _task_is_failed_replan(gap, board) or "replan" in text:
        return (
            [Capability.REPLAN_FAILURE],
            True,
            "A replanned task failed to close the gap.",
        )
    if gap.kind is GapKind.ENGINE_MOCK:
        return (
            [Capability.ENGINE_GROUNDING],
            True,
            "Engine evidence was absent, mock, or not grounded.",
        )
    if any(
        token in reason_text
        for token in ("as-of", "as_of", "stale", "publication date", "future dated")
    ):
        return (
            [Capability.AS_OF_DISCIPLINE],
            True,
            "The failure concerns point-in-time discipline.",
        )
    # Task context includes successful engine reads as well as failed evidence.
    # Only the gap's own reason can identify an engine-grounding failure.
    if any(
        token in reason_text
        for token in (
            "engine_query",
            "engine result",
            "engine mock",
            "engine observation",
            "v_d",
        )
    ):
        return (
            [Capability.ENGINE_GROUNDING],
            True,
            "Engine evidence was absent, mock, or not grounded.",
        )
    if any(
        token in text
        for token in ("contradict", "conflicting", "cherry-pick", "dissent")
    ):
        return (
            [Capability.CONTRADICTION_SEARCH],
            True,
            "Contradictory evidence was not resolved or surfaced.",
        )
    if any(
        token in text
        for token in (
            "crowd",
            "positioning",
            "finra",
            "short interest",
            "days-to-cover",
        )
    ):
        return (
            [Capability.CROWDING_CONFIRMATION],
            True,
            "Crowding required independent confirmation.",
        )
    if any(
        token in text
        for token in (
            "withhold",
            "overstat",
            "unsupported conclusion",
            "insufficient evidence",
        )
    ):
        return (
            [Capability.CLAIM_WITHHOLDING],
            True,
            "The conclusion exceeded the available evidence.",
        )
    if gap.kind in {GapKind.MISSING_EVIDENCE, GapKind.UNANSWERED_QUESTION}:
        return (
            [Capability.SOURCE_DISCOVERY],
            True,
            "Required evidence was not discovered.",
        )
    if any(
        token in text
        for token in ("primary source", "secondary source", "source quality", "filing")
    ):
        return (
            [Capability.SOURCE_QUALITY],
            True,
            "The evidence did not meet source-quality requirements.",
        )
    return (
        [Capability.SOURCE_QUALITY],
        False,
        "Failure retained for review because no deterministic taxonomy rule matched.",
    )


def _matching_world_ids(
    worlds: list[ResearchWorld],
    capabilities: list[Capability],
    policy: MomentumCapability,
) -> list[str]:
    del policy
    wanted = {item.value for item in capabilities}
    return [
        world.world_id for world in worlds if wanted.intersection(world.capabilities)
    ]


def _case_path(project_root: Path, case_id: str) -> Path:
    digest = hashlib.sha256(case_id.encode()).hexdigest()
    return Path(project_root) / "reports" / "capability_cases" / f"{digest}.json"


def _persist_case(project_root: Path, case: MinedCapabilityCase) -> MinedCapabilityCase:
    path = _case_path(project_root, case.case_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(case.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    if path.is_file():
        if path.read_text(encoding="utf-8") == text:
            return case
        try:
            return MinedCapabilityCase.model_validate(_read_json(path))
        except (OSError, ValueError, TypeError):
            raise ValueError(
                f"stored immutable capability case is invalid: {case.case_id}"
            ) from None
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
    return case


def mine_session(
    session_dir: Path,
    project_root: Path,
    worlds: list[ResearchWorld] | None = None,
    max_cases: int = MAX_MINED_CASES,
) -> list[MinedCapabilityCase]:
    """Mine at most eight deterministic cases from one persisted verification."""
    if isinstance(max_cases, bool) or not 1 <= max_cases <= MAX_MINED_CASES:
        raise ValueError(f"max_cases must be from 1 through {MAX_MINED_CASES}")
    session_dir = Path(session_dir).resolve()
    project_root = Path(project_root).resolve()
    verification_path = session_dir / "verification.json"
    if not verification_path.is_file():
        raise FileNotFoundError("missing verification.json")
    try:
        verification = VerificationReport.model_validate(_read_json(verification_path))
    except (OSError, ValueError, TypeError):
        raise ValueError("invalid verification.json") from None
    gap_ids = [gap.id for gap in verification.gaps]
    if len(gap_ids) != len(set(gap_ids)):
        raise ValueError("duplicate gap ids in verification.json")
    board_path = session_dir / "task_board.json"
    try:
        board = _read_json(board_path) if board_path.is_file() else {}
        if not isinstance(board, dict):
            board = {}
    except (OSError, ValueError, TypeError):
        board = {}
    approved = _valid_worlds(_load_worlds(worlds))
    references, hashes = _source_artifacts(session_dir)
    session_id = str(board.get("session_id") or session_dir.name)
    cases: list[MinedCapabilityCase] = []
    for gap in verification.gaps[:max_cases]:
        context = _bound_context(session_dir, gap, board)
        capabilities, classified, rationale = _classify(gap, board, context)
        policy_capability = _POLICY_CAPABILITY[capabilities[0]]
        world_ids = (
            _matching_world_ids(approved, capabilities, policy_capability)
            if classified
            else []
        )
        occurrence_id = _occurrence_id(session_id, gap.id)
        case = MinedCapabilityCase(
            case_id=_case_id(session_id, [occurrence_id]),
            source_session_id=session_id,
            triggering_gap_ids=[occurrence_id],
            source_evidence_ids=[gap.evidence_id or gap.id],
            capabilities=capabilities,
            policy_capability=policy_capability,
            approved_world_ids=world_ids,
            approved_world_hashes={
                world.world_id: world.content_hash
                for world in approved
                if world.world_id in world_ids
            },
            status="mapped" if world_ids else "pending_world_candidate",
            source_artifact_hashes=hashes,
            source_artifact_references=references,
            rationale=rationale,
        )
        cases.append(_persist_case(project_root, case))
    return cases


def _load_mined_cases(project_root: Path) -> list[MinedCapabilityCase]:
    folder = Path(project_root) / "reports" / "capability_cases"
    cases: list[MinedCapabilityCase] = []
    for path in sorted(folder.glob("*.json")):
        try:
            cases.append(MinedCapabilityCase.model_validate(_read_json(path)))
        except (OSError, ValueError, TypeError):
            continue
    return cases


def _gap_id_for_row(project_root: Path, row: GapLedgerRow) -> str | None:
    if not row.source_session_id:
        return None
    path = Path(project_root) / "reports" / row.source_session_id / "verification.json"
    if not path.is_file():
        return None
    try:
        report = VerificationReport.model_validate(_read_json(path))
    except (OSError, ValueError, TypeError):
        return None
    match = next(
        (gap for gap in report.gaps if (gap.evidence_id or gap.id) == row.evidence_id),
        None,
    )
    return match.id if match is not None else None


def _fallback_capabilities(row: GapLedgerRow) -> list[Capability]:
    gap = GapEntry(
        kind=row.gap_kind,
        claim=row.claim,
        notes=row.notes,
        evidence_id=row.evidence_id,
    )
    capabilities, classified, _rationale = _classify(
        gap, {}, f"{row.claim} {row.notes}"
    )
    if classified:
        return capabilities
    return []


def select_worlds_for_open_gaps(
    project_root: Path,
    worlds: list[ResearchWorld],
    max_targets: int = MAX_TARGET_WORLDS,
) -> tuple[list[ResearchWorld], list[str], list[str]]:
    """Select fixed guards plus bounded approved targets for OPEN occurrences."""
    if isinstance(max_targets, bool) or not 0 <= max_targets <= MAX_TARGET_WORLDS:
        raise ValueError(f"max_targets must be from 0 through {MAX_TARGET_WORLDS}")
    approved = _valid_worlds(list(worlds))
    guards = [world for world in approved if world.guard]
    cases = _load_mined_cases(project_root)
    case_index = {
        (case.source_session_id, evidence_id): case
        for case in cases
        for evidence_id in case.source_evidence_ids
    }
    by_id = {world.world_id: world for world in approved}
    targets: list[ResearchWorld] = []
    trigger_ids: list[str] = []
    target_ids: list[str] = []
    if max_targets == 0:
        return guards, trigger_ids, target_ids
    for row in load_rows(Path(project_root)):
        if row.status is not GapLedgerStatus.OPEN:
            continue
        mined_gap_id = _gap_id_for_row(Path(project_root), row)
        raw_gap_id = mined_gap_id or row.evidence_id
        fallback_trigger_id = _occurrence_id(
            row.source_session_id or "unknown", raw_gap_id
        )
        case = case_index.get((row.source_session_id or "", row.evidence_id))
        candidate_ids = case.approved_world_ids if case is not None else []
        if case is not None and any(
            world_id not in by_id
            or by_id[world_id].content_hash != case.approved_world_hashes.get(world_id)
            for world_id in candidate_ids
        ):
            candidate_ids = []
        if case is None:
            candidate_ids = _matching_world_ids(
                approved, _fallback_capabilities(row), row.capability
            )
        chosen = next(
            (
                by_id[world_id]
                for world_id in candidate_ids
                if world_id in by_id and world_id not in target_ids
            ),
            None,
        )
        if chosen is None:
            continue
        if chosen.world_id not in {world.world_id for world in guards}:
            targets.append(chosen)
        target_ids.append(chosen.world_id)
        trigger_ids.append(
            case.triggering_gap_ids[0] if case is not None else fallback_trigger_id
        )
        if len(target_ids) >= max_targets:
            break
    return [*guards, *targets], trigger_ids, target_ids


__all__ = [
    "MAX_MINED_CASES",
    "MAX_TARGET_WORLDS",
    "Capability",
    "MinedCapabilityCase",
    "mine_session",
    "select_worlds_for_open_gaps",
]
