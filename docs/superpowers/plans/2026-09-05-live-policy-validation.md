# Live policy evaluation validation record

This increment implements session-case import and shadow comparison of real LLM
decisions over fixed recorded observations. It does not enable live promotion,
change the independent verifier, add live data adapters, or implement B replanning.

## Credentials and connectivity

The existing locally stored DeepSeek credential was reused without changing its
source file. Its local variable name was mapped to `DEEPSEEK_API_KEY` only inside
the validation process. No credential value is included in this repository.

A single connectivity request succeeded on 2026-09-05:

- Requested model: `deepseek-chat`; response model: `deepseek-v4-flash`.
- Hard request limit: one; SDK retries disabled; timeout: 20 seconds.
- Maximum output: 16 tokens. Reported usage: 6 prompt + 1 completion = 7 tokens.

This verifies credentials and a chat completion, not tool-calling behavior or
research improvement. The reply content was not persisted.

## Dataset limitation

No historical session artifacts were found in the main checkout, prior policy
worktree, or earlier project working copy. Imported cases require complete source
artifacts and separately reviewed expectations before behavioral scoring. Synthetic
test fixtures are not historical failures and cannot substantiate a real-world
improvement claim.

## Validation status

- Pre-change full suite: 153 passed.
- Session import task after review fixes: 173 full-suite tests passed; importer
  module coverage 86%.
- Replay/comparison/CLI focused tests: 45 passed after review hardening.
- Independent full suite on `c656cd8`: 210 passed in 2.07 seconds. Combined
  coverage of the three new evaluation modules: 86% (importer 86%, replay 91%,
  comparison 82%). CLI help and whitespace checks also passed.
- CLI with valid comparison inputs but no key printed the enforced bounds and
  returned exit 2 before any request.
- Bundled offline engine check `dm-2026-05-29`: passed independently.
- Historical-failure experiment (3–5 targets plus independent guards): pending
  real session data and curated assertions.
- Automatic live promotion: intentionally disabled; comparison is shadow-only.

## Bounded real-LLM wiring smoke

On 2026-09-05, the real DeepSeek client ran two explicitly synthetic cases against
baseline `dbc0fb5e969a` and candidate `db700c811d08`. One case required withholding
an unavailable datum; the guard required evidence from a fixed toy observation.
The example source is on `example.invalid`, not a real financial source.

- Requested and returned model: `deepseek-v4-flash` throughout.
- Two policies × two cases × one repeat = four successful agent runs.
- Each agent called `web_search` once; its observation came from the in-memory
  replay registry, not the web. Eight model requests were made in total.
- Hard limits: 12 model requests, 1,024 output tokens per request, three turns per
  run, 40-second call timeout, 90-second run deadline; SDK retries disabled.
- Reported usage: 9,317 prompt + 1,653 completion = 10,970 tokens. Including the
  earlier connectivity check, this increment used 10,977 reported tokens.
- Both policies passed both cases. `observed_no_regression=true`, but
  `target_improvements=[]`: no improvement was demonstrated.
- The isolated smoke active-policy pointer was byte-identical before and after.
  Production policy/gap state was not touched by the comparison.

After the live run, additional offline regression tests hardened unknown-tool
handling, strict terminal completion (empty/filtered/truncated responses), finite
positive runtime budgets, and per-run/per-pair resolved-model drift. No further
paid calls were needed.
The actual credential value was checked against changed files and local smoke
JSON artifacts and was not present.

Local ignored report:
`reports/synthetic_live_smoke/reports/live_evals/20260905_223059_8ef8d45f/comparison.json`.
It contains policy/case/expectation snapshots, hashes, actual model/tool outputs,
usage, timing and per-run assessments. The default comparison uses two repeats;
this deliberately small wiring smoke used one. It is not statistical evidence.

## Scope decisions

1. Deliver slices 1–3 first, as the accepted plan specifies. Promotion and B remain
   later increments; this costs an additional integration phase.
2. Implement the replay runtime and comparison as one task because their budget,
   outcome and CLI contracts are coupled; this creates a larger review surface.
3. Without historical data, use only a clearly labeled synthetic-fixture live
   wiring smoke. This leaves real improvement validation for a later data-backed run.
4. Keep verifier traces as source provenance, separate from research-task replay
   inputs, because the original ledger intentionally includes both. This adds a
   small source/replay distinction instead of rejecting ordinary verified sessions.
5. Bind source-identity collisions to the canonical directory without requiring
   directory basename to equal session ID; custom session directories remain valid.
   A moved source directory yields a distinct occurrence identity.
