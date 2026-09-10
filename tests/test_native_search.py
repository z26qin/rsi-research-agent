"""Native search contract through the real SDK, with offline HTTP responses."""
import asyncio
import hashlib
import json
from pathlib import Path

import httpx
from openai import AsyncOpenAI
import pytest

from momentum_research_agent import config
from momentum_research_agent.brief_research import LimitedClient
from momentum_research_agent.models.schemas import UsageSummary
from momentum_research_agent.tools import web_search
from momentum_research_agent.tools.registry import ToolContext, set_tool_context


def response():
    return {"id": "msg_test", "type": "message", "role": "assistant",
        "model": "deepseek-v4-flash", "stop_reason": "end_turn", "stop_sequence": None,
        "content": [{"id": "ws_1", "type": "server_tool_use", "name": "web_search",
                     "input": {"query": "MTUM objective"}},
                    {"type": "web_search_tool_result", "tool_use_id": "ws_1", "content": [
                        {"type": "web_search_result", "url": "https://www.ishares.com/mtum",
                         "title": "MTUM", "page_age": None, "encrypted_content": "opaque"}]}],
        "usage": {"input_tokens": 100, "cache_read_input_tokens": 40,
                  "cache_creation_input_tokens": 10, "output_tokens": 20,
                  "server_tool_use": {"web_search_requests": 1}}}


@pytest.fixture
def env(monkeypatch):
    for name in ("DEEPSEEK_API_KEY", "DeepSeekAPI", "MOMENTUM_ENV_FILE", "SERPER_API_KEY", "TAVILY_API_KEY", "WEB_SEARCH_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DeepSeekAPI", "test-not-secret")


def sdk(handler):
    return AsyncOpenAI(api_key="test-not-secret", base_url="https://api.deepseek.com",
                       http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), max_retries=0)


async def test_native_search_returns_sources_without_requiring_a_model_answer(tmp_path, env):
    calls = []
    def handler(request):
        assert str(request.url) == "https://api.deepseek.com/anthropic/v1/messages"
        assert request.headers["x-api-key"] == "test-not-secret"
        assert request.headers["anthropic-version"] == "2023-06-01"
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=response())
    async with sdk(handler) as client:
        usage = UsageSummary()
        set_tool_context(ToolContext(project_root=tmp_path, session_dir=tmp_path, client=client, usage=usage))
        result = json.loads(await web_search.web_search("MTUM objective"))
    assert result["status"] == "ok" and result["sources"][0]["url"] == "https://www.ishares.com/mtum"
    artifact = tmp_path / result["artifact"]
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == result["sha256"]
    assert json.loads(artifact.read_text())["response"]["id"] == "msg_test"
    assert "summary" not in result and result["evidence_kind"] == "source_discovery"
    assert result["sources"][0]["snippet"] is None
    assert usage.total_tokens == 170
    assert calls[0]["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}]
    assert calls[0]["max_tokens"] == 1024 and calls[0]["thinking"] == {"type": "disabled"}
    assert len(calls) == 1


@pytest.mark.parametrize("invalid", ["max_tokens", "pause_turn", "no_search", "empty", "unsafe_url", "only_error", "malformed"])
async def test_native_search_never_treats_unsourced_or_incomplete_text_as_evidence(tmp_path, env, invalid):
    data = response()
    data["content"].append({"type": "text", "text": "Invented claim https://www.ishares.com/mtum", "citations": []})
    if invalid in {"max_tokens", "pause_turn"}:
        data["stop_reason"] = invalid
    elif invalid == "no_search":
        data["content"].pop(1)
    elif invalid == "empty":
        data["content"][1]["content"] = []
    elif invalid == "only_error":
        data["content"][1]["content"] = {"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"}
    elif invalid == "malformed":
        data["content"][1]["content"] = "not results"
    else:
        data["content"][1]["content"][0]["url"] = "file:///private/secret"
    async with sdk(lambda request: httpx.Response(200, json=data)) as client:
        usage = UsageSummary()
        set_tool_context(ToolContext(project_root=tmp_path, session_dir=tmp_path, client=client, usage=usage))
        result = json.loads(await web_search.web_search("MTUM"))
    assert result["status"] == "unavailable" and not result["sources"]
    assert usage.total_tokens == 170
    assert (tmp_path / result["artifact"]).exists()


async def test_search_failure_has_no_retry_and_per_role_attempt_cap(tmp_path, env):
    calls = []
    def handler(request):
        calls.append(True)
        return httpx.Response(429, json={"error": {"message": "private secret", "type": "rate_limit"}})
    async with sdk(handler) as client:
        set_tool_context(ToolContext(project_root=tmp_path, session_dir=tmp_path, client=client))
        results = [json.loads(await web_search.web_search("MTUM")) for _ in range(3)]
    assert len(calls) == 2
    assert all(item["status"] == "unavailable" for item in results)
    assert "private secret" not in json.dumps(results)
    assert len(list((tmp_path / "search_results").glob("*.json"))) == 2


async def test_native_requests_share_supplement_five_request_budget(tmp_path, env):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith('/messages'):
            return httpx.Response(200, json=response())
        return httpx.Response(200, json={"id":"c", "object":"chat.completion", "created":1, "model":"test",
            "choices":[{"index":0,"finish_reason":"stop","message":{"role":"assistant","content":"ok"}}]})
    async with sdk(handler) as client:
        limited = LimitedClient(client)
        for _ in range(4):
            await limited.create(model="test", messages=[])
        usage = UsageSummary()
        set_tool_context(ToolContext(project_root=tmp_path, session_dir=tmp_path, client=limited, usage=usage))
        assert json.loads(await web_search.web_search("MTUM"))["status"] == "ok"
        assert json.loads(await web_search.web_search("SPY"))["status"] == "unavailable"
    assert len(calls) == limited.requests == 5
    assert limited.usage.total_tokens == usage.total_tokens == 170


def test_explicit_env_file_maps_alias_without_overwriting_exported_key(tmp_path, env, monkeypatch):
    path = tmp_path / "shared.env"
    path.write_text("DeepSeekAPI=from-file\n")
    monkeypatch.delenv("DeepSeekAPI")
    monkeypatch.setenv("MOMENTUM_ENV_FILE", str(path))
    config.load_env(tmp_path)
    assert config.deepseek_api_key() == "from-file"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "exported")
    assert config.deepseek_api_key() == "exported"


