"""Daily brief first; at most one bounded explanatory supplement per target day."""
from __future__ import annotations

import asyncio
from datetime import date
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from momentum_research_agent import market_brief
from momentum_research_agent.agents.audit import static_audit
from momentum_research_agent.agents.budget import LoopBudget
from momentum_research_agent.agents.ledger import finalize_ledger
from momentum_research_agent.agents.sub_agent import SubAgent
from momentum_research_agent.agents.verifier import Verifier
from momentum_research_agent.brief_readiness import sha256_file
from momentum_research_agent.config import make_client, sub_agent_model
from momentum_research_agent.coordinator.coordinator import load_or_snapshot_policy
from momentum_research_agent.coordinator.gap_seed import record_session_gaps
from momentum_research_agent.coordinator.task_board import TaskBoard
from momentum_research_agent.errors import AgentRuntimeError, UnauthorizedTool
from momentum_research_agent.models.schemas import ResearchReport, UsageSummary, VerificationReport, VerificationStatus, parse_model_json
from momentum_research_agent.proxy_data import save_json
from momentum_research_agent.state.reports import persist_research_report, persist_verification_report
from momentum_research_agent.state.traces import load_traces


class Alert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["price_move", "volatility_jump", "short_interest_gap", "holdings_gap"]
    observation: str
    profile: Literal["technicals_analyst", "flow_analyst"]


class Supplement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal["brief_research_v1"] = "brief_research_v1"
    status: Literal["no_alert", "disabled", "duplicate", "unavailable", "running", "partial", "complete", "failed", "cancelled"]
    source_sha256: str | None = None
    alert: Alert | None = None
    session_dir: Path | None = None
    llm_requests: int = 0
    usage: dict = Field(default_factory=dict)
    reason: str = ""


def select_alert(data: dict, previous: dict | None = None) -> Alert | None:
    """Versioned operational heuristics, not calibrated financial risk thresholds."""
    facts = data["facts"]
    if facts["status"] != "partial":
        return None  # LLM cannot repair a missing core price snapshot.
    metrics = facts["metrics"]
    daily = metrics.get("MTUM.return_1d")
    if daily is not None and abs(daily) >= .03:
        return Alert(kind="price_move", profile="technicals_analyst",
                     observation=f"MTUM adjusted daily return {daily:+.2%}; absolute move >=3%.")
    vol = metrics.get("MTUM.volatility_21d")
    old_vol = facts.get("comparisons", {}).get("previous_session", {}).get("metrics", {}).get("MTUM.volatility_21d")
    if vol is not None and old_vol is not None and old_vol > 0 and vol - old_vol >= .05 and vol >= old_vol * 1.5:
        return Alert(kind="volatility_jump", profile="technicals_analyst",
                     observation=f"MTUM 21d annualized volatility {old_vol:.2%} -> {vol:.2%}; >=5pp and >=50% increase.")
    if previous:
        def has_position(item):
            return "MTUM" in ((item.get("short_interest", {}).get("periods", {}).get("latest") or {}).get("records", {}))
        if has_position(previous) and not has_position(data):
            return Alert(kind="short_interest_gap", profile="flow_analyst",
                         observation="Previously available MTUM short-interest position is now unavailable; not zero positions.")
        def has_holdings(item):
            fund = item["facts"].get("crowding", {}).get("funds", {}).get("MTUM", {})
            return fund.get("status") == "ok" and not fund.get("stale", True)
        if has_holdings(previous) and not has_holdings(data):
            return Alert(kind="holdings_gap", profile="flow_analyst",
                         observation="Previously current MTUM issuer holdings are now missing or stale.")
    return None


