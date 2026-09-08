"""Small real panels test coverage gates, not upstream model mechanics."""
from datetime import date
import json
import os
import subprocess
import sys

import pandas as pd
import pytest

from momentum_research_agent import brief_readiness


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.delenv("MOMENTUM_DISABLE_PIPELINE", raising=False)
    root = tmp_path / "engine"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts/run_monitor.py").write_text("# test engine entry point\n")
    data = root / "data" / "processed"
    data.mkdir(parents=True)
    for name in ("market_features", "leg_risk_history", "sp500_prices", "sp500_benchmark",
                 "french_research_factors_daily", "momentum_labels_h5", "momentum_labels_h20"):
        pd.DataFrame({"date": ["2026-05-28", "2026-05-29"]}).to_parquet(data / f"{name}.parquet")
    pd.DataFrame({"effective_month": ["2026-05"], "formation_date": ["2026-04-30"]}).to_parquet(
        data / "momentum_portfolio_holdings.parquet")
    pd.DataFrame({"as_of_date": ["2026-07-24"]}).to_parquet(data / "sp500_universe.parquet")
    return root


def test_readiness_retains_actual_dates_and_future_universe_warning(engine):
    result = brief_readiness.inspect_inputs(engine, date(2026, 5, 29))
    assert result["ready"] is True
    record = result["inputs"]["market_features.parquet"]
    assert record["latest_date"] == "2026-05-29"
    assert record["latest_on_or_before"] == "2026-05-29"
    assert len(record["sha256"]) == 64
    assert any("universe" in item and "2026-07-24" in item for item in result["limitations"])


@pytest.mark.parametrize("values", [["2026-05-28"], ["2026-06-01"], ["not-a-date"], []])
def test_missing_exact_date_blocks_even_when_latest_date_is_newer(engine, values):
    pd.DataFrame({"date": values}).to_parquet(engine / "data/processed/market_features.parquet")
    assert brief_readiness.inspect_inputs(engine, date(2026, 5, 29))["ready"] is False


def test_missing_or_corrupt_panels_are_unavailable(engine):
    (engine / "data/processed/market_features.parquet").unlink()
    (engine / "data/processed/sp500_prices.parquet").write_bytes(b"invalid")
    result = brief_readiness.inspect_inputs(engine, date(2026, 5, 29))
    assert result["ready"] is False
    assert result["inputs"]["market_features.parquet"]["status"] == "missing"
    assert result["inputs"]["sp500_prices.parquet"]["status"] == "invalid"


def test_holdings_must_cover_month_without_future_formation(engine):
    path = engine / "data/processed/momentum_portfolio_holdings.parquet"
    pd.DataFrame({"effective_month": ["2026-05"], "formation_date": ["2026-05-30"]}).to_parquet(path)
    assert brief_readiness.inspect_inputs(engine, date(2026, 5, 29))["ready"] is False


def test_native_parquet_period_months_are_supported(engine):
    path = engine / "data/processed/momentum_portfolio_holdings.parquet"
    pd.DataFrame({"effective_month": pd.PeriodIndex(["2026-05"], freq="M"),
                  "formation_date": pd.to_datetime(["2026-04-30"])}).to_parquet(path)
    result = brief_readiness.inspect_inputs(engine, date(2026, 5, 29))
    assert result["ready"] is True
    assert result["inputs"][path.name]["latest_date"] == "2026-05-01"


@pytest.fixture
def assessment():
    return {"schema_version": "hermes-monitor-v1", "as_of_date": "2026-05-29",
            "data_cutoff": "2026-05-29T16:00:00-04:00", "overall_risk_state": "normal",
            "mechanical_unwind_state": "FRAGILITY_BUILDING", "full_run_fingerprint": "abcdefgh12345678",
            "mechanism_scores": {"crowded_unwind": 96, "dm_recovery": 45,
                                 "book_vulnerability": 56, "fundamental_repricing": None},
            "monitoring_severity_score": 96, "score_is_probability": False,
            "score_formula": "prior-only percentile", "pm_posture": "escalate_for_pm_review"}


