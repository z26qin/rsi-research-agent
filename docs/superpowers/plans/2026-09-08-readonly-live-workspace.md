# Read-only live workspace — approved phases 1–3

Scope: automatically import existing backend artifacts, explain recorded Agent flow,
and put the latest market/book Daily Brief on Home. No execution endpoint, scheduler,
backend mutation, model call, deployment, or change to verification semantics.

1. Test and implement a local artifact watcher. Resolve the main checkout by default;
   allow explicit project/reports roots. Scan only importer-approved paths. Coalesce
   edits, stage immutable snapshots, retain last published data on malformed input,
   expose read-only sync health, and stop with the development server.
2. Test and implement one-manifest workspace loads. Poll in Artifact mode, reuse the
   snapshot when its version is unchanged, retain prior data on transport failure,
   and expose snapshot time plus synchronization health. Never fall back to Mock.
3. Test and implement latest-available brief on Home, including a newer failed attempt;
   preserve as-of/cutoff/partial semantics. Add readable recorded task groups and
   independent artifact/verification states to session overview and Agent Pulse.
4. Run Python importer/watcher tests, TypeScript/interaction tests, typecheck, production
   build, and a local HTTP smoke check. Document actual-data availability and limits.

Validation must use temporary synthetic artifacts when real reports are absent;
never plant demonstration files into real reports or launch research to obtain fixtures.

## Execution record

Implemented all four tasks in the existing isolated frontend worktree. No backend
source/report changes, live engine/model calls, deployment, or launch endpoints.

- Python importer/watcher: 25 tests passed, including persistent worker detection,
  shutdown, syntax-invalid retention/recovery, ignored policies, profile changes,
  unsafe output roots, and legacy verification trace fallback.
- Frontend: 39 tests passed. Includes Python import → typed adapter → React Home,
  automatic refresh, disconnect retention, expired heartbeat, typed-schema retention,
  pinned manifests, latest available brief versus newer failure, and recorded flow.
- Coverage: statements 89.45%, branches 84.85%, functions 85.17%, lines 89.36%.
- Typecheck/build passed; worker packaging 4/4, artifact privacy build tests 4/4.
- Ruff and git diff --check passed.
- Local HTTP smoke: Home 200, sync ready, POST artifacts denied 405.
- Main checkout discovery: 0 sessions, 0 briefs, 6 real profile entries. Complete
  genuine content acceptance remains contingent on saved backend session/brief files.
  Temporary backend-shaped fixtures prove the data path, not the truth of research.
- Independent read-only review found two P2s (legacy trace notice blocked sync;
  schema-invalid sessions bypassed retention). Both fixed with regression tests.
- No new visual/browser QA performed this phase; prior visual QA applies to the
  earlier design only. New surfaces were covered by component/interaction tests.

Operational limits: local development only; 3-second source checks and 4-second page
polling, plus import time. Static builds do not auto-sync. A persistent syntax-invalid
source holds the complete generated snapshot; typed failures retain the last loaded
valid workspace in the current page. Initial loads show available valid siblings and
diagnostics if no earlier typed-valid workspace exists. No persisted browser copy of
private research is introduced. Source signatures use path/type/size/mtime/inode, not
continuous full-file hashing. Immutable generated snapshots accumulate; no automatic
retention deletion was added, to avoid invalidating open-page references.
