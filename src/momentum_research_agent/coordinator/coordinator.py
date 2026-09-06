"""Coordinator: decompose → gap seed → warm engine → dispatch → replan → verify → follow-up → synthesize."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI
from pydantic import ValidationError
from rich.console import Console
from rich.live import Live
from rich.table import Table

from momentum_research_agent.agents.budget import LoopBudget
from momentum_research_agent.agents.sub_agent import SubAgent
from momentum_research_agent.agents.verifier import Verifier
from momentum_research_agent.config import coordinator_model, sub_agent_model, usage_cost_usd
from momentum_research_agent.coordinator.followup import (
    MAX_FOLLOWUP_TASKS,
    already_followed_up,
    followup_specs,
    is_followup_task,
)
from momentum_research_agent.coordinator.replan import (
    DEFAULT_REPLAN_PROFILE,
    already_replanned,
    replan_assignment,
    should_replan,
)
from momentum_research_agent.coordinator.gap_seed import (
    already_gap_seeded,
    record_session_gaps,
    resolve_consumed_gaps,
    seed_open_gaps,
)
from momentum_research_agent.coordinator.task_board import TaskBoard
from momentum_research_agent.models.schemas import (
    AgentRunResult,
    DecompositionResult,
    GapLedgerStatus,
    ResearchReport,
    SynthesisReport,
    Task,
    TaskKind,
    TaskStatus,
    UsageSummary,
    VerificationReport,
    parse_model_json,
    utcnow,
)
from momentum_research_agent.state.persistence import load_json, save_json, save_text
from momentum_research_agent.state.prompt_memory import failure_brief, refresh_profile_hints
from momentum_research_agent.state.policies import PolicyStore, ResearchPolicy
from momentum_research_agent.tools.engine_pipeline import warm_pipeline
from momentum_research_agent.state.reports import (
    load_research_report,
    load_verification_report,
    persist_verification_report,
    render_research_report_markdown,
    render_verification_markdown,
)
from momentum_research_agent.tools import RESEARCH_PROFILES

PROMPTS_DIR = Path(__file__).parent / "prompts"
POLICY_SNAPSHOT_FILE = "policy_snapshot.json"


def load_or_snapshot_policy(session_dir: Path, project_root: Path) -> ResearchPolicy:
    """Reuse a session's immutable policy version across resume attempts."""
    snapshot_path = Path(session_dir) / POLICY_SNAPSHOT_FILE
    store = PolicyStore(project_root)
    if snapshot_path.exists():
        return store.load_version(str(load_json(snapshot_path)["version_id"]))
    policy = store.load_active()
    save_json(snapshot_path, {"version_id": policy.version_id})
    return policy


