# Performance delivery implementation and acceptance

## Result

Daily market_data now produces dated deterministic comparison metrics with a
hashed archive of the full-precision prices used. A finalization failure no longer
throws away these calculations. Valid report content can also survive an orphan
numeric reference: the offending metric is withheld, the mixed summary suppressed,
and coverage marked partial. No provenance is invented and no validation is relaxed.

The latest full live question completed in 39.17 seconds with a valid researcher
report. The verifier confirmed the two ticker evidence items containing all six
requested core metrics; two contextual items remain weak. Its overall result is
pass_with_caveats. This is useful performance delivery, not acceptance of broader
crowding research or proof that all future model finalizations will finish.

## Preserved attempts

All used the prior exact performance question, deepseek-flash, policy dbc0fb5e969a
and unchanged per-role limits. No new tool authorizations or policy promotion.

| Attempt | Duration | Result |
| --- | ---: | --- |
| Prior M2 baseline | 45.72 s | Finalization timeout; no findings/metrics |
| Calculation + archive fallback | 35.01 s | Invalid report; six retained metrics independently reproduced |
| With terminal diagnostics | 33.78 s | Same failure; diagnostics identified an orphan sample-count metric |
| After withholding broken references | 39.17 s | Valid report; six core metrics confirmed, context remains caveated |

The three implementation-stage runs are preserved separately. The latest model
happened to emit valid references, so it did not exercise recovery; the saved
invalid output and offline regression cover that branch. These changing
implementations are diagnostic runs, not a controlled statistical speed comparison.

## Source and arithmetic acceptance

Actual window: 2026-08-14 through 2026-09-11, 20 common closes / 19 daily returns.
The model copied the six core values at full precision. Standard-library arithmetic
independently reproduced them from the hash-checked archive:

| Percent | MTUM | SPY |
| --- | ---: | ---: |
| Adjusted-price return | -3.206073 | -1.552161 |
| Annualized sample volatility | 21.702208 | 8.971402 |
| Within-window maximum drawdown | -7.933064 | -2.384266 |

These are Yahoo Finance adjusted-price calculations, not audited NAV total returns
or a long-short momentum factor. Independent verifier recomputation uses the same
vendor; it is not independent third-party price confirmation. Requested core
metrics match the archive; extra model-derived metrics are not automatically
certified by that arithmetic check. Returned dates are explicit, not a claim of
latest market freshness.

## Boundaries

- Research/LLM/tool deadlines and turn counts unchanged.
- Current calendar-day observations conservatively excluded; missing common
  sessions, duplicate dates and nonfinite/nonpositive prices are unavailable.
- Daily market_data uses JSON; non-daily single-ticker calls retain legacy Markdown.
- Timeout retention uses the latest successful performance archive only, not
  general extraction from arbitrary web pages or unfinished model prose.
- market_data is retained in the existing trace log. Paired policy shadow
  evaluation still rejects this tool; no new evaluation backend was added.
- Broader concentration/history and positioning/crowding research remain open.
- Research can still add unnecessary engine/context calls; this work does not
  guarantee complete semantic discipline or eliminate external model latency.
- Code remains unmerged in codex/useful-momentum-research.

## Checks

30 collected tests, all passing. Added two essential performance cases by removing
two lower-priority synthetic arena cases (documented in tests/README.md). Core
checks include hand-derived sample math, missing-window refusal, archive hashes,
timeout recovery, tamper rejection and broken metric-reference withholding.
Independent review found no blocking issues in the calculations or recovery.

Local artifacts: comparison.json, acceptance.json, execution.json, performance/
(answer.md, verification.json, traces.jsonl, market_observations/, finalizations/).

Run directory: `reports/usefulness/20260914_205340_performance_fix/`.
