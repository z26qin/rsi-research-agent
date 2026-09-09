"""Hand-computed portfolios catch rebalancing, dividend and split double-counting."""
from datetime import date
import json
import subprocess
import sys

import numpy as np
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


def fund():
    return {"symbol": "MTUM", "as_of": "2026-06-02", "holdings": [
        {"ticker": "AAA", "exchange": "NASDAQ", "currency": "USD", "name": "A", "sector": "Tech", "weight": .6},
        {"ticker": "BBB", "exchange": "NYSE", "currency": "USD", "name": "B", "sector": "Other", "weight": .3}]}


def prices():
    # AAA falls ex-dividend, then rises; the dividend stays in cash.
    rows = []
    for symbol, closes, divs in (("AAA", [100, 90, 120], [7, 10, 0]),
                                  ("BBB", [100, 100, 100], [0, 0, 0]),
                                  ("MTUM", [100, 100, 110], [0, 0, 0]),
                                  ("SPY", [100, 100, 100], [0, 0, 0])):
        for day, close, div in zip(pd.to_datetime(["2026-05-29", "2026-06-01", "2026-06-02"]), closes, divs):
            rows.append({"Ticker": symbol, "Date": day, "Close": close, "Adj Close": close,
                         "Dividends": div, "Stock Splits": 0., "Volume": 100})
    return pd.DataFrame(rows)


def test_cash_dividends_no_reinvestment_and_drifting_weights(basket):
    r = basket.calculate(fund(), prices(), START, END)
    assert r["status"] == "partial"
    # .006 * 120 + .003 * 100 + .10 initial cash + .006 * 10 dividend = 1.18.
    assert r["portfolio"]["return"] == pytest.approx(.18)
    assert r["path"][-1]["cash"] == pytest.approx(.16)
    assert r["positions"][0]["end_weight"] == pytest.approx(.72 / 1.18)
    assert r["concentration"]["start"]["equity_hhi"] == pytest.approx(.45)
    assert r["concentration"]["end"]["equity_hhi"] == pytest.approx((.72**2 + .3**2) / 1.18**2)
    assert r["relative"]["SPY"] == pytest.approx(.18)
    assert r["relative"]["MTUM"] == pytest.approx(1.18 / 1.1 - 1)
    assert r["portfolio"]["volatility"] == pytest.approx(.18 / np.sqrt(2) * np.sqrt(252))
    assert r["portfolio"]["max_drawdown"] == 0
    assert r["look_ahead_bias"] is True
    assert r["holdings_as_of"] == "2026-06-02"


def test_split_adjusted_close_is_not_split_adjusted_twice(basket):
    raw = prices()
    raw.loc[raw.Ticker == "AAA", "Close"] = [50, 50, 50]
    raw.loc[raw.Ticker == "AAA", "Dividends"] = 0
    raw.loc[(raw.Ticker == "AAA") & (raw.Date == "2026-06-01"), "Stock Splits"] = 2
    r = basket.calculate(fund(), raw, START, END)
    assert r["portfolio"]["return"] == pytest.approx(0)
    assert r["positions"][0]["split_events"] == [{"date": "2026-06-01", "ratio": 2.}]


@pytest.mark.parametrize("ratio", [1.241, 1.5])
def test_complex_or_synthetic_split_requires_review_not_ordinary_share_adjustment(basket, ratio):
    # Yahoo can encode a spin-off as a non-integer split (FDX 2026-06-01).
    # Even a genuine 3-for-2 split needs explicit review under the lightweight policy.
    raw = prices()
    raw.loc[(raw.Ticker == "AAA") & (raw.Date == "2026-06-01"), "Stock Splits"] = ratio
    r = basket.calculate(fund(), raw, START, END)
    assert r["status"] == "unavailable"
    assert r["portfolio"] is None
    assert "corporate action" in r["coverage"]["missing"]["AAA"]


def test_supported_reverse_split_and_start_close_action_do_not_change_units(basket):
    raw = prices()
    raw.loc[(raw.Ticker == "AAA") & (raw.Date == "2026-06-01"), "Stock Splits"] = .5
    raw.loc[(raw.Ticker == "AAA") & (raw.Date == "2026-05-29"), "Stock Splits"] = 1.241
    assert basket.calculate(fund(), raw, START, END)["portfolio"]["return"] == pytest.approx(.18)


@pytest.mark.parametrize("problem", ["missing_symbol", "gap", "duplicate", "negative", "missing_adj", "nan_action", "negative_split"])
def test_bad_constituent_withholds_entire_basket_without_renormalizing(basket, problem):
    raw = prices()
    if problem == "missing_symbol": raw = raw[raw.Ticker != "AAA"]
    if problem == "gap": raw = raw.drop(raw[(raw.Ticker == "AAA") & (raw.Date == "2026-06-01")].index)
    if problem == "duplicate": raw = pd.concat([raw, raw.iloc[[0]]])
    if problem == "negative": raw.loc[0, "Close"] = -1
    if problem == "missing_adj": raw = raw.drop(columns="Adj Close")
    if problem == "nan_action": raw.loc[0, "Dividends"] = np.nan
    if problem == "negative_split": raw.loc[0, "Stock Splits"] = -2
    r = basket.calculate(fund(), raw, START, END)
    assert r["status"] == "unavailable"
    assert r["portfolio"] is None and r["concentration"] is None and not r["path"]
    assert r["coverage"]["missing"]["AAA"]
    assert r["coverage"]["available_equity_weight"] <= .3


