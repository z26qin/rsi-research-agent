# Momentum research workspace

A local React/TypeScript workspace for saved research, browser-only Demo scenarios, and explicitly authorized local execution. Explore sessions, analyst tasks, evidence, independent verdicts, stored tool observations, daily briefs, and gap occurrences. The artifact reader never executes traces or writes reports. A separate restricted service launches the existing backend CLI from the Runs page; no policy, arbitrary command, or arbitrary tool endpoints are exposed.

## Run locally

From the repository root, with Node.js/npm and Python 3 available:

```bash
npm --prefix frontend install
npm --prefix frontend run dev -- --host 127.0.0.1 --port 4173
```

Open [the local workspace](http://127.0.0.1:4173). Development startup imports once, then keeps a read-only polling worker attached to Vite. Workspace settings lets you choose **Demo workspace** or **Local research artifacts**. No model API key is needed.

In Artifact mode, source files are checked every 3 seconds and the page refreshes every 4 seconds while visible. Unchanged manifests reuse their loaded objects. Typical update latency is up to roughly 7 seconds plus import time. No manual sync is needed during development. For a one-off import without the server:

```bash
npm --prefix frontend run sync:artifacts
```

**Refresh snapshot** reloads generated data and sync health; it never runs research. Saved ACTIVE statuses describe recorded task state, not process liveness. Snapshot time is the import time; source timestamps and daily-brief cutoffs remain separate. A stale/missing watcher heartbeat is shown explicitly. Automatic sync requires the local development server; a static build remains a frozen snapshot.

The default is the **main Git checkout's `reports/`**, including when this frontend lives in a linked worktree. To point the persistent worker elsewhere, set explicit paths when starting Vite (restart it when changing paths):

```bash
MOMENTUM_REPORTS_ROOT=/absolute/path/to/reports MOMENTUM_ARTIFACT_PROJECT_ROOT=/absolute/path/to/backend npm --prefix frontend run dev -- --host 127.0.0.1 --port 4173
```

For a standalone import, flags also work:

```bash
npm --prefix frontend run sync:artifacts -- --reports-root /absolute/path/to/reports
```

The watcher stages a complete snapshot before publishing it. Malformed JSON/JSONL, unsafe paths, unavailable roots, and writes racing an import retain the last published snapshot and show stale sync health; polling retries automatically. A persistent malformed file holds the whole snapshot until repaired or removed by its owner. Missing optional artifacts retain their missing-data semantics. JSON takes precedence over Markdown; missing verification means **Not reviewed**. Frontend schema diagnostics preserve valid siblings. Transport failures retain prior loaded data; the adapter never silently substitutes Demo research for a failed local read.

Home shows the latest available Daily Brief with its as-of/cutoff and `partial` status, plus a link to any newer unavailable attempt. If all attempts are unavailable, assessments remain withheld. Session overview groups recorded research/gap/replan/follow-up tasks, explains blocked causes, and keeps report, verifier, and synthesis outcomes distinct. No invented live progress percentage or automatic LLM research schedule is added.

## Local run control and Daily Brief schedule

### ETF mode (selected on 2026-09-09)

The service now persists `brief_source: etf-proxy`. This mode reuses the core from
commit `773468b` (four proxy modules and the matching CLI integration), without
the other branch's uncommitted work, crowding extensions, or LLM research.

At 08:00 Toronto it starts one bounded collection for the last completed session:
MTUM/SPY adjusted daily prices and optional FRED VIX. Each source has at most two
attempts within a shared 120-second collection budget; the service deadline is
180 seconds. A failed scheduled run is not automatically resubmitted. Missing
target-date ETF data withholds all core observations; optional VIX or lagged
French inputs do not block the valid ETF section. Weekends/holidays suppress
duplicate target dates. The existing cached-engine mode remains available.

Select the source when starting the service (stop the prior service first):

```bash
npm --prefix frontend run control:start -- --brief-source etf-proxy
```

Subsequent starts without this flag preserve the selected source. A source change
reschedules enabled automation for the next morning. Research still uses the
configured backend root unchanged. Only proxy execution uses this frontend
worktree's imported core, with outputs saved to the main checkout's reports.

Home and Daily Briefs distinguish ETF observations from original-model evaluation.
Return, drawdown and volatility values display as percentages; VIX is index points.
`factor_context.json` records actual dates of the existing engine factor cache,
not the latest date publicly published elsewhere. It is background only and does
not enable engine scores. The importer includes that sidecar without rewriting
the original `etf_proxy_brief_v1` report. Existing engine reports remain compatible.

First real collection: `brief_20260909_163944_4263ccb0`, target 2026-09-08; MTUM,
SPY and VIX matched target, all 16 core metrics reproduced from saved tables,
0 LLM calls. It was generated directly as a validation run, so it appears in
Daily Briefs, not the service-owned job history. Original engine evaluation remains
unavailable; source freshness is not independent investment-research verification.

The following generic startup and safety guidance applies to both sources;
cached-input readiness waiting applies only to engine mode.

Start the independent service in a second terminal (requires backend dependencies installed with `uv sync --group dev`):

```bash
npm --prefix frontend run control:start
```

Open [Runs & schedule](http://127.0.0.1:4173/runs). Research requires a question, single/team mode, 1–4 analysts, and an explicit API-usage confirmation. Daily Brief requires a completed-session date and confirmation. Accepted artifacts enter the existing sync pipeline automatically. Offline service and active service-owned jobs disable new submissions. Uncertain submissions retain their complete request and idempotency key in tab storage; retry reuses the original payload. History reconciliation clears accepted requests. Starting a new request is explicit and does not cancel the old one.

The fixed schedule is **08:00 America/Toronto**, automatically adjusting for DST. Engine mode checks cached inputs every 15 minutes through 10:00 (at most 9 checks), and allows at most one scheduled engine attempt per date without downloading data. ETF mode downloads the bounded public sources described above. Neither mode calls an LLM. Existing valid partial briefs of the selected source suppress duplicate dates. No historical catch-up or automatic failed-run retry. Scheduler calendar coverage is 2026–2028; future years and unscheduled closures require an update.

New installations default to schedule disabled. Enable it explicitly in Runs; enabling begins at the next 08:00. The persisted setting survives restart, but interrupted jobs are never replayed. **The computer must be awake and the service running**; closing the browser does not stop the service. No login daemon is installed. Turning off the schedule does not cancel an active job.

The service binds only to `127.0.0.1:4181`. Vite on port 4173 proxies fixed same-origin endpoints and adds a private token server-side. State and token are outside the repository in `~/.local/state/momentum-ui/<project-hash>/`, protected by directory/file permissions. Optional `MOMENTUM_CONTROL_STATE_DIR` must be the same for Vite and the service. `MOMENTUM_ARTIFACT_PROJECT_ROOT` chooses the backend for both; its `reports/` should also be the reader's report root. Never publish this state directory. The service has a backend-root singleton lock inherited by child processes, fixed CLI arguments, fresh artifact directories, and deadlines of 15 minutes for research / 3 minutes for briefs. Shutdown and timeout terminate owned process groups. Direct CLI runs outside this service are not serialized by it.

Research uses backend `.env` configuration and may incur model/tool costs; those secrets never enter the browser bundle. Backend authorization, agent budgets, and independent verification are unchanged. Process completion does not imply verified research. The static build has no execution proxy and displays service offline.

## Demo and navigation

Research creates a simulated run using the selected, prewritten scenario. Your question supplies context; the outputs are illustrative and are not newly researched answers or current market assessments. Pause, continue, and reset apply only to the Demo. Playback advances while the Research page is open and resumes from its saved step when you return.

Use `Cmd/Ctrl+K` for search, or `G` then `H`, `R`, or `S` for Home, Research, or Sessions. Navigation shortcuts do not intercept text input. Tabs, filters, and selected evidence/tasks use URL state; narrow layouts expose navigation and the inspector in drawers.

Demo progress and review marks use `sessionStorage`, which is scoped to the current browser tab/session. Refresh can restore them; closing the tab normally clears them. Browser storage failures fall back to in-memory use with a notice. Review marks never alter evidence, verdicts, or gap status. Inter and Instrument Serif ship through the installed Fontsource packages; runtime font loading does not require Google Fonts.

## Build modes and research privacy

```bash
# Default: Demo only, even when local snapshots exist.
npm --prefix frontend run build

# Explicit opt-in: include the current generated snapshot.
npm --prefix frontend run build:local

# Preview whichever build was produced most recently.
npm --prefix frontend run preview -- --host 127.0.0.1 --port 4174
```

`build:local` does not run sync. Run `sync:artifacts` first if you need a newer snapshot. The build reads only `frontend/.generated/artifacts/index.json` and the session/brief files referenced by that manifest. It copies the manifest—including gap entries, profiles, and diagnostics—and those referenced files into `dist/client/artifacts/`. Unreferenced files and older snapshot directories are excluded. Invalid references, missing files, malformed JSON, and symbolic links fail the local build. A subsequent successful default build clears the local snapshot from the output.

**A local build contains potentially private research.** Ignoring `.generated/` and `dist/` in Git does not make a copied or hosted local build private. Share a default Demo build when research content should be excluded. Neither build command deploys anything. If a build fails, do not treat any existing `dist/` directory as a newly validated build.

Both modes preserve the template's `dist/client/index.html`, `dist/server/index.js`, and `dist/.openai/hosting.json` packaging. The template worker retains SPA route fallback. Default builds have no artifact index, so selecting Local research artifacts in their preview reports unavailable data. Use development mode or an explicit local build to browse snapshots.

## Data boundary

The development server exposes a fixed, GET-only generated-artifact endpoint. It does not mount the original reports directory or offer arbitrary file paths. The importer reads the allowed session JSON/Markdown files, traces, daily briefs, and gap ledger; profile descriptions and tool allowlists are discovered statically from the backend source. It does not follow source symlinks or trace `source_path` values, import the research runtime, execute Python profile code, or read `.env` files. Rendering stored traces never executes them.

The importer writes only its separate generated-output directory and atomically publishes the index after writing its snapshot files. Source changes detected during an import retain the previous snapshot with diagnostics when one exists. Build scripts read generated snapshots and write their own `dist/` output. Original `reports/` artifacts are not modified by frontend sync or builds. Explicit execution requests and enabled scheduled briefs invoke the existing backend, which writes its normal artifacts.

## Verification

Run from the repository root:

```bash
npm --prefix frontend run typecheck
npm --prefix frontend run test -- --run
npm --prefix frontend run test -- --run --coverage
uv run pytest frontend/scripts/test_sync_artifacts.py -q
uv run pytest frontend/scripts/test_artifact_watch.py -q
uv run pytest frontend/scripts/test_control.py frontend/scripts/test_control_http.py -q
npm --prefix frontend run test:control-proxy
npm --prefix frontend run build
npm --prefix frontend run test:build-artifacts
npm --prefix frontend run test:sites
```

The packaging tests perform actual builds in temporary frontend copies with synthetic private markers. They check default exclusion, explicit inclusion, cleanup after a local build, traversal rejection, and symlink rejection. They do not execute a model or engine. The importer tests use synthetic report fixtures; passing them is not a claim that every private historical report has been inspected.

Browser acceptance tests live in `e2e/` and use `playwright.config.ts` against an already running local server on port 4173. For developers running them locally: `cd frontend && npx playwright install chromium && npx playwright test`. Screenshots and the visual comparison record are in `qa/` and [design-qa.md](design-qa.md).

The `ResearchDataSource` interface in `src/types/index.ts` is the future API boundary. UI components consume normalized, validated data through workspace context; a future HTTP adapter can replace the artifact adapter without exposing backend execution to components. `ArtifactResearchDataSource.loadWorkspace()` pins one manifest for all collections and caches only complete loads. This version loads the bounded local collection together, rather than using a paginated remote index.

Integration availability: the main checkout has the authorized real ETF Brief noted above; it has no saved agent research sessions at this verification point. Tests use synthetic artifacts; the separately authorized ETF collection uses actual public data. Existing backend profile files remain read-only.

See the [design specification](../docs/superpowers/specs/2026-09-08-research-workspace-design.md) and [implementation/verification plan](../docs/superpowers/plans/2026-09-08-research-workspace.md) for the agreed scope and acceptance record.
