"""ETF proxy reporting and hash-checked offline recomputation."""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from momentum_research_agent.brief_readiness import sha256_file
from momentum_research_agent.proxy_data import collect, save_json
from momentum_research_agent.proxy_metrics import (
    CALCULATION_VERSION, SYMBOLS, calculate, normalize_prices, target_date,
)


class ProxyBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["etf_proxy_brief_v1"] = "etf_proxy_brief_v1"
    calculation_version: Literal["etf_proxy_metrics_v1"] = CALCULATION_VERSION
    scope: Literal["long_only_etf_proxy"] = "long_only_etf_proxy"
    requested_as_of: date
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Literal["partial", "unavailable"] = "unavailable"
    manifest_sha256: str | None = None
    sources: dict = Field(default_factory=dict)
    metrics: dict[str, float | None] = Field(default_factory=dict)
    vix: dict = Field(default_factory=dict)
    changes: dict = Field(default_factory=dict)
    comparison_note: str = "No previous proxy brief supplied."
    limitations: list[str] = Field(default_factory=list)
    llm_requests: Literal[0] = 0


def checked_path(root: Path, relative: str, digest: str) -> Path:
    path = (root / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root.resolve()) or sha256_file(path) != digest:
        raise ValueError("Snapshot path or hash mismatch")
    return path


def load_snapshot(root: Path) -> tuple[dict, dict[str, pd.DataFrame]]:
    manifest = json.loads((root / "manifest.json").read_text())
    if (manifest["schema_version"] != "etf_proxy_snapshot_v1" or
            manifest["calculation_version"] != CALCULATION_VERSION):
        raise ValueError("Unsupported snapshot version")
    as_of = date.fromisoformat(manifest["target_date"])
    panels = {}
    for symbol in SYMBOLS:
        entry = manifest["sources"][symbol]
        if entry["status"] != "ok":
            raise ValueError("Required ETF unavailable")
        vendor = checked_path(root, entry["vendor_path"], entry["vendor_sha256"])
        normalized = checked_path(root, entry["normalized_path"], entry["normalized_sha256"])
        frame = normalize_prices(pd.read_parquet(vendor), as_of)
        if not frame.equals(pd.read_parquet(normalized)):
            raise ValueError("Normalized table does not reproduce vendor table")
        panels[symbol] = frame
    return manifest, panels


def replay_snapshot(root: Path) -> dict[str, float | None]:
    """Recompute solely from saved, checked tables; never contacts a provider."""
    manifest, panels = load_snapshot(root)
    return calculate(panels, date.fromisoformat(manifest["target_date"]))


def compare_previous(result: ProxyBrief, panels: dict, previous: Path) -> None:
    try:
        prior = ProxyBrief.model_validate_json(previous.read_text())
        if prior.status != "partial" or prior.requested_as_of >= result.requested_as_of:
            raise ValueError("Incompatible prior date/status")
        if sha256_file(previous.parent / "manifest.json") != prior.manifest_sha256:
            raise ValueError("Prior manifest changed")
        manifest, older = load_snapshot(previous.parent)
        if manifest["target_date"] != prior.requested_as_of.isoformat():
            raise ValueError("Prior report date does not match snapshot")
        for symbol in SYMBOLS:
            first = max(older[symbol].date.min(), panels[symbol].date.min())
            last = older[symbol].date.max()
            left = older[symbol].loc[older[symbol].date >= first, ["date", "adj_close"]].reset_index(drop=True)
            right = panels[symbol].loc[panels[symbol].date.between(first, last), ["date", "adj_close"]].reset_index(drop=True)
            if left.empty or not left.equals(right):
                result.comparison_note = "Overlapping adjusted-price revision or coverage change; comparison withheld."
                return
        old_metrics = calculate(older, prior.requested_as_of)
        for name, value in result.metrics.items():
            before = old_metrics[name]
            if value is not None and before is not None:
                result.changes[name] = {"previous": before, "current": value, "delta": value - before}
        result.comparison_note = f"Compared with {prior.requested_as_of}; same methodology, unchanged overlapping adjusted prices."
    except (OSError, ValueError, KeyError, TypeError):
        result.comparison_note = "Invalid, incompatible or corrupt previous proxy brief; comparison withheld."


