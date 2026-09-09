"""Issuer observations, not a calibrated or market-wide crowding model."""
from __future__ import annotations

import csv
from datetime import date, datetime
import io
import json
import math
import re

import pandas as pd

from momentum_research_agent.proxy_metrics import sessions

VERSION = "etf_crowding_indicators_v1"
FUND_NAMES = {"MTUM": "iShares MSCI USA Momentum Factor ETF",
              "QUAL": "iShares MSCI USA Quality Factor ETF", "IVV": "iShares Core S&P 500 ETF"}
PRODUCTS = {"MTUM": "251614/ishares-msci-usa-momentum-factor-etf",
            "QUAL": "256101/ishares-msci-usa-quality-factor-etf",
            "IVV": "239726/ishares-core-sp-500-etf"}


def number(value: str) -> float:
    result = float(value.replace(",", "").replace("$", ""))
    if not math.isfinite(result):
        raise ValueError("Non-finite issuer value")
    return result


def issuer_date(value: str) -> str:
    return datetime.strptime(value.strip(), "%b %d, %Y").date().isoformat()


def nav_facts(html: str, symbol: str, target: date) -> dict:
    """Only dated issuer NAV/net assets; never infer NAV from holdings values."""
    facts = {}
    for script in re.findall(r'<script[^>]*type=[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script>', html, re.S):
        graph = json.loads(script).get("@graph", [])
        if not any(node.get("alternateName") == symbol for node in graph):
            continue
        for node in graph:
            for prop in node.get("additionalProperty", []):
                key = {"NAV as of": "nav", "Net Assets of Fund": "net_assets"}.get(prop.get("name"))
                if key and prop.get("unitText") == "USD":
                    observed = issuer_date(prop["valueReference"]["value"])
                    value = number(prop["value"])
                    if date.fromisoformat(observed) > target or value <= 0 or key in facts:
                        raise ValueError("Invalid/ambiguous issuer NAV")
                    facts[key] = {"value": value, "as_of": observed, "currency": "USD"}
    return facts


def normalize(raw: dict, symbol: str, target: date) -> dict:
    rows = list(csv.reader(io.StringIO(raw["holdings_csv"].lstrip("\ufeff"))))
    if not rows or rows[0] != [FUND_NAMES[symbol]]:
        raise ValueError("Issuer fund identity mismatch")
    try:
        start = next(i for i, row in enumerate(rows) if row and row[0] == "Ticker")
        metadata = dict(row for row in rows[1:start] if len(row) == 2)
        observed = issuer_date(metadata["Fund Holdings as of"])
        observed_date = date.fromisoformat(observed)
        shares = number(metadata["Shares Outstanding"])
        header = rows[start]
        required = {"Ticker", "Name", "Sector", "Asset Class", "Weight (%)", "Market Value", "Exchange", "Currency"}
        if (not required.issubset(header) or shares <= 0 or observed_date > target or
                len(sessions(observed_date, observed_date)) != 1):
            raise ValueError("Invalid issuer metadata or columns")
        holdings, seen, total = [], set(), 0.
        for row in rows[start + 1:]:
            if not row or not any(cell.strip() for cell in row):
                break  # standard issuer blank line before legal footer
            if len(row) != len(header):
                raise ValueError("Malformed holdings row")
            item = dict(zip(header, row))
            weight = number(item["Weight (%)"]) / 100
            total += weight
            if item["Asset Class"] != "Equity":
                continue  # no cash, derivatives or fund look-through in overlap
            market_value = number(item["Market Value"])
            ticker, exchange, currency = (item[k].strip() for k in ("Ticker", "Exchange", "Currency"))
            key = (ticker, exchange, currency)
            if (not all(key) or "-" in key or currency != "USD" or key in seen or
                    weight < 0 or weight > 1 or market_value < 0 or not item["Sector"].strip()):
                raise ValueError("Invalid/duplicate equity listing")
            seen.add(key)
            holdings.append({"ticker": ticker, "name": item["Name"].strip(), "sector": item["Sector"].strip(),
                             "exchange": exchange, "currency": currency, "weight": weight, "market_value": market_value})
        if not holdings or not .98 <= total <= 1.02 or sum(h["weight"] for h in holdings) > 1.02:
            raise ValueError("Incomplete or invalid holdings weight coverage")
    except (KeyError, StopIteration, TypeError) as exc:
        raise ValueError("Malformed issuer holdings") from exc
    facts, warnings = {}, []
    try:
        facts = nav_facts(raw.get("product_html", ""), symbol, target)
    except (ValueError, KeyError, TypeError):
        warnings.append("NAV/net assets unavailable: invalid dated issuer facts")
    return {"symbol": symbol, "as_of": observed, "shares_outstanding": shares,
            "nav": facts.get("nav"), "net_assets": facts.get("net_assets"), "holdings": holdings,
            "reported_weight_total": total, "warnings": warnings}


