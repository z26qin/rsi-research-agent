# Live RSI validation — 2026-09-13

The DeepSeek connection works. The final paired experiment completed all eight research/verifier runs and generated one valid candidate. It improved a triggering recovery-risk capability, but safety regressions rejected promotion. This is evidence of live autonomous research and target improvement, **not a completed safe-promotion loop**.

## Earlier paired result (extractive_v1)

- Experiment: `reports/rsi_live_demo/20260913_134231_c88ad74a/reports/rsi_experiments/20260913_134231_d052a050`
- Demonstration and session pins: `reports/rsi_live_demo/20260913_134231_c88ad74a/demonstration.json`
- Requested and resolved model: `deepseek-flash` in all runs.
- Production failure source: `20260910_003250_eb4b7abf`; eight mined capability cases.
- Targets: recovery risk and incomplete evidence. Fixed guards: local crowding, contradictory evidence, incomplete evidence.
- Actual bundled engine guard: `dm-2026-05-29` passed.
- Per-run controls: 8 turns per phase, 28 LLM requests, 32 tools, 500,000 total token ceiling, 8,192 output tokens, 300 seconds overall, 60 seconds per model call, temperature 0.
- Generation: one request, 8,192 output tokens maximum, 60-second timeout.

| World | VERIFIED recall, baseline → candidate | Unsupported findings, baseline → candidate | Outcome |
| --- | --- | --- | --- |
| high_quality_contradiction | 0% → 67% | 3 → 1 | Contradiction handling improved |
| incomplete_withholding | 0% → 0% | 3 → 4 | Unsupported findings increased |
| local_crowding | 33% → 0% | 1 → 4 | Guard regression |
| recovery_risk | 0% → 100% | 2 → 2 | Target improved |

“Unsupported” is the conservative extractive scoring contract: a finding must meet quote, sentence, category, stance, timestamp, source-read, and independent-verdict requirements. A source-supported paraphrase may fail this contract; this count is not a claim that every such statement is factually false. All sources and market observations are synthetic.

These saved metrics use the original `extractive_v1` scorer. The subsequent
`extractive_v2` excludes retrieval-process notes from claim penalties,
separates factual support from category/stance recall, and tracks reversed stance
as an interpretation error. It accepts narrowly defined equivalent missing-evidence
assertions while rejecting questions and conflicting known-value statements.
Historical artifacts and their original scoring semantics are retained unchanged.
Replay now checks saved scores as well as the decision and rejects unknown scorer
versions. The v1 rejection above is not retrospectively converted into a success.

Candidate feedback now packs complete observed records within its budget and
includes failed guard observations after a target failure triggers generation.
Previously, duplicated report narratives could consume the text limit before
source observations reached the generator. Public-format diagnostics identify
extractive-contract failures without supplying hidden expected answers.

The candidate selected its own searches, document reads, and a second recovery-risk investigation. Its policy was generated from observed baseline failures and the public research contract. Hidden expectations remained in scoring. The candidate’s target gain cannot outweigh the local-crowding regression or increased unsupported findings in incomplete evidence.

No policy was promoted. Production, existing/resumed demonstration sessions, and the fresh demonstration session all retain `dbc0fb5e969a`. Rejected candidate `be220797acaa` remains as an immutable version in the isolated demonstration store.

## Earlier live attempts

| Demonstration directory | Outcome |
| --- | --- |
| `20260913_132723_a29a2496` | rejected: Baseline research incomplete; no candidate generated |
| `20260913_133008_e0c124ba` | rejected: Baseline research incomplete; no candidate generated |
| `20260913_133310_0ca34e81` | error: ValueError: unknown profile: unwind_crash.verified_claim_recall |
| `20260913_133841_5fcd881b` | error: ValueError: candidate generation did not complete with a terminal stop |
| `20260913_210329_0c8d3fb4` | rejected before model calls: actual offline engine exceeded its 90-second bound while the full test suite was also running |
| `20260913_210635_07842230` | engine passed; rejected before generation because incomplete-evidence research returned an empty terminal response |
| `20260913_211241_2c34846d` | engine passed; rejected before generation because the review parser did not accept an explanatory rationale field |
| `20260913_211720_9a89e145` | all eight runs complete; candidate `d0e77cc36d5a` improved recovery target but increased unsupported findings in contradiction and incomplete-evidence guards; rejected and replay confirmed |
| `20260913_212720_95e698b0` | rejected before generation: baseline emitted invalid category enum `contrary_evidence`; original controls allowed no repair |
| `20260913_213340_eafd262a` | all eight runs complete; candidate `c78aab41e8eb` regressed on guards and showed no target improvement; rejected and replay confirmed |

The v2 local-crowding baseline in the latter run classified the event correctly,
with independently supported full-sentence findings, but used labels relative to
its local-unwind conclusion. Independent review confirmed that public stance
semantics were underspecified and that `market_regime` and
`contradicting_evidence` overlap. Its saved outcome remains rejected under v2.
For future v3 experiments, factual recall is separated from label alignment;
contradiction credit and reversed-stance checks remain separate safety criteria.
Both research and verifier receive the same mechanism-relative stance definition.
The review decision schema subsequently gained an optional bounded rationale;
it still rejects unknown fields and requires a valid assignment for replanning.
The completed v3 rejection exposed another feedback omission: per-finding records
retained verdict status but discarded independent verifier explanations. Subsequent
feedback includes bounded notes/issues for non-VERIFIED findings and observed
source quality; the total budget and hidden-answer exclusion remain unchanged.
Later runs pin a single bounded enum-repair request. It can correct only invalid
finding category/stance values; a deterministic comparison requires every other
field to remain unchanged. Repairs share the run's existing request/token/time
budget, cannot call tools, and never give the verifier a research policy.

All attempts remain saved; none was overwritten or converted into a success. The initial replay of the final experiment exposed reason-list ordering differences between selection and filename order. The fix canonicalizes new decisions and compares older reason lists without order sensitivity, preserving every reason and its count. Offline replay now reproduces the saved rejection without changing any experiment artifact.

## Validation

- Full unit suite and targeted lint/whitespace results are recorded in the completion audit. Unit tests use mocked transports and do not contact DeepSeek.
- New regression tests cover stopping without an unused assignment, rejecting an incomplete replan assignment, independent verifier scope, diagnostics for truncated generation, and replay of rejection across multiple worlds.
- Production tools, allowlists, committed research/verifier profiles, fixture expectations, and promotion gates remain unchanged.
- The original definition of done remains incomplete because the candidate did not qualify for safe promotion.
