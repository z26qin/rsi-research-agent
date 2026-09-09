from datetime import date
import json

import numpy as np
import pandas as pd
import pytest

from momentum_research_agent import proxy_brief as brief
from momentum_research_agent import proxy_data
from momentum_research_agent.proxy_metrics import sessions


@pytest.fixture
def provider(monkeypatch):
    dates = sessions(date(2024, 1, 1), date(2026, 9, 4))
    panels = {symbol: pd.DataFrame({"Date": dates, "Close": 200.,
              "Adj Close": 100 * 1.001 ** np.arange(len(dates)), "Volume": 1000,
              "Dividends": 0., "Stock Splits": 0.}) for symbol in ("MTUM", "SPY")}
    def worker(source, start, end, destination, **kwargs):
        frame = panels[source] if source != "VIXCLS" else pd.DataFrame({"observation_date": ["2026-09-03"], "VIXCLS": [20.]})
        frame.to_parquet(destination, index=False)
    monkeypatch.setattr(proxy_data, "run_worker", worker)
    return panels


def test_brief_and_offline_replay_agree(provider, tmp_path):
    result = brief.run_proxy_brief(date(2026, 9, 4), tmp_path / "run")
    assert result.status == "partial"
    assert result.schema_version == "etf_proxy_brief_v1"
    assert result.llm_requests == 0
    assert result.metrics == brief.replay_snapshot(tmp_path / "run")
    assert result.vix["observation_date"] == "2026-09-03"
    assert result.vix["stale"] is True
    assert (tmp_path / "run/brief.md").is_file()
    assert "2026-09-04" in (tmp_path / "run/brief.md").read_text()
    assert "not a crash probability" in (tmp_path / "run/brief.md").read_text()


def test_missing_one_etf_withholds_all_core_metrics(provider, tmp_path):
    provider["SPY"] = provider["SPY"].iloc[:-1]
    result = brief.run_proxy_brief(date(2026, 9, 4), tmp_path / "run")
    assert result.status == "unavailable"
    assert result.metrics == {}
    assert json.loads((tmp_path / "run/brief.json").read_text())["status"] == "unavailable"


def test_previous_metrics_recomputed_and_revisions_block_comparison(provider, tmp_path):
    prior = tmp_path / "prior"
    brief.run_proxy_brief(date(2026, 9, 3), prior)
    payload = json.loads((prior / "brief.json").read_text())
    payload["metrics"]["MTUM.return_1d"] = 999
    (prior / "brief.json").write_text(json.dumps(payload))
    current = brief.run_proxy_brief(date(2026, 9, 4), tmp_path / "current", prior / "brief.json")
    assert current.changes["MTUM.return_1d"]["delta"] == pytest.approx(0, abs=1e-12)
    provider["MTUM"].loc[1, "Adj Close"] *= .99
    revised = brief.run_proxy_brief(date(2026, 9, 4), tmp_path / "revised", prior / "brief.json")
    assert not revised.changes
    assert "revision" in revised.comparison_note.lower()


def test_corrupt_snapshot_rejected_and_no_overwrite(provider, tmp_path):
    output = tmp_path / "run"
    brief.run_proxy_brief(date(2026, 9, 4), output)
    before = (output / "brief.json").read_bytes()
    with pytest.raises(FileExistsError):
        brief.run_proxy_brief(date(2026, 9, 4), output)
    assert (output / "brief.json").read_bytes() == before
    (output / "normalized/MTUM.parquet").write_bytes(b"changed")
    with pytest.raises(ValueError):
        brief.replay_snapshot(output)


def test_control_rejects_old_snapshot_relabelled_as_current(provider, tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'frontend/scripts'))
    from proxy_control_worker import validate_proxy
    output = tmp_path / 'run'
    brief.run_proxy_brief(date(2026, 9, 4), output)
    payload = json.loads((output / 'brief.json').read_text())
    payload['requested_as_of'] = '2026-09-08'
    (output / 'brief.json').write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='Snapshot target'):
        validate_proxy(output, '2026-09-08')


def test_different_report_type_cannot_be_compared(provider, tmp_path):
    previous = tmp_path / "old.json"
    previous.write_text('{"schema_version":"daily_brief_v1"}')
    result = brief.run_proxy_brief(date(2026, 9, 4), tmp_path / "run", previous)
    assert result.status == "partial"
    assert not result.changes


