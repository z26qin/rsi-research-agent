# Task 2 report: bounded replay and behavioral shadow comparison

## Outcome

Implemented accepted slices 2–3 with the existing ReAct loop. The runner uses only
validated stored `engine_query` / `web_search` observations and never falls back to a
live tool. The comparison is a paired behavioral assertion check over separately
curated, case-hash-bound expectations; it is not generic semantic truth scoring and
does not promote policy or write the active pointer/gap ledger.

No credential file was read or changed and no paid request was made by the implementer.
The controller separately ran the explicitly bounded synthetic wiring smoke described
below.

## Implementation

- Added `eval/replay_runner.py`:
  - canonical `(tool name, JSON arguments)` stored-observation matching;
  - trace hash/truncation/tool/profile checks and conflicting-observation rejection;
  - closed-over replay functions whose tool identity cannot be changed by model args;
  - every actual call recorded, including unknown/unmatched/non-finite calls;
  - no live-tool fallback, and unmatched calls make the run unscorable;
  - real profile/report instructions/ReAct loop/`LoopBudget`/`UsageSummary` reuse;
  - capability-scoped prompt overlays, task templates, and authorized tool guidance;
  - no legacy mutable overlay or `PolicyStore.load_active()` use;
  - a shared hard attempted-request budget checked immediately before each request;
  - `with_options(max_retries=0)`, explicit output tokens and temperature;
  - requested and actual response model IDs, raw/report output, calls, usage, latency,
    completion state, outcome, and sanitized reasons;
  - max-turn-after-tool, stale intermediate text, length truncation, malformed reports,
    budget exhaustion, and unknown observations cannot count as success;
  - `CancelledError` continues to propagate.
- Added `react_loop_detailed()` while preserving the existing `react_loop()` string API.
  The detailed result distinguishes a real final answer from length/max-turn exits and
  accepts bounded request/response hooks.
- Added `eval/live_compare.py`:
  - `BehavioralExpectationSet` with reviewer/provenance/rationale metadata;
  - exact `SessionEvalCase` content-hash binding;
  - explicit target/guard distinction;
  - non-vacuous exact required calls, optional engine as-of binding, observation-backed
    evidence requirements, and typed claim-withholding/status assertions;
  - evidence URL/excerpt validation against observations actually consumed;
  - exact paired case/repeat execution and per-pair resolved-model fairness;
  - violations and unscorable runs retained rather than converted to passes;
  - target improvements separate from observed guard non-regression;
  - self-contained `reports/live_evals/<unique-id>/comparison.json` with policies,
    cases, selected expectations/hash, budgets, outputs, usage, latency, and outcomes;
  - runtime failures are recorded into the persisted comparison without raw transport
    details.
- Added CLI surfaces:
  - `--import-session PATH` remains offline;
  - `--live-compare` requires explicit baseline/candidate/cases/expectations;
  - positive max-cases/repeats/request/output/turn/timeout bounds;
  - enforced request and output-token ceilings printed before client creation;
  - missing key exits before a request.
- Updated `AGENTS.md` and `README.md` for occurrence-aware gap import, evaluation
  artifacts, expectation semantics, operator commands, and the synthetic smoke result.

## Stable interfaces

```python
from momentum_research_agent.eval.replay_runner import (
    LLMRequestBudget,
    ReplayRunResult,
    case_content_sha256,
    run_replay_case,
)
from momentum_research_agent.eval.live_compare import (
    BehavioralExpectation,
    BehavioralExpectationSet,
    ExpectedEvidence,
    ExpectedToolCall,
    LiveComparisonReport,
    run_live_compare,
)
```

`run_replay_case(...) -> ReplayRunResult` accepts an explicit client, requested model,
project root, `SessionEvalCase`, supplied validated `ResearchPolicy`, `LoopBudget`, shared
`LLMRequestBudget`, and max output tokens.

`run_live_compare(...) -> tuple[LiveComparisonReport, Path]` accepts the same controls
plus explicit baseline/candidate policies, cases, expectations, repeats, and max cases.

