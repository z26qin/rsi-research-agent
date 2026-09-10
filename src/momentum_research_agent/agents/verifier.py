"""Independent verifier: static audit plus a bounded ReAct re-check of Evidence[]."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from openai import AsyncOpenAI
from pydantic import ValidationError

from momentum_research_agent.agents.audit import merge_verification, rollup_status, static_audit
from momentum_research_agent.agents.budget import LoopBudget
from momentum_research_agent.agents.ledger import finalize_ledger, record_trace
from momentum_research_agent.agents.react_loop import react_loop
from momentum_research_agent.agents.sub_agent import load_profile
from momentum_research_agent.errors import AgentRuntimeError
from momentum_research_agent.models.schemas import (
    ResearchReport,
    ToolTrace,
    UsageSummary,
    VerificationReport,
    VerificationRunResult,
    VerificationStatus,
    parse_model_json,
)
from momentum_research_agent.state.reports import persist_verification_report
from momentum_research_agent.state.traces import append_traces, load_traces
from momentum_research_agent.tools import authorize_tools
from momentum_research_agent.tools.registry import (
    ToolContext,
    resolve_tools,
    set_tool_context,
)

VERIFIER_PROFILE = "verifier"


def _guard_source_discovery(report: VerificationReport, reports: list[ResearchReport], traces: list[ToolTrace]) -> None:
    """Retrieval alone cannot substantiate claims, including redirects/download leads."""
    discovered_urls: set[str] = set()
    verifier_reads: set[str] = set()
    def key(url: object) -> str:
        return url.split("#", 1)[0].rstrip("/") if isinstance(url, str) else ""
    for trace in traces:
        if trace.tool == 'read_url':
            requested = trace.arguments.get('url')
            if isinstance(requested, str):
                discovered_urls.add(key(requested))
            try:
                content = json.loads(trace.observation)
            except (ValueError, TypeError):
                continue
            if isinstance(content, dict):
                urls = [content.get('url'), content.get('requested_url')]
                if isinstance(content.get('links'), list):
                    urls.extend(content['links'])
                normalized = {key(url) for url in urls if key(url)}
                discovered_urls.update(normalized)
                if trace.agent_role == VERIFIER_PROFILE and content.get('status') == 'ok':
                    verifier_reads.update({key(requested), key(content.get('url')), key(content.get('requested_url'))} - {''})
            continue
        if trace.tool != "web_search":
            continue
        try:
            observation = json.loads(trace.observation)
        except (ValueError, TypeError):
            continue
        if (isinstance(observation, dict) and observation.get("provider") == "deepseek_native"
                and observation.get("evidence_kind") == "source_discovery" and observation.get("status") == "ok"):
            for source in observation.get("sources", []):
                if isinstance(source, dict) and isinstance(source.get("url"), str):
                    discovered_urls.add(key(source["url"]))
    web_ids = {item.id for research in reports for item in research.findings
               if key(item.source_url) in discovered_urls}
    changed = False
    for verdict in report.verdicts:
        source = key(verdict.rechecked_source)
        independently_read = source in verifier_reads
        if not independently_read and verdict.evidence_id in web_ids:
            independently_read = any(
                key(item.source_url) in verifier_reads
                for research in reports for item in research.findings
                if item.id == verdict.evidence_id
            )
        web_claim = verdict.evidence_id in web_ids or source in discovered_urls or source == "web_search"
        if verdict.status is VerificationStatus.VERIFIED and web_claim and not independently_read:
            verdict.status = VerificationStatus.UNCHECKED
            issue = "Web claim lacks a successful independent verifier source read."
            verdict.issues.append(issue)
            verdict.notes = f"{verdict.notes} {issue}".strip()
            if verdict.claim not in report.unsupported_claims:
                report.unsupported_claims.append(verdict.claim)
            changed = True
    if changed:
        report.overall_status = rollup_status(report.verdicts, report.missing_evidence)
        report.summary += " Web claims based on source discovery or page retrieval remain unchecked."


def _instructions(question: str, reports: list[ResearchReport], static: VerificationReport) -> str:
    payload = {
        "question": question,
        "reports": [report.model_dump(mode="json") for report in reports],
        "static_audit": static.model_dump(mode="json"),
    }
    return (
        "You are an independent verifier. You did not produce these reports.\n\n"
        "Audit the Evidence[] items. Do not invent new research claims. "
        "Do not fabricate URLs or timestamps. You may only judge existing evidence_id values "
        "from the static audit. Prefer conservative verdicts.\n\n"
        "Use tools to re-check sources and market facts when a URL or ticker is available. "
        "If you cannot check an item, leave it UNCHECKED or WEAK — never mark it verified.\n\n"
        "When finished, stop calling tools and return JSON (no markdown fences):\n"
        "{\n"
        f'  "question": {question!r},\n'
        '  "overall_status": "pass" | "pass_with_caveats" | "fail",\n'
        '  "summary": "short independent view",\n'
        '  "unsupported_claims": ["..."],\n'
        '  "missing_evidence": ["..."],\n'
        '  "verdicts": [\n'
        "    {\n"
        '      "evidence_id": "existing id only",\n'
        '      "task_id": "optional",\n'
        '      "claim": "...",\n'
        '      "status": "verified" | "weak" | "rejected" | "unchecked",\n'
        '      "notes": "...",\n'
        '      "issues": ["..."],\n'
        '      "rechecked_source": "url or tool name or null"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        f"Input JSON:\n{payload}"
    )


class Verifier:
    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        project_root: Path,
        budget: LoopBudget | None = None,
        verbose: bool = False,
        console=None,
    ) -> None:
        self.client = client
        self.model = model
        self.project_root = Path(project_root)
        self.budget = budget or LoopBudget()
        self.verbose = verbose
        self.console = console

    async def run(
        self,
        question: str,
        reports: list[ResearchReport],
        session_dir: Path,
    ) -> VerificationRunResult:
        session_dir = Path(session_dir)
        static = static_audit(question, reports)
        local_usage = UsageSummary()
        tool_calls = 0
        traces: list[ToolTrace] = []

        def _persist(report: VerificationReport) -> VerificationReport:
            if traces:
                append_traces(session_dir, traces)
            all_traces = [*load_traces(session_dir), *traces]
            _guard_source_discovery(report, reports, all_traces)
            compiled = finalize_ledger(
                report,
                reports,
                all_traces,
            )
            persist_verification_report(session_dir, compiled)
            return compiled

        if not any(report.findings for report in reports):
            compiled = _persist(static)
            return VerificationRunResult(report=compiled, usage=local_usage, tool_calls=0, traces=compiled.traces)

        tool_names = authorize_tools(VERIFIER_PROFILE)
        definitions, registry = resolve_tools(tool_names)
        set_tool_context(
            ToolContext(
                project_root=self.project_root,
                session_dir=session_dir,
                console=self.console,
                verbose=self.verbose,
                client=self.client,
                usage=local_usage,
                agent_id="verifier",
                agent_role="verifier",
            )
        )

        def _on_tool(name: str, arguments: dict, result: str) -> None:
            nonlocal tool_calls
            tool_calls += 1
            event = record_trace(
                name,
                arguments,
                result,
                agent_id="verifier",
                agent_role="verifier",
            )
            if event is not None:
                traces.append(event)
            if self.verbose and self.console is not None:
                preview = result if len(result) < 240 else result[:240] + "…"
                self.console.print(f"[dim]verifier · {name}({arguments}) → {preview}[/dim]")

        try:
            system_prompt = load_profile(
                VERIFIER_PROFILE, self.project_root, apply_overlay=False
            )
            text = await react_loop(
                client=self.client,
                model=self.model,
                system_prompt=system_prompt,
                user_message=_instructions(question, reports, static),
                tools=definitions,
                tool_registry=registry,
                on_tool_call=_on_tool,
                usage_tracker=local_usage,
                budget=self.budget,
            )
            llm_report = parse_model_json(VerificationReport, text)
            report = merge_verification(static, llm_report, question)
        except asyncio.CancelledError:
            if traces:
                append_traces(session_dir, traces)
            raise
        except (AgentRuntimeError, ValidationError, ValueError) as exc:
            report = static.model_copy(
                update={
                    "summary": (
                        f"{static.summary} LLM re-check failed ({type(exc).__name__}: {exc}); "
                        "static audit retained."
                    ),
                    "overall_status": (
                        "pass_with_caveats" if static.overall_status == "pass" else static.overall_status
                    ),
                }
            )

        compiled = _persist(report)
        return VerificationRunResult(
            report=compiled,
            usage=local_usage,
            tool_calls=tool_calls,
            traces=compiled.traces,
        )
