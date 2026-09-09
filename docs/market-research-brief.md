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
The brief-focus stage uses the existing native ReAct loop for **at most one request**, with no tools,
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
from the facts. This focus stage does not change active policy, the gap ledger,
engine code or verification.

Existing plain `--daily-brief` / `--with-crowding` retain zero LLM requests and
their current artifacts. Engine remains the default source and still requires
an explicit date. This feature is opt-in through `--with-market-research`.

## Fast brief, optional research, independent improvement

The CLI saves and prints the daily brief path **before** optional supplemental
research. The supplement never edits the published brief or changes its exit
status. This is not a detached background service: the CLI still waits for the
bounded supplement, while the saved brief is already readable.

Version `brief_research_v1` selects at most one operational alert, in priority order:

1. Absolute MTUM adjusted daily return at least 3%.
2. MTUM 21-day annualized volatility rises at least 5 percentage points **and**
   50% relative to the previous session, recomputed from the current price vintage.
3. Previously available MTUM short-interest positions or current issuer holdings
   become missing/stale. This requires a valid earlier market sidecar via
   `--previous-brief`; without it, a newly lost source cannot be established.

These are simple investigation heuristics, not calibrated crowding/risk signals.
Permanent limitations such as missing borrow fees/float do not trigger repeated
research. Missing core prices do not launch an LLM to repair missing data.

An alert reuses one existing technicals/flow analyst and the independent verifier.
Only `web_search` and `file_reader` are exposed; prices come from the checked
brief, not a second vendor download or historical-engine run. Web search now
uses DeepSeek native search when the existing DeepSeek key is configured; no
Tavily/Serper key is needed on that path. See [native search](native-search.md)
for key loading, archived evidence and billing limitations. Without adequate
evidence, the supplement must remain unresolved.

The analyst has three turns/35 seconds; verification has two turns/25 seconds.
Together they get at most **five additional LLM requests**, 2048 output tokens
per request, no SDK retries, 15-second request and 8-second tool timeouts, within
a 60-second research deadline. Native search requests count toward the same
five-request limit, not as free tool calls. Local replay/disk work and client cleanup are
additional. Including brief focus, a run uses at most six requests. Quiet days
use no supplemental requests. `--no-brief-research` skips the supplement;
`--no-brief-llm` disables both model stages.

An analyst search plus final answer and a verifier search plus final verdict can
need six requests, which exceeds this deliberately retained five-request budget.
The run must then remain incomplete; the integration does not silently increase
the budget to obtain a passing verdict.

An atomic `reports/brief_research/YYYY-MM-DD` directory permits only one attempt
per target date/project, including failed or interrupted attempts. There is no
automatic retry or stale-claim reclamation. Use an explicit research session for
a deliberate follow-up. `research_status.json` and `research_addendum.md` sit
beside the brief; the research session stores checked context, task board, pinned
policy, analyst report, tool traces and verification. A missing terminal model
response or failed re-check cannot publish static-only claims as verified.

Research pins the existing active policy; the verifier never loads its overlay.
Failures feed the existing gap ledger. Nothing automatically runs `--improve`,
changes active policy or modifies Python/tool code. Curate representative failed
sessions separately, for example:

```bash
uv run momentum-research-agent --import-session reports/brief_research/YYYY-MM-DD
```

Imported cases remain pending, not trusted expected answers. Unsupported/missing
traces may be non-replayable. Import does not silently add cases to the frozen
`--improve` evaluation suite. Independent improvement still requires the existing
target-fix/no-regression gate before promotion, affecting future research only,
not today's brief or its deterministic trigger thresholds.

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

Before the alert bridge was added, the reviewed end-to-end run completed in
6.20 seconds with target September 4,
reference May 29, all 125 current equity constituents covered (99.79% of fund
weight), FINRA version `finra_short_interest_v2_zero_volume`, and exactly one
successful model request. Offline source replay reproduced all deterministic
facts, short-interest results and answers exactly. Public files, credentials
and generated research reports are not committed. This single successful run
does not establish ongoing availability or an SLA.

The alert bridge was separately checked offline against a copy of that real
snapshot: MTUM daily return was +1.8168%, no eligible alert was selected, and
there were zero supplemental model requests. All four original brief files
retained their hashes and deterministic replay matched exactly. Triggered
research, failed verification, exhaustion and trace retention are exercised with
recorded/simulated responses; no live supplemental investigation is claimed by
this acceptance check.
