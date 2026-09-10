"""Small behavioral suite for the daily-to-research handoff."""
import asyncio
import ast
from copy import deepcopy
from datetime import date
import json
from types import SimpleNamespace

import pytest

from test_proxy_brief import provider
from test_short_interest import network
from momentum_research_agent import brief_research as bridge, market_brief, proxy_brief
from momentum_research_agent.errors import AgentRuntimeError


def facts():
    return {"facts": {"target_date": "2026-09-04", "status": "partial",
        "metrics": {"MTUM.return_1d": .01, "MTUM.volatility_21d": .2},
        "comparisons": {"previous_session": {"metrics": {"MTUM.volatility_21d": .19}}},
        "crowding": {"funds": {"MTUM": {"status": "ok", "stale": False}}}},
        "short_interest": {"periods": {"latest": {"records": {"MTUM": {"short_shares": 10}}}}}}


def test_only_material_price_or_volatility_changes_trigger():
    data = facts()
    assert bridge.select_alert(data) is None
    data["facts"]["metrics"]["MTUM.return_1d"] = -.031
    assert bridge.select_alert(data).kind == "price_move"
    data["facts"]["metrics"]["MTUM.return_1d"] = .01
    data["facts"]["metrics"]["MTUM.volatility_21d"] = .30
    assert bridge.select_alert(data).kind == "volatility_jump"


def test_only_new_optional_data_loss_triggers_not_permanent_limitations():
    old = facts()
    new = deepcopy(old)
    new["short_interest"]["periods"]["latest"] = None
    assert bridge.select_alert(new) is None
    assert bridge.select_alert(new, old).kind == "short_interest_gap"
    assert bridge.select_alert(new, new) is None
    new = deepcopy(old)
    new["facts"]["crowding"] = {}
    assert bridge.select_alert(new, old).kind == "holdings_gap"
    new["facts"]["status"] = "unavailable"
    assert bridge.select_alert(new, old) is None


@pytest.fixture
async def saved(provider, network, tmp_path):
    provider["MTUM"].loc[provider["MTUM"].index[-1], "Adj Close"] *= .94
    root = tmp_path / "brief"
    proxy_brief.run_proxy_brief(date(2026, 9, 4), root)
    await market_brief.run(root, llm=False)
    return root


class Client:
    def __init__(self, failure=None):
        self.chat = self.completions = self
        self.calls = []
        self.failure = failure

    def with_options(self, **kwargs):
        assert kwargs == {"max_retries": 0}
        return self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure:
            raise self.failure
        payload = {"task_id": "model", "title": "Unresolved anomaly", "agent_role": "technicals_analyst",
            "summary": "Cannot establish a cause.", "status": "insufficient_evidence", "findings": [],
            "unanswered_questions": ["Need independent evidence explaining the price move."], "contradictions": []}
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(
            content=json.dumps(payload), tool_calls=None))], usage=None)


async def test_report_saved_first_feedback_persisted_without_policy_promotion(saved, tmp_path):
    before = {name: (saved / name).read_bytes() for name in ("brief.json", "market_brief.json", "market_brief.md")}
    client = Client()
    result = await bridge.run(saved, tmp_path, client=client)
    assert result.status == "partial" and result.llm_requests == 1
    assert result.session_dir and (result.session_dir / "verification.json").exists()
    assert (tmp_path / "reports/gap_ledger.jsonl").exists()
    assert all((saved / name).read_bytes() == value for name, value in before.items())
    assert "Cannot establish a cause" not in (saved / "research_addendum.md").read_text()
    assert not (tmp_path / "reports/policies/experiments").exists()
    assert client.calls[0]["max_tokens"] == 2048
    again = await bridge.run(saved, tmp_path, client=Client(AssertionError("duplicate request")))
    assert again == result


async def test_same_date_dedup_across_run_directories(saved, tmp_path):
    import shutil
    other = tmp_path / "other"
    shutil.copytree(saved, other)
    await bridge.run(saved, tmp_path, client=Client())
    result = await bridge.run(other, tmp_path, client=Client(AssertionError("duplicate date")))
    assert result.status == "duplicate" and result.llm_requests == 0


