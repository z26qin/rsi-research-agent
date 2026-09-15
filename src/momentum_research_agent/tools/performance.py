"""Dated, deterministic calculations over a bounded common daily price sample."""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from pathlib import Path

import pandas as pd

from momentum_research_agent.models.schemas import ResearchReport, utcnow
from momentum_research_agent.proxy_metrics import sessions, target_date


def calculate(frames: dict) -> dict:
    panels = {}
    cutoff = target_date(None)
    for symbol, frame in frames.items():
        if frame is None or frame.empty:
            raise ValueError("Missing prices")
        frame = frame.copy()
        if frame.columns.nlevels > 1:
            frame.columns = [col[0] for col in frame.columns]
        series = frame["Close"]
        dates = pd.DatetimeIndex(series.index)
        if dates.tz is not None:
            dates = dates.tz_convert("America/New_York").tz_localize(None)
        series.index = dates.normalize()
        if series.index.has_duplicates or series.index.hasnans:
            raise ValueError("Duplicate or invalid dates")
        series = series.sort_index().loc[: str(cutoff)].tail(300)
        if not series.map(
            lambda v: pd.notna(v) and math.isfinite(float(v)) and float(v) > 0
        ).all():
            raise ValueError("Invalid adjusted prices")
        panels[symbol] = series
    common = pd.DataFrame(panels).dropna().tail(20)
    if len(common) != 20:
        raise ValueError("Need 20 common daily price observations")
    if not common.index.equals(
        sessions(common.index[0].date(), common.index[-1].date())
    ):
        raise ValueError("Missing or non-trading sessions in common window")
    metrics = {}
    for symbol in common:
        price = common[symbol]
        returns = price.pct_change(fill_method=None).iloc[1:]
        metrics[symbol] = {
            "return_pct": float((price.iloc[-1] / price.iloc[0] - 1) * 100),
            "volatility_pct": float(returns.std(ddof=1) * math.sqrt(252) * 100),
            "max_drawdown_pct": float((price / price.cummax() - 1).min() * 100),
        }
    return {
        "schema": "daily_performance_v1",
        "status": "ok",
        "provider": "Yahoo Finance via yfinance",
        "auto_adjust": True,
        "start": str(common.index[0].date()),
        "as_of": str(common.index[-1].date()),
        "price_observations": 20,
        "return_observations": 19,
        "metrics": metrics,
        "sources": [
            {"url": f"https://finance.yahoo.com/quote/{s}/history/"} for s in common
        ],
        "prices": [
            {"date": str(day.date()), **{s: float(row[s]) for s in common}}
            for day, row in common.iterrows()
        ],
        "method": "Adjusted close: last/first-1; sample daily-return std(ddof=1)*sqrt(252); min(price/cummax-1). All metrics in percent.",
        "limits": [
            "20 common prices, 19 returns; not a full month or a long-short factor.",
            "Vendor adjusted closes, not audited fund NAV returns. Current calendar day excluded.",
            "A returned date is not proof of current data freshness.",
        ],
    }


def archive(payload: dict, session_dir: Path) -> dict:
    payload = {**payload, "retrieved_at": utcnow().isoformat()}
    folder = session_dir / "market_observations"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex}.json"
    raw = json.dumps(payload, sort_keys=True, allow_nan=False).encode()
    path.write_bytes(raw)
    return {k: v for k, v in payload.items() if k != "prices"} | {
        "artifact": str(path.relative_to(session_dir)),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def retained_report(
    task, traces, session_dir: Path, reason: str
) -> ResearchReport | None:
    """Recover only archived tool calculations, never unfinished model prose."""
    for trace in reversed(traces):
        if trace.tool != "market_data" or trace.truncated:
            continue
        try:
            result = json.loads(trace.observation)
            if (
                result.get("status") != "ok"
                or result.get("schema") != "daily_performance_v1"
            ):
                continue
            relative = result["artifact"]
            if not re.fullmatch(r"market_observations/[a-f0-9]{32}\.json", relative):
                continue
            path = (session_dir / relative).resolve()
            path.relative_to(session_dir.resolve())
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != result["sha256"]:
                continue
            data = json.loads(raw)
            if any(
                data[k] != result[k]
                for k in ("schema", "metrics", "as_of", "start", "sources")
            ):
                continue
            findings, metrics = [], []
            labels = {
                "return_pct": "adjusted-price return",
                "volatility_pct": "annualized sample volatility",
                "max_drawdown_pct": "within-window maximum drawdown",
            }
            for symbol, values in data["metrics"].items():
                url = f"https://finance.yahoo.com/quote/{symbol}/history/"
                for name, value in values.items():
                    eid = f"{task.id}:computed:{symbol}:{name}"
                    claim = f"{symbol} {labels[name]} over {data['start']} to {data['as_of']}: {value:.6f}% (20 prices, 19 returns)."
                    findings.append(
                        {
                            "id": eid,
                            "claim": claim,
                            "category": "other",
                            "stance": "neutral",
                            "source_url": url,
                            "source_name": f"{relative} sha256={result['sha256']}",
                            "excerpt": claim,
                            "confidence": "medium",
                        }
                    )
                    metrics.append(
                        {
                            "name": f"{symbol} {labels[name]}",
                            "value": value,
                            "unit": "%",
                            "as_of": data["as_of"],
                            "source_url": url,
                            "evidence_id": eid,
                        }
                    )
            return ResearchReport(
                task_id=task.id,
                title=task.title,
                agent_role=task.profile,
                findings=findings,
                metrics=metrics,
                as_of=data["as_of"],
                sources=[x["url"] for x in data["sources"]],
                summary="Computed price observations retained; model interpretation did not complete.",
                status="partial",
                limitations=[reason, *data["limits"], data["method"]],
                unanswered_questions=[
                    task.assignment,
                    "Interpretation and requested context remain incomplete.",
                ],
            )
        except (KeyError, ValueError, TypeError, OSError):
            continue
    return None
