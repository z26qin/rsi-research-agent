import subprocess
import sys

import pandas as pd
import pytest

from momentum_research_agent import fixed_basket_fetch
from test_fixed_basket import prices, fund, START, END


def module():
    return fixed_basket_fetch


def test_download_preserves_price_action_columns_and_explicit_adjustment(monkeypatch):
    m = module()
    import yfinance
    def download(**kwargs):
        assert kwargs["auto_adjust"] is False and kwargs["actions"] is True
        assert kwargs["timeout"] == 20 and kwargs["threads"] == 8
        assert kwargs["start"] == "2026-05-29" and kwargs["end"] == "2026-06-03"
        assert kwargs["tickers"] == ["AAA", "BBB", "MTUM", "SPY"]
        return pd.concat({s: f.drop(columns="Ticker").set_index("Date") for s, f in prices().groupby("Ticker")}, axis=1)
    monkeypatch.setattr(yfinance, "download", download)
    raw = m.fetch(m.request(["AAA", "BBB", "MTUM", "SPY"], START, END))
    assert len(raw) == 12
    assert raw.loc[(raw.Ticker == "AAA") & (raw.Date == "2026-06-01"), "Dividends"].iloc[0] == 10


def test_retry_retains_attempts_and_does_not_merge_different_vintages(tmp_path, monkeypatch):
    m = module()
    calls = []
    def worker(request, destination, timeout):
        calls.append(destination)
        raw = prices()
        if len(calls) == 1: raw = raw.query('Ticker != "BBB"')
        raw.to_parquet(destination, index=False)
    monkeypatch.setattr(m, "run_worker", worker)
    path, record = m.collect(tmp_path, fund(), START, END)
    assert len(calls) == 2 and all(p.exists() for p in calls)
    assert record["selected_attempt"] == 2
    assert len(pd.read_parquet(path)) == 12
    assert all(e["sha256"] for e in record["attempts"])


def test_download_failure_keeps_diagnostics_and_finishes(tmp_path, monkeypatch):
    m = module()
    def fail(*args): raise subprocess.TimeoutExpired("download", 55)
    monkeypatch.setattr(m, "run_worker", fail)
    path, record = m.collect(tmp_path, fund(), START, END)
    assert len(record["attempts"]) == 2
    assert all(a["error_type"] == "TimeoutExpired" for a in record["attempts"])
    assert pd.read_parquet(path).empty


def test_total_budget_exhaustion_stops_before_next_attempt(tmp_path, monkeypatch):
    m = module()
    ticks = iter([0., 121.])
    monkeypatch.setattr(m.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(m, "run_worker", lambda *a: pytest.fail("budget exhausted"))
    path, record = m.collect(tmp_path, fund(), START, END)
    assert record["deadline_exhausted"] is True
    assert not record["attempts"]


def test_blocking_download_subprocess_is_terminated(tmp_path, monkeypatch):
    m = module()
    monkeypatch.setattr(m, "worker_command", lambda *a: [sys.executable, "-c", "import time; time.sleep(20)"])
    with pytest.raises(subprocess.TimeoutExpired): m.run_worker(tmp_path / "request", tmp_path / "raw", .05)


def test_empty_vendor_response_is_rejected(monkeypatch):
    m = module()
    import yfinance
    monkeypatch.setattr(yfinance, "download", lambda **kwargs: pd.DataFrame())
    with pytest.raises(ValueError): m.fetch(m.request(["AAA"], START, END))


def test_mixed_equity_etf_optional_capital_gains_preserves_presence(monkeypatch):
    m = module()
    from momentum_research_agent.fixed_basket import calculate
    import yfinance
    parts = {s: f.drop(columns="Ticker").set_index("Date") for s, f in prices().groupby("Ticker")}
    for s in ("MTUM", "SPY"): parts[s]["Capital Gains"] = 0.
    monkeypatch.setattr(yfinance, "download", lambda **kwargs: pd.concat(parts, axis=1))
    raw = m.fetch(m.request(list(parts), START, END))
    assert calculate(fund(), raw, START, END)["portfolio"]["return"] == pytest.approx(.18)
    assert raw.loc[raw.Ticker == "AAA", "Capital Gains"].isna().all()
    assert not raw.loc[raw.Ticker == "AAA", "Capital Gains Present"].any()
    # A field that really was supplied but malformed must still be rejected.
    parts["AAA"]["Capital Gains"] = float("nan")
    invalid = m.fetch(m.request(list(parts), START, END))
    assert calculate(fund(), invalid, START, END)["status"] == "unavailable"
    parts["AAA"]["Capital Gains"] = 1.
    invalid = m.fetch(m.request(list(parts), START, END))
    assert calculate(fund(), invalid, START, END)["status"] == "unavailable"
