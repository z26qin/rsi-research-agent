from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from momentum_research_agent.coordinator.coordinator import Coordinator
from momentum_research_agent.models.schemas import (
    AgentRunResult,
    Evidence,
    EvidenceCategory,
    EvidenceStance,
    EvidenceVerdict,
    ResearchReport,
    UsageSummary,
    VerificationReport,
    VerificationRunResult,
    VerificationStatus,
)
from momentum_research_agent.state.reports import (
    load_research_report,
    persist_research_report,
    persist_verification_report,
)
from momentum_research_agent.state.policies import PolicyPatch, PolicyStore, merge_policy_patch


class FakeUsage:
    prompt_tokens = 100
    completion_tokens = 50


def _coordinator(tmp_path: Path) -> Coordinator:
    return Coordinator(
        session_dir=tmp_path / "session",
        client=FakeClient([]),  # type: ignore[arg-type]
        question="Is the NVDA selloff a crash?",
        project_root=tmp_path,
    )


def test_coordinator_pins_active_policy_at_construction(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path)
    baseline = store.load_active()
    coordinator = _coordinator(tmp_path)
    candidate = merge_policy_patch(
        baseline,
        PolicyPatch(prompt_overlays={"momentum_analyst": "new rule"}),
        trigger_ids=["trajectory:new-rule"],
    )
    store.write_version(candidate)
    store.activate(candidate.version_id)

    assert coordinator.policy.version_id == baseline.version_id
    assert PolicyStore(tmp_path).load_active().version_id == candidate.version_id


def test_coordinator_resume_uses_session_policy_snapshot(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path)
    coordinator = _coordinator(tmp_path)
    baseline_id = coordinator.policy.version_id
    candidate = merge_policy_patch(
        coordinator.policy,
        PolicyPatch(prompt_overlays={"momentum_analyst": "new rule"}),
        trigger_ids=["trajectory:new-rule"],
    )
    store.write_version(candidate)
    store.activate(candidate.version_id)

    resumed = _coordinator(tmp_path)

    assert resumed.policy.version_id == baseline_id


class FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=None))]
        self.usage = FakeUsage()


class FakeCompletions:
    def __init__(self, payloads: list[str]) -> None:
        self._payloads = list(payloads)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._payloads:
            raise AssertionError("unexpected extra LLM call")
        return FakeResponse(self._payloads.pop(0))


class FakeClient:
    def __init__(self, payloads: list[str]) -> None:
        self.completions = FakeCompletions(payloads)
        self.chat = SimpleNamespace(completions=self.completions)


DECOMPOSE = json.dumps(
    {
        "reasoning": "Split price-factor state from credit confirmation.",
        "tasks": [
            {
                "title": "Momentum state",
                "assignment": "Query the engine and tape for NVDA momentum crash risk.",
                "profile": "momentum_analyst",
            },
            {
                "title": "Credit overlay",
                "assignment": "Check whether NVDA credit confirms the equity unwind.",
                "profile": "credit_analyst",
            },
        ],
    }
)

SYNTHESIS = json.dumps(
    {
        "question": "Is the NVDA selloff a crash?",
        "executive_summary": "The tape looks like a rotation, not a DM crash.",
        "analysis_by_dimension": {
            "momentum": "Crowding is fading but crash frequency is not critical.",
            "credit": "No credit event confirms an unwind cascade.",
        },
        "risk_assessment": "Net read is healthy rotation with residual crowding risk.",
        "actionable_signals": ["Do not flatten the whole book", "Watch SMH breadth"],
        "confidence_level": "medium",
        "dissenting_views": ["Credit data is thin"],
    }
)


def _run_result(task, prompt_tokens: int, completion_tokens: int) -> AgentRunResult:
    usage = UsageSummary()
    usage.add("deepseek-chat", prompt_tokens, completion_tokens)
    report = ResearchReport(
        task_id=task.id,
        title=task.title,
        agent_role=task.profile,
        findings=[
            Evidence(
                claim=f"Mock evidence for {task.profile}",
                category=EvidenceCategory.MARKET_REGIME,
                stance=EvidenceStance.SUPPORTING,
                source_name="test",
                confidence="high",
                agent_id=task.id,
            )
        ],
        summary=f"Mock findings for {task.profile}",
        unanswered_questions=[],
        contradictions=["tape vs credit is thin"] if task.profile == "credit_analyst" else [],
        status="complete",
    )
    return AgentRunResult(report=report, usage=usage, tool_calls=2)


