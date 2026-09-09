"""Dict-based tool registry. Tools register themselves with @register_tool."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Console
from momentum_research_agent.models.schemas import UsageSummary


@dataclass
class ToolContext:
    project_root: Path
    session_dir: Path | None = None
    console: Console | None = None
    verbose: bool = False
    client: Any = None
    usage: UsageSummary | None = None
    search_requests: int = 0
    agent_id: str | None = None
    agent_role: str | None = None


@dataclass
class ToolSpec:
    name: str
    fn: Callable[..., Any]
    definition: dict[str, Any]


_REGISTRY: dict[str, ToolSpec] = {}
_CONTEXT: ContextVar[ToolContext | None] = ContextVar("tool_context", default=None)


def set_tool_context(ctx: ToolContext) -> None:
    _CONTEXT.set(ctx)


def get_tool_context() -> ToolContext:
    ctx = _CONTEXT.get()
    if ctx is None:
        raise RuntimeError("Tool context is not set. SubAgent.run must bind it first.")
    return ctx


def register_tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        _REGISTRY[name] = ToolSpec(
            name=name,
            fn=fn,
            definition={
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            },
        )
        return fn

    return decorator


def get_tool(name: str) -> ToolSpec:
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        known = ", ".join(sorted(_REGISTRY)) or "(none registered)"
        raise KeyError(f"Unknown tool '{name}'. Registered: {known}") from exc


def resolve_tools(names: list[str]) -> tuple[list[dict[str, Any]], dict[str, Callable[..., Any]]]:
    """Return OpenAI tool definitions and a name → callable map."""
    definitions: list[dict[str, Any]] = []
    callables: dict[str, Callable[..., Any]] = {}
    for name in names:
        spec = get_tool(name)
        definitions.append(spec.definition)
        callables[name] = spec.fn
    return definitions, callables


def registered_names() -> list[str]:
    return sorted(_REGISTRY)


async def call_tool(fn: Callable[..., Any], arguments: Mapping[str, Any]) -> str:
    result = fn(**arguments)
    if inspect.isawaitable(result):
        result = await result
    return str(result)
