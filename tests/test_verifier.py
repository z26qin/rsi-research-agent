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


async def test_verifier_timeout_after_source_read_persists_unchecked(
    tmp_path, monkeypatch
):
    from datetime import timedelta
    from test_research_arena import ScriptedClient, response
    from momentum_research_agent.agents.verifier import Verifier
    from momentum_research_agent.errors import AgentDeadlineExceeded
    from momentum_research_agent.models.schemas import utcnow
    from momentum_research_agent.tools import read_url

    report = _report()
    report.findings.append(
        report.findings[0].model_copy(
            update={
                "id": "future",
                "claim": "Future-dated evidence.",
                "published_at": utcnow() + timedelta(days=2),
            }
        )
    )

    async def fetch(url):
        return {
            "url": url,
            "text": "Crowding score is elevated.",
            "content_type": "text/plain",
            "truncated": False,
            "body_base64": "",
        }

    monkeypatch.setattr(read_url, "_fetch", fetch)
    client = ScriptedClient(
        [
            response(None, [("read_url", {"url": report.findings[0].source_url})]),
            AgentDeadlineExceeded("simulated deadline"),
        ]
    )
    result = await Verifier(client, "test", tmp_path).run("q", [report], tmp_path)
    saved = VerificationReport.model_validate_json(
        (tmp_path / "verification.json").read_text()
    )
    assert result.tool_calls == 1
    assert [v.status for v in saved.verdicts] == [
        VerificationStatus.UNCHECKED,
        VerificationStatus.REJECTED,
    ]
    assert report.findings[0].claim in saved.unsupported_claims
    assert any(
        g.evidence_id == "ev01" and g.kind.value == "unchecked_evidence"
        for g in saved.gaps
    )
    assert "AgentDeadlineExceeded" in saved.summary
