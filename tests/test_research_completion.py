"""The useful lookup path keeps scope narrow and presents evidence status."""

import json
from io import StringIO

from rich.console import Console
from test_research_arena import ScriptedClient, response

from momentum_research_agent.cli import run_single
from momentum_research_agent.models.schemas import (
    ResearchReport,
    Task,
    UsageSummary,
    VerificationReport,
)
from momentum_research_agent.tools import read_url

URL = "https://www.ishares.com/us/products/251614/ishares-msci-usa-momentum-factor-etf/latest-holdings.csv"
ROWS = [
    ("AAA", 10),
    ("BBB", 9),
    ("CCC", 8),
    ("DDD", 7),
    ("EEE", 6),
    ("FFF", 5),
    ("GGG", 4),
    ("HHH", 3),
    ("III", 2),
    ("JJJ", 1),
]


def lookup_report():
    return {
        "task_id": "model-task",
        "title": "Holdings",
        "agent_role": "momentum_analyst",
        "summary": "Ten holdings from the retrieved table.",
        "status": "complete",
        "as_of": "2026-09-11",
        "sources": [URL],
        "findings": [
            {
                "id": symbol,
                "claim": f"{symbol} has fund weight {weight}%.",
                "category": "other",
                "stance": "neutral",
                "source_url": URL,
                "excerpt": f"{symbol},{weight}",
                "confidence": "high",
            }
            for symbol, weight in ROWS
        ],
        "metrics": [
            {
                "name": symbol,
                "value": weight,
                "unit": "%",
                "as_of": "2026-09-11",
                "source_url": URL,
                "evidence_id": symbol,
            }
            for symbol, weight in ROWS
        ],
    }


async def test_single_holdings_lookup_uses_source_tools_and_persists_answer(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "momentum_research_agent.cli.Task", lambda **kwargs: Task(id="lookup", **kwargs)
    )

    async def fetch(url):
        assert url == URL
        return {
            "url": url,
            "text": 'Fund Holdings as of,"Sep 11, 2026"\nTicker,Weight (%)\n'
            + "\n".join(f"{symbol},{weight}" for symbol, weight in ROWS),
            "content_type": "text/csv",
            "truncated": False,
            "body_base64": "",
        }

    monkeypatch.setattr(read_url, "_fetch", fetch)
    client = ScriptedClient(
        [
            response(None, [("read_url", {"url": URL})]),
            response(lookup_report()),
            response(None, [("read_url", {"url": URL})]),
            # Explicit independent uncertainty must remain visible in the final answer.
            response(
                {
                    "question": "Holdings",
                    "overall_status": "pass_with_caveats",
                    "summary": "Independent support remains uncertain.",
                    "verdicts": [
                        {
                            "evidence_id": f"lookup:{symbol}",
                            "claim": f"{symbol} has fund weight {weight}%.",
                            "status": "unchecked",
                        }
                        for symbol, weight in ROWS
                    ],
                }
            ),
        ]
    )
    session = tmp_path / "session"
    await run_single(
        question="What are MTUM's top 10 holdings? Include weights, observation date and sources.",
        session_dir=session,
        client=client,
        model="test",
        project_root=tmp_path,
        verbose=False,
        console=Console(file=StringIO()),
        usage=UsageSummary(),
    )
    research_tools = {tool["function"]["name"] for tool in client.requests[0]["tools"]}
    assert research_tools == {"read_url", "web_search"}
    report = json.loads(next((session / "sub_reports").glob("*.json")).read_text())
    assert len(report["metrics"]) == 10
    answer = (session / "answer.md").read_text()
    assert "| AAA | 10.0 | % | 2026-09-11 | unchecked |" in answer
    assert "| JJJ | 1.0 | % | 2026-09-11 | unchecked |" in answer
    assert URL in answer
    assert "verified |" not in answer
    from momentum_research_agent.research_contract import is_holdings_lookup

    for question in (
        "Compare MTUM holdings concentration and reversal risk.",
        "List MTUM holdings and calculate maximum drawdown",
        "Show MTUM holdings and run engine_query",
        "Show MTUM holdings and price",
    ):
        assert not is_holdings_lookup(question)


def test_answer_does_not_present_rejected_numbers_or_unreviewed_summary():
    from momentum_research_agent.state.reports import render_answer_markdown

    report = ResearchReport.model_validate(lookup_report())
    report.summary = "The fabricated total is 200%."
    verification = VerificationReport(
        question="Holdings",
        overall_status="fail",
        summary="One wrong number",
        verdicts=[
            {
                "evidence_id": "AAA",
                "claim": report.findings[0].claim,
                "status": "verified",
                "rechecked_source": URL,
            },
            {
                "evidence_id": "DDD",
                "claim": report.findings[3].claim,
                "status": "verified",
                "notes": "Static audit retained after timeout.",
            },
            {
                "evidence_id": "BBB",
                "claim": report.findings[1].claim,
                "status": "rejected",
                "issues": ["Wrong value"],
                "rechecked_source": URL,
            },
        ],
    )
    answer = render_answer_markdown(report, verification)
    assert "| AAA | 10.0 | % | 2026-09-11 | verified |" in answer
    assert "| BBB | withheld | % | 2026-09-11 | rejected |" in answer
    assert "| CCC | 8.0 | % | 2026-09-11 | unchecked |" in answer
    assert (
        "| DDD | 7.0 | % | 2026-09-11 | unconfirmed (saved status: verified) |"
        in answer
    )
    assert "Wrong value" in answer
    assert "200%" not in answer
    assert "**verified**: AAA has fund weight 10%." in answer
    assert "BBB has fund weight 9%." not in answer
    assert (
        report.metrics[1].value == 9
    )  # Canonical research is preserved for the audit.
