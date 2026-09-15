# Structured, source-backed research

Use **Runs → Auto — identify question type** (the default). Factual lookups such as MTUM holdings use Single; comparison, causal explanation and assessment questions use Team. This is a transparent keyword heuristic, not semantic classification; ambiguous questions stay Single and the user can explicitly override the route. “Direct answer” and “Deep research” are also explicit choices. A checked API-usage confirmation is required. The Research page remains a demo. Schedules are independent and need not be enabled.

CLI uses the same `--mode auto` default; `--mode single` and `--mode team` override it. Single skips decomposition, engine warming and coordinator follow-up. Its existing analyst/verifier budgets remain unchanged, with a 120-second frontend supervisor cap; Team retains the 900-second cap. Neither cap is a promised response time. Daily-brief limits are unchanged.

The LLM still chooses how to investigate the question; there is no hard-coded MTUM answer. `web_search` discovers links. The explicitly authorized `read_url` tool reads public HTTPS HTML, UTF-8 text, CSV or JSON, including download links found in page content. Pages are untrusted evidence, not instructions. No login, scripts, PDF extraction, paywall bypass, or provider fallback is added. A blocked page produces a gap, not a made-up holding list.

## Output

The existing Pydantic `ResearchReport` is extended, not replaced:

- `summary`: direct LLM answer, optionally a numbered list.
- `findings`: existing machine-readable `Evidence[]`; the independent verifier judges these, not the summary.
- `as_of`: actual data observation date or null, never inferred from fetch time.
- `sources`: observed source URLs / leads; not a verified-source badge.
- `limitations`, `unanswered_questions`: explicit coverage gaps.
- `status`: existing `complete`, `partial`, `insufficient_evidence` vocabulary.
- `metrics`: named numeric observations with finite `value`, `unit`, actual `as_of`, `source_url` and a matching `evidence_id`. Missing observations use `value: null` plus `missing_reason`, never zero. Duplicate evidence IDs are rejected and analyst IDs are namespaced by task. This is structural provenance validation, not mathematical or semantic verification of the number.

Older reports load without the new optional fields. Session Overview displays the single-agent answer even when there is no coordinator synthesis. Verification remains separate. A completed process is not a verified answer.

Both direct answers and research synthesis display numeric observations. Synthesis copies the original analyst metrics rather than inventing another metric set. Prompts ask for holdings weights, measured volatility/returns/concentration where relevant, and separately dated current/comparison observations. No new risk score, crowding probability or fabricated historical data is introduced.

The configured MTUM/QUAL/IVV issuer directory is supplied to the LLM using existing pipeline URLs. It contains addresses, not answers: the model must still read and interpret the source. Failed reads and discovery-only leads cannot become research findings; removed claims also suppress the mixed draft summary and invalidate dependent metrics. Run history separately labels process state and answer coverage. Missing numeric observations or missing/blocked task reports prevent “Answer available”; that label is coverage only, never verification.

## Bounds and evidence

- Research keeps the existing total deadline and maximum turns. Up to one third of the time (capped at the LLM-call limit) and the last turn are reserved for a no-tools JSON finalization request. No extra turn is added.
- Native search still allows at most two attempts per role. Exhausted tools are removed from later tool choices and repeated calls in a batch do not execute them again.
- Source reading allows at most three attempts per role; each worker is bounded to eight seconds (the outer remaining tool/deadline limit wins). Cancellation kills and reaps the worker.
- Public HTTPS only, port 443, no URL credentials. All DNS answers must be public; the TLS connection pins the checked IP while validating the original hostname. Redirects are checked afresh. No API keys, environment proxies, cookies or authorization headers enter the worker.
- Downloads are limited to 512 KB, at most three redirects. Extracted text is capped at 12,000 characters with an explicit truncation flag. HTML table cell boundaries and up to 30 source links are retained. The archive includes the full accepted response body as base64 and the extracted observation.
- `source_reads/{unique}.json` stores fetch time, requested/final URL, body and text. Tool results reference its SHA-256; `read_url` traces retain the bounded text for offline stored-observation replay. This is not a new live replay provider: unsupported calls in policy shadow evaluation still fail closed.
- Deadline or malformed/truncated final output after collecting observations yields a deterministic partial report with sources and gaps, no invented findings. Cancellation and authorization failures are not converted into success. Existing verifier conservatism is unchanged; reading a page does not automatically verify it.

The existing deterministic verifier guard requires a successful independent verifier source read for source-derived web claims. Researcher retrieval alone does not confer verification. Native discovery remains subject to its existing conservative guard. This M1 change does not relax or modify either guard. See the static-fallback limitation below; a saved status alone is not proof that independent re-check completed.

The runtime tool contract is in `agents/source_reading.md`, applied only to researchers authorized for `read_url`; frozen profiles and policy snapshots are unchanged. No self-improvement promotion, daily-brief budget increase, or additional framework is involved.

## Testing

The maintained 30-case suite uses local HTTP/model doubles and pinned engine fixtures. It retains authorization, deadlines/cancellation, independent source reading, discovery provenance and useful-answer regressions. See `tests/README.md` for the retained coverage and deliberate omissions. Tests make no paid LLM calls.

For a manually approved live test, ask: “What are MTUM's top 10 holdings? Read an official source; include weights and the actual observation date. If unavailable, explain the missing evidence.” Inspect the answer, Evidence, Verification and Trace tabs. A truthful partial result is expected when the issuer blocks access; it is not proof that the holdings question was answered.

## Useful holdings answers (M1)

For a narrowly recognized English holdings lookup, Single offers the researcher
only its existing `read_url` and `web_search` tools. Unknown vocabulary or mixed
requests retain the full profile. This conservative heuristic is a scope hint,
not a semantic classifier. The shared source-reading contract asks for one
holding per Evidence/metric, original fund weights, actual data dates and a
source-supported ranking. It does not contain live holdings or weights.

