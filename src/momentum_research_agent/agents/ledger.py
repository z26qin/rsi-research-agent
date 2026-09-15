"""Momentum gap ledger: turn verdicts + engine/search traces into a replayable book."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from momentum_research_agent.models.schemas import (
    GapEntry,
    GapKind,
    ReplayHint,
    ResearchReport,
    ToolTrace,
    VerificationReport,
    VerificationStatus,
)
from momentum_research_agent.tools.engine_adapter import normalize_engine_payload

TRACEABLE_TOOLS = frozenset({"engine_query", "web_search", "read_url", "market_data"})
MAX_OBSERVATION_CHARS = 4000


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonicalize_observation(tool: str, observation: str) -> str:
    if tool == "engine_query":
        try:
            return json.dumps(json.loads(observation), sort_keys=True, indent=2)
        except json.JSONDecodeError:
            pass
    return observation


def _replay_hint(tool: str, arguments: dict[str, Any], observation: str) -> ReplayHint:
    if tool == "web_search":
        query = arguments.get("query")
        return ReplayHint(
            method="stored_observation",
            query=str(query) if query is not None else None,
        )
    try:
        payload = json.loads(observation)
    except json.JSONDecodeError:
        return ReplayHint(method="stored_observation")
    if not isinstance(payload, dict):
        return ReplayHint(method="stored_observation")
    source = payload.get("source")
    source_path = payload.get("source_path")
    as_of = payload.get("as_of")
    if source == "momentum-tail-risk-monitor" and source_path:
        return ReplayHint(
            method="engine_snapshot",
            source=str(source),
            source_path=str(source_path),
            as_of=str(as_of) if as_of else None,
        )
    return ReplayHint(
        method="stored_observation",
        source=str(source) if source else None,
        as_of=str(as_of) if as_of else None,
    )


def record_trace(
    tool: str,
    arguments: dict[str, Any],
    observation: str,
    *,
    agent_id: str | None = None,
    agent_role: str | None = None,
) -> ToolTrace | None:
    if tool not in TRACEABLE_TOOLS:
        return None
    canonical = canonicalize_observation(tool, observation)
    limit = 200_000 if tool in {'read_url', 'market_data'} else MAX_OBSERVATION_CHARS
    truncated = len(canonical) > limit
    stored = canonical[:limit]
    if truncated:
        stored = stored + "\n…[truncated]"
    return ToolTrace(
        tool=tool,  # type: ignore[arg-type]
        arguments=dict(arguments),
        observation=stored,
        observation_sha256=_sha256(stored),
        truncated=truncated,
        agent_id=agent_id,
        agent_role=agent_role,
        replay=_replay_hint(tool, arguments, canonical),
    )


def _traces_for_task(traces: list[ToolTrace], task_id: str | None) -> list[str]:
    if not task_id:
        return [item.id for item in traces if item.agent_role == "verifier"]
    ids = [item.id for item in traces if item.agent_id == task_id]
    ids.extend(item.id for item in traces if item.agent_role == "verifier")
    return list(dict.fromkeys(ids))


def build_gaps(
    reports: list[ResearchReport],
    report: VerificationReport,
    traces: list[ToolTrace],
) -> list[GapEntry]:
    gaps: list[GapEntry] = []
    for verdict in report.verdicts:
        if verdict.status is VerificationStatus.REJECTED:
            kind = GapKind.REJECTED_EVIDENCE
        elif verdict.status is VerificationStatus.UNCHECKED:
            kind = GapKind.UNCHECKED_EVIDENCE
        else:
            continue
        gaps.append(
            GapEntry(
                kind=kind,
                claim=verdict.claim,
                notes=verdict.notes,
                evidence_id=verdict.evidence_id,
                task_id=verdict.task_id,
                status=verdict.status,
                trace_ids=_traces_for_task(traces, verdict.task_id),
            )
        )
    for note in report.missing_evidence:
        gaps.append(
            GapEntry(
                kind=GapKind.MISSING_EVIDENCE,
                claim=note,
                notes="Called out as missing during verification.",
            )
        )
    for research in reports:
        for question in research.unanswered_questions:
            gaps.append(
                GapEntry(
                    kind=GapKind.UNANSWERED_QUESTION,
                    claim=question,
                    task_id=research.task_id,
                    notes=f"Left open by {research.agent_role}.",
                    trace_ids=_traces_for_task(traces, research.task_id),
                )
            )
    for trace in traces:
        if trace.tool != "engine_query":
            continue
        if (trace.replay.source or "") != "mock":
            continue
        ticker = str(trace.arguments.get("ticker") or "?")
        gaps.append(
            GapEntry(
                kind=GapKind.ENGINE_MOCK,
                claim=f"engine_query({ticker}) returned labeled mock data.",
                notes="Replay uses the stored observation; no live snapshot was attached.",
                evidence_id=f"engine_mock:{ticker}",
                task_id=trace.agent_id,
                trace_ids=[trace.id],
            )
        )
    return gaps


def finalize_ledger(
    report: VerificationReport,
    reports: list[ResearchReport],
    traces: list[ToolTrace],
) -> VerificationReport:
    unique: dict[str, ToolTrace] = {}
    for item in traces:
        unique[item.id] = item
    ordered = list(unique.values())
    gaps = build_gaps(reports, report, ordered)
    return report.model_copy(
        update={
            "schema_kind": "momentum_gap_ledger",
            "gaps": gaps,
            "traces": ordered,
        }
    )


def replay_trace(trace: ToolTrace) -> dict[str, Any]:
    """Replay a stored engine/search trace without hitting the LLM."""
    if trace.tool == "web_search" or trace.replay.method == "stored_observation":
        return {
            "ok": True,
            "method": "stored_observation",
            "tool": trace.tool,
            "observation": trace.observation,
            "sha256_match": _sha256(trace.observation) == trace.observation_sha256,
            "note": (
                "web_search replay uses the stored observation; a live search is not bit-identical."
                if trace.tool == "web_search"
                else "Stored observation replay."
            ),
        }
    path = Path(trace.replay.source_path) if trace.replay.source_path else None
    if path is None or not path.is_file():
        return {
            "ok": False,
            "method": "engine_snapshot",
            "tool": trace.tool,
            "reason": "engine snapshot path is missing.",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = None
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "method": "engine_snapshot",
            "tool": trace.tool,
            "reason": f"could not parse {path}",
        }
    ticker = str(trace.arguments.get("ticker") or "UNKNOWN")
    start = trace.arguments.get("start")
    end = trace.arguments.get("end")
    live = normalize_engine_payload(
        payload,
        ticker,
        path,
        start=None if start is None else str(start),
        end=None if end is None else str(end),
    )
    dumped = canonicalize_observation("engine_query", json.dumps(live))
    return {
        "ok": True,
        "method": "engine_snapshot",
        "tool": trace.tool,
        "observation": dumped,
        "sha256_match": _sha256(dumped) == trace.observation_sha256,
        "source_path": str(path),
        "as_of": live.get("as_of"),
    }
