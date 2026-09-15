# RSI v1 completion audit

**Test inventory update (2026-09-14):** At the user's request, the repository
suite was reduced from 698 collected cases to 30 essential cases. The tables
below record the original implementation audit; some named tests have since
been removed. [The maintained coverage list](../tests/README.md) is current.

The authoritative requested scope is `rsi-v1-spec.md`. This audit distinguishes
implementation evidence from the still-unproven live-model result. Passing
scripted tests does not satisfy the full definition of done.

| Requirement | Current-state evidence | Finding |
| --- | --- | --- |
| 1. FrozenResearchWorld and reproducible research tools | `eval/research_world.py`; public/hidden typed models, complete content hash, deterministic metadata search, exact frozen document reads, simulation-only engine adapter; `test_research_world.py` exercises hash tampering, unknown URLs, authorization and timestamp guards | Implemented and deterministically tested |
| 2. Four meaningful worlds with provenance | Packaged `recovery_risk`, `local_crowding`, `high_quality_contradiction`, `incomplete_withholding` JSON files and pinned manifest; fixture README labels all observations synthetic | Four scenarios present; these are capability fixtures, not market claims |
| 3. Actual bounded research path and independent trajectories | `run_world` invokes `react_loop_detailed` for planning, research, optional one replan and independent verification; existing report instructions, grounding, TaskBoard and verifier rules are reused; each run persists its own requests and observations | Live DeepSeek planning, autonomous tool choices, reporting and independent verification completed in all four worlds; an earlier candidate improved a target but failed safety guards |
| 4. Typed outcome scoring | Versioned `ResearchCapabilityScore` uses inspected sources, timestamps, complete quotes and independently VERIFIED verdicts; v3 factual recall is separate from category/stance alignment, while contradiction and interpretation checks remain separate gates | Tested under the documented conservative extractive contract; general paraphrase usefulness is not measured |
| 5. Production failures become capability cases | Coordinator runs mining after final verification/follow-up; daily supplement has an isolated hook. `capability_mining.py` uses gaps, tasks, bound reports/evidence and traces; occurrence artifacts pin source and approved-world hashes | Tests cover mapped and pending cases, stale mappings, repeated occurrences, OPEN selection and hook failure isolation |
| 6. One bounded improvement cycle | `run_rsi_cycle` loads the active policy and approved worlds, selects at most two targets plus fixed guards, runs baseline, builds FailureBundle, invokes the existing generator once, validates and materializes one candidate, compares, seals and conditionally activates | Scripted end-to-end tests pass; live baseline and one-shot generation were exercised. Invalid and truncated live patches failed closed; no automatic production improvement hook exists |
| 7. Promotion contract | Per-world safety vetoes and engine gates, no gain for additional calls alone, terminal completion, bound controls, world/profile hashes, requested/resolved model identity, allowlists, independent verifier; model identity must also be uniform across all worlds | Deterministic rejection and promotion tests pass, including actual candidate-timeout rejection |
| 8. Auditable artifacts and replay | Unique experiment directory contains the manifest, policy/patch snapshots, selected worlds/hashes, source gap/case copies, isolated run directories, usage and model IDs, scores, comparison and decision. Offline replay checks artifact hashes and regenerates observations/scores/decision | Retained paired demo replays; early non-promotion experiments can be audited without model calls |
| 9. Verifier asymmetry | Frozen verifier profile and arena-owned synthetic-source scope are loaded without overlays. Only question, produced reports/static audit and allowed frozen observations reach its loop. Candidate generation, policy, hidden expectations and promotion rules are excluded | Sentinel prompt test and omitted-verdict/source-read tests pass |
| 11. Non-goals | Source diff adds only evaluation modules, fixtures, tests, docs, CLI routing and bounded mining hooks; no production tool or analyst profile additions, framework, frontend change, model training or autonomous commit | No excluded subsystem introduced |

## Required deterministic tests (section 10)

