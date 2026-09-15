"""Hand-computed portfolios catch rebalancing, dividend and split double-counting."""

from datetime import date

import pandas as pd
import pytest

from momentum_research_agent import crowding_data as cd
from momentum_research_agent import fixed_basket
from momentum_research_agent.proxy_data import save_json
from test_crowding_metrics import payload

START, END = date(2026, 5, 29), date(2026, 6, 2)


@pytest.fixture
def basket():
    return fixed_basket


def prices():
    # AAA falls ex-dividend, then rises; the dividend stays in cash.
    rows = []
    for symbol, closes, divs in (
        ("AAA", [100, 90, 120], [7, 10, 0]),
        ("BBB", [100, 100, 100], [0, 0, 0]),
        ("MTUM", [100, 100, 110], [0, 0, 0]),
        ("SPY", [100, 100, 100], [0, 0, 0]),
    ):
        for day, close, div in zip(
            pd.to_datetime(["2026-05-29", "2026-06-01", "2026-06-02"]), closes, divs
        ):
            rows.append(
                {
                    "Ticker": symbol,
                    "Date": day,
                    "Close": close,
                    "Adj Close": close,
                    "Dividends": div,
                    "Stock Splits": 0.0,
                    "Volume": 100,
                }
            )
    return pd.DataFrame(rows)


def reference(root, monkeypatch):
    def worker(symbol, destination, timeout):
        save_json(
            destination,
            payload(ticker=symbol, day="Jun 02, 2026", weights=(60, 30, 10)),
        )

    monkeypatch.setattr(cd, "run_worker", worker)
    result = cd.build(root / "crowding", END, None, None)
    path = root / "brief.json"
    save_json(
        path,
        {
            "schema_version": "etf_proxy_brief_v1",
            "calculation_version": "etf_proxy_metrics_v1",
            "requested_as_of": END.isoformat(),
            "crowding": result,
        },
    )
    return path


def recorded(root):
    raw = prices()
    path = root / "recorded.parquet"
    raw.to_parquet(path, index=False)
    return path


def test_offline_run_replays_independent_of_sources_and_ignores_edited_metrics(
    basket, tmp_path, monkeypatch
):
    source = reference(tmp_path / "source", monkeypatch)
    data = recorded(tmp_path)
    out = tmp_path / "run"
    result = basket.run(source, START, out, prices_file=data)
    assert result["portfolio"]["return"] == pytest.approx(0.18)
    assert result["llm_requests"] == 0
    assert basket.replay(out) == result
    source.write_text("changed")
    data.write_text("changed")
    edited = dict(result)
    edited["portfolio"] = {"return": 999}
    save_json(out / "simulation.json", edited)
    assert basket.replay(out) == result
    assert "look-ahead" in (out / "simulation.md").read_text().lower()
    with pytest.raises(FileExistsError):
        basket.run(source, START, out, prices_file=data)
    (out / "prices.parquet").write_text("changed")
    with pytest.raises(ValueError):
        basket.replay(out)