def run_brief(engine, tmp_path, monkeypatch, assessment, **kwargs):
    from momentum_research_agent import daily_brief
    from momentum_research_agent.tools.engine_pipeline import PipelineRun
    monkeypatch.setenv("MOMENTUM_ENGINE_DIR", str(engine))
    monkeypatch.setattr(daily_brief, "run_pipeline", lambda *a, **k:
                        PipelineRun(True, assessment, None, False, engine, 0.1))
    return daily_brief.run_daily_brief(tmp_path, date(2026, 5, 29), tmp_path / "brief", **kwargs)


def test_brief_preserves_metrics_source_and_limitations(engine, tmp_path, monkeypatch, assessment):
    brief = run_brief(engine, tmp_path, monkeypatch, assessment)
    assert brief.status == "partial"
    assert brief.metrics["crowded_unwind"].value == 96
    assert brief.metrics["crowded_unwind"].source_field == "/mechanism_scores/crowded_unwind"
    assert brief.metrics["fundamental_repricing"].value is None
    assert brief.engine_fingerprint == "abcdefgh12345678"
    payload = json.loads((tmp_path / "brief/brief.json").read_text())
    assert payload["requested_as_of"] == "2026-05-29"
    assert payload["llm_requests"] == 0
    assert json.loads((tmp_path / "brief/assessment.json").read_text()) == assessment
    markdown = (tmp_path / "brief/brief.md").read_text()
    assert "2026-05-29T16:00:00-04:00" in markdown
    assert "not a crash probability" in markdown
    assert "market/book" in markdown
    assert "Missing metric: fundamental_repricing" in markdown


def test_stale_panels_do_not_run_engine(engine, tmp_path, monkeypatch):
    from momentum_research_agent import daily_brief
    monkeypatch.setenv("MOMENTUM_ENGINE_DIR", str(engine))
    def forbidden(*args, **kwargs):
        pytest.fail("stale inputs must stop before subprocess")
    monkeypatch.setattr(daily_brief, "run_pipeline", forbidden)
    result = daily_brief.run_daily_brief(tmp_path, date(2026, 9, 8), tmp_path / "brief")
    assert result.status == "unavailable"
    assert not result.metrics
    assert (tmp_path / "brief/brief.md").is_file()


@pytest.mark.parametrize("field,value", [("as_of_date", "2026-05-28"),
    ("overall_risk_state", "made_up"), ("full_run_fingerprint", None),
    ("monitoring_severity_score", float("nan")), ("score_is_probability", True),
    ("data_cutoff", "2026-06-01T16:00:00-04:00"),
    ("data_cutoff", "2026-05-29T16:00:00+00:00"),
    ("schema_version", "unknown"), ("mechanism_scores", []),
    ("mechanical_unwind_state", 12), ("monitoring_severity_score", 101)])
def test_invalid_assessment_withholds_metrics(engine, tmp_path, monkeypatch, assessment, field, value):
    assessment[field] = value
    result = run_brief(engine, tmp_path, monkeypatch, assessment)
    assert result.status == "unavailable"
    assert not result.metrics


@pytest.mark.parametrize("risk", ["normal", "bear_low_volatility", "panic_elevated"])
def test_all_engine_risk_states_are_preserved_without_invented_safety(engine, tmp_path, monkeypatch, assessment, risk):
    assessment["overall_risk_state"] = risk
    brief = run_brief(engine, tmp_path, monkeypatch, assessment)
    assert brief.status == "partial"
    assert brief.metrics["overall_risk_state"].value == risk


def test_failed_pipeline_persists_unavailable_without_leaking_error(engine, tmp_path, monkeypatch):
    from momentum_research_agent import daily_brief
    from momentum_research_agent.tools.engine_pipeline import PipelineRun
    monkeypatch.setenv("MOMENTUM_ENGINE_DIR", str(engine))
    monkeypatch.setattr(daily_brief, "run_pipeline", lambda *a, **k:
                        PipelineRun(False, None, "provider-secret", False, engine, 90))
    result = daily_brief.run_daily_brief(tmp_path, date(2026, 5, 29), tmp_path / "brief")
    assert result.status == "unavailable"
    assert "provider-secret" not in (tmp_path / "brief/brief.json").read_text()