async def test_timeout_and_cancellation_leave_diagnostics(tmp_path, env, monkeypatch):
    from momentum_research_agent.tools import deepseek_search
    monkeypatch.setattr(deepseek_search, "TIMEOUT_SECONDS", .01)
    async def slow(request):
        await asyncio.sleep(60)
    async with sdk(slow) as client:
        set_tool_context(ToolContext(project_root=tmp_path, session_dir=tmp_path, client=client))
        result = json.loads(await web_search.web_search("MTUM"))
        assert result["status"] == "unavailable"
        task = asyncio.create_task(web_search.web_search("SPY"))
        await asyncio.sleep(.001)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    files = list((tmp_path / "search_results").glob("*.json"))
    assert len(files) == 2
    assert any(json.loads(path.read_text())["status"] == "cancelled" for path in files)


async def test_outer_agent_timeout_keeps_interrupted_search_trace(tmp_path, env):
    from momentum_research_agent.agents.sub_agent import SubAgent
    from momentum_research_agent.agents.budget import LoopBudget
    from momentum_research_agent.errors import ToolExecutionTimeout
    from momentum_research_agent.models.schemas import Task
    from momentum_research_agent.state.traces import load_traces
    async def handler(request):
        if request.url.path.endswith('/messages'):
            await asyncio.sleep(60)
        return httpx.Response(200, json={"id":"c", "object":"chat.completion", "created":1, "model":"test",
            "choices":[{"index":0,"finish_reason":"tool_calls","message":{"role":"assistant","content":"",
                "tool_calls":[{"id":"ws", "type":"function", "function":{"name":"web_search", "arguments":'{"query":"MTUM"}'}}]}}]})
    task = Task(title="Investigate", assignment="MTUM", profile="technicals_analyst")
    async with sdk(handler) as client:
        agent = SubAgent(client, "test", tmp_path, budget=LoopBudget(tool_timeout_s=.02))
        with pytest.raises(ToolExecutionTimeout):
            await agent.run(task, None, tmp_path)
    traces = load_traces(tmp_path)
    assert len(traces) == 1 and traces[0].agent_id == task.id
    assert json.loads(traces[0].observation)["status"] == "cancelled"


