/goal

Implement **RSI v1: an Autonomous Research Capability Arena** for this repository.

The purpose is to close the existing loop:

production research failure
→ capability case
→ candidate ResearchPolicy
→ baseline-vs-candidate autonomous research evaluation
→ safe promote/reject
→ future research sessions use the winner.

This is NOT a request to add more agents, tools, UI, RAG, LangGraph, MCP, model fine-tuning, or unconstrained self-modifying code.

The current system already has:

* Coordinator + persistent TaskBoard
* bounded parallel ReAct sub-agents
* typed Evidence / ResearchReport
* independent Verifier
* gap ledger
* immutable ResearchPolicy versions
* PolicyPatch generation
* offline policy evaluation
* SessionEvalCase
* replay runner
* live_compare
* deterministic engine guards

Reuse these components. Do not build a parallel framework.

## Core missing capability

Current policy improvement and live comparison mostly evaluate behavior against recorded/fixed observations.

Add an evaluation mode that tests whether a candidate policy can **autonomously research better than the baseline** from the same initial research world.

The evaluated agent must choose for itself:

* what question/subproblem to investigate
* which allowed tool to call
* what search query to issue
* which source to inspect
* whether evidence is sufficient
* whether to replan
* when to stop
* what claims to withhold

Baseline and candidate must receive the same initial case/world and budgets, but MUST NOT receive each other's tool trajectory or discovered evidence.

---

## 1. Introduce FrozenResearchWorld

Create a small deterministic research environment abstraction, for example:

`eval/research_world.py`

A FrozenResearchWorld represents one reproducible momentum research scenario.

It should include at minimum:

* world_id
* research_question
* as_of
* capability under test
* allowed profiles
* allowed tools
* deterministic engine observations
* a frozen web/source corpus or deterministic search adapter
* source metadata / publication timestamps
* hidden evaluation facts
* explicit delivery contract
* world content hash

Do NOT let evaluation depend on today's live internet.

The runtime presented to the agent should behave like research:
`web_search(query)` should search the world's source corpus,
`read_url(url)` should return the corresponding frozen document,
and `engine_query(...)` should return the frozen deterministic engine result.

The agent should not know which sources are evaluator targets.

Keep production tools unchanged. Implement the frozen world as an evaluation adapter.

---

## 2. Create at least 4 meaningful momentum research worlds

Do not create toy "call tool X" cases.

Create small but realistic cases covering different failure modes.

Minimum:

### World A — true recovery-crash evidence

The world contains enough evidence to identify a Daniel–Moskowitz style recovery-risk setup.

### World B — crowded/local unwind but no DM crash

The correct behavior is to distinguish structural/local unwind evidence from a broad momentum recovery crash.

### World C — contradictory evidence

Some sources support the hypothesis and at least one high-quality source contradicts it.
The agent must surface the contradiction rather than cherry-pick.

### World D — insufficient evidence / guard case

Evidence is intentionally incomplete.
The correct behavior is to withhold a strong conclusion and explicitly state what is missing.

Use deterministic fixtures and document their provenance.

These worlds are capability evaluation fixtures, not claims about current markets.

---

## 3. Run the REAL research policy in each world

Add an evaluation runner such as:

`eval/research_arena.py`

For every selected world run:

baseline ResearchPolicy
and
candidate ResearchPolicy

through the actual bounded research/ReAct path.

Do not replace the agent with a hand-written policy simulator.

Both variants must have identical:

* model
* temperature
* max turns
* token budget
* tool budget
* timeout
* initial world state
* source corpus
* engine state

The only intended behavioral difference is ResearchPolicy.

Use isolated per-run session directories.

No state from one variant may leak into the other.

No active policy mutation is allowed during evaluation.

---

## 4. Add capability-level scoring

Score outcomes, not prompt similarity.

Produce a typed `ResearchCapabilityScore` with dimensions such as:

* verified_claim_recall
* unsupported_claim_count
* contradiction_handling
* required_evidence_coverage
* correct_withholding
* source_quality
* unnecessary_tool_calls
* research_budget_used
* completion_status

Prefer deterministic checks wherever possible.

A model judge may be optional for semantic usefulness, but it MUST NOT be the sole promotion criterion.

Verifier outputs and grounded Evidence objects should be primary inputs.

Hidden world expectations must never be passed to the research agent.

---

## 5. Connect production failures to capability cases

Add a bounded case-mining step.

After a real research session, use:

* verification.gaps
* task_board
* ResearchReport findings
* traces
* failed/unchecked evidence

to classify failures into a stable capability taxonomy.

Examples:

* SOURCE_DISCOVERY
* SOURCE_QUALITY
* CONTRADICTION_SEARCH
* ENGINE_GROUNDING
* CLAIM_WITHHOLDING
* AS_OF_DISCIPLINE
* CROWDING_CONFIRMATION
* REPLAN_FAILURE

