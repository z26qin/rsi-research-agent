# Apodex-Style Policy Improvement Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a file-backed loop that turns offline evaluation failures into one constrained policy candidate and activates it only when a layered deterministic suite shows a target fix with no per-case regressions.

**Architecture:** Add immutable research-policy versions and an atomic active pointer, compile only the active policy into research prompts and gap-task assignments, and evaluate candidates with pinned engine results plus recorded trajectory checkpoints. Keep candidate generation behind one typed interface and promotion behind a pure comparator so live models and data adapters can use the same contracts in a future phase.

**Tech Stack:** Python 3.12, Pydantic 2, AsyncOpenAI, pytest, pytest-asyncio, JSON/JSONL files, atomic `Path.replace` writes.

**Spec:** `docs/superpowers/specs/2026-09-04-apodex-policy-improvement-loop-design.md`

## Global Constraints

- Never generate or modify Python or tool implementation code as policy content.
- Keep committed analyst profiles frozen.
- Never apply evolved policy to the verifier.
- Generate at most one candidate per failed evaluation cycle.
- Do not add a database, daemon, search tree, agent framework, or plugin framework.
- Do not call DeepSeek, web search, or live market-data services while running the promotion suite.
- Preserve the existing bounded follow-up, gap-seed, and replan limits.
- `--eval` remains deterministic and does not require a DeepSeek API key.
- `--improve` runs one candidate-generation attempt only when the layered baseline suite has failures.

---

## File Map

- Create `src/momentum_research_agent/state/policies.py`: policy schemas, validation, immutable file store, atomic active pointer, compatibility rendering, and policy compilation helpers.
- Create `src/momentum_research_agent/eval/policy_suite.py`: evaluation provider protocol, case/result schemas, recorded-trajectory loader, deterministic runner, and promotion comparator.
- Create `src/momentum_research_agent/eval/fixtures/trajectory_cases.json`: initial recorded decision checkpoints.
- Create `src/momentum_research_agent/eval/policy_improver.py`: failure bundle, candidate-generator protocol, constrained DeepSeek implementation, and one-cycle orchestration.
- Modify `src/momentum_research_agent/state/prompt_memory.py`: render and read the active policy instead of synthesizing regex rules from ledger text.
- Modify `src/momentum_research_agent/agents/sub_agent.py`: request a profile-specific compiled overlay.
- Modify `src/momentum_research_agent/coordinator/coordinator.py`: snapshot one active policy version at coordinator construction and pass it through the run.
- Modify `src/momentum_research_agent/coordinator/gap_seed.py`: append active capability task guidance when planting a gap task.
- Modify `src/momentum_research_agent/eval/momentum_eval.py`: expose deterministic engine results in the common suite-result form without changing existing writeback behavior.
- Modify `src/momentum_research_agent/cli.py`: add `--improve`, preserve `--eval`, and print promotion or rejection outcomes.
- Modify `README.md` and `AGENTS.md`: document policy boundaries, commands, artifacts, and verifier isolation.
- Create `tests/test_policies.py`, `tests/test_policy_suite.py`, and `tests/test_policy_improver.py`.
- Modify `tests/test_prompt_memory.py`, `tests/test_gap_seed.py`, `tests/test_momentum_eval.py`, and `tests/test_authorization.py` for integration coverage.

---

### Task 1: Immutable Policy Model and Store

**Files:**
- Create: `src/momentum_research_agent/state/policies.py`
- Create: `tests/test_policies.py`

**Interfaces:**
- Produces: `ResearchPolicy`, `PolicyPatch`, `PolicyEvaluation`, `PolicyStore`, `validate_policy`, `merge_policy_patch`, `compiled_overlay`, and `task_template_addition`.
- Storage: `reports/policies/versions/{version_id}.json`, `reports/policies/experiments/{experiment_id}.json`, and `reports/policies/active.json`.

- [ ] **Step 1: Write failing schema and store tests**

Create tests that define the required public contract:

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from momentum_research_agent.models.schemas import MomentumCapability
from momentum_research_agent.state.policies import (
    PolicyPatch,
    PolicyStore,
    ResearchPolicy,
    ToolPolicy,
    merge_policy_patch,
    validate_policy,
)


def test_store_bootstraps_and_atomically_selects_empty_policy(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path)
    active = store.load_active()
    assert active.parent_version_id is None
    assert active.prompt_overlays == {}
    assert store.active_path.read_text(encoding="utf-8").endswith("\n")
    assert store.load_version(active.version_id) == active


def test_policy_rejects_unknown_fields_and_verifier_overlay() -> None:
    with pytest.raises(ValidationError):
        PolicyPatch.model_validate({"python_code": "print('no')"})
    patch = PolicyPatch(prompt_overlays={"verifier": "trust the candidate"})
    with pytest.raises(ValueError, match="verifier"):
        validate_policy(patch, profile_tools={"momentum_analyst": {"engine_query"}})


