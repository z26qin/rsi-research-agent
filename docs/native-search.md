# DeepSeek native search

The existing authorized `web_search(query)` tool uses DeepSeek's Anthropic-format
Messages API with server-side `web_search_20250305`. Research/coordinator chat endpoints remain
unchanged; no framework, new agent, profile or authorization expansion is added.
The search model is pinned by this implementation to `deepseek-v4-flash`, using
the existing OpenAI SDK's generic POST transport (`openai>=3.8.0`), not a new SDK
or framework. Search uses the fixed official endpoint
`https://api.deepseek.com/anthropic/v1/messages` with the same key; changing the
chat base URL does not redirect search. HTTP redirects fail closed.

## Run with an existing key

From the checkout containing this change:

```bash
MOMENTUM_ENV_FILE=/Users/aaronqin/Desktop/ENV/.env \
SUB_AGENT_MODEL=deepseek-v4-flash \
uv run momentum-research-agent --daily-brief --brief-source etf-proxy \
  --with-market-research
```

`DEEPSEEK_API_KEY` takes precedence; the existing `DeepSeekAPI` alias is accepted
when the standard variable is absent/empty. Shared env files are loaded only via
an explicit path, never discovered across home/Desktop. Exported variables and
project `.env` values are not overwritten. No key is copied into reports or code.
Daily prices/FINRA data still work with `--no-brief-llm` and no API key.

`WEB_SEARCH_PROVIDER=auto` chooses native search when a DeepSeek key is configured,
otherwise the old Serper→Tavily path. `deepseek` selects native only; `legacy`
explicitly keeps the old providers. Native failures never silently switch to a
second paid service. Missing credentials produce unavailable evidence. Research
calls require an active tool context and a writable session directory.

## Limits and costs

Each analyst/verifier gets at most two native request attempts. Each sends one
query of at most 512 characters, no conversation history, no SDK retries, and
requested `max_tokens=1024`, `max_uses=1`, and thinking disabled. Native calls have a 20-second
inner timeout; the existing outer tool deadline (8 seconds for brief supplements,
10 seconds by default for research) and remaining role budget may cancel sooner.

Native requests **consume the same five-request brief supplement budget** as
analyst/verifier requests. They do not count as free tool work. If that budget
prevents a complete verification, leave the result unresolved. Recorded usage is
added to each role's local UsageSummary and the shared supplement usage, without
double-counting at either level. Failed attempts still consume request slots.

These are request parameters/client wait limits, **not a guaranteed dollar cap**.
The live Messages diagnostic returned one successful search and a second attempt
blocked by `max_uses_exceeded`, while usage reported two search requests. Do not
derive billable searches from successful result counts. Cancelling the client
does not prove server work/billing stopped. Raw returned usage is retained;
without it, billing is explicitly unknown. Messages input token totals include
uncached input, cache reads and cache writes. Existing
USD estimates are token-only estimates, not a search-inclusive invoice.

## Evidence and failures

Each attempted network search creates a unique `search_results/*.json` artifact:
query, fetch time, requested model, limits, elapsed time, status, returned usage,
and SDK-parsed response (not raw HTTP bytes). Errors expose only sanitized type
and HTTP status, not provider error bodies. Failed/cancelled searches preserve
diagnostics without overwriting earlier evidence.

A successful observation requires `stop_reason=end_turn` and at least one usable
structured `web_search_result` in `web_search_tool_result` blocks. Paused or
truncated responses fail closed and are not automatically continued. Errors are
parsed separately: a later `max_uses_exceeded` does not discard earlier valid
results. Empty/error-only responses remain unavailable.

The tool returns up to three deduplicated HTTP(S) sources, plus artifact path/hash,
bounded usage counters and action error codes. It does not require or return a model-authored
answer, scrape URLs from prose, or invent excerpts. `evidence_kind=source_discovery`
marks titles/URLs as source leads, not substantive claim evidence. `snippet` stays
null; `page_age` is provider metadata, not a verified publication/observation date.
An analyst must leave claims unresolved when supporting content is unavailable.
Before persisting verification or closing gaps, Verifier deterministically
downgrades proposed VERIFIED verdicts tied to native-discovered URLs (ignoring
URL fragments), or an ambiguous `web_search` re-check, to UNCHECKED. An unrelated
native failure does not downgrade other verified sources. This first version
conservatively leaves a discovered URL unchecked even if a later local file
might contain relevant content; verified URL-to-content binding is not implemented.
Provider metadata and action error lists are bounded in compact observations;
the full response, raw usage and error list remain in the hashed artifact.
Full returned material stays in the artifact. Existing `traces.jsonl` stores the observation for offline
replay; it does not need a new tool schema or second log. Outer deadline/cancellation
also preserves an interrupted observation in that same trace stream.

Search results are not proof of causal claims or momentum crowding. Existing
analyst evidence rules and independent conservative verification remain in force.
No live search is called in unit tests, the offline policy evaluation suite, or
stored-observation replay. Independent policy reflection can still use its own
separately configured LLM, as before.

## September 9, 2026 acceptance status

Offline SDK-transport tests cover source-only results, a recorded real response
with mixed success/limit errors, missing results, incomplete responses, 429/no
retries, redirect rejection, per-role/shared budgets, cancellation, and real
analyst/verifier trace persistence and separate usage. Oversized metadata stays
replayable, and source-only findings stay unchecked with their gaps open.
No test makes a live call.

Responses probes timed out at 20 seconds; independent 60-second probes returned
in 38.8 seconds (forced search) and 33.6 seconds (auto), but without final cited
answers. Top-level `completed` alone was not evidence of usable research output.

An independent Messages diagnostic completed in **4.719 seconds**, `end_turn`,
with 10 structured sources and no citation excerpts. One search succeeded; a
second attempted search was blocked by its limit. Its raw usage was 7,811 input,
384 cache-read and 593 output tokens, plus two reported server search requests.
The response, with opaque encrypted payloads removed, is the committed offline
fixture `tests/fixtures/deepseek_search_messages.json`.

This establishes one successful live retrieval, not sustained availability or
verified research conclusions. The production prompt now requests one search
and no research answer; that exact revised prompt has not had another paid live
test. Diagnostics remain locally under `reports/native-search-*`. All production
timeouts, request budgets and provider-selection rules remain unchanged.

Protocol references: [DeepSeek compatibility guide](https://api-docs.deepseek.com/guides/anthropic_api/)
and [official Harness search implementation](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/web/web-search-deepseek/src/provider.ts).
