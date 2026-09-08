from datetime import date
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest

from momentum_research_agent import crowding_history as history
from momentum_research_agent import crowding_data as cd
from momentum_research_agent.brief_readiness import sha256_file
from momentum_research_agent.proxy_data import save_json
from test_crowding_metrics import payload


def imports(root, day="May 29, 2026", weights=(60, 30, 10)):
    root.mkdir()
    funds = {}
    for symbol in ("MTUM", "QUAL", "IVV"):
        path = root / f"{symbol}.csv"
        path.write_text(payload(ticker=symbol, day=day, weights=weights)["holdings_csv"])
        funds[symbol] = {"holdings_file": path.name, "sha256": sha256_file(path),
                         "source_url": cd.product_url(symbol), "retrieved_at": "2026-09-08T12:00:00+00:00"}
    path = root / "import.json"
    save_json(path, {"schema_version": "issuer_file_import_v1", "as_of": "2026-05-29", "funds": funds})
    return path


def newer(root, monkeypatch):
    def worker(symbol, destination, timeout):
        save_json(destination, payload(ticker=symbol, weights=(40, 40, 20)))
    monkeypatch.setattr(cd, "run_worker", worker)
    result = cd.build(root / "crowding", date(2026, 9, 4), None, None)
    path = root / "brief.json"
    save_json(path, {"schema_version": "etf_proxy_brief_v1", "calculation_version": "etf_proxy_metrics_v1",
                     "requested_as_of": "2026-09-04", "crowding": result})
    return path


def test_import_compare_and_self_contained_replay(tmp_path, monkeypatch):
    source = imports(tmp_path / "imports")
    reference = newer(tmp_path / "newer", monkeypatch)
    monkeypatch.setattr(history, "run_worker", lambda *a: pytest.fail("import must stay offline"))
    out = tmp_path / "backfill"
    result = history.run(date(2026, 5, 29), out, source, reference)
    assert result["status"] == "partial"
    c = result["comparison"]
    assert c["status"] == "partial"
    assert c["funds"]["MTUM"]["top10_weight"]["delta"] == pytest.approx(-.1)
    assert c["funds"]["MTUM"]["equity_hhi"]["delta"] == pytest.approx(-.13)
    assert c["funds"]["MTUM"]["sector_weights"]["Tech"]["delta"] == pytest.approx(-.1)
    assert c["overlaps"]["MTUM/QUAL"]["weighted_overlap"]["delta"] == pytest.approx(-.1)
    assert "flow" not in c["funds"]["MTUM"]
    assert history.replay(out) == result
    reference.write_text("changed after copy")
    source.write_text("changed after import")
    assert history.replay(out) == result
    assert "No flow inference" in (out / "backfill.md").read_text()


@pytest.mark.parametrize("day", ["Sep 04, 2026", "May 28, 2026"])
def test_import_requires_exact_date_not_older_or_newer(tmp_path, day):
    result = history.run(date(2026, 5, 29), tmp_path / "out", imports(tmp_path / "imports", day=day), None)
    assert result["status"] == "unavailable"
    assert result["comparison"]["status"] == "unavailable"


@pytest.mark.parametrize("change", ["hash", "escape", "source", "timestamp", "version", "target"])
def test_import_rejects_bad_provenance(tmp_path, change):
    source = imports(tmp_path / "imports")
    obj = json.loads(source.read_text())
    for entry in obj["funds"].values():
        if change == "hash": entry["sha256"] = "0" * 64
        if change == "escape": entry["holdings_file"] = "../outside.csv"
        if change == "source": entry["source_url"] = "https://not-the-issuer.example"
        if change == "timestamp": entry["retrieved_at"] = "yesterday"
    if change == "version": obj["schema_version"] = "other"
    if change == "target": obj["as_of"] = "2026-05-28"
    save_json(source, obj)
    assert history.run(date(2026, 5, 29), tmp_path / "out", source, None)["status"] == "unavailable"


def test_bad_download_preserved_and_retried_without_latest_fallback(tmp_path, monkeypatch):
    calls = []
    def worker(symbol, target, path, timeout):
        calls.append((symbol, target))
        save_json(path, {"holdings_csv": "<html>not historical data</html>"})
    monkeypatch.setattr(history, "run_worker", worker)
    out = tmp_path / "out"
    assert history.run(date(2026, 5, 29), out, None, None)["status"] == "unavailable"
    assert len(calls) == 6
    assert all(t == date(2026, 5, 29) for _, t in calls)
    assert (out / "crowding/vendor/MTUM-1.json").is_file()
    assert len(json.loads((out / "crowding/manifest.json").read_text())["attempts"]) == 6