@pytest.mark.parametrize("oversized", [False, True])
async def test_real_analyst_and_verifier_keep_discovery_unchecked_and_replayable(tmp_path, env, oversized):
    from momentum_research_agent.agents.sub_agent import SubAgent
    from momentum_research_agent.agents.verifier import Verifier
    from momentum_research_agent.models.schemas import Task
    from momentum_research_agent.state.traces import load_traces
    data = response()
    if oversized:
        data["usage"]["unexpected_metadata"] = "x" * 6000
        results = data["content"][1]["content"]
        results[0]["page_age"] = "x" * 6000
        results.append({"type": "web_search_result", "url": "https://www.sec.gov/mtum", "title": "MTUM",
                        "page_age": {"nested": "x" * 6000}})
        results.extend([{"type": "web_search_tool_result_error", "error_code": "limit" * 100}] * 100)
    chats = []
    def handler(request):
        if request.url.path.endswith('/messages'):
            return httpx.Response(200, json=data)
        chats.append(True)
        message = {"role":"assistant", "content":""}
        finish = "stop"
        if len(chats) in (1, 3):
            finish = "tool_calls"
            message["tool_calls"] = [{"id":"ws", "type":"function", "function":{"name":"web_search", "arguments":'{"query":"MTUM"}'}}]
        elif len(chats) == 2:
            message["content"] = json.dumps({"task_id":"t", "title":"MTUM", "agent_role":"technicals_analyst", "summary":"Evidence collected",
                "status":"complete", "findings":[{"id":"e1", "claim":"MTUM targets momentum", "category":"market_regime", "stance":"supporting", "source_url":"https://www.ishares.com/mtum"}]})
        else:
            message["content"] = json.dumps({"question":"MTUM", "summary":"Checked", "overall_status":"pass", "verdicts":[{
                "evidence_id":"e1", "claim":"MTUM targets momentum", "status":"verified", "rechecked_source":"https://www.ishares.com/mtum"}]})
        return httpx.Response(200, json={"id":"c", "object":"chat.completion", "created":1, "model":"test",
            "choices":[{"index":0,"finish_reason":finish,"message":message}], "usage":{"prompt_tokens":5,"completion_tokens":5,"total_tokens":10}})
    async with sdk(handler) as client:
        analyst = await SubAgent(client, "test", tmp_path).run(Task(title="MTUM", assignment="MTUM", profile="technicals_analyst"), None, tmp_path)
        verified = await Verifier(client, "test", tmp_path).run("MTUM", [analyst.report], tmp_path)
    assert analyst.usage.total_tokens == 190 and verified.usage.total_tokens == 0
    assert not analyst.report.findings and not verified.report.verdicts
    assert verified.report.overall_status == 'fail'
    assert any("MTUM targets momentum" in item for item in analyst.report.limitations)
    assert verified.report.gaps
    traces = load_traces(tmp_path)
    assert len(traces) == 1 and {t.agent_role for t in traces} == {"technicals_analyst"}
    assert all(not t.truncated and json.loads(t.observation)["sources"] for t in traces)
    for trace in traces:
        observation = json.loads(trace.observation)
        artifact = tmp_path / observation["artifact"]
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == observation["sha256"]
    assert len(list((tmp_path / "search_results").glob("*.json"))) == 1


