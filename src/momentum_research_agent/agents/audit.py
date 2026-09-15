"""Deterministic evidence audit. No LLM. Fail closed on missing or impossible metadata."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Literal

from momentum_research_agent.models.schemas import (
    Evidence,
    EvidenceStance,
    EvidenceVerdict,
    ResearchReport,
    VerificationReport,
    VerificationStatus,
    utcnow,
)

OverallStatus = Literal["pass", "pass_with_caveats", "fail"]

_RANK = {
    VerificationStatus.VERIFIED: 0,
    VerificationStatus.WEAK: 1,
    VerificationStatus.UNCHECKED: 2,
    VerificationStatus.REJECTED: 3,
}


def more_conservative(left: VerificationStatus, right: VerificationStatus) -> VerificationStatus:
    return left if _RANK[left] >= _RANK[right] else right


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def rollup_status(
    verdicts: list[EvidenceVerdict],
    missing_evidence: list[str],
) -> OverallStatus:
    if missing_evidence and not verdicts:
        return "fail"
    if any(item.status is VerificationStatus.REJECTED for item in verdicts):
        return "fail"
    if missing_evidence or any(
        item.status in {VerificationStatus.WEAK, VerificationStatus.UNCHECKED} for item in verdicts
    ):
        return "pass_with_caveats"
    if not verdicts:
        return "fail"
    return "pass"


def static_audit(question: str, reports: list[ResearchReport]) -> VerificationReport:
    now = utcnow()
    verdicts: list[EvidenceVerdict] = []
    missing: list[str] = []
    unsupported: list[str] = []

    if not reports:
        missing.append("No research reports were provided.")

    pairs: list[tuple[ResearchReport, Evidence]] = []
    for report in reports:
        if report.status == "complete" and not report.findings:
            missing.append(f"Task {report.task_id} ({report.agent_role}) is complete with empty findings.")
        for item in report.findings:
            pairs.append((report, item))

    for report, item in pairs:
        issues: list[str] = []
        status = VerificationStatus.VERIFIED
        if not item.source_url and not item.source_name:
            issues.append("No source_url or source_name")
            status = VerificationStatus.UNCHECKED
        elif not item.source_url:
            issues.append("Source name present but no retrievable URL")
            status = more_conservative(status, VerificationStatus.WEAK)
        if item.published_at is not None and _as_utc(item.published_at) > now:
            issues.append("published_at is in the future")
            status = VerificationStatus.REJECTED
        if item.confidence == "low":
            status = more_conservative(status, VerificationStatus.WEAK)
        if status in {VerificationStatus.REJECTED, VerificationStatus.UNCHECKED}:
            unsupported.append(item.claim)
        notes = "; ".join(issues) if issues else "Static checks passed; independent re-check still required."
        verdicts.append(
            EvidenceVerdict(
                evidence_id=item.id,
                task_id=report.task_id,
                claim=item.claim,
                status=status,
                notes=notes,
                issues=issues,
            )
        )

    by_category: dict[str, list[tuple[EvidenceVerdict, Evidence]]] = defaultdict(list)
    for (report, item), verdict in zip(pairs, verdicts, strict=True):
        by_category[item.category.value].append((verdict, item))
    for items in by_category.values():
        stances = {evidence.stance for _, evidence in items}
        if EvidenceStance.SUPPORTING in stances and EvidenceStance.CONTRADICTING in stances:
            for verdict, _evidence in items:
                conflict = "Cross-report supporting vs contradicting stance in the same category"
                if conflict not in verdict.issues:
                    verdict.issues.append(conflict)
                verdict.status = more_conservative(verdict.status, VerificationStatus.WEAK)
                if not verdict.notes.endswith(conflict):
                    verdict.notes = f"{verdict.notes}; {conflict}" if verdict.notes else conflict

    overall = rollup_status(verdicts, missing)
    if not reports:
        summary = "Verification failed: no reports to audit."
    elif not pairs:
        summary = "No evidence items to verify."
        overall = "fail"
        missing.append("No Evidence[] items across completed reports.")
    else:
        summary = (
            f"Static audit of {len(verdicts)} evidence item(s): overall={overall}. "
            "LLM re-check may tighten or confirm these verdicts."
        )
    return VerificationReport(
        question=question,
        overall_status=overall,  # type: ignore[arg-type]
        summary=summary,
        verdicts=verdicts,
        unsupported_claims=list(dict.fromkeys(unsupported)),
        missing_evidence=missing,
    )


def merge_verification(
    static: VerificationReport,
    llm: VerificationReport,
    question: str,
) -> VerificationReport:
    by_id = {item.evidence_id: item for item in static.verdicts}
    merged: list[EvidenceVerdict] = []
    seen: set[str] = set()
    for llm_verdict in llm.verdicts:
        if llm_verdict.evidence_id not in by_id:
            continue
        static_verdict = by_id[llm_verdict.evidence_id]
        seen.add(llm_verdict.evidence_id)
        issues = list(dict.fromkeys([*static_verdict.issues, *llm_verdict.issues]))
        merged.append(
            EvidenceVerdict(
                evidence_id=static_verdict.evidence_id,
                task_id=static_verdict.task_id,
                claim=static_verdict.claim,
                status=more_conservative(static_verdict.status, llm_verdict.status),
                notes=llm_verdict.notes or static_verdict.notes,
                issues=issues,
                rechecked_source=llm_verdict.rechecked_source,
            )
        )
    for evidence_id, static_verdict in by_id.items():
        if evidence_id not in seen:
            issue = "No terminal independent verdict was returned for this evidence."
            merged.append(static_verdict.model_copy(update={
                "status": more_conservative(static_verdict.status, VerificationStatus.UNCHECKED),
                "issues": list(dict.fromkeys([*static_verdict.issues, issue])),
                "notes": f"{static_verdict.notes} {issue}",
                "rechecked_source": None,
            }))

    missing = list(dict.fromkeys([*static.missing_evidence, *llm.missing_evidence]))
    unsupported = [
        item.claim
        for item in merged
        if item.status in {VerificationStatus.REJECTED, VerificationStatus.UNCHECKED}
    ]
    overall = rollup_status(merged, missing)
    summary = llm.summary.strip() or static.summary
    return VerificationReport(
        question=question,
        overall_status=overall,  # type: ignore[arg-type]
        summary=summary,
        verdicts=merged,
        unsupported_claims=list(dict.fromkeys(unsupported)),
        missing_evidence=missing,
    )
