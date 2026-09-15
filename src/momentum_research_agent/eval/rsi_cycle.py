"""One exclusive, auditable autonomous research policy improvement cycle."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from momentum_research_agent.eval.capability_mining import select_worlds_for_open_gaps
from momentum_research_agent.eval.momentum_eval import (
    engine_case_results,
    run_offline_engine_eval,
)
from momentum_research_agent.eval.policy_improver import (
    CandidateGenerator,
    FailureBundle,
    _exclusive_cycle,
    _research_profile_tools,
)
from momentum_research_agent.eval.policy_suite import CaseResult
from momentum_research_agent.eval.research_arena import (
    ArenaControls,
    ArenaRun,
    profile_snapshot,
    run_world,
    write_artifact,
)
from momentum_research_agent.eval.research_scoring import (
    SCORING_VERSION,
    ArenaDecision,
    ResearchCapabilityScore,
    compare_arena_runs,
    score_run,
)
from momentum_research_agent.eval.research_feedback import observed_failure_context
from momentum_research_agent.eval.research_world import (
    FrozenResearchWorld,
    FrozenWorldAdapter,
    load_approved_worlds,
)
from momentum_research_agent.models.schemas import new_session_id
from momentum_research_agent.state.policies import (
    PolicyPatch,
    PolicyStore,
    merge_policy_patch,
    validate_policy,
)
from momentum_research_agent.tools.engine_pipeline import bundled_engine_root


class RSICycleOutcome(BaseModel):
    status: Literal["promoted", "rejected", "no_change", "error"]
    previous_version_id: str
    candidate_version_id: str | None = None
    experiment_dir: str
    reasons: list[str] = Field(default_factory=list)


def _engine_passed(results: list[CaseResult]) -> bool:
    return (
        bool(results)
        and len({r.case_id for r in results}) == len(results)
        and all(
            r.layer == "engine" and r.passed and r.score == 1 and not r.failures
            for r in results
        )
    )


def _seal(directory: Path, manifest: dict) -> None:
    manifest["artifact_hashes"] = {
        path.relative_to(directory).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }
    write_artifact(directory / "manifest.json", manifest)


def _contains_world_answers(
    policy: PolicyPatch, worlds: list[FrozenResearchWorld]
) -> bool:
    """Guidance may transfer research method, never fixture answers or source leads."""
    text = " ".join(
        [*policy.prompt_overlays.values(), *policy.task_templates.values()]
    ).casefold()
    forbidden = []
    for world in worlds:
        forbidden.extend([world.as_of, world.world_id])
        for source in world.sources:
            forbidden.append(source.url)
            forbidden.extend(
                s.strip()
                for s in re.split(r"(?<=[.!?])\s+", source.text)
                if len(s.strip()) > 20
            )
        forbidden.extend(f.claim for f in world.hidden_facts)
    return any(value.casefold() in text for value in forbidden)


async def run_rsi_cycle(
    project_root: Path,
    *,
    client: Any,
    requested_model: str,
    generator: CandidateGenerator,
    controls: ArenaControls | None = None,
    engine_results: list[CaseResult] | None = None,
) -> RSICycleOutcome:
    """Select only packaged approved worlds. Injection of engine results is for tests.

    Production CLI always runs the existing offline pinned-engine guard suite.
    No generation/evaluation can write the active pointer. Activation is the final
    state change after a sealed comparison under the existing improvement lock.
    """
    project_root = Path(project_root)
    controls = controls or ArenaControls(max_schema_repairs=1)
    store = PolicyStore(project_root)
    directory = project_root / "reports" / "rsi_experiments" / new_session_id()
    directory.mkdir(parents=True, exist_ok=False)
    active = None
    candidate = None
    manifest: dict[str, Any] = {
        "schema_kind": "rsi_experiment_v1",
        "scoring_version": SCORING_VERSION,
        "status": "running",
        "requested_model": requested_model,
        "controls": controls.model_dump(mode="json"),
        "max_candidates": 1,
        "max_promotions": 1,
        "fixture_truth": "synthetic",
        "engine_guard_provider": "injected"
        if engine_results is not None
        else "offline_pinned_engine",
    }
    write_artifact(directory / "manifest.json", manifest)

    def finish(status, reasons, decision=None):
        outcome = RSICycleOutcome(
            status=status,
            previous_version_id=active.version_id if active else "",
            candidate_version_id=candidate.version_id if candidate else None,
            experiment_dir=str(directory.resolve()),
            reasons=reasons,
        )
        write_artifact(
            directory / "promotion_decision.json",
            decision or {"promote": False, "reasons": reasons},
        )
        write_artifact(directory / "outcome.json", outcome)
        manifest["status"] = status
        _seal(directory, manifest)
        return outcome

    try:
        with _exclusive_cycle(store):
            active = store.load_active()
            write_artifact(directory / "baseline_policy.json", active)
            approved = load_approved_worlds()
            selected, triggers, target_list = select_worlds_for_open_gaps(
                project_root, approved
            )
            targets = set(target_list)
            guards = {w.world_id for w in approved if w.guard}
            if not guards:
                return finish("rejected", ["No fixed guard worlds"])
            manifest.update(
                {
                    "baseline_version_id": active.version_id,
                    "world_hashes": {w.world_id: w.content_hash for w in selected},
                    "target_ids": sorted(targets),
                    "guard_ids": sorted(guards),
                    "triggering_gap_ids": triggers,
                }
            )
            write_artifact(
                directory / "selected_worlds.json",
                [
                    {
                        "world_id": w.world_id,
                        "world_hash": w.content_hash,
                        "capabilities": w.capabilities,
                        "target": w.world_id in targets,
                        "guard": w.world_id in guards,
                    }
                    for w in selected
                ],
            )
            for w in selected:
                write_artifact(directory / "worlds" / f"{w.world_id}.json", w)
            # Snapshot the causal production inputs; later ledger closure cannot erase them.
            ledger = project_root / "reports" / "gap_ledger.jsonl"
            if ledger.exists():
                (directory / "triggering_gap_ledger.jsonl").write_bytes(
                    ledger.read_bytes()
                )
            for path in sorted(
                (project_root / "reports" / "capability_cases").glob("*.json")
            ):
                (directory / "capability_cases").mkdir(exist_ok=True)
                (directory / "capability_cases" / path.name).write_bytes(
                    path.read_bytes()
                )
            if not targets:
                return finish(
                    "no_change", ["No OPEN gaps mapped to approved frozen worlds"]
                )
            if engine_results is None:
                raw = await run_offline_engine_eval(bundled_engine_root(project_root))
                write_artifact(directory / "engine_observations.json", raw)
                engine_results = engine_case_results(raw)
            write_artifact(
                directory / "engine_guards.json",
                [r.model_dump(mode="json") for r in engine_results],
            )
            if not _engine_passed(engine_results):
                return finish(
                    "rejected", ["Deterministic engine guards failed or missing"]
                )
            profiles = profile_snapshot(project_root, selected)
            write_artifact(directory / "profile_snapshots.json", profiles)
            baseline_runs = []
            baseline_scores: dict[str, ResearchCapabilityScore] = {}
            for w in selected:
                result = await run_world(
                    client=client,
                    requested_model=requested_model,
                    project_root=project_root,
                    world=w,
                    policy=active,
                    session_dir=directory / "baseline_runs" / w.world_id,
                    controls=controls,
                    profiles=profiles,
                )
                baseline_runs.append(result)
                baseline_scores[w.world_id] = score_run(
                    w, result, version=SCORING_VERSION
                )
            write_artifact(
                directory / "capability_scores.json",
                {
                    "baseline": {
                        k: s.model_dump(mode="json") for k, s in baseline_scores.items()
                    }
                },
            )
            if any(r.completion_status != "complete" for r in baseline_runs):
                return finish(
                    "rejected", ["Baseline research incomplete; no candidate generated"]
                )
            failed_targets = [
                w.world_id
                for w in selected
                if w.world_id in targets and not baseline_scores[w.world_id].passed
            ]
            if not failed_targets:
                return finish(
                    "no_change",
                    ["Baseline has no triggering target capability failures"],
                )
            # A profile overlay also affects guard worlds. Give the one generator
            # their observed failures, never hidden answers, so its repair can
            # account for the full selected evaluation surface.
            failed = [
                w.world_id for w in selected if not baseline_scores[w.world_id].passed
            ]
            by_world = {w.world_id: w for w in selected}
            by_run = {r.world_id: r for r in baseline_runs}
            # Only observed baseline failures and findings; no hidden target quotes/facts.
            bundle = FailureBundle(
                active_policy=active,
                failed_case_ids=failed,
                case_failures={wid: baseline_scores[wid].failures for wid in failed},
                case_profiles={
                    wid: by_run[wid].reports[0].agent_role for wid in failed
                },
                case_capabilities={wid: by_world[wid].capability for wid in failed},
                verifier_gaps=[
                    g for wid in failed for g in by_run[wid].verification.gaps
                ][:24],
                recorded_observations={
                    wid: observed_failure_context(
                        by_world[wid].research_question,
                        by_run[wid],
                        profiles["arena_research"],
                    )
                    for wid in failed
                },
            )
            write_artifact(directory / "failure_bundle.json", bundle)
            # Exactly one generator invocation, with an outer timeout and no retry.
            try:
                async with asyncio.timeout(controls.llm_timeout_s):
                    patch = await generator.generate(bundle)
            finally:
                write_artifact(
                    directory / "generation.json",
                    {
                        "requested_model": str(getattr(generator, "model", "unknown")),
                        "usage": getattr(generator, "last_usage", None),
                        "response_model": getattr(
                            generator, "last_response_model", None
                        ),
                        "response_text": getattr(generator, "last_response_text", None),
                    },
                )
            patch = PolicyPatch.model_validate(patch.model_dump())
            write_artifact(directory / "policy_patch.json", patch)
            validate_policy(patch, _research_profile_tools())
            if _contains_world_answers(patch, approved):
                return finish(
                    "rejected",
                    ["Policy patch contains frozen-world answers or source leads"],
                )
            candidate = merge_policy_patch(active, patch, trigger_ids=triggers[:24])
            validate_policy(candidate, _research_profile_tools())
            store.write_version(candidate)
            write_artifact(directory / "candidate_policy.json", candidate)
            candidate_runs = []
            candidate_scores = {}
            for w in selected:
                result = await run_world(
                    client=client,
                    requested_model=requested_model,
                    project_root=project_root,
                    world=w,
                    policy=candidate,
                    session_dir=directory / "candidate_runs" / w.world_id,
                    controls=controls,
                    profiles=profiles,
                )
                candidate_runs.append(result)
                candidate_scores[w.world_id] = score_run(
                    w, result, version=SCORING_VERSION
                )
            decision = compare_arena_runs(
                baseline_runs,
                candidate_runs,
                baseline_scores,
                candidate_scores,
                target_ids=targets,
                guard_ids=guards,
                engine_guards_passed=_engine_passed(engine_results),
            )
            write_artifact(
                directory / "capability_scores.json",
                {
                    "baseline": {
                        k: s.model_dump(mode="json") for k, s in baseline_scores.items()
                    },
                    "candidate": {
                        k: s.model_dump(mode="json")
                        for k, s in candidate_scores.items()
                    },
                },
            )
            write_artifact(directory / "comparison.json", decision)
            if not decision.promote:
                return finish("rejected", decision.reasons, decision)
            # A writer bypassing the shared lock still cannot silently overwrite a new active policy.
            if store.load_active().version_id != active.version_id:
                return finish("rejected", ["Active policy changed during evaluation"])
            write_artifact(directory / "promotion_decision.json", decision)
            manifest["status"] = "approved_pending_activation"
            manifest["candidate_version_id"] = candidate.version_id
            _seal(directory, manifest)
            store.activate(candidate.version_id)
            # Once activation succeeded, an audit-finalization error must not lie about
            # whether the active pointer moved; the sealed intent remains inspectable.
            try:
                return finish(
                    "promoted",
                    ["Target capability improved and all promotion guards passed"],
                    decision,
                )
            except OSError as exc:
                return RSICycleOutcome(
                    status="promoted",
                    previous_version_id=active.version_id,
                    candidate_version_id=candidate.version_id,
                    experiment_dir=str(directory.resolve()),
                    reasons=[f"Activated; final audit write failed: {exc}"],
                )
    except asyncio.CancelledError:
        finish("error", ["Cycle cancelled; no pending activation performed"])
        raise
    except Exception as exc:  # noqa: BLE001 -- cycle boundary fails closed and preserves the audit
        return finish("error", [f"{type(exc).__name__}: {exc}"])


def replay_experiment(experiment_dir: Path | str) -> ArenaDecision:
    """Recompute the sealed trajectory grounding, scores and decision with no LLM/network.

    This audits the observed trajectory, while rerunning the model is a new
    experiment. It does not claim that a remote model is bitwise reproducible.
    """
    directory = Path(experiment_dir)
    manifest = json.loads((directory / "manifest.json").read_text())
    scoring_version = manifest.get("scoring_version", "extractive_v1")
    if scoring_version not in {"extractive_v1", "extractive_v2", "extractive_v3"}:
        raise ValueError("Unsupported scoring version")
    for name, expected in manifest["artifact_hashes"].items():
        path = directory / name
        if not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError("Invalid artifact path")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Artifact hash mismatch: {name}")
    if not (directory / "comparison.json").exists():
        decision = ArenaDecision.model_validate_json(
            (directory / "promotion_decision.json").read_text()
        )
        if (
            manifest.get("status") not in {"rejected", "error", "no_change"}
            or decision.promote
        ):
            raise ValueError("Incomplete experiment cannot authorize promotion")
        return decision
    worlds = [
        FrozenResearchWorld.model_validate_json(p.read_text())
        for p in sorted((directory / "worlds").glob("*.json"))
    ]
    variants = {}
    scores = {}
    for variant in ("baseline", "candidate"):
        variants[variant] = []
        scores[variant] = {}
        for world in worlds:
            if world.content_hash != manifest["world_hashes"][world.world_id]:
                raise ValueError("World hash mismatch")
            run = ArenaRun.model_validate_json(
                (
                    directory / f"{variant}_runs" / world.world_id / "run.json"
                ).read_text()
            )
            if run.world_hash != world.content_hash:
                raise ValueError("Run world hash mismatch")
            adapter = FrozenWorldAdapter(world.public_world())
            for trace in run.traces:
                if (
                    hashlib.sha256(trace.observation.encode()).hexdigest()
                    != trace.observation_sha256
                ):
                    raise ValueError("Trace hash mismatch")
                try:
                    expected = adapter.call(trace.tool, trace.arguments)
                except ValueError:
                    # Failed calls cannot carry successful observations or earn credit.
                    if "raised ValueError" not in trace.observation:
                        raise ValueError(
                            "Invalid failed frozen tool observation"
                        ) from None
                else:
                    if expected != trace.observation:
                        raise ValueError("Frozen observation differs on replay")
            variants[variant].append(run)
            scores[variant][world.world_id] = score_run(
                world, run, version=scoring_version
            )
    saved_scores = json.loads((directory / "capability_scores.json").read_text())
    for variant in ("baseline", "candidate"):
        if set(saved_scores.get(variant, {})) != set(scores[variant]):
            raise ValueError("Saved score world selection mismatch")
        for world_id, score in scores[variant].items():
            if score != ResearchCapabilityScore.model_validate(
                saved_scores[variant][world_id]
            ):
                raise ValueError(f"Replayed score mismatch: {variant}/{world_id}")
    engine = [
        CaseResult.model_validate(r)
        for r in json.loads((directory / "engine_guards.json").read_text())
    ]
    decision = compare_arena_runs(
        variants["baseline"],
        variants["candidate"],
        scores["baseline"],
        scores["candidate"],
        target_ids=set(manifest["target_ids"]),
        guard_ids=set(manifest["guard_ids"]),
        engine_guards_passed=_engine_passed(engine),
    )
    saved = ArenaDecision.model_validate_json(
        (directory / "comparison.json").read_text()
    )
    # Older experiments preserve selection order; replay loads worlds by filename.
    # Reason ordering has no decision semantics, but preserve every reason/count.
    if (
        decision.promote != saved.promote
        or sorted(decision.reasons) != sorted(saved.reasons)
        or sorted(decision.target_improvements) != sorted(saved.target_improvements)
    ):
        raise ValueError("Replayed decision mismatch")
    # A passing comparison establishes eligibility, not the final outcome: the
    # active-policy check or activation itself can still veto promotion.
    final = ArenaDecision.model_validate_json(
        (directory / "promotion_decision.json").read_text()
    )
    outcome = RSICycleOutcome.model_validate_json(
        (directory / "outcome.json").read_text()
    )
    if (
        outcome.status != manifest.get("status")
        or final.promote != (outcome.status == "promoted")
        or (final.promote and not decision.promote)
    ):
        raise ValueError("Final promotion decision conflicts with saved outcome")
    return final