async def test_disabled_or_missing_key_never_calls_llm(saved, tmp_path, monkeypatch):
    disabled = await bridge.run(saved, tmp_path, enabled=False)
    assert disabled.status == "disabled" and disabled.llm_requests == 0
    import shutil
    other = tmp_path / "other"
    shutil.copytree(saved, other, ignore=shutil.ignore_patterns("research_status.json", "research_addendum.md"))
    monkeypatch.setattr(bridge, "make_client", lambda: (_ for _ in ()).throw(RuntimeError("private secret")))
    result = await bridge.run(other, tmp_path)
    assert result.status == "unavailable" and result.llm_requests == 0
    assert "private secret" not in (other / "research_status.json").read_text()


async def test_model_failure_preserves_brief_and_importable_failed_session(saved, tmp_path):
    from momentum_research_agent.eval.session_cases import import_session_cases
    result = await bridge.run(saved, tmp_path, client=Client(TimeoutError("private secret")))
    assert result.status == "failed" and result.llm_requests == 1
    assert (saved / "market_brief.md").exists()
    cases = import_session_cases(tmp_path, result.session_dir)
    assert cases and all(case.curation_status == "pending" for case in cases)
    assert "private secret" not in (saved / "research_status.json").read_text()


async def test_cancelled_research_is_recorded_and_cancellation_propagates(saved, tmp_path):
    with pytest.raises(asyncio.CancelledError):
        await bridge.run(saved, tmp_path, client=Client(asyncio.CancelledError()))
    result = json.loads((saved / "research_status.json").read_text())
    assert result["status"] == "cancelled"


async def test_corrupt_brief_fails_closed_without_research(saved, tmp_path):
    (saved / "normalized/MTUM.parquet").write_bytes(b"corrupt")
    result = await bridge.run(saved, tmp_path, client=Client(AssertionError("untrusted data")))
    assert result.status == "unavailable" and result.llm_requests == 0


async def test_budget_client_caps_actual_requests_and_rejects_truncated_output():
    client = Client()
    limited = bridge.LimitedClient(client)
    for _ in range(5):
        await limited.create(model="test", messages=[])
    with pytest.raises(AgentRuntimeError):
        await limited.create(model="test", messages=[])
    assert len(client.calls) == 5


async def test_supplement_rejects_hidden_tools_and_incomplete_model_response():
    from momentum_research_agent.errors import UnauthorizedTool
    class BadClient(Client):
        finish = "tool_calls"
        async def create(self, **kwargs):
            assert all(t["function"]["name"] == "web_search" for t in kwargs.get("tools", []))
            call = SimpleNamespace(function=SimpleNamespace(name="engine_query"))
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason=self.finish,
                message=SimpleNamespace(tool_calls=[call], content="invented"))], usage=None)
    client = BadClient()
    limited = bridge.LimitedClient(client)
    tools = [{"function": {"name": name}} for name in ("web_search", "market_data", "engine_query")]
    with pytest.raises(UnauthorizedTool):
        await limited.create(model="test", tools=tools)
    client.finish = "length"
    with pytest.raises(AgentRuntimeError):
        await limited.create(model="test", tools=tools)


async def test_cli_research_failure_does_not_change_delivered_brief_exit(provider, network, tmp_path, monkeypatch, capsys):
    from momentum_research_agent import cli, crowding_data
    from test_crowding_metrics import payload
    from momentum_research_agent.proxy_data import save_json
    monkeypatch.setattr(crowding_data, "run_worker", lambda symbol, path, timeout: save_json(path, payload(ticker=symbol)))
    root = tmp_path / "cli"
    started = []
    async def fail_after_publication(output, *args, **kwargs):
        assert (output / "market_brief.md").exists()
        assert "Market brief:" in capsys.readouterr().out
        assert kwargs["enabled"] is False
        started.append(True)
        raise RuntimeError("private diagnostic")
    monkeypatch.setattr(bridge, "run", fail_after_publication)
    args = cli.build_parser().parse_args(["--daily-brief", "--brief-source", "etf-proxy", "--with-market-research",
        "--as-of", "2026-09-04", "--no-brief-llm", "--session-dir", str(root)])
    assert await cli.async_main(args) == 0
    assert started == [True]
    assert "private diagnostic" not in capsys.readouterr().out
    assert await cli.async_main(cli.build_parser().parse_args(["--no-brief-research"])) == 2