def concentration(fund: dict) -> dict:
    holdings = fund["holdings"]
    sectors = {}
    for item in holdings:
        sectors[item["sector"]] = sectors.get(item["sector"], 0.) + item["weight"]
    return {"equity_weight": sum(item["weight"] for item in holdings),
            "equity_listings": len(holdings), "top10_weight": sum(sorted((h["weight"] for h in holdings), reverse=True)[:10]),
            "equity_hhi": sum(item["weight"] ** 2 for item in holdings),
            "sector_weights": dict(sorted(sectors.items(), key=lambda x: (-x[1], x[0])))}


def overlap(left: dict, right: dict) -> dict:
    if left["as_of"] != right["as_of"]:
        raise ValueError("Holdings dates differ")
    def indexed(fund):
        return {(h["ticker"], h["exchange"], h["currency"]): h for h in fund["holdings"]}
    a, b = indexed(left), indexed(right)
    common = sorted(a.keys() & b.keys())
    if any(a[key]["name"] != b[key]["name"] for key in common):
        raise ValueError("Listing name collision; no fuzzy identity matching")
    return {"as_of": left["as_of"], "weighted_overlap": sum(min(a[k]["weight"], b[k]["weight"]) for k in common),
            "shared_listings": len(common), "left_shared_weight": sum(a[k]["weight"] for k in common),
            "right_shared_weight": sum(b[k]["weight"] for k in common),
            "identity_basis": "exact ticker + exchange + currency, checked name; not issuer-level ownership"}


def flow(old: dict, new: dict, prices: pd.DataFrame) -> dict:
    """One-session estimated net creations. Missing/non-adjacent history is not zero."""
    before, after = date.fromisoformat(old["as_of"]), date.fromisoformat(new["as_of"])
    if (old["symbol"] != new["symbol"] or before >= after or
            list(sessions(before, after)) != [pd.Timestamp(before), pd.Timestamp(after)] or
            not new["nav"] or new["nav"]["as_of"] != new["as_of"]):
        raise ValueError("Need adjacent trading-session shares and same-date NAV")
    actions = prices.loc[prices.date == pd.Timestamp(after), "stock_splits"]
    if len(actions) != 1 or not math.isfinite(float(actions.iloc[0])) or actions.iloc[0] < 0:
        raise ValueError("Missing/invalid split coverage")
    ratio = float(actions.iloc[0]) or 1.
    adjusted_before = old["shares_outstanding"] * ratio
    change = new["shares_outstanding"] - adjusted_before
    return {"from_date": old["as_of"], "to_date": new["as_of"], "split_ratio": ratio,
            "estimated_net_creation_usd": change * new["nav"]["value"],
            "share_change_pct": change / adjusted_before,
            "method": "(shares[t] - shares[t-1] * split_ratio[t]) * issuer_NAV[t]; estimate, not cash flow"}