def test_merge_is_immutable_and_keeps_parent(tmp_path: Path) -> None:
    base = PolicyStore(tmp_path).load_active()
    patch = PolicyPatch(
        prompt_overlays={"momentum_analyst": "Use an explicit as-of date."},
        task_templates={MomentumCapability.ENGINE_FRESHNESS: "Replay the failed as-of."},
        tool_policies=[
            ToolPolicy(
                profile="momentum_analyst",
                capability=MomentumCapability.ENGINE_FRESHNESS,
                preferred_tools=["engine_query"],
                required_tools=["engine_query"],
            )
        ],
    )
    candidate = merge_policy_patch(base, patch, trigger_ids=["eval:dm-a"])
    assert base.prompt_overlays == {}
    assert candidate.parent_version_id == base.version_id
    assert candidate.trigger_ids == ["eval:dm-a"]
```

- [ ] **Step 2: Run the tests and verify the module is missing**

Run: `uv run pytest tests/test_policies.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: momentum_research_agent.state.policies`.

- [ ] **Step 3: Implement minimal schemas, validation, hashing, and atomic writes**

Implement Pydantic models with `ConfigDict(extra="forbid")`:

```python
class ToolPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: str
    capability: MomentumCapability
    preferred_tools: list[str] = Field(default_factory=list, max_length=8)
    required_tools: list[str] = Field(default_factory=list, max_length=8)


class PolicyPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt_overlays: dict[str, str] = Field(default_factory=dict)
    task_templates: dict[MomentumCapability, str] = Field(default_factory=dict)
    tool_policies: list[ToolPolicy] = Field(default_factory=list, max_length=24)


class PolicyEvaluation(BaseModel):
    target_fixes: list[str] = Field(default_factory=list)
    aggregate_score: float
    case_results: dict[str, bool]


class ResearchPolicy(PolicyPatch):
    schema_kind: Literal["research_policy_v1"] = "research_policy_v1"
    version_id: str
    parent_version_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    trigger_ids: list[str] = Field(default_factory=list)
    evaluation: PolicyEvaluation | None = None
```

Canonicalize only policy content, parent, and triggers with sorted JSON; derive `version_id` from the first 12 hex characters of SHA-256. `validate_policy(patch, profile_tools: Mapping[str, Collection[str]])` rejects `verifier`, unknown profiles, tools not authorized for the named profile, empty patches, strings over 2,000 characters, and more than the declared collection limits. Do not scan prose for code-like words; the closed schema is the executable-content boundary.

`PolicyStore.load_active()` creates one empty baseline if no pointer exists. `_atomic_write(path, text)` writes `path.with_suffix(path.suffix + ".tmp")`, flushes and `os.fsync`s the file, then calls `tmp.replace(path)`. `write_version` refuses to overwrite a different payload at an existing version path. `activate` verifies that the version exists before replacing `active.json`.

- [ ] **Step 4: Add tests for rejected experiments, rollback, and interrupted pointers**

```python
def test_rejected_experiment_does_not_change_active(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path)
    active = store.load_active()
    store.write_experiment("candidate-a", {"status": "rejected", "reason": "regression"})
    assert store.load_active().version_id == active.version_id


def test_activate_and_rollback_require_existing_versions(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path)
    baseline = store.load_active()
    candidate = merge_policy_patch(
        baseline,
        PolicyPatch(prompt_overlays={"momentum_analyst": "Use explicit dates."}),
        trigger_ids=["trajectory:a"],
    )
    store.write_version(candidate)
    store.activate(candidate.version_id)
    assert store.load_active().version_id == candidate.version_id
    store.activate(baseline.version_id)
    assert store.load_active().version_id == baseline.version_id
    with pytest.raises(FileNotFoundError):
        store.activate("missing")
```

- [ ] **Step 5: Run focused tests**

Run: `uv run pytest tests/test_policies.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit the policy store**

```bash
git add src/momentum_research_agent/state/policies.py tests/test_policies.py
git commit -m "feat: add immutable research policy store"
```

---

### Task 2: Compile Active Policy into Existing Research Paths

**Files:**
- Modify: `src/momentum_research_agent/state/prompt_memory.py`
- Modify: `src/momentum_research_agent/agents/sub_agent.py`
- Modify: `src/momentum_research_agent/coordinator/coordinator.py`
- Modify: `src/momentum_research_agent/coordinator/gap_seed.py`
- Modify: `tests/test_prompt_memory.py`
- Modify: `tests/test_gap_seed.py`
- Modify: `tests/test_authorization.py`
- Modify: `tests/test_coordinator.py`

