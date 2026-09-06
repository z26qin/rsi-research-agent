from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from momentum_research_agent import cli
from momentum_research_agent.config import find_project_root
from momentum_research_agent.eval import momentum_eval
from momentum_research_agent.eval.momentum_eval import (
    CASES,
    EvalCase,
    engine_case_results,
    run_eval_case,
    run_offline_engine_eval,
)
from momentum_research_agent.eval.policy_improver import FailureBundle
from momentum_research_agent.models.schemas import MomentumCapability
from momentum_research_agent.state.policies import PolicyPatch, PolicyStore, ToolPolicy
from momentum_research_agent.tools.engine_pipeline import WARM_TIMEOUT_S, run_pipeline
from momentum_research_agent.tools.registry import ToolContext, set_tool_context

ENGINE = find_project_root() / "fixtures" / "engine"


class FixingGenerator:
    model = "fake-policy-model"

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, bundle: FailureBundle) -> PolicyPatch:
        self.calls += 1
        assert set(bundle.failed_case_ids) == {
            "trajectory:stale-engine",
            "trajectory:source-quality",
            "trajectory:crowding-web-search",
        }
        return PolicyPatch(
            prompt_overlays={
                "momentum_analyst": "Use an explicit as-of date.",
                "technicals_analyst": "Require a primary source.",
            },
            task_templates={
                MomentumCapability.ENGINE_FRESHNESS: "Do not retry the failed call.",
                MomentumCapability.SOURCE_QUALITY: "Find the primary filing.",
            },
            tool_policies=[
                ToolPolicy(
                    profile="momentum_analyst",
                    capability=MomentumCapability.ENGINE_FRESHNESS,
                    required_tools=["engine_query"],
                ),
                ToolPolicy(
                    profile="technicals_analyst",
                    capability=MomentumCapability.SOURCE_QUALITY,
                    required_tools=["web_search"],
                ),
                ToolPolicy(
                    profile="flow_analyst",
                    capability=MomentumCapability.CROWDING,
                    required_tools=["web_search"],
                ),
            ],
        )


def passing_offline_eval() -> list[dict]:
    return [
        {
            "case_id": "dm-2026-05-29",
            "ok": True,
            "payload": {
                "as_of": "2026-05-29",
                "risk_state": "normal",
                "pipeline_run": True,
                "full_run_fingerprint": "a3fed64fc1d0d687",
                "delivery_hash": "0123456789abcdef",
                "delivery_contract": {
                    "verdict": "pass",
                    "as_of": "2026-05-29",
                    "requested_as_of": "2026-05-29",
                    "fingerprint": "a3fed64fc1d0d687",
                    "delivery_hash": "0123456789abcdef",
                },
            },
            "error": None,
            "gaps": [],
        }
    ]


def test_improve_flag_is_explicit_and_mutually_exclusive_with_eval() -> None:
    parser = cli.build_parser()
    assert parser.parse_args(["--eval"]).run_eval is True
    assert parser.parse_args(["--eval"]).improve is False
    assert parser.parse_args(["--improve"]).improve is True
    with pytest.raises(SystemExit) as rejected:
        parser.parse_args(["--eval", "--improve"])
    assert rejected.value.code == 2


@pytest.mark.asyncio
async def test_eval_never_constructs_llm_candidate_generator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_eval = AsyncMock(return_value=[])
    construct = Mock(side_effect=AssertionError("--eval must not construct a generator"))
    monkeypatch.setattr(cli, "run_eval", run_eval, raising=False)
    monkeypatch.setattr(cli, "LLMCandidateGenerator", construct, raising=False)

    assert await cli.async_main(cli.build_parser().parse_args(["--eval"])) == 0
    run_eval.assert_awaited_once()
    construct.assert_not_called()


