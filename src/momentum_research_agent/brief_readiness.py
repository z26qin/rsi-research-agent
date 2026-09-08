"""Coverage checks for the existing processed-panel contract; not a data adapter.

An observation date is NOT proof of publication-time availability. No engine
module is imported and no signals are recomputed here.
"""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pandas as pd

DAILY_PANELS = (
    "market_features.parquet", "leg_risk_history.parquet", "sp500_prices.parquet",
    "sp500_benchmark.parquet", "french_research_factors_daily.parquet",
    "momentum_labels_h5.parquet", "momentum_labels_h20.parquet",
)


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inspect_inputs(engine_root: Path, as_of: date) -> dict:
    inputs = {}
    limitations = [
        "Date coverage does not certify publication-time availability or point-in-time correctness.",
        "Panel coverage does not certify complete constituent coverage or valid values in every metric.",
    ]
    ready = True
    inventory = {name: "date" for name in DAILY_PANELS}
    inventory.update({"momentum_portfolio_holdings.parquet": "effective_month",
                      "sp500_universe.parquet": "as_of_date"})
    for name, column in inventory.items():
        path = engine_root / "data" / "processed" / name
        record = {"path": str(path.resolve()), "sha256": None, "date_column": column,
                  "latest_date": None, "latest_on_or_before": None, "status": "missing"}
        inputs[name] = record
        if not path.is_file():
            ready = False
            limitations.append(f"Missing input: {name}.")
            continue
        try:
            record["sha256"] = sha256_file(path)
            columns = [column, "formation_date"] if column == "effective_month" else [column]
            frame = pd.read_parquet(path, columns=columns)
            raw_dates = frame[column]
            if isinstance(raw_dates.dtype, pd.PeriodDtype):
                raw_dates = raw_dates.dt.to_timestamp()
            dates = pd.to_datetime(raw_dates, errors="coerce", utc=True).dt.date
            if dates.empty or dates.isna().any():
                raise ValueError("invalid dates")
            record["latest_date"] = max(dates).isoformat()
            past = dates[dates <= as_of]
            record["latest_on_or_before"] = max(past).isoformat() if len(past) else None
            if column == "effective_month":
                matching = dates == as_of.replace(day=1)
                formations = pd.to_datetime(frame["formation_date"], errors="coerce", utc=True).dt.date
                covered = bool(matching.any() and formations[matching].notna().all()
                               and (formations[matching] < as_of.replace(day=1)).all())
            elif column == "as_of_date":
                covered = True
                limitations.append(f"Constituent universe vintage: {record['latest_date']}; "
                                   "historical membership/survivorship correctness is not certified.")
            else:
                covered = bool((dates == as_of).any())
            record["status"] = "covered" if covered else "date_unavailable"
            if not covered:
                ready = False
                limitations.append(f"No usable coverage for {as_of.isoformat()}: {name}.")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            record["status"] = "invalid"
            ready = False
            limitations.append(f"Invalid input: {name} ({type(exc).__name__}).")
    # Optional panels can affect engine scores too. Hash every additional input;
    # unknown date conventions must not be presented as verified coverage.
    for path in sorted((engine_root / "data" / "processed").glob("*.parquet")):
        if path.name not in inputs:
            inputs[path.name] = {"path": str(path.resolve()), "sha256": sha256_file(path),
                                 "date_column": None, "latest_date": None,
                                 "latest_on_or_before": None, "status": "coverage_unverified"}
            limitations.append(f"Optional input coverage unverified: {path.name}.")
    return {"ready": ready, "inputs": inputs, "limitations": limitations}
