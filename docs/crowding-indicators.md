# ETF crowding indicators: partial evidence

## Run

```bash
uv run momentum-research-agent --daily-brief --brief-source etf-proxy --with-crowding
```

To estimate the next session's net creations/redemptions, supply the preceding
session's brief (which must also have used `--with-crowding`):

```bash
uv run momentum-research-agent --daily-brief --brief-source etf-proxy \
  --with-crowding --previous-brief reports/<prior-run>/brief.json
```

The existing ETF return report, SPY return benchmark and engine mode are unchanged.
The optional `crowding` field has its own version `etf_crowding_indicators_v1`.
The ordinary ETF command makes no issuer requests unless `--with-crowding` is set.
This extension is deterministic: no LLM, API key, policy update, new risk score,
database or scheduling system. An original research agent may read the resulting
`brief.json` and the normalized issuer files with its existing `file_reader` tool;
there is no automatic LLM launch or change to the verifier's evidence standards.

## Basket and interpretation

- MTUM: momentum-style long-only ETF.
- QUAL: quality-style long-only comparison.
- IVV: broad-market holdings comparison; not a replacement for SPY return data.

All three use the same issuer format. They do **not** represent independent
investor decisions, all momentum funds, aggregate short positions, borrowed-share
availability, or market-wide ownership. No stock-level free-float ownership ratio
or liquidation-time estimate is inferred. Short interest is outside this version.

### Concentration

Use the issuer's reported equity weights divided by 100. Top-10 weight is the sum
of the ten largest equity-listing weights. Equity HHI is the sum of squared
equity weights (fractional units, not the 0–10,000 scale). Sector weights sum
equity rows in each issuer sector. Cash, derivatives and money-market funds are
excluded, with no look-through and no rescaling of equity weights to 100%.
Show equity coverage and the overall reported weight total. Rounded holdings
weights can differ slightly from the issuer's aggregated sector page.

Malformed, duplicate or negative equity rows fail validation. A total reported
weight outside 98–102% fails validation. The tolerance accommodates rounded
holdings weights; it does not certify that every security was supplied. A small
omission can pass this check. Dates must be XNYS sessions at/before the target.

### Cross-fund overlap

For MTUM/QUAL and MTUM/IVV, sum `min(weight_A, weight_B)` over shared listings.
Also retain shared-listing count and each fund's weight in those shared listings.
Only same-observation-date holdings are compared. Dates may be older than the
brief target, but are explicitly labeled stale; no date is filled forward.

These downloads do not provide stable security identifiers. Matching therefore
requires an exact ticker + exchange + currency tuple and matching security name.
Ambiguous name collisions withhold the pair. No fuzzy ticker aliases are merged.
Different share classes remain separate listings, so this is **listing overlap**,
not issuer-level or investor-level ownership. A high overlap is not proof of
crowding; concentration by itself is not proof either.

### MTUM flow estimate

Only adjacent trading-session observations with compatible saved issuer evidence
are eligible. Use the current core MTUM price snapshot's explicit split field:

```text
adjusted_prior_shares = prior_shares × split_ratio_on_current_session
estimated_net_creation_USD = (current_shares − adjusted_prior_shares) × current_issuer_NAV
share_change_pct = current_shares / adjusted_prior_shares − 1
```

Zero in yfinance's split field means no split (ratio 1). Missing, duplicate,
negative or nonfinite split observations withhold the estimate. NAV must be the
issuer's USD NAV for exactly the current holdings date; the current holdings date
must equal the brief target. Holdings market values are never used to infer NAV.

This is a one-session **estimated net creation/redemption**, not cash flows from
investors. In-kind transactions, arbitrage, rounding and issuer revisions can
affect interpretation. AUM growth alone is never called inflow. Without a valid
prior snapshot, show `unavailable`, not zero. No retrospective daily flow history,
multi-day flow aggregate, percentile or trend is invented from one observation.

## Collection and provenance

Download each fund's `latest-holdings.csv` plus product-page structured NAV/net
assets. These endpoints return their latest observation, not guaranteed historical
as-of data. A future snapshot is rejected, not relabeled for a historical target.
Dates and retrieval times remain separate; backtests are not publication-time/PIT
certified. The first run establishes a baseline; keep subsequent run directories.

The optional stage has its own 120-second download budget, in addition to the
core stage's 120 seconds. Each fund gets at most two subprocess attempts, each
with a 20-second deadline; each HTTP request also has a 20-second timeout.
Local validation/serialization adds time. Successful holdings are checkpointed
before fetching the optional NAV page, so a hanging page does not discard them.
Diagnostics use exception types, never arbitrary provider stderr or credentials.

```text
brief.json                          # includes optional crowding section
brief.md                            # price observations + deterministic issuer section
crowding/manifest.json               # version, targets, attempts, provenance, hashes
crowding/vendor/<fund>-<attempt>.json # downloaded CSV/HTML text envelope
crowding/normalized/<fund>.json      # reproducible normalized issuer observations
crowding/vendor/MTUM-prior.json      # copied prior input when supplied and valid
crowding/normalized/MTUM-prior.json   # prior normalized input for standalone replay
```

The envelope contains decoded issuer response bodies, not a full HTTP transaction
archive. Prior report/issuer versions and manifest hashes are checked, then raw
and normalized hashes and reproducibility are verified. Imported prior evidence
is copied into the new run and keeps its origin manifest hash/retrieval time.
Replay does not depend on the original prior directory still being present.

Issuer failures do not erase valid price metrics. Valid issuer evidence can also
remain available when core prices fail; in that case flows are withheld and the
overall brief still exits 2 (`unavailable`). No old successful output is replaced.

## Offline replay

```bash
uv run python -c 'import json,sys; from pathlib import Path; from momentum_research_agent.proxy_brief import replay_crowding; print(json.dumps(replay_crowding(Path(sys.argv[1])), indent=2))' reports/<run>
```

The helper checks report-to-manifest bindings, verifies and re-normalizes the
issuer evidence, and recomputes metrics. When the original core was available,
its tables are checked too before using split data. Integrity failures withhold
affected indicators or reject mismatched manifests; there is no network fallback.

## Initial acceptance

On 2026-09-08, all three issuer sources returned 2026-09-04 holdings and NAV.
The live report's issuer section matched offline recomputation exactly. MTUM
top-10 equity weight was 35.08%; weighted overlap was 22.30% with QUAL and 27.24%
with IVV. Flow was unavailable because no prior issuer snapshot existed. Tests
exercise positive/negative flows and splits; a real two-session flow comparison
still requires the next eligible saved snapshot. One successful run is not an SLA.

Issuer sources: [MTUM](https://www.ishares.com/us/products/251614/ishares-msci-usa-momentum-factor-etf),
[QUAL](https://www.ishares.com/us/products/256101/ishares-msci-usa-quality-factor-etf),
[IVV](https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf).
Personal research only; public access is not a commercial redistribution license.
