# Research agent priorities

The primary prototype is a useful momentum research assistant: it independently
finds readable sources, extracts dated evidence, and answers the user's research
question. Self-improvement should make that real research more useful. A successful
RSI arena promotion is not the first product milestone.

## First: answer a real research question usefully

- [x] Start with the persisted MTUM holdings failure: retrieve readable source
  content and produce the top ten holdings, weights, actual observation date,
  and source links. Distinguish blocked access from missing data and from a
  reasoning failure; a report describing failed retrieval is not an answered question.
- [x] Inspect the existing search → source reading → extraction → verification →
  answer path. Fix the concrete bottleneck using existing authorized tools and
  runtime bounds. Keep successful reads separate from independently verified claims.
- [x] Deliver a concise answer that leads with the requested facts, cites their
  sources and dates, and identifies remaining gaps without burying available facts.

M1 content delivery is implemented; full sign-off remains pending independent
MTUM verification (live verifier timed out). See [execution review](docs/m1-usefulness-review.md).

- [x] Resolve static-only verification being retained as VERIFIED after timeout;
  missing terminal verdicts now persist as UNCHECKED, and static rejections remain.
  Legacy answer presentation still marks missing rechecked sources as unconfirmed.

## Then: make momentum research useful repeatedly

- [ ] Exercise a small set of real questions: current momentum performance versus
  the market, holdings/concentration changes, and evidence for crowding or reversal
  risk. Separate observed facts, interpretation, contrary evidence, and unknowns.
- [ ] Evaluate actual answer coverage, evidence support, freshness, time, and
  usage. Preserve unsuccessful attempts alongside useful outputs; do not substitute
  process completion or synthetic benchmark scores for usefulness.

### First M2 execution

Three bounded live questions were exercised and preserved; all three reached the
research finalization deadline without structured findings. M2 acceptance remains
open. Manual deterministic price/concentration checks produced a research note,
which is explicitly not autonomous-agent success. See
[the first M2 review](docs/m2-first-research-review.md).

- [x] Return archived, deterministically calculated performance metrics through
  the existing research tools, instead of relying on rounded table arithmetic.
- [ ] Keep factual research focused and preserve retrieved facts within the
  existing finalization budget; do not increase retries to hide failure.
  Performance metrics now survive timeout and invalid numeric references are withheld;
  general research finalization and concentration/history coverage remain open.
- [ ] Obtain a comparable historical holdings snapshot and current positioning
  evidence before claiming concentration changes or crowding.

## After that: improve from real research failures

- [ ] Curate one genuine failed research trajectory and one passing regression guard from saved sessions. Record reviewer-authored expectations, case hashes, and observation dates; do not invent expected answers or treat missing data as a reasoning error.
- [ ] Run the existing bounded feedback/shadow workflow with baseline and candidate under identical models, tool observations, and budgets. Report target fixes, guard regressions, completion, evidence support, numeric-answer coverage, latency, and usage. An inconclusive result stays inconclusive.
- [ ] Repeat on representative reviewed cases before proposing any connection to automatic promotion. Document that the current `--improve` gate checks bundled offline contracts, while imported real cases and `--live-compare` remain separate. Preserve independent verification and per-session policy pinning.

## Supporting maintenance

- [ ] Align the application's DeepSeek cost estimates with documented current rates and distinguish estimates from actual billing.

Keep the implementation lightweight: reuse the existing case importer, evaluator, policy store, and reports. Do not add another orchestration framework or make self-improvement block daily delivery.

## Concentration implementation checkpoint

Official CSV reads now compute current top10, largest listing and sector weights;
validated two-date archives compute percentage-point changes and top10 entry/exit
contributions. Wrong dates, same dates, incompatible identities and changed hashes
cannot establish a comparison. Thirty tests remain; dedicated short-interest and
fixed-basket replay tests were replaced by two holdings cases.

One live MTUM run and independent verifier confirmed current Sep 11, 2026 figures.
The configured Aug 14 historical CSV was unavailable to both, so all historical
change values remain missing. Historical comparison arithmetic is tested on
synthetic fixtures but not yet accepted against a real two-date pair. See
[concentration execution review](docs/concentration-delivery-review.md).

## Integration and risk checkpoint — 2026-09-15

Merged and pushed useful metrics/verification work as 2055d43; 30 tests pass.
A live risk run retained six independently checked metrics despite finalization
timeout, but crowding/reversal interpretation remains incomplete. An actual-data
offline comparison confirms timeout retention improves from zero to six metrics;
a successful terminal-report binding guard is unchanged. This is not policy
self-improvement. Seven actual failures were imported, all blocked on replay
compatibility. Next: bounded archive replay for read_url/market_data, preserving
hashes and unknown-call rejection, then a paired real-failure/real-success policy
comparison. See [risk and improvement review](docs/risk-and-improvement-review.md).
