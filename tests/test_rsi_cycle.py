import json
from pathlib import Path

from test_research_arena import ScriptedClient, script_for

from momentum_research_agent.coordinator.coordinator import load_or_snapshot_policy
from momentum_research_agent.eval.policy_suite import CaseResult
from momentum_research_agent.eval.research_arena import ArenaControls
from momentum_research_agent.eval.research_world import load_approved_worlds
from momentum_research_agent.eval.rsi_cycle import replay_experiment, run_rsi_cycle
from momentum_research_agent.state.policies import (
    PolicyPatch,
    PolicyStore,
    merge_policy_patch,
)


class Generator:
    model = "test-generator"

    def __init__(self):
        self.patch = PolicyPatch(
            prompt_overlays={
                "momentum_analyst": "Inspect factor evidence and cross-check high-beta prior losers before concluding."
            }
        )
        self.calls = 0

    async def generate(self, bundle):
        self.calls += 1
        assert bundle.failed_case_ids
        return self.patch


def seed_gap(root):
    from momentum_research_agent.models.schemas import (
        GapKind,
        GapLedgerRow,
        MomentumCapability,
    )

    row = GapLedgerRow(
        evidence_id="missed-factor",
        source_session_id="production-failure",
        capability=MomentumCapability.UNWIND_CRASH,
        gap_kind=GapKind.MISSING_EVIDENCE,
        claim="Recovery crash factor evidence missing",
    )
    (root / "reports").mkdir(exist_ok=True)
    (root / "reports" / "gap_ledger.jsonl").write_text(row.model_dump_json() + "\n")


async def cycle(
    root,
    *,
    regression=False,
    generator=None,
    seed=True,
):
    if seed:
        seed_gap(root)
    worlds = load_approved_worlds()
    from momentum_research_agent.eval.capability_mining import (
        select_worlds_for_open_gaps,
    )

    selected, _, targets = select_worlds_for_open_gaps(root, worlds)
    scripts = []
    for variant in ("baseline", "candidate"):
        for w in selected:
            facts = w.hidden_facts
            if variant == "baseline" and w.world_id in targets:
                facts = facts[:1]
            if variant == "candidate" and regression and w.guard:
                facts = []
            scripts += script_for(w, facts)
    generator = generator or Generator()
    result = await run_rsi_cycle(
        root,
        client=ScriptedClient(scripts),
        requested_model="test",
        generator=generator,
        controls=ArenaControls(),
        engine_results=[
            CaseResult(case_id="engine-test", layer="engine", passed=True, score=1)
        ],
    )
    return result, generator


async def test_guard_regression_preserves_active_pointer(tmp_path):
    store = PolicyStore(tmp_path)
    store.load_active()
    pointer = store.active_path.read_bytes()
    result, generator = await cycle(
        tmp_path,
        regression=True,
    )
    assert result.status == "rejected", result.reasons
    assert generator.calls == 1
    assert store.active_path.read_bytes() == pointer
    assert not replay_experiment(result.experiment_dir).promote


async def test_failed_engine_guard_stops_before_candidate_or_research(tmp_path):
    seed_gap(tmp_path)
    generator = Generator()
    result = await run_rsi_cycle(
        tmp_path,
        client=ScriptedClient([]),
        requested_model="test",
        generator=generator,
        controls=ArenaControls(),
        engine_results=[],
    )
    assert result.status == "rejected"
    assert generator.calls == 0


async def test_replay_preserves_final_active_policy_veto(tmp_path):
    store = PolicyStore(tmp_path)
    baseline = store.load_active()
    replacement = merge_policy_patch(
        baseline,
        PolicyPatch(
            prompt_overlays={
                "momentum_analyst": "Check source publication timestamps before use."
            }
        ),
        trigger_ids=[],
    )
    store.write_version(replacement)

    class ConcurrentGenerator(Generator):
        async def generate(self, bundle):
            store.activate(replacement.version_id)
            return await super().generate(bundle)

    outcome, _ = await cycle(tmp_path, generator=ConcurrentGenerator())
    directory = Path(outcome.experiment_dir)
    comparison = json.loads((directory / "comparison.json").read_text())
    final = json.loads((directory / "promotion_decision.json").read_text())
    assert comparison["promote"] is True
    assert outcome.status == "rejected"
    assert final["promote"] is False
    pointer = store.active_path.read_bytes()
    replayed = replay_experiment(directory)
    assert replayed.promote is False
    assert replayed.reasons == ["Active policy changed during evaluation"]
    assert store.active_path.read_bytes() == pointer


async def test_failure_to_mined_case_to_generated_patch_to_new_session(tmp_path):
    from test_research_arena import response

    from momentum_research_agent.coordinator.gap_seed import record_session_gaps
    from momentum_research_agent.eval.capability_mining import mine_session
    from momentum_research_agent.eval.policy_improver import LLMCandidateGenerator
    from momentum_research_agent.eval.research_arena import run_world

    world = load_approved_worlds()[0]
    policy = PolicyStore(tmp_path).load_active()
    old_session = tmp_path / "existing-session"
    load_or_snapshot_policy(old_session, tmp_path)
    source_dir = tmp_path / "reports" / "scripted-source-session"
    script = script_for(world, world.hidden_facts[:1])
    report = json.loads(script[3].choices[0].message.content)
    report["status"] = "partial"
    report["unanswered_questions"] = ["Recovery crash factor evidence missing"]
    script[3] = response(report)
    failure = await run_world(
        client=ScriptedClient(script),
        requested_model="test",
        project_root=tmp_path,
        world=world,
        policy=policy,
        session_dir=source_dir,
        controls=ArenaControls(),
    )
    assert failure.verification.gaps
    rows = record_session_gaps(tmp_path, source_dir, source_dir.name)
    cases = mine_session(source_dir, tmp_path)
    assert rows and cases and cases[0].approved_world_ids
    generator = LLMCandidateGenerator(
        client=ScriptedClient(
            [
                response(
                    {
                        "prompt_overlays": {
                            "momentum_analyst": "Inspect factor breadth and the prior-loser beta mechanism before concluding."
                        }
                    }
                )
            ]
        ),
        model="test-generator",
    )
    outcome, _ = await cycle(tmp_path, generator=generator, seed=False)
    assert outcome.status == "promoted", outcome.reasons
    assert replay_experiment(outcome.experiment_dir).promote
    assert (
        load_or_snapshot_policy(tmp_path / "fresh-session", tmp_path).version_id
        == outcome.candidate_version_id
    )
    assert (
        load_or_snapshot_policy(old_session, tmp_path).version_id == policy.version_id
    )
    manifest = json.loads((Path(outcome.experiment_dir) / "manifest.json").read_text())
    assert any("scripted-source-session" in g for g in manifest["triggering_gap_ids"])
