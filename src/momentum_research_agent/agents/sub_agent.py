"""Profile-bound ReAct runner that writes a ResearchReport to the session directory."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI
from pydantic import ValidationError

from momentum_research_agent.agents.budget import LoopBudget
from momentum_research_agent.agents.react_loop import react_loop
from momentum_research_agent.agents.ledger import record_trace
from momentum_research_agent.errors import AgentRuntimeError
from momentum_research_agent.models.schemas import (
    AgentRunResult,
    ResearchReport,
    Task,
    ToolTrace,
    UsageSummary,
    parse_model_json,
)
from momentum_research_agent.state.reports import persist_research_report
from momentum_research_agent.state.traces import append_traces
from momentum_research_agent.state.prompt_memory import overlay_text
from momentum_research_agent.state.policies import PolicyStore, ResearchPolicy
from momentum_research_agent.tools import authorize_research_tools
from momentum_research_agent.tools.registry import (
    ToolContext,
    resolve_tools,
    set_tool_context,
)

OnProgress = Callable[[str, int, int], None]


def load_profile(
    profile: str,
    project_root: Path,
    *,
    apply_overlay: bool = True,
    policy: ResearchPolicy | None = None,
) -> str:
    """Load a frozen profile. Overlay is for research profiles only.

    Verifier must call with apply_overlay=False so OPEN-gap / eval rules
    cannot leak into the independent checker.
    """
    name = profile.removesuffix(".md")
    candidates = [
        project_root / "profiles" / f"{name}.md",
        Path(__file__).parent / "profiles" / f"{name}.md",
    ]
    for path in candidates:
        if path.exists():
            text = path.read_text(encoding="utf-8")
            if name == "verifier" or not apply_overlay:
                return text
            overlay = overlay_text(project_root, name, policy=policy)
            if overlay:
                return f"{text.rstrip()}\n\n{overlay}\n"
            return text
    known = ", ".join(p.stem for p in (Path(__file__).parent / "profiles").glob("*.md"))
    raise FileNotFoundError(f"Unknown profile '{profile}'. Available: {known}")


def _report_instructions(task: Task) -> str:
    return (
        f"# Assignment\n\n{task.assignment}\n\n"
        "Investigate using only your authorized tools. The ReAct trajectory stays "
        "internal; the coordinator receives only the final JSON ResearchReport.\n\n"
        "Collect concrete evidence. Distinguish supporting vs contradicting items. "
        "Include source URLs when you actually retrieved them. Do not fabricate "
        "published timestamps or URLs. Do not turn speculation into Evidence. "
        "Use category OTHER only when no main category fits. If the investigation "
        "is incomplete, set status to partial or insufficient_evidence.\n\n"
        "When finished, stop calling tools and respond with JSON (no markdown fences):\n"
        "{\n"
        f'  "task_id": "{task.id}",\n'
        f'  "title": "{task.title}",\n'
        f'  "agent_role": "{task.profile}",\n'
        '  "summary": "short human-readable view",\n'
        '  "status": "complete" | "partial" | "insufficient_evidence",\n'
        '  "unanswered_questions": ["..."],\n'
        '  "contradictions": ["..."],\n'
        '  "findings": [\n'
        "    {\n"
        '      "claim": "...",\n'
        '      "category": "market_regime" | "crowded_positioning" | '
        '"fundamental_repricing" | "contradicting_evidence" | "other",\n'
        '      "stance": "supporting" | "contradicting" | "neutral",\n'
        '      "source_url": "https://... or null",\n'
        '      "source_name": "optional",\n'
        '      "published_at": "ISO-8601 or null — only if actually known",\n'
        '      "excerpt": "optional short quote",\n'
        '      "confidence": "high" | "medium" | "low"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Be precise with numbers. Flag speculation in unanswered_questions, not as evidence."
    )


def _bind_report(task: Task, report: ResearchReport) -> ResearchReport:
    for item in report.findings:
        if not item.agent_id:
            item.agent_id = task.id
    return report.model_copy(
        update={
            "task_id": task.id,
            "title": report.title or task.title,
            "agent_role": task.profile,
        }
    )


def _fallback_report(task: Task, text: str, error: str | None = None) -> ResearchReport:
    summary = text.strip() if text.strip() else (error or "Sub-agent produced no report.")
    unanswered = ["Final model output did not match ResearchReport JSON."]
    if error:
        unanswered.append(error)
        summary = f"{summary}\n\nError: {error}"
    return ResearchReport(
        task_id=task.id,
        title=task.title,
        agent_role=task.profile,
        findings=[],
        summary=summary,
        unanswered_questions=unanswered,
        contradictions=[],
        status="insufficient_evidence",
    )


class SubAgent:
    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        project_root: Path,
        budget: LoopBudget | None = None,
        verbose: bool = False,
        on_progress: Optional[OnProgress] = None,
        console=None,
        policy: ResearchPolicy | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.project_root = Path(project_root)
        self.budget = budget or LoopBudget()
        self.verbose = verbose
        self.on_progress = on_progress
        self.console = console
        self.policy = policy or PolicyStore(self.project_root).load_active()

    async def run(
        self,
        task: Task,
        tools: list[str] | None,
        session_dir: Path,
    ) -> AgentRunResult:
        session_dir = Path(session_dir)
        tool_names = authorize_research_tools(task.profile, tools)
        definitions, registry = resolve_tools(tool_names)
        set_tool_context(
            ToolContext(
                project_root=self.project_root,
                session_dir=session_dir,
                console=self.console,
                verbose=self.verbose,
            )
        )

        local_usage = UsageSummary()
        tool_calls = 0
        traces: list[ToolTrace] = []

        def _on_tool(name: str, arguments: dict, result: str) -> None:
            nonlocal tool_calls
            tool_calls += 1
            event = record_trace(
                name,
                arguments,
                result,
                agent_id=task.id,
                agent_role=task.profile,
            )
            if event is not None:
                traces.append(event)
            if self.on_progress is not None:
                self.on_progress(task.id, tool_calls, local_usage.total_tokens)
            if self.verbose and self.console is not None:
                preview = result if len(result) < 240 else result[:240] + "…"
                self.console.print(f"[dim]{task.profile} · {name}({arguments}) → {preview}[/dim]")

        try:
            system_prompt = load_profile(task.profile, self.project_root, policy=self.policy)
            text = await react_loop(
                client=self.client,
                model=self.model,
                system_prompt=system_prompt,
                user_message=_report_instructions(task),
                tools=definitions,
                tool_registry=registry,
                on_tool_call=_on_tool,
                usage_tracker=local_usage,
                budget=self.budget,
            )
            try:
                report = _bind_report(task, parse_model_json(ResearchReport, text))
            except ValidationError:
                report = _fallback_report(task, text)
        except asyncio.CancelledError:
            if traces:
                append_traces(session_dir, traces)
            raise
        except AgentRuntimeError:
            if traces:
                append_traces(session_dir, traces)
            raise

        if self.on_progress is not None:
            self.on_progress(task.id, tool_calls, local_usage.total_tokens)

        persist_research_report(session_dir, task, report)
        if traces:
            append_traces(session_dir, traces)
        return AgentRunResult(report=report, usage=local_usage, tool_calls=tool_calls, traces=traces)
