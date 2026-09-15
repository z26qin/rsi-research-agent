"""Native search contract through the real SDK, with offline HTTP responses."""

import hashlib
import json

import httpx
from openai import AsyncOpenAI
import pytest


def response():
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "deepseek-v4-flash",
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "content": [
            {
                "id": "ws_1",
                "type": "server_tool_use",
                "name": "web_search",
                "input": {"query": "MTUM objective"},
            },
            {
                "type": "web_search_tool_result",
                "tool_use_id": "ws_1",
                "content": [
                    {
                        "type": "web_search_result",
                        "url": "https://www.ishares.com/mtum",
                        "title": "MTUM",
                        "page_age": None,
                        "encrypted_content": "opaque",
                    }
                ],
            },
        ],
        "usage": {
            "input_tokens": 100,
            "cache_read_input_tokens": 40,
            "cache_creation_input_tokens": 10,
            "output_tokens": 20,
            "server_tool_use": {"web_search_requests": 1},
        },
    }


@pytest.fixture
def env(monkeypatch):
    for name in (
        "DEEPSEEK_API_KEY",
        "DeepSeekAPI",
        "MOMENTUM_ENV_FILE",
        "SERPER_API_KEY",
        "TAVILY_API_KEY",
        "WEB_SEARCH_PROVIDER",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DeepSeekAPI", "test-not-secret")


def sdk(handler):
    return AsyncOpenAI(
        api_key="test-not-secret",
        base_url="https://api.deepseek.com",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )


async def test_real_analyst_and_verifier_keep_discovery_unchecked_and_replayable(
    tmp_path, env
):
    from momentum_research_agent.agents.sub_agent import SubAgent
    from momentum_research_agent.agents.verifier import Verifier
    from momentum_research_agent.models.schemas import Task
    from momentum_research_agent.state.traces import load_traces

    data = response()
    data["usage"]["unexpected_metadata"] = "x" * 6000
    results = data["content"][1]["content"]
    results[0]["page_age"] = "x" * 6000
    results.append(
        {
            "type": "web_search_result",
            "url": "https://www.sec.gov/mtum",
            "title": "MTUM",
            "page_age": {"nested": "x" * 6000},
        }
    )
    results.extend(
        [{"type": "web_search_tool_result_error", "error_code": "limit" * 100}] * 100
    )
    chats = []

    def handler(request):
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json=data)
        chats.append(True)
        message = {"role": "assistant", "content": ""}
        finish = "stop"
        if len(chats) in (1, 3):
            finish = "tool_calls"
            message["tool_calls"] = [
                {
                    "id": "ws",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": '{"query":"MTUM"}'},
                }
            ]
        elif len(chats) == 2:
            message["content"] = json.dumps(
                {
                    "task_id": "t",
                    "title": "MTUM",
                    "agent_role": "technicals_analyst",
                    "summary": "Evidence collected",
                    "status": "complete",
                    "findings": [
                        {
                            "id": "e1",
                            "claim": "MTUM targets momentum",
                            "category": "market_regime",
                            "stance": "supporting",
                            "source_url": "https://www.ishares.com/mtum",
                        }
                    ],
                }
            )
        else:
            message["content"] = json.dumps(
                {
                    "question": "MTUM",
                    "summary": "Checked",
                    "overall_status": "pass",
                    "verdicts": [
                        {
                            "evidence_id": "e1",
                            "claim": "MTUM targets momentum",
                            "status": "verified",
                            "rechecked_source": "https://www.ishares.com/mtum",
                        }
                    ],
                }
            )
        return httpx.Response(
            200,
            json={
                "id": "c",
                "object": "chat.completion",
                "created": 1,
                "model": "test",
                "choices": [{"index": 0, "finish_reason": finish, "message": message}],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 5,
                    "total_tokens": 10,
                },
            },
        )

    async with sdk(handler) as client:
        analyst = await SubAgent(client, "test", tmp_path).run(
            Task(title="MTUM", assignment="MTUM", profile="technicals_analyst"),
            None,
            tmp_path,
        )
        verified = await Verifier(client, "test", tmp_path).run(
            "MTUM", [analyst.report], tmp_path
        )
    assert analyst.usage.total_tokens == 190 and verified.usage.total_tokens == 0
    assert not analyst.report.findings and not verified.report.verdicts
    assert verified.report.overall_status == "fail"
    assert any("MTUM targets momentum" in item for item in analyst.report.limitations)
    assert verified.report.gaps
    traces = load_traces(tmp_path)
    assert len(traces) == 1 and {t.agent_role for t in traces} == {"technicals_analyst"}
    assert all(not t.truncated and json.loads(t.observation)["sources"] for t in traces)
    for trace in traces:
        observation = json.loads(trace.observation)
        artifact = tmp_path / observation["artifact"]
        assert (
            hashlib.sha256(artifact.read_bytes()).hexdigest() == observation["sha256"]
        )
    assert len(list((tmp_path / "search_results").glob("*.json"))) == 1