async def test_recorded_search_preserves_results_when_second_action_hits_limit(tmp_path, env):
    # September 9 live Messages response; opaque encrypted payloads removed only.
    data = json.loads((Path(__file__).parent / "fixtures/deepseek_search_messages.json").read_text())
    async with sdk(lambda request: httpx.Response(200, json=data)) as client:
        usage = UsageSummary()
        set_tool_context(ToolContext(project_root=tmp_path, session_dir=tmp_path, client=client, usage=usage))
        result = json.loads(await web_search.web_search("MTUM objective"))
    assert result["status"] == "ok" and len(result["sources"]) == 3
    assert result["search_errors"] == ["max_uses_exceeded"]
    assert all(source["snippet"] is None for source in result["sources"])
    assert "summary" not in result
    assert result["usage"]["server_tool_use"]["web_search_requests"] == 2
    assert usage.total_tokens == 8788  # 7811 uncached + 384 cache-read + 593 output.
    assert json.loads((tmp_path / result["artifact"]).read_text())["response"] == data


async def test_search_redirect_is_not_followed_with_credentials(tmp_path, env):
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(307, headers={"location": "https://untrusted.example/messages"})
    async with sdk(handler) as client:
        set_tool_context(ToolContext(project_root=tmp_path, session_dir=tmp_path, client=client))
        result = json.loads(await web_search.web_search("MTUM"))
    assert result["status"] == "unavailable"
    assert calls == ["https://api.deepseek.com/anthropic/v1/messages"]


def test_discovery_guard_does_not_downgrade_unrelated_checked_sources():
    from momentum_research_agent.agents.verifier import _guard_source_discovery
    from momentum_research_agent.agents.ledger import record_trace
    from momentum_research_agent.models.schemas import ResearchReport, VerificationReport
    research = ResearchReport(task_id="t", title="Sources", agent_role="technicals_analyst", summary="Mixed sources", findings=[
        {"id": "lead", "claim": "Unchecked lead", "category": "other", "stance": "neutral", "source_url": "https://www.ishares.com/mtum"},
        {"id": "checked", "claim": "Content checked separately", "category": "other", "stance": "neutral", "source_url": "https://www.sec.gov/other"}])
    verification = VerificationReport(question="Sources", overall_status="pass", summary="Mixed checks", verdicts=[
        {"evidence_id": "lead", "claim": "Unchecked lead", "status": "verified", "rechecked_source": "https://www.ishares.com/mtum"},
        {"evidence_id": "checked", "claim": "Content checked separately", "status": "verified", "rechecked_source": "file_reader"}])
    failed = record_trace("web_search", {"query": "irrelevant"}, json.dumps({"provider": "deepseek_native", "status": "unavailable", "sources": []}))
    _guard_source_discovery(verification, [research], [failed])
    assert [v.status.value for v in verification.verdicts] == ["verified", "verified"]
    found = record_trace("web_search", {"query": "MTUM"}, json.dumps({"provider": "deepseek_native", "status": "ok",
        "evidence_kind": "source_discovery", "sources": [{"url": "https://www.ishares.com/mtum#1"}]}))
    _guard_source_discovery(verification, [research], [failed, found])
    assert [v.status.value for v in verification.verdicts] == ["unchecked", "verified"]


@pytest.mark.asyncio
async def test_reader_redirect_claim_cannot_pass_when_independent_recheck_fails(tmp_path):
    from momentum_research_agent.agents.verifier import Verifier
    from momentum_research_agent.agents.ledger import record_trace
    from momentum_research_agent.models.schemas import ResearchReport
    from momentum_research_agent.state.traces import append_traces
    from test_react_loop import FakeClient
    trace = record_trace('read_url', {'url':'https://example.com/fund'}, json.dumps({
        'status':'ok','evidence_kind':'page_content', 'url':'https://example.com/holdings.csv',
        'requested_url':'https://example.com/fund', 'text':'AAA 10%',
        'links':['https://example.com/other.csv']}), agent_role='momentum_analyst')
    append_traces(tmp_path,[trace])
    research = ResearchReport(task_id='t',title='Holdings',agent_role='momentum_analyst',summary='AAA 10%',findings=[
        {'id':'e','claim':'AAA 10%','category':'other','stance':'neutral','source_url':'https://example.com/holdings.csv'}])
    client = FakeClient([])
    async def failed(**kwargs): raise ValueError('Independent recheck failed')
    client.completions.create = failed
    result = await Verifier(client,'test',tmp_path).run('Holdings?', [research],tmp_path)
    assert result.report.verdicts[0].status.value == 'unchecked'
    assert result.report.gaps
