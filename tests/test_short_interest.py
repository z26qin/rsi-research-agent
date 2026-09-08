"""Publication cutoff, complete-basket coverage, and offline evidence integrity."""
from datetime import date
import hashlib
import json
import subprocess
import time

import pytest

from momentum_research_agent import short_interest as si

TARGET = date(2026, 9, 4)
REFERENCE = date(2026, 5, 29)
HOLDINGS = [dict(ticker="AMD", weight=.3, exchange="NASDAQ", currency="USD", name="AMD"),
            dict(ticker="MU", weight=.2, exchange="NASDAQ", currency="USD", name="Micron")]
HEADER = "accountingYearMonthNumber|symbolCode|issueName|issuerServicesGroupExchangeCode|marketClassCode|currentShortPositionQuantity|previousShortPositionQuantity|stockSplitFlag|averageDailyVolumeQuantity|daysToCoverQuantity|revisionFlag|changePercent|changePreviousNumber|settlementDate\n"


def schedule(rows=None):
    rows = rows or [("May 29", "June 9"), ("July 31", "August 11"),
                    ("August 14", "August 25"), ("August 31", "September 10")]
    body = "".join(f'<tr><td data-th="Settlement Date"><strong>{s}</strong><br>(Friday)</td><td>June 2 – 6:00 p.m.</td><td data-th="Exchange Receipt Date"><strong>{p}</strong><br>(Tuesday)</td></tr>' for s, p in rows)
    return ('<h2>2026&nbsp;Short Interest Reporting Dates</h2><table class="table"><thead><tr><th>Settlement Date</th><th>Due Date<sup>1</sup></th><th>Publication Date</th></tr></thead><tbody>' + body + '</tbody></table>').encode()


def data(day, missing=(), bad=None):
    rows = []
    for symbol, shares, adv, dtc in [("MTUM", 1273798, 1366379, 1.00), ("SPY", 10000, 5000, 2),
                                     ("AMD", 40065798, 26911002, 1.49), ("MU", 30016025, 33755659, 1)]:
        if symbol in missing:
            continue
        cells = [day.replace("-", ""), symbol, symbol + " Company", "R", "NNM", str(shares), "100", "", str(adv), str(dtc), "", "1", "1", day]
        if bad and symbol == "AMD":
            cells[bad[0]] = bad[1]
        rows.append("|".join(cells))
    return (HEADER + "\n".join(rows) + "\n").encode()


@pytest.fixture
def network(monkeypatch):
    calls = []
    def fetch(url, timeout):
        calls.append((url, timeout))
        if url == si.SCHEDULE_URL:
            return schedule()
        day = url.rsplit("shrt", 1)[1][:8]
        assert day != "20260831", "Unpublished data requested"
        return data(f"{day[:4]}-{day[4:6]}-{day[6:]}")
    monkeypatch.setattr(si, "_attempt", fetch)
    return calls


def test_published_periods_and_preserved_dtc_replay(tmp_path, network):
    root = tmp_path / "evidence"
    result = si.build(root, TARGET, REFERENCE, HOLDINGS)
    assert result["status"] == "complete"
    assert result["latest_settlement"] == "2026-08-14"
    assert result["latest_publication"] == "2026-08-25"
    assert result["periods"]["previous"]["settlement_date"] == "2026-07-31"
    assert result["periods"]["reference"]["publication_date"] == "2026-06-09"
    assert result["periods"]["latest"]["records"]["MTUM"]["days_to_cover"] == 1
    assert result["basket"]["weighted_days_to_cover"]["latest"] == pytest.approx(1.294)
    assert result["basket"]["covered_count"] == 2
    assert result["basket"]["total_weight"] == .5
    assert len(network) == 4
    assert si.replay(root) == result
    with pytest.raises(FileExistsError):
        si.build(root, TARGET, REFERENCE, HOLDINGS)


def test_missing_constituent_never_reweights(tmp_path, monkeypatch, network):
    monkeypatch.setattr(si, "_attempt", lambda url, timeout: schedule() if url == si.SCHEDULE_URL else data("2026-08-14", missing=("MU",)))
    result = si.build(tmp_path / "e", TARGET, None, HOLDINGS)
    assert result["status"] == "partial"
    assert result["basket"]["covered_weight"] == .3
    assert result["basket"]["weighted_days_to_cover"]["latest"] is None
    assert result["periods"]["latest"]["missing"] == ["MU"]