async def fake_verify(self, question, reports, session_dir):
    report = VerificationReport(
        question=question,
        overall_status="pass_with_caveats",
        summary="mock verification",
        verdicts=[],
    )
    persist_verification_report(session_dir, report)
    return VerificationRunResult(report=report)


def _patch_runtime(monkeypatch: pytest.MonkeyPatch, fake_run) -> None:
    monkeypatch.setattr(
        "momentum_research_agent.coordinator.coordinator.SubAgent.run",
        fake_run,
    )
    monkeypatch.setattr(
        "momentum_research_agent.coordinator.coordinator.Verifier.run",
        fake_verify,
    )


@pytest.mark.asyncio
async def test_decompose_dispatch_synthesize_writes_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_dir = tmp_path / "20260101_120000_deadbeef"
    client = FakeClient([DECOMPOSE, SYNTHESIS])
    usage = UsageSummary()
    coordinator = Coordinator(
        session_dir=session_dir,
        client=client,  # type: ignore[arg-type]
        question="Is the NVDA selloff a crash?",
        project_root=tmp_path,
        sub_model="deepseek-chat",
        coordinator_model_name="deepseek-reasoner",
        max_sub_agents=4,
        usage_tracker=usage,
    )

    async def fake_run(self, task, tools, session_dir):
        result = _run_result(task, 30, 10)
        persist_research_report(session_dir, task, result.report)
        return result

    _patch_runtime(monkeypatch, fake_run)

    report = await coordinator.run("Is the NVDA selloff a crash?")

    assert report.executive_summary.startswith("The tape looks like a rotation")
    assert (session_dir / "task_board.json").exists()
    assert (session_dir / "synthesis.md").exists()
    assert (session_dir / "synthesis.json").exists()
    assert (session_dir / "verification.json").exists()
    assert (session_dir / "verification.md").exists()
    assert len(list((session_dir / "sub_reports").glob("*.md"))) == 2
    assert len(list((session_dir / "sub_reports").glob("*.json"))) == 2
    board = json.loads((session_dir / "task_board.json").read_text(encoding="utf-8"))
    assert board["question"] == "Is the NVDA selloff a crash?"
    assert {task["status"] for task in board["tasks"]} == {"COMPLETED"}
    assert len(client.completions.calls) == 2
    assert "Independent verification" in client.completions.calls[1]["messages"][-1]["content"]
    assert usage.total_tokens == 300 + 80
    synthesis_text = (session_dir / "synthesis.md").read_text(encoding="utf-8")
    assert "Actionable Signals" in synthesis_text


@pytest.mark.asyncio
async def test_parallel_usage_is_local_then_merged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_dir = tmp_path / "session"
    client = FakeClient([DECOMPOSE, SYNTHESIS])
    usage = UsageSummary()
    coordinator = Coordinator(
        session_dir=session_dir,
        client=client,  # type: ignore[arg-type]
        question="Is the NVDA selloff a crash?",
        project_root=tmp_path,
        usage_tracker=usage,
    )

    async def fake_run(self, task, tools, session_dir):
        await asyncio.sleep(0.01)
        if task.profile == "momentum_analyst":
            result = _run_result(task, 100, 40)
        else:
            result = _run_result(task, 20, 10)
        persist_research_report(session_dir, task, result.report)
        return result

    _patch_runtime(monkeypatch, fake_run)

    await coordinator.run("Is the NVDA selloff a crash?")

    by_task = {task.profile: task for task in coordinator.board.tasks}
    assert by_task["momentum_analyst"].tokens_used == 140
    assert by_task["credit_analyst"].tokens_used == 30
    sub_agent_tokens = 140 + 30
    coordinator_tokens = 300
    assert usage.total_tokens == coordinator_tokens + sub_agent_tokens
    assert usage.prompt_tokens == 100 + 100 + 20 + 100
    assert usage.completion_tokens == 50 + 40 + 10 + 50