async def test_quiet_day_makes_no_extra_request(provider, network, tmp_path):
    root = tmp_path / "quiet"
    proxy_brief.run_proxy_brief(date(2026, 9, 4), root)
    await market_brief.run(root, llm=False)
    result = await bridge.run(root, tmp_path, client=Client(AssertionError("no trigger")))
    assert result.status == "no_alert" and result.llm_requests == 0


@pytest.mark.parametrize("failure", ["timeout", "invalid", "omitted", "exhausted", None])
async def test_recheck_requires_valid_complete_evidence_verdicts(saved, tmp_path, failure):
    class RecheckClient(Client):
        async def create(self, **kwargs):
            response = await super().create(**kwargs)
            message = response.choices[0].message
            if len(self.calls) == 1:
                payload = json.loads(message.content)
                payload.update(status="complete", findings=[{"id": "e1", "claim": "Rates caused the move",
                    "category": "market_regime", "stance": "supporting",
                    "source_url": "https://example.com/evidence", "confidence": "high"}])
                message.content = json.dumps(payload)
            elif failure == "timeout":
                raise TimeoutError()
            elif failure == "invalid":
                message.content = "not JSON"
            elif failure == "omitted":
                message.content = json.dumps({"question": "q", "overall_status": "pass", "summary": "done", "verdicts": []})
            elif failure is None:
                # The verifier must use the actual task-scoped ID it received.
                prompt = kwargs['messages'][1]['content']
                evidence_id = ast.literal_eval(prompt.split('Input JSON:\n',1)[1])['reports'][0]['findings'][0]['id']
                message.content = json.dumps({"question": "q", "overall_status": "pass", "summary": "checked",
                    "verdicts": [{"evidence_id": evidence_id, "claim": "Rates caused the move", "status": "verified",
                                  "rechecked_source": "https://example.com/evidence"}]})
            else:
                response.choices[0].finish_reason = "tool_calls"
                message.content = json.dumps({"question": "q", "overall_status": "pass", "summary": "done", "verdicts": []})
                message.tool_calls = [SimpleNamespace(id="read", type="function", function=SimpleNamespace(
                    name="file_reader", arguments='{"path":"missing-evidence.txt"}'))]
            return response
    result = await bridge.run(saved, tmp_path, client=RecheckClient())
    if failure is None:
        assert result.status == "complete" and result.llm_requests == 2
        assert "[verified] Rates caused the move" in (saved / "research_addendum.md").read_text()
        return
    assert result.status == "failed"
    assert result.llm_requests >= 2
    assert "[verified]" not in (saved / "research_addendum.md").read_text()
    verification = json.loads((result.session_dir / "verification.json").read_text())
    assert verification["gaps"]
    assert (tmp_path / "reports/gap_ledger.jsonl").exists()


async def test_analyst_requires_terminal_stop_not_tool_call_content(saved, tmp_path):
    class UnfinishedClient(Client):
        async def create(self, **kwargs):
            response = await super().create(**kwargs)
            response.choices[0].finish_reason = "tool_calls"
            response.choices[0].message.tool_calls = [SimpleNamespace(id="read", type="function", function=SimpleNamespace(
                name="file_reader", arguments='{"path":"missing-evidence.txt"}'))]
            return response
    result = await bridge.run(saved, tmp_path, client=UnfinishedClient())
    assert result.status == "failed" and result.llm_requests == 3


@pytest.mark.parametrize("finish", ["stop", "length"])
async def test_failed_final_response_keeps_prior_search_trace(saved, tmp_path, monkeypatch, finish):
    from momentum_research_agent.tools.registry import get_tool
    monkeypatch.setattr(get_tool("web_search"), "fn", lambda **kwargs: "Recorded independent observation")
    class SearchThenFail(Client):
        async def create(self, **kwargs):
            response = await super().create(**kwargs)
            choice = response.choices[0]
            if len(self.calls) == 1:
                choice.finish_reason = "tool_calls"
                choice.message.tool_calls = [SimpleNamespace(id="search", function=SimpleNamespace(
                    name="web_search", arguments='{"query":"MTUM move"}'))]
            else:
                choice.finish_reason, choice.message.content = finish, "broken final JSON"
            return response
    result = await bridge.run(saved, tmp_path, client=SearchThenFail())
    assert result.status == "failed" and result.llm_requests == 2
    assert "Recorded independent observation" in (result.session_dir / "traces.jsonl").read_text()