@pytest.mark.parametrize("reference", [date(2026, 8, 31), date(2026, 5, 28)])
def test_exact_unpublished_or_unscheduled_reference_is_unavailable(tmp_path, network, reference):
    result = si.build(tmp_path / "e", TARGET, reference, HOLDINGS)
    assert result["periods"]["reference"] is None
    assert result["status"] == "partial"
    assert len(network) == 3


def test_reference_matching_latest_fetched_once(tmp_path, network):
    result = si.build(tmp_path / "e", TARGET, date(2026, 8, 14), HOLDINGS)
    assert result["periods"]["reference"] == result["periods"]["latest"]
    assert len(network) == 3


def test_schedule_failure_is_replayable_unavailable_and_retries_bounded(tmp_path, monkeypatch):
    calls = []
    def failing(url, timeout):
        calls.append(timeout)
        raise TimeoutError("should not expose credential-like arbitrary exception messages")
    monkeypatch.setattr(si, "_attempt", failing)
    root = tmp_path / "e"
    result = si.build(root, TARGET, REFERENCE, HOLDINGS)
    assert result["status"] == "unavailable"
    assert len(calls) == 2 and all(0 < t <= 20 for t in calls)
    assert si.replay(root) == result
    assert "credential-like" not in json.dumps(result)


def test_failed_latest_does_not_fallback_to_previous(tmp_path, monkeypatch):
    def fetch(url, timeout):
        if url == si.SCHEDULE_URL:
            return schedule()
        if "20260814" in url:
            raise OSError("failure")
        return data("2026-07-31")
    monkeypatch.setattr(si, "_attempt", fetch)
    result = si.build(tmp_path / "e", TARGET, None, HOLDINGS)
    assert result["status"] == "unavailable"
    assert result["latest_settlement"] == "2026-08-14"
    assert result["periods"]["latest"]["records"] == {}
    assert result["periods"]["previous"]["records"]["AMD"]["short_shares"] == 40065798


@pytest.mark.parametrize("bad", [(5, "-1"), (5, "1.5"), (8, "nan"), (9, "inf"), (9, "-1"), (13, "2026-08-31"), (0, "20260831")])
def test_invalid_record_is_missing_without_discarding_other_symbols(bad):
    records, missing = si.parse_records(data("2026-08-14", bad=bad), date(2026, 8, 14), ["AMD", "MU"])
    assert "AMD" not in records and missing == ["AMD"]
    assert records["MU"]["short_shares"] == 30016025


def test_duplicate_record_is_ambiguous():
    raw = data("2026-08-14")
    duplicate = next(r for r in raw.splitlines() if b"|AMD|" in r)
    records, missing = si.parse_records(raw + duplicate + b"\n", date(2026, 8, 14), ["AMD", "MU"])
    assert "AMD" not in records and missing == ["AMD"]


def test_schedule_year_rollover_and_missing_headers():
    rows = si.parse_schedule(schedule([("December 31", "January 12")]))
    assert rows == [{"settlement_date": "2026-12-31", "publication_date": "2027-01-12"}]
    with pytest.raises(ValueError):
        si.parse_schedule(b"<html>blocked</html>")
    with pytest.raises(ValueError):
        si.parse_schedule(schedule([("May 29", "June 9"), ("May 29", "June 10")]))


def test_no_published_rows_does_not_request_files(tmp_path, network):
    result = si.build(tmp_path / "e", date(2026, 5, 29), None, HOLDINGS)
    assert result["status"] == "unavailable" and len(network) == 1


@pytest.mark.parametrize("artifact", ["manifest.json", "normalized.json", "raw/schedule.html", "raw/20260814.csv"])
def test_tampered_evidence_rejected(tmp_path, network, artifact):
    root = tmp_path / "e"
    si.build(root, TARGET, REFERENCE, HOLDINGS)
    path = root / artifact
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        si.replay(root)


def test_editable_result_metrics_ignored(tmp_path, network):
    root = tmp_path / "e"
    expected = si.build(root, TARGET, REFERENCE, HOLDINGS)
    path = root / "short_interest.json"
    result = json.loads(path.read_text())
    result["basket"]["weighted_days_to_cover"]["latest"] = 999
    path.write_text(json.dumps(result))
    assert si.replay(root) == expected