@pytest.mark.asyncio
async def test_resume_reloads_json_reports(tmp_path: Path) -> None:
    session_dir = tmp_path / "session"
    client = FakeClient([])
    coordinator = Coordinator(
        session_dir=session_dir,
        client=client,  # type: ignore[arg-type]
        question="Is the NVDA selloff a crash?",
        project_root=tmp_path,
    )
    task = coordinator.board.add_task("Momentum state", "Check crowding", "momentum_analyst")
    coordinator.board.activate(task.id)
    result = _run_result(task, 5, 5)
    persist_research_report(session_dir, task, result.report)
    coordinator.board.complete(task.id, result.report.summary)

    other = Coordinator(
        session_dir=session_dir,
        client=client,  # type: ignore[arg-type]
        question="Is the NVDA selloff a crash?",
        project_root=tmp_path,
        board=coordinator.board,
    )
    other._load_existing_sub_reports()
    loaded = other.sub_reports[task.id]
    assert loaded.findings[0].claim == f"Mock evidence for {task.profile}"
    assert loaded.contradictions == []
    assert loaded.status == "complete"
    assert load_research_report(session_dir, task) is not None


@pytest.mark.asyncio
async def test_dispatch_cancels_non_research_profile(tmp_path: Path) -> None:
    coordinator = Coordinator(
        session_dir=tmp_path / "session",
        client=FakeClient([]),  # type: ignore[arg-type]
        question="q",
        project_root=tmp_path,
    )
    task = coordinator.board.add_task("Audit yourself", "do not", "verifier")
    await coordinator.dispatch_all()
    restored = coordinator.board.get(task.id)
    assert restored.status.value == "CANCELLED"
    assert "not a research profile" in (restored.error or "")


@pytest.mark.asyncio
async def test_follow_up_dispatches_once_for_unchecked_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_dir = tmp_path / "session"
    client = FakeClient([DECOMPOSE, SYNTHESIS])
    coordinator = Coordinator(
        session_dir=session_dir,
        client=client,  # type: ignore[arg-type]
        question="Is the NVDA selloff a crash?",
        project_root=tmp_path,
        usage_tracker=UsageSummary(),
    )
    titles: list[str] = []
    verify_counts: list[int] = []

    async def fake_run(self, task, tools, session_dir):
        titles.append(task.title)
        result = _run_result(task, 30, 10)
        persist_research_report(session_dir, task, result.report)
        return result

    async def fake_verify(self, question, reports, session_dir):
        verify_counts.append(len(reports))
        if len(verify_counts) == 1:
            first = reports[0]
            report = VerificationReport(
                question=question,
                overall_status="pass_with_caveats",
                summary="unchecked claim",
                verdicts=[
                    EvidenceVerdict(
                        evidence_id=first.findings[0].id,
                        task_id=first.task_id,
                        claim=first.findings[0].claim,
                        status=VerificationStatus.UNCHECKED,
                        issues=["no source"],
                    )
                ],
            )
        else:
            report = VerificationReport(
                question=question,
                overall_status="pass",
                summary="follow-up repaired the gap",
                verdicts=[],
            )
        persist_verification_report(session_dir, report)
        return VerificationRunResult(report=report)

    monkeypatch.setattr(
        "momentum_research_agent.coordinator.coordinator.SubAgent.run",
        fake_run,
    )
    monkeypatch.setattr(
        "momentum_research_agent.coordinator.coordinator.Verifier.run",
        fake_verify,
    )

    report = await coordinator.run("Is the NVDA selloff a crash?")

    assert any(title.startswith("Follow-up:") for title in titles)
    assert len(titles) == 3
    assert verify_counts == [2, 3]
    followup_tasks = [task for task in coordinator.board.tasks if task.kind.value == "followup"]
    assert len(followup_tasks) == 1
    assert followup_tasks[0].profile in {"momentum_analyst", "credit_analyst"}
    assert report.executive_summary.startswith("The tape looks like a rotation")
    assert "Follow-up reports below" in client.completions.calls[1]["messages"][-1]["content"]
    # second follow-up must not spawn
    followed_again = await coordinator.follow_up()
    assert followed_again is False
