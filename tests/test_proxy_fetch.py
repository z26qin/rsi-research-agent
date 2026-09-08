import io
import sys

import pandas as pd
import pytest

from momentum_research_agent import proxy_fetch


def test_etf_fetch_preserves_explicit_adjustment_and_action_settings(monkeypatch):
    import yfinance
    class Ticker:
        def __init__(self, symbol):
            assert symbol == "MTUM"
        def history(self, **kwargs):
            assert kwargs == {"start": "2021-09-04", "end": "2026-09-05", "interval": "1d",
                              "auto_adjust": False, "actions": True, "timeout": 20, "raise_errors": True}
            return pd.DataFrame({"Adj Close": [100], "Close": [105]}, index=pd.DatetimeIndex(["2026-09-04"], name="Date"))
    monkeypatch.setattr(yfinance, "Ticker", Ticker)
    result = proxy_fetch.fetch("MTUM", "2021-09-04", "2026-09-05")
    assert result["Adj Close"].iloc[0] == 100
    assert result["Close"].iloc[0] == 105
    assert "Date" in result


def test_fred_download_and_worker_persistence(tmp_path, monkeypatch):
    def urlopen(request, timeout):
        assert request.full_url == "https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS"
        assert timeout == 20
        return io.BytesIO(b"observation_date,VIXCLS\n2026-09-04,20.5\n")
    monkeypatch.setattr(proxy_fetch.urllib.request, "urlopen", urlopen)
    path = tmp_path / "vix.parquet"
    monkeypatch.setattr(sys, "argv", ["worker", "VIXCLS", "2021-09-04", "2026-09-05", str(path)])
    proxy_fetch.main()
    assert pd.read_parquet(path)["VIXCLS"].iloc[0] == 20.5


def test_unknown_source_and_empty_response_rejected(monkeypatch, tmp_path):
    with pytest.raises(ValueError):
        proxy_fetch.fetch("UNKNOWN", "2021-09-04", "2026-09-05")
    monkeypatch.setattr(proxy_fetch, "fetch", lambda *args: pd.DataFrame())
    monkeypatch.setattr(sys, "argv", ["worker", "MTUM", "2021-09-04", "2026-09-05", str(tmp_path / "x")])
    with pytest.raises(ValueError):
        proxy_fetch.main()
