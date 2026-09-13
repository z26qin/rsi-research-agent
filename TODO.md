# Research agent priorities

The core product is the research agent loop and measurable self-improvement. Daily briefs supply recurring research questions and evidence; the frontend exposes answers, traces, and verification.

## Next: demonstrate improvement on real research failures

- [ ] Curate one genuine failed research trajectory and one passing regression guard from saved sessions. Record reviewer-authored expectations, case hashes, and observation dates; do not invent expected answers or treat missing data as a reasoning error.
- [ ] Run the existing bounded feedback/shadow workflow with baseline and candidate under identical models, tool observations, and budgets. Report target fixes, guard regressions, completion, evidence support, numeric-answer coverage, latency, and usage. An inconclusive result stays inconclusive.
- [ ] Repeat on representative reviewed cases before proposing any connection to automatic promotion. Document that the current `--improve` gate checks bundled offline contracts, while imported real cases and `--live-compare` remain separate. Preserve independent verification and per-session policy pinning.

## Supporting maintenance

- [ ] Align the application's DeepSeek cost estimates with documented current rates and distinguish estimates from actual billing.

Keep the implementation lightweight: reuse the existing case importer, evaluator, policy store, and reports. Do not add another orchestration framework or make self-improvement block daily delivery.
