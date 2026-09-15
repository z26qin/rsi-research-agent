from __future__ import annotations

import json
from pathlib import Path

import pytest

from momentum_research_agent.config import find_project_root
from momentum_research_agent.tools.engine_pipeline import (
    WARM_TIMEOUT_S,
    run_pipeline,
)
from momentum_research_agent.tools.engine_query import engine_query
from momentum_research_agent.tools.registry import ToolContext, set_tool_context

ENGINE = find_project_root() / "fixtures" / "engine"


@pytest.fixture
def live_engine(monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("MOMENTUM_DISABLE_PIPELINE", raising=False)
    monkeypatch.setenv("MOMENTUM_ENGINE_DIR", str(ENGINE))
    monkeypatch.delenv("MOMENTUM_ENGINE_SNAPSHOT", raising=False)
    set_tool_context(ToolContext(project_root=find_project_root(), session_dir=None))
    return ENGINE


@pytest.mark.asyncio
async def test_engine_query_pipeline_pass_and_ignores_poisoned_snapshot(
    live_engine: Path,
) -> None:
    run_pipeline(
        "2026-05-29", project_root=find_project_root(), timeout_s=WARM_TIMEOUT_S
    )
    poison = (
        live_engine / "outputs" / "snapshot_2026-05-29" / "structured_snapshot.json"
    )
    poison.parent.mkdir(parents=True, exist_ok=True)
    poison.write_text(
        json.dumps(
            {
                "as_of_date": "2026-05-29",
                "overall_risk_state": "panic_elevated",
                "mechanical_unwind_state": "UNWIND",
            }
        ),
        encoding="utf-8",
    )
    try:
        raw = await engine_query("NVDA", end="2026-05-29")
        payload = json.loads(raw)
        assert payload["pipeline_run"] is True
        assert payload["delivery_contract"]["verdict"] == "pass"
        assert payload["delivery_contract"]["source"] == "run_mvp"
        assert payload["delivery_contract"]["delivery_hash"]
        assert payload["delivery_hash"] == payload["delivery_contract"]["delivery_hash"]
        assert payload["risk_state"] == "normal"
        assert payload["source"] == "run_mvp"
        assert "does not read structured_snapshot.json" in payload.get("note", "")
        assert payload["risk_state"] != "panic_elevated"
    finally:
        poison.unlink(missing_ok=True)
