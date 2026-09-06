# Tasks 4 and 5 Report: Constrained Policy Improvement Cycle

## Status

Complete.

## Implementation

Added one bounded improvement cycle. A `FailureBundle` contains only failed
trajectory checkpoints, their failure labels, and recorded observations
truncated to 1,000 characters. Recorded text is labeled as untrusted evidence
in the generation prompt. The LLM generator embeds the exact `PolicyPatch`
JSON schema and concrete research-profile tool allowlists, constructs its
client lazily, disables SDK retries with `with_options(max_retries=0)`, and
wraps its single request in an asyncio timeout.

The cycle evaluates the active policy first and returns without constructing
or calling an LLM client when all checks pass. Missing layers, duplicate cases,
and failed engine guards reject before generation. One generated patch and its
merged candidate are both validated against research-only `PROFILE_TOOLS`,
then evaluated against the identical engine results and recorded trajectory
cases. Existing per-case comparison admits promotion only when a triggering
case is fixed without pass/fail or score regression.

Every evaluated candidate writes one experiment containing the baseline and
candidate suites and policies, generated patch, decision, generation model,
and SHA-256 fixture fingerprints. A promoted immutable version carries its
`PolicyEvaluation`. A minimal exclusive file prevents concurrent cycles from
overwriting the active pointer. Cancellation propagates and releases the lock.
Compatibility rendering happens after activation; a rendering failure is
reported as a warning on a truthful `promoted` outcome rather than relabeling
the completed activation as an unchanged error.

## TDD Evidence

The initial focused run was intentionally RED before the module existed:

```text
ModuleNotFoundError: No module named 'momentum_research_agent.eval.policy_improver'
```

The concrete allowlist prompt check was separately RED before allowlist values
were added:

```text
AssertionError: assert '"momentum_analyst"' in system
```

After implementation:

- Focused: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/aaronqin/Desktop/rsi-research-agent/.worktrees/apodex-policy-loop/.venv/bin/python -m pytest tests/test_policy_improver.py -q` — 12 passed.
- Policy integration: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/aaronqin/Desktop/rsi-research-agent/.worktrees/apodex-policy-loop/.venv/bin/python -m pytest tests/test_policy_improver.py tests/test_policy_suite.py tests/test_policies.py -q` — 41 passed.
- Full suite: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/aaronqin/Desktop/rsi-research-agent/.worktrees/apodex-policy-loop/.venv/bin/python -m pytest` — 144 passed in 1.07s.
- `git diff --check` — clean before the implementation commit.

Tests cover failed-only bundling and truncation, a single bounded non-retrying
call, schema and authorization failures, no-change zero calls, pre-generation
engine and layer rejection, target repair, per-case regression, generator
failure, interrupted activation with lock cleanup, successful activation with
attached evaluation, reproducibility metadata, and truthful promotion when
derived rendering fails. No test invoked DeepSeek, web search, or live market
data.

## Commit

`a0a2d1f feat: add constrained policy improvement cycle`

## Operational Note

The exclusive lock fails closed if another cycle is active. A hard process
kill that bypasses Python cleanup can leave the small lock file in place; the
next cycle will refuse to run rather than risk overlapping promotion.

## Review Follow-up: Failed Experiment Provenance

Review found that the experiment ID was allocated only after candidate
generation and evaluation. Consequently, generator, schema/authorization,
merge, or candidate-evaluation failures returned without an experiment record.
The failure bundle also omitted the profile and capability associated with each
failed trajectory case, forcing a generator to infer context from case IDs.

The cycle now allocates its experiment ID immediately before the sole
generation attempt. Each stage records its current phase, reason, baseline
policy and suite, failed-only bundle, fixture fingerprints, generation model,
and any patch, merged candidate policy, or candidate suite already available.
If the error record itself cannot be written, the outcome retains the allocated
ID and explicitly includes the persistence failure without changing the active
policy. `FailureBundle` now carries failed-only `case_profiles` and
`case_capabilities` mappings sourced directly from `RecordedTrajectoryCase`,
independent of case-ID naming.

The new regression tests were RED with six failures: the new bundle fields
were rejected or absent, and generator/evaluation error outcomes had no
experiment IDs or files. After the correction:

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/aaronqin/Desktop/rsi-research-agent/.worktrees/apodex-policy-loop/.venv/bin/python -m pytest tests/test_policy_improver.py -q` — 14 passed.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/aaronqin/Desktop/rsi-research-agent/.worktrees/apodex-policy-loop/.venv/bin/python -m pytest tests/test_policy_improver.py tests/test_policy_suite.py tests/test_policies.py -q` — 43 passed.
- `git diff --check` — clean before commit.

Review-fix commit: `9c34ab8 fix: preserve failed policy experiments`.

## Final Review: Promotion Audit Finalization

The pre-activation experiment previously used `status: promoted`, so an
`asyncio.CancelledError` during version activation propagated correctly but
left a false promoted audit record while the baseline pointer remained active.
Accepted candidates are now first persisted as `approved` in the
`promotion_pending` phase. Only after the active pointer confirms the candidate
does the same experiment finalize to `promoted` in the `activated` phase.

If that final audit write fails after activation, the cycle preserves the
truthful `promoted` outcome and adds an audit-finalization warning. The earlier
approved record remains on disk rather than falsely claiming a completed audit
update. The interrupted-activation regression test now checks both the baseline
pointer and the non-promoted record; the successful path checks the finalized
status. The historical `git diff --check 9f1afec..HEAD` trailing blank in the
Task 0 report was also removed.

The three new assertions/tests were RED before the state transition was added:
the successful record remained in the `decision` phase, cancellation left
`status: promoted`, and no second audit write existed to exercise the warning
path. After the correction:

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Users/aaronqin/Desktop/rsi-research-agent/.worktrees/apodex-policy-loop/.venv/bin/python -m pytest tests/test_policy_improver.py tests/test_policy_suite.py tests/test_policies.py -q` — 44 passed.
- `git diff --check 9f1afec..HEAD` — clean after commit.

Final review-fix commit: `3a3e480 fix: finalize promotion audit after activation`.
