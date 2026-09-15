"""Bounded observed failure context, without evaluator answers or silent JSON cuts."""

from __future__ import annotations

import json
import re

from momentum_research_agent.eval.research_arena import ArenaRun


def observed_failure_context(question: str, run: ArenaRun, public_contract: str) -> str:
    """Only run observations and public instructions can enter this interface.

    Pack whole records, reserve room for both documents and findings, and count
    omissions. Long human narratives must never push source observations out.
    Diagnostics enforce public format requirements, not hidden fact alignment.
    """

    def encoded(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def bounded_text(value, limit):
        shortened = value[:limit]
        while len(encoded(shortened)) > limit:
            shortened = shortened[: len(shortened) // 2]
        return shortened

    bounded_question = bounded_text(question, 1000)
    bounded_contract = bounded_text(public_contract, 3000)
    context = {
        "question": bounded_question,
        "question_truncated": bounded_question != question,
        "public_research_contract": bounded_contract,
        "contract_truncated": bounded_contract != public_contract,
        "documents": [],
        "findings": [],
        "report_statuses": [r.status for r in run.submitted_reports[:2]],
        "unanswered_questions": [],
        "omitted_documents": 0,
        "omitted_findings": 0,
        "omitted_questions": 0,
    }
    documents = {}
    for trace in run.traces:
        if trace.agent_role == "verifier" or trace.tool != "read_url":
            continue
        try:
            data = json.loads(trace.observation)
        except ValueError:
            continue
        if not isinstance(data, dict) or data.get("status") != "ok":
            continue
        url = trace.arguments.get("url")
        if not isinstance(url, str):
            continue
        text = data.get("text") or data.get("page_content")
        if isinstance(text, str):
            documents[url] = {
                "url": url,
                "text": text,
                "published_at": data.get("published_at"),
                "quality": data.get("quality"),
            }

    def add(section, item, section_limit, omitted):
        context[section].append(item)
        if (
            len(encoded(context[section])) > section_limit
            or len(encoded(context)) > 11900
        ):
            context[section].pop()
            context[omitted] += 1

    for document in documents.values():
        # A partial observation is explicitly marked; it is never an answer key.
        excerpt = {
            **document,
            "text": document["text"][:2000],
            "truncated": len(document["text"]) > 2000,
        }
        add("documents", excerpt, 4000, "omitted_documents")
    verdicts = (
        {v.evidence_id: v for v in run.verification.verdicts}
        if run.verification
        else {}
    )
    for report in run.submitted_reports:
        # Failure diagnostics take priority over already-verified items if this
        # world's fixed feedback budget cannot hold every complete record.
        for item in sorted(
            report.findings,
            key=lambda finding: bool(
                verdicts.get(finding.id)
                and verdicts[finding.id].status.value == "verified"
            ),
        ):
            source = documents.get(item.source_url)
            verdict = verdicts.get(item.id)
            notes = (
                verdict.notes or ""
                if verdict and verdict.status.value != "verified"
                else ""
            )
            bounded_notes = bounded_text(notes, 800)
            issues = []
            if item.kind == "retrieval":
                issues.append("retrieval_observation_belongs_in_limitations")
            else:
                sentences = (
                    {s.strip() for s in re.split(r"(?<=[.!?])\s+", source["text"])}
                    if source
                    else set()
                )
                if not source:
                    issues.append("source_document_not_read")
                if item.excerpt not in sentences:
                    issues.append("excerpt_not_one_complete_source_sentence")
                if item.claim != item.excerpt or item.claim not in sentences:
                    issues.append("claim_not_exact_source_sentence")
                if item.published_at is None:
                    issues.append("missing_publication_timestamp")
                if not verdict or verdict.status.value != "verified":
                    issues.append("no_independent_verified_verdict")
            add(
                "findings",
                {
                    "id": item.id,
                    "kind": item.kind,
                    "claim": item.claim,
                    "excerpt": item.excerpt,
                    "source_url": item.source_url,
                    "category": item.category.value,
                    "stance": item.stance.value,
                    "independent_verdict": verdict.status.value if verdict else None,
                    "independent_verdict_notes": bounded_notes,
                    "verdict_notes_truncated": bounded_notes != notes,
                    "independent_verdict_issues": [
                        bounded_text(issue, 200) for issue in verdict.issues[:4]
                    ] if verdict and verdict.status.value != "verified" else [],
                    "public_contract_issues": issues,
                },
                6500,
                "omitted_findings",
            )
        for question in report.unanswered_questions:
            add("unanswered_questions", question, 1500, "omitted_questions")
    return encoded(context)