def test_missing_benchmark_does_not_invalidate_basket(basket):
    r = basket.calculate(fund(), prices().query('Ticker != "SPY"'), START, END)
    assert r["status"] == "partial"
    assert r["relative"]["SPY"] is None
    assert r["benchmarks"]["SPY"]["status"] == "unavailable"
    assert r["portfolio"]["return"] == pytest.approx(.18)


def test_outside_window_ignored_and_drawdown_not_endpoint_only(basket):
    raw = prices()
    raw.loc[raw.Ticker == "AAA", "Close"] = [100, 50, 100]
    raw.loc[raw.Ticker == "AAA", "Dividends"] = 0
    extra = raw.iloc[[0]].copy(); extra["Date"] = pd.Timestamp("2026-06-03"); extra["Close"] = -1
    r = basket.calculate(fund(), pd.concat([raw, extra]), START, END)
    assert r["portfolio"]["return"] == pytest.approx(0)
    assert r["portfolio"]["max_drawdown"] == pytest.approx(-.3)


@pytest.mark.parametrize("problem", ["duplicate", "overallocated", "currency", "ticker", "date"])
def test_invalid_allocations_reject_instead_of_reweighting(basket, problem):
    f = fund()
    if problem == "duplicate": f["holdings"].append(dict(f["holdings"][0]))
    if problem == "overallocated": f["holdings"][0]["weight"] = .9
    if problem == "currency": f["holdings"][0]["currency"] = "EUR"
    if problem == "ticker": f["holdings"][0]["ticker"] = "UNKNOWN.X"
    if problem == "date": f["as_of"] = "2026-05-28"
    with pytest.raises(ValueError): basket.calculate(f, prices(), START, END)


def reference(root, monkeypatch):
    def worker(symbol, destination, timeout):
        save_json(destination, payload(ticker=symbol, day="Jun 02, 2026", weights=(60, 30, 10)))
    monkeypatch.setattr(cd, "run_worker", worker)
    result = cd.build(root / "crowding", END, None, None)
    path = root / "brief.json"
    save_json(path, {"schema_version": "etf_proxy_brief_v1", "calculation_version": "etf_proxy_metrics_v1",
                     "requested_as_of": END.isoformat(), "crowding": result})
    return path


def recorded(root):
    raw = prices()
    path = root / "recorded.parquet"; raw.to_parquet(path, index=False)
    return path


def test_offline_run_replays_independent_of_sources_and_ignores_edited_metrics(basket, tmp_path, monkeypatch):
    source = reference(tmp_path / "source", monkeypatch)
    data = recorded(tmp_path)
    out = tmp_path / "run"
    result = basket.run(source, START, out, prices_file=data)
    assert result["portfolio"]["return"] == pytest.approx(.18)
    assert result["llm_requests"] == 0
    assert basket.replay(out) == result
    source.write_text("changed")
    data.write_text("changed")
    edited = dict(result); edited["portfolio"] = {"return": 999}
    save_json(out / "simulation.json", edited)
    assert basket.replay(out) == result
    assert "look-ahead" in (out / "simulation.md").read_text().lower()
    with pytest.raises(FileExistsError): basket.run(source, START, out, prices_file=data)
    (out / "prices.parquet").write_text("changed")
    with pytest.raises(ValueError): basket.replay(out)


def test_cli_offline_no_key_and_failure_exit(basket, tmp_path, monkeypatch):
    source = reference(tmp_path / "source", monkeypatch)
    data = recorded(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    command = [sys.executable, "-m", "momentum_research_agent.cli", "--simulate-basket",
               "--basket-brief", str(source), "--start-date", str(START), "--basket-prices", str(data)]
    out = tmp_path / "cli"
    p = subprocess.run(command + ["--session-dir", str(out)], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert json.loads((out / "simulation.json").read_text())["portfolio"]["return"] == pytest.approx(.18)
    raw = pd.read_parquet(data).query('Ticker != "AAA"'); raw.to_parquet(data, index=False)
    failed = subprocess.run(command + ["--session-dir", str(tmp_path / "failed")], capture_output=True, text=True)
    assert failed.returncode == 2
    assert (out / "simulation.json").is_file()


@pytest.mark.parametrize("extra", [[], ["--start-date", "2026-05-29"], ["--daily-brief", "--basket-brief", "x"]])
def test_cli_rejects_incomplete_or_mixed_arguments(basket, extra):
    command = [sys.executable, "-m", "momentum_research_agent.cli"]
    if not extra or extra[0] != "--daily-brief": command.append("--simulate-basket")
    assert subprocess.run(command + extra, capture_output=True).returncode == 2