@pytest.mark.asyncio
async def test_improve_runs_real_one_cycle_with_fake_generator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = FixingGenerator()
    monkeypatch.setattr(cli, "find_project_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "load_env", lambda _root: None)
    monkeypatch.setattr(
        cli,
        "run_offline_engine_eval",
        AsyncMock(return_value=passing_offline_eval()),
        raising=False,
    )
    monkeypatch.setattr(
        cli,
        "LLMCandidateGenerator",
        lambda **_kwargs: generator,
        raising=False,
    )

    result = await cli.async_main(cli.build_parser().parse_args(["--improve"]))

    assert result == 0
    assert generator.calls == 1
    assert PolicyStore(tmp_path).load_active().prompt_overlays[
        "momentum_analyst"
    ] == "Use an explicit as-of date."


@pytest.mark.asyncio
async def test_improve_missing_fixtures_reject_before_generator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = FixingGenerator()
    monkeypatch.setattr(cli, "find_project_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "load_env", lambda _root: None)
    monkeypatch.setattr(cli, "bundled_engine_root", lambda _root: tmp_path / "missing")
    monkeypatch.setattr(cli, "LLMCandidateGenerator", lambda **_kwargs: generator)

    result = await cli.async_main(cli.build_parser().parse_args(["--improve"]))

    assert result == 1
    assert generator.calls == 0


@pytest.mark.asyncio
async def test_improve_reports_missing_key_only_when_generation_is_needed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "find_project_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "load_env", lambda _root: None)
    monkeypatch.setattr(
        cli,
        "run_offline_engine_eval",
        AsyncMock(return_value=passing_offline_eval()),
        raising=False,
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    result = await cli.async_main(cli.build_parser().parse_args(["--improve"]))

    assert result == 2
    output = capsys.readouterr().out
    assert "DEEPSEEK_API_KEY is not set" in output
    assert "api_key=" not in output


@pytest.mark.asyncio
async def test_offline_eval_forces_subprocess_and_blocks_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = tmp_path / "engine"
    script = engine / "scripts" / "run_monitor.py"
    script.parent.mkdir(parents=True)
    script.write_text(
        """from __future__ import annotations
import argparse
import json
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--as-of-date')
parser.add_argument('--output-json')
args = parser.parse_args()
try:
    urllib.request.urlopen('https://example.invalid')
except RuntimeError as error:
    assert 'network disabled' in str(error)
else:
    raise SystemExit('network was not blocked')
payload = {
    'as_of_date': args.as_of_date,
    'overall_risk_state': 'normal',
    'mechanical_unwind_state': 'NORMAL',
    'full_run_fingerprint': 'offline12345678',
    'mechanism_scores': {},
}
path = Path(args.output_json)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload), encoding='utf-8')
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        momentum_eval,
        "CASES",
        (
            EvalCase(
                case_id="offline-test",
                ticker="NVDA",
                end="2026-05-29",
                expect_pipeline=True,
                expect_verdict="pass",
                expect_risk_state="normal",
                expect_fingerprint="offline12345678",
                expect_delivery_hash="a54c217b6c9289e8",
            ),
        ),
    )

    results = await run_offline_engine_eval(engine)

    assert results[0]["ok"] is True
    payload = results[0]["payload"]
    assert payload["delivery_contract"]["verdict"] == "pass"
    assert payload["delivery_contract"]["fingerprint"] == "offline12345678"
    assert payload["delivery_hash"] == payload["delivery_contract"]["delivery_hash"]
    assert not (engine / "outputs").exists()


@pytest.mark.asyncio
async def test_eval_case_calls_engine_query_live_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MOMENTUM_DISABLE_PIPELINE", raising=False)
    monkeypatch.setenv("MOMENTUM_ENGINE_DIR", str(ENGINE))
    monkeypatch.delenv("MOMENTUM_ENGINE_SNAPSHOT", raising=False)
    set_tool_context(ToolContext(project_root=find_project_root(), session_dir=None))
    run_pipeline("2026-05-29", project_root=find_project_root(), timeout_s=WARM_TIMEOUT_S)
    case = CASES[0]
    result = await run_eval_case(case, find_project_root())
    assert result["ok"] is True
    payload = result["payload"]
    assert payload["pipeline_run"] is True
    assert payload["delivery_contract"]["verdict"] == "pass"
    assert payload["risk_state"] == "normal"
    json.dumps(payload)


def test_engine_case_results_converts_eval_outcomes_and_fails_invalid_payloads() -> None:
    results = engine_case_results(
        [
            {
                "case_id": "dm-2026-05-29",
                "ok": True,
                "payload": {"risk_state": "normal"},
                "error": None,
                "gaps": [],
            },
            {
                "case_id": "broken",
                "ok": True,
                "payload": None,
                "error": None,
                "gaps": [],
            },
            {"case_id": "failure", "ok": False, "payload": {}, "error": "boom", "gaps": []},
        ]
    )

    assert [(item.case_id, item.layer, item.passed, item.score) for item in results] == [
        ("dm-2026-05-29", "engine", True, 1.0),
        ("broken", "engine", False, 0.0),
        ("failure", "engine", False, 0.0),
    ]
    assert results[1].failures == ["invalid engine eval payload"]


def test_engine_case_results_rejects_success_claim_with_recorded_gaps() -> None:
    results = engine_case_results(
        [
            {
                "case_id": "inconsistent-success",
                "ok": True,
                "payload": {"risk_state": "normal"},
                "error": None,
                "gaps": [{"evidence_id": "eval:inconsistent-success"}],
            }
        ]
    )

    assert results[0].passed is False
    assert results[0].score == 0.0
    assert results[0].failures == ["engine eval reported gaps"]
