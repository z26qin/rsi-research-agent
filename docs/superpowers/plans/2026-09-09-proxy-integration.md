# ETF Brief integration plan

> Execute inline with executing-plans and TDD. Preserve the current isolated frontend worktree.

Goal: generate the September 8 ETF proxy Brief, display it on Home, and switch the approved Toronto 08:00 schedule after validation.

Approved design: reuse committed ETF proxy code only, separate current ETF observations from lagged French context, never emit original-engine scores or enable LLM calls. Do not merge branches or modify another worktree. Local-only.

## Tasks

- [x] Import the four core proxy modules and matching CLI integration/tests from commit 773468b via git object reads. Add exchange-calendars dependency. Run baseline and imported tests offline.
- [x] Add a fixed proxy worker and control-service source configuration. Tests assert proxy mode bypasses old engine coverage, preserves exact date and fixed arguments, rejects invalid snapshots, and retains per-source date deduplication. Existing engine mode remains default until explicit restart in proxy mode.
- [x] Accept etf_proxy_brief_v1 in the frontend adapter, normalized to typed metrics with percentage units. Test unavailable metrics are withheld and engine fields are not invented. Add a separate dated factor-context sidecar read by importer; never mutate the original proxy artifact.
- [x] Extend existing Home/Brief/Runs surfaces with proxy labels, units, actual source dates, and explicit original-model unavailability. Preserve the site's existing visual style and Demo behavior.
- [x] Run Python/TypeScript/component suites, build and privacy tests, then perform one authorized real proxy run in a new main-checkout reports directory. Recompute saved metrics offline and compare exactly.
- [x] Restart local service with the selected proxy source, preserving schedule state; verify next check and artifact synchronization. Record any provider failure without stale substitution. No deployment, merge, or unrelated changes.

Acceptance: imported ETF code required its matching CLI hunks; those were carried
without unrelated later commits. Review found a snapshot-date binding gap in the
new control wrapper; regression failed before the fix and passed afterward.
Real report `brief_20260909_163944_4263ccb0` has 2026-09-08 MTUM/SPY/VIX coverage,
16 replay-equal metrics, zero LLM requests. Main frozen inputs untouched. Factor
context truthfully reports the active cache date (2026-06-30), not the July 31
official archives downloaded separately in staging. Frontend snapshot imported
the proxy and sidecar with no diagnostics. Enabled scheduler source etf-proxy,
next check 2026-09-10T08:00:00-04:00. No browser QA, deployment, merge or commit.

Acceptance commands: `.venv/bin/python3 -m pytest tests/test_proxy*.py frontend/scripts -q`; `npm --prefix frontend run typecheck`; `npm --prefix frontend run test -- --run`; `npm --prefix frontend run build`.