Single writes `answer.md` after independent verification and displays that answer
instead of the unchecked draft summary. The answer retains numeric observations,
verdict-labelled findings and caveats. Rejected values/claims are withheld;
weak/unchecked observations remain explicitly labelled. The summary is still
preserved in the canonical sub-report, but can mix unsupported calculations and
is not reused as the final answer. Metrics are not separately recalculated by
this renderer. Team and frontend rendering are unchanged.

```bash
uv run momentum-research-agent --mode single \
  --session-dir reports/my-mtum-lookup \
  "What are MTUM's top 10 holdings? Read source content and include weights, the actual observation date, and source links. State any missing evidence."
```

Use a fresh session directory for each run. This command makes live model/data
requests using existing configuration and budgets. Inspect `answer.md`,
`sub_reports/*.json`, `verification.json` and archived `source_reads/` together.

A saved `verified` verdict without `rechecked_source` is displayed as unconfirmed:
the existing static fallback may retain that status after a verifier timeout.
This presentation safeguard leaves canonical verification unchanged and is not
proof of independent verification completion. See [M1 execution review](m1-usefulness-review.md).

## Independent verifier failure semantics

Timeout, malformed output or another bounded runtime failure now merges an empty
independent result: every evidence item without a terminal verdict becomes
`unchecked`, while deterministic `rejected` verdicts remain rejected. The same
rule applies to omitted IDs in otherwise valid verifier JSON. Reading a source
before timing out cannot retain a static `verified` verdict. The resulting gaps
are persisted through the existing ledger path; cancellation still propagates.
Old saved sessions are unchanged, so the conservative presentation guard remains
for their static-only statuses. A timeout is truthfully reported, not retried with
larger budgets or converted into research success.

## Daily performance observations

`market_data(ticker="MTUM", benchmark="SPY")` now returns deterministic JSON for
daily prices: return, sample annualized volatility and within-window maximum
drawdown for each ticker. The optional benchmark uses exactly the same 20 common
completed-session closes (19 returns). An internally missing session, fewer than
20 prices, duplicate date, nonfinite/nonpositive price or unavailable symbol
produces `unavailable`, not a shorter sample or zero. Current calendar-day data
is excluded conservatively; the last returned date is not a freshness guarantee.
Non-daily single-ticker calls retain the recent-price Markdown format; benchmark
comparisons require daily data. Daily consumers must use the new JSON contract.

`market_observations/<id>.json` archives the full-precision prices used, dates,
provider/adjustment basis, formulas and results. The tool returns its relative path
and SHA-256 alongside compact metrics. `traces.jsonl` now includes `market_data`;
this is source-observation retention, not a second tool log. Paired policy shadow
evaluation still rejects market_data: its accepted replay tools are unchanged.

The shared research contract directs performance-only comparisons to one combined
price call and prompt completion. Existing research deadlines/turns are unchanged.
If finalization times out or is invalid, only the latest successful hash-matching
performance archive may supply deterministic Evidence/metrics. That answer stays
partial with interpretation and the assignment unresolved; it is not a fabricated
LLM completion. A changed, missing or out-of-session archive is refused.

A syntactically complete report with broken metric evidence references may retain
its otherwise valid findings/metrics: only mismatched references are withheld,
coverage becomes partial, the mixed summary is suppressed and the gaps are named.
No source link is invented, no metric value is repaired, and other schema errors
still reject. `finalizations/<task-id>.json` preserves terminal model text and
validation diagnostics separately from canonical sub-reports. Treat this draft
as untrusted model output, not verified research.

The verifier still independently judges evidence, with source reads required for
web/vendor claims and UNCHECKED on missing terminal verdicts. A successful
independent market_data call can support a vendor calculation, but does not
establish third-party price accuracy or current positioning/crowding.

## Official holdings concentration

`read_url` adds deterministic `holdings_summary` for a recognized configured
issuer CSV. It parses the full archived response body, validates fund identity,
observed date and weight coverage through the existing normalizer, and returns
original fund-weight top10/sector percentages plus the largest listing. Individual
holding weights remain fractions, explicitly labelled. Generic page reads retain
their original content and status even when concentration cannot be computed.

To compare, first read the earlier dated CSV. Then call read_url on the newer
CSV with `compare_to_artifact` and `compare_to_sha256` from the earlier response.
Only a hash-matching source_reads archive inside the same session is accepted.
Both files must identify the same fund with strictly increasing dates. If a URL
requests asOfDate, it must exactly match the CSV header. Date mismatches, missing
history or changed listing identity yield an unavailable comparison and null
`top10_change_pp`; the current concentration remains usable.

`holdings_comparison` contains top10 change in percentage points, largest holdings,
sector-weight changes and contributions of the union of the two top10 lists.
For each listing, contribution = its weight in the new top10 (zero outside) minus
its weight in the old top10 (zero outside). This reconciles to total top10 change;
entry into the top10 does not establish a new fund holding or a purchase.
Share classes remain separate and there is no causal trade/flow attribution.

Research source hints include existing configured exact-date history URLs when
explicit dates and historical/concentration intent occur in the question. These
are addresses to try, not availability guarantees or historical observations.
The source-reading limits, timeouts and profile authorization are unchanged.
Only current facts are reported when history cannot be retrieved.

On finalization failure, valid hash-bound holdings archives can retain calculated
metrics as a partial report. The model explanation remains incomplete. The usual
independent verifier still judges these claims; source download or deterministic
calculation is not automatic verification. This does not certify publication-time
availability or market-wide crowding.