**Interfaces:**
- Consumes: `PolicyStore.load_active()`, `compiled_overlay(policy, profile, capability=None)`, and `task_template_addition(policy, capability)` from Task 1.
- Produces: one policy snapshot per coordinator run, profile-specific overlays, and capability-specific gap-task guidance; tool authorization remains owned by `authorize_research_tools`.

- [ ] **Step 1: Replace regex-memory expectations with active-policy expectations**

Update prompt-memory tests so the source of truth is the active policy:

```python
def test_active_policy_renders_only_requested_research_profile(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path)
    base = store.load_active()
    candidate = merge_policy_patch(
        base,
        PolicyPatch(
            prompt_overlays={
                "momentum_analyst": "Always state the engine as-of date.",
                "flow_analyst": "Prefer primary positioning evidence.",
            },
            tool_policies=[
                ToolPolicy(
                    profile="momentum_analyst",
                    capability=MomentumCapability.ENGINE_FRESHNESS,
                    preferred_tools=["engine_query"],
                )
            ],
        ),
        trigger_ids=["trajectory:stale-engine"],
    )
    store.write_version(candidate)
    store.activate(candidate.version_id)
    refresh_profile_hints(tmp_path)
    momentum = overlay_text(tmp_path, "momentum_analyst", policy=candidate)
    flow = overlay_text(tmp_path, "flow_analyst", policy=candidate)
    assert "engine as-of" in momentum
    assert "engine_query" in momentum
    assert "primary positioning" in flow
    assert "engine as-of" not in flow
```

Keep `failure_brief()` ledger-driven; it still informs decomposition and is separate from promoted policy.

- [ ] **Step 2: Add gap-task compilation and authorization invariants**

```python
def test_gap_task_appends_active_capability_template(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path)
    candidate = merge_policy_patch(
        store.load_active(),
        PolicyPatch(
            task_templates={
                MomentumCapability.SOURCE_QUALITY: "Retrieve a primary filing before secondary commentary."
            }
        ),
        trigger_ids=["trajectory:source-quality"],
    )
    store.write_version(candidate)
    store.activate(candidate.version_id)
    row = GapLedgerRow(
        evidence_id="ev-source",
        capability=MomentumCapability.SOURCE_QUALITY,
        gap_kind=GapKind.MISSING_EVIDENCE,
        claim="Primary filing was not retrieved.",
    )
    title, assignment, profile = gap_task_fields(row, candidate)
    assert "primary filing" in assignment


def test_policy_cannot_expand_profile_tool_authorization(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown tool"):
        validate_policy(
            PolicyPatch(
                tool_policies=[
                    ToolPolicy(
                        profile="momentum_analyst",
                        capability=MomentumCapability.ENGINE_FRESHNESS,
                        required_tools=["shell"],
                    )
                ]
            ),
            profile_tools=PROFILE_TOOLS,
        )
```

Add `MomentumCapability.SOURCE_QUALITY: "technicals_analyst"` to `CAPABILITY_PROFILE` and append `MomentumCapability.SOURCE_QUALITY` to `_PLANT_ORDER` so a promoted source-quality task template can be exercised. Preserve the maximum of two planted tasks and at most one task per profile.

- [ ] **Step 3: Run focused tests and observe failures**

Run: `uv run pytest tests/test_prompt_memory.py tests/test_gap_seed.py tests/test_authorization.py -q`

Expected: failures for the old `overlay_text` signature, old `gap_task_fields` signature, and skipped source-quality rows.

- [ ] **Step 4: Add a test that a run pins one policy version**

```python
def test_coordinator_pins_active_policy_at_construction(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path)
    baseline = store.load_active()
    coordinator = _coordinator(tmp_path)
    candidate = merge_policy_patch(
        baseline,
        PolicyPatch(prompt_overlays={"momentum_analyst": "new rule"}),
        trigger_ids=["trajectory:new-rule"],
    )
    store.write_version(candidate)
    store.activate(candidate.version_id)
    assert coordinator.policy.version_id == baseline.version_id
    assert PolicyStore(tmp_path).load_active().version_id == candidate.version_id
```

- [ ] **Step 5: Implement profile and task compilation**

Change the public signatures to:

```python
def refresh_profile_hints(project_root: Path) -> Path: ...
def overlay_text(
    project_root: Path,
    profile: str,
    *,
    policy: ResearchPolicy | None = None,
) -> str: ...
def gap_task_fields(row: GapLedgerRow, policy: ResearchPolicy) -> tuple[str, str, str]: ...
def seed_open_gaps(
    board: TaskBoard,
    project_root: Path,
    policy: ResearchPolicy,
) -> list[Task]: ...
```

