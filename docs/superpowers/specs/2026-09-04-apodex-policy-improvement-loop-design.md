# Apodex-Style Policy Improvement Loop

## Goal

Add a small, controlled self-improvement loop to the momentum research agent. Offline evaluation failures and recorded failed trajectories produce one constrained policy candidate. The candidate becomes active only when it fixes at least one triggering case and causes no per-case regressions across the complete offline suite.

This phase combines:

- evaluation failures that generate and replay improved research tasks;
- trajectory-informed evolution of prompt overlays, task templates, and tool-selection guidance.

Live staged replanning during a run is the next phase. This design leaves a clean input for it but does not implement it.

## Constraints

- Never generate or modify Python or tool implementation code.
- Keep committed analyst profiles frozen.
- Never apply evolved policy to the verifier.
- Generate at most one candidate per failed evaluation cycle.
- Do not add a database, daemon, search tree, agent framework, or plugin framework.
- Do not call DeepSeek, web search, or live market-data services while running the promotion suite.
- Preserve the existing bounded follow-up, gap-seed, and replan limits.

## Architecture

The existing `--eval` failure path is the loop entry point. A file-backed `PolicyStore` keeps immutable policy versions under `reports/policies/` and an atomic `active.json` pointer. Normal research runs load only the active version.

When an evaluation fails, a `PolicyImprover` receives a failure bundle containing the failed cases, verifier gaps, relevant recorded trajectories, and the active policy. It makes one constrained LLM reflection call and parses the response into a schema-validated policy candidate. The response cannot contain executable code.

A promotion runner evaluates both the active policy and the candidate against the same layered offline suite. A pure comparator promotes the candidate only when it fixes at least one triggering case and every previously passing case remains passing. Rejected candidates never change the active pointer.

Two small extension seams preserve the future direction:

- `CandidateGenerator` produces a schema-validated policy candidate. The first implementation uses one constrained LLM reflection call; later implementations may use other live models.
- `EvalCaseProvider` supplies evaluation cases. The first implementation reads local engine fixtures and recorded trajectories; later providers may use live data-pipeline adapters.

These are typed interfaces passed directly to callers, not a discovery or plugin system. The policy store and promotion comparator depend only on their stable input and result schemas.

## Policy Model and Storage

Each immutable policy version is a compact JSON document with:

- version ID, parent version ID, creation time, and triggering failure IDs;
- prompt overlays keyed by research profile;
- task-template additions keyed by momentum capability;
- preferred or required tool-selection guidance keyed by profile and capability;
- promotion evidence: target fixes, aggregate score, and per-case results.

The policy schema permits declarative text and tool names only. It rejects unknown research profiles, verifier overlays, unknown tools, executable content, and unbounded rule collections.

`reports/policies/active.json` contains only the active version ID. Version documents are written before the pointer is atomically replaced, so an interrupted write cannot select a partial version. Moving the pointer to an earlier passing version provides rollback.

Recorded trajectory fixtures remain separate from policy versions so every candidate is evaluated against the same cases. `reports/profile_hints.md` remains a generated human-readable rendering of the active policy for compatibility; it is not the source of truth.

## Evaluation Suite

The first promotion suite is fully offline and deterministic.

### Engine cases

Engine cases run against pinned fixture data and assert the delivery contract, as-of date, recomputed fingerprint, and expected risk state. They extend the current frozen engine evaluation rather than introducing a second engine harness.

### Recorded-trajectory cases

Trajectory cases replay stored tool observations and score declared decision checkpoints:

- capability classification;
- selected task template;
- permitted, preferred, or required tools;
- required evidence handling;
- verifier isolation.

The initial suite does not rerun the research model. Prompt overlays are checked structurally and for required-rule coverage. This intentionally avoids claiming that deterministic tests prove natural-language research quality. A future live evaluation provider may return the same per-case result schema after running a model and data pipeline.

### Promotion rule

A candidate is promoted only when all conditions hold:

1. The candidate and its referenced profiles, capabilities, and tools validate.
2. At least one triggering case changes from failing to passing.
3. Every previously passing case still passes.
4. The suite's aggregate score increases; ties are rejected.

Missing fixtures, generation errors, schema errors, timeouts, or comparison errors fail closed and leave the current policy active.

## Runtime Data Flow

```text
offline eval failure
  -> failure bundle (cases + gaps + trajectories + active policy)
  -> one constrained policy candidate
  -> baseline and candidate offline runs
  -> per-case comparison
  -> write immutable candidate
  -> atomically promote or record rejection
```

Normal research runs compile the active policy into profile-specific prompt overlays, capability-specific task additions, and tool-selection guidance. The verifier continues to load its frozen profile with policy application disabled.

The future live-replanning phase may read the same active task and tool policy while updating the shared task board. It must not change the promotion rules or mutate policy during an active research run.

## Failure Handling and Auditability

- Candidate generation failure records a failed experiment and changes nothing active.
- Invalid candidates are rejected before evaluation.
- Evaluation failures distinguish infrastructure errors from scored case failures.
- Promotion writes the immutable version first and replaces `active.json` last.
- Rejected experiment metadata records the parent version, trigger, and reason without making the rejected policy active.
- Every result can be reproduced from a policy version and the suite fixture versions.

## Testing

Implementation will be test-driven and will cover:

- policy schema validation and forbidden verifier/code changes;
- initial policy creation, immutable version writes, and loading;
- constrained candidate parsing;
- deterministic engine and trajectory case execution;
- required target improvement;
- rejection of per-case regressions and aggregate ties;
- successful atomic promotion and explicit rollback;
- interrupted or invalid writes leaving the active policy unchanged;
- compilation into research prompts, task templates, and tool guidance;
- verifier isolation;
- compatibility rendering to `profile_hints.md`.

No unit or integration test will call the live DeepSeek API.

## Deferred Work

- Live LLM research-run evaluation.
- Live data-pipeline or market-data adapters for evaluation cases.
- Multiple candidate search, ranking, or iterative self-reflection.
- Live staged return, shared-plan mutation, and branch cancellation.
- Autonomous code or tool implementation changes.