class Coordinator:
    def __init__(
        self,
        session_dir: Path,
        client: AsyncOpenAI,
        question: str = "",
        project_root: Path | None = None,
        board: TaskBoard | None = None,
        sub_model: str | None = None,
        coordinator_model_name: str | None = None,
        max_sub_agents: int = 4,
        max_follow_ups: int = MAX_FOLLOWUP_TASKS,
        verbose: bool = False,
        console: Console | None = None,
        usage_tracker: UsageSummary | None = None,
        budget: LoopBudget | None = None,
    ) -> None:
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        (self.session_dir / "sub_reports").mkdir(exist_ok=True)
        self.client = client
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self.policy = load_or_snapshot_policy(self.session_dir, self.project_root)
        self.board = board or TaskBoard(self.session_dir, question=question)
        if question and not self.board.question:
            self.board.question = question
        self.sub_model = sub_model or sub_agent_model()
        self.coordinator_model_name = coordinator_model_name or coordinator_model()
        self.max_sub_agents = max_sub_agents
        self.max_follow_ups = max_follow_ups
        self.verbose = verbose
        self.console = console or Console()
        self.usage_tracker = usage_tracker or UsageSummary()
        self.budget = budget or LoopBudget()
        self.sub_reports: dict[str, ResearchReport] = {}
        self.verification: VerificationReport | None = None

    async def run(self, question: str) -> SynthesisReport:
        self.board.question = question
        self.board.save()
        await self.decompose(question)
        self.seed_from_ledger()
        await self._dispatch_wave()
        await self.verify()
        if await self.follow_up():
            await self.verify()
        return await self.synthesize()

    async def resume(self) -> SynthesisReport:
        synthesis_path = self.session_dir / "synthesis.md"
        pending = [
            task
            for task in self.board.tasks
            if task.status in {TaskStatus.PENDING, TaskStatus.BLOCKED, TaskStatus.ACTIVE}
        ]
        ran_dispatch = False
        if pending:
            if not already_gap_seeded(self.board.tasks):
                self.seed_from_ledger()
            await self._dispatch_wave(requeue=True)
            ran_dispatch = True
        elif not self.board.tasks:
            await self.decompose(self.board.question)
            self.seed_from_ledger()
            await self._dispatch_wave()
            ran_dispatch = True
        self._load_existing_sub_reports()
        existing_verification = load_verification_report(self.session_dir)
        if ran_dispatch or existing_verification is None:
            await self.verify()
        else:
            self.verification = existing_verification
            if self._followup_needs_reverify():
                await self.verify()
        json_path = self.session_dir / "synthesis.json"
        session_complete = (json_path.exists() or synthesis_path.exists()) and not ran_dispatch
        if session_complete:
            if json_path.exists():
                return SynthesisReport.model_validate_json(
                    json_path.read_text(encoding="utf-8")
                )
            return parse_model_json(SynthesisReport, synthesis_path.read_text(encoding="utf-8"))
        if await self.follow_up():
            await self.verify()
        return await self.synthesize()

    async def decompose(self, question: str) -> list[Task]:
        system_prompt = (PROMPTS_DIR / "decompose.md").read_text(encoding="utf-8")
        user_message = f"Research question:\n\n{question}"
        brief = failure_brief(self.project_root)
        if brief:
            user_message = f"{user_message}\n\n{brief}"
        result = await self._complete_json(
            system_prompt,
            user_message,
            DecompositionResult,
            self.coordinator_model_name,
        )
        created: list[Task] = []
        for spec in result.tasks[: self.max_sub_agents]:
            created.append(
                self.board.add_task(
                    title=spec.title,
                    assignment=spec.assignment,
                    profile=spec.profile,
                )
            )
        self.console.print(f"[bold]Decomposition[/bold] — {result.reasoning}\n")
        self.console.print(self.render_board_table())
        return created

    async def dispatch_all(self) -> None:
        for task in list(self.board.pending):
            if task.profile.removesuffix(".md") not in RESEARCH_PROFILES:
                self.console.print(
                    f"[red]Rejecting non-research profile '{task.profile}' on task {task.id}[/red]"
                )
                self.board.cancel(
                    task.id,
                    f"Profile '{task.profile}' is not a research profile.",
                )
        pending = self.board.pending
        if not pending:
            return

        semaphore = asyncio.Semaphore(self.max_sub_agents)

        async def run_one(task: Task) -> AgentRunResult:
            async with semaphore:
                self.board.activate(task.id)
                agent = SubAgent(
                    client=self.client,
                    model=self.sub_model,
                    project_root=self.project_root,
                    budget=self.budget,
                    verbose=self.verbose,
                    on_progress=self._on_progress,
                    console=self.console,
                    policy=self.policy,
                )
                return await agent.run(task, None, self.session_dir)

        with Live(self.render_board_table(), console=self.console, refresh_per_second=4) as live:
            gathered = await asyncio.gather(
                *[self._tracked(run_one, task, live) for task in pending],
                return_exceptions=True,
            )

        for task, result in zip(pending, gathered, strict=False):
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, Exception):
                error_type = type(result).__name__
                self.console.print(f"[red]Task {task.id} failed ({error_type}):[/red] {result}")
                self.board.fail(task.id, str(result), error_type=error_type)
                continue
            assert isinstance(result, AgentRunResult)
            self.usage_tracker.extend(result.usage)
            self.sub_reports[task.id] = result.report
            self.board.record_usage(
                task.id,
                tool_calls=result.tool_calls,
                tokens_used=result.usage.total_tokens,
            )
            self.board.complete(task.id, result.report.summary)

        self.console.print(self.render_board_table())

    async def verify(self) -> VerificationReport:
        self._load_existing_sub_reports()
        reports = [
            self.sub_reports[task.id]
            for task in self.board.completed
            if task.id in self.sub_reports
        ]
        try:
            result = await Verifier(
                client=self.client,
                model=self.sub_model,
                project_root=self.project_root,
                budget=self.budget,
                verbose=self.verbose,
                console=self.console,
            ).run(self.board.question, reports, self.session_dir)
            self.usage_tracker.extend(result.usage)
            self.verification = result.report
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            from momentum_research_agent.agents.audit import static_audit
            from momentum_research_agent.agents.ledger import finalize_ledger
            from momentum_research_agent.state.traces import load_traces

            report = static_audit(self.board.question, reports)
            report = report.model_copy(
                update={
                    "summary": f"{report.summary} Verifier crashed ({type(exc).__name__}: {exc}).",
                    "overall_status": (
                        "fail" if report.overall_status == "fail" else "pass_with_caveats"
                    ),
                }
            )
            report = finalize_ledger(report, reports, load_traces(self.session_dir))
            persist_verification_report(self.session_dir, report)
            self.verification = report
            self.console.print(f"[red]Verifier failed:[/red] {exc}")
        self.console.print(
            f"[bold]Verification[/bold] — {self.verification.overall_status}: "
            f"{self.verification.summary}"
        )
        self.record_gaps()
        self.resolve_planted_gaps()
        refresh_profile_hints(self.project_root)
        return self.verification

    def record_gaps(self) -> None:
        """Append this session's verification.gaps to reports/gap_ledger.jsonl."""
        gaps = self.verification.gaps if self.verification is not None else None
        record_session_gaps(
            self.project_root,
            self.session_dir,
            self.board.session_id,
            report_gaps=gaps,
        )

    def resolve_planted_gaps(self) -> None:
        """Mark this session's planted rows CLOSED or OPEN from verification."""
        if self.verification is None:
            return
        changed = resolve_consumed_gaps(self.project_root, self.board, self.verification)
        if not changed:
            return
        closed = sum(1 for row in changed if row.status is GapLedgerStatus.CLOSED)
        reopened = sum(1 for row in changed if row.status is GapLedgerStatus.OPEN)
        self.console.print(
            f"[bold]Gap resolve[/bold] — closed {closed}, reopened {reopened}"
        )

    def seed_from_ledger(self) -> list[Task]:
        """After decompose, plant at most 2 kind=gap tasks from OPEN ledger rows."""
        self.record_gaps()
        planted = seed_open_gaps(self.board, self.project_root, self.policy)
        if planted:
            self.console.print(
                f"[bold]Gap seed[/bold] — planted {len(planted)} kind=gap task(s)"
            )
            self.console.print(self.render_board_table())
        return planted

    async def _dispatch_wave(self, *, requeue: bool = False) -> None:
        """Warm engine, dispatch pending tasks, then at most one kind=replan."""
        self.warm_engine()
        if requeue:
            self.board.requeue_unfinished()
        await self.dispatch_all()
        if self.maybe_replan():
            await self.dispatch_all()

    def warm_engine(self) -> None:
        """Prefetch run_mvp for frozen as-of dates so ReAct stays inside the tool budget."""
        results = warm_pipeline(self.project_root)
        ok = sum(1 for item in results if item.ok)
        if results:
            self.console.print(
                f"[bold]Engine warm[/bold] — {ok}/{len(results)} run_mvp cache(s) ready"
            )

    def maybe_replan(self) -> bool:
        """At most one kind=replan after the first dispatch wave."""
        if already_replanned(self.board.tasks):
            return False
        if not should_replan(self.board.tasks, self.session_dir):
            return False
        self.board.add_task(
            "Replan: live engine_query",
            replan_assignment(self.board.question),
            DEFAULT_REPLAN_PROFILE,
            kind=TaskKind.REPLAN,
        )
        self.console.print("[bold]Replan[/bold] — one kind=replan task (not follow-up)")
        self.console.print(self.render_board_table())
        return True

    async def follow_up(self) -> bool:
        """One bounded round of research on rejected/unchecked evidence."""
        if self.verification is None:
            self.verification = load_verification_report(self.session_dir)
        if self.verification is None:
            return False
        if already_followed_up(self.board.tasks):
            return False
        self._load_existing_sub_reports()
        specs = followup_specs(
            self.board.question,
            self.verification,
            self.sub_reports,
            max_tasks=min(self.max_follow_ups, self.max_sub_agents),
        )
        if not specs:
            return False
        self.console.print(
            f"[bold]Follow-up[/bold] — {len(specs)} task(s) on rejected/unchecked evidence"
        )
        for spec in specs:
            self.board.add_task(
                spec.title,
                spec.assignment,
                spec.profile,
                kind=TaskKind.FOLLOWUP,
            )
        await self.dispatch_all()
        return True

    async def synthesize(self) -> SynthesisReport:
        self._load_existing_sub_reports()
        system_prompt = (PROMPTS_DIR / "synthesize.md").read_text(encoding="utf-8")
        missing = [
            task
            for task in self.board.tasks
            if task.status in {TaskStatus.BLOCKED, TaskStatus.CANCELLED}
        ]
        completed = [
            task for task in self.board.tasks if task.status == TaskStatus.COMPLETED
        ]
        chunks: list[str] = [
            f"Original research question:\n{self.board.question}\n",
            "Treat findings: Evidence[] as the machine-readable source of truth. "
            "summary is only a human view.",
        ]
        if self.verification is None:
            self.verification = load_verification_report(self.session_dir)
        if self.verification is not None:
            chunks.append(
                "## Independent verification\n\n"
                f"{render_verification_markdown(self.verification)}\n\n"
                f"Verification JSON:\n{self.verification.model_dump_json(indent=2)}\n\n"
                "Weight rejected/unchecked evidence down. Do not treat unverified claims as facts."
            )
        followups = [task for task in completed if is_followup_task(task)]
        if followups:
            chunks.append(
                "Follow-up reports below were spawned only for rejected/unchecked "
                "evidence (one round). Prefer their sourced findings over the original "
                "rejected/unchecked claims they were asked to repair."
            )
        for task in completed:
            report = self.sub_reports.get(task.id)
            if report is None:
                chunks.append(f"## Sub-report: {task.title} [{task.profile}]\n\n{task.report or ''}")
                continue
            chunks.append(
                f"## Sub-report: {task.title} [{task.profile}]\n\n"
                f"{render_research_report_markdown(report)}\n\n"
                f"Evidence JSON:\n{report.model_dump_json(indent=2)}"
            )
        if missing:
            names = ", ".join(
                f"{task.title} ({task.status.value}: {task.error_type or task.error})"
                for task in missing
            )
            chunks.append(
                "The following dimensions are missing because the sub-agent failed "
                f"or was cancelled: {names}. Note the gap in the synthesis."
            )
        raw = await self._complete_json(
            system_prompt,
            "\n\n---\n\n".join(chunks),
            SynthesisReport,
            self.coordinator_model_name,
        )
        report = raw.model_copy(update={"question": self.board.question, "timestamp": utcnow()})
        save_text(self.session_dir / "synthesis.md", _render_synthesis_markdown(report))
        save_text(
            self.session_dir / "synthesis.json",
            report.model_dump_json(indent=2),
        )
        return report

    def render_board_table(self) -> Table:
        table = Table(title=f"Task board · {self.board.summary}", expand=True)
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Title")
        table.add_column("Profile")
        table.add_column("Status")
        table.add_column("Tools", justify="right")
        table.add_column("Tokens", justify="right")
        style = {
            TaskStatus.PENDING: "dim",
            TaskStatus.ACTIVE: "yellow",
            TaskStatus.COMPLETED: "green",
            TaskStatus.BLOCKED: "red",
            TaskStatus.CANCELLED: "magenta",
        }
        for task in self.board.tasks:
            table.add_row(
                task.id,
                task.title,
                task.profile,
                f"[{style[task.status]}]{task.status.value}[/]",
                str(task.tool_calls),
                str(task.tokens_used),
            )
        return table

    def cost_summary_lines(self) -> list[str]:
        lines = ["Token / cost summary"]
        for model, bucket in self.usage_tracker.totals().items():
            cost = usage_cost_usd(
                UsageSummary.model_validate(
                    {
                        "events": [
                            {
                                "model": model,
                                "prompt_tokens": bucket["prompt_tokens"],
                                "completion_tokens": bucket["completion_tokens"],
                            }
                        ]
                    }
                )
            )
            lines.append(
                f"  {model}: {bucket['calls']} calls · "
                f"in={bucket['prompt_tokens']:,} out={bucket['completion_tokens']:,} · "
                f"${cost:.4f}"
            )
        lines.append(
            f"  total tokens={self.usage_tracker.total_tokens:,} · "
            f"${usage_cost_usd(self.usage_tracker):.4f}"
        )
        return lines

    async def _complete_json(
        self,
        system_prompt: str,
        user_message: str,
        model_cls: type,
        model: str,
    ) -> Any:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        last_error = ""
        for _attempt in range(2):
            if last_error:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your previous response failed schema validation:\n"
                            f"{last_error}\n\n"
                            "Return ONLY valid JSON matching the requested schema."
                        ),
                    }
                )
            response = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
            )
            usage = getattr(response, "usage", None)
            if usage is not None:
                self.usage_tracker.add(
                    model,
                    int(getattr(usage, "prompt_tokens", 0) or 0),
                    int(getattr(usage, "completion_tokens", 0) or 0),
                )
            content = response.choices[0].message.content or ""
            try:
                return parse_model_json(model_cls, content)
            except ValidationError as exc:
                last_error = str(exc)
                messages.append({"role": "assistant", "content": content})
        raise ValueError(f"Could not parse {model_cls.__name__} after retry: {last_error}")

    def _on_progress(self, task_id: str, tool_calls: int, tokens_used: int) -> None:
        try:
            self.board.record_usage(task_id, tool_calls=tool_calls, tokens_used=tokens_used)
        except KeyError:
            return

    async def _tracked(self, fn, task: Task, live: Live):
        try:
            return await fn(task)
        finally:
            live.update(self.render_board_table())

    def _load_existing_sub_reports(self) -> None:
        for task in self.board.completed:
            if task.id in self.sub_reports:
                continue
            loaded = load_research_report(self.session_dir, task)
            if loaded is not None:
                self.sub_reports[task.id] = loaded

    def _followup_needs_reverify(self) -> bool:
        if self.verification is None:
            return True
        followup_ids = {
            task.id
            for task in self.board.tasks
            if is_followup_task(task) and task.status == TaskStatus.COMPLETED
        }
        if not followup_ids:
            return False
        covered = {verdict.task_id for verdict in self.verification.verdicts if verdict.task_id}
        return bool(followup_ids - covered)


def _render_synthesis_markdown(report: SynthesisReport) -> str:
    dimensions = "\n\n".join(
        f"### {name}\n\n{body}" for name, body in report.analysis_by_dimension.items()
    ) or "_(none)_"
    signals = "\n".join(f"- {item}" for item in report.actionable_signals) or "- (none)"
    dissent = "\n".join(f"- {item}" for item in report.dissenting_views) or "- (none)"
    return (
        f"# Synthesis\n\n"
        f"**Question:** {report.question}\n\n"
        f"**Timestamp:** {report.timestamp.isoformat()}\n\n"
        f"**Confidence:** {report.confidence_level}\n\n"
        f"## Executive Summary\n\n{report.executive_summary}\n\n"
        f"## Analysis by Dimension\n\n{dimensions}\n\n"
        f"## Cross-Dimensional Risk Assessment\n\n{report.risk_assessment}\n\n"
        f"## Actionable Signals\n\n{signals}\n\n"
        f"## Dissenting Views\n\n{dissent}\n"
    )
