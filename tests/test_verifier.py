from __future__ import annotations

import json


from momentum_research_agent.models.schemas import (
    Evidence,
    EvidenceCategory,
    EvidenceStance,
    ResearchReport,
    VerificationReport,
    VerificationStatus,
)
from momentum_research_agent.agents.ledger import record_trace


def _report() -> ResearchReport:
    return ResearchReport(
        task_id="aa11bb22",
        title="Momentum",
        agent_role="momentum_analyst",
        findings=[
            Evidence(
                id="ev01",
                claim="Crowding score is elevated.",
                category=EvidenceCategory.CROWDED_POSITIONING,
                stance=EvidenceStance.SUPPORTING,
                source_url="https://example.com/crowding",
                confidence="high",
            )
        ],
        summary="Crowded.",
        status="complete",
    )


def test_web_verdict_requires_successful_independent_verifier_read() -> None:
    from momentum_research_agent.agents.verifier import _guard_source_discovery

    url = "https://example.com/crowding"
    verified = VerificationReport(
        question="q",
        overall_status="pass",
        summary="ok",
        verdicts=[
            {
                "evidence_id": "ev01",
                "claim": "Crowding score is elevated.",
                "status": "verified",
                "rechecked_source": url,
            }
        ],
    )
    analyst = record_trace(
        "read_url",
        {"url": url},
        json.dumps({"status": "ok", "url": url}),
        agent_role="momentum_analyst",
    )
    assert analyst is not None
    _guard_source_discovery(verified, [_report()], [analyst])
    assert verified.verdicts[0].status is VerificationStatus.UNCHECKED

    verified = VerificationReport(
        question="q",
        overall_status="pass",
        summary="ok",
        verdicts=[
            {
                "evidence_id": "ev01",
                "claim": "Crowding score is elevated.",
                "status": "verified",
                "rechecked_source": url,
            }
        ],
    )
    verifier = record_trace(
        "read_url",
        {"url": url},
        json.dumps({"status": "ok", "url": url}),
        agent_role="verifier",
    )
    assert verifier is not None
    _guard_source_discovery(verified, [_report()], [analyst, verifier])
    assert verified.verdicts[0].status is VerificationStatus.VERIFIED