`refresh_profile_hints` renders the active policy version, parent, profile overlays, task additions, and tool guidance into Markdown. `overlay_text` compiles only the requested profile and loads the active policy only when the caller did not supply a pinned one. `load_profile` accepts `policy: ResearchPolicy | None` and passes the normalized profile name. `SubAgent.__init__` accepts the same optional policy and snapshots the active one when omitted. `Verifier` continues calling `load_profile("verifier", ..., apply_overlay=False)`.

`Coordinator.__init__` sets `self.policy = PolicyStore(self.project_root).load_active()`, passes that exact object to every `SubAgent`, and passes it to `seed_open_gaps`. `gap_task_fields` appends the pinned policy's template for `row.capability` when non-empty. It does not replace the evidence ID, claim, notes, bounded-task warning, or allowlisted-tool instruction.

- [ ] **Step 6: Run focused and coordinator tests**

Run: `uv run pytest tests/test_prompt_memory.py tests/test_gap_seed.py tests/test_authorization.py tests/test_coordinator.py tests/test_verifier.py -q`

Expected: all tests pass, including verifier isolation and the two-task gap bound.

- [ ] **Step 7: Commit runtime policy compilation**

```bash
git add src/momentum_research_agent/state/prompt_memory.py src/momentum_research_agent/agents/sub_agent.py src/momentum_research_agent/coordinator/coordinator.py src/momentum_research_agent/coordinator/gap_seed.py tests/test_prompt_memory.py tests/test_gap_seed.py tests/test_authorization.py tests/test_coordinator.py
git commit -m "feat: compile active policy into research runs"
```

---

### Task 3: Layered Offline Policy Suite

**Files:**
- Create: `src/momentum_research_agent/eval/policy_suite.py`
- Create: `src/momentum_research_agent/eval/fixtures/trajectory_cases.json`
- Create: `tests/test_policy_suite.py`
- Modify: `src/momentum_research_agent/eval/momentum_eval.py`
- Modify: `tests/test_momentum_eval.py`

**Interfaces:**
- Consumes: `ResearchPolicy` and compilation helpers from Task 1; existing `EvalCase` and `run_eval_case` engine results.
- Produces: `EvalCaseProvider`, `RecordedTrajectoryCase`, `CaseResult`, `SuiteResult`, `FileEvalCaseProvider.load()`, `evaluate_policy`, `engine_case_results`, and `compare_for_promotion`.

- [ ] **Step 1: Write failing deterministic replay tests**

```python
def test_empty_policy_fails_recorded_engine_freshness_checkpoint(tmp_path: Path) -> None:
    policy = PolicyStore(tmp_path).load_active()
    case = RecordedTrajectoryCase(
        case_id="trajectory:stale-engine",
        profile="momentum_analyst",
        capability=MomentumCapability.ENGINE_FRESHNESS,
        required_overlay_terms=["explicit as-of"],
        required_task_terms=["do not retry"],
        required_tools=["engine_query"],
    )
    result = evaluate_trajectory_case(policy, case)
    assert result.passed is False
    assert set(result.failures) == {"overlay:explicit as-of", "task:do not retry", "tool:engine_query"}


def test_matching_policy_passes_recorded_checkpoint(tmp_path: Path) -> None:
    base = PolicyStore(tmp_path).load_active()
    policy = merge_policy_patch(
        base,
        PolicyPatch(
            prompt_overlays={"momentum_analyst": "Use an explicit as-of date."},
            task_templates={MomentumCapability.ENGINE_FRESHNESS: "Do not retry the failed call."},
            tool_policies=[
                ToolPolicy(
                    profile="momentum_analyst",
                    capability=MomentumCapability.ENGINE_FRESHNESS,
                    preferred_tools=["engine_query"],
                )
            ],
        ),
        trigger_ids=["trajectory:stale-engine"],
    )
    case = RecordedTrajectoryCase(
        case_id="trajectory:stale-engine",
        profile="momentum_analyst",
        capability=MomentumCapability.ENGINE_FRESHNESS,
        required_overlay_terms=["explicit as-of"],
        required_task_terms=["do not retry"],
        required_tools=["engine_query"],
    )
    result = evaluate_trajectory_case(policy, case)
    assert result.passed is True
    assert result.score == 1.0
```

- [ ] **Step 2: Add comparator tests for target fixes, ties, and regressions**

```python
def test_promotion_requires_target_fix_and_zero_regressions() -> None:
    baseline = SuiteResult.from_bools({"target": False, "guard": True})
    improved = SuiteResult.from_bools({"target": True, "guard": True})
    decision = compare_for_promotion(baseline, improved, trigger_ids={"target"})
    assert decision.promote is True
    assert decision.target_fixes == ["target"]


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        ({"target": False, "guard": True}, "no triggering case was fixed"),
        ({"target": True, "guard": False}, "regressed: guard"),
    ],
)
def test_promotion_rejects_ties_and_per_case_regressions(candidate, reason) -> None:
    baseline = SuiteResult.from_bools({"target": False, "guard": True})
    decision = compare_for_promotion(
        baseline,
        SuiteResult.from_bools(candidate),
        trigger_ids={"target"},
    )
    assert decision.promote is False
    assert reason in decision.reason
```

