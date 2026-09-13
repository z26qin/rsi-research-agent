"""Tool package. Importing this module registers every built-in tool."""

from momentum_research_agent.errors import UnauthorizedTool
from momentum_research_agent.tools import (  # noqa: F401
    engine_query,
    file_reader,
    market_data,
    shell,
    web_search,
    read_url,
)
from momentum_research_agent.tools.registry import (
    ToolContext,
    get_tool_context,
    registered_names,
    resolve_tools,
    set_tool_context,
)

# Research default — not a fallback for unknown profiles.
DEFAULT_TOOLS = [
    "engine_query",
    "market_data",
    "web_search",
    "file_reader",
    "read_url",
]

PROFILE_TOOLS: dict[str, list[str]] = {
    "momentum_analyst": ["engine_query", "market_data", "web_search", "file_reader", "read_url"],
    "credit_analyst": ["market_data", "web_search", "file_reader", "read_url"],
    "macro_analyst": ["market_data", "web_search", "file_reader", "read_url"],
    "flow_analyst": ["engine_query", "market_data", "web_search", "file_reader", "read_url"],
    "technicals_analyst": ["market_data", "web_search", "file_reader", "read_url"],
    "verifier": ["engine_query", "market_data", "web_search", "file_reader", "read_url"],
}

RESEARCH_PROFILES = frozenset(
    name for name in PROFILE_TOOLS if name != "verifier"
)


def tools_for_profile(profile: str) -> list[str]:
    name = profile.removesuffix(".md")
    if name not in PROFILE_TOOLS:
        known = ", ".join(sorted(PROFILE_TOOLS))
        raise UnauthorizedTool(f"Unknown profile '{name}'. Authorized profiles: {known}")
    return list(PROFILE_TOOLS[name])


def authorize_tools(profile: str, requested: list[str] | None = None) -> list[str]:
    """Fail closed: unknown profiles and extra tools are rejected, not broadened."""
    allowed = tools_for_profile(profile)
    if requested is None:
        return allowed
    extra = [name for name in requested if name not in set(allowed)]
    if extra:
        raise UnauthorizedTool(
            f"Profile '{profile.removesuffix('.md')}' is not authorized for: {', '.join(extra)}. "
            f"Allowlist: {', '.join(allowed)}"
        )
    return list(requested)


def authorize_research_tools(profile: str, requested: list[str] | None = None) -> list[str]:
    name = profile.removesuffix(".md")
    if name not in RESEARCH_PROFILES:
        raise UnauthorizedTool(
            f"Profile '{name}' is not a research profile. "
            f"Research profiles: {', '.join(sorted(RESEARCH_PROFILES))}"
        )
    return authorize_tools(name, requested)


__all__ = [
    "DEFAULT_TOOLS",
    "PROFILE_TOOLS",
    "RESEARCH_PROFILES",
    "ToolContext",
    "authorize_research_tools",
    "authorize_tools",
    "get_tool_context",
    "registered_names",
    "resolve_tools",
    "set_tool_context",
    "tools_for_profile",
]
