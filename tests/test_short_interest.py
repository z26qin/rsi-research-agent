"""Publication cutoff, complete-basket coverage, and offline evidence integrity."""

from datetime import date

import pytest

from momentum_research_agent import short_interest as si

TARGET = date(2026, 9, 4)
REFERENCE = date(2026, 5, 29)
HOLDINGS = [
    dict(ticker="AMD", weight=0.3, exchange="NASDAQ", currency="USD", name="AMD"),
    dict(ticker="MU", weight=0.2, exchange="NASDAQ", currency="USD", name="Micron"),
]
HEADER = "accountingYearMonthNumber|symbolCode|issueName|issuerServicesGroupExchangeCode|marketClassCode|currentShortPositionQuantity|previousShortPositionQuantity|stockSplitFlag|averageDailyVolumeQuantity|daysToCoverQuantity|revisionFlag|changePercent|changePreviousNumber|settlementDate\n"


def schedule(rows=None):
    rows = rows or [
        ("May 29", "June 9"),
        ("July 31", "August 11"),
        ("August 14", "August 25"),
        ("August 31", "September 10"),
    ]
    body = "".join(
        f'<tr><td data-th="Settlement Date"><strong>{s}</strong><br>(Friday)</td><td>June 2 – 6:00 p.m.</td><td data-th="Exchange Receipt Date"><strong>{p}</strong><br>(Tuesday)</td></tr>'
        for s, p in rows
    )
    return (
        '<h2>2026&nbsp;Short Interest Reporting Dates</h2><table class="table"><thead><tr><th>Settlement Date</th><th>Due Date<sup>1</sup></th><th>Publication Date</th></tr></thead><tbody>'
        + body
        + "</tbody></table>"
    ).encode()


def data(day, missing=(), bad=None):
    rows = []
    for symbol, shares, adv, dtc in [
        ("MTUM", 1273798, 1366379, 1.00),
        ("SPY", 10000, 5000, 2),
        ("AMD", 40065798, 26911002, 1.49),
        ("MU", 30016025, 33755659, 1),
    ]:
        if symbol in missing:
            continue
        cells = [
            day.replace("-", ""),
            symbol,
            symbol + " Company",
            "R",
            "NNM",
            str(shares),
            "100",
            "",
            str(adv),
            str(dtc),
            "",
            "1",
            "1",
            day,
        ]
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
    assert result["basket"]["total_weight"] == 0.5
    assert len(network) == 4
    assert si.replay(root) == result
    with pytest.raises(FileExistsError):
        si.build(root, TARGET, REFERENCE, HOLDINGS)
