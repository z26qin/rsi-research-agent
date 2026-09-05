from __future__ import annotations

import json

import pytest

from momentum_research_agent.config import find_project_root
from momentum_research_agent.eval.momentum_eval import CASES, engine_case_results, run_eval_case
from momentum_research_agent.tools.engine_pipeline import WARM_TIMEOUT_S, run_pipeline
from momentum_research_agent.tools.registry import ToolContext, set_tool_context

ENGINE = find_project_root() / "fixtures" / "engine"


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
