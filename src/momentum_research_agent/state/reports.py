"""Research report artifacts: JSON is canonical, Markdown is a human view."""

from __future__ import annotations

from pathlib import Path

from momentum_research_agent.models.schemas import (
    Evidence,
    EvidenceCategory,
    EvidenceStance,
    ResearchReport,
    Task,
    VerificationReport,
    utcnow,
)
from momentum_research_agent.state.persistence import load_json, save_json, save_text

LEGACY_MARKDOWN_NOTE = (
    "Loaded from legacy Markdown; structured Evidence[] was not preserved."
)


def report_stem(task: Task) -> str:
    return f"{task.id}_{task.profile}"


def json_path(session_dir: Path, task: Task) -> Path:
    return Path(session_dir) / "sub_reports" / f"{report_stem(task)}.json"


def markdown_path(session_dir: Path, task: Task) -> Path:
    return Path(session_dir) / "sub_reports" / f"{report_stem(task)}.md"


def render_research_report_markdown(report: ResearchReport) -> str:
    evidence_blocks: list[str] = []
    for item in report.findings:
        source = item.source_url or item.source_name or "(no source)"
        evidence_blocks.append(
            f"- **{item.stance.value}** / `{item.category.value}` / "
            f"{item.confidence}: {item.claim} — {source}"
        )
    evidence = "\n".join(evidence_blocks) or "- (none)"
    unanswered = "\n".join(f"- {item}" for item in report.unanswered_questions) or "- (none)"
    contradictions = "\n".join(f"- {item}" for item in report.contradictions) or "- (none)"
    return (
        f"# {report.title}\n\n"
        f"- Task ID: `{report.task_id}`\n"
        f"- Role: `{report.agent_role}`\n"
        f"- Status: **{report.status}**\n\n"
        f"## Summary\n\n{report.summary}\n\n"
        "## Numeric observations (not independently verified)\n\n"
        + '\n'.join(f'- {m.name}: {m.value if m.value is not None else "unavailable"} {m.unit}; as-of {m.as_of or "unknown"}; {m.source_url or m.missing_reason}; evidence {m.evidence_id or "none"}' for m in report.metrics) + '\n\n' +
        f"Data as-of: {report.as_of or 'unknown'}\n\n"
        f"## Sources (not verification)\n\n{chr(10).join(report.sources) or '(none)'}\n\n"
        f"## Limitations\n\n{chr(10).join(report.limitations) or '(none)'}\n\n"
        f"## Evidence\n\n{evidence}\n\n"
        f"## Contradictions\n\n{contradictions}\n\n"
        f"## Unanswered Questions\n\n{unanswered}\n"
    )


def persist_research_report(session_dir: Path, task: Task, report: ResearchReport) -> Path:
    payload_path = json_path(session_dir, task)
    save_json(payload_path, report.model_dump(mode="json"))
    save_text(markdown_path(session_dir, task), render_research_report_markdown(report))
    return payload_path


def research_report_from_legacy_markdown(task: Task, text: str) -> ResearchReport:
    body = text.strip() or "(empty legacy markdown)"
    return ResearchReport(
        task_id=task.id,
        title=task.title,
        agent_role=task.profile,
        findings=[
            Evidence(
                claim=LEGACY_MARKDOWN_NOTE,
                category=EvidenceCategory.OTHER,
                stance=EvidenceStance.NEUTRAL,
                excerpt=body[:500],
                confidence="low",
                agent_id=task.id,
                retrieved_at=utcnow(),
            )
        ],
        summary=body,
        unanswered_questions=[LEGACY_MARKDOWN_NOTE],
        contradictions=[],
        status="partial",
    )


def load_research_report(session_dir: Path, task: Task) -> ResearchReport | None:
    folder = Path(session_dir) / "sub_reports"
    if not folder.exists():
        return None

    canonical = json_path(session_dir, task)
    if canonical.exists():
        return ResearchReport.model_validate(load_json(canonical))

    json_matches = sorted(folder.glob(f"{task.id}_*.json"))
    if json_matches:
        return ResearchReport.model_validate(load_json(json_matches[0]))

    md_matches = sorted(folder.glob(f"{task.id}_*.md"))
    if md_matches:
        return research_report_from_legacy_markdown(
            task, md_matches[0].read_text(encoding="utf-8")
        )
    return None


def verification_json_path(session_dir: Path) -> Path:
    return Path(session_dir) / "verification.json"


def verification_markdown_path(session_dir: Path) -> Path:
    return Path(session_dir) / "verification.md"


def render_verification_markdown(report: VerificationReport) -> str:
    rows = "\n".join(
        f"- `{item.evidence_id}` **{item.status.value}**: {item.claim}"
        + (f" — {item.notes}" if item.notes else "")
        for item in report.verdicts
    ) or "- (none)"
    unsupported = "\n".join(f"- {item}" for item in report.unsupported_claims) or "- (none)"
    missing = "\n".join(f"- {item}" for item in report.missing_evidence) or "- (none)"
    gaps = "\n".join(
        f"- `{item.kind.value}` {item.claim}"
        + (f" — traces: {', '.join(f'`{tid}`' for tid in item.trace_ids)}" if item.trace_ids else "")
        for item in report.gaps
    ) or "- (none)"
    traces = "\n".join(
        f"- `{item.id}` **{item.tool}** `{item.replay.method}` "
        f"args={item.arguments} sha256={item.observation_sha256[:12]}…"
        for item in report.traces
    ) or "- (none)"
    return (
        f"# Momentum gap ledger\n\n"
        f"**Question:** {report.question}\n\n"
        f"**Overall:** {report.overall_status}\n\n"
        f"**Timestamp:** {report.timestamp.isoformat()}\n\n"
        f"## Summary\n\n{report.summary}\n\n"
        f"## Gaps\n\n{gaps}\n\n"
        f"## Replayable traces\n\n{traces}\n\n"
        f"## Verdicts\n\n{rows}\n\n"
        f"## Unsupported Claims\n\n{unsupported}\n\n"
        f"## Missing Evidence\n\n{missing}\n"
    )


def persist_verification_report(session_dir: Path, report: VerificationReport) -> Path:
    path = verification_json_path(session_dir)
    save_json(path, report.model_dump(mode="json"))
    save_text(verification_markdown_path(session_dir), render_verification_markdown(report))
    return path


def load_verification_report(session_dir: Path) -> VerificationReport | None:
    path = verification_json_path(session_dir)
    if not path.exists():
        return None
    return VerificationReport.model_validate(load_json(path))
