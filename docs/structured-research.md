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

For this initial reader release, source-derived web claims (including redirect destinations and download links) remain `unchecked` under the deterministic verifier guard. The LLM may report the observed facts, but a successfully downloaded page is not a verified-claim badge. No verification checks are relaxed to make a run look successful.

The runtime tool contract is in `agents/source_reading.md`, applied only to researchers authorized for `read_url`; frozen profiles and policy snapshots are unchanged. No self-improvement promotion, daily-brief budget increase, or additional framework is involved.

## Testing

Offline tests use recorded HTTP/model responses, including exhausted search, interrupted finalization, preserved source artifacts, private-address/redirect rejection, and frontend legacy compatibility. They make no paid LLM calls.

For a manually approved live test, ask: “What are MTUM's top 10 holdings? Read an official source; include weights and the actual observation date. If unavailable, explain the missing evidence.” Inspect the answer, Evidence, Verification and Trace tabs. A truthful partial result is expected when the issuer blocks access; it is not proof that the holdings question was answered.