- [ ] **Step 3: Run tests and verify missing suite symbols**

Run: `uv run pytest tests/test_policy_suite.py -q`

Expected: FAIL during collection because `eval.policy_suite` does not exist.

- [ ] **Step 4: Implement the provider and deterministic case runner**

Use these contracts:

```python
class EvalCaseProvider(Protocol):
    def load(self) -> list[RecordedTrajectoryCase]: ...


class CaseResult(BaseModel):
    case_id: str
    layer: Literal["engine", "trajectory"]
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    failures: list[str] = Field(default_factory=list)


class SuiteResult(BaseModel):
    cases: list[CaseResult]

    @property
    def aggregate_score(self) -> float:
        return sum(case.score for case in self.cases) / len(self.cases) if self.cases else 1.0


def evaluate_policy(
    policy: ResearchPolicy,
    *,
    engine_results: list[CaseResult],
    trajectory_cases: list[RecordedTrajectoryCase],
) -> SuiteResult: ...
```

`RecordedTrajectoryCase` contains `case_id`, `profile`, `capability`, `observation`, `required_overlay_terms`, `forbidden_overlay_terms`, `required_task_terms`, and `required_tools`; all list fields default to empty lists. Term matching is normalized lowercase substring matching. Forbidden terms fail when present. A tool checkpoint passes when the required tool appears in the matching profile/capability `ToolPolicy.required_tools` or `preferred_tools`. Engine results are invariant guard cases included unchanged in both baseline and candidate suites.

Add at least three fixture cases: explicit-as-of handling for `engine_freshness`, primary-source handling for `source_quality`, and crowding evidence requiring `web_search`. Fixtures contain recorded observation excerpts for candidate context but assertions use only explicit checkpoint fields.

Add `engine_case_results(results: list[dict[str, Any]]) -> list[CaseResult]` to `momentum_eval.py`, mapping each existing result to an engine-layer `CaseResult` without changing `run_eval`, gap writeback, or `--eval` semantics.

- [ ] **Step 5: Run suite and existing eval tests**

Run: `uv run pytest tests/test_policy_suite.py tests/test_momentum_eval.py -q`

Expected: all tests pass and no test calls DeepSeek or web search.

- [ ] **Step 6: Commit the layered offline suite**

```bash
git add src/momentum_research_agent/eval/policy_suite.py src/momentum_research_agent/eval/fixtures/trajectory_cases.json src/momentum_research_agent/eval/momentum_eval.py tests/test_policy_suite.py tests/test_momentum_eval.py
git commit -m "feat: add layered offline policy evaluation"
```

---

### Task 4: Constrained Candidate Generator

**Files:**
- Create: `src/momentum_research_agent/eval/policy_improver.py`
- Create: `tests/test_policy_improver.py`

**Interfaces:**
- Consumes: `PolicyPatch`, `ResearchPolicy`, `merge_policy_patch`, `RecordedTrajectoryCase`, and `SuiteResult`.
- Produces: `FailureBundle`, `CandidateGenerator`, `LLMCandidateGenerator.generate(bundle)`, and `build_failure_bundle`.

- [ ] **Step 1: Write tests with a fake generator and fake OpenAI response**

```python
class FakeGenerator:
    def __init__(self, patch: PolicyPatch) -> None:
        self.patch = patch
        self.calls = 0

    async def generate(self, bundle: FailureBundle) -> PolicyPatch:
        self.calls += 1
        return self.patch


class FakeCompletions:
    def __init__(self, text: str) -> None:
        self.text = text
        self.call_count = 0
        self.last_kwargs: dict = {}

    async def create(self, **kwargs):
        self.call_count += 1
        self.last_kwargs = kwargs
        message = SimpleNamespace(content=self.text)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def fake_client(text: str):
    completions = FakeCompletions(text)
    return SimpleNamespace(
        chat=SimpleNamespace(completions=completions),
        completions=completions,
    )


def one_failure_bundle(tmp_path: Path) -> FailureBundle:
    return FailureBundle(
        active_policy=PolicyStore(tmp_path).load_active(),
        failed_case_ids=["trajectory:stale-engine"],
        case_failures={"trajectory:stale-engine": ["overlay:explicit as-of"]},
        recorded_observations={"trajectory:stale-engine": "engine_query used no end date"},
    )


@pytest.mark.asyncio
async def test_generator_is_called_once_with_only_failed_cases(tmp_path: Path) -> None:
    bundle = build_failure_bundle(
        active=PolicyStore(tmp_path).load_active(),
        suite=SuiteResult.from_bools({"trajectory:stale-engine": False}),
        trajectory_cases=[
            RecordedTrajectoryCase(
                case_id="trajectory:stale-engine",
                profile="momentum_analyst",
                capability=MomentumCapability.ENGINE_FRESHNESS,
                required_overlay_terms=["explicit as-of"],
                observation="engine_query used no end date",
            )
        ],
    )
    generator = FakeGenerator(
        PolicyPatch(
            task_templates={MomentumCapability.ENGINE_FRESHNESS: "Use an explicit end date."}
        )
    )
    patch = await generator.generate(bundle)
    assert generator.calls == 1
    assert bundle.failed_case_ids == ["trajectory:stale-engine"]
    assert patch.task_templates[MomentumCapability.ENGINE_FRESHNESS]


@pytest.mark.asyncio
async def test_llm_generator_rejects_non_schema_output(tmp_path: Path) -> None:
    client = fake_client('{"python_code": "print(1)"}')
    generator = LLMCandidateGenerator(client=client, model="deepseek-reasoner")
    with pytest.raises(ValidationError):
        await generator.generate(one_failure_bundle(tmp_path))
```

