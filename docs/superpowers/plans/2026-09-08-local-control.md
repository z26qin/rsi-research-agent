# Local control implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Manual backend runs and bounded 08:00 Toronto Daily Brief automation.
**Architecture:** Separate local Python service; authenticated same-origin Vite proxy;
existing CLI subprocess and read-only artifact ingestion. No runtime rewrite.
**Tech Stack:** Python stdlib, existing backend dependencies, React/TypeScript.
**Spec:** docs/superpowers/specs/2026-09-08-local-control-design.md

## Global Constraints

No arbitrary commands/paths, model calls in tests, altered verifier, auto-replayed jobs,
cloud deployment, login-daemon installation, or browser-exposed credentials.

### Task 1 — Calendar and scheduler decisions
- [x] Write `frontend/scripts/test_control.py`: Toronto DST, holidays, dates, 08–10
  window, retry limit, duplicate as-of and enable-next-morning cases.
- [x] Verify failure; implement `control_calendar.py` pure date helpers and scheduling
  decisions consumed by `ControlManager.tick(now)`.

### Task 2 — Durable job manager and fixed CLI boundary
- [x] Extend tests for request validation, idempotency, serial dispatch, status/artifact
  distinction, and restart interruption. Implement `control_manager.py` with atomic JSON
  state, `submit(payload, now)`, `snapshot(now)`, `tick(now)`, and `set_schedule(enabled, now)`.
- [x] Implement fixed CLI invocation, isolated process group, deadline and input probe.
  Inject runner/readiness only through constructor for boundary testing.

### Task 3 — Local transport
- [x] Write HTTP security tests before implementing `control_service.py` and Vite
  `scripts/control_proxy.mjs`. Fixed endpoints: GET /status, POST /jobs, POST /schedule.
  Token stays outside the repository in private local state, file mode 0600; loopback-only service.
- [x] Verify missing/wrong token, hostile Origin/Host, invalid method/body and oversized
  payload rejection. Startup defaults schedule disabled; acquire singleton backend lock.

### Task 4 — Frontend controls
- [x] Write tests for offline service, confirmation, duplicate submit protection, schedule
  toggle and real-run artifact navigation. Implement typed control client + Runs page.
- [x] Add explicit links from Research and Daily Briefs; preserve Demo and reader flows.

### Task 5 — Acceptance and activation
- [x] Run control/importer suites, TS/interaction tests + coverage, typecheck, build,
  privacy/worker tests, independent read-only review and HTTP smoke.
- [x] Start the local service without running a job; enable the approved Toronto 08:00
  schedule via authenticated API. Verify saved state/next check and disclose data readiness.
- [x] Update README and this execution record. Keep work unmerged until user requests it.

## Acceptance record — 2026-09-08

- Backend suite: 275 passed. Importer/watcher/control suites: 53 passed.
- Frontend: 45 passed; statements 89.55%, branches 84.56%, functions 85.26%, lines 89.78%.
- TypeScript and Ruff passed. Production Demo build passed (non-blocking bundle-size and dependency annotation warnings).
- Proxy integration: 1 passed. Privacy/build tests: 4 passed. Worker tests: 4 passed.
- Independent read-only review found process-group cleanup, uncertain-request recovery,
  malformed-prior-brief, and post-spawn persistence-failure issues; corrected with regression tests.
- Real local HTTP smoke: service online, missing token/origin rejected (403), private
  connection file denied by Vite (403), artifact sync ready. No browser QA in this phase.
- Approved schedule activated and read back: enabled, America/Toronto 08:00,
  next check **2026-09-09T08:00:00-04:00**, zero jobs launched during activation.
- Read-only input probe for 2026-09-08: not ready; 8 input panels lack date coverage.
  Scheduler will wait/expire without executing the engine until required inputs exist.
- Local service and Vite left running; no login daemon, deployment, commit or merge.
  No live model or engine execution used for acceptance. First real-data result remains
  dependent on existing backend configuration and cached data readiness.
