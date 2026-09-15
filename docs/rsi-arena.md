# RSI v1 research capability arena

The arena evaluates a research policy with the real bounded ReAct loop against
four frozen, synthetic momentum scenarios. Production failures are mined into
capability cases after verification; an explicit cycle may generate and promote
one policy. No scheduled or recursive improvement is started by production research.

See [the completion audit](rsi-completion-audit.md) for requirement-by-requirement
evidence and the pending live-model demonstration.

```bash
uv run momentum-research-agent --rsi-cycle \
  --max-output-tokens 4096 --max-llm-calls 28 --max-turns 8 \
  --max-tool-calls 32 --max-total-tokens 250000 \
  --overall-deadline-s 180 --llm-timeout-s 20

uv run momentum-research-agent --replay-rsi reports/rsi_experiments/EXPERIMENT_ID
```

The cycle uses the configured DeepSeek research model and the existing candidate
generator. It needs a configured API key for model requests, but **world tools
never access the live internet**. A missing key exits before changing policy.
`MOMENTUM_ENV_FILE` can point to an existing configuration file. Replay needs no key.

## Execution and isolation

Each variant starts with the same question, corpus, engine state, frozen profile
texts and controls. The model chooses a profile and subproblem, chooses its own
search queries and source reads, returns a structured report, and chooses whether
to request one additional investigation. Both investigations use the existing
research report instructions and persistent TaskBoard. There is no fixed tool
trajectory or handwritten policy simulator in the runtime.

Baseline and candidate have separate directories, messages, observations and
budgets. Research policy overlays, task guidance and authorized tool preferences
are the intended differences. Candidate generation receives observed baseline
failures, never hidden expected facts. Patches containing frozen source URLs,
scenario dates/IDs or copied expected/source sentences are rejected to prevent
direct answer transfer. This is a conservative exact-content contamination check,
not a general semantic detector for paraphrases.

The verifier uses its frozen profile, the arena-owned `arena_verification.md`
scope contract, and the existing independent verifier instructions, static audit,
conservative merge and ledger builder. Its prompt
receives the question and produced reports; it cannot load policy, candidate
reasoning, prompt evolution, hidden facts or promotion criteria. A terminal model
verification response is required even when research withholds all findings.
An omitted verdict cannot receive static-only VERIFIED credit. Web findings also
require a successful independent verifier read of the cited frozen document.
VERIFIED in the arena means checked support within the synthetic corpus, not
confirmation that a fixture source or market event exists in the real world.
The fixture domain alone is neither grounds for rejection nor grounds for credit.
This verifier scope is identical for both variants and never comes from policy.

Request counts, total token reservation, tool calls and total wall time are
shared by planning, research, optional replan and verification within each run.
`max_turns` applies separately to each phase; `max_llm_requests` caps requests
across all phases, and `max_output_tokens` caps each response.
Total tokens are conservatively reserved from
UTF-8 input bytes plus framing overhead and the output ceiling before a request;
missing usage or a provider exceeding the reservation makes the run incomplete.
TaskBoard usage is local to each investigation; run artifacts also retain the
planning/review/verifier usage in the aggregate. Candidate generation is one
separate request with an output ceiling and outer timeout, and is audited separately.
Generation response text, model identity, and usage are saved even when the patch
is truncated or fails validation. Planning explicitly precedes tool use; a review
decision to stop needs no unused next assignment, but replanning requires one.
Stop decisions may include a bounded explanatory rationale. New cycles pin
`max_schema_repairs=1`; historical controls default to zero. If a terminal, parsed
research report has only invalid finding category/stance enum values, the runtime
may make one tool-free, one-turn repair request within the same shared budget.
Every other JSON key/value must remain identical, including all findings, claims,
quotes, provenance and metrics. Rewriting or removing claims, invalid repairs,
empty/truncated responses and unrelated schema errors fail closed. The allowance
is shared across initial research and replan and cannot affect verification.

## Worlds and scoring

| World | Capability exercised | Fixed guard |
| --- | --- | --- |
| `recovery_risk` | Bear-market rebound, prior-loser beta and broad momentum reversal | No |
| `local_crowding` | Concentrated covering versus broad recovery-crash evidence | Yes |
| `high_quality_contradiction` | Preserve high-quality contradictory evidence | Yes |
| `incomplete_withholding` | Identify missing evidence and withhold a strong conclusion | Yes |

Fixtures and provenance are in
`src/momentum_research_agent/eval/fixtures/research_worlds/`. Every source and
measurement is synthetic. The approval manifest pins the entire public and hidden
payload, including timestamps and provenance. Updating a fixture requires an
explicit reviewed manifest update in source control; pending mined cases cannot
approve a world. Production tools and profile allowlists remain unchanged.

`ResearchCapabilityScore` measures VERIFIED claim recall, unsupported claims,
contradiction handling, required evidence coverage, withholding, source quality,
duplicate tool calls, consumption and completion. Scoring uses a deliberately
narrow **extractive evidence contract**. Version `extractive_v2` introduced:
a research claim must equal its excerpt and one complete source sentence, with
valid dates, researcher and verifier source reads, and an independent VERIFIED
verdict. Retrieval process notes earn neither claim credit nor unsupported-claim
penalties. Unread research claims still fail. Factual support is separate from
hidden category/stance alignment: a supported sentence can miss target recall;
a reversed stance also incurs an interpretation error and a promotion veto if
the count increases. Source quality is coverage-weighted over required facts.

