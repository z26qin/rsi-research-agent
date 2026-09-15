# Momentum Research Agent

An evidence-driven research agent for US equity momentum risk, built around a bounded agent loop and evaluation-gated self-improvement. Uses `deepseek-flash` (DeepSeek V4.1 Flash); daily briefs and the frontend make its research usable.

- **Daily brief:** MTUM versus SPY returns, volatility, drawdown, and optional crowding and short-interest evidence.
- **Research:** factual questions use one analyst; comparisons and risk assessments use a coordinated team. Reports retain sources, dates, metrics, and evidence gaps.
- **Self-improvement:** a separate offline evaluation loop for versioned research policies. Candidates must pass evaluations without regressions before promotion; policies cannot modify Python/tool code or the verifier.

Daily delivery, optional research, and policy improvement run separately. Missing evidence stays explicit; ETF proxies and monitoring scores are not crash probabilities.

## Agent loop

Automatic routing sends factual questions to **Single** and comparisons or risk assessments to **Team**. Either mode can be selected explicitly.

```text
Question → route + pin active policy
  Single → one analyst
  Team   → Coordinator → TaskBoard → parallel analysts
Analyst ReAct: reason → authorized tool → observation → repeat within budget
  → ResearchReport JSON (findings, numeric metrics, dates, sources, gaps)
  → independent Verifier → answer / team synthesis
```

Each analyst has bounded turns, timeouts, and an explicit tool allowlist. Search discovers sources; URL reading supplies page content. Unsupported web findings are withheld. The verifier judges existing evidence IDs, stays independent of research policies, and cannot override a static rejection with an optimistic LLM verdict.

Team research can seed up to **2 prior gap tasks**, run at most **1 replan** after blocked/mock/failed-delivery work, and make **1 follow-up round** for rejected or unchecked evidence. Single answers skip this team orchestration. Task state, tool traces, reports, and verification are saved for inspection and replay.

## Self-improvement loop

Improvement is explicitly invoked with `--improve`, never a mandatory stage of a daily brief or research run.

```text
Active policy + offline engine guards + recorded trajectory cases
  → evaluate baseline → select failed checkpoints
  → one constrained LLM reflection → schema-validated PolicyPatch
  → evaluate candidate on the same cases
  → promotion gate → activate immutable version for future sessions
                   → reject / no change: retain current version
```

- **Allowed changes:** prompt overlays, task templates, and selection among already-authorized tools. No Python/tool-code changes, added permissions, or verifier changes.
- **Promotion requires:** passing engine guards, no pass/fail or per-case score regression, at least one triggering failure fixed, and a higher aggregate score. Promotion atomically changes the active policy pointer; running and resumed sessions keep their pinned version. Rollback validates and activates a prior version.
- **Current scope:** `--improve` uses bundled recorded contract cases. Offline checks establish contract compliance, not general LLM reasoning quality. `--import-session` creates pending real failure cases; `--live-compare` separately compares baseline/candidate behavior against reviewed expectations and stored observations, without promotion.

Connecting representative real failures to measured, repeatable research improvement is the next priority: see [TODO](TODO.md). The [feedback experiment](docs/feedback-experiment.md) provides the bounded capture → review → reflection → shadow-comparison workflow.

## Frontend UI

Browse daily briefs, run research, and inspect answers, numeric observations, sources, and independent verdicts.

![Momentum research dashboard](frontend/qa/dashboard-desktop.png)

<details>
<summary>Evidence review</summary>

![Evidence filters, claims, and source inspector](frontend/qa/evidence-desktop.png)

</details>

Screenshots show **Demo mode, September 8, 2026**: illustrative data, before the later Daily Brief and run-control additions.

## Quick start

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and Node.js/npm for the UI.

```bash
uv sync --group dev
cp .env.example .env
# Add DEEPSEEK_API_KEY to .env for LLM research.

npm --prefix frontend install
npm --prefix frontend run dev -- --host 127.0.0.1 --port 4173
```

Open [localhost:4173](http://127.0.0.1:4173). To launch runs from the UI, start the execution service in a second terminal:

```bash
npm --prefix frontend run control:start -- --brief-source etf-proxy
```

Demo mode and saved-report browsing need no API key. Native web search reuses the DeepSeek key. To load an existing environment file, set `MOMENTUM_ENV_FILE=/absolute/path/to/.env`.

## CLI usage

```bash
# Previous trading session: public ETF data, no LLM or API key
uv run momentum-research-agent --daily-brief --brief-source etf-proxy

# Add issuer flows, concentration, and holdings overlap
uv run momentum-research-agent --daily-brief --brief-source etf-proxy --with-crowding

# Momentum, crowding, short interest, and volatility comparison; no LLM
uv run momentum-research-agent --daily-brief --brief-source etf-proxy \
  --with-market-research --reference-date 2026-05-29 --no-brief-llm

# Automatic routing: factual answer or deeper research
uv run momentum-research-agent "What are MTUM's top 10 holdings? Include weights, observation date, and sources."
uv run momentum-research-agent --mode team "Compare momentum crowding and volatility with May 29."

# Historical deterministic engine; explicit date required
uv run momentum-research-agent --daily-brief --brief-source engine --as-of 2026-05-29

# Deterministic evaluation; improvement may make one LLM reflection call
uv run momentum-research-agent --eval
uv run momentum-research-agent --improve
```

Use `--help` for all options. Reports and data snapshots are saved under `reports/`; `--session-dir` selects an output directory. Research retains structured JSON, readable Markdown, tool traces, and verifier verdicts. Process completion and an answered question are reported separately.

ETF briefs use public data for the previous New York trading session. The original engine uses processed historical inputs: set `MOMENTUM_ENGINE_DIR` for an external checkout, or use the bundled historical engine. Neither stale data nor missing evidence is treated as current coverage.

## DeepSeek pricing

Research, coordinator, and native search default to `deepseek-flash`. Override research models with `SUB_AGENT_MODEL` and `COORDINATOR_MODEL`.

Official **USD per 1 million tokens**, checked September 12, 2026:

| Model | Period | Input: cache hit | Input: cache miss | Output |
| --- | --- | ---: | ---: | ---: |
| `deepseek-flash` | Off-peak | $0.003 | $0.15 | $0.60 |
| `deepseek-flash` | Peak | $0.006 | $0.30 | $1.20 |
| `deepseek-v4-pro` | Off-peak | $0.022 | $0.66 | $1.98 |
| `deepseek-v4-pro` | Peak | $0.044 | $1.32 | $3.96 |

Peak hours: Monday–Friday, **01:00–04:00 and 06:00–10:00 UTC**; all other hours are off-peak. See [official pricing](https://api-docs.deepseek.com/quick_start/pricing/) for updates. The application's cost summary currently uses older fixed estimates and does not account for cache discounts or peak hours; it is not a billing total.

## Documentation and tests

- [Frontend setup and run control](frontend/README.md) · [Mobile UI](frontend/qa/home-390.png)
- [Structured research](docs/structured-research.md) · [Native search and budgets](docs/native-search.md)
- [ETF brief and replay](docs/etf-proxy-brief.md) · [Five-question market brief](docs/market-research-brief.md)
- [Crowding indicators](docs/crowding-indicators.md) · [Historical imports](docs/historical-crowding.md) · [Fixed-basket comparisons](docs/fixed-basket.md)
- [Policy evaluation experiments](docs/feedback-experiment.md) · [Architecture and contributor rules](AGENTS.md)
- [RSI frozen research arena, promotion and replay](docs/rsi-arena.md)

```bash
uv run pytest
npm --prefix frontend test -- --run
npm --prefix frontend run typecheck
```