def test_successful_download_records_actual_historical_request(tmp_path, monkeypatch):
    def worker(symbol, target, path, timeout): save_json(path, payload(ticker=symbol, day="May 29, 2026"))
    monkeypatch.setattr(history, "run_worker", worker)
    out = tmp_path / "out"
    assert history.run(date(2026, 5, 29), out, None, None)["status"] == "partial"
    manifest = json.loads((out / "crowding/manifest.json").read_text())
    assert "asOfDate=20260529" in manifest["sources"]["MTUM"]["holdings_url"]
    assert history.replay(out)["crowding"]["funds"]["MTUM"]["as_of"] == "2026-05-29"


def test_tampered_current_or_wrong_version_withholds_comparison(tmp_path, monkeypatch):
    source = imports(tmp_path / "imports")
    reference = newer(tmp_path / "newer", monkeypatch)
    (reference.parent / "crowding/vendor/MTUM-1.json").write_text("changed")
    result = history.run(date(2026, 5, 29), tmp_path / "out", source, reference)
    assert result["comparison"]["status"] == "unavailable"
    assert result["status"] == "partial"
    obj = json.loads(reference.read_text()); obj["schema_version"] = "engine"
    save_json(reference, obj)
    assert history.run(date(2026, 5, 29), tmp_path / "out2", source, reference)["comparison"]["status"] == "unavailable"


def test_replay_rejects_tampered_manifest_and_preserves_existing_directory(tmp_path):
    source = imports(tmp_path / "imports")
    out = tmp_path / "out"
    history.run(date(2026, 5, 29), out, source, None)
    original = (out / "backfill.json").read_bytes()
    with pytest.raises(FileExistsError): history.run(date(2026, 5, 29), out, source, None)
    assert (out / "backfill.json").read_bytes() == original
    (out / "crowding/manifest.json").write_text("changed")
    with pytest.raises(ValueError): history.replay(out)


def test_replay_discards_invented_comparison_without_reference(tmp_path):
    source = imports(tmp_path / "imports")
    out = tmp_path / "out"
    original = history.run(date(2026, 5, 29), out, source, None)
    edited = json.loads((out / "backfill.json").read_text())
    edited["comparison"] = {"status": "partial", "funds": {"MTUM": {"top10_weight": {"delta": 999}}}}
    save_json(out / "backfill.json", edited)
    assert history.replay(out)["comparison"] == original["comparison"]


def test_fetch_preserves_response_and_request_date_without_nav(monkeypatch):
    class Response(io.BytesIO):
        status = 200
        headers = {"Content-Type": "text/csv"}
    def get(request, timeout):
        assert request.full_url.endswith("asOfDate=20260529")
        assert timeout == 20
        return Response(b"issuer CSV body")
    monkeypatch.setattr(history.urllib.request, "urlopen", get)
    raw = history.fetch("MTUM", date(2026, 5, 29))
    assert raw["holdings_csv"] == "issuer CSV body"
    assert raw["http_status"] == 200
    assert "product_html" not in raw


def test_history_worker_timeout_and_url_date(monkeypatch, tmp_path):
    assert "asOfDate=20260529" in history.historical_url("MTUM", date(2026, 5, 29))
    monkeypatch.setattr(history, "worker_command", lambda *a: [sys.executable, "-c", "import time; time.sleep(20)"])
    with pytest.raises(subprocess.TimeoutExpired): history.run_worker("MTUM", date(2026, 5, 29), tmp_path / "x", .05)


def test_no_download_after_total_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "TOTAL_TIMEOUT", 0.)
    monkeypatch.setattr(history, "run_worker", lambda *a: pytest.fail("budget exhausted"))
    assert history.run(date(2026, 5, 29), tmp_path / "out", None, None)["status"] == "unavailable"


@pytest.mark.asyncio
async def test_cli_backfill_requires_date_and_can_import_without_key(tmp_path, monkeypatch):
    from momentum_research_agent import cli
    monkeypatch.setattr(cli, "make_client", lambda: pytest.fail("No LLM client"))
    source = imports(tmp_path / "imports")
    args = cli.build_parser().parse_args(["--backfill-crowding", "--as-of", "2026-05-29", "--issuer-files", str(source), "--session-dir", str(tmp_path / "out")])
    assert await cli.async_main(args) == 0
    assert (tmp_path / "out/backfill.md").is_file()
    assert await cli.async_main(cli.build_parser().parse_args(["--backfill-crowding"])) == 2
    assert await cli.async_main(cli.build_parser().parse_args(["question", "--issuer-files", str(source)])) == 2
