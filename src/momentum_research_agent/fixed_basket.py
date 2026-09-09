"""Retrospective fixed MTUM equity basket. Never historical holdings or a PIT backtest."""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
import re
import shutil

import numpy as np
import pandas as pd

from momentum_research_agent.crowding_metrics import concentration
from momentum_research_agent import crowding_data as cd
from momentum_research_agent.brief_readiness import sha256_file
from momentum_research_agent.crowding_history import copy_reference
from momentum_research_agent.proxy_data import save_json
from momentum_research_agent.proxy_metrics import normalize_prices, sessions, target_date

SCHEMA = "fixed_basket_simulation_v1"
VERSION = "fixed_basket_cash_dividends_v2"
LIMITATIONS = [
    "Look-ahead bias: constituents and starting weights were selected after the simulation start. Not a point-in-time backtest.",
    "Hypothetical current-basket simulation, not actual historical MTUM holdings, crowding, flows or strategy-selection skill.",
    "Latest reported equity weights are applied at the start close; the residual is zero-interest cash, not the issuer's actual non-equity positions.",
    "No rebalancing. Dividends accrue to cash on the ex-date (receivable convention), not payment date; no reinvestment.",
    "Yahoo Close and Dividends use the vendor's split-adjusted basis. Split events are recorded, not multiplied into prices or units again.",
    "Adj Close is retained and validated but not used for this cash-dividend simulation. Benchmarks use the same cash-dividend convention.",
    "Concentration uses equity market values divided by total simulated wealth, including cash. Sectors are frozen at the holdings snapshot.",
    "Current ticker mappings are not a historical security master; mergers, spin-offs and delisted histories may be unsupported.",
    "Only simple integer forward or reciprocal-integer reverse splits are accepted automatically. Other ratios require corporate-action review; this heuristic is not comprehensive spin-off detection.",
    "No taxes, transaction costs, cash interest or trading execution. Personal research only; no production SLA.",
]


def allocations(fund: dict, start: date, end: date) -> list[dict]:
    observed = date.fromisoformat(fund["as_of"])
    if fund["symbol"] != "MTUM" or not start < observed <= end or start >= end:
        raise ValueError("Need a later MTUM snapshot and start < holdings date <= end")
    dates = sessions(start, end)
    if not len(dates) or dates[0].date() != start or dates[-1].date() != end:
        raise ValueError("Endpoints must be XNYS sessions")
    result, seen = [], set()
    for item in fund["holdings"]:
        symbol = item["ticker"]
        weight = float(item["weight"])
        if (symbol in seen or not re.fullmatch(r"[A-Z]{1,6}(?:-[A-Z])?", symbol)
                or symbol in {"MTUM", "SPY"} or item["currency"] != "USD"
                or item["exchange"] not in {"NASDAQ", "NYSE", "Cboe BZX", "NYSE Arca"}
                or not math.isfinite(weight) or weight < 0):
            raise ValueError("Invalid or ambiguous equity allocation; no fuzzy ticker mapping")
        seen.add(symbol)
        if weight > 0:
            result.append(dict(item))
    total = sum(h["weight"] for h in result)
    if not result or total > 1 or total <= 0:
        raise ValueError("Equity allocation must be positive and at most 100%; no rescaling")
    return result


