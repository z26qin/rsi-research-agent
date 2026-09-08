from datetime import date
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from test_proxy_brief import provider
from test_short_interest import network
from momentum_research_agent import proxy_brief
from momentum_research_agent import market_brief as market


@pytest.fixture
def snapshot(provider, tmp_path):
    root = tmp_path / "run"
    proxy_brief.run_proxy_brief(date(2026, 9, 4), root)
    return root


def test_questions_recomputed_and_reference_is_retrospective(snapshot):
    report = json.loads((snapshot / "brief.json").read_text())
    report["metrics"]["relative.return_21d"] = 999
    (snapshot / "brief.json").write_text(json.dumps(report))
    facts, holdings = market.price_facts(snapshot, date(2026, 5, 29))
    assert facts["metrics"]["relative.return_21d"] == 0
    assert facts["comparisons"]["previous_session"]["date"] == "2026-09-03"
    assert facts["comparisons"]["reference"]["date"] == "2026-05-29"
    assert "retrospective" in facts["comparison_method"]
    assert not holdings
    assert len(market.answers(facts, {})) == 5
    assert "证据不足" in market.answers(facts, {})["crowding"]


def test_corrupt_and_forward_reference_rejected(snapshot):
    with pytest.raises(ValueError):
        market.price_facts(snapshot, date(2026, 9, 4))
    (snapshot / "normalized/MTUM.parquet").write_bytes(b"bad")
    with pytest.raises(ValueError):
        market.price_facts(snapshot, None)


def test_short_interest_uses_disclosure_not_daily_change():
    si = {"latest_settlement": "2026-08-14", "latest_publication": "2026-08-25",
          "periods": {"latest": {"records": {"MTUM": {"short_shares": 1273798, "days_to_cover": 1}}},
                      "previous": {"records": {"MTUM": {"short_shares": 933278, "days_to_cover": 1}}},
                      "reference": {"records": {"MTUM": {"short_shares": 1801719, "days_to_cover": 1}}}},
          "basket": {"required_count": 2, "covered_count": 1, "covered_weight": .6, "total_weight": 1,
                     "weighted_days_to_cover": {"latest": None, "previous": None, "reference": None}}}
    text = market.answers({"metrics": {}, "comparisons": {}, "split_safe": {"MTUM": True}}, si)["short_interest"]
    assert "2026-08-14" in text and "2026-08-25" in text
    assert "+36.49%" in text and "-29.30%" in text
    assert "非每日" in text and "1/2" in text
    assert "short float" in text
    blocked = market.answers({"metrics": {}, "comparisons": {}, "split_safe": {"MTUM": False}}, si)
    assert "+36.49%" not in blocked["short_interest"]


@pytest.mark.asyncio
async def test_bounded_llm_selects_only_verified_answer_ids():
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(
        return_value=SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(
            content='{"focus":["volatility","crowding"]}', tool_calls=None))], usage=None)))))
    result = await market.interpret({"volatility": "recorded observation", "crowding": "insufficient"}, client)
    assert result["status"] == "ok"
    assert result["focus"] == ["volatility", "crowding"]
    kwargs = client.chat.completions.create.call_args.kwargs
    assert "tools" not in kwargs
    assert kwargs["max_tokens"] == 512
    assert client.chat.completions.create.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ['{"focus":["invented"]}', '{"focus":["crowding"],"claim":"buy"}', 'bad', '{"focus":["crowding","crowding"]}'])
async def test_llm_invalid_or_unavailable_falls_back(content):
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(
        return_value=SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(
            content=content, tool_calls=None))], usage=None)))))
    result = await market.interpret({"crowding": "insufficient"}, client)
    assert result["status"] == "fallback"
    assert result["llm_requests"] == 1
    assert result["focus"] == ["crowding"]


@pytest.mark.asyncio
async def test_market_cli_validates_modes_before_any_network(monkeypatch, tmp_path):
    from momentum_research_agent import cli
    for flags in (["--with-market-research"], ["--daily-brief", "--with-market-research"],
                  ["--reference-date", "2026-05-29"], ["--no-brief-llm"]):
        assert await cli.async_main(cli.build_parser().parse_args(flags)) == 2


@pytest.mark.asyncio
async def test_full_market_report_offline_replay_and_immutable(snapshot, network, monkeypatch):
    monkeypatch.setattr(market, "make_client", lambda: pytest.fail("offline must not request a key"))
    report = await market.run(snapshot, date(2026, 5, 29), llm=False)
    assert report.status == "partial" and report.interpretation["llm_requests"] == 0
    assert market.replay(snapshot)["answers"] == report.answers
    assert all(title in (snapshot / "market_brief.md").read_text() for title in market.TITLES.values())
    with pytest.raises(FileExistsError):
        await market.run(snapshot, llm=False)
    (snapshot / "market/short_interest/raw/20260814.csv").write_text("changed")
    with pytest.raises(ValueError):
        market.replay(snapshot)


@pytest.mark.asyncio
async def test_unscheduled_reference_and_no_reference(snapshot, network):
    report = await market.run(snapshot, llm=False)
    assert report.short_interest["periods"]["reference"] is None
    assert "参考结算日不可用" in report.answers["short_interest"]


