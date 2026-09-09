# Historical issuer backfill and comparison

## Historical download

```bash
uv run momentum-research-agent --backfill-crowding --as-of 2026-05-29 \
  --compare-brief reports/etf-crowding-reviewed-20260908/brief.json \
  --session-dir reports/may29-backfill
```

This is a separate, deterministic data-preparation command, not a live research
agent or an engine run. It does not download ETF prices or call an LLM. Its output
is `backfill.json`, `backfill.md`, and a `crowding/` snapshot. The target must be an
explicit completed XNYS trading date; the output directory must not already exist.

It requests each of MTUM, QUAL and IVV from the issuer's historical CSV route with
`asOfDate=YYYYMMDD`. It checks the downloaded file's own date, fund identity,
weights and listing validity. **Only an exact date match is accepted**: even an
older date is not silently substituted. There is no fallback to latest holdings,
another provider, a month-end date, or an original-engine portfolio.

Each fund gets at most two attempts, with a killable 20-second subprocess timeout
and a shared 120-second collection budget. Downloaded response text is retained,
including invalid HTML/incorrect-date responses, with hashes and attempt
diagnostics. Local parsing and serialization add time. Historical NAV is not
inferred from market values or today's product page.

The historical endpoint is **best effort, not a guaranteed working API**. The
initial May 29 tests returned HTML rather than usable issuer holdings. A command
that successfully finishes with `unavailable` has not recovered the requested
historical data. Failed runs are retained; imports use a new output directory.

## Import genuine issuer exports without a network request

If you obtain the original dated issuer CSV files, place them together with an
import manifest. Do not edit their dates or fabricate metadata to make them pass.
The supported layout is the issuer CSV with a fund-name row, `Fund Holdings as of`,
`Shares Outstanding`, and the standard ticker/name/sector/asset-class/market-value/
weight/exchange/currency columns. Other layouts, including XLS/XML, are rejected.

An import manifest has this shape (replace example paths, dates and hash):

```json
{
  "schema_version": "issuer_file_import_v1",
  "as_of": "2026-05-29",
  "funds": {
    "MTUM": {
      "holdings_file": "MTUM.csv",
      "sha256": "<SHA256 of the original CSV>",
      "source_url": "https://www.ishares.com/us/products/251614/ishares-msci-usa-momentum-factor-etf",
      "retrieved_at": "2026-09-08T12:00:00+00:00"
    }
  }
}
```

Add equivalent QUAL and IVV entries with their own issuer product URLs and file
hashes. Missing funds remain unavailable. Paths must be relative to the manifest
directory and cannot escape it, including through symlinks. Use `shasum -a 256
MTUM.csv` to obtain a hash. The retrieval timestamp is when the export was actually
obtained, not the holdings observation date; include a timezone.

Optional `product_file` and `product_sha256` fields can preserve a corresponding
issuer HTML export containing dated USD NAV/net-assets structured data. Missing
NAV does not prevent concentration or overlap calculations.

```bash
uv run momentum-research-agent --backfill-crowding --as-of 2026-05-29 \
  --issuer-files /absolute/path/to/import.json \
  --compare-brief reports/etf-crowding-reviewed-20260908/brief.json \
  --session-dir reports/may29-import
```

Imports never fall back to network downloads. Their provenance is explicitly
**user-supplied**. Hashes prove that the copied file matches the supplied file,
not that the content truly came from the issuer. Observation dates do not certify
when data was published or whether it was knowable at the historical date.

## Comparison semantics

`--compare-brief` must point to a newer ETF `brief.json` with a crowding section,
or a newer `backfill.json`. Issuer calculation versions must match. The reference
manifest's date must match its report, and accepted reference holdings must match
that exact date. Original-engine reports and stale or incompatible references
are rejected. Price-snapshot comparisons retain their separate, unchanged rules.

The command recomputes both sets of concentration and overlap metrics from
hash-checked raw/normalized issuer evidence; it does not trust editable report
summary numbers. Comparison includes:

- Each fund's top-10 equity weight, equity HHI, equity weight coverage and listing
  count, with previous/current/delta values.
- Sector equity-weight changes, using zero only when the sector is absent from
  an otherwise validated holdings snapshot.
- MTUM/QUAL and MTUM/IVV weighted overlap, shared-listing counts and shared weights.

Percentage-weight differences are displayed in percentage points; HHI remains a
fractional sum of squares. A comparison can be partial when a fund is missing.
Concentration may change due to price moves, reconstitution, or classification
changes. It is not proof of flows or crowded investor positioning. There is no
multi-month flow calculation, crowding score, causal attribution or engine-score
comparison. See [indicator definitions](crowding-indicators.md).

## Offline evidence and replay

The reference's validated issuer files are copied into
`reference/crowding/`, with the original manifest hash retained as lineage. Replay
does not require the input import files or the original newer report directory
to remain available. It rechecks copied file hashes and normalization.

```bash
uv run python -c 'import json,sys; from pathlib import Path; from momentum_research_agent.crowding_history import replay; print(json.dumps(replay(Path(sys.argv[1])), indent=2))' reports/may29-import
```

`backfill.json` binds both issuer manifests by hash. Altered manifests reject;
invalid fund evidence withholds affected indicators. All output is local. No
policies, model settings, existing snapshots or source files are modified.

Exit 0 means the historical MTUM issuer snapshot is available with research
limitations (`partial`). Exit 2 means historical MTUM data is unavailable or the
invocation is invalid. Check `comparison.status` separately: available historical
data does not imply that a newer comparison reference was valid.