| Requested case | Authoritative test |
| --- | --- |
| 1. Target fix promotes | `test_target_fix_promotes_once_and_only_new_sessions_pin_winner` |
| 2. Target fix plus guard regression rejects | `test_rejected_or_error_cycle_preserves_active_pointer[guard]` |
| 3. More unsupported claims rejects | `test_rejected_or_error_cycle_preserves_active_pointer[unsupported]` |
| 4. More calls without capability gain is not improvement | `test_more_calls_without_capability_gain_is_not_improvement` |
| 5. Incomplete/timeout candidate rejects | `test_candidate_timeout_rejects_cycle_without_changing_active_policy` |
| 6. World hash mismatch fails closed | `test_promotion_rejects_each_safety_regression[hash]` |
| 7. Resolved model mismatch fails closed | `test_promotion_rejects_each_safety_regression[model]` and `test_model_drift_between_worlds_vetoes_promotion` |
| 8. Hidden facts excluded from agent prompts | `test_public_world_detaches_and_hides_evaluator_expectations` and `test_real_loop_records_independent_source_verification` |
| 9. Verifier cannot load policy overlay | `test_verifier_prompt_excludes_policy_and_hidden_evaluator_fields` |
| 10. Rejected/error cycles preserve active pointer | `test_rejected_or_error_cycle_preserves_active_pointer` and candidate-timeout test |
| 11. One candidate maximum | Promotion, rejection, generation-error and timeout cycle tests assert one generator invocation; no-change test asserts zero |
| 12. Only fresh sessions use promoted policy | `test_target_fix_promotes_once_and_only_new_sessions_pin_winner` and `test_failure_to_mined_case_to_generated_patch_to_new_session` |

## Definition of done: remaining evidence

The retained demonstration at
`reports/rsi_demo/20260913_124953_fd50a2ad/demonstration.json` contains a complete
persisted causal chain and uses a real bundled engine guard. Its model responses
and tool choices are scripted. It proves integration, safe activation and session
pinning, but **does not prove that an autonomous model chose a better research
trajectory because of its generated policy**.

The repository `.env` now loads successfully. Live DeepSeek cycles use copies of
production session `20260910_003250_eb4b7abf`, its OPEN gaps, and the active policy.
Eight immutable capability cases map to two target worlds plus all fixed guards.
The real bundled-engine guard passes. All production policy pointers remain
unchanged; fresh and resumed demonstration sessions are audited separately.

Live validation exposed and addressed a stop-decision parser that required unused
assignment fields, ambiguous stage instructions, and missing verifier context for
synthetic sources. Engine-only metrics are explicitly distinguished from document
metrics. Failed/truncated candidate responses now remain in generation diagnostics;
the generator is told the public research contract and exact policy key format.
Later reviewed scorer revisions separate factual support from retrieval metadata and unpublished labeling conventions. Historical scores remain version-pinned; production profiles and source-support/promotion safety requirements remain intact.

Before the deliberate test reduction: **698 passed** (including the v3 correction). Three tests covered null/omitted stop
assignments and invalid requested replans. Existing tests now check verifier-owned
scope isolation and generation diagnostics on truncation. An existing configuration
test is isolated from developers' local environment files.

A live-model promotion remains unproven. The earlier live attempts are preserved
under `reports/rsi_live_demo/` and replay as non-promotion outcomes. The definition
of done remains incomplete until an independently researched candidate actually
improves a triggering capability, passes the guards, and is promoted. Invalid,
incomplete, rejected, or no-change outcomes must not be relabeled as success.

Final live paired experiment: `reports/rsi_live_demo/20260913_134231_c88ad74a/demonstration.json`. All eight runs completed. Recovery-risk VERIFIED recall improved from 0% to 100%, but local-crowding recall fell from 33% to 0% and unsupported findings increased in two guards, so the candidate was rejected. Offline replay confirms the rejection after a reason-ordering regression fix. No active policy changed. See `docs/rsi-live-validation.md` for metrics and all retained attempts.

## Reviewed scoring and feedback corrections

V2 excludes retrieval process notes from research-claim penalties, uses narrow
missing-evidence concept assertions, and pins replay semantics. V3 removes
unpublished category conventions from factual recall and separates contradiction
credit. Reversed stance still incurs an interpretation error; full source support,
independent verification, completed runs and per-world safety vetoes remain.
Mechanism-relative stance is now explained to both research and verifier. An
ambiguous reference can still limit interpretation scoring; factual recall alone
is not evidence of directional understanding.

Observed failure feedback packs complete records with omission counts rather than
truncating JSON before source documents. Failed guard observations accompany target
failures after generation is triggered. Neither path exposes hidden target answers.
Independent review and focused tests cover these corrections. All seven retained
pre-v3 live attempts replay without score or outcome changes.