def normalized_table(fund: dict, raw: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    symbols = [h["ticker"] for h in allocations(fund, start, end)] + ["MTUM", "SPY"]
    panels, _ = price_panels(raw, symbols, start, end)
    return (pd.concat([frame.reset_index().assign(ticker=s) for s, frame in sorted(panels.items())], ignore_index=True)
            if panels else pd.DataFrame())


def saved_fund(root: Path, reference: dict) -> dict:
    base = root / "reference/crowding"
    path = cd.checked(base, "manifest.json", reference["manifest_sha256"])
    manifest = json.loads(path.read_text())
    entry = manifest["sources"]["MTUM"]
    fund = cd.load_fund(base, entry)
    if (fund["symbol"] != "MTUM" or entry["symbol"] != "MTUM" or
            fund["as_of"] != reference["target_date"] or manifest["target_date"] != reference["target_date"]):
        raise ValueError("Allocation snapshot date/identity mismatch")
    return fund


def replay(root: Path) -> dict:
    """Recompute from pinned evidence. Never trust editable result metrics."""
    report = json.loads((root / "simulation.json").read_text())
    manifest_path = cd.checked(root, "manifest.json", report["manifest_sha256"])
    manifest = json.loads(manifest_path.read_text())
    if manifest["schema_version"] != SCHEMA or manifest["calculation_version"] != VERSION:
        raise ValueError("Unsupported simulation version")
    start, end = (date.fromisoformat(manifest[key]) for key in ("start_date", "end_date"))
    fund = saved_fund(root, manifest["reference"])
    raw = pd.read_parquet(cd.checked(root, "prices.parquet", manifest["prices_sha256"]))
    normalized = pd.read_parquet(cd.checked(root, "normalized.parquet", manifest["normalized_sha256"]))
    if not normalized.equals(normalized_table(fund, raw, start, end)):
        raise ValueError("Price normalization cannot be reproduced")
    return {**calculate(fund, raw, start, end), "generated_at": manifest["generated_at"],
            "manifest_sha256": sha256_file(manifest_path), "data_source": manifest["data_source"]}


def render(result: dict) -> str:
    def percent(value):
        return "unavailable" if value is None else f"{value:.2%}"
    c = result["coverage"]
    lines = ["# Retrospective MTUM fixed-basket simulation", "",
             "**LOOK-AHEAD BIAS — hypothetical portfolio, not historical MTUM holdings or crowding.**", "",
             f"Period: {result['start_date']} → {result['end_date']} (close to close).",
             f"Allocation source date: {result['holdings_as_of']}. Generated: {result.get('generated_at', 'offline calculation')}.",
             f"Status: {result['status']}. Version: {VERSION}. LLM requests: 0.", "",
             f"Price coverage: {c['available_constituents']}/{c['required_constituents']} constituents; "
             f"{c['available_equity_weight']:.2%} of initial wealth covered out of {c['requested_equity_weight']:.2%} allocated to equities.",
             f"Initial residual cash: {c['initial_cash_weight']:.2%}. No missing-stock reweighting.", "",
             "## Performance over the simulation interval", "",
             "All three series hold dividends as cash/receivables; these are not dividend-reinvested total returns.", "",
             "| Portfolio | Return | Annualized daily volatility | Maximum drawdown |",
             "| --- | ---: | ---: | ---: |"]
    for label, item in [("Fixed basket", result["portfolio"]), *result["benchmarks"].items()]:
        lines.append(f"| {label} | {percent(item.get('return') if item else None)} | "
                     f"{percent(item.get('volatility') if item else None)} | {percent(item.get('max_drawdown') if item else None)} |")
    lines += ["", f"Relative wealth change versus SPY: {percent(result['relative']['SPY'])}; "
              f"versus actual MTUM market-price series: {percent(result['relative']['MTUM'])}."]
    if result["concentration"]:
        a, b = result["concentration"]["start"], result["concentration"]["end"]
        lines += ["", "## Price-driven concentration (simulated, not issuer observations)", "",
                  f"Top-10 equity weight: {a['top10_weight']:.2%} → {b['top10_weight']:.2%}.",
                  f"Equity HHI: {a['equity_hhi']:.6f} → {b['equity_hhi']:.6f}.",
                  f"Ending cash/receivable weight: {result['path'][-1]['cash'] / result['path'][-1]['value']:.2%}.", "",
                  "Sector weights, every position and the daily wealth path are retained in simulation.json."]
    if c["missing"]:
        lines += ["", "## Missing or invalid price history", ""]
        lines += [f"- {symbol}: {reason}" for symbol, reason in sorted(c["missing"].items())]
    lines += ["", "## Method and limitations", ""] + ["- " + s for s in result["limitations"]]
    return "\n".join(lines) + "\n"


def run(reference: Path, start: date, root: Path, end: date | None = None, prices_file: Path | None = None) -> dict:
    root.mkdir(parents=True, exist_ok=False)
    start = target_date(start)
    copied = copy_reference(reference, root / "reference/crowding", start)
    end = target_date(end or date.fromisoformat(copied["target_date"]))
    fund = saved_fund(root, copied)
    allocations(fund, start, end)
    if prices_file is None:
        from momentum_research_agent.fixed_basket_fetch import collect
        path, data_source = collect(root, fund, start, end)
    else:
        path = prices_file
        data_source = {"source": "user-supplied recorded yfinance-format table; not independently authenticated",
                       "input_sha256": sha256_file(path), "imported_at": datetime.now(timezone.utc).isoformat()}
    shutil.copyfile(path, root / "prices.parquet")
    raw = pd.read_parquet(root / "prices.parquet")
    normalized_table(fund, raw, start, end).to_parquet(root / "normalized.parquet", index=False)
    manifest = {"schema_version": SCHEMA, "calculation_version": VERSION, "start_date": str(start), "end_date": str(end),
                "generated_at": datetime.now(timezone.utc).isoformat(), "reference": copied,
                "prices_sha256": sha256_file(root / "prices.parquet"), "normalized_sha256": sha256_file(root / "normalized.parquet"),
                "data_source": data_source}
    save_json(root / "manifest.json", manifest)
    save_json(root / "simulation.json", {"manifest_sha256": sha256_file(root / "manifest.json")})
    result = replay(root)
    save_json(root / "simulation.json", result)
    (root / "simulation.md").write_text(render(result), encoding="utf-8")
    return result


def price_panels(raw: pd.DataFrame, symbols: list[str], start: date, end: date) -> tuple[dict, dict]:
    """Require complete daily prices AND actions for each positive-weight constituent."""
    panels, missing = {}, {}
    expected = sessions(start, end)
    for symbol in symbols:
        try:
            part = raw.loc[raw["Ticker"] == symbol].copy()
            dates = pd.to_datetime(part["Date"], errors="raise")
            if dates.dt.tz is not None:
                dates = dates.dt.tz_convert("America/New_York").dt.tz_localize(None)
            part["Date"] = dates.dt.normalize()
            part = part.loc[part.Date.between(pd.Timestamp(start), pd.Timestamp(end))]
            if "Capital Gains" in part:
                present = part.get("Capital Gains Present", pd.Series(True, index=part.index))
                if not present.isin([True, False]).all():
                    raise ValueError("Invalid optional-field presence marker")
                present = present.astype(bool)
                if (not part.loc[present, "Capital Gains"].eq(0).all()
                        or not part.loc[~present, "Capital Gains"].isna().all()):
                    raise ValueError("Unsupported or invalid capital-gain distribution")
            frame = normalize_prices(part, end)
            if not pd.DatetimeIndex(frame.date).equals(expected):
                raise ValueError("Missing trading-session observations; no filling")
            for column in ("dividends", "stock_splits"):
                frame[column] = pd.to_numeric(frame[column], errors="raise")
                if not (np.isfinite(frame[column]) & (frame[column] >= 0)).all():
                    raise ValueError("Invalid corporate-action coverage")
            for event in frame.iloc[1:].itertuples():
                ratio = float(event.stock_splits)
                if ratio:
                    scale = ratio if ratio >= 1 else 1 / ratio
                    if not math.isfinite(scale) or not math.isclose(scale, round(scale), rel_tol=0, abs_tol=1e-8):
                        raise ValueError(f"Unsupported corporate action on {event.date.date()}: vendor split ratio {ratio}; review required")
            panels[symbol] = frame.set_index("date")
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            missing[symbol] = str(exc)
    return panels, missing


def cash_path(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Value and accumulated distributions per $1 invested at the start close."""
    dividends = frame.dividends.copy()
    dividends.iloc[0] = 0.  # Bought at the close: no entitlement to start-date dividend.
    cash = dividends.cumsum() / float(frame.close.iloc[0])
    return frame.close / float(frame.close.iloc[0]) + cash, cash


def performance(values: pd.Series) -> dict:
    changes = values.pct_change(fill_method=None).iloc[1:]
    return {"return": float(values.iloc[-1] / values.iloc[0] - 1),
            "max_drawdown": float((values / values.cummax() - 1).min()),
            "volatility": float(changes.std(ddof=1) * np.sqrt(252)) if len(changes) >= 2 else None,
            "return_observations": len(changes)}


def calculate(fund: dict, raw: pd.DataFrame, start: date, end: date) -> dict:
    holdings = allocations(fund, start, end)
    symbols = [h["ticker"] for h in holdings]
    panels, missing = price_panels(raw, symbols + ["MTUM", "SPY"], start, end)
    equity_weight = sum(h["weight"] for h in holdings)
    result = {"schema_version": SCHEMA, "calculation_version": VERSION, "status": "unavailable",
              "start_date": str(start), "end_date": str(end), "holdings_as_of": fund["as_of"],
              "look_ahead_bias": True, "llm_requests": 0, "limitations": list(LIMITATIONS),
              "coverage": {"required_constituents": len(holdings), "available_constituents": sum(s in panels for s in symbols),
                           "requested_equity_weight": equity_weight,
                           "available_equity_weight": sum(h["weight"] for h in holdings if h["ticker"] in panels),
                           "initial_cash_weight": 1 - equity_weight, "missing": missing},
              "portfolio": None, "concentration": None, "positions": [], "path": [], "benchmarks": {},
              "relative": {"MTUM": None, "SPY": None}}
    for symbol in ("MTUM", "SPY"):
        result["benchmarks"][symbol] = ({"status": "ok", **performance(cash_path(panels[symbol])[0])}
                                        if symbol in panels else {"status": "unavailable"})
    if any(symbol not in panels for symbol in symbols):
        return result  # Never silently drop missing constituents or rescale their weights.
    dates = sessions(start, end)
    cash = pd.Series(1 - equity_weight, index=dates)
    equity_columns = {}
    for h in holdings:
        symbol, weight = h["ticker"], h["weight"]
        frame = panels[symbol]
        equity_columns[symbol] = weight * frame.close / frame.close.iloc[0]
        cash += weight * cash_path(frame)[1]
    equity = pd.DataFrame(equity_columns, index=dates)
    values = equity.sum(axis=1) + cash
    weights = equity.div(values, axis=0)
    result["status"] = "partial"
    result["portfolio"] = performance(values)
    result["path"] = [{"date": d.date().isoformat(), "value": float(values.loc[d]), "cash": float(cash.loc[d]),
                       "equity_value": float(equity.loc[d].sum())} for d in dates]
    result["concentration"] = {}
    for label, i in (("start", 0), ("end", -1)):
        rows = [{**h, "weight": float(weights[h["ticker"]].iloc[i])} for h in holdings]
        result["concentration"][label] = concentration({"holdings": rows})
    for h in holdings:
        symbol = h["ticker"]
        frame = panels[symbol]
        splits = frame.iloc[1:].loc[frame.iloc[1:].stock_splits > 0, "stock_splits"]
        result["positions"].append({**h, "start_weight": h["weight"], "end_weight": float(weights[symbol].iloc[-1]),
                                    "split_adjusted_units_per_initial_dollar": h["weight"] / float(frame.close.iloc[0]),
                                    "cash_dividends_per_initial_dollar": h["weight"] * float(cash_path(frame)[1].iloc[-1]),
                                    "split_events": [{"date": d.date().isoformat(), "ratio": float(r)} for d, r in splits.items()]})
    for symbol, benchmark in result["benchmarks"].items():
        if benchmark["status"] == "ok":
            result["relative"][symbol] = (1 + result["portfolio"]["return"]) / (1 + benchmark["return"]) - 1
    return result
