"""Actual bounded ReAct research against evaluation-only frozen tool adapters."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from momentum_research_agent.agents.audit import merge_verification, static_audit
from momentum_research_agent.agents.budget import LoopBudget
from momentum_research_agent.agents.ledger import finalize_ledger
from momentum_research_agent.agents.react_loop import react_loop_detailed
from momentum_research_agent.agents.sub_agent import (
    _bind_report,
    _report_instructions,
    load_profile,
)
from momentum_research_agent.agents.verifier import (
    _guard_source_discovery,
    _instructions,
)
from momentum_research_agent.coordinator.task_board import TaskBoard
from momentum_research_agent.eval.research_world import (
    FrozenResearchWorld,
    FrozenWorldAdapter,
)
from momentum_research_agent.models.schemas import (
    ReplayHint,
    ResearchReport,
    ToolTrace,
    UsageSummary,
    VerificationReport,
    VerificationStatus,
    parse_model_json,
    extract_json_text,
)
from momentum_research_agent.research_contract import ground_report
from momentum_research_agent.state.policies import (
    ResearchPolicy,
    _expected_version_id,
    compiled_overlay,
)
from momentum_research_agent.state.reports import (
    persist_research_report,
    persist_verification_report,
)
from momentum_research_agent.state.traces import append_traces
from momentum_research_agent.tools import (
    authorize_research_tools,
    authorize_tools,
    resolve_tools,
)


class ArenaControls(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    temperature: float = Field(default=0, ge=0, le=2, allow_inf_nan=False)
    max_turns: int = Field(default=8, ge=1, le=16, strict=True)
    max_llm_requests: int = Field(default=28, ge=1, le=64, strict=True)
    max_output_tokens: int = Field(default=2048, ge=128, le=8192, strict=True)
    max_total_tokens: int = Field(default=250000, ge=512, le=1000000, strict=True)
    max_tool_calls: int = Field(default=32, ge=1, le=128, strict=True)
    overall_deadline_s: float = Field(default=180, gt=0, le=600, allow_inf_nan=False)
    llm_timeout_s: float = Field(default=20, gt=0, le=60, allow_inf_nan=False)
    tool_timeout_s: float = Field(default=10, gt=0, le=30, allow_inf_nan=False)
    # Legacy controls omitted this field and had no repair opportunity.
    max_schema_repairs: int = Field(default=0, ge=0, le=1, strict=True)


class ArenaPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: str
    subquestion: str = Field(max_length=4000)
    replan: bool = False


class ArenaReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    replan: bool
    profile: str | None = None
    subquestion: str | None = Field(default=None, max_length=4000)
    rationale: str | None = Field(default=None, max_length=2000)


class ArenaRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    world_id: str
    world_hash: str
    policy_version_id: str
    requested_model: str
    response_model_ids: list[str] = Field(default_factory=list)
    controls: ArenaControls
    profile_hashes: dict[str, str] = Field(default_factory=dict)
    completion_status: Literal["complete", "failed"] = "failed"
    reasons: list[str] = Field(default_factory=list)
    reports: list[ResearchReport] = Field(default_factory=list)
    submitted_reports: list[ResearchReport] = Field(default_factory=list)
    verification: VerificationReport | None = None
    verifier_completed: bool = False
    traces: list[ToolTrace] = Field(default_factory=list)
    usage: UsageSummary = Field(default_factory=UsageSummary)
    llm_requests: int = 0
    tool_calls: int = 0
    latency_ms: int = 0
    schema_repair_requests: int = Field(default=0, ge=0, le=1)
    budget_tokens_reserved: int = 0


def write_artifact(path: Path, value: Any) -> None:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def profile_snapshot(
    project_root: Path, worlds: list[FrozenResearchWorld]
) -> dict[str, str]:
    names = {"verifier"} | {p for w in worlds for p in w.allowed_profiles}
    texts = {
        p: load_profile(p, project_root, apply_overlay=False) for p in sorted(names)
    }
    texts["arena_research"] = (
        Path(__file__).with_name("arena_research.md").read_text(encoding="utf-8")
    )
    texts["arena_verification"] = (
        Path(__file__).with_name("arena_verification.md").read_text(encoding="utf-8")
    )
    texts["source_reading"] = (
        Path(__file__).parents[1] / "agents" / "source_reading.md"
    ).read_text(encoding="utf-8")
    return texts


class _BoundedClient:
    """Reserve a conservative UTF-8 input ceiling before each external request."""

    def __init__(self, client: Any, run: ArenaRun, session_dir: Path):
        self.client = client.with_options(max_retries=0)
        self.run, self.session_dir = run, session_dir
        self.phase = "planning"
        self.phase_usage: dict[str, UsageSummary] = {}
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        controls = self.run.controls
        if self.run.llm_requests >= controls.max_llm_requests:
            raise ValueError("LLM request budget exhausted")
        # Byte-level upper bound plus framing reserve; output limited by max_tokens.
        input_ceiling = len(json.dumps(kwargs, ensure_ascii=False).encode()) + 4096
        reservation = input_ceiling + controls.max_output_tokens
        if self.run.budget_tokens_reserved + reservation > controls.max_total_tokens:
            raise ValueError("Total token budget exhausted")
        self.run.budget_tokens_reserved += reservation
        self.run.llm_requests += 1
        record = {"phase": self.phase, "request": kwargs, "reservation": reservation}
        with (self.session_dir / "requests.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        response = await self.client.chat.completions.create(**kwargs)
        model = getattr(response, "model", None) or "unknown"
        if model not in self.run.response_model_ids:
            self.run.response_model_ids.append(model)
        usage = getattr(response, "usage", None)
        if usage is None:
            raise ValueError("Missing model token usage")
        input_tokens = getattr(usage, "prompt_tokens", None)
        output_tokens = getattr(usage, "completion_tokens", None)
        if (
            not isinstance(input_tokens, int)
            or not isinstance(output_tokens, int)
            or min(input_tokens, output_tokens) < 0
        ):
            raise ValueError("Invalid model token usage")
        self.run.usage.add(model, input_tokens, output_tokens)
        self.phase_usage.setdefault(self.phase, UsageSummary()).add(
            model, input_tokens, output_tokens
        )
        choice = response.choices[0]
        record = {
            "phase": self.phase,
            "model": model,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
            "finish_reason": choice.finish_reason,
            "content": choice.message.content,
            "tool_calls": [
                {"name": c.function.name, "arguments": c.function.arguments}
                for c in (getattr(choice.message, "tool_calls", None) or [])
            ],
        }
        with (self.session_dir / "responses.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        if input_tokens > input_ceiling or output_tokens > controls.max_output_tokens:
            raise ValueError("Provider exceeded reserved token bound")
        return response


async def run_world(
    *,
    client: Any,
    requested_model: str,
    project_root: Path,
    world: FrozenResearchWorld,
    policy: ResearchPolicy,
    session_dir: Path,
    controls: ArenaControls,
    profiles: dict[str, str] | None = None,
) -> ArenaRun:
    """Independent plan → research → optional replan → verifier, no active policy IO."""
    session_dir = Path(session_dir)
    session_dir.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    run = ArenaRun(
        world_id=world.world_id,
        world_hash=world.content_hash,
        policy_version_id=policy.version_id,
        requested_model=requested_model,
        controls=controls.model_copy(deep=True),
    )
    board = TaskBoard(session_dir, question=world.research_question)
    active_task = None
    try:
        if policy.version_id != _expected_version_id(policy):
            raise ValueError("Invalid policy content hash")
        public = world.public_world()
        # Only the detached public world ever reaches adapters, agent or verifier.
        adapter = FrozenWorldAdapter(public)
        profiles = dict(profiles or profile_snapshot(project_root, [world]))
        run.profile_hashes = {
            name: hashlib.sha256(text.encode()).hexdigest()
            for name, text in profiles.items()
        }
        write_artifact(session_dir / "policy_snapshot.json", policy)
        write_artifact(session_dir / "public_world.json", public)
        write_artifact(session_dir / "profiles.json", profiles)
        bounded = _BoundedClient(client, run, session_dir)
        phase_tools: dict[str, int] = {}
        controls = run.controls
        loop_budget = LoopBudget(
            max_turns=controls.max_turns,
            overall_deadline_s=controls.overall_deadline_s,
            llm_timeout_s=controls.llm_timeout_s,
            tool_timeout_s=controls.tool_timeout_s,
        )
        public_input = json.dumps(
            {
                "question": world.research_question,
                "as_of": world.as_of,
                "allowed_profiles": world.allowed_profiles,
                "allowed_tools": world.allowed_tools,
                "delivery_contract": world.delivery_contract,
            },
            ensure_ascii=False,
        )
        # Policy guidance is research-only; capability labels/targets never enter prompts.
        guidance = json.dumps(
            {
                "profile_guidance": {
                    p: compiled_overlay(policy, p) for p in world.allowed_profiles
                },
                "task_guidance": list(policy.task_templates.values()),
            }
        )
        research_rules = profiles["arena_research"]

        async def loop(phase, system, user, profile=None, *, one_turn=False):
            bounded.phase = phase
            tools, registry = [], {}
            if profile:
                allowed = (
                    authorize_tools(profile)
                    if profile == "verifier"
                    else authorize_research_tools(profile)
                )
                names = [name for name in world.allowed_tools if name in allowed]
                tools, _ = resolve_tools(names)
                tools = deepcopy(tools)
                for definition in tools:
                    if definition["function"]["name"] == "engine_query":
                        definition["function"]["description"] = (
                            "Read the frozen deterministic scenario engine observation. Simulation only."
                        )
                        definition["function"]["parameters"] = {
                            "type": "object",
                            "properties": {
                                "end": {
                                    "type": "string",
                                    "description": "Frozen as-of date YYYY-MM-DD; omit to use the scenario date.",
                                }
                            },
                            "additionalProperties": False,
                        }

                def bind_frozen_tool(name):
                    async def frozen_tool(**arguments):
                        if run.tool_calls >= controls.max_tool_calls:
                            raise ValueError("Tool budget exhausted")
                        return adapter.call(name, arguments)

                    return frozen_tool

                registry = {name: bind_frozen_tool(name) for name in names}

            def record(name, args, observation):
                run.tool_calls += 1
                phase_tools[phase] = phase_tools.get(phase, 0) + 1
                if name not in registry or run.tool_calls > controls.max_tool_calls:
                    raise ValueError("Unauthorized tool or tool budget exceeded")
                trace = ToolTrace(
                    tool=name,
                    arguments=args,
                    observation=observation,
                    observation_sha256=hashlib.sha256(observation.encode()).hexdigest(),
                    agent_role=profile,
                    agent_id="verifier" if profile == "verifier" else phase,
                    replay=ReplayHint(method="stored_observation"),
                )
                run.traces.append(trace)
                append_traces(session_dir, [trace])

            outcome = await react_loop_detailed(
                client=bounded,
                model=requested_model,
                system_prompt=system,
                user_message=user,
                tools=tools,
                tool_registry=registry,
                on_tool_call=record,
                budget=replace(loop_budget, max_turns=1) if one_turn else loop_budget,
                max_output_tokens=controls.max_output_tokens,
                temperature=controls.temperature,
            )
            if not outcome.completed:
                raise ValueError(f"{phase} incomplete: {outcome.stop_reason}")
            return outcome.text

        async with asyncio.timeout(controls.overall_deadline_s):
            plan = parse_model_json(
                ArenaPlan,
                await loop(
                    "planning",
                    research_rules + "\n" + guidance,
                    public_input
                    + "\nCurrent stage: initial planning. Choose the research assignment "
                    "only; tools become available in the next stage. Return one JSON "
                    "object with string fields profile and subquestion, without tool "
                    "calls, prose, or findings.",
                ),
            )
            for index in range(1, 3):
                if (
                    plan.profile not in world.allowed_profiles
                    or not plan.subquestion.strip()
                ):
                    raise ValueError("Invalid research plan")
                active_task = board.add_task(
                    title="Frozen momentum investigation",
                    assignment=public_input
                    + "\nChosen subproblem: "
                    + plan.subquestion,
                    profile=plan.profile,
                    task_id=f"research-{index}",
                    kind="research" if index == 1 else "replan",
                )
                board.activate(active_task.id)
                system = (
                    profiles[plan.profile]
                    + "\n"
                    + compiled_overlay(policy, plan.profile)
                    + "\n"
                    + research_rules
                    + "\n"
                    + profiles["source_reading"]
                    + "\n"
                    + guidance
                )
                raw = await loop(
                    active_task.id,
                    system,
                    _report_instructions(active_task),
                    plan.profile,
                )
                try:
                    parsed = parse_model_json(ResearchReport, raw)
                except ValidationError as exc:
                    errors = exc.errors(include_url=False, include_input=False)
                    paths = [e["loc"] for e in errors]
                    eligible = bool(paths) and all(
                        e["type"] == "enum"
                        and len(e["loc"]) == 3
                        and e["loc"][0] == "findings"
                        and isinstance(e["loc"][1], int)
                        and e["loc"][2] in {"category", "stance"}
                        for e in errors
                    )
                    if not eligible or run.schema_repair_requests >= controls.max_schema_repairs:
                        raise
                    original = json.loads(extract_json_text(raw))
                    run.schema_repair_requests += 1
                    repaired = await loop(
                        active_task.id,
                        system,
                        "Current stage: enum-only report repair. Correct only the "
                        "invalid finding category/stance fields identified below. "
                        "Return the complete JSON object with every other key and "
                        "value unchanged. Do not add/drop findings, rewrite claims, "
                        "or call tools. This is the run's only repair request.\n"
                        + json.dumps({"validation_errors": errors, "report": original,
                                      "schema": ResearchReport.model_json_schema()}),
                        one_turn=True,
                    )
                    revised = json.loads(extract_json_text(repaired))
                    before, after = deepcopy(original), deepcopy(revised)
                    for _, finding_index, field in paths:
                        before["findings"][finding_index][field] = None
                        after["findings"][finding_index][field] = None
                    if json.dumps(before, sort_keys=True) != json.dumps(after, sort_keys=True):
                        raise ValueError("Schema repair changed non-enum report content")
                    parsed = parse_model_json(ResearchReport, repaired)
                report = _bind_report(active_task, parsed)
                run.submitted_reports.append(report.model_copy(deep=True))
                report = ground_report(
                    report, [t for t in run.traces if t.agent_id == active_task.id]
                )
                run.reports.append(report)
                persist_research_report(session_dir, active_task, report)
                board.complete(active_task.id, report.summary)
                board.record_usage(
                    active_task.id,
                    tool_calls=phase_tools.get(active_task.id, 0),
                    tokens_used=bounded.phase_usage.get(
                        active_task.id, UsageSummary()
                    ).total_tokens,
                )
                active_task = None
                if index == 2:
                    break
                review = (
                    public_input
                    + "\nReview the evidence and choose whether one replan is necessary.\n"
                    + report.model_dump_json()
                    + "\nCurrent stage: review. Return one JSON object with replan "
                    "(boolean). If true, include profile and subquestion for the next "
                    "investigation; if false, those fields may be null or omitted. "
                    "An optional rationale string (at most 2000 characters) may "
                    "explain the decision. No other fields are accepted. "
                    "Tools are unavailable during this decision stage."
                )
                decision = parse_model_json(
                    ArenaReview,
                    await loop("review", research_rules + "\n" + guidance, review),
                )
                if not decision.replan:
                    break
                plan = ArenaPlan(
                    profile=decision.profile,
                    subquestion=decision.subquestion,
                    replan=True,
                )

            static = static_audit(world.research_question, run.reports)
            # Always request terminal independent verification, including withholding runs.
            raw = await loop(
                "verifier",
                profiles["verifier"] + "\n" + profiles["arena_verification"],
                _instructions(world.research_question, run.reports, static),
                "verifier",
            )
            independent = parse_model_json(VerificationReport, raw)
            ids = [v.evidence_id for v in independent.verdicts]
            existing = {e.id for r in run.reports for e in r.findings}
            if len(ids) != len(set(ids)) or set(ids) - existing:
                raise ValueError("Verifier returned duplicate or unknown evidence IDs")
            merged = merge_verification(static, independent, world.research_question)
            for verdict in merged.verdicts:
                if verdict.evidence_id not in ids:
                    verdict.status = VerificationStatus.UNCHECKED
                    verdict.issues.append("No terminal independent verdict")
            _guard_source_discovery(merged, run.reports, run.traces)
            run.verification = finalize_ledger(merged, run.reports, run.traces)
            persist_verification_report(session_dir, run.verification)
            run.verifier_completed = True
            if world.content_hash != run.world_hash:
                raise ValueError("World mutated during run")
            if len(run.response_model_ids) != 1 or "unknown" in run.response_model_ids:
                raise ValueError("Model resolution ambiguous")
            run.completion_status = "complete"
    except asyncio.CancelledError:
        run.reasons.append("cancelled")
        raise
    except Exception as exc:  # noqa: BLE001 -- external runtime errors must persist a failed run
        run.reasons.append(f"{type(exc).__name__}: {exc}")
    finally:
        if active_task is not None:
            board.fail(active_task.id, "; ".join(run.reasons) or "interrupted")
        run.latency_ms = round((time.monotonic() - started) * 1000)
        write_artifact(session_dir / "run.json", run)
    return run
