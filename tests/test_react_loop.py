from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from momentum_research_agent.agents.budget import LoopBudget
from momentum_research_agent.agents.react_loop import react_loop, react_loop_detailed
from momentum_research_agent.errors import AgentDeadlineExceeded


class FakeFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, call_id: str, name: str, arguments: str) -> None:
        self.id = call_id
        self.function = FakeFunction(name, arguments)


class FakeMessage:
    def __init__(
        self, content: str | None = None, tool_calls: list | None = None
    ) -> None:
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
            budget=LoopBudget(
                max_turns=2, overall_deadline_s=10, llm_timeout_s=10, tool_timeout_s=10
            ),
        )
    )
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_length_response_with_tool_calls_does_not_execute_tools_or_continue() -> (
    None
):
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
            FakeResponse(
                FakeMessage(content="later valid final"), finish_reason="stop"
            ),
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
