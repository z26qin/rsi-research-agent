"""Bounded, disposable yfinance batch download for a frozen equity basket."""
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

import pandas as pd

from momentum_research_agent.brief_readiness import sha256_file
from momentum_research_agent.fixed_basket import allocations, price_panels
from momentum_research_agent.proxy_data import save_json


def request(symbols: list[str], start: date, end: date) -> dict:
    return {"tickers": sorted(set(symbols)), "start": str(start), "end": str(end + timedelta(days=1)),
            "interval": "1d", "auto_adjust": False, "actions": True, "repair": False,
            "group_by": "ticker", "threads": 8, "timeout": 20, "progress": False,
            "ignore_tz": True, "keepna": True, "multi_level_index": True}


def fetch(parameters: dict) -> pd.DataFrame:
    import yfinance as yf
    frame = yf.download(**parameters)
    if frame is None or frame.empty or not isinstance(frame.columns, pd.MultiIndex):
        raise ValueError("No usable vendor price table")
    # Only reshape the returned table; do not repair, fill, or drop failed ticker rows.
    parts = []
    for symbol in parameters["tickers"]:
        if symbol in frame.columns.get_level_values(0):
            part = frame[symbol].reset_index()
            # Preserve absence before concat introduces NaNs for optional ETF-only fields.
            parts.append(part.assign(Ticker=symbol, **{"Capital Gains Present": "Capital Gains" in part.columns}))
    return pd.concat(parts, ignore_index=True)


def worker_command(spec: Path, destination: Path) -> list[str]:
    return [sys.executable, "-m", "momentum_research_agent.fixed_basket_fetch", str(spec), str(destination)]


def run_worker(spec: Path, destination: Path, timeout: float):
    return subprocess.run(worker_command(spec, destination), timeout=min(55., timeout), check=True,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def collect(root: Path, fund: dict, start: date, end: date) -> tuple[Path, dict]:
    holdings = allocations(fund, start, end)
    symbols = [h["ticker"] for h in holdings] + ["MTUM", "SPY"]
    parameters = request(symbols, start, end)
    save_json(root / "request.json", parameters)
    record = {"source": "yfinance/Yahoo Finance", "request": parameters,
              "started_at": datetime.now(timezone.utc).isoformat(), "attempts": [],
              "format": "vendor-returned daily table reshaped to long form with optional-field presence marker; not raw HTTP",
              "selected_attempt": None}
    started, best, best_score = time.monotonic(), None, (-1., -1)
    for number in (1, 2):
        remaining = 120. - (time.monotonic() - started)
        if remaining <= 0:
            record["deadline_exhausted"] = True
            break
        destination = root / f"prices-attempt-{number}.parquet"
        event = {"number": number, "fetched_at": datetime.now(timezone.utc).isoformat()}
        try:
            run_worker(root / "request.json", destination, remaining)
            panels, missing = price_panels(pd.read_parquet(destination), symbols, start, end)
            event.update(status="partial" if missing else "ok", missing=missing)
            score = (sum(h["weight"] for h in holdings if h["ticker"] in panels), len(panels))
            if score > best_score:
                best, best_score, record["selected_attempt"] = destination, score, number
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            event.update(status="failed", error_type=type(exc).__name__)
        if destination.is_file():
            event.update(path=destination.name, sha256=sha256_file(destination))
        record["attempts"].append(event)
        save_json(root / "collection.json", record)
        if event["status"] == "ok":
            break
    if best is None:
        best = root / "prices-empty.parquet"
        pd.DataFrame().to_parquet(best, index=False)
    record["finished_at"] = datetime.now(timezone.utc).isoformat()
    save_json(root / "collection.json", record)
    return best, record


if __name__ == "__main__":
    fetch(json.loads(Path(sys.argv[1]).read_text())).to_parquet(sys.argv[2], index=False)