def render_proxy(result: ProxyBrief) -> str:
    lines = [f"# ETF momentum proxy brief — {result.requested_as_of}", "",
             f"Status: **{result.status.upper()}** | Personal next-session research | Long-only ETF proxy", "",
             f"Generated: {result.generated_at.isoformat()}", "",
             "MTUM versus SPY; not the academic winner-minus-loser factor, not a crash probability, "
             "and not a measurement of actual crowding. No trading instruction.", "",
             "## Observations", "", "| Metric | Value |", "| --- | ---: |"]
    lines.extend(f"| {name} | {'unavailable' if value is None else format(value, '.2%')} |"
                 for name, value in result.metrics.items())
    if not result.metrics:
        lines.append("| Core assessment | withheld: required ETF data unavailable |")
    lines += ["", "Returns: adjusted close P[t]/P[t−n]−1. Relative returns: "
              "(1+MTUM return)/(1+SPY return)−1. Drawdown: last close / maximum of 252 closes −1. "
              "Volatility: sample standard deviation of 21 daily returns × √252.", "",
              "## VIX background", ""]
    if result.vix:
        lines.append(f"VIX: {result.vix['value']:g} index points; observation date {result.vix['observation_date']}; "
                     f"{'OLDER than target date — not filled forward' if result.vix['stale'] else 'matches target date'}.")
    else:
        lines.append("Unavailable; core ETF observations do not depend on VIX.")
    lines += ["", "## Data provenance", ""]
    for name, entry in result.sources.items():
        lines.append(f"- {name}: {entry['status']}; latest usable date {entry.get('latest_date', 'unavailable')}; "
                     f"fetched {entry.get('fetched_at', 'unavailable')}; {entry['source']}.")
    lines += ["", "## Changes from previous brief", "", result.comparison_note, ""]
    lines.extend(f"- {name}: {item['previous']:.2%} → {item['current']:.2%} "
                 f"(change {100 * item['delta']:+.2f} percentage points)" for name, item in result.changes.items())
    lines += ["", "## Limitations", "", *[f"- {item}" for item in result.limitations], "",
              f"Calculation version: `{result.calculation_version}`. Manifest SHA256: `{result.manifest_sha256}`.", "",
              "Saved vendor-returned tables are not raw HTTP responses. The manifest links vendor and normalized file hashes.", ""]
    return "\n".join(lines)


def run_proxy_brief(requested: date | None, output: Path, previous: Path | None = None) -> ProxyBrief:
    as_of = target_date(requested)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    result = ProxyBrief(requested_as_of=as_of, limitations=[
        "Personal research only; public access does not grant commercial redistribution rights.",
        "ETF proxy, not the original engine or a user portfolio; no engine scores or calibrated crash probabilities.",
        "Vendor-adjusted histories can be revised; retrieval time does not establish historical publication-time/PIT availability.",
        "Missing sessions are not filled; insufficient windows produce unavailable metrics.",
    ])
    try:
        manifest = collect(output, as_of)
        result.manifest_sha256 = sha256_file(output / "manifest.json")
        result.sources = manifest["sources"]
        _, panels = load_snapshot(output)
        result.metrics = calculate(panels, as_of)
        result.status = "partial"
        optional = manifest["sources"]["VIXCLS"]
        if optional["status"] == "ok":
            try:
                path = checked_path(output, optional["normalized_path"], optional["normalized_sha256"])
                last = pd.read_parquet(path).iloc[-1]
                result.vix = {"value": float(last.vix), "observation_date": last.date.date().isoformat(),
                              "stale": last.date.date() < as_of}
            except (OSError, ValueError, KeyError, TypeError):
                result.sources["VIXCLS"] = {**optional, "status": "invalid_snapshot"}
                result.limitations.append("Optional VIX snapshot failed validation; VIX withheld.")
        if previous is not None:
            compare_previous(result, panels, previous)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result.status = "unavailable"
        result.metrics = {}
        result.limitations.append(f"Core snapshot unavailable or invalid ({type(exc).__name__}); assessment withheld.")
    (output / "brief.md").write_text(render_proxy(result), encoding="utf-8")
    save_json(output / "brief.json", result.model_dump(mode="json"))
    return result
