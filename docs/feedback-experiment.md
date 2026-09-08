# Lightweight feedback experiment

One standalone script reuses the existing analyst profile and detailed ReAct loop, static audit, session importer,
schema-validated reflection, and stored-observation comparison. It does not change
the normal agent loop. There is no promotion, deployment, background loop, or new
data adapter.

Its added value over `--live-compare` is orchestration: capture a fresh historical
trajectory, pause for human review, reproduce the target failure and passing
guard, generate one constrained candidate, then compare it—all under one
persisted allowance. `--live-compare` alone requires cases and both policies to
be supplied. This script is experiment tooling, not evidence of a better agent.

## Capture

From the repository, with its Python dependencies installed:

```sh
PYTHONPATH=src python scripts/feedback_experiment.py reports/feedback-demo
```

Set `DEEPSEEK_API_KEY` in the process environment first. The script does not read
or copy personal credential files. For the existing local configuration, load
`DEEPSEEK_API_KEY` or its `DeepSeekAPI` alias from the user-owned `.env` into the
process only; never paste it into a command, report, or commit.

The script pins `deepseek-v4-flash`, the bundled historical engine, and the
2026-05-29 SPY task. It snapshots the current active policy read-only, or uses an
empty baseline when no active policy exists. Only `engine_query` is exposed.
No new data-service API key is required. This is historical research, not current
market coverage. Trace truncation, fallback data, or missing calls stop capture.
Tool observations are persisted immediately, so a later provider error cannot
erase them. Incomplete runs and malformed final reports block the task rather
than becoming research failures for reflection. The engine-directory environment
setting is restored on exit, including failure.

Outputs live under the supplied directory:

- `state.json`: status and cumulative model attempts.
- `session/`: original report, tool traces, task board, static verification.
- `baseline.json`, `profiles/`: pinned policy and analyst prompt.
- `captured-cases.json`: actual imported gaps, with replay blockers preserved.
- `responses/`: returned model name, finish reason, and response text, including
  incomplete output. Request headers and provider error messages are not saved.

`review_required` means **possible failures**, not confirmed errors. Static audit
can flag an appropriately unanswered question. `no_failure_found` means no gap was
identified; it is not a quality certification. Neither state generates a patch.

## Review, then run the same command again

Manually inspect the report and complete observations. Only if there is a genuine
replayable failure, provide:

1. `reviewed-cases.json`: exactly two full existing `SessionEvalCase` objects:
   one unchanged case from `captured-cases.json`, and one real historical
   regression case expected to pass now. Both must use the pinned policy and same
   analyst profile. Do not invent a gap or label synthetic data as real to create
   a guard. If no suitable guard exists, stop and collect/review one separately.
2. `expectations.json`: the existing `BehavioralExpectationSet` schema, one
   `target` and one `guard`. Include reviewer, provenance, rationale, exact
   required tool arguments, allowed report statuses, and either required evidence
   or explicit withholding. Bind each to `case_content_sha256(case)` from
   `momentum_research_agent.eval.replay_runner`. Do not ask the candidate-generating
   LLM to author its own expected answers.

The script first replays both with the baseline. Unless the target fails a
scorable assertion and the guard passes, it stops before reflection. It then
requests at most one target-profile prompt overlay (1,000 characters maximum),
rejects task-template/tool-policy changes, and runs old/new once each on both
cases. It writes `preflight.json`, `candidate.json`, and
`reports/live_evals/.../comparison.json` inside the experiment directory.

This small comparison measures specified behavioral assertions only. One success
does not demonstrate stable improvement; **the active policy never changes**.
The wider deterministic suite remains the existing test suite, not a new
promotion gate in this script.

## Limits and interruption

All phases share **20 total attempted model requests**, including errors and the
baseline preflight. Each response is capped at 2,048 output tokens; SDK retries
are disabled. Each research/replay run has at most three model turns. Requests
are reserved on disk before sending. Running the command again does not reset
the budget or rerun completed/error/interrupted experiments. A process lock
prevents concurrent runs against the same directory.

An interrupted `running` or `error` experiment is terminal for automatic use;
inspect its artifacts before deciding what to do. Do not delete state or make
new directories to bypass the agreed budget. Provider errors are recorded by
type only, without provider messages or credentials. Actual model calls require
the user's authorization; unit tests use fake LLM responses and real local logic.
Review-file validation failures before any new model request remain
`review_required`: correct the files and rerun without resetting the counter.
Once model execution has started, failed runs are not automatically retried.
Inspecting terminal state or waiting for missing review files needs no API key.

## First live attempt (2026-09-08)

The first real DeepSeek capture used 3 of the 20 allowed attempts and stopped
with `ValueError`, before producing an importable report. No candidate was
generated, no comparison ran, and no policy was activated. That attempt preceded
the response-diagnostics addition, so the precise provider finish reason was not
retained; do not infer a confirmed research failure from it. Its local state is
`reports/feedback-20260908/state.json`. It has not been reset or retried.
