"""Web search: native DeepSeek by default when configured; optional legacy providers."""

from __future__ import annotations

import os
from typing import Any

import httpx

from momentum_research_agent.config import deepseek_api_key

from momentum_research_agent.tools.registry import register_tool


def _format_serper(payload: dict[str, Any]) -> str:
    organic = payload.get("organic") or []
    if not organic:
        return "No organic results returned."
    lines: list[str] = []
    for i, item in enumerate(organic[:8], start=1):
        title = item.get("title", "(no title)")
        url = item.get("link", "")
        snippet = item.get("snippet", "")
        lines.append(f"{i}. {title}\n   {url}\n   {snippet}")
    return "\n\n".join(lines)


def _format_tavily(payload: dict[str, Any]) -> str:
    results = payload.get("results") or []
    if not results:
        answer = payload.get("answer")
        return answer or "No results returned."
    lines: list[str] = []
    if payload.get("answer"):
        lines.append(f"Answer: {payload['answer']}\n")
    for i, item in enumerate(results[:8], start=1):
        title = item.get("title", "(no title)")
        url = item.get("url", "")
        snippet = item.get("content", "")
        lines.append(f"{i}. {title}\n   {url}\n   {snippet}")
    return "\n\n".join(lines)


async def _serper_search(query: str) -> str:
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key:
        raise RuntimeError("SERPER_API_KEY is not set")
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": 8},
        )
        response.raise_for_status()
        return _format_serper(response.json())


async def _tavily_search(query: str) -> str:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is not set")
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "max_results": 8},
        )
        response.raise_for_status()
        return _format_tavily(response.json())


@register_tool(
    name="web_search",
    description="Search the public web for news, research, and market commentary.",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query, including tickers or factor names when relevant.",
            }
        },
        "required": ["query"],
    },
)
async def web_search(query: str) -> str:
    provider = os.environ.get("WEB_SEARCH_PROVIDER", "auto")
    if provider not in {"auto", "deepseek", "legacy"}:
        return "web_search unavailable: invalid WEB_SEARCH_PROVIDER"
    if provider == "deepseek" or (provider == "auto" and deepseek_api_key()):
        from momentum_research_agent.tools.deepseek_search import search
        return await search(query)
    if os.environ.get("SERPER_API_KEY"):
        try:
            return await _serper_search(query)
        except Exception as exc:
            if not os.environ.get("TAVILY_API_KEY"):
                return f"web_search failed via Serper: {exc}"
    if os.environ.get("TAVILY_API_KEY"):
        try:
            return await _tavily_search(query)
        except Exception as exc:
            return f"web_search failed via Tavily: {exc}"
    return (
        "web_search is unavailable: set SERPER_API_KEY (preferred) or TAVILY_API_KEY "
        "in the environment / .env file."
    )
