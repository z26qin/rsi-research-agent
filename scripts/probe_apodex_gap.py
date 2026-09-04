#!/usr/bin/env python3
"""Replayable evidence probe for Apodex self-improvement reviews.

Scans a git ref for file/symbol signals that map to the seven dimensions
in docs/apodex_gap.json. This does not assign the qualitative 0-100 scores;
it prints which signals are present so a main review can be re-run without
memory. Official scores stay in the JSON and change only after commits land
on main.

Usage:
    python scripts/probe_apodex_gap.py
    python scripts/probe_apodex_gap.py origin/main
    python scripts/probe_apodex_gap.py origin/cursor/cloud-agent-1788530459636-8e4tt
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Signal:
    id: str
    dimension: str
    pattern: str
    present: bool
    hits: list[str]


DIMENSIONS = (
    "gap_mining",
    "task_pipeline",
    "environment_scaling",
    "coordination_scaling",
    "asymmetric_verification",
    "training_loop",
    "eval_attribution",
)

# pathspec, then regex. Keep patterns tight so a comment cannot fake a feature.
SIGNALS: tuple[tuple[str, str, str, str], ...] = (
    ("gap_mining", "task_error_field", "src", r"class Task\b"),
    ("gap_mining", "blocked_status", "src", r"BLOCKED\s*="),
    ("gap_mining", "evidence_verdict", "src", r"class EvidenceVerdict\b"),
    ("gap_mining", "capability_ledger", "src", r"capability_gap|gap_ledger|GapTaxonomy"),
    ("task_pipeline", "followup_specs", "src", r"def followup_specs\b"),
    ("task_pipeline", "task_kind_followup", "src", r"FOLLOWUP\s*="),
    ("task_pipeline", "gap_seed", "src", r"def seed_open_gaps\b"),
    ("task_pipeline", "new_environment_factory", "src", r"TaskPipeline|environment_factory|world_manifest"),
    ("environment_scaling", "engine_adapter", "src", r"def load_engine_state\b"),
    ("environment_scaling", "delivery_verifier", "src", r"\bV_D\b|delivery_contract|world_manifest"),
    ("environment_scaling", "labeled_mock_fallback", "src", r"MOCK DATA|source.: .mock"),
    ("coordination_scaling", "disk_task_board", "src", r"class TaskBoard\b"),
    ("coordination_scaling", "coordinator_follow_up", "src", r"async def follow_up\b"),
    ("coordination_scaling", "live_replan", "src", r"class AgentBus\b|async def replan\b|async def replan_blocked\b|def replan_specs\b|def staged_return\b"),
    ("asymmetric_verification", "verifier_class", "src", r"class Verifier\b"),
    ("asymmetric_verification", "static_audit", "src", r"def static_audit\b"),
    ("asymmetric_verification", "conservative_merge", "src", r"def more_conservative\b"),
    ("training_loop", "trajectory_log", "src", r"trajectory_log|ExecutionTrace|replay_record|class ToolTrace\b|def replay_trace\b|def append_tool_event\b"),
    ("training_loop", "prompt_evolution", "src", r"evolve_prompt|profile_patch|sft_mixture|def refresh_profile_hints\b"),
    ("eval_attribution", "unit_tests", "tests", r"def test_"),
    ("eval_attribution", "verifier_tests", "tests", r"def test_.*verif"),
    ("eval_attribution", "working_capability_bench", "tests", r"working_capability|HDS6|FrontierFinance"),
)


def git_grep(ref: str, pathspec: str, pattern: str) -> list[str]:
    result = subprocess.run(
        ["git", "grep", "-l", "-P", pattern, ref, "--", pathspec],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in {0, 1}:
        raise RuntimeError(result.stderr.strip() or f"git grep failed for {pattern!r}")
    return [line.split(":", 1)[-1] for line in result.stdout.splitlines() if line.strip()]


def probe(ref: str) -> list[Signal]:
    found: list[Signal] = []
    for dimension, signal_id, pathspec, pattern in SIGNALS:
        hits = git_grep(ref, pathspec, pattern)
        found.append(
            Signal(
                id=signal_id,
                dimension=dimension,
                pattern=pattern,
                present=bool(hits),
                hits=hits,
            )
        )
    return found


def summarize(signals: list[Signal]) -> dict[str, dict[str, object]]:
    out: dict[str, dict[str, object]] = {}
    for dimension in DIMENSIONS:
        items = [item for item in signals if item.dimension == dimension]
        present = [item.id for item in items if item.present]
        missing = [item.id for item in items if not item.present]
        out[dimension] = {
            "present": present,
            "missing": missing,
            "hit_count": len(present),
            "signal_count": len(items),
        }
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "ref",
        nargs="?",
        default="origin/main",
        help="Git ref to scan (default: origin/main)",
    )
    args = parser.parse_args(argv)
    signals = probe(args.ref)
    payload = {
        "ref": args.ref,
        "dimensions": summarize(signals),
        "signals": [asdict(item) for item in signals],
    }
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