- [ ] **Step 2: Run tests and verify the module is missing**

Run: `uv run pytest tests/test_policy_improver.py -q`

Expected: FAIL during collection with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the constrained reflection request**

Use a protocol rather than a registry:

```python
class CandidateGenerator(Protocol):
    async def generate(self, bundle: FailureBundle) -> PolicyPatch: ...


class FailureBundle(BaseModel):
    active_policy: ResearchPolicy
    failed_case_ids: list[str]
    case_failures: dict[str, list[str]]
    verifier_gaps: list[GapEntry] = Field(default_factory=list)
    recorded_observations: dict[str, str] = Field(default_factory=dict)
```

The system prompt must state: return one JSON `PolicyPatch`; use only named research profiles, capabilities, and currently allowlisted tools; do not emit Python, shell, new tools, verifier instructions, or markdown. Include the exact JSON schema generated by `PolicyPatch.model_json_schema()`.

Call `client.chat.completions.create` once with `temperature=0`, parse with `parse_model_json(PolicyPatch, text)`, then call `validate_policy`. No retry loop is added. `build_failure_bundle` includes only failed case checkpoints and truncates each stored observation to 1,000 characters.

- [ ] **Step 4: Add timeout and single-call tests**

```python
@pytest.mark.asyncio
async def test_llm_generator_has_one_bounded_call(tmp_path: Path) -> None:
    client = fake_client(
        '{"prompt_overlays":{"momentum_analyst":"Use explicit dates."},'
        '"task_templates":{},"tool_policies":[]}'
    )
    generator = LLMCandidateGenerator(client=client, model="deepseek-reasoner", timeout_s=20)
    await generator.generate(one_failure_bundle(tmp_path))
    assert client.completions.call_count == 1
    assert client.completions.last_kwargs["temperature"] == 0
    assert client.completions.last_kwargs["timeout"] == 20
```

- [ ] **Step 5: Run focused tests**

Run: `uv run pytest tests/test_policy_improver.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit candidate generation**

```bash
git add src/momentum_research_agent/eval/policy_improver.py tests/test_policy_improver.py
git commit -m "feat: generate constrained policy candidates"
```

---

### Task 5: One-Cycle Evaluation and Promotion Orchestrator

**Files:**
- Modify: `src/momentum_research_agent/eval/policy_improver.py`
- Modify: `tests/test_policy_improver.py`

**Interfaces:**
- Consumes: `CandidateGenerator`, `PolicyStore`, `evaluate_policy`, `compare_for_promotion`, `merge_policy_patch`, and deterministic engine results.
- Produces: `ImprovementOutcome` and `run_improvement_cycle(project_root, generator, engine_results, provider)`.

- [ ] **Step 1: Write end-to-end promotion and rejection tests**

Use explicit local fakes and fixtures:

```python
class FakeProvider:
    def __init__(self, cases: list[RecordedTrajectoryCase]) -> None:
        self.cases = cases

    def load(self) -> list[RecordedTrajectoryCase]:
        return self.cases


class RaisingGenerator:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def generate(self, bundle: FailureBundle) -> PolicyPatch:
        raise self.error


def passing_engine_results() -> list[CaseResult]:
    return [CaseResult(case_id="engine:dm-normal", layer="engine", passed=True, score=1.0)]


def stale_engine_case() -> RecordedTrajectoryCase:
    return RecordedTrajectoryCase(
        case_id="trajectory:stale-engine",
        profile="momentum_analyst",
        capability=MomentumCapability.ENGINE_FRESHNESS,
        observation="engine_query was called without an explicit end date",
        required_overlay_terms=["explicit as-of"],
    )