@pytest.mark.asyncio
async def test_cli_proxy_without_key_and_engine_still_requires_date(provider, tmp_path, monkeypatch):
    from momentum_research_agent import cli
    monkeypatch.setattr(cli, "make_client", lambda: pytest.fail("proxy must not construct LLM client"))
    args = cli.build_parser().parse_args(["--daily-brief", "--brief-source", "etf-proxy", "--as-of", "2026-09-04",
                                         "--session-dir", str(tmp_path / "run")])
    assert await cli.async_main(args) == 0
    assert json.loads((tmp_path / "run/brief.json").read_text())["schema_version"] == "etf_proxy_brief_v1"
    assert await cli.async_main(cli.build_parser().parse_args(["--daily-brief"])) == 2
    assert await cli.async_main(cli.build_parser().parse_args(["--brief-source", "etf-proxy"])) == 2


@pytest.mark.asyncio
async def test_cli_unavailable_and_default_target(provider, tmp_path, monkeypatch):
    from momentum_research_agent import cli
    monkeypatch.setattr(brief, "target_date", lambda requested: date(2026, 9, 4))
    provider["MTUM"] = provider["MTUM"].iloc[:-1]
    args = cli.build_parser().parse_args(["--daily-brief", "--brief-source", "etf-proxy", "--session-dir", str(tmp_path / "run")])
    assert await cli.async_main(args) == 2
    assert (tmp_path / "run/brief.json").is_file()


def test_optional_corrupt_vix_does_not_withhold_etf_metrics(provider, tmp_path, monkeypatch):
    original = brief.collect
    def corrupt(output, as_of):
        manifest = original(output, as_of)
        (output / "normalized/VIXCLS.parquet").write_bytes(b"corrupt")
        return manifest
    monkeypatch.setattr(brief, "collect", corrupt)
    result = brief.run_proxy_brief(date(2026, 9, 4), tmp_path / "run")
    assert result.status == "partial"
    assert result.metrics["MTUM.return_1d"] is not None
    assert not result.vix


@pytest.mark.asyncio
async def test_cli_crowding_sidecar_is_optional_replayable_and_nonblocking(provider, tmp_path, monkeypatch):
    from momentum_research_agent import cli, crowding_data
    from test_crowding_metrics import payload
    from momentum_research_agent.proxy_data import save_json
    monkeypatch.setattr(crowding_data, "run_worker", lambda symbol, path, timeout: save_json(path, payload(ticker=symbol)))
    args = cli.build_parser().parse_args(["--daily-brief", "--brief-source", "etf-proxy", "--with-crowding",
                                         "--as-of", "2026-09-04", "--session-dir", str(tmp_path / "run")])
    assert await cli.async_main(args) == 0
    report = json.loads((tmp_path / "run/brief.json").read_text())
    assert report["crowding"]["status"] == "partial"
    assert "Weighted overlap" in (tmp_path / "run/brief.md").read_text()
    assert brief.replay_crowding(tmp_path / "run") == report["crowding"]
    assert await cli.async_main(cli.build_parser().parse_args(["--with-crowding", "question"])) == 2
    assert await cli.async_main(cli.build_parser().parse_args(["--daily-brief", "--as-of", "2026-09-04", "--with-crowding"])) == 2
    def failure(*args, **kwargs): raise OSError("source down")
    monkeypatch.setattr(crowding_data, "run_worker", failure)
    result = brief.run_proxy_brief(date(2026, 9, 4), tmp_path / "failed", with_crowding=True)
    assert result.status == "partial"
    assert result.crowding["status"] == "unavailable"
    assert len(result.metrics) == 16


def test_optional_issuer_replay_with_unavailable_core(provider, tmp_path, monkeypatch):
    from momentum_research_agent import crowding_data
    from test_crowding_metrics import payload
    from momentum_research_agent.proxy_data import save_json
    provider["SPY"] = provider["SPY"].iloc[:-1]
    monkeypatch.setattr(crowding_data, "run_worker", lambda symbol, path, timeout: save_json(path, payload(ticker=symbol)))
    output = tmp_path / "run"
    result = brief.run_proxy_brief(date(2026, 9, 4), output, with_crowding=True)
    assert result.status == "unavailable"
    assert result.crowding["status"] == "partial"
    assert brief.replay_crowding(output) == result.crowding
