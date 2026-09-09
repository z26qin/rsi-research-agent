# Local run control and 08:00 Toronto brief scheduling

Approved in conversation: implement phases 4–5, independent local service, manually
started research, Daily Brief auto-enabled after acceptance at 08:00 America/Toronto.

## Boundary

Keep the existing CLI/coordinator/verifier untouched. A loopback-only Python service
accepts validated research or brief requests, serializes service-owned jobs, and stores
atomic local JSON state. The development server proxies a fixed /control surface after
Host/Origin checks, adding a local private token that never reaches the browser bundle.
State/token live outside the repository in `~/.local/state/momentum-ui/<project-hash>/`
(directory 0700, files 0600); Vite denies direct access to credential/state filenames.
No arbitrary command, model, filesystem, resume, eval, policy or tool endpoint.
Research mode team/single; 1–4 agents; question 1–4000 characters. Explicit confirmation
and idempotency key required. Brief accepts a completed NYSE session date. Outputs go
only to fresh generated directories in the configured backend reports root. Backend
default loop budgets remain; supervisor caps research at 15 minutes, brief at 3 minutes.
Termination stops the owned process group. Service restarts never replay jobs. The
service lock is inherited by its child so a surviving job blocks competing services.
External direct CLI runs are outside this service's serialization boundary.

## Daily schedule

08:00 America/Toronto, DST-aware. Target the latest completed session, not today's
unfinished trading day. Persist dedupe by target date and scheduled attempt. Recheck
readiness every 15 minutes until 10:00 (at most 9 checks); only one actual scheduled
engine attempt per target. No input download, no scheduled LLM research, no unbounded
retry or historical catch-up. New enablement starts at the next 08:00. A missed window
is recorded; explicit manual generation remains available. Existing valid partial briefs
for that as-of suppress duplicate scheduled generation. API failure/partial status stay
separate. No claim of a successful assessment from process exit alone.

Calendar is a bounded offline 2026–2028 NYSE calendar verified against
https://www.nyse.com/trade/hours-calendars (2026-09-08); outside this range fail closed.
Special unscheduled exchange closures require a calendar update. Existing engine
cutoff semantics remain unchanged; no frontend reinterpretation of an early close.

## UI

Runs page: service connectivity, manual research form with confirmation, manual brief
date form with confirmation, Toronto schedule enable/disable, next check and most recent
readiness/skip/error reason, job history with artifact links. Real execution is visibly
separate from Demo. Completed jobs flow into existing read-only artifact importer.
No running state inferred from stored TaskBoard ACTIVE. No automatic research retry.

## Verification and activation

Test validation, injection/path rejection, same-origin/token enforcement, idempotency,
process timeout/failure classification, restart recovery, calendar/DST/holiday behavior,
readiness retry budget, duplicate dates and UI confirmation/connectivity. All subprocess
execution tests use controlled fake workers; no live model/engine runs for testing.
After tests, start service locally and enable only the approved 08:00 brief schedule.
No login-service installation or cloud deployment. Scheduling needs the computer awake
and the local service alive; closing the web page does not stop it.