def passing_guard_case() -> RecordedTrajectoryCase:
    return RecordedTrajectoryCase(
        case_id="trajectory:source-guard",
        profile="momentum_analyst",
        capability=MomentumCapability.SOURCE_QUALITY,
        observation="primary evidence must remain required",
        forbidden_overlay_terms=["skip primary evidence"],
    )


def fixing_patch() -> PolicyPatch:
    return PolicyPatch(
        prompt_overlays={"momentum_analyst": "Use an explicit as-of date."}
    )


def regressing_patch() -> PolicyPatch:
    return PolicyPatch(
        prompt_overlays={
            "momentum_analyst": "Use an explicit as-of date; skip primary evidence."
        }
    )
```

```python
@pytest.mark.asyncio
async def test_cycle_promotes_one_candidate_that_fixes_target_without_regression(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path)
    baseline_id = store.load_active().version_id
    generator = FakeGenerator(fixing_patch())
    outcome = await run_improvement_cycle(
        tmp_path,
        generator=generator,
        engine_results=passing_engine_results(),
        provider=FakeProvider([stale_engine_case(), passing_guard_case()]),
    )
    assert outcome.status == "promoted"
    assert outcome.previous_version_id == baseline_id
    assert store.load_active().version_id == outcome.candidate_version_id
    assert generator.calls == 1


@pytest.mark.asyncio
async def test_cycle_rejects_regression_and_keeps_active_pointer(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path)
    baseline_id = store.load_active().version_id
    outcome = await run_improvement_cycle(
        tmp_path,
        generator=FakeGenerator(regressing_patch()),
        engine_results=passing_engine_results(),
        provider=FakeProvider([stale_engine_case(), passing_guard_case()]),
    )
    assert outcome.status == "rejected"
    assert store.load_active().version_id == baseline_id
    assert (store.experiments_dir / f"{outcome.experiment_id}.json").exists()
```

- [ ] **Step 2: Add no-failure and generator-error tests**

```python
@pytest.mark.asyncio
async def test_cycle_skips_generation_when_baseline_passes(tmp_path: Path) -> None:
    generator = FakeGenerator(fixing_patch())
    outcome = await run_improvement_cycle(
        tmp_path,
        generator=generator,
        engine_results=passing_engine_results(),
        provider=FakeProvider([passing_guard_case()]),
    )
    assert outcome.status == "no_change"
    assert generator.calls == 0


@pytest.mark.asyncio
async def test_generator_error_fails_closed(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path)
    baseline_id = store.load_active().version_id
    outcome = await run_improvement_cycle(
        tmp_path,
        generator=RaisingGenerator(RuntimeError("model unavailable")),
        engine_results=passing_engine_results(),
        provider=FakeProvider([stale_engine_case()]),
    )
    assert outcome.status == "error"
    assert "model unavailable" in outcome.reason
    assert store.load_active().version_id == baseline_id
```

- [ ] **Step 3: Run the new tests and verify orchestration is absent**

Run: `uv run pytest tests/test_policy_improver.py -q`

Expected: FAIL because `run_improvement_cycle` and `ImprovementOutcome` are not defined.

- [ ] **Step 4: Implement exactly one improvement attempt**

Use this outcome contract:

```python
class ImprovementOutcome(BaseModel):
    status: Literal["promoted", "rejected", "no_change", "error"]
    previous_version_id: str
    candidate_version_id: str | None = None
    experiment_id: str | None = None
    reason: str
    baseline: SuiteResult
    candidate: SuiteResult | None = None
```

Algorithm:

1. Load or create the active policy.
2. Load trajectory cases and evaluate the baseline with supplied engine guard results.
3. Return `no_change` without calling the generator when the baseline has no failures.
4. Build one failure bundle and await one `generator.generate` call.
5. Validate and merge the patch into one candidate.
6. Evaluate the candidate against the identical engine results and trajectory cases.
7. Compare per-case outcomes using all baseline failures as trigger IDs.
8. Write one experiment record containing baseline, candidate, and decision.
9. On success, attach `PolicyEvaluation`, write the immutable candidate version, render compatibility hints, then atomically activate it.
10. On rejection or any exception, leave the active pointer unchanged.

Do not recurse, retry generation, or produce a second candidate.

- [ ] **Step 5: Run focused tests**

Run: `uv run pytest tests/test_policy_improver.py tests/test_policy_suite.py tests/test_policies.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit the promotion cycle**

```bash
git add src/momentum_research_agent/eval/policy_improver.py tests/test_policy_improver.py
git commit -m "feat: promote non-regressing policy improvements"
```

---

### Task 6: CLI Integration, Documentation, and Full Verification

