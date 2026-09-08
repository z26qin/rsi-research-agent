#!/usr/bin/env python3
"""One historical-data experiment; capture → human review → shadow comparison.

Usage: PYTHONPATH=src python scripts/feedback_experiment.py EXPERIMENT_DIR
Set DEEPSEEK_API_KEY in the process environment. See docs/feedback-experiment.md.
No production policy pointer or cross-session gap ledger is written.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path

from momentum_research_agent.agents.audit import static_audit
from momentum_research_agent.agents.budget import LoopBudget
from momentum_research_agent.agents.ledger import finalize_ledger
from momentum_research_agent.agents.sub_agent import SubAgent, load_profile
from momentum_research_agent.config import make_client
from momentum_research_agent.coordinator.task_board import TaskBoard
from momentum_research_agent.eval.live_compare import (
    assess_replay_run, load_cases_reference, load_expectations, run_live_compare,
)
from momentum_research_agent.eval.policy_improver import FailureBundle, LLMCandidateGenerator
from momentum_research_agent.eval.replay_runner import (
    LLMRequestBudget, LLMRequestBudgetExceeded, case_content_sha256, run_replay_case,
)
from momentum_research_agent.eval.session_cases import import_session_cases
from momentum_research_agent.state.policies import (
    PolicyPatch, PolicyStore, ResearchPolicy, _version_id, merge_policy_patch, validate_policy,
)
from momentum_research_agent.state.reports import persist_verification_report
from momentum_research_agent.tools import PROFILE_TOOLS
from momentum_research_agent.tools.engine_pipeline import run_pipeline

ROOT = Path(__file__).resolve().parents[1]
MODEL = "deepseek-v4-flash"
BUDGET = LoopBudget(max_turns=3, overall_deadline_s=120, llm_timeout_s=40, tool_timeout_s=15)
QUESTION = (
    "Use engine_query(ticker='SPY', end='2026-05-29') to assess momentum tail risk "
    "as of that historical date. Separate market-level regime evidence from "
    "ticker-specific crowding/unwind evidence. Cite only observed facts and "
    "explicitly identify what the engine cannot establish."
)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


@contextmanager
def locked(folder):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "experiment.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class BoundedClient:
    """One persisted 20-attempt allowance shared by every phase, retries disabled."""

    def __init__(self, raw, folder, state):
        self.raw = raw.with_options(max_retries=0)
        self.folder, self.state = folder, state
        self.chat = self.completions = self

    def with_options(self, **kwargs):
        return self

    async def create(self, **kwargs):
        if self.state["attempts"] >= 20:
            raise LLMRequestBudgetExceeded("experiment request budget exhausted")
        self.state["attempts"] += 1
        save(self.folder / "state.json", self.state)  # Reserve before sending, even on failure.
        kwargs["max_tokens"] = min(kwargs.get("max_tokens", 2048), 2048)
        kwargs["timeout"] = min(kwargs.get("timeout", 40), 40)
        response = await asyncio.wait_for(self.raw.chat.completions.create(**kwargs), 40)
        choice = response.choices[0] if response.choices else None
        message = getattr(choice, "message", None)
        save(self.folder / "responses" / f"{self.state['attempts']}.json", {
            "model": getattr(response, "model", None),
            "finish_reason": getattr(choice, "finish_reason", None),
            "content": getattr(message, "content", None),
        })  # Preserve incomplete output too, without request headers or provider errors.
        if not response.choices or response.choices[0].finish_reason not in {"stop", "tool_calls"}:
            raise ValueError("incomplete model response")
        return response


def prompt_only(patch, profile):
    validate_policy(patch, {name: tools for name, tools in PROFILE_TOOLS.items() if name != "verifier"})
    if (patch.task_templates or patch.tool_policies or set(patch.prompt_overlays) != {profile}
            or not patch.prompt_overlays[profile].strip() or len(patch.prompt_overlays[profile]) > 1000):
        raise ValueError("experiment permits one nonempty target-profile overlay, at most 1000 characters")


async def capture(folder, client, state):
    # Pin the bundled historical engine explicitly; never silently collect fallback data.
    os.environ["MOMENTUM_ENGINE_DIR"] = str(ROOT / "fixtures" / "engine")
    engine = await asyncio.to_thread(run_pipeline, "2026-05-29", project_root=ROOT,
                                     engine_root=ROOT / "fixtures" / "engine", offline=True, timeout_s=90)
    if not engine.ok:
        raise ValueError("historical engine unavailable")
    source_store = PolicyStore(ROOT)
    if source_store.active_path.exists():
        baseline = source_store.load_version(read(source_store.active_path)["version_id"])
    else:
        baseline = ResearchPolicy(version_id=_version_id(PolicyPatch(), None, []))
    PolicyStore(folder).write_version(baseline)  # Immutable copy, no active pointer.
    save(folder / "baseline.json", baseline.model_dump(mode="json"))
    session = folder / "session"
    save(session / "policy_snapshot.json", baseline.model_dump(mode="json"))
    profile = "momentum_analyst"
    (folder / "profiles").mkdir(exist_ok=True)
    (folder / "profiles" / f"{profile}.md").write_text(
        load_profile(profile, ROOT, apply_overlay=False), encoding="utf-8")
    board = TaskBoard(session, question=QUESTION)
    task = board.add_task("Historical momentum risk", QUESTION, profile)
    board.activate(task.id)
    result = await SubAgent(client, MODEL, ROOT, budget=BUDGET, policy=baseline).run(
        task, ["engine_query"], session)
    board.record_usage(task.id, tool_calls=result.tool_calls)
    board.complete(task.id)
    # A successful warm-up does not guarantee the later tool call used that data.
    if not result.traces or any(trace.truncated or trace.replay.source != "run_mvp"
            or trace.replay.as_of != "2026-05-29"
            or json.loads(trace.observation).get("delivery_contract", {}).get("verdict") != "pass"
            for trace in result.traces):
        state["status"] = "unscorable_capture"
        return
    audit = finalize_ledger(static_audit(QUESTION, [result.report]), [result.report], result.traces)
    persist_verification_report(session, audit)
    cases = import_session_cases(folder, session)
    save(folder / "captured-cases.json", [case.model_dump(mode="json") for case in cases])
    state["status"] = "review_required" if cases else "no_failure_found"
    state["audit"] = "static_only; gaps are hypotheses, not human-confirmed failures"
    state["replayable_cases"] = sum(case.replayable for case in cases)


async def compare(folder, client, state):
    # Human supplies two genuine imported occurrences and hash-bound expectations.
    cases = load_cases_reference(folder, folder / "reviewed-cases.json")
    expectations = load_expectations(folder / "expectations.json")
    if len(cases) != 2 or len(expectations.expectations) != 2:
        raise ValueError("review must select exactly one target and one guard")
    bound = expectations.bind_cases(cases)
    if {item.kind for item in bound.values()} != {"target", "guard"}:
        raise ValueError("review requires target and guard")
    target = next(case for case in cases if bound[case.case_id].kind == "target")
    captured = {case_content_sha256(case) for case in load_cases_reference(folder, folder / "captured-cases.json")}
    if case_content_sha256(target) not in captured:
        raise ValueError("target must be an unchanged captured failure occurrence")
    baseline = ResearchPolicy.model_validate(read(folder / "baseline.json"))
    PolicyStore(folder).write_version(baseline)  # Validates immutable content hash.
    if any(not case.replayable or case.policy_version_id != baseline.version_id for case in cases):
        raise ValueError("both cases must be replayable and originate under the pinned baseline")
    if any(case.profile != target.profile for case in cases):
        raise ValueError("lightweight guard must exercise the same profile as the target")
    # Establish a failed target and passing guard before spending the single reflection.
    preflight = []
    for case in cases:
        run = await run_replay_case(client=client, requested_model=MODEL, project_root=folder,
            case=case, policy=baseline, budget=BUDGET, request_budget=LLMRequestBudget(20),
            max_output_tokens=2048)
        assessed = assess_replay_run(run, bound[case.case_id])
        preflight.append({"run": run.model_dump(mode="json"), "assessment": assessed.model_dump(mode="json")})
    save(folder / "preflight.json", preflight)
    for case, item in zip(cases, preflight):
        assessment = item["assessment"]
        if assessment["unscorable"] or item["run"]["outcome"] != "success":
            state["status"] = "unscorable"
            return
        if assessment["passed"] != (bound[case.case_id].kind == "guard"):
            state["status"] = "target_not_reproduced_or_guard_failed"
            return
    target_result = next(item for case, item in zip(cases, preflight) if case.case_id == target.case_id)
    reviewed_feedback = json.dumps({
        "expectation": bound[target.case_id].model_dump(mode="json"),
        "failed_baseline_report": target_result["run"]["report"],
    }, sort_keys=True)
    if len(reviewed_feedback) > 12000:
        raise ValueError("reviewed target feedback exceeds this small experiment's input bound")
    bundle = FailureBundle(active_policy=baseline, failed_case_ids=[target.case_id],
        case_failures={target.case_id: target_result["assessment"]["violations"] +
                       ["Return only one prompt_overlays entry for this profile; no templates or tool policies."]},
        case_profiles={target.case_id: target.profile}, case_capabilities={target.case_id: target.capability},
        verifier_gaps=[target.failing_evidence],
        recorded_observations={"reviewed_target_feedback": reviewed_feedback,
            **{trace.id: trace.observation[:1000] for trace in target.tool_traces}})
    state["reflection_attempted"] = True
    save(folder / "state.json", state)
    patch = await LLMCandidateGenerator(client=client, model=MODEL, timeout_s=40).generate(bundle)
    prompt_only(patch, target.profile)
    candidate = merge_policy_patch(baseline, patch, trigger_ids=[target.case_id])
    if candidate.prompt_overlays == baseline.prompt_overlays:
        state["status"] = "no_change"
        return
    save(folder / "candidate.json", candidate.model_dump(mode="json"))
    report, path = await run_live_compare(client=client, requested_model=MODEL, project_root=folder,
        baseline_policy=baseline, candidate_policy=candidate, cases=cases, expectations=expectations,
        repeats=1, max_cases=2, request_budget=LLMRequestBudget(20), max_output_tokens=2048, budget=BUDGET)
    state.update(status="shadow_complete" if report.outcome == "completed" else "shadow_failed",
                 comparison=str(path), comparison_reasons=report.reasons, promoted=False)


async def run(folder, raw):
    with locked(folder):
        path = folder / "state.json"
        state = read(path) if path.exists() else {"attempts": 0, "status": "new", "promoted": False}
        if state["status"] not in {"new", "review_required"}:
            return state  # Interrupted/error/completed experiments cannot spend another budget.
        if state["status"] == "review_required" and not (
                (folder / "reviewed-cases.json").exists() and (folder / "expectations.json").exists()):
            return state
        phase = capture if state["status"] == "new" else compare
        state["status"] = "running"  # Crash is fail-closed; never silently retry reflection.
        save(path, state)
        try:
            await phase(folder, BoundedClient(raw, folder, state), state)
        except Exception as error:
            state.update(status="error", error_type=type(error).__name__)  # No provider/key text.
        finally:
            save(path, state)
        return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment_dir", type=Path)
    args = parser.parse_args()
    state = asyncio.run(run(args.experiment_dir.resolve(), make_client()))
    print(json.dumps(state, indent=2))
    return 1 if state["status"] in {"error", "running", "shadow_failed", "unscorable", "unscorable_capture"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
