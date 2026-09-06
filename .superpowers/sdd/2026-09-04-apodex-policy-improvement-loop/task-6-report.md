# Task 6 Report: CLI Integration and Offline Guard

## Status

Complete.

## Implementation

Added mutually exclusive `--eval` and `--improve` CLI paths. The existing eval
path is unchanged. Improvement runs the pinned `CASES` through an explicit
bundled engine root, a private temporary cache, and a network-blocked
subprocess; it never enters `engine_query`, `local_dm`, or market-data
fallbacks. V_D re-checks the exact date, risk state, fingerprint, and delivery
hash before one policy cycle may begin.

Candidate construction is lazy. Missing or invalid fixtures reject before any
generator call, while a missing DeepSeek key is reported without secret values
only when the baseline requires generation. The CLI uses the packaged
trajectory fixture, requests at most one candidate, reports baseline failures,
candidate status, active version, and reason, and maps promoted/no-change to 0,
rejected/error to 1, and a missing key to 2.

README and AGENTS now describe offline contract coverage, frozen profile and
verifier isolation, session policy snapshots, policy artifacts, validated
rollback, and stale-lock recovery. Live LLM/data evaluation and staged
replanning remain deferred.

## Verification

- RED: the first focused run failed during collection because
  `run_offline_engine_eval` did not exist.
- Focused CLI/engine checks: 72 passed.
- Full suite: 152 passed in 1.23s.
- `git diff --check`: clean.
- `--help`: lists `--eval | --improve` as mutually exclusive.
- `--eval`: passed the existing frozen DM V_D check.
- Actual offline fixture subprocess: passed `dm-2026-05-29` with risk state
  `normal`, fingerprint `a3fed64fc1d0d687`, and delivery hash
  `1a2d3c95609db4f7`.

No test or smoke command called DeepSeek, web search, yfinance, or another live
market-data service.
