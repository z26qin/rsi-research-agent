# Agent operating manual

This repository is a thin, purpose-built multi-agent research system for US equity momentum tail-risk. Read this file before changing orchestration, prompts, or tools.

## Architecture

```
Question
   ↓
Coordinator
   ↓
TaskBoard
   ↓
GAP seed (at most 2 kind=gap from reports/gap_ledger.jsonl)
   ↓
engine warm (subprocess run_mvp, ~90s cache)
   ↓
parallel SubAgents
   ↓
   optional one kind=replan (BLOCKED / mock / V_D fail)
   ↓
bounded ReAct runtime
   ↓
explicit authorized tools
   ↓
Evidence[]
   ↓
ResearchReport JSON
   ↓
independent Verifier  (static audit + bounded ReAct re-check)
   ↓
append verification.gaps → reports/gap_ledger.jsonl
   ↓
optional one-round follow-up  (rejected / unchecked only)
   ↓
VerificationReport JSON
   ↓
Coordinator synthesis
```

`summary` is for humans. `findings: list[Evidence]` is the machine-readable source of truth. The verifier does not produce new research claims; it only judges existing `evidence_id`s. Conservative merge: static REJECTED/UNCHECKED cannot be overwritten to VERIFIED by a more optimistic LLM.

`verification.json` is the per-session momentum gap ledger: `gaps[]` (rejected/unchecked/missing/unanswered/engine_mock) plus `traces[]` of replayable `engine_query` / `web_search` calls. Live search is stored-observation replay; engine snapshots replay from `source_path` when present.

After verify, those `gaps[]` are appended to the cross-session file `reports/gap_ledger.jsonl` (deduped by evidence and source-session occurrence, status `OPEN` / `CONSUMED` / `CLOSED`). The next session classifies each row as `crowding` / `unwind_crash` / `engine_freshness` / `source_quality`. After decompose and before dispatch, `seed_from_ledger()` plants at most 2 `kind=gap` tasks (`crowding` → `flow_analyst`, unwind/engine → `momentum_analyst`) and marks those rows `CONSUMED`. After this session verifies those planted tasks, the same rows become `CLOSED` (VERIFIED / no longer `ENGINE_MOCK`) or go back to `OPEN` (still rejected / unchecked / mock). This is not a second follow-up and not AgentBus.
Gap persistence is occurrence-aware: retries within one session dedupe by `(evidence_id, source_session_id)`, while the same evidence failing in a later session creates a new OPEN occurrence. `--import-session` separately converts each persisted session failure into a pending `SessionEvalCase`; ledger closure never deletes that regression occurrence.

