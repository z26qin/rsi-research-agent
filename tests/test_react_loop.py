from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from momentum_research_agent.agents.budget import LoopBudget
from momentum_research_agent.agents.react_loop import react_loop, react_loop_detailed
from momentum_research_agent.errors import AgentDeadlineExceeded, ToolExecutionTimeout
from momentum_research_agent.models.schemas import UsageSummary


class FakeFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.id = call_id
        self.function = FakeFunction(name, arguments)


class FakeMessage:
    def __init__(self, content: str | None = None, tool_calls: list | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class FakeUsage:
    def __init__(self, prompt_tokens: int = 10, completion_tokens: int = 5) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class FakeResponse:
    def __init__(
        self,
        message: FakeMessage,
        *,
        finish_reason: str = "stop",
        model: str = "resolved-model",
    ) -> None:
        self.choices = [SimpleNamespace(message=message, finish_reason=finish_reason)]
        self.usage = FakeUsage()
        self.model = model


class FakeCompletions:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("unexpected extra LLM call")
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.completions = FakeCompletions(responses)
        self.chat = SimpleNamespace(completions=self.completions)


@pytest.mark.asyncio
async def test_two_turn_tool_then_text() -> None:
    observed: list[tuple[str, dict, str]] = []

    async def ping(query: str) -> str:
        return f"pong:{query}"

    client = FakeClient(
        [
            FakeResponse(
                FakeMessage(
                    content="",
                    tool_calls=[FakeToolCall("c1", "ping", '{"query": "nvda"}')],
                )
            ),
            FakeResponse(FakeMessage(content="Final view: rotation, not crash.")),
        ]
    )
    usage = UsageSummary()
    text = await react_loop(
        client=client,  # type: ignore[arg-type]
        model="deepseek-chat",
        system_prompt="You are a tester.",
        user_message="Investigate NVDA.",
        tools=[{"type": "function", "function": {"name": "ping"}}],
        tool_registry={"ping": ping},
        on_tool_call=lambda name, args, result: observed.append((name, args, result)),
        usage_tracker=usage,
    )

    assert text == "Final view: rotation, not crash."
    assert observed == [("ping", {"query": "nvda"}, "pong:nvda")]
    assert len(client.completions.calls) == 2
    second_messages = client.completions.calls[1]["messages"]
    tool_messages = [msg for msg in second_messages if msg["role"] == "tool"]
    assert tool_messages
    assert tool_messages[0]["content"] == "pong:nvda"
    assert usage.prompt_tokens == 20
    assert usage.completion_tokens == 10


@pytest.mark.asyncio
async def test_max_turns_cutoff() -> None:
    async def ping(query: str) -> str:
        return query

    responses = [
        FakeResponse(
            FakeMessage(
                content="still thinking",
                tool_calls=[FakeToolCall(f"c{i}", "ping", '{"query": "x"}')],
            )
        )
        for i in range(3)
    ]
    client = FakeClient(responses)
    text = await react_loop(
        client=client,  # type: ignore[arg-type]
        model="deepseek-chat",
        system_prompt="sys",
        user_message="go",
        tools=[],
        tool_registry={"ping": ping},
        max_turns=2,
    )
    assert "stopped after 2 turns" in text or text == "still thinking"
    assert len(client.completions.calls) == 2


@pytest.mark.asyncio
async def test_tool_error_is_returned_to_model() -> None:
    async def boom() -> str:
        raise RuntimeError("disk full")

    client = FakeClient(
        [
            FakeResponse(
                FakeMessage(
                    tool_calls=[FakeToolCall("c1", "boom", "{}")],
                )
            ),
            FakeResponse(FakeMessage(content="Recovered after tool error.")),
        ]
    )
    text = await react_loop(
        client=client,  # type: ignore[arg-type]
        model="deepseek-chat",
        system_prompt="sys",
        user_message="go",
        tools=[],
        tool_registry={"boom": boom},
    )
    assert text == "Recovered after tool error."
    tool_messages = [
        msg for msg in client.completions.calls[1]["messages"] if msg["role"] == "tool"
    ]
    assert tool_messages
    assert "RuntimeError" in tool_messages[0]["content"]
    assert "disk full" in tool_messages[0]["content"]


@pytest.mark.asyncio
async def test_unauthorized_tool_is_not_executed() -> None:
    leaked: list[str] = []

    async def secret() -> str:
        leaked.append("ran")
        return "should never run"

    client = FakeClient(
        [
            FakeResponse(
                FakeMessage(tool_calls=[FakeToolCall("c1", "secret", "{}")]),
            ),
            FakeResponse(FakeMessage(content="Stopped after unauthorized request.")),
        ]
    )
    text = await react_loop(
        client=client,  # type: ignore[arg-type]
        model="deepseek-chat",
        system_prompt="sys",
        user_message="go",
        tools=[],
        tool_registry={"ping": lambda: "ok"},
    )
    assert leaked == []
    assert text == "Stopped after unauthorized request."
    observation = [msg for msg in client.completions.calls[1]["messages"] if msg["role"] == "tool"]
    assert observation
    assert "UNAUTHORIZED" in observation[0]["content"]


@pytest.mark.asyncio
async def test_llm_timeout_triggers() -> None:
    class SlowCompletions(FakeCompletions):
        async def create(self, **kwargs):
            await asyncio.sleep(0.2)
            return await super().create(**kwargs)

    client = FakeClient([FakeResponse(FakeMessage(content="late"))])
    client.completions = SlowCompletions(client.completions._responses)
    client.chat = SimpleNamespace(completions=client.completions)
    with pytest.raises(AgentDeadlineExceeded, match="LLM call timed out"):
        await react_loop(
            client=client,  # type: ignore[arg-type]
            model="deepseek-chat",
            system_prompt="sys",
            user_message="go",
            tools=[],
            tool_registry={},
            budget=LoopBudget(max_turns=2, overall_deadline_s=5, llm_timeout_s=0.05, tool_timeout_s=1),
        )


@pytest.mark.asyncio
async def test_overall_deadline_stops_long_run() -> None:
    client = FakeClient([FakeResponse(FakeMessage(content="late"))])
    with pytest.raises(AgentDeadlineExceeded, match="Overall deadline exceeded"):
        await react_loop(
            client=client,  # type: ignore[arg-type]
            model="deepseek-chat",
            system_prompt="sys",
            user_message="go",
            tools=[],
            tool_registry={},
            budget=LoopBudget(
                max_turns=3,
                overall_deadline_s=1e-9,
                llm_timeout_s=20,
                tool_timeout_s=10,
            ),
        )


@pytest.mark.asyncio
async def test_tool_timeout_triggers() -> None:
    async def slow_tool() -> str:
        await asyncio.sleep(0.3)
        return "done"

    client = FakeClient(
        [
            FakeResponse(FakeMessage(tool_calls=[FakeToolCall("c1", "slow_tool", "{}")])),
            FakeResponse(FakeMessage(content="should not reach")),
        ]
    )
    with pytest.raises(ToolExecutionTimeout, match="slow_tool"):
        await react_loop(
            client=client,  # type: ignore[arg-type]
            model="deepseek-chat",
            system_prompt="sys",
            user_message="go",
            tools=[],
            tool_registry={"slow_tool": slow_tool},
            budget=LoopBudget(max_turns=3, overall_deadline_s=5, llm_timeout_s=2, tool_timeout_s=0.05),
        )


@pytest.mark.asyncio
async def test_cancellation_propagates() -> None:
    class HangingCompletions(FakeCompletions):
        async def create(self, **kwargs):
            await asyncio.sleep(5)
            return await super().create(**kwargs)

    client = FakeClient([FakeResponse(FakeMessage(content="never"))])
    client.completions = HangingCompletions(client.completions._responses)
    client.chat = SimpleNamespace(completions=client.completions)
    task = asyncio.create_task(
        react_loop(
            client=client,  # type: ignore[arg-type]
            model="deepseek-chat",
            system_prompt="sys",
            user_message="go",
            tools=[],
            tool_registry={},
            budget=LoopBudget(max_turns=2, overall_deadline_s=10, llm_timeout_s=10, tool_timeout_s=10),
        )
    )
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_detailed_loop_enforces_request_hook_and_output_limit() -> None:
    attempts: list[str] = []
    responses: list[object] = []
    client = FakeClient([FakeResponse(FakeMessage(content="complete"))])

    result = await react_loop_detailed(
        client=client,  # type: ignore[arg-type]
        model="requested-model",
        system_prompt="sys",
        user_message="go",
        tools=[],
        tool_registry={},
        before_llm_request=lambda: attempts.append("attempt"),
        on_llm_response=responses.append,
        max_output_tokens=321,
        temperature=0.0,
    )

    assert attempts == ["attempt"]
    assert responses[0].model == "resolved-model"
    assert client.completions.calls[0]["max_tokens"] == 321
    assert client.completions.calls[0]["temperature"] == 0.0
    assert result.completed is True
    assert result.stop_reason == "completed"
    assert result.text == "complete"


@pytest.mark.asyncio
async def test_detailed_loop_does_not_treat_length_or_final_tool_call_as_complete() -> None:
    length_client = FakeClient(
        [FakeResponse(FakeMessage(content='{"partial":'), finish_reason="length")]
    )
    length = await react_loop_detailed(
        client=length_client,  # type: ignore[arg-type]
        model="model",
        system_prompt="sys",
        user_message="go",
        tools=[],
        tool_registry={},
    )
    assert length.completed is False
    assert length.stop_reason == "length"

    tool_client = FakeClient(
        [
            FakeResponse(
                FakeMessage(
                    content="stale intermediate",
                    tool_calls=[FakeToolCall("c1", "ping", "{}")],
                ),
                finish_reason="tool_calls",
            )
        ]
    )
    final_tool = await react_loop_detailed(
        client=tool_client,  # type: ignore[arg-type]
        model="model",
        system_prompt="sys",
        user_message="go",
        tools=[],
        tool_registry={"ping": lambda: "pong"},
        max_turns=1,
    )
    assert final_tool.completed is False
    assert final_tool.stop_reason == "max_turns_after_tool"


@pytest.mark.asyncio
async def test_detailed_loop_does_not_reuse_tool_turn_text_for_empty_final() -> None:
    client = FakeClient(
        [
            FakeResponse(
                FakeMessage(
                    content='{"looks":"final but requested a tool"}',
                    tool_calls=[FakeToolCall("c1", "ping", "{}")],
                ),
                finish_reason="tool_calls",
            ),
            FakeResponse(FakeMessage(content=""), finish_reason="stop"),
        ]
    )

    result = await react_loop_detailed(
        client=client,  # type: ignore[arg-type]
        model="model",
        system_prompt="sys",
        user_message="go",
        tools=[],
        tool_registry={"ping": lambda: "pong"},
    )

    assert result.completed is False
    assert result.stop_reason == "empty_final"
    assert result.text == ""


@pytest.mark.asyncio
async def test_detailed_loop_rejects_content_filter_terminal_reason() -> None:
    client = FakeClient(
        [
            FakeResponse(
                FakeMessage(content='{"partial":"filtered"}'),
                finish_reason="content_filter",
            )
        ]
    )

    result = await react_loop_detailed(
        client=client,  # type: ignore[arg-type]
        model="model",
        system_prompt="sys",
        user_message="go",
        tools=[],
        tool_registry={},
    )

    assert result.completed is False
    assert result.stop_reason == "content_filter"


@pytest.mark.asyncio
async def test_length_response_with_tool_calls_does_not_execute_tools_or_continue() -> None:
    executed: list[str] = []
    client = FakeClient(
        [
            FakeResponse(
                FakeMessage(
                    content="truncated",
                    tool_calls=[FakeToolCall("c1", "ping", "{}")],
                ),
                finish_reason="length",
            ),
            FakeResponse(FakeMessage(content="later valid final"), finish_reason="stop"),
        ]
    )

    result = await react_loop_detailed(
        client=client,  # type: ignore[arg-type]
        model="model",
        system_prompt="sys",
        user_message="go",
        tools=[],
        tool_registry={"ping": lambda: executed.append("ran") or "pong"},
    )

    assert result.completed is False
    assert result.stop_reason == "length"
    assert executed == []
    assert len(client.completions.calls) == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_turns": 0},
        {"max_turns": True},
        {"max_turns": 1.5},
        {"overall_deadline_s": float("nan")},
        {"llm_timeout_s": float("inf")},
        {"tool_timeout_s": -1},
    ],
)
def test_loop_budget_rejects_invalid_direct_api_bounds(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        LoopBudget(**kwargs)