def test_existing_output_never_overwritten(engine, tmp_path, monkeypatch, assessment):
    run_brief(engine, tmp_path, monkeypatch, assessment)
    before = (tmp_path / "brief/brief.json").read_bytes()
    with pytest.raises(FileExistsError):
        run_brief(engine, tmp_path, monkeypatch, assessment)
    assert (tmp_path / "brief/brief.json").read_bytes() == before


def test_compare_uses_original_artifact_not_edited_brief_metrics(engine, tmp_path, monkeypatch, assessment):
    from momentum_research_agent import daily_brief
    from momentum_research_agent.tools.engine_pipeline import PipelineRun
    monkeypatch.setenv("MOMENTUM_ENGINE_DIR", str(engine))
    old = {**assessment, "as_of_date": "2026-05-28", "data_cutoff": "2026-05-28T16:00:00-04:00",
           "mechanism_scores": {**assessment["mechanism_scores"], "crowded_unwind": 80}}
    monkeypatch.setattr(daily_brief, "run_pipeline", lambda *a, **k:
                        PipelineRun(True, old, None, False, engine, .1))
    daily_brief.run_daily_brief(tmp_path, date(2026, 5, 28), tmp_path / "prior")
    previous = tmp_path / "prior/brief.json"
    payload = json.loads(previous.read_text())
    payload["metrics"]["crowded_unwind"]["value"] = 0
    previous.write_text(json.dumps(payload))
    result = run_brief(engine, tmp_path, monkeypatch, assessment, previous=previous)
    assert result.changes["crowded_unwind"]["delta"] == 16
    assert result.changes["crowded_unwind"]["previous"] == 80
    assert "fundamental_repricing" not in result.changes


def test_invalid_previous_withholds_changes_not_current_report(engine, tmp_path, monkeypatch, assessment):
    previous = tmp_path / "missing/brief.json"
    result = run_brief(engine, tmp_path, monkeypatch, assessment, previous=previous)
    assert result.status == "partial"
    assert not result.changes
    assert "not comparable" in result.comparison_note


def test_input_change_during_run_withholds_assessment(engine, tmp_path, monkeypatch, assessment):
    from momentum_research_agent import daily_brief
    from momentum_research_agent.tools.engine_pipeline import PipelineRun
    monkeypatch.setenv("MOMENTUM_ENGINE_DIR", str(engine))
    def changing_run(*args, **kwargs):
        (engine / "data/processed/market_features.parquet").write_bytes(b"changed")
        return PipelineRun(True, assessment, None, False, engine, .1)
    monkeypatch.setattr(daily_brief, "run_pipeline", changing_run)
    result = daily_brief.run_daily_brief(tmp_path, date(2026, 5, 29), tmp_path / "brief")
    assert result.status == "unavailable"
    assert not result.metrics
    assert any("changed during run" in item for item in result.limitations)


def test_optional_panel_is_fingerprinted_and_mutation_rejected(engine, tmp_path, monkeypatch, assessment):
    from momentum_research_agent import daily_brief
    from momentum_research_agent.tools.engine_pipeline import PipelineRun
    optional = engine / "data/processed/unwind_structure_history.parquet"
    pd.DataFrame({"date": ["2026-05-29"], "downside_abnormal_volume_share_5d": [.8]}).to_parquet(optional)
    monkeypatch.setenv("MOMENTUM_ENGINE_DIR", str(engine))
    def changing_run(*args, **kwargs):
        optional.write_bytes(b"changed")
        return PipelineRun(True, assessment, None, False, engine, .1)
    monkeypatch.setattr(daily_brief, "run_pipeline", changing_run)
    result = daily_brief.run_daily_brief(tmp_path, date(2026, 5, 29), tmp_path / "brief")
    assert result.status == "unavailable"
    assert not result.metrics
    assert result.readiness["inputs"][optional.name]["sha256"]


