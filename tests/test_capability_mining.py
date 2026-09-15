import hashlib
import json

from momentum_research_agent.coordinator.task_board import TaskBoard
from momentum_research_agent.eval.capability_mining import Capability, mine_session
from momentum_research_agent.models.schemas import (
    GapEntry,
    GapKind,
    ReplayHint,
    ToolTrace,
    VerificationReport,
)
from momentum_research_agent.state.traces import append_traces


def test_successful_engine_read_does_not_override_specific_gap(tmp_path):
    session = tmp_path / "reports" / "source-session"
    board = TaskBoard(session, question="Assess momentum risk")
    task = board.add_task(
        title="Check contradictory evidence",
        assignment="Investigate missing high-quality contradictory evidence",
        profile="momentum_analyst",
    )
    observation = json.dumps({"delivery_contract": {"verdict": "pass"}})
    append_traces(
        session,
        [
            ToolTrace(
                tool="engine_query",
                arguments={},
                observation=observation,
                observation_sha256=hashlib.sha256(observation.encode()).hexdigest(),
                agent_id=task.id,
                agent_role=task.profile,
                replay=ReplayHint(method="stored_observation"),
            )
        ],
    )
    verification = VerificationReport(
        question=board.question,
        overall_status="fail",
        summary="Evidence gaps remain",
        gaps=[
            GapEntry(
                kind=GapKind.UNCHECKED_EVIDENCE,
                task_id=task.id,
                evidence_id="contradiction",
                claim="High-quality contradictory evidence was omitted",
            ),
            GapEntry(
                kind=GapKind.ENGINE_MOCK,
                evidence_id="engine",
                claim="Engine evidence was mock",
            ),
        ],
    )
    (session / "verification.json").write_text(verification.model_dump_json())

    cases = mine_session(session, tmp_path)
    assert cases[0].capabilities == [Capability.CONTRADICTION_SEARCH]
    assert cases[0].approved_world_ids == ["high_quality_contradiction"]
    assert cases[1].capabilities == [Capability.ENGINE_GROUNDING]