The expectations file is a `behavioral_expectations_v1` object containing an
`expectations` list. Each entry requires `case_id`, `case_sha256`, `kind`, `reviewer`,
`provenance`, `rationale`, at least one exact `required_calls` item,
`allowed_report_statuses`, and either `required_evidence` or
`require_no_findings=true`.

## TDD evidence

Initial RED before implementation:

```text
PYTHONPATH=src ../apodex-policy-loop/.venv/bin/python -m pytest \
  tests/test_react_loop.py tests/test_replay_runner.py -q

ImportError: cannot import name 'react_loop_detailed'
ModuleNotFoundError: No module named 'momentum_research_agent.eval.replay_runner'
2 errors in 0.47s
```

Initial runner GREEN:

```text
14 passed in 0.45s
```

Further focused RED/GREEN cycles proved:

- model `_tool_name` arguments could override a closure default and incorrectly match a
  trace: `1 failed, 1 passed`; a factory with a closed-over identity fixed it;
- an omitted/unknown replay tool request initially produced a false successful run:
  `1 failed`; recording it as `REPLAY_UNAVAILABLE` made all 7 runner tests pass;
- an empty case directory initially loaded as a valid empty selection: `1 failed`;
  explicit rejection fixed it;
- aggregate model sets initially masked opposite per-pair model drift: `1 failed`;
  per-case/repeat fairness fixed it;
- a report initially hashed the caller's full expectation set rather than its persisted
  selected subset: `1 failed`; the self-contained hash now matches stored expectations;
- zero request budget was initially accepted: `1 failed`; all public numeric bounds are
  now positive, while an already-exhausted positive budget exercises failure behavior.

Final focused verification and per-module coverage:

```text
PYTHONPATH=src ../apodex-policy-loop/.venv/bin/python -m pytest \
  tests/test_react_loop.py tests/test_replay_runner.py tests/test_live_compare.py \
  tests/test_live_compare_cli.py \
  --cov=momentum_research_agent.eval.replay_runner \
  --cov=momentum_research_agent.eval.live_compare \
  --cov-report=term-missing -q

25 passed in 1.06s
live_compare.py: 280 statements, 51 missed, 82% coverage
replay_runner.py: 176 statements, 16 missed, 91% coverage
total: 85% coverage
```

Fresh compile and full-suite verification:

```text
PYTHONPATH=src ../apodex-policy-loop/.venv/bin/python -m compileall -q \
  src/momentum_research_agent

PYTHONPATH=src ../apodex-policy-loop/.venv/bin/python -m pytest -q
190 passed in 1.14s

git diff --check
# exit 0
```

## Controller-owned synthetic live wiring smoke

The controller ran one explicitly synthetic target plus one synthetic guard, two
policies, one repeat, max three turns, max 12 attempted LLM requests, and max 1,024
output tokens/request. It did not use or claim a historical corpus.

Result artifact (ignored controller workspace):

```text
reports/synthetic_live_smoke/reports/live_evals/
20260905_223059_8ef8d45f/comparison.json
```

- all four policy/case runs succeeded;
- each run made two LLM requests, eight total under the 12-call cap;
- every response resolved to `deepseek-v4-flash`;
- usage was 9,317 prompt + 1,653 completion = 10,970 tokens;
- both policies passed both toy cases;
- `observed_no_regression=true`, `target_improvements=[]`;
- the active policy pointer remained unchanged.

This validates bounded live wiring and the guard path only. It is not evidence of a
candidate improvement, historical performance, statistical significance, or generic
research quality.

## Remaining concerns

- No historical session corpus existed in the scoped roots. Real failure-case curation
  and comparison remain operator work; the code does not fabricate that dataset.
- This slice intentionally stops at shadow evaluation. Promotion and execution-time
  replanning remain outside scope.
- Evidence assertions are deliberately narrow and literal (call arguments plus consumed
  URL/excerpt provenance or withholding). Broader semantic judging would require a
  separately reviewed design and must not be inferred from these results.
