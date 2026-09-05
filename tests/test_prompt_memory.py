from __future__ import annotations

from pathlib import Path

from momentum_research_agent.coordinator.gap_seed import append_gaps
from momentum_research_agent.models.schemas import (
    GapEntry,
    GapKind,
    GapLedgerStatus,
    MomentumCapability,
)
from momentum_research_agent.agents.sub_agent import load_profile
from momentum_research_agent.state.prompt_memory import (
    evolution_path,
    failure_brief,
    overlay_text,
    refresh_profile_hints,
)
from momentum_research_agent.state.policies import (
    PolicyPatch,
    PolicyStore,
    ToolPolicy,
    merge_policy_patch,
)


def test_active_policy_renders_only_requested_research_profile(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path)
    base = store.load_active()
    candidate = merge_policy_patch(
        base,
        PolicyPatch(
            prompt_overlays={
                "momentum_analyst": "Always state the engine as-of date.",
                "flow_analyst": "Prefer primary positioning evidence.",
            },
            tool_policies=[
                ToolPolicy(
                    profile="momentum_analyst",
                    capability=MomentumCapability.ENGINE_FRESHNESS,
                    preferred_tools=["engine_query"],
                )
            ],
        ),
        trigger_ids=["trajectory:stale-engine"],
    )
    store.write_version(candidate)
    store.activate(candidate.version_id)

    refresh_profile_hints(tmp_path)
    momentum = overlay_text(tmp_path, "momentum_analyst", policy=candidate)
    flow = overlay_text(tmp_path, "flow_analyst", policy=candidate)

    assert "engine as-of" in momentum
    assert "engine_query" in momentum
    assert "primary positioning" in flow
    assert "engine as-of" not in flow


def test_refresh_hints_keeps_ledger_failures_out_of_effective_prompts(tmp_path: Path) -> None:
    append_gaps(
        tmp_path,
        [
            GapEntry(
                kind=GapKind.ENGINE_MOCK,
                claim="engine_query(NVDA) mock on 2026-05-29",
                evidence_id="engine_mock:NVDA",
            )
        ],
        session_id="a",
    )
    refresh_profile_hints(tmp_path)
    text = (tmp_path / "reports" / "profile_hints.md").read_text(encoding="utf-8")
    assert "Policy version" in text
    assert "engine_mock:NVDA" not in text
    assert failure_brief(tmp_path)
    evo = evolution_path(tmp_path)
    payload = evo.read_text(encoding="utf-8")
    assert "rules" not in payload

    from momentum_research_agent.coordinator.gap_seed import load_rows, write_rows

    rows = load_rows(tmp_path)
    rows[0].status = GapLedgerStatus.CLOSED
    write_rows(tmp_path, rows)
    refresh_profile_hints(tmp_path)
    text = (tmp_path / "reports" / "profile_hints.md").read_text(encoding="utf-8")
    assert "engine_mock:NVDA" not in text
    assert "Policy version" in text


def test_overlay_applies_to_research_but_never_verifier(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path)
    candidate = merge_policy_patch(
        store.load_active(),
        PolicyPatch(prompt_overlays={"momentum_analyst": "Use explicit dates."}),
        trigger_ids=["trajectory:dates"],
    )
    store.write_version(candidate)
    store.activate(candidate.version_id)
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "momentum_analyst.md").write_text("# Momentum\n", encoding="utf-8")
    (profiles / "verifier.md").write_text("# Verifier\n", encoding="utf-8")
    research = load_profile("momentum_analyst", tmp_path, policy=candidate)
    verifier = load_profile("verifier", tmp_path, policy=candidate, apply_overlay=True)
    assert "Use explicit dates." in research
    assert "Use explicit dates." not in verifier
