# Essential test suite

The repository retains **30 collected tests**: 28 selected core cases and two
regressions from the RSI review. Removed cases and unused helpers were deleted,
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
| Independent source reads before verification | 1 | `test_verifier.py` |
| Cancellation, deadline, truncated tool responses | 3 | `test_react_loop.py` |
| Full research delivery, bounded follow-up, resume policy isolation | 3 | `test_coordinator.py` |
| Native discovery remains unverified with replayable provenance | 1 | `test_native_search.py` |
| Real bundled engine delivery ignores poisoned snapshots | 1 | `test_engine_pipeline.py` |
| CLI subprocess delivery and supplement failure isolation | 2 | `test_daily_brief.py`, `test_brief_research.py` |
| Share-based flows, short-interest replay, fixed-basket replay | 3 | `test_crowding_metrics.py`, `test_short_interest.py`, `test_fixed_basket.py` |
| Validated rollback and per-case improvement veto | 2 | `test_policies.py`, `test_policy_improver.py` |
| Cross-session gap occurrence persistence | 1 | `test_gap_seed.py` |
| Self-contained paired shadow comparison | 1 | `test_live_compare.py` |
| RSI failure-to-promotion integration, guard veto, engine gate, final-veto replay | 4 | `test_rsi_cycle.py` |
| Verifier isolation and clipped-negation rejection | 2 | `test_research_arena.py` |
| Enum repair cannot rewrite claims | 1 | `test_arena_schema_repair.py` |
| Frozen-world tampering rejected | 1 | `test_research_world.py` |
| Known evidence cannot earn missing-evidence credit | 1 | `test_withholding_contract.py` |
| Successful engine reads cannot override the actual failure category | 1 | `test_capability_mining.py` |

All model and remote data responses are local test doubles. The bundled-engine
case executes the real pipeline against local fixtures. Synthetic RSI promotion
tests prove integration and guards, not autonomous live-model improvement.

When adding a test, replace a lower-value case to keep the 30-case ceiling.