**Files:**
- Modify: `src/momentum_research_agent/cli.py`
- Modify: `tests/test_momentum_eval.py`
- Modify: `README.md`
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: `run_eval`, `engine_case_results`, `LLMCandidateGenerator`, `FileEvalCaseProvider`, and `run_improvement_cycle`.
- Produces: `momentum-research-agent --improve` while preserving `--eval` behavior.

- [ ] **Step 1: Write parser and command-path tests**

```python
def test_improve_flag_is_explicit_and_separate_from_eval() -> None:
    parser = build_parser()
    assert parser.parse_args(["--eval"]).run_eval is True
    assert parser.parse_args(["--eval"]).improve is False
    assert parser.parse_args(["--improve"]).improve is True


@pytest.mark.asyncio
async def test_eval_never_constructs_llm_candidate_generator(monkeypatch) -> None:
    monkeypatch.setattr(cli, "run_eval", AsyncMock(return_value=[]), raising=False)
    make_client = Mock(side_effect=AssertionError("--eval must not create a client"))
    monkeypatch.setattr(cli, "make_client", make_client)
    assert await cli.async_main(build_parser().parse_args(["--eval"])) == 0
    make_client.assert_not_called()


@pytest.mark.asyncio
async def test_improve_runs_eval_then_one_cycle(monkeypatch) -> None:
    engine_result = {
        "case_id": "dm-2026-05-29",
        "ok": True,
        "payload": {"pipeline_run": True},
        "error": None,
        "gaps": [],
    }
    outcome = ImprovementOutcome(
        status="promoted",
        previous_version_id="baseline",
        candidate_version_id="candidate",
        reason="fixed trajectory:stale-engine",
        baseline=SuiteResult.from_bools({"trajectory:stale-engine": False}),
        candidate=SuiteResult.from_bools({"trajectory:stale-engine": True}),
    )
    run_eval = AsyncMock(return_value=[engine_result])
    improve = AsyncMock(return_value=outcome)
    monkeypatch.setattr(cli, "run_eval", run_eval, raising=False)
    monkeypatch.setattr(cli, "run_improvement_cycle", improve, raising=False)
    assert await cli.async_main(build_parser().parse_args(["--improve"])) == 0
    run_eval.assert_awaited_once()
    improve.assert_awaited_once()
```

- [ ] **Step 2: Run CLI tests and verify `--improve` is unknown**

Run: `uv run pytest tests/test_momentum_eval.py -q`

Expected: FAIL because the parser has no `--improve` option.

- [ ] **Step 3: Add the explicit improvement command**

Add:

```python
parser.add_argument(
    "--improve",
    action="store_true",
    help="Run the layered offline suite and attempt one constrained policy promotion.",
)
```

Reject `--eval --improve` together with exit code 2. `--improve` performs this sequence:

1. Run the existing deterministic engine eval once.
2. Convert its results to engine guard cases.
3. Construct the client only for candidate generation.
4. Run one improvement cycle with `LLMCandidateGenerator` and `FileEvalCaseProvider`.
5. Print baseline failures, candidate result, active version, and the rejection or error reason.

Return 0 for `promoted` or `no_change`, 1 for `rejected` or `error`, and 2 for a missing API key. The engine eval may write its existing gap rows; policy promotion does not change that ledger contract.

- [ ] **Step 4: Document runtime boundaries and artifacts**

Update README usage with:

```bash
uv run momentum-research-agent --eval       # deterministic; no DeepSeek
uv run momentum-research-agent --improve    # at most one candidate
```

Add `reports/policies/active.json`, `versions/`, and `experiments/` to the artifact table. Explain that policy can guide only research prompts, gap-task additions, and already-authorized tool selection. State that the verifier never loads it and that live LLM/data evaluation plus staged replanning are outside this phase.

Update AGENTS.md with the same authorization boundary and the rule that policy is loaded once at run start and is never promoted during an active research run.

- [ ] **Step 5: Run formatting-independent checks and the complete suite**

Run:

```bash
uv run pytest -q
git diff --check
```

Expected: all tests pass and `git diff --check` emits no output.

- [ ] **Step 6: Run both CLI smoke paths**

Run:

```bash
uv run momentum-research-agent --help
uv run momentum-research-agent --eval
```

Expected: help lists both commands; `--eval` completes without constructing a DeepSeek client. If the pinned engine fixture cannot execute on the machine, record the exact infrastructure error and confirm it becomes the existing eval gap without changing the active policy.

- [ ] **Step 7: Commit the integrated loop**

```bash
git add src/momentum_research_agent/cli.py tests/test_momentum_eval.py README.md AGENTS.md
git commit -m "feat: expose controlled policy improvement cycle"
```

- [ ] **Step 8: Verify repository state and commit history**

Run:

```bash
git status --short --branch
git log -8 --oneline --decorate
```

Expected: no uncommitted implementation changes, the branch is ahead of `origin/main`, and the task commits appear after the approved design and plan commits.