def test_unchanged_multimonth_holdings_are_not_same_active_book(engine, tmp_path, monkeypatch, assessment):
    from momentum_research_agent import daily_brief
    from momentum_research_agent.tools.engine_pipeline import PipelineRun
    monkeypatch.setenv("MOMENTUM_ENGINE_DIR", str(engine))
    for name in brief_readiness.DAILY_PANELS:
        pd.DataFrame({"date": ["2026-04-30", "2026-05-29"]}).to_parquet(engine / "data/processed" / name)
    pd.DataFrame({"effective_month": ["2026-04", "2026-05"],
                  "formation_date": ["2026-03-31", "2026-04-30"],
                  "symbol": ["AAPL", "NVDA"]}).to_parquet(engine / "data/processed/momentum_portfolio_holdings.parquet")
    old = {**assessment, "as_of_date": "2026-04-30", "data_cutoff": "2026-04-30T16:00:00-04:00"}
    monkeypatch.setattr(daily_brief, "run_pipeline", lambda *a, **k:
                        PipelineRun(True, old, None, False, engine, .1))
    prior = daily_brief.run_daily_brief(tmp_path, date(2026, 4, 30), tmp_path / "prior")
    assert prior.status == "partial"
    result = run_brief(engine, tmp_path, monkeypatch, assessment, previous=tmp_path / "prior/brief.json")
    assert result.status == "partial"
    assert not result.changes
    assert "not comparable" in result.comparison_note


@pytest.mark.parametrize("args", [["--daily-brief"], ["--daily-brief", "--as-of", "2026-02-30"],
    ["--daily-brief", "--as-of", "2026-05-29", "--eval"],
    ["--as-of", "2026-05-29", "some research question"]])
def test_cli_rejects_incomplete_or_conflicting_brief_arguments(args, tmp_path):
    proc = subprocess.run([sys.executable, "-m", "momentum_research_agent.cli", *args],
                          capture_output=True, text=True, timeout=15)
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr


def test_cli_unavailable_persists_without_key_or_model(tmp_path):
    output = tmp_path / "brief"
    env = {**os.environ, "MOMENTUM_ENGINE_DIR": str(tmp_path / "missing"), "DEEPSEEK_API_KEY": ""}
    proc = subprocess.run([sys.executable, "-m", "momentum_research_agent.cli", "--daily-brief",
                           "--as-of", "2026-05-29", "--session-dir", str(output)],
                          env=env, capture_output=True, text=True, timeout=15)
    assert proc.returncode == 2
    payload = json.loads((output / "brief.json").read_text())
    assert payload["status"] == "unavailable"
    assert payload["llm_requests"] == 0
    assert "Traceback" not in proc.stderr


def test_cli_success_through_real_subprocess_boundary(engine, tmp_path, assessment):
    # Synthetic engine executable exercises CLI->offline subprocess->artifacts;
    # separate manual historical smokes validate the real bundled engine.
    (engine / "scripts/run_monitor.py").write_text(
        "import argparse, json\nfrom pathlib import Path\n"
        "p=argparse.ArgumentParser()\np.add_argument('--as-of-date')\n"
        "p.add_argument('--output-json')\na=p.parse_args()\n"
        f"payload=json.loads({json.dumps(assessment)!r})\n"
        "assert a.as_of_date == payload['as_of_date']\n"
        "Path(a.output_json).write_text(json.dumps(payload))\n")
    output = tmp_path / "brief"
    env = {**os.environ, "MOMENTUM_ENGINE_DIR": str(engine), "DEEPSEEK_API_KEY": ""}
    proc = subprocess.run([sys.executable, "-m", "momentum_research_agent.cli", "--daily-brief",
                           "--as-of", "2026-05-29", "--session-dir", str(output)],
                          env=env, capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads((output / "brief.json").read_text())
    assert payload["status"] == "partial"
    assert payload["metrics"]["crowded_unwind"]["value"] == 96
    assert (output / "engine_run/2026-05-29.json").is_file()
    assert payload["delivery_contract"]["verdict"] == "pass"
