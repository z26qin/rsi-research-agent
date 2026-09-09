from datetime import date
import json
import subprocess
import sys

import pandas as pd
import pytest

from momentum_research_agent import crowding_data as cd
from momentum_research_agent.proxy_data import save_json
from test_crowding_metrics import payload


@pytest.fixture
def worker(monkeypatch):
    def run(symbol, destination, timeout):
        save_json(destination, payload(ticker=symbol))
    monkeypatch.setattr(cd, "run_worker", run)


def test_collection_replay_hashes_and_three_fund_overlap(worker, tmp_path):
    result = cd.build(tmp_path / "crowding", date(2026, 9, 4), None, None)
    assert result["status"] == "partial"
    assert result["funds"]["MTUM"]["concentration"]["equity_hhi"] == pytest.approx(.45)
    assert result["overlaps"]["MTUM/QUAL"]["weighted_overlap"] == pytest.approx(.9)
    assert result["flow"]["status"] == "unavailable"
    assert cd.replay(tmp_path / "crowding", None) == result
    (tmp_path / "crowding/vendor/MTUM-1.json").write_text("changed")
    assert cd.replay(tmp_path / "crowding", None)["funds"]["MTUM"]["status"] == "unavailable"


def test_failure_retries_are_bounded_and_dont_overwrite(worker, tmp_path, monkeypatch):
    output = tmp_path / "crowding"
    cd.build(output, date(2026, 9, 4), None, None)
    original = (output / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError): cd.build(output, date(2026, 9, 4), None, None)
    assert (output / "manifest.json").read_bytes() == original
    def bad(*args, **kwargs): raise subprocess.TimeoutExpired("worker", 20)
    monkeypatch.setattr(cd, "run_worker", bad)
    failed = tmp_path / "failed"
    result = cd.build(failed, date(2026, 9, 4), None, None)
    assert result["status"] == "unavailable"
    manifest = json.loads((failed / "manifest.json").read_text())
    assert len(manifest["attempts"]) == 6
    assert all(a["status"] == "failed" for a in manifest["attempts"])


def test_future_issuer_snapshots_not_backfilled(worker, tmp_path):
    result = cd.build(tmp_path / "crowding", date(2026, 9, 3), None, None)
    assert result["funds"]["MTUM"]["status"] == "unavailable"


def test_saved_prior_inputs_make_flow_offline_reproducible(worker, tmp_path, monkeypatch):
    def prior(symbol, destination, timeout): save_json(destination, payload(ticker=symbol, day="Sep 03, 2026", shares=90))
    monkeypatch.setattr(cd, "run_worker", prior)
    prior_root = tmp_path / "prior"
    older = cd.build(prior_root / "crowding", date(2026, 9, 3), None, None)
    prior_brief = {"schema_version": "etf_proxy_brief_v1", "calculation_version": "etf_proxy_metrics_v1", "crowding": older}
    save_json(prior_root / "brief.json", prior_brief)
    def current(symbol, destination, timeout): save_json(destination, payload(ticker=symbol))
    monkeypatch.setattr(cd, "run_worker", current)
    prices = pd.DataFrame({"date": pd.to_datetime(["2026-09-04"]), "stock_splits": [0.]})
    output = tmp_path / "current/crowding"
    result = cd.build(output, date(2026, 9, 4), prior_root / "brief.json", prices)
    assert result["flow"]["estimated_net_creation_usd"] == 100
    (prior_root / "crowding/vendor/MTUM-1.json").write_text("tampered after import")
    assert cd.replay(output, prices) == result
    rejected = cd.build(tmp_path / "rejected", date(2026, 9, 4), prior_root / "brief.json", prices)
    assert rejected["flow"]["status"] == "unavailable"


def test_worker_timeout_kills_child(tmp_path, monkeypatch):
    monkeypatch.setattr(cd, "worker_command", lambda *args: [sys.executable, "-c", "import time; time.sleep(20)"])
    with pytest.raises(subprocess.TimeoutExpired): cd.run_worker("MTUM", tmp_path / "x", .05)


def test_collection_deadline_prevents_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(cd, "TOTAL_TIMEOUT", 0.)
    monkeypatch.setattr(cd, "run_worker", lambda *args: pytest.fail("deadline must stop download"))
    result = cd.build(tmp_path / "crowding", date(2026, 9, 4), None, None)
    assert result["status"] == "unavailable"


def test_worker_fetches_only_fixed_issuer_urls_and_keeps_optional_page_failure(monkeypatch):
    import io
    calls = []
    def get(request, timeout):
        calls.append(request.full_url)
        assert timeout == 20
        if request.full_url.endswith(".csv"): return io.BytesIO(b"issuer holdings")
        raise OSError("page temporarily down")
    monkeypatch.setattr(cd.urllib.request, "urlopen", get)
    result = cd.fetch("MTUM")
    assert result["holdings_csv"] == "issuer holdings"
    assert result["page_error"] == "OSError"
    with pytest.raises(ValueError): cd.fetch("https://untrusted.example")
    assert len(calls) == 2


def test_hung_optional_page_preserves_checkpointed_holdings(tmp_path, monkeypatch):
    def hung(symbol, destination, timeout):
        raw = payload(ticker=symbol)
        raw.pop("product_html")
        save_json(destination, raw)
        raise subprocess.TimeoutExpired("worker", 20)
    monkeypatch.setattr(cd, "run_worker", hung)
    result = cd.build(tmp_path / "crowding", date(2026, 9, 4), None, None)
    assert result["status"] == "partial"
    assert result["funds"]["MTUM"]["nav"] is None
    assert result["funds"]["MTUM"]["concentration"]["top10_weight"] == pytest.approx(.9)


def test_fetch_checkpoints_holdings_before_optional_page(tmp_path, monkeypatch):
    import io
    target = tmp_path / "raw.json"
    def get(request, timeout):
        if request.full_url.endswith(".csv"): return io.BytesIO(b"holdings body")
        assert json.loads(target.read_text())["holdings_csv"] == "holdings body"
        return io.BytesIO(b"issuer page")
    monkeypatch.setattr(cd.urllib.request, "urlopen", get)
    assert cd.fetch("MTUM", target)["product_html"] == "issuer page"