Follow-up is one bounded extra dispatch (default max 2 tasks) using the original analyst profiles. It does not reopen verified items, does not loop, and is skipped on a session that already has `kind=followup` tasks or a completed synthesis. After the first dispatch wave, at most one `kind=replan` may run (BLOCKED, or this session's `engine_query` was labeled mock or V_D fail). File snapshot / local_dm / `pass_with_caveats` do not replan. Replan is not follow-up and not AgentBus. `engine_query` without `end` resolves the latest known as-of and still runs the live pipeline. Overlay (`profile_hints.md`) is appended only to research profiles; `Verifier` loads with `apply_overlay=False`.

`engine_query` prefers a **live** `run_mvp` via subprocess:

```bash
python scripts/run_monitor.py --as-of-date YYYY-MM-DD --output-json …
```

Path: `require_cached_inputs()` → `run_compact_assessment()` → `run_mvp()` reading `data/processed/*.parquet`. This repo must not `from src.mvp import` or `import momentum_crash`. One `resolve_engine_root`: `MOMENTUM_ENGINE_DIR` / a sibling checkout wins when present; otherwise the vendored PIT pack at `fixtures/engine` (commit `99b0688`). If `MOMENTUM_ENGINE_DIR` is set to a missing path, do not fall back to the bundle. File snapshots use that same root and cannot `delivery_contract.verdict=pass`. Only a live `run_mvp` artifact that `verify_live_delivery` re-checks (`as_of`, `risk_state` ∈ {normal, bear_low_volatility, panic_elevated}, fingerprint) can pass. Subprocess exit alone is not enough. Crowding/unwind claims stay on the verifier. Query timeout ~8s; Coordinator warm ~90s. `--eval` calls `engine_query(end="2026-05-29")` with no DeepSeek and writes failures as `eval:{case_id}` into the gap ledger plus `reports/prompt_evolution.json` / `profile_hints.md`. Committed `profiles/*.md` stay frozen; overlays are runtime-only and are not applied to `Verifier`. Replan and overlay read `traces.jsonl`; there is no second tool log.

## Artifacts

```
reports/gap_ledger.jsonl                  # cross-session OPEN/CONSUMED/CLOSED gaps
reports/prompt_evolution.json             # runtime overlay rules (not weight training)
reports/profile_hints.md                  # appended to research profiles only; verifier skips it
reports/{YYYYMMDD}_{HHmmss}_{8-char-hex}/
  policy_snapshot.json               # active policy pinned once for this session
  task_board.json
  sub_reports/{task_id}_{profile}.json    # source of truth
  sub_reports/{task_id}_{profile}.md      # human rendering
  traces.jsonl                       # source of truth: engine_query / web_search replay
  engine_runs/                       # optional session cache; pipeline cache lives on the engine root
  verification.json                  # per-session momentum gap ledger (gaps + replayable traces + verdicts)
  verification.md
  synthesis.md
  synthesis.json

reports/policies/
  active.json                        # atomic pointer to one immutable version
  versions/{version_id}.json         # content-addressed policy versions
  experiments/{experiment_id}.json   # one-cycle evaluation records

reports/eval_cases/                   # pending imported failure occurrences; no expected answers
reports/live_evals/{unique_id}/
  comparison.json                     # self-contained paired behavioral shadow result
```

Resume loads JSON first. Legacy Markdown-only sessions become a low-confidence `partial` report; structure is not pretended to survive.

## Runtime guarantees

Each sub-agent run is bounded by `LoopBudget`:

- `max_turns` (default 8)
- `overall_deadline_s` (default 45) via `time.monotonic()`
- `llm_timeout_s` (default 20)
- `tool_timeout_s` (default 10)

Every LLM/tool call uses `min(configured_timeout, remaining_overall_deadline)`. `asyncio.CancelledError` is never converted into a tool observation.

`--improve` is separate from `--eval`. It runs the pinned bundled engine through an explicit fixture root, a private output cache, and a no-network subprocess guard, then evaluates recorded trajectory contracts and may generate at most one candidate. These checks measure offline contract coverage, not LLM reasoning quality. Missing or invalid engine fixtures reject before candidate generation. Live LLM/data evaluation and staged replanning are outside this phase.

`--live-compare` is a separate, explicit shadow operation. It reruns the real ReAct loop against only validated stored `engine_query` / `web_search` observations, compares a supplied baseline and candidate under identical controls, and writes only `reports/live_evals/`. Curated expectations live outside cases and bind to the exact case content hash. Unknown calls, missing observations, incomplete runs, model-resolution drift, and malformed or truncated reports fail closed. This is bounded behavioral assertion coverage, not generic semantic truth scoring, and it never promotes or writes the active pointer/gap ledger.

Research policy is loaded and snapshotted once when a run starts. Resume uses the same `policy_snapshot.json`; never promote a policy into an active research run. Policy may guide only research prompt overlays, gap-task additions, and selection among tools already present in that profile's allowlist. It cannot expand authorization, alter deterministic engine logic, or influence verification. Committed profiles stay frozen and `Verifier` never loads policy.

Rollback must use `PolicyStore.activate(prior_version_id)` so the target version and content hash are validated before the atomic pointer changes. Improvement cycles are serialized by `reports/policies/improvement.lock`; after an interruption, confirm no improvement process remains before manually deleting only that stale lock.

## Tool authorization (fail closed)

```
registered tool  !=  authorized tool for this agent
```

- Unknown profile → `UnauthorizedTool`, no default capabilities
- Known profile → explicit `PROFILE_TOOLS` allowlist
- Model-requested tools not in that allowlist are not executed
- `shell` remains implemented but is not on any research or verifier allowlist
- `verifier` has tools but is **not** a research profile. Decompose/dispatch cannot assign it. Coordinator calls `Verifier` separately.

Do not add a profile to `DEFAULT_TOOLS` as a fallback. `DEFAULT_TOOLS` is documentation of the research tool set, not an authorization backdoor.

## Rules of the road

1. **No LangChain / LangGraph / CrewAI.** Raw `AsyncOpenAI` against `https://api.deepseek.com`.
2. **Prompts are markdown files.** Edit `coordinator/prompts/*.md` and `agents/profiles/*.md`.
3. **Every TaskBoard mutation saves.**
4. **Sub-agent failure is not coordinator failure.** Typed runtime errors mark the task `BLOCKED`.
5. **Structured output is Pydantic.** ResearchReport / Evidence / decompose / synthesize.
6. **Per-agent usage is local.** Coordinator merges `UsageSummary` after each run. Do not subtract global totals.
7. **Keep it flat.** Dict registry, direct imports, no plugin frameworks.

## Adding a tool

1. Create `src/momentum_research_agent/tools/your_tool.py`.
2. Decorate an `async def your_tool(**kwargs) -> str` with `@register_tool`.
3. Import the module in `tools/__init__.py` so registration happens.
4. Add the name to the relevant `PROFILE_TOOLS` allowlists. Registration alone does not authorize it.
5. Mention the tool in the profile markdown that should use it.

## Adding an analyst profile

1. Write `src/momentum_research_agent/agents/profiles/{name}.md`.
2. Copy or symlink it into repo-root `profiles/`.
3. Add `{name}` to the decompose prompt's allowed profile list **and** to `PROFILE_TOOLS`.
4. Unknown names fail closed. Do **not** add `verifier` to the decompose list; it is invoked only by the Coordinator after research completes.

## Tests

```bash
uv sync --group dev
uv run pytest
```

Do not hit the live DeepSeek API in unit tests.

## What not to build here

No AgentBus, SpawnGuard, verifier-of-the-verifier, web UI, Docker, database, MCP server, or extra agent frameworks. Follow-up research is the one bounded in-session round above — do not turn it into an unbounded loop. Cross-session gap seed plants at most 2 `kind=gap` tasks; replan is at most one `kind=replan` after the first wave. Copying `structured_snapshot.json` is not a V_D pass path.