Do not generate an arbitrary benchmark world from an LLM and immediately trust it.

A production failure may:

1. map to an existing frozen world/capability, or
2. create a `pending_world_candidate` artifact for later review.

Autonomous policy promotion may only use approved/frozen worlds.

This prevents the agent from writing its own exam and grading itself.

---

## 6. Close the existing improvement loop

Add a top-level bounded command, preferably:

`--rsi-cycle`

Conceptual flow:

1. Load active immutable ResearchPolicy.
2. Load approved research worlds.
3. Select target worlds associated with current OPEN gaps.
4. Add fixed guard worlds.
5. Evaluate baseline.
6. If baseline has no target failures: return `no_change`.
7. Build the existing FailureBundle.
8. Generate at most ONE minimal PolicyPatch using the existing candidate generator.
9. Validate the patch against current allowlists.
10. Materialize immutable candidate ResearchPolicy.
11. Run baseline and candidate through the Research Capability Arena.
12. Compare target improvements and guard regressions.
13. Promote only when the promotion contract passes.
14. Otherwise reject candidate and leave active policy untouched.
15. Persist a fully auditable experiment artifact.

Do not create recursive/unbounded improvement.

One invocation:

* max one candidate
* max one promotion
* finite worlds
* finite token/tool/time budgets

---

## 7. Promotion contract

A candidate may be promoted only if all of the following hold:

* deterministic engine guards pass
* at least one triggering target capability improves
* no guard world regresses
* unsupported claims do not increase
* contradiction handling does not regress
* correct-withholding guards do not regress
* all evaluated runs completed under configured bounds
* baseline and candidate used the same requested/resolved model
* candidate contains no unauthorized profile/tool/capability changes
* verifier remains policy-independent

If any evaluation is incomplete or ambiguous, fail closed and do not promote.

Do not optimize merely for aggregate score if a safety/grounding guard regresses.

---

## 8. Persist an auditable RSI experiment

Create something like:

`reports/rsi_experiments/<experiment-id>/`

containing:

* manifest.json
* baseline_policy.json
* candidate_policy.json
* policy_patch.json
* selected_worlds.json
* world hashes
* baseline runs/
* candidate runs/
* capability_scores.json
* comparison.json
* promotion_decision.json
* token/tool/latency usage
* model IDs
* failure bundle
* triggering gap IDs

The experiment must be replayable.

Never overwrite previous experiments.

---

## 9. Keep verifier asymmetric

Very important:

The independent Verifier must NOT load:

* candidate-generation reasoning
* profile_hints
* prompt evolution generated by the policy being evaluated
* hidden world expectations
* promotion decision logic

It receives only the research question, produced evidence/reports, allowed verification tools/observations, and verifier-owned rules.

Add tests proving this isolation.

---

## 10. Tests

Add deterministic tests for at least:

1. candidate fixes a target world and is promoted
2. candidate fixes target but regresses guard → rejected
3. candidate produces more unsupported claims → rejected
4. candidate spends more calls but adds no capability → not considered improvement
5. incomplete/timeout candidate run → rejected
6. baseline/candidate world hash mismatch → fail closed
7. resolved model mismatch → fail closed
8. hidden world expectations cannot enter agent prompts
9. verifier cannot load candidate policy overlay
10. active policy remains unchanged after rejected/error cycle
11. exactly one candidate maximum per `--rsi-cycle`
12. successful promotion affects a NEW research session but never mutates an already-running/resumed session

Keep existing tests passing.

---

## 11. Explicit non-goals

Do NOT implement:

* model weight training / SFT / RL
* self-modifying Python
* autonomous git commits
* autonomous creation of new tools
* new analyst profiles
* unbounded recursive improvement
* AgentBus
* LangGraph / LangChain / CrewAI
* MCP
* databases
* Docker/Kubernetes
* frontend changes
* general-purpose benchmark support

This is a narrow momentum-research RSI experiment.

---

## Definition of done

The feature is done when this can be demonstrated:

A frozen momentum research world exposes the same initial information to baseline and candidate.

Baseline independently researches the question and misses or mishandles a target capability.

A candidate policy is generated from the observed failure.

The candidate independently reruns the research world, chooses its own allowed search/tool trajectory, obtains better VERIFIED research output, passes guard worlds, and is automatically promoted.

A later fresh research session pins the promoted policy.

The entire causal chain is inspectable from artifacts:

research failure
→ gap
→ capability
→ candidate patch
→ autonomous baseline/candidate trajectories
→ verifier results
→ capability score delta
→ promotion decision
→ new active policy.

If the system cannot demonstrate that chain, do not describe it as an RSI loop yet.