class LimitedClient:
    """Small OpenAI-compatible facade shared by analyst and verifier."""
    def __init__(self, client):
        self.client = client.with_options(max_retries=0)
        self.chat = self.completions = self
        self.requests = 0
        self.usage = UsageSummary()
        self.schema = None
        self.evidence_ids = None
        self.terminal = None

    def begin(self, schema, evidence_ids=None):
        self.schema, self.evidence_ids, self.terminal = schema, evidence_ids, None

    def require_completion(self):
        if self.terminal is None:
            raise ValueError("Supplement role did not complete a schema-valid final response")

    def _claim_request(self):
        if self.requests >= 5:
            raise AgentRuntimeError("Supplement request budget exhausted")
        self.requests += 1

    async def search_request(self, **kwargs):
        """Native search spends the same budget; it is not a free tool call."""
        from momentum_research_agent.tools.deepseek_search import add_usage, request_sources
        self._claim_request()
        response = await request_sources(self.client, **kwargs)
        add_usage(response, self.usage)
        return response

    async def create(self, **kwargs):
        try:
            return await self._create(**kwargs)
        except AgentRuntimeError:
            raise
        except Exception as exc:
            # Existing analyst/verifier handlers preserve accumulated traces for
            # typed runtime failures. Do not leak provider/validation payloads.
            raise AgentRuntimeError(f"Supplement request failed ({type(exc).__name__})") from exc

    async def _create(self, **kwargs):
        self.terminal = None
        self._claim_request()
        kwargs["max_tokens"] = 2048
        # Reuse the checked price evidence. Do not start unbounded synchronous
        # vendor downloads or a second historical engine from this short path.
        kwargs["tools"] = [tool for tool in kwargs.get("tools", [])
                           if tool["function"]["name"] in {"web_search", "file_reader"}]
        allowed = {tool["function"]["name"] for tool in kwargs["tools"]}
        if not kwargs["tools"]:
            kwargs.pop("tools")
        response = await self.client.chat.completions.create(**kwargs)
        usage = getattr(response, "usage", None)
        if usage:
            self.usage.add(kwargs["model"], usage.prompt_tokens or 0, usage.completion_tokens or 0)
        choice = response.choices[0]
        if choice.finish_reason not in {"stop", "tool_calls"}:
            raise ValueError("Incomplete supplemental model response")
        if any(call.function.name not in allowed for call in (choice.message.tool_calls or [])):
            raise UnauthorizedTool("Supplement model requested a tool outside its reduced allowlist")
        if choice.finish_reason == "stop" and not choice.message.tool_calls and self.schema:
            parsed = parse_model_json(self.schema, choice.message.content or "")
            if self.evidence_ids is not None:
                ids = [v.evidence_id for v in parsed.verdicts]
                if len(ids) != len(set(ids)) or set(ids) != self.evidence_ids:
                    raise ValueError("Supplement verifier omitted or invented evidence IDs")
                if any(v.status is VerificationStatus.VERIFIED and not v.rechecked_source for v in parsed.verdicts):
                    raise ValueError("Supplement verified verdict lacks a rechecked source")
            self.terminal = parsed
        return response


