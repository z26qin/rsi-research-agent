# Daily momentum research: five questions

Run manually before the next US session, from the repository root:

```bash
uv run momentum-research-agent --daily-brief --brief-source etf-proxy \
  --with-market-research --reference-date 2026-05-29
```

The default target is the last XNYS trading session **before today in New York**.
An explicit completed `--as-of YYYY-MM-DD` is also accepted. Reference date is
optional, must be an earlier trading session, and is not silently rolled forward.
Use `--session-dir` to choose a new output directory; existing runs are never
overwritten. On September 8, 2026, the default target is September 4 (Labor Day
was September 7).

Every `market_brief.md` and `market_brief.json` answers:

1. Is momentum strengthening or weakening? MTUM/SPY relative returns and their
   changes, with explicit horizons rather than an invented risk score.
2. Is long exposure concentrated? Dated issuer top-10 weight, equity HHI, largest
   sector, equity coverage, and same-date IVV context. The underlying `brief.md`
   also contains all sectors, MTUM/QUAL/IVV overlap and available creation data.
3. Is short-interest pressure changing? MTUM ETF position changes across actual
   FINRA disclosures, plus descriptive DTC for a fixed current constituent basket.
4. Is volatility rising? MTUM and SPY 21-return sample volatility, annualized by
   `sqrt(252)`, compared with the previous session and optional reference date.
5. Can actual momentum crowding be established? The answer can be **insufficient
   evidence**. These proxies do not measure market-wide ownership, borrow fees,
   utilization, investor leverage or forced-unwind probability.

## Dates and comparison semantics

Price comparisons recompute both endpoints from **one current adjusted-price
vintage**. They are retrospective, not what an investor could necessarily have
known on the reference date. They do not override the original proxy's strict
cross-snapshot revision check. Missing sessions make the affected metrics
unavailable; no forward fill is used.

FINRA's [official reporting schedule](https://www.finra.org/filing-reporting/regulatory-filing-systems/short-interest)
is archived with the [published position files](https://www.finra.org/finra-data/browse-catalog/equity-short-interest/files).
The target is an end-of-day publication cutoff, not an intraday timestamp. A file
date is its **settlement date**, not publication date. As of September 4, August
14 (published August 25) is usable; August 31 (published September 10) is not.
May 29 positions were published June 9, so their use here is retrospective, not
a claim that those positions were known on May 29. Missing exact reference
disclosures are not replaced with an adjacent date.

For daily continuity, supply the previous run's **core** `brief.json`:

```bash
uv run momentum-research-agent --daily-brief --brief-source etf-proxy \
  --with-market-research --reference-date 2026-05-29 \
  --previous-brief reports/YOUR_PREVIOUS_RUN/brief.json
```

If the prior run has a valid market sidecar, its checked short-interest snapshot
is copied into this run. The report distinguishes a new settlement disclosure,
the same observation, and revisions to the same MTUM observation. No new
disclosure is **not** a new daily short-interest measurement. Without a valid
prior market report, the daily update state is explicitly unknown.

## Short-interest methodology and boundaries

- Use positions, **not short-sale volume**. The FINRA files require no API key.
- Keep raw published shares, average volume, split/revision flags and DTC. Preserve
  FINRA's minimum-one-day convention; do not substitute another volume window.
- Zero average volume makes usable DTC unavailable, even when the raw file stores
  `999.99`. Preserve that source value separately; never average it as a valid
  liquidation horizon. See the [FINRA glossary](https://www.finra.org/finra-data/browse-catalog/equity-short-interest/glossary).
- No short-float percentage without a reliable date-matched float denominator.
- MTUM ETF share changes require complete saved action-session coverage spanning
  the comparison and no split flags/events. Otherwise withhold the share change.
- Constituents and weights come from the current validated MTUM issuer snapshot.
  Reuse those weights for all requested dates, disclose look-ahead selection bias,
  and never aggregate raw short shares across different stocks or infer their
  split-adjusted share changes without an adequate corporate-action history.
- Weighted DTC = `sum(weight_i * DTC_i) / sum(all positive equity weights)`.
  It is a descriptive weighted mean, **not portfolio liquidation time**. Every
  positive-weight constituent needs a usable DTC at that date. Any missing name
  suppresses that period's mean; no dropped-name reweighting. Position counts and
  weights remain visible even when DTC itself is unavailable.
- Current ticker matching is literal, not a historical security master. Detailed
  records and missing lists for each period are in the structured report.
- Archives fetched today may include later revisions; publication-aware selection
  does not authenticate historical vintages. Personal research only, no guarantee
  of commercial redistribution rights.

This does not depend on the [fixed-basket price simulation](fixed-basket.md).
That May 29 return simulation still withholds the full basket for the unresolved
FDX/FedEx Freight spin-off. Valid short-interest observations are not blocked by
that separate cash-dividend valuation problem.

## Bounded LLM and deterministic fallback

Data and all five answers are recomputed deterministically from checked evidence.
The existing native ReAct loop makes **at most one request**, with no tools,
25-second request timeout, 512 output tokens and SDK retries disabled. It can
select one to three existing answer IDs to prioritize; it cannot add free-form
claims, prices, trades, scores or policy patches. This is intentionally a small
research assistant, not the original multi-agent engine investigation/verifier.

The existing `DEEPSEEK_API_KEY` and `SUB_AGENT_MODEL` configuration are reused.
Keep credentials in your local environment or gitignored `.env`; never pass keys
as command-line arguments or check them in. Without a key, on timeout, malformed
JSON or an unknown/duplicate ID, the deterministic brief still completes and
labels the model fallback. Use `--no-brief-llm` for an explicit zero-request run.
The model response, accepted IDs, request count and usage are stored separately
from the facts. No active policy, gap ledger, engine code or verifier is changed.

Existing plain `--daily-brief` / `--with-crowding` retain zero LLM requests and
their current artifacts. Engine remains the default source and still requires
an explicit date. This feature is opt-in through `--with-market-research`.

## Evidence and offline verification

The run contains original `brief.json`, `brief.md`, price and issuer snapshots,
plus `market_brief.json`, `market_brief.md`, `market/inputs.json` and
`market/short_interest/` (official schedule, raw files, normalized data, manifest).
SHA256 binds the input artifacts; hashes detect inconsistent evidence, not an
attacker who replaces an entire snapshot and all hashes.

```python
import json
from pathlib import Path
from momentum_research_agent.market_brief import replay

root = Path("reports/YOUR_RUN")
saved = json.loads((root / "market_brief.json").read_text())
rebuilt = replay(root)  # no network or LLM
assert all(saved[key] == value for key, value in rebuilt.items())
```

Core prices, issuer data and FINRA collection each have their own 120-second
network budget. FINRA uses a killable subprocess, at most two 20-second attempts
per source. Local normalization and disk work are additional. A source failure
does not overwrite a prior successful run. Valid core data returns `partial`
and exit 0, even if optional evidence/model is unavailable; missing required ETF
data yields `unavailable` and exit 2, with the five questions still addressed.

No scheduler, database, new framework, automatic trading or production SLA is
introduced. Start with manual runs and assess reliability over five sessions.

## September 8, 2026 acceptance

The reviewed end-to-end run completed in 6.20 seconds with target September 4,
reference May 29, all 125 current equity constituents covered (99.79% of fund
weight), FINRA version `finra_short_interest_v2_zero_volume`, and exactly one
successful model request. Offline source replay reproduced all deterministic
facts, short-interest results and answers exactly. Public files, credentials
and generated research reports are not committed. This single successful run
does not establish ongoing availability or an SLA.
