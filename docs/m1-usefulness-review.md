# M1 useful holdings research — execution review

## Outcome

Content delivery passed for MTUM and the QUAL transfer question: all ten tickers,
weights, order and Sep 11, 2026 observation date match the archived issuer CSVs.
MTUM independent verification remains incomplete: the model timed out, and the
preexisting verifier fallback retained static VERIFIED statuses with no rechecked
source. The final presentation explicitly marks them unconfirmed. QUAL completed
its independent re-check. M1 is partially accepted, not fully verified.

## Controlled runs

Baseline commit: 12c8f30325a233bb4ce8be76c5eb89e36156ee9e.
All runs used deepseek-flash and policy dbc0fb5e969a, unchanged role budgets and
configured source directory. Commands/times are in *-execution.json; source
observations, reports, verification and traces remain in each session.
Three full live sessions and one standalone public-reader probe were used. No
retry-to-success or fourth session. Source snapshots were checked after runs;
expected holdings were never supplied to the model. These are live observations,
not a randomized policy comparison or proof of autonomous self-improvement.

| Measure | Baseline MTUM | Revised MTUM | Transfer QUAL |
| --- | --- | --- | --- |
| Requested holdings matching archived CSV | 10/10 | 10/10 | 10/10 |
| Observation date | 2026-09-11 | 2026-09-11 | 2026-09-11 |
| Researcher source reads | 2 (one failed HTML) | 1 | 1 |
| Researcher unrelated calls | engine + price lookup | 0 | 0 |
| Metrics | 11, including unsolicited price | 10 | 10 |
| Holdings evidence grouping | one mixed claim | ten separate claims | ten separate claims |
| Saved verification | 3 weak / 2 verified | 10 static verified, re-check timed out | 11 verified with rechecked sources |
| Independent holdings confirmation | mixed claim weak | incomplete | completed |
| Elapsed seconds | 63.55 | 57.58 | 39.68 |
| Local model calls | 5 | 6 | 6 |
| Input tokens | 38,634 | 56,446 | 78,641 |
| Output tokens | 10,805 | 9,549 | 11,467 |

Local call counts include verifier work; provider-native search can add internal
activity. Saved SDK responses retain native usage. Traces cover the supported
read_url/web_search/engine_query subset, not every tool. Revised total token usage
increased, despite fewer researcher calls. No claim of cost improvement is made.

## Actual failure and repair

The current official CSV already worked. Its full accepted body contained 129
MTUM rows and 122 QUAL rows; bounded model text was truncated after the leading
holdings. Offline full-body sorting confirmed the ten-row selection. No network
reader or source URL fix was warranted.

Baseline's requested ten weights were correct, but its displayed draft claimed a
38.20% top-ten total (actual 35.20%) and 26.86% IT subtotal (actual 26.50%). It also
made unrelated engine/price calls. The revised source contract requests row-level
evidence, original fund denominator and dates, then stops at the requested answer.
Conservative lookup recognition restricts only recognized factual questions to
existing source tools; unknown/mixed questions keep the full profile.

The CLI now writes/displays answer.md after verification, retaining metrics,
verdict-aware findings and gaps instead of the unchecked draft summary. Rejected
values/claims are withheld. A saved VERIFIED verdict lacking a rechecked source
is labelled unconfirmed; this does not mutate the verifier or canonical report.
The latter guard was added after the MTUM timeout. Both answer.md files were
re-rendered offline from their unchanged JSON; answer-live.md preserves the
original live rendering. No extra model run was used.

## Limits and next work

- MTUM independent verification is unfinished; fixing timeout/fallback semantics
  needs a separate focused change and bounded validation before full M1 sign-off.
- Verifier still made extra calls (including engine/market data in QUAL). This
  work intentionally did not modify verifier permissions, prompts or merging.
- Answers preserve useful facts but caveats can still be verbose or contain
  unreviewed analyst interpretations. Only claim-level verdicts are labelled.
- One successful QUAL transfer is limited evidence of generality.
- This changes Single CLI presentation, not Team or the frontend.
- Runtime reports are local ignored artifacts. Code/docs are on
  codex/useful-momentum-research in the isolated worktree, not merged.

## Verification

Maintained suite: 30 collected tests, all passed. Two M1 tests replace the arena
enum-repair and withholding-credit cases. They cover source-only delivery,
mixed-intent fallback, saved evidence, rejected/unchecked display, static-only
verification labels and canonical-report preservation. Independent code review
found no blocking issue after corrections. Reader, policy and verifier unchanged.

Local artifacts: reports/usefulness/20260914_202848_5067a255/ (review.md, source-checks.json, candidate/answer.md, qual/answer.md).
