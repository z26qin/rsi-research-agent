# ETF momentum proxy brief

## Run

```bash
uv sync --group dev
uv run momentum-research-agent --daily-brief --brief-source etf-proxy
uv run momentum-research-agent --daily-brief --brief-source etf-proxy \
  --as-of 2026-09-04 --session-dir reports/proxy-example
```

No API key is needed. Use only for personal research under provider terms;
public accessibility is not a commercial redistribution license.

The default target is the last XNYS session strictly before the current New York
date, including when run after the current close. Weekends, holidays and DST use
`exchange_calendars`, not a weekday approximation. An explicit date must be a
completed XNYS session (including early closes). Invalid dates never trigger a
download. Existing engine mode still requires `--as-of` and is unchanged.

## What is measured

MTUM is a long-only momentum ETF proxy; SPY is the broad-market comparison. This
is **not** the original model book, a winner-minus-loser factor, or an estimate
of actual positioning/crowding. No engine state labels, risk scores, crash
probabilities, trading instructions, LLM calls or policy changes are produced.

- 1/5/21/63-session returns: `AdjClose[t] / AdjClose[t-n] - 1`.
- Relative performance: `(1 + MTUM return) / (1 + SPY return) - 1`.
- 252-close drawdown: current adjusted close divided by the maximum of the last
  252 adjusted closes, minus one.
- 21-return annualized volatility: sample standard deviation (`ddof=1`) times
  square root of 252.
- Optional FRED VIXCLS: latest available observation at/before target, in index
  points. Its actual date and lag are explicit; no forward fill.

Percentages are formatted for humans; JSON stores fractional values. A price
window with a missing trading session is unavailable, not silently shortened.
Missing Adj Close never falls back to Close. Missing either target-date ETF
withholds all core metrics. VIX failure does not withhold valid ETF metrics.

## Collection and evidence

Each run fetches five years through the target date. Full-window refresh is
intentional for two ETFs: dividends/splits can revise the adjusted history.
yfinance is called with daily frequency, `auto_adjust=False`, `actions=True`,
and an exclusive end date one calendar day after target. Vendor-returned Close,
Adj Close, Volume and action columns are retained; tables are not described as
raw HTTP responses. FRED uses its public VIXCLS CSV endpoint.

Each source gets at most two worker attempts. Each subprocess is killed/reaped
after at most 20 seconds; all attempts share a 120-second collection deadline.
Local validation and file-writing time is additional. No background thread is
allowed to keep a blocked downloader alive. No alternate provider or stale-cache
fallback is used. Failures record safe exception types, not provider stderr.

Every run requires a new output directory:

```text
brief.json                 # etf_proxy_brief_v1, sources, metrics, warnings
brief.md                   # deterministic human rendering
manifest.json              # request parameters, attempts, times, versions, hashes
vendor/<source>-N.parquet   # returned table for attempt N, if produced
normalized/<source>.parquet # validated, date-bounded observations
```

Collection attempts update the manifest atomically. Failed runs never replace
the prior successful run. Vendor revisions remain visible in separate snapshots.
No table is presented as publication-time/PIT-certified: retrieved-at records
when this tool saw it, not when the provider first published it.

Exit 0 means `partial`: the proxy is available, subject to its research limits.
Exit 2 means `unavailable` or invalid invocation. Inspect the manifest for per-source
errors and `brief.json` for report-level limitations. Source `ok` does not mean
every longer metric window has enough history.

## Offline recomputation and comparison

```bash
uv run python -c 'import json,sys; from pathlib import Path; from momentum_research_agent.proxy_brief import replay_snapshot; print(json.dumps(replay_snapshot(Path(sys.argv[1])), indent=2))' reports/proxy-example
```

Replay reads no network. It checks the hashes of saved vendor and normalized
tables, re-normalizes vendor tables, verifies their equality with saved normalized
tables, and recomputes metrics. Keep the manifest and both table sets together.

Use `--previous-brief reports/<prior-run>/brief.json` for an earlier report of the
same type and calculation version. The earlier metrics are recomputed, not trusted
from editable summary fields. Prior manifest/table hashes must match. Changed
overlapping adjusted prices or historical coverage suspend comparison with a
revision warning. Cross-engine and cross-version comparisons are refused. Deltas
are changes in observed metrics, not predictive performance or causal attribution.

## Initial verification and operation

2026-09-08 live public-data smoke selected 2026-09-04; both ETFs and optional VIX
returned target-date observations. All 16 ETF metrics matched offline recomputation
exactly. This verifies one collection/replay run, not a provider reliability SLA.

Run manually before market open initially. Record five trading days of success,
latency and date coverage before considering scheduling separately. No scheduler
is installed by this feature; source licensing, sustained availability and
publication-time correctness remain operational limitations.

Sources: [yfinance](https://ranaroussi.github.io/yfinance/),
[MTUM](https://www.ishares.com/us/products/251614/ishares-msci-usa-momentum-factor-etf),
[FRED VIXCLS](https://fred.stlouisfed.org/series/VIXCLS),
[exchange_calendars](https://github.com/gerrymanoim/exchange_calendars).