def _save(root: Path, result: Supplement, verification=None) -> Supplement:
    save_json(root / "research_status.json", result.model_dump(mode="json"))
    lines = ["# Optional research addendum", "", f"Status: {result.status}; additional LLM requests: {result.llm_requests}.", "",
             "The original daily brief is unchanged. This supplement is not an engine-delivery pass or a crowding score.", "",
             result.reason, ""]
    if result.alert:
        lines += [f"Trigger: {result.alert.observation}", "Operational heuristic only; not a calibrated risk signal.", ""]
    if verification:
        lines += [f"Verifier result: {verification.overall_status}", "", "## Evidence with verifier labels", ""]
        lines += [f"- [{v.status.value}] {v.claim}" for v in verification.verdicts]
        lines += ["", "## Unresolved evidence", "", *[f"- {gap.claim}" for gap in verification.gaps]]
    if result.session_dir:
        lines += ["", f"Research artifacts: {result.session_dir}",
                  "Failures are recorded in the existing gap ledger. Curate representative cases before running independent improvement; no automatic promotion."]
    (root / "research_addendum.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


async def run(root: Path, project_root: Path, previous: Path | None = None, *, enabled: bool = True, client=None) -> Supplement:
    root, project_root = root.resolve(), project_root.resolve()
    result = Supplement(status="unavailable")
    try:
        data = await asyncio.to_thread(market_brief.replay, root)
        result.source_sha256 = sha256_file(root / "market_brief.json")
        existing = root / "research_status.json"
        if existing.exists():
            saved = Supplement.model_validate_json(existing.read_text())
            if saved.source_sha256 != result.source_sha256:
                raise ValueError("Supplement source changed")
            return saved
        older = None
        if previous:
            try:
                older = await asyncio.to_thread(market_brief.replay, previous.parent)
                if older["facts"]["target_date"] >= data["facts"]["target_date"]:
                    older = None
            except (OSError, ValueError, KeyError, TypeError):
                pass
        result.alert = select_alert(data, older)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result.reason = f"Saved daily evidence failed replay ({type(exc).__name__}); no research launched."
        return _save(root, result)
    if not enabled:
        result.status, result.reason = "disabled", "Supplemental LLM research disabled; daily brief remains available."
        return _save(root, result)
    if result.alert is None:
        result.status, result.reason = "no_alert", "No eligible anomaly or newly lost optional evidence; no extra LLM request."
        return _save(root, result)
    owned = client is None
    try:
        if owned:
            client = make_client()
        limited = LimitedClient(client)
    except Exception as exc:
        result.reason = f"Research client unavailable ({type(exc).__name__}); daily brief preserved."
        return _save(root, result)
    target = date.fromisoformat(data["facts"]["target_date"])
    session = project_root / "reports/brief_research" / str(target)
    board = task = report = verification = None
    try:
        try:
            session.mkdir(parents=True, exist_ok=False)  # Atomic one-attempt-per-target-day gate.
        except FileExistsError:
            result.status, result.reason = "duplicate", "Research already claimed for this target date; no second attempt."
            result.session_dir = session
            return _save(root, result)
        result.session_dir = session
        save_json(session / "brief_context.json", {"source_sha256": result.source_sha256, **data})
        prompt = (Path(__file__).parent / "coordinator/prompts/brief_research.md").read_text()
        assignment = prompt + f"\nChecked evidence file (read-only): {session / 'brief_context.json'}\nQuoted evidence JSON:\n" + json.dumps({
            "target_date": str(target), "trigger": result.alert.model_dump(), "answers": data["answers"],
            "metrics": data["facts"]["metrics"]}, ensure_ascii=False)
        board = TaskBoard(session, question=assignment, session_id=f"brief-research-{target}")
        task = board.add_task("Investigate daily brief alert", assignment, result.alert.profile)
        board.activate(task.id)
        policy = load_or_snapshot_policy(session, project_root)
        result.status, result.reason = "running", "Daily brief already saved; bounded optional research in progress."
        _save(root, result)
        async with asyncio.timeout(60):
            limited.begin(ResearchReport)
            agent = SubAgent(client=limited, model=sub_agent_model(), project_root=project_root, policy=policy,
                             budget=LoopBudget(max_turns=3, overall_deadline_s=35, llm_timeout_s=15, tool_timeout_s=8))
            response = await agent.run(task, None, session)
            report = response.report
            limited.require_completion()
            board.record_usage(task.id, tool_calls=response.tool_calls, tokens_used=response.usage.total_tokens)
            board.complete(task.id, report.summary)
            verifier = Verifier(client=limited, model=sub_agent_model(), project_root=project_root,
                                budget=LoopBudget(max_turns=2, overall_deadline_s=25, llm_timeout_s=15, tool_timeout_s=8))
            limited.begin(VerificationReport, {item.id for item in report.findings})
            verified = await verifier.run(assignment, [report], session)
            if report.findings:
                limited.require_completion()
            verification = verified.report
        result.status = "complete" if report.status == "complete" and verification.overall_status == "pass" else "partial"
        result.reason = "One analyst and independent verifier completed; inspect evidence labels and unresolved questions."
    except BaseException as exc:
        result.status = "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
        result.reason = f"Optional research stopped ({type(exc).__name__}); daily brief preserved."
        if board is not None and task is not None:
            if task.status.value == "active":
                board.fail(task.id, result.reason, error_type=type(exc).__name__)
            if report is None:
                report = ResearchReport(task_id=task.id, title=task.title, agent_role=task.profile,
                    status="insufficient_evidence", summary=result.reason, findings=[], unanswered_questions=[result.reason])
                persist_research_report(session, task, report)
            static = static_audit(assignment, [report])
            for verdict in static.verdicts:
                if verdict.status is VerificationStatus.VERIFIED:
                    verdict.status = VerificationStatus.UNCHECKED
                    verdict.notes = "Independent re-check incomplete; static metadata is not verification."
            static.missing_evidence.append(result.reason)
            static.overall_status = "fail"
            verification = finalize_ledger(static, [report], load_traces(session))
            persist_verification_report(session, verification)
        if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
            raise
    finally:
        result.llm_requests, result.usage = limited.requests, limited.usage.model_dump(mode="json")
        if verification is not None:
            try:
                record_session_gaps(project_root, session, board.session_id, report_gaps=verification.gaps)
            except (OSError, ValueError, KeyError, TypeError):
                result.reason += " Gap ledger persistence failed; session verification remains available for manual import."
        _save(root, result, verification)
        if owned:
            try:
                await asyncio.wait_for(client.close(), timeout=2)
            except Exception:
                pass
    return result
