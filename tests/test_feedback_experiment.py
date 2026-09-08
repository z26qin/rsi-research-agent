"""Safety boundaries for the standalone, non-promoting experiment."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "feedback_experiment.py"
spec = importlib.util.spec_from_file_location("feedback_experiment", SCRIPT)
experiment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(experiment)


def client():
    response = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop")])
    create = AsyncMock(return_value=response)
    raw = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    raw.with_options = lambda **kwargs: raw
    return raw, create


@pytest.mark.asyncio
async def test_budget_persists_across_restarts_and_counts_failed_requests(tmp_path):
    state = {"attempts": 19}
    experiment.save(tmp_path / "state.json", state)
    raw, create = client()
    create.side_effect = RuntimeError("private provider detail")
    bounded = experiment.BoundedClient(raw, tmp_path, state)
    with pytest.raises(RuntimeError):
        await bounded.chat.completions.create(model="test")
    restored = experiment.read(tmp_path / "state.json")
    assert restored["attempts"] == 20
    with pytest.raises(experiment.LLMRequestBudgetExceeded):
        await experiment.BoundedClient(raw, tmp_path, restored).chat.completions.create()
    assert create.await_count == 1


@pytest.mark.asyncio
async def test_request_caps_and_truncation(tmp_path):
    raw, create = client()
    bounded = experiment.BoundedClient(raw, tmp_path, {"attempts": 0})
    assert bounded.with_options(max_retries=8) is bounded
    await bounded.chat.completions.create(max_tokens=99999, timeout=999)
    assert create.call_args.kwargs["max_tokens"] == 2048
    assert create.call_args.kwargs["timeout"] == 40
    create.return_value.choices[0].finish_reason = "length"
    with pytest.raises(ValueError):
        await bounded.chat.completions.create()
    assert experiment.read(tmp_path / "responses" / "2.json")["finish_reason"] == "length"


@pytest.mark.parametrize("patch", [
    {}, {"prompt_overlays": {"verifier": "change"}},
    {"prompt_overlays": {"flow_analyst": "x"}, "task_templates": {"source_quality": "x"}},
    {"prompt_overlays": {"flow_analyst": "x", "momentum_analyst": "y"}},
    {"prompt_overlays": {"flow_analyst": " "}},
])
def test_rejects_nonminimal_patch(patch):
    with pytest.raises(ValueError):
        experiment.prompt_only(experiment.PolicyPatch.model_validate(patch), "flow_analyst")


def test_accepts_one_target_overlay():
    experiment.prompt_only(experiment.PolicyPatch(prompt_overlays={"flow_analyst": "Cite evidence."}), "flow_analyst")


def test_lock_prevents_concurrent_runs(tmp_path):
    with experiment.locked(tmp_path):
        with pytest.raises(BlockingIOError):
            with experiment.locked(tmp_path):
                pass
    with experiment.locked(tmp_path):
        pass


def response(content=None, tool=None):
    from test_replay_runner import FakeResponse, FakeToolCall, _message
    calls = [FakeToolCall("call", tool[0], json.dumps(tool[1]))] if tool else []
    return FakeResponse(_message(content, calls), finish_reason="tool_calls" if calls else "stop", model="fixed-model")


def report(passing=True):
    return json.dumps({"task_id": "test", "agent_role": "flow_analyst", "title": "Test",
        "summary": "Test", "status": "complete" if passing else "partial", "findings": [{
            "claim": "Observed fact", "category": "other", "stance": "neutral",
            "source_name": "web_search", "source_url": "https://example.test/filing",
            "excerpt": "Synthetic filing evidence.", "confidence": "medium"}]})


def prepared(tmp_path):
    from test_live_compare import _case, _expectation
    target = _case(tmp_path, "target", "https://example.test/filing Synthetic filing evidence.")
    guard = _case(tmp_path, "guard", "https://example.test/filing Synthetic filing evidence.")
    baseline = experiment.PolicyStore(tmp_path).load_version(target.policy_version_id)
    experiment.save(tmp_path / "baseline.json", baseline.model_dump(mode="json"))
    experiment.save(tmp_path / "captured-cases.json", [target.model_dump(mode="json")])
    experiment.save(tmp_path / "reviewed-cases.json", [c.model_dump(mode="json") for c in [target, guard]])
    experiment.save(tmp_path / "expectations.json", {"expectations": [
        _expectation(target, kind="target").model_dump(mode="json"),
        _expectation(guard, kind="guard").model_dump(mode="json")]})
    experiment.save(tmp_path / "state.json", {"status": "review_required", "attempts": 2})
    return target, guard


def replay_responses(case, passing):
    trace = case.tool_traces[0]
    return [response(tool=(trace.tool, trace.arguments)), response(report(passing))]


@pytest.mark.asyncio
async def test_full_shadow_preserves_active_and_cannot_repeat(tmp_path):
    from test_replay_runner import FakeClient
    target, guard = prepared(tmp_path)
    active = experiment.PolicyStore(tmp_path).active_path.read_bytes()
    raw = FakeClient(replay_responses(target, False) + replay_responses(guard, True) +
        [response(json.dumps({"prompt_overlays": {"flow_analyst": "Cite observed facts."}}))] +
        replay_responses(target, False) + replay_responses(target, True) +
        replay_responses(guard, True) + replay_responses(guard, True))
    state = await experiment.run(tmp_path, raw)
    assert state["status"] == "shadow_complete", state
    assert state["attempts"] == 15
    assert state["promoted"] is False
    reflection_input = raw.calls[4]["messages"][1]["content"]
    assert "allowed_report_statuses" in reflection_input
    assert "failed_baseline_report" in reflection_input
    assert guard.case_id not in reflection_input
    assert experiment.PolicyStore(tmp_path).active_path.read_bytes() == active
    assert not (tmp_path / "reports" / "gap_ledger.jsonl").exists()
    count = len(raw.calls)
    assert await experiment.run(tmp_path, raw) == state
    assert len(raw.calls) == count


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["pass", "malformed", "invalid_patch", "budget", "bad_hash"])
async def test_stops_without_promotion(tmp_path, mode):
    from test_replay_runner import FakeClient
    target, guard = prepared(tmp_path)
    replies = replay_responses(target, mode == "pass") + replay_responses(guard, True)
    if mode == "malformed":
        replies[1] = response("not json")
    if mode == "invalid_patch":
        replies.append(response('{"task_templates":{"source_quality":"change"}}'))
    if mode == "budget":
        experiment.save(tmp_path / "state.json", {"status": "review_required", "attempts": 20})
    if mode == "bad_hash":
        data = experiment.read(tmp_path / "expectations.json")
        data["expectations"][0]["case_sha256"] = "0" * 64
        experiment.save(tmp_path / "expectations.json", data)
    raw = FakeClient(replies)
    state = await experiment.run(tmp_path, raw)
    assert state["status"] in {"error", "unscorable", "target_not_reproduced_or_guard_failed"}
    assert state["attempts"] <= 20
    assert not (tmp_path / "candidate.json").exists()
    if mode in {"bad_hash", "budget"}:
        assert not raw.calls


@pytest.mark.asyncio
async def test_waits_for_human_and_sanitizes_error(tmp_path):
    raw, create = client()
    experiment.save(tmp_path / "state.json", {"status": "review_required", "attempts": 2})
    assert (await experiment.run(tmp_path, raw))["status"] == "review_required"
    assert create.await_count == 0
    experiment.save(tmp_path / "reviewed-cases.json", [])
    experiment.save(tmp_path / "expectations.json", {"private": "secret"})
    state = await experiment.run(tmp_path, raw)
    assert state["status"] == "error"
    assert "secret" not in (tmp_path / "state.json").read_text()


@pytest.mark.asyncio
async def test_capture_real_engine_with_fake_llm(tmp_path, monkeypatch):
    from test_replay_runner import FakeClient
    monkeypatch.delenv("MOMENTUM_ENGINE_DIR", raising=False)
    monkeypatch.delenv("MOMENTUM_DISABLE_PIPELINE", raising=False)
    raw = FakeClient([response(tool=("engine_query", {"ticker": "SPY", "end": "2026-05-29"})),
        response(json.dumps({"task_id": "test", "agent_role": "momentum_analyst", "title": "Test",
            "summary": "Need crowding evidence", "status": "partial", "findings": [],
            "unanswered_questions": ["Ticker crowding is not established."]}))])
    state = await experiment.run(tmp_path, raw)
    assert state["status"] == "review_required", state
    assert state["attempts"] == 2
    assert (tmp_path / "session" / "traces.jsonl").exists()
    assert not experiment.PolicyStore(tmp_path).active_path.exists()


@pytest.mark.asyncio
async def test_budget_exhaustion_inside_comparison_is_not_completion(tmp_path):
    from test_replay_runner import FakeClient
    target, guard = prepared(tmp_path)
    experiment.save(tmp_path / "state.json", {"status": "review_required", "attempts": 15})
    raw = FakeClient(replay_responses(target, False) + replay_responses(guard, True) +
        [response('{"prompt_overlays":{"flow_analyst":"Cite observed facts."}}')])
    state = await experiment.run(tmp_path, raw)
    assert state["status"] == "shadow_failed"
    assert state["attempts"] == 20
