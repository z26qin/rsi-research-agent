"""Publication cutoff, complete-basket coverage, and offline evidence integrity."""

import pytest

from momentum_research_agent import short_interest as si

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
