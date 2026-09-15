# Holdings concentration delivery — execution review

## Outcome

Current MTUM concentration is now calculated directly from the full official CSV
archive and delivered through the existing read_url → ResearchReport → independent
Verifier path. One live research run completed in 42.07 seconds. The researcher
and verifier each attempted the configured historical Aug 14 source once and read
the current source once. Five current evidence items were verified; overall status
is pass_with_caveats and research coverage remains partial.

**The requested real two-date comparison is not complete:** neither the standalone
probe, researcher nor verifier obtained the 2026-08-14 official CSV. No earlier
snapshot was fabricated, no current data was relabelled, and all three report
change fields remain null. A second real date is still required for historical
comparison acceptance. No crowding/reversal-risk conclusion is asserted.

## Current facts

Source: [official iShares MTUM CSV](https://www.ishares.com/us/products/251614/ishares-msci-usa-momentum-factor-etf/latest-holdings.csv).
Actual header date: **2026-09-11**.

- Top10 fund weight: **35.20%**.
- Largest listing: **AMD, 5.46%**.
- Information Technology: **51.61%**.
- Equity weight: 99.80%, across 125 equity listings.

These are sums of reported CSV row weights, not independently recalculated NAV
weights. Small differences versus issuer webpage sector aggregates can reflect
rounding/aggregation. Share classes remain separate. The independent verifier
re-read the same issuer source; this is not a second vendor confirmation.
Independent Decimal arithmetic also reproduced the archived top10, largest and
technology values; see acceptance.json and its source/hash pointer.

## Implemented behavior

- Reuse the existing issuer normalizer and concentration function on the full
  accepted archived CSV body, even if displayed text is truncated.
- read_url accepts an earlier same-session artifact/hash for comparison with the
  current read. No extra downloads, retry loops or tool authorizations.
- Require matching fund, strictly ordered observation dates, and exact agreement
  between any requested asOfDate and CSV header. Reject missing/altered/outside
  archives and ambiguous top10 listing identity.
- Calculate top10 percentage-point change, largest holdings, sector changes and
  top10 listing contributions, including entry/exit effects. Contributions sum
  to total top10 change. They do not prove purchases, sales, flows or causation.
- Missing history leaves comparison unavailable while current facts remain usable.
- On finalization failure, hash-validated archives retain deterministic holdings
  observations as partial output, still requiring independent verification.

## Verification and limits

30 collected pytest cases, all passed. Two necessary holdings cases replace the
dedicated short-interest and fixed-basket replay cases; the shared network fixture
was preserved separately for daily-brief failure isolation. Tests cover an 11-stock
ranking change (96% to 97% top10), entries/exits, exact dates, altered hashes and
partial finalization recovery. This is synthetic arithmetic validation, not proof
that live history was acquired. Independent code review found no blocking issue.

The historical URL is the preexisting configured issuer route. Its availability
was not assumed and no unsupported endpoint was invented. This run used the same
model/policy/budgets as prior research; no live loop or promotion was added.

Artifacts in this directory: current/previous probe records, manifest.json,
execution.json, research.log, acceptance.json and research/ (answer.md, structured
reports, verification.json, traces.jsonl and source archives). The earlier-source
failure is retained. Code remains unmerged on codex/useful-momentum-research.

Next acceptance prerequisite: a readable, authentic earlier official CSV with a
validated date and matching fund identity. Until then, the answer to whether
concentration increased and which stocks drove that change remains unknown.

Local run: `reports/usefulness/20260914_215154_concentration/`.
