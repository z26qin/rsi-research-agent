# Essential test suite

The repository retains **30 collected behavior and regression tests**. Removed cases and unused helpers were deleted,
not skipped, deselected, or bundled into a hidden suite. Parameter matrices were
reduced to representative scenarios. This deliberately trades exhaustive edge-case
coverage for a small maintained suite.

Run the suite and inspect its count:

```bash
uv run pytest
uv run pytest --collect-only -q
```

| Coverage | Cases | Files |
| --- | ---: | --- |
| Unknown profiles and unauthorized tools | 2 | `test_authorization.py` |
| Independent source reads and timeout fallback persistence | 2 | `test_verifier.py` |
| Cancellation, deadline, truncated tool responses | 3 | `test_react_loop.py` |
| Full research delivery, bounded follow-up, resume policy isolation | 3 | `test_coordinator.py` |
| Native discovery remains unverified with replayable provenance | 1 | `test_native_search.py` |
| Real bundled engine delivery ignores poisoned snapshots | 1 | `test_engine_pipeline.py` |
| CLI subprocess delivery and supplement failure isolation | 2 | `test_daily_brief.py`, `test_brief_research.py` |
| Share-based flows | 1 | `test_crowding_metrics.py` |
| Official holdings comparison, rank attribution, exact dates and integrity | 2 | `test_holdings_comparison.py` |
| Validated rollback and per-case improvement veto | 2 | `test_policies.py`, `test_policy_improver.py` |
| Cross-session gap occurrence persistence | 1 | `test_gap_seed.py` |
| Self-contained paired shadow comparison | 1 | `test_live_compare.py` |
| RSI failure-to-promotion integration, engine gate, final-veto replay | 3 | `test_rsi_cycle.py` |
| Verifier isolation | 1 | `test_research_arena.py` |
| Common-date performance calculations, archives, timeout retention | 2 | `test_performance_delivery.py` |
| Source-only lookup delivery and verdict-aware answer rendering | 2 | `test_research_completion.py` |
| Successful engine reads cannot override the actual failure category | 1 | `test_capability_mining.py` |

All model and remote data responses are local test doubles. The bundled-engine
case executes the real pipeline against local fixtures. Synthetic RSI promotion
tests prove integration and guards, not autonomous live-model improvement.

When adding a test, replace a lower-value case to keep the 30-case ceiling.

M1 replaces the arena enum-repair and withholding-credit cases with the two
useful-answer regressions. Their exhaustive edge-case coverage is no longer
maintained; authorization, independent verification and both RSI bug regressions remain.

The verifier-timeout regression replaces the frozen-world manifest-tampering case.
It exercises a successful independent source read followed by a terminal timeout,
then checks saved UNCHECKED status, retained rejection and the pending gap.

Performance delivery replaces the synthetic clipped-negation case and RSI cycle
guard-regression case; the independent policy-improver per-case veto test remains.
The new cases cover unrounded common-date math, missing sample rejection, archived
hashes, timeout recovery and tampered-archive refusal.

Holdings comparison replaces the dedicated short-interest and fixed-basket replay
cases. The shared short-interest network fixture remains in short_interest_fixtures.py
for daily-brief failure isolation; it does not contain hidden or skipped tests.
Those advanced replay paths no longer have dedicated maintained cases.
