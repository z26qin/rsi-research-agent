from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from momentum_research_agent.agents.budget import LoopBudget
from momentum_research_agent.eval.replay_runner import (
    LLMRequestBudget,
    build_replay_registry,
    case_content_sha256,
    run_replay_case,
)
from momentum_research_agent.eval.session_cases import SessionEvalCase
from momentum_research_agent.models.schemas import (
    GapEntry,
    GapKind,
    MomentumCapability,
    ReplayHint,
    ToolTrace,
)
from momentum_research_agent.state.policies import (
    PolicyPatch,
    PolicyStore,
    ToolPolicy,
    merge_policy_patch,
)


def _case(tmp_path: Path, *, traces: list[ToolTrace] | None = None) -> SessionEvalCase:
    observation = json.dumps(
        {
            "results": [
                {
                    "url": "https://example.test/source",
                    "snippet": "Synthetic primary-source observation.",
                }
            ]
        }
    )
    trace = ToolTrace(
        id="trace-1",
        tool="web_search",
        arguments={"query": "synthetic replay"},
        observation=observation,
        observation_sha256=hashlib.sha256(observation.encode()).hexdigest(),
        agent_id="task-1",
        agent_role="flow_analyst",
        replay=ReplayHint(method="stored_observation", query="synthetic replay"),
    )
    policy = PolicyStore(tmp_path).load_active()
    selected = traces or [trace]
    return SessionEvalCase(
        case_id=(
            "session:synthetic:" + "a" * 64 + ":gap-1"
        ),
        source_session_id="synthetic",
        source_directory_sha256="a" * 64,
        source_question="Synthetic question",
        source_task_id="task-1",
        source_trace_ids=[item.id for item in selected],
        profile="flow_analyst",
        capability=MomentumCapability.SOURCE_QUALITY,
        task_title="Synthetic task",
        task_input="Use the synthetic replay observation.",
        failing_evidence=GapEntry(
            id="gap-1",
            kind=GapKind.UNCHECKED_EVIDENCE,
            claim="Synthetic claim",
            task_id="task-1",
            trace_ids=[item.id for item in selected],
        ),
        tool_traces=selected,
        source_artifact_hashes={"synthetic.json": "b" * 64},
        policy_version_id=policy.version_id,
        replayable=True,
    )


class FakeFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.id = call_id
        self.function = FakeFunction(name, arguments)


class FakeResponse:
    def __init__(self, message: object, *, finish_reason: str, model: str) -> None:
        self.choices = [SimpleNamespace(message=message, finish_reason=finish_reason)]
        self.usage = SimpleNamespace(prompt_tokens=11, completion_tokens=7)
        self.model = model


class FakeClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.retry_options: list[int] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def with_options(self, *, max_retries: int):
        self.retry_options.append(max_retries)
        return self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("unexpected request")
        return self.responses.pop(0)


def _message(content: str | None = None, tool_calls: list | None = None) -> object:
    return SimpleNamespace(content=content, tool_calls=tool_calls or [])


