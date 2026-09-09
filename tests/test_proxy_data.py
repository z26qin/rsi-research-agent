from datetime import date
import json
import subprocess
import sys

import pandas as pd

from momentum_research_agent import proxy_data as data


def vendor():
    return pd.DataFrame({"Date": ["2026-09-04"], "Close": [110.], "Adj Close": [100.],
                         "Volume": [1000], "Dividends": [0.], "Stock Splits": [0.]})


def test_collect_retains_vendor_and_normalized_tables(tmp_path, monkeypatch):
    def worker(source, start, end, destination, **kwargs):
        frame = vendor() if source != "VIXCLS" else pd.DataFrame({"observation_date": ["2026-09-03"], "VIXCLS": [20.]})
        frame.to_parquet(destination, index=False)
        return subprocess.CompletedProcess([], 0)
    monkeypatch.setattr(data, "run_worker", worker)
    manifest = data.collect(tmp_path, date(2026, 9, 4))
    assert manifest["sources"]["MTUM"]["status"] == "ok"
    assert manifest["sources"]["VIXCLS"]["latest_date"] == "2026-09-03"
    assert len(manifest["attempts"]) == 3
    entry = manifest["sources"]["SPY"]
    assert pd.read_parquet(tmp_path / entry["vendor_path"])["Close"].iloc[0] == 110
    assert pd.read_parquet(tmp_path / entry["normalized_path"])["adj_close"].iloc[0] == 100
    assert len(entry["normalized_sha256"]) == 64
    assert json.loads((tmp_path / "manifest.json").read_text())["target_date"] == "2026-09-04"


def test_failed_sources_get_only_two_attempts_without_secret_errors(tmp_path, monkeypatch):
    def worker(*args, **kwargs):
        raise RuntimeError("credential-secret")
    monkeypatch.setattr(data, "run_worker", worker)
    manifest = data.collect(tmp_path, date(2026, 9, 4))
    assert len(manifest["attempts"]) == 6
    assert all(item["status"] == "unavailable" for item in manifest["sources"].values())
    assert "credential-secret" not in (tmp_path / "manifest.json").read_text()


def test_timeout_kills_real_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "ATTEMPT_TIMEOUT", .1)
    monkeypatch.setattr(data, "worker_command", lambda *args:
                        [sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        data.run_worker("MTUM", "2021-09-04", "2026-09-05", tmp_path / "out.parquet")
    except subprocess.TimeoutExpired as exc:
        assert exc.timeout <= .1
    else:
        assert False, "blocked worker must be terminated"


def test_empty_vendor_tables_fail_closed(tmp_path, monkeypatch):
    def worker(source, start, end, destination, **kwargs):
        pd.DataFrame().to_parquet(destination)
    monkeypatch.setattr(data, "run_worker", worker)
    manifest = data.collect(tmp_path, date(2026, 9, 4))
    assert all(item["status"] == "unavailable" for item in manifest["sources"].values())


def test_total_deadline_stops_additional_sources(tmp_path, monkeypatch):
    ticks = iter([0., 121., 122., 123.])
    monkeypatch.setattr(data.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(data, "run_worker", lambda *args: (_ for _ in ()).throw(AssertionError("must not start")))
    manifest = data.collect(tmp_path, date(2026, 9, 4))
    assert not manifest["attempts"]
    assert all(item["status"] == "unavailable" for item in manifest["sources"].values())


def test_successful_retry_clears_source_error_but_keeps_attempt_history(tmp_path, monkeypatch):
    attempts = []
    def worker(source, start, end, destination, **kwargs):
        attempts.append(source)
        if len(attempts) == 1:
            raise RuntimeError("rate limited")
        (vendor() if source != "VIXCLS" else pd.DataFrame({"DATE": ["2026-09-04"], "VALUE": [20.]})).to_parquet(destination)
    monkeypatch.setattr(data, "run_worker", worker)
    manifest = data.collect(tmp_path, date(2026, 9, 4))
    assert manifest["sources"]["MTUM"]["status"] == "ok"
    assert "error" not in manifest["sources"]["MTUM"]
    assert manifest["attempts"][0]["status"] == "failed"