@pytest.mark.asyncio
async def test_market_cli_recorded_public_data_no_key(provider, network, tmp_path, monkeypatch):
    from momentum_research_agent import cli, crowding_data
    from test_crowding_metrics import payload
    from momentum_research_agent.proxy_data import save_json
    monkeypatch.setattr(crowding_data, "run_worker", lambda symbol, path, timeout: save_json(path, payload(ticker=symbol)))
    monkeypatch.setattr(market, "make_client", lambda: pytest.fail("no API key required"))
    root = tmp_path / "cli"
    args = cli.build_parser().parse_args(["--daily-brief", "--brief-source", "etf-proxy", "--with-market-research",
        "--reference-date", "2026-05-29", "--no-brief-llm", "--as-of", "2026-09-04", "--session-dir", str(root)])
    assert await cli.async_main(args) == 0
    report = json.loads((root / "market_brief.json").read_text())
    assert "Top10" in report["answers"]["concentration"]
    assert report["short_interest"]["basket"]["covered_count"] == 0
    assert market.replay(root)["facts"] == report["facts"]


@pytest.mark.asyncio
async def test_no_short_interest_or_prices_still_answers_questions(provider, tmp_path, monkeypatch):
    from momentum_research_agent import short_interest
    provider["SPY"] = provider["SPY"].iloc[:-1]
    root = tmp_path / "unavailable"
    proxy_brief.run_proxy_brief(date(2026, 9, 4), root)
    monkeypatch.setattr(short_interest, "_attempt", lambda *args: (_ for _ in ()).throw(TimeoutError()))
    report = await market.run(root, llm=False)
    assert report.status == "unavailable"
    assert len(report.answers) == 5
    assert market.replay(root)["answers"] == report.answers


@pytest.mark.asyncio
async def test_missing_key_and_model_timeout_have_no_claims(monkeypatch):
    monkeypatch.setattr(market, "make_client", lambda: (_ for _ in ()).throw(RuntimeError("private secret")))
    result = await market.interpret({"crowding": "unknown"})
    assert result["llm_requests"] == 0 and "secret" not in json.dumps(result)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(side_effect=TimeoutError()))))
    result = await market.interpret({"crowding": "unknown"}, client)
    assert result["llm_requests"] == 1 and result["status"] == "fallback"


@pytest.mark.asyncio
async def test_prior_brief_same_disclosure_is_not_new_daily_reading(provider, network, tmp_path):
    prior = tmp_path / "prior"
    current = tmp_path / "current"
    proxy_brief.run_proxy_brief(date(2026, 9, 3), prior)
    await market.run(prior, llm=False)
    proxy_brief.run_proxy_brief(date(2026, 9, 4), current)
    report = await market.run(current, llm=False, previous=prior / "brief.json")
    assert "无新披露" in report.facts["si_update"]
    assert market.replay(current)["answers"] == report.answers
    # The current run is self-contained; source changes afterwards cannot alter it.
    (prior / "market/short_interest/raw/20260814.csv").write_text("changed")
    assert market.replay(current)["answers"] == report.answers


def test_finra_split_flag_blocks_share_change():
    record = {"short_shares": 100, "days_to_cover": 1, "split_flag": "S"}
    si = {"latest_settlement": "2026-08-14", "latest_publication": "2026-08-25",
          "periods": {"latest": {"records": {"MTUM": record}}, "previous": {"records": {"MTUM": record}}}}
    answer = market.answers({"split_safe": {"MTUM": True}}, si)["short_interest"]
    assert "+0.00%" not in answer


def test_missing_action_session_cannot_exclude_split(provider, tmp_path):
    provider["MTUM"] = provider["MTUM"].loc[provider["MTUM"].Date != "2026-06-01"]
    root = tmp_path / "gap"
    proxy_brief.run_proxy_brief(date(2026, 9, 4), root)
    facts, _ = market.price_facts(root, date(2026, 5, 29))
    assert facts["split_safe"]["MTUM"] is False


@pytest.mark.asyncio
async def test_supplied_sdk_client_has_retries_disabled():
    from unittest.mock import Mock
    create = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop",
        message=SimpleNamespace(content='{"focus":["crowding"]}', tool_calls=None))], usage=None))
    supplied = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    supplied.with_options = Mock(return_value=supplied)
    result = await market.interpret({"crowding": "uncertain"}, supplied)
    supplied.with_options.assert_called_once_with(max_retries=0)
    assert result["status"] == "ok"


def test_zero_adv_dtc_rendered_unavailable():
    si = {"latest_settlement": "2026-08-14", "latest_publication": "2026-08-25", "periods": {
        "latest": {"records": {"MTUM": {"short_shares": 100, "days_to_cover": None, "published_days_to_cover": 999.99}}}}}
    answer = market.answers({}, si)["short_interest"]
    assert "999.99" not in answer and "days-to-cover 不可用" in answer


def test_settlement_before_action_window_withholds_share_change():
    record = {"short_shares": 100, "days_to_cover": 1, "split_flag": ""}
    si = {"latest_settlement": "2026-08-14", "latest_publication": "2026-08-25", "periods": {
        "latest": {"records": {"MTUM": record}},
        "reference": {"settlement_date": "2026-05-29", "records": {"MTUM": record}}}}
    facts = {"split_safe": {"MTUM": True}, "price_coverage_start": {"MTUM": "2026-06-01"}}
    assert "+0.00%" not in market.answers(facts, si)["short_interest"]
