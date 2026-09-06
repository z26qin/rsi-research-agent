"""Bounded ReAct execution against validated, read-only stored observations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from momentum_research_agent.agents.budget import LoopBudget
from momentum_research_agent.agents.react_loop import react_loop_detailed
from momentum_research_agent.agents.sub_agent import (
    _bind_report,
    _report_instructions,
    load_profile,
)
from momentum_research_agent.eval.session_cases import (
    REPLAYABLE_TOOLS,
    SessionEvalCase,
)
from momentum_research_agent.models.schemas import ResearchReport, Task, UsageSummary, parse_model_json
from momentum_research_agent.state.policies import (
    ResearchPolicy,
    compiled_overlay,
    task_template_addition,
)
from momentum_research_agent.tools import authorize_research_tools
from momentum_research_agent.tools.registry import resolve_tools


class LLMRequestBudgetExceeded(RuntimeError):
    pass


@dataclass
class LLMRequestBudget:
    max_attempts: int
    attempts: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.max_attempts, int) or isinstance(self.max_attempts, bool):
            raise ValueError("max_attempts must be a positive integer")
        if self.max_attempts <= 0:
            raise ValueError("max_attempts must be a positive integer")
        if (
            not isinstance(self.attempts, int)
            or isinstance(self.attempts, bool)
            or self.attempts < 0
            or self.attempts > self.max_attempts
        ):
            raise ValueError("attempts must be within the request budget")

    def claim(self) -> None:
        if self.attempts >= self.max_attempts:
            raise LLMRequestBudgetExceeded("LLM request budget exhausted")
        self.attempts += 1


class ReplayCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    arguments: dict[str, Any]
    canonical_arguments: str
    matched_trace_id: str | None = None
    observation_sha256: str | None = None
    result: str


class ReplayRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    case_sha256: str
    policy_version_id: str
    requested_model: str
    response_model_ids: list[str] = Field(default_factory=list)
    max_output_tokens: int
    completed: bool = False
    outcome: Literal["success", "unscorable", "failed"]
    reasons: list[str] = Field(default_factory=list)
    raw_output: str = ""
    report: ResearchReport | None = None
    calls: list[ReplayCall] = Field(default_factory=list)
    consumed_trace_ids: list[str] = Field(default_factory=list)
    usage: UsageSummary = Field(default_factory=UsageSummary)
    latency_ms: int = 0
    llm_requests: int = 0


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def case_content_sha256(case: SessionEvalCase) -> str:
    payload = _canonical_json(case.model_dump(mode="json"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_replay_registry(
    case: SessionEvalCase,
) -> tuple[list[dict[str, Any]], dict[str, Callable[..., str]], list[ReplayCall]]:
    """Build functions that can return only validated observations from ``case``."""
    if not case.replayable or case.replay_blockers:
        raise ValueError("case is not replayable")
    if not case.profile or not case.source_task_id or not case.task_input:
        raise ValueError("case lacks required replay bindings")

    indexed: dict[tuple[str, str], tuple[str, str, str]] = {}
    for trace in case.tool_traces:
        if trace.tool not in REPLAYABLE_TOOLS:
            raise ValueError("case contains unsupported replay tool")
        if trace.truncated or not trace.observation:
            raise ValueError("case contains invalid replay observation")
        actual_hash = hashlib.sha256(trace.observation.encode("utf-8")).hexdigest()
        if actual_hash != trace.observation_sha256:
            raise ValueError("case contains invalid replay observation")
        canonical = _canonical_json(trace.arguments)
        key = (trace.tool, canonical)
        prior = indexed.get(key)
        candidate = (trace.id, trace.observation, trace.observation_sha256)
        if prior is not None and prior[1:] != candidate[1:]:
            raise ValueError("conflicting replay observations for the same tool arguments")
        indexed.setdefault(key, candidate)

    tool_names = sorted({trace.tool for trace in case.tool_traces})
    authorize_research_tools(case.profile, tool_names)
    definitions, _live_registry = resolve_tools(tool_names)
    calls: list[ReplayCall] = []
    registry: dict[str, Callable[..., str]] = {}

    def make_replay_tool(tool_name: str) -> Callable[..., str]:
        def replay_tool(**arguments: Any) -> str:
            try:
                canonical = _canonical_json(arguments)
            except (TypeError, ValueError):
                calls.append(
                    ReplayCall(
                        tool=tool_name,
                        arguments={},
                        canonical_arguments="<invalid-json-arguments>",
                        result="REPLAY_UNAVAILABLE",
                    )
                )
                return "REPLAY_UNAVAILABLE"
            matched = indexed.get((tool_name, canonical))
            if matched is None:
                calls.append(
                    ReplayCall(
                        tool=tool_name,
                        arguments=dict(arguments),
                        canonical_arguments=canonical,
                        result="REPLAY_UNAVAILABLE",
                    )
                )
                return "REPLAY_UNAVAILABLE"
            trace_id, observation, observation_hash = matched
            calls.append(
                ReplayCall(
                    tool=tool_name,
                    arguments=dict(arguments),
                    canonical_arguments=canonical,
                    matched_trace_id=trace_id,
                    observation_sha256=observation_hash,
                    result=observation,
                )
            )
            return observation

        return replay_tool

    for tool_name in tool_names:
        registry[tool_name] = make_replay_tool(tool_name)
    return definitions, registry, calls


def _system_prompt(
    project_root: Path,
    case: SessionEvalCase,
    policy: ResearchPolicy,
    base_profile_text: str | None,
) -> str:
    assert case.profile is not None
    base = base_profile_text
    if base is None:
        base = load_profile(case.profile, project_root, apply_overlay=False)
    overlay = compiled_overlay(policy, case.profile, case.capability)
    return f"{base.rstrip()}\n\n{overlay}\n" if overlay else base


def _task(case: SessionEvalCase, policy: ResearchPolicy) -> Task:
    addition = task_template_addition(policy, case.capability)
    assignment = case.task_input or ""
    if addition:
        assignment = f"{assignment.rstrip()}\n\nPolicy task guidance:\n{addition}"
    return Task(
        id=case.source_task_id or "replay-task",
        title=case.task_title or "Replay evaluation",
        assignment=assignment,
        profile=case.profile or "",
    )


async def run_replay_case(
    *,
    client: Any,
    requested_model: str,
    project_root: Path,
    case: SessionEvalCase,
    policy: ResearchPolicy,
    budget: LoopBudget,
    request_budget: LLMRequestBudget,
    max_output_tokens: int,
    temperature: float = 0.0,
    base_profile_text: str | None = None,
) -> ReplayRunResult:
    """Rerun one case without allowing any live tool execution."""
    if not isinstance(max_output_tokens, int) or isinstance(max_output_tokens, bool):
        raise ValueError("max_output_tokens must be a positive integer")
    if max_output_tokens <= 0:
        raise ValueError("max_output_tokens must be a positive integer")
    started = time.monotonic()
    case_hash = case_content_sha256(case)
    calls: list[ReplayCall] = []
    usage = UsageSummary()
    response_models: list[str] = []
    attempts_before = request_budget.attempts
    raw_output = ""
    report: ResearchReport | None = None
    completed = False
    outcome: Literal["success", "unscorable", "failed"] = "failed"
    reasons: list[str] = []

    try:
        if case.policy_version_id is None:
            raise ValueError("case has no source policy binding")
        definitions, registry, calls = build_replay_registry(case)
        task = _task(case, policy)
        observed_registry_calls = 0

        def record_response(response: Any) -> None:
            model_id = getattr(response, "model", None)
            response_models.append(str(model_id) if model_id else "unknown")

        def record_actual_call(name: str, arguments: dict[str, Any], _result: str) -> None:
            nonlocal observed_registry_calls
            if len(calls) > observed_registry_calls:
                observed_registry_calls = len(calls)
                return
            try:
                canonical = _canonical_json(arguments)
                safe_arguments = dict(arguments)
            except (TypeError, ValueError):
                canonical = "<invalid-json-arguments>"
                safe_arguments = {}
            calls.append(
                ReplayCall(
                    tool=name,
                    arguments=safe_arguments,
                    canonical_arguments=canonical,
                    result="REPLAY_UNAVAILABLE",
                )
            )
            observed_registry_calls = len(calls)

        bounded_client = client.with_options(max_retries=0)
        loop_result = await react_loop_detailed(
            client=bounded_client,
            model=requested_model,
            system_prompt=_system_prompt(
                Path(project_root), case, policy, base_profile_text
            ),
            user_message=_report_instructions(task),
            tools=definitions,
            tool_registry=registry,
            on_tool_call=record_actual_call,
            usage_tracker=usage,
            budget=budget,
            before_llm_request=request_budget.claim,
            on_llm_response=record_response,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
        )
        raw_output = loop_result.text
        completed = loop_result.completed
        if not loop_result.completed:
            reasons.append(
                "output_length_truncated"
                if loop_result.stop_reason == "length"
                else loop_result.stop_reason
            )
        else:
            try:
                report = _bind_report(task, parse_model_json(ResearchReport, raw_output))
            except ValidationError:
                reasons.append("malformed_research_report")
        if any(call.matched_trace_id is None for call in calls):
            reasons.append("unmatched_replay_call")
        if completed and report is not None and not reasons:
            outcome = "success"
        elif "unmatched_replay_call" in reasons:
            outcome = "unscorable"
    except asyncio.CancelledError:
        raise
    except LLMRequestBudgetExceeded:
        reasons = ["llm_request_budget_exhausted"]
    except Exception as exc:
        reasons = [f"replay_failed:{type(exc).__name__}"]

    return ReplayRunResult(
        case_id=case.case_id,
        case_sha256=case_hash,
        policy_version_id=policy.version_id,
        requested_model=requested_model,
        response_model_ids=response_models,
        max_output_tokens=max_output_tokens,
        completed=completed,
        outcome=outcome,
        reasons=reasons,
        raw_output=raw_output,
        report=report,
        calls=calls,
        consumed_trace_ids=list(
            dict.fromkeys(
                call.matched_trace_id for call in calls if call.matched_trace_id is not None
            )
        ),
        usage=usage,
        latency_ms=max(0, round((time.monotonic() - started) * 1000)),
        llm_requests=request_budget.attempts - attempts_before,
    )
