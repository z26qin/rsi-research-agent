"""Small real panels test coverage gates, not upstream model mechanics."""

import json
import os
import subprocess
import sys

import pandas as pd
import pytest


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.delenv("MOMENTUM_DISABLE_PIPELINE", raising=False)
    root = tmp_path / "engine"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts/run_monitor.py").write_text("# test engine entry point\n")
    data = root / "data" / "processed"
    data.mkdir(parents=True)
    for name in (
        "market_features",
        "leg_risk_history",
        "sp500_prices",
        "sp500_benchmark",
        "french_research_factors_daily",
        "momentum_labels_h5",
        "momentum_labels_h20",
    ):
        pd.DataFrame({"date": ["2026-05-28", "2026-05-29"]}).to_parquet(
            data / f"{name}.parquet"
        )
    pd.DataFrame(
        {"effective_month": ["2026-05"], "formation_date": ["2026-04-30"]}
    ).to_parquet(data / "momentum_portfolio_holdings.parquet")
    pd.DataFrame({"as_of_date": ["2026-07-24"]}).to_parquet(
        data / "sp500_universe.parquet"
    )
    return root


@pytest.fixture
def assessment():
    return {
        "schema_version": "hermes-monitor-v1",
        "as_of_date": "2026-05-29",
        "data_cutoff": "2026-05-29T16:00:00-04:00",
        "overall_risk_state": "normal",
        "mechanical_unwind_state": "FRAGILITY_BUILDING",
        "full_run_fingerprint": "abcdefgh12345678",
        "mechanism_scores": {
            "crowded_unwind": 96,
            "dm_recovery": 45,
            "book_vulnerability": 56,
            "fundamental_repricing": None,
        },
        "monitoring_severity_score": 96,
        "score_is_probability": False,
        "score_formula": "prior-only percentile",
        "pm_posture": "escalate_for_pm_review",
    }


def test_cli_success_through_real_subprocess_boundary(engine, tmp_path, assessment):
    # Synthetic engine executable exercises CLI->offline subprocess->artifacts;
    # separate manual historical smokes validate the real bundled engine.
    (engine / "scripts/run_monitor.py").write_text(
        "import argparse, json\nfrom pathlib import Path\n"
        "p=argparse.ArgumentParser()\np.add_argument('--as-of-date')\n"
        "p.add_argument('--output-json')\na=p.parse_args()\n"
        f"payload=json.loads({json.dumps(assessment)!r})\n"
        "assert a.as_of_date == payload['as_of_date']\n"
        "Path(a.output_json).write_text(json.dumps(payload))\n"
    )
    output = tmp_path / "brief"
    env = {**os.environ, "MOMENTUM_ENGINE_DIR": str(engine), "DEEPSEEK_API_KEY": ""}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "momentum_research_agent.cli",
            "--daily-brief",
            "--as-of",
            "2026-05-29",
            "--session-dir",
            str(output),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads((output / "brief.json").read_text())
    assert payload["status"] == "partial"
    assert payload["metrics"]["crowded_unwind"]["value"] == 96
    assert (output / "engine_run/2026-05-29.json").is_file()
    assert payload["delivery_contract"]["verdict"] == "pass"
