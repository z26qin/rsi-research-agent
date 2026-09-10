from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from momentum_research_agent.agents.verifier import Verifier
from momentum_research_agent.models.schemas import (
    Evidence,
    EvidenceCategory,
    EvidenceStance,
    ResearchReport,
    VerificationReport,
    VerificationStatus,
)
from momentum_research_agent.agents.ledger import record_trace
from momentum_research_agent.state.reports import load_verification_report


class FakeUsage:
    prompt_tokens = 11
    completion_tokens = 7


class FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=None))]
        self.usage = FakeUsage()


class FakeCompletions:
    def __init__(self, payloads: list[str]) -> None:
        self._payloads = list(payloads)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeResponse(self._payloads.pop(0))


class FakeClient:
    def __init__(self, payloads: list[str]) -> None:
        self.completions = FakeCompletions(payloads)
        self.chat = SimpleNamespace(completions=self.completions)


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


@pytest.mark.asyncio
async def test_verifier_writes_json_and_merges_llm(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    llm_payload = json.dumps(
        {
            "question": "Is this a crash?",
            "overall_status": "pass",
            "summary": "URL re-checked; claim stands.",
            "unsupported_claims": [],
            "missing_evidence": [],
            "verdicts": [
                {
                    "evidence_id": "ev01",
                    "task_id": "aa11bb22",
                    "claim": "Crowding score is elevated.",
                    "status": "verified",
                    "notes": "Re-checked example.com",
                    "issues": [],
                    "rechecked_source": "https://example.com/crowding",
                }
            ],
        }
    )
    client = FakeClient([llm_payload])
    verifier = Verifier(
        client=client,  # type: ignore[arg-type]
        model="deepseek-chat",
        project_root=project_root,
    )
    result = await verifier.run("Is this a crash?", [_report()], tmp_path / "session")
    assert result.report.verdicts[0].status is VerificationStatus.VERIFIED
    assert result.report.verdicts[0].rechecked_source == "https://example.com/crowding"
    loaded = load_verification_report(tmp_path / "session")
    assert loaded is not None
    assert (tmp_path / "session" / "verification.md").exists()
    assert result.usage.total_tokens == 18


@pytest.mark.asyncio
async def test_verifier_keeps_static_audit_when_llm_fails(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    client = FakeClient(["not-json"])
    verifier = Verifier(
        client=client,  # type: ignore[arg-type]
        model="deepseek-chat",
        project_root=project_root,
    )
    result = await verifier.run("q", [_report()], tmp_path / "session")
    assert "static audit retained" in result.report.summary.lower() or "failed" in result.report.summary.lower()
    assert result.report.verdicts[0].evidence_id == "ev01"


@pytest.mark.asyncio
async def test_verifier_skips_llm_when_no_evidence(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    client = FakeClient([])
    empty = ResearchReport(
        task_id="x",
        title="Empty",
        agent_role="credit_analyst",
        findings=[],
        summary="nothing",
        status="insufficient_evidence",
    )
    verifier = Verifier(
        client=client,  # type: ignore[arg-type]
        model="deepseek-chat",
        project_root=project_root,
    )
    result = await verifier.run("q", [empty], tmp_path / "session")
    assert client.completions.calls == []
    assert result.report.overall_status == "fail"
    assert load_verification_report(tmp_path / "session") is not None


def test_web_verdict_requires_successful_independent_verifier_read() -> None:
    from momentum_research_agent.agents.verifier import _guard_source_discovery
    url = 'https://example.com/crowding'
    verified = VerificationReport(question='q',overall_status='pass',summary='ok',verdicts=[{
        'evidence_id':'ev01','claim':'Crowding score is elevated.','status':'verified','rechecked_source':url}])
    analyst = record_trace('read_url', {'url':url}, json.dumps({'status':'ok','url':url}), agent_role='momentum_analyst')
    assert analyst is not None
    _guard_source_discovery(verified, [_report()], [analyst])
    assert verified.verdicts[0].status is VerificationStatus.UNCHECKED

    verified = VerificationReport(question='q',overall_status='pass',summary='ok',verdicts=[{
        'evidence_id':'ev01','claim':'Crowding score is elevated.','status':'verified','rechecked_source':url}])
    verifier = record_trace('read_url', {'url':url}, json.dumps({'status':'ok','url':url}), agent_role='verifier')
    assert verifier is not None
    _guard_source_discovery(verified, [_report()], [analyst, verifier])
    assert verified.verdicts[0].status is VerificationStatus.VERIFIED
