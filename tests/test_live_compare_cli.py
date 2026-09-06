from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from momentum_research_agent import cli


def test_parser_accepts_explicit_import_and_bounded_live_compare_options() -> None:
    parser = cli.build_parser()

    imported = parser.parse_args(["--import-session", "/tmp/session"])
    assert imported.import_session == Path("/tmp/session")

    live = parser.parse_args(
        [
            "--live-compare",
            "--baseline-policy", "abc123abc123",
            "--candidate-policy", "def456def456",
            "--cases", "cases.json",
            "--expectations", "expectations.json",
            "--max-cases", "2",
            "--repeats", "1",
            "--max-llm-calls", "12",
            "--max-output-tokens", "1024",
            "--max-turns", "3",
            "--llm-timeout-s", "40",
            "--overall-deadline-s", "90",
        ]
    )
    assert live.live_compare is True
    assert live.max_llm_calls == 12
    assert live.max_output_tokens == 1024
    assert live.max_turns == 3

    with pytest.raises(SystemExit):
        parser.parse_args(["--live-compare", "--max-llm-calls", "0"])
    for value in ("nan", "inf", "-inf"):
        with pytest.raises(SystemExit):
            parser.parse_args(["--live-compare", "--llm-timeout-s", value])


@pytest.mark.asyncio
async def test_import_session_cli_is_offline_and_does_not_make_a_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[Path, Path]] = []
    monkeypatch.setattr(cli, "find_project_root", lambda: tmp_path)
    monkeypatch.setattr(
        cli,
        "import_session_cases",
        lambda root, session: calls.append((root, session)) or [object(), object()],
    )
    monkeypatch.setattr(
        cli,
        "make_client",
        lambda: (_ for _ in ()).throw(AssertionError("client must not be created")),
    )
    args = cli.build_parser().parse_args(
        ["--import-session", str(tmp_path / "reports" / "source")]
    )

    result = await cli.async_main(args)

    assert result == 0
    assert calls == [(tmp_path, (tmp_path / "reports" / "source").resolve())]
    assert "Imported 2 pending evaluation case" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_live_cli_prints_hard_ceiling_before_missing_key_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "find_project_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "load_policy_reference", lambda root, value: object())
    monkeypatch.setattr(cli, "load_cases_reference", lambda root, path: [object(), object()])
    monkeypatch.setattr(cli, "load_expectations", lambda path: object())
    monkeypatch.setattr(cli, "load_env", lambda root: None)
    monkeypatch.setattr(
        cli,
        "make_client",
        lambda: (_ for _ in ()).throw(RuntimeError("DEEPSEEK_API_KEY is not set")),
    )
    args = cli.build_parser().parse_args(
        [
            "--live-compare",
            "--baseline-policy", "baseline.json",
            "--candidate-policy", "candidate.json",
            "--cases", "cases.json",
            "--expectations", "expectations.json",
            "--max-cases", "2",
            "--repeats", "1",
            "--max-llm-calls", "12",
            "--max-output-tokens", "1024",
        ]
    )

    result = await cli.async_main(args)

    output = capsys.readouterr().out
    assert result == 2
    assert "max 12 LLM requests" in output
    assert "12,288 output tokens" in output
    assert output.index("max 12 LLM requests") < output.index("DEEPSEEK_API_KEY")


@pytest.mark.asyncio
async def test_live_cli_turns_comparison_validation_errors_into_sanitized_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "find_project_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "load_policy_reference", lambda root, value: object())
    monkeypatch.setattr(cli, "load_cases_reference", lambda root, path: [object(), object()])
    monkeypatch.setattr(cli, "load_expectations", lambda path: object())
    monkeypatch.setattr(cli, "load_env", lambda root: None)
    monkeypatch.setattr(cli, "make_client", lambda: object())

    async def reject(**kwargs):
        raise ValueError("selected comparison requires at least one guard: sk-secret")

    monkeypatch.setattr(cli, "run_live_compare", reject)
    args = cli.build_parser().parse_args(
        [
            "--live-compare",
            "--baseline-policy", "baseline.json",
            "--candidate-policy", "candidate.json",
            "--cases", "cases.json",
            "--expectations", "expectations.json",
        ]
    )

    result = await cli.async_main(args)

    output = capsys.readouterr().out
    assert result == 2
    assert "Live comparison rejected invalid inputs" in output
    assert "sk-secret" not in output
