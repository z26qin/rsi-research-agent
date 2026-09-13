"""Bounded native source discovery, independent of model-authored answers."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from momentum_research_agent.config import make_client
from momentum_research_agent.agents.ledger import record_trace
from momentum_research_agent.state.traces import append_traces
from momentum_research_agent.tools.registry import get_tool_context

TIMEOUT_SECONDS = 20
MAX_REQUESTS_PER_ROLE = 2
MODEL = "deepseek-flash"
ENDPOINT = "https://api.deepseek.com/anthropic/v1/messages"


async def request_sources(client, **body) -> dict:
    """Reuse the SDK's transport/key; search has a fixed official endpoint."""
    return await client.with_options(max_retries=0).post(
        ENDPOINT, cast_to=dict[str, Any], body=body,
        options={"headers": {"x-api-key": client.api_key, "anthropic-version": "2023-06-01"},
                 "follow_redirects": False},
    )


def add_usage(data: dict, usage) -> None:
    """Messages separates cache reads/writes from uncached input tokens."""
    returned = data.get("usage")
    if returned and usage is not None:
        inputs = sum(returned.get(name, 0) or 0 for name in (
            "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        usage.add(data.get("model", MODEL), inputs, returned.get("output_tokens", 0) or 0)


def compact_usage(usage: dict | None) -> dict | None:
    """Only bounded counters belong in replay; archive keeps all provider fields."""
    if not isinstance(usage, dict):
        return None
    result = {name: value for name in (
        "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens"
    ) if type(value := usage.get(name)) is int and 0 <= value < 10**15}
    server = usage.get("server_tool_use")
    if isinstance(server, dict):
        count = server.get("web_search_requests")
        if type(count) is int and 0 <= count < 10**15:
            result["server_tool_use"] = {"web_search_requests": count}
    return result


def evidence(data: dict) -> tuple[list[dict], list[str]]:
    # A paused/truncated server run is not a completed search request. Never
    # continue it automatically or use its model prose as retrieved evidence.
    if data.get("type") != "message" or data.get("stop_reason") != "end_turn":
        raise ValueError("Incomplete native search response")
    sources, errors, seen = [], [], set()
    for block in data.get("content") or []:
        if block.get("type") != "web_search_tool_result":
            continue
        items = block.get("content")
        if isinstance(items, dict):
            items = [items]  # Providers may encode a tool error as an object.
        if not isinstance(items, list):
            raise ValueError("Malformed search result block")
        for item in items:
            if item.get("type") == "web_search_tool_result_error":
                if len(errors) < 3:
                    errors.append(str(item.get("error_code", "unknown"))[:100])
                continue
            if item.get("type") != "web_search_result":
                continue
            url = item.get("url")
            if not isinstance(url, str) or len(url) > 512:
                continue
            try:
                parsed = urlsplit(url)
            except ValueError:
                continue
            if (parsed.scheme in {"http", "https"} and parsed.hostname
                    and not parsed.username and not any(c.isspace() for c in url) and url not in seen):
                seen.add(url)
                age = item.get("page_age")
                sources.append({"url": url, "title": str(item.get("title") or "")[:120],
                                "page_age": age[:120] if isinstance(age, str) else None, "snippet": None})
    if not sources:
        raise ValueError("Native search returned no usable sources")
    return sources[:3], errors


async def search(query: str) -> str:
    ctx = get_tool_context()
    result = {"provider": "deepseek_native", "status": "unavailable", "sources": []}
    if not isinstance(query, str) or not query.strip() or len(query) > 512:
        return json.dumps({**result, "reason": "Query must contain 1-512 characters"})
    if ctx.session_dir is None:
        return json.dumps({**result, "reason": "A session directory is required for evidence retention"})
    if ctx.search_requests >= MAX_REQUESTS_PER_ROLE:
        return json.dumps({**result, "reason": "Native search attempt budget exhausted", "budget_exhausted": True})
    ctx.search_requests += 1
    result['budget_exhausted'] = ctx.search_requests >= MAX_REQUESTS_PER_ROLE
    directory = ctx.session_dir / "search_results"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid4().hex}.json"
    started = time.monotonic()
    archive = {"query": query, "provider": "deepseek_native", "requested_model": MODEL,
               "endpoint": ENDPOINT,
               "fetched_at": datetime.now(timezone.utc).isoformat(), "status": "unavailable",
               "max_tokens": 1024, "max_uses": 1, "timeout_seconds": TIMEOUT_SECONDS,
               "usage": None, "billing": "unknown_without_returned_usage"}
    owned = ctx.client is None
    client = None
    try:
        client = make_client() if owned else ctx.client
        prompt = (Path(__file__).parents[1] / "coordinator/prompts/native_search.md").read_text()
        body = dict(model=MODEL, system=prompt,
                    messages=[{"role": "user", "content": [{"type": "text", "text": query}]}],
                    tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}],
                    thinking={"type": "disabled"}, max_tokens=1024)
        archive["parameters"] = body
        async with asyncio.timeout(TIMEOUT_SECONDS):
            request = getattr(client, "search_request", None)
            data = await request(**body) if request else await request_sources(client, **body)
        archive.update(response=data, usage=data.get("usage"))
        if data.get("usage"):
            archive["billing"] = "provider_reported_tokens_not_a_dollar_cap"
            add_usage(data, ctx.usage)
        sources, errors = evidence(data)
        result.update(status="ok", evidence_kind="source_discovery", sources=sources, search_errors=errors,
                      stop_reason=data.get("stop_reason"),
                      note="Source discovery only: titles/URLs are not page text or verified claims. "
                           "Model prose is excluded; page_age is provider metadata, not a verified observation date.")
        archive["status"] = "ok"
    except asyncio.CancelledError:
        result["status"] = "cancelled"
        archive["status"] = "cancelled"
        archive["error_type"] = "CancelledError"
        raise
    except Exception as exc:
        result["reason"] = f"Native search unavailable ({type(exc).__name__}); no provider fallback"
        archive.update(error_type=type(exc).__name__, http_status=getattr(exc, "status_code", None))
    finally:
        archive["elapsed_seconds"] = round(time.monotonic() - started, 3)
        serialized = json.dumps(archive, ensure_ascii=False, indent=2)
        path.write_text(serialized, encoding="utf-8")
        result.update(artifact=str(path.relative_to(ctx.session_dir)),
                      sha256=hashlib.sha256(serialized.encode()).hexdigest(),
                      fetched_at=archive["fetched_at"], usage=compact_usage(archive["usage"]), billing=archive["billing"])
        if archive["status"] == "cancelled":
            # Outer tool/role deadlines bypass ReAct's normal observation callback.
            # Only interrupted calls write here; successful calls use that callback.
            trace = record_trace("web_search", {"query": query}, json.dumps(result, ensure_ascii=False),
                                 agent_id=ctx.agent_id, agent_role=ctx.agent_role)
            append_traces(ctx.session_dir, [trace])
        if owned and client is not None:
            try:
                await asyncio.wait_for(client.close(), timeout=2)
            except Exception:
                pass
    return json.dumps(result, ensure_ascii=False)
