"""Bounded public-data collection into a run-local, auditable snapshot."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import pandas as pd

from momentum_research_agent.brief_readiness import sha256_file
from momentum_research_agent.proxy_metrics import CALCULATION_VERSION, SYMBOLS, normalize_prices

ATTEMPT_TIMEOUT = 20.0
TOTAL_TIMEOUT = 120.0
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS"


def save_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def worker_command(source: str, start: str, end: str, destination: Path) -> list[str]:
    return [sys.executable, "-m", "momentum_research_agent.proxy_fetch", source,
            start, end, str(destination)]


def run_worker(source: str, start: str, end: str, destination: Path, *, timeout: float | None = None):
    # subprocess.run kills and reaps the child on timeout; no thread-only timeout.
    return subprocess.run(worker_command(source, start, end, destination), check=True,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                          timeout=min(ATTEMPT_TIMEOUT, timeout) if timeout is not None else ATTEMPT_TIMEOUT)


def normalize_vix(raw: pd.DataFrame, as_of: date) -> pd.DataFrame:
    if {"observation_date", "VIXCLS"}.issubset(raw.columns):
        dates, values = raw["observation_date"], raw["VIXCLS"]
    elif {"DATE", "VALUE"}.issubset(raw.columns):
        dates, values = raw["DATE"], raw["VALUE"]
    else:
        raise ValueError("Unknown VIX columns")
    result = pd.DataFrame({"date": pd.to_datetime(dates, errors="raise"),
                           "vix": pd.to_numeric(values.replace(".", np.nan), errors="raise")})
    result = result.loc[result.date <= pd.Timestamp(as_of)].dropna().sort_values("date")
    if result.empty or result.date.duplicated().any() or not (np.isfinite(result.vix) & (result.vix > 0)).all():
        raise ValueError("Invalid VIX observations")
    return result.reset_index(drop=True)


def collect(output: Path, as_of: date) -> dict:
    started = time.monotonic()
    start = (pd.Timestamp(as_of) - pd.DateOffset(years=5)).date().isoformat()
    end = (as_of + timedelta(days=1)).isoformat()  # vendor end is exclusive
    (output / "vendor").mkdir()
    (output / "normalized").mkdir()
    manifest = {"schema_version": "etf_proxy_snapshot_v1", "calculation_version": CALCULATION_VERSION,
                "target_date": as_of.isoformat(), "started_at": datetime.now(timezone.utc).isoformat(),
                "libraries": {name: importlib.metadata.version(name) for name in ("yfinance", "exchange-calendars")},
                "sources": {}, "attempts": []}
    for source in (*SYMBOLS, "VIXCLS"):
        entry = {"status": "unavailable", "source": FRED_URL if source == "VIXCLS" else "Yahoo Finance via yfinance",
                 "parameters": {"start": start, "end_exclusive": end, "symbol": source,
                                "interval": "1d", "auto_adjust": False, "actions": True},
                 "table_kind": "vendor-returned table, not raw HTTP response"}
        if source == "VIXCLS":
            entry["parameters"] = {"url": FRED_URL, "target_date": as_of.isoformat()}
        manifest["sources"][source] = entry
        for number in (1, 2):
            remaining = TOTAL_TIMEOUT - (time.monotonic() - started)
            if remaining <= 0:
                entry["error"] = "total_deadline"
                break
            attempt = {"source": source, "attempt": number, "status": "running",
                       "started_at": datetime.now(timezone.utc).isoformat()}
            manifest["attempts"].append(attempt)
            save_json(output / "manifest.json", manifest)
            path = output / "vendor" / f"{source}-{number}.parquet"
            tick = time.monotonic()
            try:
                run_worker(source, start, end, path, timeout=remaining)
                raw = pd.read_parquet(path)
                normalized = normalize_vix(raw, as_of) if source == "VIXCLS" else normalize_prices(raw, as_of)
                destination = output / "normalized" / f"{source}.parquet"
                normalized.to_parquet(destination, index=False)
                entry.update(status="ok", vendor_path=str(path.relative_to(output)), vendor_sha256=sha256_file(path),
                             normalized_path=str(destination.relative_to(output)), normalized_sha256=sha256_file(destination),
                             first_date=normalized.date.min().date().isoformat(), latest_date=normalized.date.max().date().isoformat(),
                             fetched_at=datetime.now(timezone.utc).isoformat())
                entry.pop("error", None)
                attempt["status"] = "ok"
            except Exception as exc:
                # Never persist arbitrary provider stderr (URLs/cookies may be sensitive).
                attempt.update(status="failed", error_type=type(exc).__name__)
                entry["error"] = type(exc).__name__
            finally:
                attempt["elapsed_s"] = round(time.monotonic() - tick, 3)
                save_json(output / "manifest.json", manifest)
            if entry["status"] == "ok":
                break
    save_json(output / "manifest.json", manifest)
    return manifest