Withholding requires explicit missing/unknown assertions for every required
concept. Narrow nominal aliases permit equivalent terminology without accepting
unrelated words, mere questions, known-value assertions, or conflicting claims.
The accepted concept mapping belongs only to scoring and is never sent to the
research agent or candidate generator.

New experiments now pin `extractive_v3`. This retains v2 source-support checks
but measures factual recall independently of hidden category/stance labels.
The category enum overlaps factual topics and argumentative roles, so exact
category agreement is not a published capability requirement. Contradiction
credit separately requires the expected direction and an explicit contradiction
in the report; reversed stance remains a separate error and promotion veto.
The public instructions define stance relative to the mechanism evaluated, rather
than agreement with the report's conclusion. Mechanism-reference ambiguity remains
a benchmark limitation; a label mismatch alone does not establish a false quote.

This is reproducible capability coverage on four scenarios, not general semantic
truth scoring. An otherwise useful paraphrase can fail this conservative contract.
Human summaries are not the machine-readable claim source; findings remain the
authoritative research claims. No optional model judge overrides the deterministic gates.

## Mining and promotion

The miner classifies at most eight persisted gap occurrences using bound task,
report, evidence and trace context. It records the stable taxonomy, source hashes,
occurrence IDs and approved world hashes in `reports/capability_cases/`. Unknown
failures stay `pending_world_candidate`. Repeating the same source occurrence
does not overwrite it; a later session creates a distinct occurrence.

The cycle selects at most two target worlds from OPEN gaps and always adds the
fixed guards. A guard can also be a target. It runs the existing offline engine
guard suite against the pinned bundled engine in a private cache. Frozen engine
observations are explicitly simulation-only and cannot satisfy live V_D delivery.

Baseline runs happen before generation and are retained as the paired baseline.
If they are incomplete, generation is skipped. If they have no target failures,
the result is `no_change`. Otherwise the existing FailureBundle and
LLMCandidateGenerator produce at most one schema-validated minimal patch.
The bundle packs whole observed finding/document records and public-contract
diagnostics within its text budget, recording omissions. After a target failure
triggers generation, failed guard observations are included too, because a shared
profile overlay can affect those worlds. Hidden answers remain excluded.

Promotion requires a target capability improvement, no per-world increase in
unsupported claims, no contradiction/withholding regression, no guard dimension
regression, completed bounded runs, matching world/profile/control hashes and
requested/resolved model IDs, valid allowlists and passing deterministic engine
guards. More calls or an aggregate score increase alone cannot justify promotion.
All worlds in the paired experiment must share one requested model identity and
one resolved model identity; pairwise equality alone cannot excuse model drift.

The existing `improvement.lock` serializes cycles with `--improve`. All evaluation
and decision artifacts are sealed before the final `PolicyStore.activate` call.
A changed active policy observed before activation vetoes promotion. Rejection
and pre-activation failures preserve the pointer. New sessions pin the winner;
already-running or resumed sessions retain their saved version.

## Audit and replay

Each unique `reports/rsi_experiments/<id>/` contains the policy snapshots, patch,
failure bundle, production gap/case snapshots, selected worlds and full hashes,
frozen profiles, baseline/candidate session directories, requests and responses,
tool traces, reports, independent verification, model IDs, usage, capability
scores, comparison, decision and outcome. Previous experiment directories are
never reused. Per-run public world snapshots contain no hidden expectations.

`--replay-rsi` verifies sealed artifact hashes, replays the saved tool arguments
against the frozen corpus, recomputes grounding and capability scores, and checks
the saved scores and comparison, then returns the final saved promotion decision.
A passing comparison does not override a later active-policy or activation veto;
the final decision must agree with the saved outcome. Scoring is versioned: unversioned legacy
experiments retain `extractive_v1` semantics, v2 experiments retain their category
and stance aligned recall, and unknown versions fail closed.
An updated scorer cannot silently reinterpret a historical result.
Early rejected/error/no-change experiments can be
audited as non-promotion outcomes. Replay neither calls a model nor activates a
policy. A fresh live-model run is a new experiment; remote model output is not
claimed to be bitwise reproducible.

## Validation and demonstration boundary

```bash
uv run pytest
```

The repository intentionally retains at most 30 essential tests, including the
two replay/classification regressions. See [retained coverage](../tests/README.md).

The integration test
`test_failure_to_mined_case_to_generated_patch_to_new_session` exercises a persisted
failed report → gap → mined capability → existing candidate generator → independent
paired research → verifier → improved score → promotion → new-session snapshot.
Only the external model transport is scripted. Its findings and tool choices are
fixtures, so this proves integration and safety behavior, **not autonomous live-model
learning or improvement**. Unit tests never contact DeepSeek.

Live DeepSeek evaluation is now configured and has been exercised against the
frozen worlds. The audit and live experiment artifacts record its outcomes.
A successful live-model promotion has not yet been demonstrated. Until an
audited live cycle shows that improvement, this should be described as an RSI
arena implementation with a deterministic integration demonstration, not as a
proven autonomous RSI loop.
