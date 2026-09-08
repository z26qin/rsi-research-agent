import json
from datetime import date

import pandas as pd
import pytest

from momentum_research_agent import crowding_metrics as cm


def payload(day="Sep 04, 2026", shares=100, weights=(60, 30, 10), ticker="MTUM"):
    rows = [f'{cm.FUND_NAMES[ticker]}', f'Fund Holdings as of,"{day}"',
            f'Shares Outstanding,{shares}', '',
            'Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Quantity,Price,Location,Exchange,Currency,FX Rate,Market Currency,Accrual Date']
    for symbol, sector, weight in zip(("AAA", "BBB", "USD"), ("Tech", "Tech", "Cash"), weights):
        asset = "Cash" if symbol == "USD" else "Equity"
        rows.append(f'{symbol},{symbol} NAME,{sector},{asset},{weight * 10},{weight},{weight * 10},10,10,United States,NASDAQ,USD,1,USD,-')
    props = [{"name": "NAV as of", "value": "10", "unitText": "USD", "valueReference": {"value": day}},
             {"name": "Net Assets of Fund", "value": "1000", "unitText": "USD", "valueReference": {"value": day}}]
    graph = [{"alternateName": ticker}, {"additionalProperty": props}]
    return {"holdings_csv": "\n".join(rows) + "\n\nLegal disclosure", "product_html":
            '<script type="application/ld+json">' + json.dumps({"@graph": graph}) + '</script>'}


def fund(ticker="MTUM", **kwargs):
    return cm.normalize(payload(ticker=ticker, **kwargs), ticker, date(2026, 9, 4))


def test_concentration_uses_fund_weights_without_renormalizing_cash():
    result = cm.concentration(fund())
    assert result["equity_weight"] == pytest.approx(.9)
    assert result["top10_weight"] == pytest.approx(.9)
    assert result["equity_hhi"] == pytest.approx(.45)
    assert result["sector_weights"] == {"Tech": pytest.approx(.9)}


def test_overlap_is_weighted_shared_listings_not_correlation():
    left, right = fund(), fund("QUAL", weights=(20, 70, 10))
    result = cm.overlap(left, right)
    assert result["weighted_overlap"] == pytest.approx(.5)
    assert result["shared_listings"] == 2
    right["holdings"][0]["exchange"] = "NYSE"
    assert cm.overlap(left, right)["weighted_overlap"] == pytest.approx(.3)


@pytest.mark.parametrize("change", ["future", "duplicate", "negative", "incomplete", "wrong_fund", "bad_header", "bad_weight"])
def test_invalid_holdings_fail_closed(change):
    raw = payload()
    if change == "future": raw = payload(day="Sep 08, 2026")
    if change == "duplicate": raw["holdings_csv"] = raw["holdings_csv"].replace('BBB,BBB NAME', 'AAA,AAA NAME')
    if change == "negative": raw = payload(weights=(-60, 150, 10))
    if change == "incomplete": raw = payload(weights=(10, 10, 10))
    if change == "wrong_fund": raw = payload(ticker="QUAL")
    if change == "bad_header": raw["holdings_csv"] = "blocked HTML"
    if change == "bad_weight": raw["holdings_csv"] = raw["holdings_csv"].replace(',60,', ',NaN,')
    with pytest.raises(ValueError): cm.normalize(raw, "MTUM", date(2026, 9, 4))


def test_optional_nav_failure_preserves_holdings_and_does_not_infer_nav():
    raw = payload()
    raw["product_html"] = "no structured NAV"
    item = cm.normalize(raw, "MTUM", date(2026, 9, 4))
    assert item["nav"] is None
    assert cm.concentration(item)["top10_weight"] == pytest.approx(.9)


def test_overlap_refuses_different_dates_and_name_collisions():
    with pytest.raises(ValueError): cm.overlap(fund(), fund("QUAL", day="Sep 03, 2026"))
    right = fund("QUAL")
    right["holdings"][0]["name"] = "DIFFERENT ISSUER"
    with pytest.raises(ValueError): cm.overlap(fund(), right)


def test_flow_uses_share_changes_and_splits_not_aum_growth():
    old, new = fund(day="Sep 03, 2026"), fund(shares=110)
    prices = pd.DataFrame({"date": pd.to_datetime(["2026-09-03", "2026-09-04"]), "stock_splits": [0., 0.]})
    out = cm.flow(old, new, prices)
    assert out["estimated_net_creation_usd"] == 100
    assert out["share_change_pct"] == pytest.approx(.1)
    new["shares_outstanding"] = 200
    prices.loc[1, "stock_splits"] = 2.
    assert cm.flow(old, new, prices)["estimated_net_creation_usd"] == 0
    new["shares_outstanding"] = 180
    assert cm.flow(old, new, prices)["estimated_net_creation_usd"] == -200


@pytest.mark.parametrize("change", ["same_day", "gap", "missing_actions", "invalid_actions", "nav_date", "nav_missing"])
def test_flow_withheld_for_incompatible_inputs(change):
    old, new = fund(day="Sep 03, 2026"), fund()
    prices = pd.DataFrame({"date": pd.to_datetime(["2026-09-04"]), "stock_splits": [0.]})
    if change == "same_day": old["as_of"] = new["as_of"]
    if change == "gap": old["as_of"] = "2026-09-02"
    if change == "missing_actions": prices = prices.iloc[:0]
    if change == "invalid_actions": prices.loc[0, "stock_splits"] = float("nan")
    if change == "nav_date": new["nav"]["as_of"] = "2026-09-03"
    if change == "nav_missing": new["nav"] = None
    with pytest.raises(ValueError): cm.flow(old, new, prices)


def test_non_session_date_cannot_masquerade_as_adjacent_flow():
    with pytest.raises(ValueError): fund(day="Aug 29, 2026")
    old, new = fund(day="Aug 28, 2026"), fund(day="Sep 01, 2026")
    old["as_of"] = "2026-08-29"
    prices = pd.DataFrame({"date": pd.to_datetime(["2026-09-01"]), "stock_splits": [0.]})
    with pytest.raises(ValueError): cm.flow(old, new, prices)
