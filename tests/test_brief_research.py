"""Small behavioral suite for the daily-to-research handoff."""

import pytest

from proxy_fixtures import provider  # noqa: F401 -- pytest fixture
from short_interest_fixtures import network  # noqa: F401 -- pytest fixture
from momentum_research_agent import brief_research as bridge


@pytest.mark.usefixtures("provider", "network")
async def test_cli_research_failure_does_not_change_delivered_brief_exit(
    tmp_path, monkeypatch, capsys
):
    from momentum_research_agent import cli, crowding_data
    from test_crowding_metrics import payload
    from momentum_research_agent.proxy_data import save_json

    monkeypatch.setattr(
        crowding_data,
        "run_worker",
        lambda symbol, path, timeout: save_json(path, payload(ticker=symbol)),
    )
    root = tmp_path / "cli"
    started = []

    async def fail_after_publication(output, *args, **kwargs):
        assert (output / "market_brief.md").exists()
        assert "Market brief:" in capsys.readouterr().out
        assert kwargs["enabled"] is False
        started.append(True)
        raise RuntimeError("private diagnostic")

    monkeypatch.setattr(bridge, "run", fail_after_publication)
    args = cli.build_parser().parse_args(
        [
            "--daily-brief",
            "--brief-source",
            "etf-proxy",
            "--with-market-research",
            "--as-of",
            "2026-09-04",
            "--no-brief-llm",
            "--session-dir",
            str(root),
        ]
    )
    assert await cli.async_main(args) == 0
    assert started == [True]
    assert "private diagnostic" not in capsys.readouterr().out
    assert (
        await cli.async_main(cli.build_parser().parse_args(["--no-brief-research"]))
        == 2
    )