@pytest.mark.asyncio
async def test_replay_runs_actual_loop_with_canonical_argument_match_and_pinned_policy(
    tmp_path: Path,
) -> None:
    case = _case(tmp_path)
    baseline = PolicyStore(tmp_path).load_version(case.policy_version_id or "")
    policy = merge_policy_patch(
        baseline,
        PolicyPatch(
            prompt_overlays={"flow_analyst": "Use replay provenance."},
            task_templates={
                MomentumCapability.SOURCE_QUALITY: "Withhold unsupported evidence."
            },
            tool_policies=[
                ToolPolicy(
                    profile="flow_analyst",
                    capability=MomentumCapability.SOURCE_QUALITY,
                    preferred_tools=["web_search"],
                )
            ],
        ),
        trigger_ids=[case.case_id],
    )
    report = {
        "task_id": "task-1",
        "title": "Synthetic task",
        "agent_role": "flow_analyst",
        "summary": "Grounded synthetic result.",
        "status": "complete",
        "unanswered_questions": [],
        "contradictions": [],
        "findings": [
            {
                "claim": "Synthetic observation was retrieved.",
                "category": "other",
                "stance": "neutral",
                "source_url": "https://example.test/source",
                "source_name": "web_search",
                "excerpt": "Synthetic primary-source observation.",
                "confidence": "medium",
            }
        ],
    }
    client = FakeClient(
        [
            FakeResponse(
                _message(
                    tool_calls=[
                        FakeToolCall(
                            "call-1",
                            "web_search",
                            '{"query":"synthetic replay"}',
                        )
                    ]
                ),
                finish_reason="tool_calls",
                model="deepseek-v4-flash",
            ),
            FakeResponse(
                _message(json.dumps(report)),
                finish_reason="stop",
                model="deepseek-v4-flash",
            ),
        ]
    )
    requests = LLMRequestBudget(max_attempts=4)

    result = await run_replay_case(
        client=client,
        requested_model="deepseek-chat",
        project_root=tmp_path,
        case=case,
        policy=policy,
        budget=LoopBudget(max_turns=3),
        request_budget=requests,
        max_output_tokens=512,
    )

    assert result.outcome == "success"
    assert result.report is not None
    assert result.report.findings[0].source_url == "https://example.test/source"
    assert result.calls[0].matched_trace_id == "trace-1"
    assert result.calls[0].arguments == {"query": "synthetic replay"}
    assert result.consumed_trace_ids == ["trace-1"]
    assert result.response_model_ids == ["deepseek-v4-flash", "deepseek-v4-flash"]
    assert result.requested_model == "deepseek-chat"
    assert result.llm_requests == 2
    assert result.usage.total_tokens == 36
    assert client.retry_options == [0]
    assert all(call["max_tokens"] == 512 for call in client.calls)
    assert "Use replay provenance" in client.calls[0]["messages"][0]["content"]
    assert "Preferred tools for source_quality: web_search" in client.calls[0]["messages"][0]["content"]
    assert "Withhold unsupported evidence" in client.calls[0]["messages"][1]["content"]
    assert "Synthetic primary-source observation" not in client.calls[0]["messages"][0]["content"]
    assert "Synthetic primary-source observation" not in client.calls[0]["messages"][1]["content"]
    assert "Synthetic primary-source observation" in client.calls[1]["messages"][-1]["content"]
    assert case_content_sha256(case) == case_content_sha256(case.model_copy(deep=True))


def test_replay_registry_rejects_conflicting_duplicate_keys_and_invalid_observations(
    tmp_path: Path,
) -> None:
    case = _case(tmp_path)
    first = case.tool_traces[0]
    other_text = "different"
    conflicting = first.model_copy(
        update={
            "id": "trace-2",
            "observation": other_text,
            "observation_sha256": hashlib.sha256(other_text.encode()).hexdigest(),
        }
    )
    payload = case.model_dump(mode="json")
    payload["source_trace_ids"].append("trace-2")
    payload["failing_evidence"]["trace_ids"].append("trace-2")
    payload["tool_traces"].append(conflicting.model_dump(mode="json"))
    conflicting_case = SessionEvalCase.model_validate(payload)

    with pytest.raises(ValueError, match="conflicting replay observations"):
        build_replay_registry(conflicting_case)


def test_model_arguments_cannot_override_closed_over_replay_tool_name(tmp_path: Path) -> None:
    case = _case(tmp_path)
    _definitions, registry, calls = build_replay_registry(case)

    result = registry["web_search"](
        _tool_name="web_search",
        query="synthetic replay",
    )

    assert result == "REPLAY_UNAVAILABLE"
    assert calls[0].tool == "web_search"
    assert calls[0].arguments == {
        "_tool_name": "web_search",
        "query": "synthetic replay",
    }
    assert calls[0].matched_trace_id is None


def test_non_finite_model_arguments_cannot_match_a_replay_observation(tmp_path: Path) -> None:
    case = _case(tmp_path)
    _definitions, registry, calls = build_replay_registry(case)

    result = registry["web_search"](query=float("nan"))

    assert result == "REPLAY_UNAVAILABLE"
    assert calls[0].matched_trace_id is None


