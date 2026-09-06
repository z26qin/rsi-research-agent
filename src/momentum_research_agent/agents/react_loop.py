"""Generic ReAct loop: think → act → observe until the model stops calling tools."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass
from typing import Any, Optional, TypeVar

from openai import AsyncOpenAI

from momentum_research_agent.agents.budget import LoopBudget
from momentum_research_agent.errors import (
    AgentDeadlineExceeded,
    ToolExecutionTimeout,
    UnauthorizedTool,
)
from momentum_research_agent.models.schemas import UsageSummary
from momentum_research_agent.tools.registry import call_tool

OnToolCall = Callable[[str, dict[str, Any], str], None]
BeforeLLMRequest = Callable[[], None]
OnLLMResponse = Callable[[Any], None]
T = TypeVar("T")


@dataclass(frozen=True)
class ReactLoopResult:
    text: str
    completed: bool
    stop_reason: str


def _record_usage(usage_tracker: UsageSummary | None, model: str, response: Any) -> None:
    usage = getattr(response, "usage", None)
    if usage_tracker is None or usage is None:
        return
    usage_tracker.add(
        model,
        int(getattr(usage, "prompt_tokens", 0) or 0),
        int(getattr(usage, "completion_tokens", 0) or 0),
    )


def _assistant_message(message: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": "assistant",
        "content": message.content or "",
    }
    tool_calls = getattr(message, "tool_calls", None) or []
    if tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments or "{}",
                },
            }
            for call in tool_calls
        ]
    return payload


def _parse_arguments(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _remaining_timeout(deadline: float, configured: float) -> float:
    left = deadline - time.monotonic()
    if left <= 0:
        raise AgentDeadlineExceeded("Overall deadline exceeded.")
    return min(configured, left)


async def _await_bounded(
    coro: Coroutine[Any, Any, T],
    timeout: float,
    on_timeout: AgentDeadlineExceeded | ToolExecutionTimeout,
) -> T:
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.CancelledError:
        raise
    except TimeoutError as exc:
        raise on_timeout from exc


def _resolve_budget(budget: LoopBudget | None, max_turns: int | None) -> LoopBudget:
    if budget is not None:
        return budget
    if max_turns is not None:
        return LoopBudget(max_turns=max_turns)
    return LoopBudget()


async def react_loop_detailed(
    client: AsyncOpenAI,
    model: str,
    system_prompt: str,
    user_message: str,
    tools: list[dict[str, Any]],
    tool_registry: Mapping[str, Callable[..., Any]],
    max_turns: int | None = None,
    on_tool_call: Optional[OnToolCall] = None,
    usage_tracker: UsageSummary | None = None,
    budget: LoopBudget | None = None,
    before_llm_request: BeforeLLMRequest | None = None,
    on_llm_response: OnLLMResponse | None = None,
    max_output_tokens: int | None = None,
    temperature: float | None = None,
) -> ReactLoopResult:
    """Run the native loop and expose whether a final answer really completed."""
    resolved = _resolve_budget(budget, max_turns)
    deadline = time.monotonic() + resolved.overall_deadline_s
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    last_text = ""

    for _turn in range(resolved.max_turns):
        llm_timeout = _remaining_timeout(deadline, resolved.llm_timeout_s)
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        if max_output_tokens is not None:
            kwargs["max_tokens"] = max_output_tokens
        if temperature is not None:
            kwargs["temperature"] = temperature
        if before_llm_request is not None:
            before_llm_request()
        response = await _await_bounded(
            client.chat.completions.create(**kwargs),
            llm_timeout,
            AgentDeadlineExceeded(f"LLM call timed out after {llm_timeout:.1f}s."),
        )
        if on_llm_response is not None:
            on_llm_response(response)
        _record_usage(usage_tracker, model, response)

        choice = response.choices[0]
        message = choice.message
        current_text = message.content or ""
        tool_calls = getattr(message, "tool_calls", None) or []
        finish_reason = str(getattr(choice, "finish_reason", "") or "")
        messages.append(_assistant_message(message))

        if finish_reason == "length":
            return ReactLoopResult(
                text=current_text,
                completed=False,
                stop_reason="length",
            )

        if not tool_calls:
            if finish_reason != "stop":
                return ReactLoopResult(
                    text=current_text,
                    completed=False,
                    stop_reason=finish_reason or "missing_finish_reason",
                )
            if not current_text.strip():
                return ReactLoopResult(
                    text="",
                    completed=False,
                    stop_reason="empty_final",
                )
            return ReactLoopResult(
                text=current_text,
                completed=True,
                stop_reason="completed",
            )

        last_text = current_text or last_text
        for call in tool_calls:
            name = call.function.name
            arguments = _parse_arguments(call.function.arguments)
            if name not in tool_registry:
                result = (
                    f"UNAUTHORIZED: tool '{name}' is not on this agent's allowlist. "
                    f"Available: {', '.join(sorted(tool_registry)) or '(none)'}"
                )
            else:
                tool_timeout = _remaining_timeout(deadline, resolved.tool_timeout_s)
                try:
                    result = await _await_bounded(
                        call_tool(tool_registry[name], arguments),
                        tool_timeout,
                        ToolExecutionTimeout(
                            f"Tool '{name}' timed out after {tool_timeout:.1f}s."
                        ),
                    )
                except asyncio.CancelledError:
                    raise
                except ToolExecutionTimeout:
                    raise
                except AgentDeadlineExceeded:
                    raise
                except UnauthorizedTool:
                    raise
                except Exception as exc:
                    result = f"Tool '{name}' raised {type(exc).__name__}: {exc}"
            if on_tool_call is not None:
                on_tool_call(name, arguments, result)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": result,
                }
            )

    return ReactLoopResult(
        text=last_text
        or f"ReAct loop stopped after {resolved.max_turns} turns without a final answer.",
        completed=False,
        stop_reason="max_turns_after_tool",
    )


async def react_loop(
    client: AsyncOpenAI,
    model: str,
    system_prompt: str,
    user_message: str,
    tools: list[dict[str, Any]],
    tool_registry: Mapping[str, Callable[..., Any]],
    max_turns: int | None = None,
    on_tool_call: Optional[OnToolCall] = None,
    usage_tracker: UsageSummary | None = None,
    budget: LoopBudget | None = None,
) -> str:
    """Run a native OpenAI-compatible tool-calling loop and return final text."""
    result = await react_loop_detailed(
        client=client,
        model=model,
        system_prompt=system_prompt,
        user_message=user_message,
        tools=tools,
        tool_registry=tool_registry,
        max_turns=max_turns,
        on_tool_call=on_tool_call,
        usage_tracker=usage_tracker,
        budget=budget,
    )
    return result.text
