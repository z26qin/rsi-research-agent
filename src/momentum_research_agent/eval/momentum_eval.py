"""Frozen DM eval cases. No DeepSeek. Failures write back to the gap ledger."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from momentum_research_agent.coordinator.gap_seed import append_gaps
from momentum_research_agent.eval.policy_suite import CaseResult
from momentum_research_agent.models.schemas import GapEntry, GapKind
from momentum_research_agent.state.prompt_memory import refresh_profile_hints
from momentum_research_agent.tools.engine_contract import verify_live_delivery
from momentum_research_agent.tools.engine_pipeline import WARM_TIMEOUT_S, run_pipeline
from momentum_research_agent.tools.engine_query import engine_query
from momentum_research_agent.tools.registry import ToolContext, set_tool_context


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    ticker: str
    end: str
    expect_pipeline: bool
    expect_verdict: str
    expect_risk_state: str | None = None
    expect_fingerprint: str | None = None
    expect_delivery_hash: str | None = None


CASES = (
    EvalCase(
        case_id="dm-2026-05-29",
        ticker="NVDA",
        end="2026-05-29",
        expect_pipeline=True,
        expect_verdict="pass",
        expect_risk_state="normal",
        expect_fingerprint="a3fed64fc1d0d687",
        expect_delivery_hash="1a2d3c95609db4f7",
    ),
)


def _failures_from_result(case: EvalCase, payload: dict[str, Any] | None, error: str | None) -> list[GapEntry]:
    if error:
        return [
            GapEntry(
                kind=GapKind.ENGINE_MOCK,
                claim=f"eval {case.case_id} failed: {error}",
                notes="--eval writeback",
                evidence_id=f"eval:{case.case_id}",
            )
        ]
    assert payload is not None
    contract = payload.get("delivery_contract") if isinstance(payload.get("delivery_contract"), dict) else {}
    problems: list[str] = []
    if case.expect_pipeline and payload.get("pipeline_run") is not True:
        problems.append("pipeline_run was not True")
    if contract.get("verdict") != case.expect_verdict:
        problems.append(
            f"V_D verdict {contract.get('verdict')!r} != {case.expect_verdict!r}"
        )
    if case.expect_risk_state and payload.get("risk_state") != case.expect_risk_state:
        problems.append(
            f"risk_state {payload.get('risk_state')!r} != {case.expect_risk_state!r}"
        )
    if payload.get("as_of") != case.end:
        problems.append(f"as_of {payload.get('as_of')!r} != {case.end!r}")
    if (
        contract.get("as_of") != case.end
        or contract.get("requested_as_of") != case.end
    ):
        problems.append("V_D as-of fields do not match the pinned case")
    fingerprint = str(contract.get("fingerprint") or "")
    if len(fingerprint) < 8 or fingerprint != payload.get("full_run_fingerprint"):
        problems.append("V_D fingerprint is missing or inconsistent")
    if case.expect_fingerprint and fingerprint != case.expect_fingerprint:
        problems.append(
            f"fingerprint {fingerprint!r} != {case.expect_fingerprint!r}"
        )
    delivery_hash = str(contract.get("delivery_hash") or "")
    if not delivery_hash or delivery_hash != payload.get("delivery_hash"):
        problems.append("V_D delivery hash is missing or inconsistent")
    if case.expect_delivery_hash and delivery_hash != case.expect_delivery_hash:
        problems.append(
            f"delivery hash {delivery_hash!r} != {case.expect_delivery_hash!r}"
        )
    if not problems:
        return []
    return [
        GapEntry(
            kind=GapKind.ENGINE_MOCK,
            claim=f"eval {case.case_id}: " + "; ".join(problems),
            notes="--eval writeback",
            evidence_id=f"eval:{case.case_id}",
        )
    ]


async def run_eval_case(case: EvalCase, project_root: Path) -> dict[str, Any]:
    set_tool_context(ToolContext(project_root=project_root, session_dir=None))
    try:
        raw = await engine_query(case.ticker, end=case.end)
        payload = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 — eval must write back any failure
        payload = None
        error = f"{type(exc).__name__}: {exc}"
    else:
        error = None
    gaps = _failures_from_result(case, payload, error)
    if gaps:
        append_gaps(project_root, gaps, session_id="eval")
        refresh_profile_hints(
            project_root,
            extra_failures=[
                {
                    "id": f"eval:{case.case_id}",
                    "text": gaps[0].claim,
                    "capability": "engine_freshness",
                }
            ],
        )
    return {
        "case_id": case.case_id,
        "ok": not gaps,
        "payload": payload,
        "error": error,
        "gaps": [item.model_dump(mode="json") for item in gaps],
    }


async def run_eval(project_root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in CASES:
        results.append(await run_eval_case(case, project_root))
    return results


async def run_offline_engine_eval(root: Path) -> list[dict[str, Any]]:
    """Run pinned engine guards against one explicit fixture root, with no fallback."""
    results: list[dict[str, Any]] = []
    with TemporaryDirectory(prefix="momentum-offline-engine-") as raw_cache:
        cache_dir = Path(raw_cache)
        for case in CASES:
            run = await asyncio.to_thread(
                run_pipeline,
                case.end,
                timeout_s=WARM_TIMEOUT_S,
                cache_dir=cache_dir,
                engine_root=root,
                offline=True,
            )
            if not run.ok or run.assessment is None:
                payload = None
                error = run.error or "offline engine wrote no assessment"
            else:
                contract = verify_live_delivery(run.assessment, case.end)
                payload = {
                    "as_of": str(run.assessment.get("as_of_date") or "")[:10],
                    "risk_state": run.assessment.get("overall_risk_state"),
                    "pipeline_run": contract.pipeline_run,
                    "full_run_fingerprint": run.assessment.get(
                        "full_run_fingerprint"
                    ),
                    "delivery_hash": contract.delivery_hash,
                    "delivery_contract": contract.model_dump(mode="json"),
                }
                error = None
            gaps = _failures_from_result(case, payload, error)
            results.append(
                {
                    "case_id": case.case_id,
                    "ok": not gaps,
                    "payload": payload,
                    "error": error,
                    "gaps": [item.model_dump(mode="json") for item in gaps],
                }
            )
    return results


def run_eval_sync(project_root: Path) -> list[dict[str, Any]]:
    return asyncio.run(run_eval(project_root))


def engine_case_results(results: list[dict[str, Any]]) -> list[CaseResult]:
    """Adapt frozen eval outcomes into fail-closed engine guard results."""
    cases: list[CaseResult] = []
    for index, result in enumerate(results):
        case_id = result.get("case_id")
        valid_case_id = isinstance(case_id, str) and bool(case_id.strip())
        valid_payload = isinstance(result.get("payload"), dict)
        valid_gaps = isinstance(result.get("gaps"), list)
        no_gaps = valid_gaps and not result["gaps"]
        passed = (
            valid_case_id
            and result.get("ok") is True
            and valid_payload
            and result.get("error") is None
            and no_gaps
        )
        resolved_case_id = case_id if valid_case_id else f"engine:invalid-{index}"
        if passed:
            failures: list[str] = []
        elif not valid_payload:
            failures = ["invalid engine eval payload"]
        elif not valid_case_id or not valid_gaps:
            failures = ["invalid engine eval result"]
        elif result.get("error"):
            failures = [f"engine eval failed: {result['error']}"]
        elif result["gaps"]:
            failures = ["engine eval reported gaps"]
        else:
            failures = ["engine eval did not pass"]
        cases.append(
            CaseResult(
                case_id=resolved_case_id,
                layer="engine",
                passed=passed,
                score=1.0 if passed else 0.0,
                failures=failures,
            )
        )
    return cases
