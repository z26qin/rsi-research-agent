"""Deterministic, auditable market/book brief over one bounded engine run."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from momentum_research_agent.brief_readiness import inspect_inputs, sha256_file
from momentum_research_agent.tools.engine_contract import verify_live_delivery
from momentum_research_agent.tools.engine_pipeline import (
    WARM_TIMEOUT_S, bundled_engine_root, resolve_pipeline_root, run_pipeline,
)


class Metric(BaseModel):
    value: str | float | None
    source_field: str


class DailyBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["daily_brief_v1"] = "daily_brief_v1"
    scope: Literal["market/book"] = "market/book"
    requested_as_of: date
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: Literal["partial", "unavailable"] = "unavailable"
    source_kind: str = "unavailable"
    engine_root: str | None = None
    engine_code_sha256: str | None = None
    engine_fingerprint: str | None = None
    assessment_sha256: str | None = None
    data_cutoff: str | None = None
    readiness: dict = Field(default_factory=dict)
    delivery_contract: dict = Field(default_factory=dict)
    metrics: dict[str, Metric] = Field(default_factory=dict)
    changes: dict = Field(default_factory=dict)
    comparison_note: str = "No previous brief supplied."
    limitations: list[str] = Field(default_factory=list)
    llm_requests: Literal[0] = 0


def engine_code_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for directory in ("src", "scripts", "config", "configs"):
        for path in sorted((root / directory).rglob("*")):
            if path.is_file() and path.suffix in {".py", ".json", ".yaml", ".yml", ".toml"}:
                digest.update(str(path.relative_to(root)).encode())
                digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def extract_metrics(assessment: dict, as_of: date) -> dict[str, Metric]:
    if assessment.get("schema_version") != "hermes-monitor-v1":
        raise ValueError("Unsupported engine schema")
    if verify_live_delivery(assessment, as_of.isoformat()).verdict != "pass":
        raise ValueError("Invalid engine delivery")
    cutoff = datetime.fromisoformat(assessment["data_cutoff"])
    expected = datetime.combine(as_of, time(16), ZoneInfo("America/New_York"))
    if cutoff.tzinfo is None or cutoff != expected or cutoff > datetime.now(timezone.utc):
        raise ValueError("Invalid cutoff")
    if assessment.get("score_is_probability") is not False:
        raise ValueError("Unspecified score semantics")
    metrics = {}
    for name in ("overall_risk_state", "mechanical_unwind_state", "pm_posture"):
        value = assessment.get(name)
        if value is not None and not isinstance(value, str):
            raise ValueError("Invalid state")
        metrics[name] = Metric(value=value, source_field=f"/{name}")
    scores = assessment.get("mechanism_scores")
    if not isinstance(scores, dict):
        raise ValueError("Invalid mechanism scores")
    for name in ("monitoring_severity_score", "crowded_unwind", "dm_recovery",
                 "book_vulnerability", "fundamental_repricing"):
        top = name == "monitoring_severity_score"
        value = assessment.get(name) if top else scores.get(name)
        if value is not None and (type(value) not in (int, float)
                                  or not math.isfinite(value) or not 0 <= value <= 100):
            raise ValueError("Invalid score")
        metrics[name] = Metric(value=value, source_field=f"/{name}" if top else f"/mechanism_scores/{name}")
    return metrics


def _compare(brief: DailyBrief, assessment: dict, previous: Path) -> None:
    try:
        prior = DailyBrief.model_validate_json(previous.read_text())
        source = previous.parent / "assessment.json"
        if prior.status != "partial" or prior.requested_as_of >= brief.requested_as_of:
            raise ValueError("Previous date or status incompatible")
        if prior.requested_as_of.replace(day=1) != brief.requested_as_of.replace(day=1):
            raise ValueError("Active holdings month changed")
        if not prior.engine_code_sha256 or prior.engine_code_sha256 != brief.engine_code_sha256:
            raise ValueError("Engine changed")
        if sha256_file(source) != prior.assessment_sha256:
            raise ValueError("Previous source changed")
        old = json.loads(source.read_text())
        for key in ("score_formula", "schema_version"):
            if not assessment.get(key) or old.get(key) != assessment[key]:
                raise ValueError("Score definitions differ")
        for name in ("momentum_portfolio_holdings.parquet", "sp500_universe.parquet"):
            if (prior.readiness["inputs"][name]["sha256"] !=
                    brief.readiness["inputs"][name]["sha256"]):
                raise ValueError("Book/universe changed")
        old_metrics = extract_metrics(old, prior.requested_as_of)
        for name, current in brief.metrics.items():
            before = old_metrics[name].value
            if before is None or current.value is None:
                continue
            change = {"previous": before, "current": current.value,
                      "source_field": current.source_field}
            if isinstance(before, float) and isinstance(current.value, float):
                change["delta"] = current.value - before
            brief.changes[name] = change
        brief.comparison_note = f"Compared with {prior.requested_as_of} ({previous.resolve()}); " \
                                "same engine, score definition, holdings and universe fingerprints."
    except (OSError, ValueError, KeyError, TypeError):
        brief.comparison_note = "Previous brief is invalid or not comparable; changes withheld."
        brief.limitations.append(brief.comparison_note)


def render_brief(brief: DailyBrief) -> str:
    lines = [f"# Momentum daily brief — {brief.requested_as_of}", "",
             f"Status: **{brief.status.upper()}** | Scope: market/book | Source: {brief.source_kind}", "",
             f"Generated: {brief.generated_at.isoformat()}", "",
             f"Engine data cutoff: {brief.data_cutoff or 'unavailable'}", "",
             "Historical/as-of assessment, not a real-time feed. A normal DM state does not establish low overall risk.", "",
             "Scores are engine monitoring scores (0–100), not a crash probability. No trading instruction.", "",
             "## Engine observations", "", "| Field | Value | Source field in assessment.json |",
             "| --- | --- | --- |"]
    for name, metric in brief.metrics.items():
        value = "unavailable" if metric.value is None else str(metric.value)
        value = value.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {name} | {value} | `{metric.source_field}` |")
    if not brief.metrics:
        lines.append("| Assessment | withheld | readiness/delivery failed |")
    lines += ["", "## Changes", "", brief.comparison_note, ""]
    for name, change in brief.changes.items():
        lines.append(f"- {name}: {change['previous']} → {change['current']}"
                     + (f" (delta {change['delta']:+g})" if "delta" in change else ""))
    lines += ["", "## Input coverage", "", "| Panel | Latest | At/before requested date | Status |",
              "| --- | --- | --- | --- |"]
    for name, item in brief.readiness.get("inputs", {}).items():
        lines.append(f"| {name} | {item['latest_date']} | {item['latest_on_or_before']} | {item['status']} |")
    lines += ["", "## Limitations and next checks", ""]
    lines.extend(f"- {item}" for item in brief.limitations)
    lines += ["", "## Audit", "", f"Engine fingerprint: `{brief.engine_fingerprint}`",
              f"Assessment SHA256: `{brief.assessment_sha256}`", "",
              "See brief.json for input hashes, delivery checks and source metadata. "
              "Validation covers delivery and score structure, not independent research truth.", ""]
    return "\n".join(lines)


def run_daily_brief(project_root: Path, as_of: date, output_dir: Path,
                    previous: Path | None = None) -> DailyBrief:
    """New output directory only; no retries, model, policy changes or data fetching."""
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    brief = DailyBrief(requested_as_of=as_of)
    brief.limitations = ["Market/book context is not ticker-specific or the user's portfolio risk.",
                         "No calibrated crash probability or independent fundamental/news confirmation."]
    try:
        if as_of > datetime.now(timezone.utc).date():
            raise ValueError("Future assessment date")
        root = resolve_pipeline_root(project_root)
        if root is None:
            raise ValueError("Engine unavailable or disabled")
        brief.engine_root = str(root.resolve())
        brief.source_kind = ("bundled historical engine" if root.resolve() == bundled_engine_root(project_root).resolve()
                             else "configured engine, cached inputs")
        brief.engine_code_sha256 = engine_code_hash(root)
        brief.readiness = inspect_inputs(root, as_of)
        brief.limitations.extend(brief.readiness["limitations"])
        if not brief.readiness["ready"]:
            raise ValueError("Input coverage unavailable")
        run = run_pipeline(as_of.isoformat(), project_root=project_root, engine_root=root,
                           timeout_s=WARM_TIMEOUT_S, cache_dir=output_dir / "engine_run", offline=True)
        if not run.ok or run.assessment is None:
            raise ValueError("Engine run unavailable (failed or timed out)")
        assessment = run.assessment
        source = output_dir / "assessment.json"
        source.write_text(json.dumps(assessment, indent=2, allow_nan=False) + "\n")
        brief.assessment_sha256 = sha256_file(source)
        brief.delivery_contract = verify_live_delivery(assessment, as_of.isoformat()).model_dump()
        metrics = extract_metrics(assessment, as_of)
        panel_names = {path.name for path in (root / "data/processed").glob("*.parquet")}
        if (panel_names != set(brief.readiness["inputs"]) or
            engine_code_hash(root) != brief.engine_code_sha256 or any(
            sha256_file(Path(item["path"])) != item["sha256"] for item in brief.readiness["inputs"].values()
        )):
            raise ValueError("Engine inputs or code changed during run")
        brief.engine_fingerprint = assessment["full_run_fingerprint"]
        brief.data_cutoff = assessment["data_cutoff"]
        brief.metrics = metrics
        brief.status = "partial"  # Cached panels lack publication-time/PIT certification.
        for name, metric in metrics.items():
            if metric.value is None:
                brief.limitations.append(f"Missing metric: {name}; not imputed.")
        if previous is not None:
            _compare(brief, assessment, previous)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        brief.status = "unavailable"
        brief.metrics = {}
        # Keep local diagnostics useful without forwarding subprocess/provider output.
        reason = str(exc) if type(exc) is ValueError and str(exc) in {
            "Future assessment date", "Engine unavailable or disabled", "Input coverage unavailable",
            "Engine run unavailable (failed or timed out)", "Engine inputs or code changed during run",
        } else f"Assessment validation failed ({type(exc).__name__})"
        brief.limitations.append(reason + "; assessment withheld.")
    (output_dir / "brief.md").write_text(render_brief(brief))
    (output_dir / "brief.json").write_text(brief.model_dump_json(indent=2) + "\n")
    return brief
