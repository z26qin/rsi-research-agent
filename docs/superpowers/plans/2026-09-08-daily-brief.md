# Market-level daily brief implementation plan

> **For agentic workers:** Use superpowers:executing-plans for inline execution. Steps use checkbox syntax for tracking.

**Goal:** One CLI invocation produces an auditable market/book-level momentum brief without presenting stale data as current.

**Architecture:** A small readiness module inspects the existing engine's processed data, without importing or changing engine code. A daily-brief module runs the existing bounded subprocess into a private session cache, validates its delivery contract, and renders deterministic JSON/Markdown with source-field references. No model request is necessary for this first brief; normal free-form research remains unchanged.

**Tech Stack:** Existing Python, pandas/parquet, Pydantic, argparse, pytest.

**Spec:** User-approved daily brief proposal in this task: readiness, traceable market-level metrics, comparable changes, explicit limitations, bounded failures, historical validation. This implementation delivers the deterministic brief first; refreshed ingestion and supervised daily/model research validation remain subsequent work.

## Global constraints

- No new dependencies, frameworks, UI, scheduling, database, or engine/tool-code policy mutation.
- Explicit `--as-of YYYY-MM-DD`; no guessed market calendar or silent latest-date substitution.
- Inspect core daily panels for an observation on the requested date, holdings for its effective month, and record universe vintage separately. Presence of a date is coverage, not publication-time or point-in-time certification.
- Block stale/missing daily panels before running the engine. Preserve readiness and unavailable reports.
- Snapshot source dates and SHA256 fingerprints. Reject input changes during execution.
- Historical/frozen provenance, missing metrics, and universe/look-ahead limitations remain visible. Scores are not probabilities or trading instructions.
- At most one engine subprocess (90 seconds), no implicit retries, no model calls or policy activation.

### Task 1: Readiness and source provenance

**Files:** Create `src/momentum_research_agent/brief_readiness.py`, `tests/test_daily_brief.py`.

**Interfaces:** `inspect_inputs(engine_root: Path, as_of: date) -> dict` returns `ready`, input records, and limitations; records retain SHA256, date column, latest date, and latest date at/before request.

- [x] Write tests using small real parquet panels: exact-date coverage, stale/future-only/malformed/missing inputs, holdings month, future universe vintage.
- [x] Run `pytest tests/test_daily_brief.py -q`; confirm missing readiness behavior fails.
- [x] Implement explicit panel inventory and date parsing; preserve missing/invalid status instead of inventing dates.
- [x] Run readiness tests and existing suite.

### Task 2: Bounded report and comparison

**Files:** Create `src/momentum_research_agent/daily_brief.py`; extend `tests/test_daily_brief.py`.

**Interfaces:** `run_daily_brief(project_root: Path, as_of: date, output_dir: Path, previous: Path | None = None) -> DailyBrief`; `render_brief(brief) -> str`.

- [x] Write tests asserting stale data skips engine execution; valid assessments produce source-linked scores; invalid delivery, missing metrics, pipeline failure, input mutation and incompatible previous runs fail closed.
- [x] Run tests to see the new behavior fail.
- [x] Implement Pydantic artifact, fixed source-field extraction, bounded `run_pipeline`, new output directory per run, source snapshot and SHA256, comparison only for matching engine/formula/book and earlier validated source artifact.
- [x] Render explicit unavailable/partial status and unresolved limitations; never infer safety from `normal` DM state.
- [x] Run tests with coverage of the new modules above 80%.

### Task 3: CLI, historical smoke, documentation and review

**Files:** Modify `src/momentum_research_agent/cli.py`, `README.md`; extend `tests/test_daily_brief.py`.

- [x] Add CLI tests for mutually exclusive mode, required valid date, missing inputs without credentials, and persisted unavailable report; observe the missing persistence fail before implementation.
- [x] Implement `--daily-brief --as-of DATE [--previous-brief FILE]`, reuse `--session-dir`, branch before any client creation; return 2 for unavailable, 0 for partial.
- [x] Run offline bundled-engine historical smokes and a stale-date smoke; inspect JSON and Markdown. No DeepSeek calls.
- [x] Document output, limitations, exit codes, explicit comparison, and daily data dependency.
- [x] Run full tests, coverage, diff checks, request a bounded code review and resolve findings before committing.

## Verification record — 2026-09-08

- Baseline: 238 tests. Implementation verification: 275 passed; new modules 96.88% line coverage (readiness 100%, report 96%).
- Real offline subprocess smokes: 2026-05-29 (normal DM / FRAGILITY_BUILDING), 2020-03-24 (panic_elevated / FRAGILITY_BUILDING), 2024-01-05 (bear_low_volatility / NORMAL). All produced partial briefs with valid delivery contracts; this is integration evidence, not predictive validation.
- Requested 2026-09-08: unavailable; stale core panels blocked execution and no scores were published.
- First historical smoke exposed native `period[M]` holdings columns. A failing real-parquet regression test preceded the fix; original failed artifact retained.
- Review fixes: include optional processed panel hashes and presence changes; reject comparisons across holdings months even with an unchanged multimonth file; correct resolver precedence documentation.
- Synthetic subprocess CLI test verifies successful artifact production without credentials. Invalid/missing inputs and invalid engine delivery remain covered separately.
- Model calls: zero. No policy generated, promoted, or activated. No engine code, normal agent prompts, or signal thresholds changed.
- Remaining operational work: refreshed data ingestion, publication-time/PIT and constituent coverage contracts, then supervised daily use. Normal live-LLM research reliability is not claimed by this deterministic release.
