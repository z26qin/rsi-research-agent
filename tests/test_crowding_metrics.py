import json
from datetime import date

import pandas as pd
import pytest

from momentum_research_agent import crowding_metrics as cm


def payload(day="Sep 04, 2026", shares=100, weights=(60, 30, 10), ticker="MTUM"):
    rows = [
        f"{cm.FUND_NAMES[ticker]}",
        f'Fund Holdings as of,"{day}"',
        f"Shares Outstanding,{shares}",
        "",
        "Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Quantity,Price,Location,Exchange,Currency,FX Rate,Market Currency,Accrual Date",
    ]
    for symbol, sector, weight in zip(
        ("AAA", "BBB", "USD"), ("Tech", "Tech", "Cash"), weights
    ):
        asset = "Cash" if symbol == "USD" else "Equity"
        rows.append(
            f"{symbol},{symbol} NAME,{sector},{asset},{weight * 10},{weight},{weight * 10},10,10,United States,NASDAQ,USD,1,USD,-"
        )
    props = [
        {
            "name": "NAV as of",
            "value": "10",
            "unitText": "USD",
            "valueReference": {"value": day},
        },
        {
            "name": "Net Assets of Fund",
            "value": "1000",
            "unitText": "USD",
            "valueReference": {"value": day},
        },
    ]
    graph = [{"alternateName": ticker}, {"additionalProperty": props}]
    return {
        "holdings_csv": "\n".join(rows) + "\n\nLegal disclosure",
        "product_html": '<script type="application/ld+json">'
        + json.dumps({"@graph": graph})
        + "</script>",
    }


def fund(ticker="MTUM", **kwargs):
    return cm.normalize(payload(ticker=ticker, **kwargs), ticker, date(2026, 9, 4))


def test_flow_uses_share_changes_and_splits_not_aum_growth():
    old, new = fund(day="Sep 03, 2026"), fund(shares=110)
    prices = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-09-03", "2026-09-04"]),
            "stock_splits": [0.0, 0.0],
        }
    )
    out = cm.flow(old, new, prices)
    assert out["estimated_net_creation_usd"] == 100
    assert out["share_change_pct"] == pytest.approx(0.1)
    new["shares_outstanding"] = 200
    prices.loc[1, "stock_splits"] = 2.0
    assert cm.flow(old, new, prices)["estimated_net_creation_usd"] == 0
    new["shares_outstanding"] = 180
    assert cm.flow(old, new, prices)["estimated_net_creation_usd"] == -200
