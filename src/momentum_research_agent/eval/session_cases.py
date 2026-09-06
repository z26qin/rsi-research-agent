"""Import verified session failures as pending, offline evaluation cases."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from momentum_research_agent.coordinator.gap_seed import classify_capability
from momentum_research_agent.models.schemas import (
    GapEntry,
    MomentumCapability,
    ResearchReport,
    Task,
    ToolTrace,
    VerificationReport,
)

REPLAYABLE_TOOLS = frozenset({"engine_query", "web_search"})
UNSUPPORTED_REPLAY_TOOLS = frozenset({"file_reader", "local_dm", "market_data", "shell"})
_POLICY_VERSION_RE = re.compile(r"^[0-9a-f]{12}$")


class SessionEvalCase(BaseModel):
    """One uncurated failure occurrence with immutable recorded inputs.

    The importer deliberately supplies no expected answer.  A later, separate
    curation step must bind behavioral expectations to this case's content.
    """

    model_config = ConfigDict(extra="forbid")

    schema_kind: Literal["session_eval_case_v1"] = "session_eval_case_v1"
    case_id: str = Field(min_length=1)
    curation_status: Literal["pending"] = "pending"
    source_session_id: str = Field(min_length=1)
    source_question: str = ""
    source_task_id: str | None = None
    source_trace_ids: list[str] = Field(default_factory=list)
    profile: str | None = None
    capability: MomentumCapability
    task_title: str | None = None
    task_input: str | None = None
    failing_evidence: GapEntry
    tool_traces: list[ToolTrace] = Field(default_factory=list)
    source_artifact_hashes: dict[str, str] = Field(default_factory=dict)
    policy_version_id: str | None = None
    replayable: bool = False
    replay_blockers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_replay_contract(self) -> SessionEvalCase:
        if self.replayable and self.replay_blockers:
            raise ValueError("a replayable case cannot have replay blockers")
        if self.replayable and not self.tool_traces:
            raise ValueError("a replayable case must contain at least one tool trace")
        trace_ids = {trace.id for trace in self.tool_traces}
        if not trace_ids.issubset(set(self.source_trace_ids)):
            raise ValueError("tool trace ids must be declared in source_trace_ids")
        if self.replayable:
            if not self.profile or not self.task_input or not self.policy_version_id:
                raise ValueError("a replayable case must bind profile, task input, and policy")
            if trace_ids != set(self.source_trace_ids):
                raise ValueError("a replayable case must resolve every source trace id")
            for trace in self.tool_traces:
                if trace.truncated:
                    raise ValueError("replayable case contains truncated trace")
                if _sha256_text(trace.observation) != trace.observation_sha256:
                    raise ValueError("replayable case contains hash-mismatched trace")
        return self


def eval_cases_dir(project_root: Path) -> Path:
    return Path(project_root) / "reports" / "eval_cases"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_text(payload: str) -> str:
    return _sha256_bytes(payload.encode("utf-8"))


def _artifact_hashes(session_dir: Path) -> dict[str, str]:
    names = [
        "verification.json",
        "traces.jsonl",
        "task_board.json",
        "policy_snapshot.json",
    ]
    paths = [session_dir / name for name in names]
    paths.extend(sorted((session_dir / "sub_reports").glob("*.json")))
    return {
        path.relative_to(session_dir).as_posix(): _sha256_bytes(path.read_bytes())
        for path in paths
        if path.is_file()
    }


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_tasks(session_dir: Path) -> tuple[dict[str, Task], dict[str, Any], list[str]]:
    path = session_dir / "task_board.json"
    if not path.is_file():
        return {}, {}, ["missing task_board.json"]
    try:
        payload = _read_json(path)
        if not isinstance(payload, dict):
            raise ValueError("task board must be a JSON object")
        tasks = [Task.model_validate(item) for item in payload.get("tasks", [])]
    except (OSError, ValueError, TypeError):
        return {}, {}, ["invalid task_board.json"]
    return {task.id: task for task in tasks}, payload, []


def _load_traces(session_dir: Path) -> tuple[dict[str, ToolTrace], list[str]]:
    path = session_dir / "traces.jsonl"
    if not path.is_file():
        return {}, ["missing traces.jsonl"]
    traces: dict[str, ToolTrace] = {}
    blockers: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}, ["invalid traces.jsonl"]
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            trace = ToolTrace.model_validate(json.loads(line))
        except (ValueError, TypeError):
            blockers.append(f"invalid traces.jsonl line {line_number}")
            continue
        prior = traces.get(trace.id)
        if prior is not None:
            label = "conflicting" if prior != trace else "duplicate"
            blockers.append(f"{label} trace id in traces.jsonl")
            continue
        traces[trace.id] = trace
    return traces, blockers


def _load_policy_version(session_dir: Path) -> tuple[str | None, list[str]]:
    path = session_dir / "policy_snapshot.json"
    if not path.is_file():
        return None, ["missing policy_snapshot.json"]
    try:
        payload = _read_json(path)
        version_id = payload.get("version_id") if isinstance(payload, dict) else None
    except (OSError, ValueError, TypeError):
        return None, ["invalid policy_snapshot.json"]
    if not isinstance(version_id, str) or not _POLICY_VERSION_RE.fullmatch(version_id):
        return None, ["invalid policy_snapshot.json: version_id is not 12 lowercase hex characters"]
    return version_id, []


def _load_sub_reports(
    session_dir: Path,
) -> tuple[dict[str, ResearchReport], list[str]]:
    folder = session_dir / "sub_reports"
    if not folder.is_dir():
        return {}, ["missing sub_reports directory"]
    reports: dict[str, ResearchReport] = {}
    blockers: list[str] = []
    for path in sorted(folder.glob("*.json")):
        try:
            report = ResearchReport.model_validate(_read_json(path))
        except (OSError, ValueError, TypeError):
            blockers.append("invalid sub-report JSON")
            continue
        if report.task_id in reports:
            blockers.append("duplicate sub-report for task")
            continue
        reports[report.task_id] = report
    return reports, blockers


def _case_id(session_id: str, gap: GapEntry) -> str:
    return f"session:{session_id}:{gap.id}"


def _case_path(project_root: Path, case_id: str) -> Path:
    safe_name = _sha256_text(case_id)
    return eval_cases_dir(project_root) / f"{safe_name}.json"


def _write_case(project_root: Path, case: SessionEvalCase) -> Path:
    path = _case_path(project_root, case.case_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(case.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return path
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path


def _append_once(items: list[str], message: str) -> None:
    if message not in items:
        items.append(message)


def _trace_blockers(trace: ToolTrace) -> list[str]:
    blockers: list[str] = []
    if trace.tool not in REPLAYABLE_TOOLS:
        blockers.append(f"unsupported replay tool {trace.tool}")
    if trace.truncated:
        blockers.append("truncated observation for trace")
    if _sha256_text(trace.observation) != trace.observation_sha256:
        blockers.append("observation hash mismatch for trace")
    return blockers


def _verification_trace_mismatch(
    trace: ToolTrace,
    verification_traces: dict[str, ToolTrace],
) -> str | None:
    copied = verification_traces.get(trace.id)
    if copied is None:
        return "trace missing from verification.json"
    if copied != trace:
        return "trace differs between traces.jsonl and verification.json"
    return None


def import_session_cases(project_root: Path, session_dir: Path) -> list[SessionEvalCase]:
    """Import each recorded failure occurrence without network or model calls.

    A valid ``verification.json`` is required because it is the source of
    failing evidence.  Other incomplete artifacts become explicit replay
    blockers on pending cases instead of being filled with invented data.
    Re-importing the same persisted gap writes the same case path.
    """

    project_root = Path(project_root)
    session_dir = Path(session_dir)
    verification_path = session_dir / "verification.json"
    if not verification_path.is_file():
        raise FileNotFoundError("missing verification.json")
    try:
        verification = VerificationReport.model_validate(_read_json(verification_path))
    except (OSError, ValueError, TypeError):
        raise ValueError("invalid verification.json") from None

    tasks, board_payload, board_blockers = _load_tasks(session_dir)
    traces, trace_file_blockers = _load_traces(session_dir)
    policy_version_id, policy_blockers = _load_policy_version(session_dir)
    reports, report_file_blockers = _load_sub_reports(session_dir)
    source_hashes = _artifact_hashes(session_dir)
    session_id_value = board_payload.get("session_id") if board_payload else None
    session_id = (
        session_id_value.strip()
        if isinstance(session_id_value, str) and session_id_value.strip()
        else session_dir.name
    )
    question_value = board_payload.get("question") if board_payload else None
    question = question_value if isinstance(question_value, str) else verification.question
    verification_traces = {trace.id: trace for trace in verification.traces}

    imported: list[SessionEvalCase] = []
    for gap in verification.gaps:
        blockers = [
            *board_blockers,
            *trace_file_blockers,
            *policy_blockers,
            *report_file_blockers,
        ]
        task = tasks.get(gap.task_id or "")
        if task is None:
            _append_once(blockers, "failure has no matching task")
        report = reports.get(task.id) if task is not None else None
        if task is not None and report is None:
            _append_once(blockers, "missing sub-report for task")
        if report is not None and task is not None and report.agent_role != task.profile:
            _append_once(blockers, "sub-report role differs from task profile")

        selected_traces: list[ToolTrace] = []
        for trace_id in gap.trace_ids:
            trace = traces.get(trace_id)
            if trace is None:
                _append_once(blockers, "missing trace reference from traces.jsonl")
                continue
            selected_traces.append(trace)
            for reason in _trace_blockers(trace):
                _append_once(blockers, reason)
            mismatch = _verification_trace_mismatch(trace, verification_traces)
            if mismatch:
                _append_once(blockers, mismatch)
        if not gap.trace_ids:
            _append_once(blockers, "failure has no recorded tool traces")

        if task is not None:
            recorded_task_calls = sum(1 for trace in traces.values() if trace.agent_id == task.id)
            if task.tool_calls != recorded_task_calls:
                _append_once(
                    blockers,
                    "task tool-call count differs from recorded task traces",
                )
        if report is not None:
            dependencies = {
                finding.source_name
                for finding in report.findings
                if finding.source_name in UNSUPPORTED_REPLAY_TOOLS
            }
            for dependency in sorted(dependencies):
                _append_once(blockers, f"unsupported tool dependency {dependency}")

        case = SessionEvalCase(
            case_id=_case_id(session_id, gap),
            source_session_id=session_id,
            source_question=question,
            source_task_id=task.id if task is not None else gap.task_id,
            source_trace_ids=list(gap.trace_ids),
            profile=task.profile if task is not None else (report.agent_role if report else None),
            capability=classify_capability(gap),
            task_title=task.title if task is not None else None,
            task_input=task.assignment if task is not None else None,
            failing_evidence=gap,
            tool_traces=selected_traces,
            source_artifact_hashes=dict(source_hashes),
            policy_version_id=policy_version_id,
            replayable=not blockers,
            replay_blockers=blockers,
        )
        _write_case(project_root, case)
        imported.append(case)
    return imported


def load_session_eval_cases(project_root: Path) -> list[SessionEvalCase]:
    """Load all imported pending cases in stable case-id order."""

    root = eval_cases_dir(project_root)
    if not root.is_dir():
        return []
    cases = [
        SessionEvalCase.model_validate(_read_json(path))
        for path in sorted(root.glob("*.json"))
    ]
    return sorted(cases, key=lambda case: case.case_id)
