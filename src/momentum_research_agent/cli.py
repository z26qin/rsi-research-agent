"""CLI entry point: decompose, dispatch, synthesize, print a PM brief."""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from momentum_research_agent.agents.budget import LoopBudget
from momentum_research_agent.agents.sub_agent import SubAgent
from momentum_research_agent.agents.verifier import Verifier
from momentum_research_agent.config import (
    coordinator_model,
    find_project_root,
    load_env,
    make_client,
    reports_root,
    sub_agent_model,
)
from momentum_research_agent.coordinator.coordinator import (
    Coordinator,
    _render_synthesis_markdown,
    load_or_snapshot_policy,
)
from momentum_research_agent.coordinator.task_board import TaskBoard
from momentum_research_agent.eval.momentum_eval import (
    engine_case_results,
    run_eval,
    run_offline_engine_eval,
)
from momentum_research_agent.eval.live_compare import (
    load_cases_reference,
    load_expectations,
    load_policy_reference,
    run_live_compare,
)
from momentum_research_agent.eval.replay_runner import LLMRequestBudget
from momentum_research_agent.eval.session_cases import import_session_cases
from momentum_research_agent.eval.policy_improver import (
    LLMCandidateGenerator,
    ImprovementOutcome,
    run_improvement_cycle,
)
from momentum_research_agent.eval.policy_suite import FileEvalCaseProvider
from momentum_research_agent.models.schemas import Task, UsageSummary, new_session_id
from momentum_research_agent.state.policies import PolicyStore
from momentum_research_agent.state.reports import (
    render_research_report_markdown,
    render_verification_markdown,
)
from momentum_research_agent.tools.engine_pipeline import bundled_engine_root


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be finite and positive")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="momentum-research-agent",
        description="Multi-agent US equity momentum tail-risk research.",
    )
    parser.add_argument("question", nargs="?", help="Research question to investigate.")
    parser.add_argument(
        "--mode",
        choices=("team", "single"),
        default="team",
        help="team = coordinator + sub-agents (default); single = one ReAct loop.",
    )
    parser.add_argument(
        "--session-dir",
        type=Path,
        help="Override output directory (default: reports/{session_id}/).",
    )
    parser.add_argument(
        "--resume",
        metavar="SESSION_ID",
        help="Resume a previous session from its task board.",
    )
    parser.add_argument(
        "--max-sub-agents",
        type=int,
        default=4,
        help="Max parallel sub-agents (default: 4).",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"Model for sub-agents (default: {sub_agent_model()}).",
    )
    parser.add_argument(
        "--coordinator-model",
        default=None,
        help=f"Model for decompose/synthesize (default: {coordinator_model()}).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show full tool-call details.",
    )
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument(
        "--eval",
        action="store_true",
        dest="run_eval",
        help="Run frozen DM eval (no DeepSeek). Writes failures to the gap ledger.",
    )
    commands.add_argument(
        "--improve",
        action="store_true",
        help="Run the layered offline suite and attempt one constrained policy promotion.",
    )
    commands.add_argument(
        "--import-session",
        type=Path,
        help="Import one session's failures as pending replay cases (offline).",
    )
    commands.add_argument(
        "--live-compare",
        action="store_true",
        help="Run an explicitly bounded baseline/candidate behavioral shadow comparison.",
    )
    parser.add_argument("--baseline-policy", help="Baseline policy version ID or JSON path.")
    parser.add_argument("--candidate-policy", help="Candidate policy version ID or JSON path.")
    parser.add_argument("--cases", type=Path, help="Explicit replay case file or directory.")
    parser.add_argument("--expectations", type=Path, help="Curated expectations JSON path.")
    parser.add_argument("--max-cases", type=_positive_int, default=5)
    parser.add_argument("--repeats", type=_positive_int, default=2)
    parser.add_argument("--max-llm-calls", type=_positive_int, default=40)
    parser.add_argument("--max-output-tokens", type=_positive_int, default=1024)
    parser.add_argument("--max-turns", type=_positive_int, default=8)
    parser.add_argument("--overall-deadline-s", type=_positive_float, default=90.0)
    parser.add_argument("--llm-timeout-s", type=_positive_float, default=40.0)
    parser.add_argument("--tool-timeout-s", type=_positive_float, default=10.0)
    return parser


def _print_improvement_outcome(
    console: Console,
    outcome: ImprovementOutcome,
    *,
    project_root: Path,
) -> None:
    failures = [case.case_id for case in outcome.baseline.cases if not case.passed]
    console.print(
        "[bold]baseline failures[/bold] "
        + (", ".join(failures) if failures else "none")
    )
    candidate = outcome.candidate_version_id or "not generated"
    console.print(f"[bold]candidate result[/bold] {outcome.status} ({candidate})")
    console.print(
        f"[bold]active version[/bold] {PolicyStore(project_root).load_active().version_id}"
    )
    console.print(f"[bold]reason[/bold] {outcome.reason}")