def test_evidence_symlink_rejected(tmp_path, network):
    root = tmp_path / "e"
    si.build(root, TARGET, None, HOLDINGS)
    path = root / "raw/schedule.html"
    external = tmp_path / "external"
    path.rename(external)
    path.symlink_to(external)
    with pytest.raises(ValueError):
        si.replay(root)


def test_untrusted_manifest_url_cannot_trigger_network(tmp_path, network, monkeypatch):
    root = tmp_path / "e"
    si.build(root, TARGET, None, HOLDINGS)
    path = root / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["sources"]["schedule"]["url"] = "https://evil.invalid/steal"
    path.write_text(json.dumps(manifest))
    result_path = root / "short_interest.json"
    result = json.loads(result_path.read_text())
    result["manifest_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    result_path.write_text(json.dumps(result))
    monkeypatch.setattr(si, "_attempt", lambda *a: pytest.fail("replay used network"))
    with pytest.raises(ValueError):
        si.replay(root)


def test_worker_timeout_and_body_limit(monkeypatch):
    def timeout(*args, **kwargs):
        assert kwargs["timeout"] <= 20
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        si._attempt(si.SCHEDULE_URL, .01)
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, b"a" * (si.MAX_BYTES + 1), b""))
    with pytest.raises(ValueError):
        si._attempt(si.SCHEDULE_URL, 20)


