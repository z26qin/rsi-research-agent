import json
import hashlib
import math
import pandas as pd
import pytest
from test_research_arena import ScriptedClient, response
from momentum_research_agent.tools import market_data
from momentum_research_agent.tools.registry import ToolContext, set_tool_context
from momentum_research_agent.agents.sub_agent import SubAgent
from momentum_research_agent.models.schemas import Task
from momentum_research_agent.errors import AgentDeadlineExceeded


def prices():
    dates = pd.bdate_range("2026-08-14", "2026-09-11").difference(
        pd.DatetimeIndex(["2026-09-07"])
    )
    return pd.DataFrame({"Close": [100.0, 120.0, 90.0] + [110.0] * 17}, index=dates)


async def test_comparison_metrics_use_shared_unrounded_prices_and_archive(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(market_data, "_download", lambda *args: prices())
    set_tool_context(ToolContext(project_root=tmp_path, session_dir=tmp_path))
    result = json.loads(await market_data.market_data("MTUM", benchmark="SPY"))
    assert result["status"] == "ok"
    assert result["price_observations"] == 20
    assert result["return_observations"] == 19
    assert result["metrics"]["MTUM"]["return_pct"] == pytest.approx(10)
    assert result["metrics"]["MTUM"]["max_drawdown_pct"] == pytest.approx(-25)
    returns = [0.2, -0.25, 110 / 90 - 1] + [0.0] * 16
    mean = sum(returns) / 19
    vol = math.sqrt(sum((x - mean) ** 2 for x in returns) / 18) * math.sqrt(252) * 100
    assert result["metrics"]["MTUM"]["volatility_pct"] == pytest.approx(vol)
    raw = (tmp_path / result["artifact"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == result["sha256"]
    assert len(json.loads(raw)["prices"]) == 20
    monkeypatch.setattr(
        market_data,
        "_download",
        lambda symbol, *args: prices().iloc[1:] if symbol == "SPY" else prices(),
    )
    missing = json.loads(await market_data.market_data("MTUM", benchmark="SPY"))
    assert missing["status"] == "unavailable"
    assert "metrics" not in missing


async def test_finalization_timeout_keeps_computed_metrics_with_evidence(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(market_data, "_download", lambda *args: prices())
    client = ScriptedClient(
        [
            response(None, [("market_data", {"ticker": "MTUM", "benchmark": "SPY"})]),
            AgentDeadlineExceeded("collection timed out"),
            AgentDeadlineExceeded("final timed out"),
        ]
    )
    task = Task(
        title="Performance",
        assignment="Compare MTUM and SPY performance",
        profile="momentum_analyst",
    )
    result = await SubAgent(client, "test", tmp_path).run(
        task, ["market_data"], tmp_path
    )
    assert result.report.status == "partial"
    assert len(result.report.metrics) == 6
    assert all(
        m.evidence_id in {e.id for e in result.report.findings}
        for m in result.report.metrics
    )
    assert next(
        m.value for m in result.report.metrics if m.name == "MTUM adjusted-price return"
    ) == pytest.approx(10)
    assert "timed out" in " ".join(result.report.limitations)
    assert result.traces[0].tool == "market_data"

    # An altered archive must not survive as calculated evidence after timeout.
    trace = json.loads(result.traces[0].observation)
    (tmp_path / trace["artifact"]).write_text("{}")
    from momentum_research_agent.agents.sub_agent import _budget_report

    assert not _budget_report(task, result.traces, "timeout", tmp_path).metrics

    from momentum_research_agent.agents.sub_agent import _recover_metric_links

    payload = result.report.model_dump(mode="json")
    payload["status"] = "complete"
    payload["metrics"].append(
        {**payload["metrics"][0], "name": "orphan", "evidence_id": "missing"}
    )
    recovered = _recover_metric_links(json.dumps(payload))
    assert len(recovered.metrics) == 6
    assert recovered.status == "partial"
    assert any("orphan" in gap for gap in recovered.unanswered_questions)