@pytest.mark.asyncio
async def test_unmatched_call_is_unscorable_and_never_invokes_a_live_tool(
    tmp_path: Path,
) -> None:
    case = _case(tmp_path)
    policy = PolicyStore(tmp_path).load_version(case.policy_version_id or "")
    client = FakeClient(
        [
            FakeResponse(
                _message(
                    tool_calls=[
                        FakeToolCall("call-1", "web_search", '{"query":"not recorded"}')
                    ]
                ),
                finish_reason="tool_calls",
                model="resolved",
            ),
            FakeResponse(
                _message(
                    json.dumps(
                        {
                            "task_id": "task-1",
                            "title": "Synthetic task",
                            "agent_role": "flow_analyst",
                            "summary": "Unavailable.",
                            "status": "insufficient_evidence",
                            "findings": [],
                        }
                    )
                ),
                finish_reason="stop",
                model="resolved",
            ),
        ]
    )

    result = await run_replay_case(
        client=client,
        requested_model="model",
        project_root=tmp_path,
        case=case,
        policy=policy,
        budget=LoopBudget(max_turns=3),
        request_budget=LLMRequestBudget(max_attempts=2),
        max_output_tokens=128,
    )

    assert result.outcome == "unscorable"
    assert result.calls[0].matched_trace_id is None
    assert result.calls[0].result == "REPLAY_UNAVAILABLE"


@pytest.mark.asyncio
async def test_unknown_tool_attempt_is_recorded_and_cannot_pass(tmp_path: Path) -> None:
    case = _case(tmp_path)
    policy = PolicyStore(tmp_path).load_version(case.policy_version_id or "")
    client = FakeClient(
        [
            FakeResponse(
                _message(
                    tool_calls=[
                        FakeToolCall(
                            "call-1",
                            "engine_query",
                            '{"ticker":"NVDA","end":"2026-05-29"}',
                        )
                    ]
                ),
                finish_reason="tool_calls",
                model="resolved",
            ),
            FakeResponse(
                _message(
                    json.dumps(
                        {
                            "task_id": "task-1",
                            "title": "Synthetic task",
                            "agent_role": "flow_analyst",
                            "summary": "Stopped.",
                            "status": "insufficient_evidence",
                            "findings": [],
                        }
                    )
                ),
                finish_reason="stop",
                model="resolved",
            ),
        ]
    )

    result = await run_replay_case(
        client=client,
        requested_model="model",
        project_root=tmp_path,
        case=case,
        policy=policy,
        budget=LoopBudget(max_turns=3),
        request_budget=LLMRequestBudget(max_attempts=2),
        max_output_tokens=128,
    )

    assert result.outcome == "unscorable"
    assert result.calls[0].tool == "engine_query"
    assert result.calls[0].arguments == {"ticker": "NVDA", "end": "2026-05-29"}
    assert result.calls[0].matched_trace_id is None
    assert result.calls[0].result == "REPLAY_UNAVAILABLE"


@pytest.mark.asyncio
async def test_budget_exhaustion_and_length_truncation_cannot_succeed(tmp_path: Path) -> None:
    case = _case(tmp_path)
    policy = PolicyStore(tmp_path).load_version(case.policy_version_id or "")
    with pytest.raises(ValueError, match="positive"):
        LLMRequestBudget(max_attempts=0)
    exhausted_budget = LLMRequestBudget(max_attempts=1)
    exhausted_budget.claim()
    no_budget = await run_replay_case(
        client=FakeClient([]),
        requested_model="model",
        project_root=tmp_path,
        case=case,
        policy=policy,
        budget=LoopBudget(max_turns=2),
        request_budget=exhausted_budget,
        max_output_tokens=64,
    )
    assert no_budget.outcome == "failed"
    assert no_budget.report is None
    assert no_budget.reasons == ["llm_request_budget_exhausted"]

    truncated = await run_replay_case(
        client=FakeClient(
            [
                FakeResponse(
                    _message('{"task_id":"task-1"'),
                    finish_reason="length",
                    model="resolved",
                )
            ]
        ),
        requested_model="model",
        project_root=tmp_path,
        case=case,
        policy=policy,
        budget=LoopBudget(max_turns=2),
        request_budget=LLMRequestBudget(max_attempts=1),
        max_output_tokens=64,
    )
    assert truncated.outcome == "failed"
    assert truncated.reasons == ["output_length_truncated"]
