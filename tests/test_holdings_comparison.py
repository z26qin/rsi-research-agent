import base64, json
import pytest
from test_crowding_metrics import payload
from momentum_research_agent.tools import read_url
from momentum_research_agent.tools.registry import ToolContext, set_tool_context

BASE = (
    "https://www.ishares.com/us/products/251614/ishares-msci-usa-momentum-factor-etf/"
)


def source(url, day, weights):
    return {
        "url": url,
        "text": "bounded CSV excerpt",
        "body_base64": base64.b64encode(
            payload(day=day, weights=weights)["holdings_csv"].encode()
        ).decode(),
        "content_type": "text/csv",
        "truncated": True,
    }


async def test_official_snapshot_comparison_preserves_dates_and_stock_contributions(
    tmp_path, monkeypatch
):
    async def fetch(url):
        old = "20260903" in url
        data = source(url, "Sep 03, 2026" if old else "Sep 04, 2026", (60, 30, 10))
        weights = (
            [20, 15, 12, 10, 9, 8, 7, 6, 5, 4, 4]
            if old
            else [15, 20, 12, 10, 9, 8, 7, 6, 5, 3, 5]
        )
        text = base64.b64decode(data["body_base64"]).decode().splitlines()[:5]
        for i, weight in enumerate(weights):
            ticker = chr(65 + i) * 3
            sector = "Tech" if i < 2 else "Other"
            text.append(
                f"{ticker},{ticker} NAME,{sector},Equity,100,{weight},100,10,10,United States,NASDAQ,USD,1,USD,-"
            )
        data["body_base64"] = base64.b64encode(
            ("\n".join(text) + "\n\n").encode()
        ).decode()
        return data

    monkeypatch.setattr(read_url, "_fetch", fetch)
    set_tool_context(ToolContext(project_root=tmp_path, session_dir=tmp_path))
    old = json.loads(await read_url.read_url(BASE + "history.csv?asOfDate=20260903"))
    new = json.loads(
        await read_url.read_url(
            BASE + "latest-holdings.csv",
            compare_to_artifact=old["artifact"],
            compare_to_sha256=old["sha256"],
        )
    )
    c = new["holdings_comparison"]
    assert c["from_date"] == "2026-09-03" and c["to_date"] == "2026-09-04"
    assert c["top10_change_pp"] == pytest.approx(1)
    assert (
        c["largest_before"]["ticker"] == "AAA" and c["largest_after"]["ticker"] == "BBB"
    )
    assert sum(
        x["top10_contribution_pp"] for x in c["holdings_changes"]
    ) == pytest.approx(1)
    assert c["sector_change_pp"]["Tech"] == pytest.approx(0)
    contributions = {
        h["ticker"]: h["top10_contribution_pp"] for h in c["holdings_changes"]
    }
    assert contributions["JJJ"] == pytest.approx(-4) and contributions[
        "KKK"
    ] == pytest.approx(5)
    from momentum_research_agent.agents.ledger import record_trace
    from momentum_research_agent.agents.sub_agent import _budget_report
    from momentum_research_agent.models.schemas import Task

    task = Task(
        title="Concentration",
        assignment="Compare concentration",
        profile="momentum_analyst",
    )
    trace = record_trace(
        "read_url",
        {
            "url": BASE + "latest-holdings.csv",
            "compare_to_artifact": old["artifact"],
            "compare_to_sha256": old["sha256"],
        },
        json.dumps(new),
    )
    report = _budget_report(task, [trace], "final timeout", tmp_path)
    assert report.status == "partial"
    assert next(
        m.value for m in report.metrics if m.name == "Top10 change"
    ) == pytest.approx(1)


async def test_historical_date_mismatch_and_tampering_never_become_a_change(
    tmp_path, monkeypatch
):
    async def fetch(url):
        return source(url, "Sep 04, 2026", (60, 30, 10))

    monkeypatch.setattr(read_url, "_fetch", fetch)
    set_tool_context(ToolContext(project_root=tmp_path, session_dir=tmp_path))
    wrong = json.loads(await read_url.read_url(BASE + "history.csv?asOfDate=20260903"))
    assert wrong["holdings_summary"]["status"] == "unavailable"
    current = json.loads(await read_url.read_url(BASE + "latest-holdings.csv"))
    (tmp_path / current["artifact"]).write_text("{}")
    again = json.loads(
        await read_url.read_url(
            BASE + "latest-holdings.csv",
            compare_to_artifact=current["artifact"],
            compare_to_sha256=current["sha256"],
        )
    )
    assert again["holdings_summary"]["status"] == "ok"
    assert again["holdings_comparison"]["status"] == "unavailable"
    assert again["holdings_comparison"]["top10_change_pp"] is None