def test_overall_deadline_stops_new_requests(tmp_path, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(si.time, "monotonic", lambda: clock[0])
    calls = []
    def fetch(url, timeout):
        calls.append(url)
        clock[0] += 121
        raise TimeoutError()
    monkeypatch.setattr(si, "_attempt", fetch)
    result = si.build(tmp_path / "e", TARGET, None, HOLDINGS)
    assert result["status"] == "unavailable" and len(calls) == 1


@pytest.mark.parametrize("holdings", [[HOLDINGS[0], HOLDINGS[0]], [dict(HOLDINGS[0], weight=float("nan"))], [dict(HOLDINGS[0], ticker="../bad")]])
def test_invalid_allocations_rejected_before_network(tmp_path, network, holdings):
    with pytest.raises(ValueError):
        si.build(tmp_path / "e", TARGET, None, holdings)
    assert not network


def test_system_parent_alias_does_not_reject_safe_snapshot(tmp_path, network):
    parent = tmp_path / "real"
    parent.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(parent, target_is_directory=True)
    result = si.build(alias / "nested/snapshot", TARGET, None, HOLDINGS)
    assert si.replay(alias / "nested/snapshot") == result


def test_transient_failure_then_success_records_both_attempts(tmp_path, monkeypatch, network):
    delegate = si._attempt
    first = [True]
    def retry(url, timeout):
        if first[0]:
            first[0] = False
            raise OSError("transient")
        return delegate(url, timeout)
    monkeypatch.setattr(si, "_attempt", retry)
    root = tmp_path / "e"
    result = si.build(root, TARGET, None, HOLDINGS)
    assert result["status"] == "complete"
    manifest = json.loads((root / "manifest.json").read_text())
    assert len(manifest["sources"]["schedule"]["attempts"]) == 2
    assert "error" not in manifest["sources"]["schedule"]


def test_actual_worker_is_killed_on_timeout(monkeypatch):
    monkeypatch.setattr(si, "_WORKER", "import time; time.sleep(10)")
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        si._attempt(si.SCHEDULE_URL, .05)
    assert time.monotonic() - start < 2


@pytest.mark.parametrize("body", [b"<html>temporarily unavailable</html>", b"\xff"])
def test_malformed_schedule_is_preserved_and_replayed_as_unavailable(tmp_path, monkeypatch, body):
    monkeypatch.setattr(si, "_attempt", lambda *args: body)
    root = tmp_path / "e"
    result = si.build(root, TARGET, None, HOLDINGS)
    assert result["status"] == "unavailable"
    assert (root / "raw/schedule.html").read_bytes() == body
    assert si.replay(root) == result


def test_malformed_short_file_does_not_produce_zero_position(tmp_path, monkeypatch):
    monkeypatch.setattr(si, "_attempt", lambda url, timeout: schedule() if url == si.SCHEDULE_URL else b"ticker|shortSaleVolume\nAMD|12345\n")
    root = tmp_path / "e"
    result = si.build(root, TARGET, None, HOLDINGS)
    assert result["status"] == "unavailable"
    assert result["periods"]["latest"]["records"] == {}
    assert result["basket"]["weighted_days_to_cover"]["latest"] is None
    assert si.replay(root) == result


def reseal_manifest(root, manifest):
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest))
    result_path = root / "short_interest.json"
    result = json.loads(result_path.read_text())
    result["manifest_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    result_path.write_text(json.dumps(result))


@pytest.mark.parametrize("mutation", ["missing", "version", "path", "extra", "normalized"])
def test_resealed_malformed_manifest_or_fabricated_normalization_rejected(tmp_path, network, mutation):
    root = tmp_path / "e"
    si.build(root, TARGET, None, HOLDINGS)
    manifest = json.loads((root / "manifest.json").read_text())
    if mutation == "missing":
        del manifest["target_date"]
    elif mutation == "version":
        manifest["version"] = "unsupported"
    elif mutation == "path":
        manifest["sources"]["2026-08-14"]["file"] = "../secret.csv"
    elif mutation == "extra":
        manifest["sources"]["2026-08-31"] = {}
    else:
        path = root / "normalized.json"
        raw = path.read_bytes().replace(b"40065798", b"99999999")
        path.write_bytes(raw)
        manifest["normalized_sha256"] = hashlib.sha256(raw).hexdigest()
    reseal_manifest(root, manifest)
    with pytest.raises(ValueError):
        si.replay(root)


def test_null_hash_cannot_disable_snapshot_verification(tmp_path, network):
    root = tmp_path / "e"
    si.build(root, TARGET, None, HOLDINGS)
    path = root / "short_interest.json"
    result = json.loads(path.read_text())
    result["manifest_sha256"] = None
    path.write_text(json.dumps(result))
    with pytest.raises(ValueError):
        si.replay(root)


@pytest.mark.parametrize("symbol, fragment", [("MTUM", b"|1366379|1.0|"), ("AMD", b"|26911002|1.49|")])
def test_zero_adv_keeps_position_and_published_sentinel_but_dtc_is_unavailable(symbol, fragment):
    # Actual FINRA file shape: zero ADV is accompanied by published 999.99.
    raw = data("2026-08-14").replace(fragment, b"|0|999.99|")
    records, missing = si.parse_records(raw, date(2026, 8, 14), [symbol])
    assert missing == []
    assert records[symbol]["short_shares"] > 0
    assert records[symbol]["average_daily_volume"] == 0
    assert records[symbol]["published_days_to_cover"] == 999.99
    assert records[symbol]["days_to_cover"] is None


@pytest.mark.parametrize("symbol, fragment", [("MTUM", b"|1366379|1.0|"), ("AMD", b"|26911002|1.49|")])
def test_zero_adv_snapshot_replay_and_basket_coverage(tmp_path, monkeypatch, symbol, fragment):
    def fetch(url, timeout):
        if url == si.SCHEDULE_URL:
            return schedule()
        stamp = url.rsplit("shrt", 1)[1][:8]
        day = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
        raw = data(day)
        return raw.replace(fragment, b"|0|999.99|") if day == "2026-08-14" else raw
    monkeypatch.setattr(si, "_attempt", fetch)
    root = tmp_path / "e"
    result = si.build(root, TARGET, REFERENCE, HOLDINGS)
    assert result["status"] == "partial"
    assert result["periods"]["latest"]["records"][symbol]["days_to_cover"] is None
    assert result["periods"]["latest"]["missing"] == []
    assert result["basket"]["covered_count"] == 2
    assert result["basket"]["covered_weight"] == .5
    latest_mean = result["basket"]["weighted_days_to_cover"]["latest"]
    if symbol == "AMD":
        assert latest_mean is None
    else:
        assert latest_mean == pytest.approx(1.294)
    assert result["basket"]["weighted_days_to_cover"]["previous"] == pytest.approx(1.294)
    assert si.replay(root) == result


def test_high_published_dtc_with_positive_volume_is_not_a_missing_sentinel():
    raw = data("2026-08-14").replace(b"|26911002|1.49|", b"|1|999.99|")
    records, missing = si.parse_records(raw, date(2026, 8, 14), ["AMD"])
    assert not missing
    assert records["AMD"]["days_to_cover"] == 999.99
    assert records["AMD"]["published_days_to_cover"] == 999.99