def resolve_session_dir(
    project_root: Path,
    session_dir: Path | None,
    resume: str | None,
) -> Path:
    root = reports_root(project_root)
    if session_dir is not None:
        return session_dir.expanduser().resolve()
    if resume:
        candidate = root / resume
        if not (candidate / "task_board.json").exists():
            raise SystemExit(f"No task board found for session {resume}: {candidate}")
        return candidate
    return root / new_session_id()


def print_banner(
    console: Console,
    *,
    session_id: str,
    mode: str,
    model: str,
    coordinator: str,
    question: str,
    session_dir: Path,
) -> None:
    console.print(
        Panel.fit(
            f"[bold]Momentum Research Agent[/bold]\n"
            f"session   {session_id}\n"
            f"mode      {mode}\n"
            f"sub-model {model}\n"
            f"coord     {coordinator}\n"
            f"output    {session_dir}\n\n"
            f"[italic]{question}[/italic]",
            title="session",
            border_style="cyan",
        )
    )


async def run_single(
    *,
    question: str,
    session_dir: Path,
    client,
    model: str,
    project_root: Path,
    verbose: bool,
    console: Console,
    usage: UsageSummary,
) -> None:
    task = Task(
        title="Single-agent investigation",
        assignment=question,
        profile="momentum_analyst",
    )
    board = TaskBoard(session_dir, question=question)
    board.add_task(task.title, task.assignment, task.profile, task_id=task.id)
    board.activate(task.id)
    agent = SubAgent(
        client=client,
        model=model,
        project_root=project_root,
        verbose=verbose,
        console=console,
        policy=load_or_snapshot_policy(session_dir, project_root),
    )
    try:
        result = await agent.run(task, None, session_dir)
        usage.extend(result.usage)
        board.record_usage(
            task.id,
            tool_calls=result.tool_calls,
            tokens_used=result.usage.total_tokens,
        )
        board.complete(task.id, result.report.summary)
        console.print(
            Panel(
                Markdown(render_research_report_markdown(result.report)),
                title="Research report",
                border_style="green",
            )
        )
        verifier = Verifier(
            client=client,
            model=model,
            project_root=project_root,
            verbose=verbose,
            console=console,
        )
        try:
            verified = await verifier.run(question, [result.report], session_dir)
            usage.extend(verified.usage)
            console.print(
                Panel(
                    Markdown(render_verification_markdown(verified.report)),
                    title="Verification",
                    border_style="yellow",
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            console.print(f"[red]Verifier failed:[/red] {exc}")
    except Exception as exc:
        board.fail(task.id, str(exc), error_type=type(exc).__name__)
        raise


async def async_main(args: argparse.Namespace) -> int:
    console = Console()
    project_root = find_project_root()

    if getattr(args, "import_session", None) is not None:
        session_dir = args.import_session.expanduser().resolve()
        try:
            imported = import_session_cases(project_root, session_dir)
        except (OSError, ValueError) as exc:
            console.print(f"[red]Session import failed:[/red] {exc}")
            return 2
        console.print(
            f"[green]Imported {len(imported)} pending evaluation case(s).[/green]"
        )
        return 0

    if getattr(args, "run_eval", False):
        load_env(project_root)
        results = await run_eval(project_root)
        failed = [item for item in results if not item["ok"]]
        for item in results:
            status = "ok" if item["ok"] else "FAIL"
            console.print(f"[bold]eval {item['case_id']}[/bold] {status}")
            if item.get("error"):
                console.print(f"  {item['error']}")
        if failed:
            console.print(f"[red]{len(failed)} eval case(s) wrote gap-ledger rows[/red]")
            return 1
        console.print("[green]eval passed (live run_mvp V_D)[/green]")
        return 0

    if getattr(args, "improve", False):
        load_env(project_root)
        fixture_path = (
            Path(__file__).resolve().parent
            / "eval"
            / "fixtures"
            / "trajectory_cases.json"
        )
        offline_results = await run_offline_engine_eval(
            bundled_engine_root(project_root)
        )
        outcome = await run_improvement_cycle(
            project_root,
            generator=LLMCandidateGenerator(
                model=args.coordinator_model or coordinator_model()
            ),
            engine_results=engine_case_results(offline_results),
            provider=FileEvalCaseProvider(fixture_path),
        )
        _print_improvement_outcome(console, outcome, project_root=project_root)
        if (
            outcome.status == "error"
            and "DEEPSEEK_API_KEY is not set" in outcome.reason
        ):
            console.print(
                "[red]DEEPSEEK_API_KEY is not set; no candidate was generated.[/red]"
            )
            return 2
        return 0 if outcome.status in {"promoted", "no_change"} else 1

    if getattr(args, "live_compare", False):
        required = {
            "--baseline-policy": args.baseline_policy,
            "--candidate-policy": args.candidate_policy,
            "--cases": args.cases,
            "--expectations": args.expectations,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            console.print(
                f"[red]--live-compare requires: {', '.join(missing)}[/red]"
            )
            return 2
        try:
            baseline = load_policy_reference(project_root, args.baseline_policy)
            candidate = load_policy_reference(project_root, args.candidate_policy)
            cases = load_cases_reference(project_root, args.cases)
            expectations = load_expectations(args.expectations)
        except (OSError, ValueError) as exc:
            console.print(f"[red]Live comparison input failed:[/red] {exc}")
            return 2
        output_ceiling = args.max_llm_calls * args.max_output_tokens
        console.print(
            "[bold]Live comparison hard bounds:[/bold] "
            f"max {args.max_llm_calls} LLM requests; "
            f"max {args.max_output_tokens:,} output tokens/request; "
            f"{output_ceiling:,} output tokens total ceiling; SDK retries disabled."
        )
        load_env(project_root)
        try:
            client = make_client()
        except RuntimeError as exc:
            console.print(f"[red]{exc}[/red]")
            return 2
        try:
            report, path = await run_live_compare(
                client=client,
                requested_model=args.model or sub_agent_model(),
                project_root=project_root,
                baseline_policy=baseline,
                candidate_policy=candidate,
                cases=cases,
                expectations=expectations,
                repeats=args.repeats,
                max_cases=args.max_cases,
                request_budget=LLMRequestBudget(max_attempts=args.max_llm_calls),
                max_output_tokens=args.max_output_tokens,
                budget=LoopBudget(
                    max_turns=args.max_turns,
                    overall_deadline_s=args.overall_deadline_s,
                    llm_timeout_s=args.llm_timeout_s,
                    tool_timeout_s=args.tool_timeout_s,
                ),
            )
        except ValueError:
            console.print("[red]Live comparison rejected invalid inputs.[/red]")
            return 2
        console.print(f"[bold]Behavioral shadow[/bold] {report.outcome}: {path}")
        console.print(
            f"observed_no_regression={report.observed_no_regression}; "
            f"target_improvements={len(report.target_improvements)}"
        )
        return 0 if report.outcome == "completed" else 1

    if not args.resume and not args.question:
        console.print("[red]A research question is required unless --resume is set.[/red]")
        return 2

    load_env(project_root)

    session_dir = resolve_session_dir(project_root, args.session_dir, args.resume)
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "sub_reports").mkdir(exist_ok=True)

    model = args.model or sub_agent_model()
    coord_model = args.coordinator_model or coordinator_model()
    question = args.question or ""

    try:
        client = make_client()
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2

    if args.resume:
        board = TaskBoard.load(session_dir)
        question = question or board.question
    else:
        board = None

    print_banner(
        console,
        session_id=session_dir.name,
        mode=args.mode,
        model=model,
        coordinator=coord_model,
        question=question,
        session_dir=session_dir,
    )

    usage = UsageSummary()

    if args.mode == "single" and not args.resume:
        await run_single(
            question=question,
            session_dir=session_dir,
            client=client,
            model=model,
            project_root=project_root,
            verbose=args.verbose,
            console=console,
            usage=usage,
        )
        coordinator = Coordinator(
            session_dir=session_dir,
            client=client,
            question=question,
            project_root=project_root,
            usage_tracker=usage,
            console=console,
        )
    else:
        coordinator = Coordinator(
            session_dir=session_dir,
            client=client,
            question=question,
            project_root=project_root,
            board=board,
            sub_model=model,
            coordinator_model_name=coord_model,
            max_sub_agents=args.max_sub_agents,
            verbose=args.verbose,
            console=console,
            usage_tracker=usage,
        )
        if args.resume:
            report = await coordinator.resume()
        else:
            report = await coordinator.run(question)
        if coordinator.verification is not None:
            console.print(
                Panel(
                    Markdown(render_verification_markdown(coordinator.verification)),
                    title="Verification",
                    border_style="yellow",
                )
            )
        console.print(
            Panel(
                Markdown(_render_synthesis_markdown(report)),
                title="Synthesis",
                border_style="green",
            )
        )

    for line in coordinator.cost_summary_lines():
        console.print(f"[bold]{line}[/bold]" if line.startswith("Token") else line)
    console.print(f"\nSession artifacts: [cyan]{session_dir}[/cyan]")
    return 0


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(async_main(args)))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
