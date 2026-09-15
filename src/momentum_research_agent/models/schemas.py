"""Pydantic models for the task board, sub-reports, and synthesis."""

from __future__ import annotations

import re
import secrets
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_task_id() -> str:
    return secrets.token_hex(4)


def new_session_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{secrets.token_hex(4)}"


def new_evidence_id() -> str:
    return secrets.token_hex(4)


def new_trace_id() -> str:
    return secrets.token_hex(4)


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class TaskKind(str, Enum):
    RESEARCH = "research"
    FOLLOWUP = "followup"
    GAP = "gap"
    REPLAN = "replan"


class InvalidTransition(ValueError):
    """Raised when a TaskBoard status change is not allowed."""


ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.ACTIVE, TaskStatus.CANCELLED},
    TaskStatus.ACTIVE: {TaskStatus.COMPLETED, TaskStatus.BLOCKED, TaskStatus.CANCELLED},
    TaskStatus.BLOCKED: {TaskStatus.ACTIVE, TaskStatus.CANCELLED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.CANCELLED: set(),
}


class Task(BaseModel):
    id: str = Field(default_factory=new_task_id)
    title: str
    assignment: str
    profile: str
    status: TaskStatus = TaskStatus.PENDING
    report: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    tool_calls: int = 0
    tokens_used: int = 0
    error_type: Optional[str] = None
    kind: TaskKind = TaskKind.RESEARCH


class TaskSpec(BaseModel):
    title: str
    assignment: str
    profile: str

    @field_validator("profile")
    @classmethod
    def normalize_profile(cls, value: str) -> str:
        return value.strip().removesuffix(".md")


class DecompositionResult(BaseModel):
    tasks: list[TaskSpec]
    reasoning: str


class EvidenceCategory(str, Enum):
    MARKET_REGIME = "market_regime"
    CROWDED_POSITIONING = "crowded_positioning"
    FUNDAMENTAL_REPRICING = "fundamental_repricing"
    CONTRADICTING_EVIDENCE = "contradicting_evidence"
    OTHER = "other"


class EvidenceStance(str, Enum):
    SUPPORTING = "supporting"
    CONTRADICTING = "contradicting"
    NEUTRAL = "neutral"


class Evidence(BaseModel):
    id: str = Field(default_factory=new_evidence_id)
    claim: str
    category: EvidenceCategory
    stance: EvidenceStance
    source_url: str | None = None
    source_name: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime = Field(default_factory=utcnow)
    excerpt: str | None = None
    confidence: Literal["high", "medium", "low"] = "medium"
    agent_id: str | None = None
    kind: Literal['research', 'retrieval'] = 'research'


class NumericMetric(BaseModel):
    name: str = Field(min_length=1)
    value: float | None = Field(default=None, allow_inf_nan=False)
    unit: str = Field(min_length=1)
    as_of: date | None = None
    source_url: str | None = None
    evidence_id: str | None = None
    missing_reason: str | None = None

    @model_validator(mode='after')
    def require_provenance(self):
        if self.value is not None:
            if not self.as_of or not self.evidence_id or not self.source_url or not self.source_url.startswith(('https://','http://')):
                raise ValueError('Numeric values require observation date, source URL and evidence_id')
        elif not self.missing_reason:
            raise ValueError('Unavailable metrics require missing_reason, never substitute zero')
        return self


class ResearchReport(BaseModel):
    task_id: str
    title: str
    agent_role: str
    findings: list[Evidence] = Field(default_factory=list)
    summary: str
    as_of: date | None = None
    sources: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    unanswered_questions: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    status: Literal["complete", "partial", "insufficient_evidence"] = "complete"
    metrics: list[NumericMetric] = Field(default_factory=list)

    @model_validator(mode='after')
    def bind_metrics(self):
        evidence = {item.id:item for item in self.findings}
        if len(evidence) != len(self.findings):
            raise ValueError('Evidence IDs must be unique within a report')
        for metric in self.metrics:
            if metric.value is not None and (metric.evidence_id not in evidence or evidence[metric.evidence_id].source_url != metric.source_url):
                raise ValueError('Metric must reference an Evidence item with the same source URL')
        return self


class SynthesisReport(BaseModel):
    question: str
    executive_summary: str
    analysis_by_dimension: dict[str, str] = Field(default_factory=dict)
    risk_assessment: str
    actionable_signals: list[str] = Field(default_factory=list)
    confidence_level: str
    dissenting_views: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=utcnow)
    metrics: list[NumericMetric] = Field(default_factory=list)


class UsageEvent(BaseModel):
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class UsageSummary(BaseModel):
    events: list[UsageEvent] = Field(default_factory=list)

    def add(self, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        self.events.append(
            UsageEvent(
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        )

    def totals(self) -> dict[str, dict[str, int]]:
        by_model: dict[str, dict[str, int]] = {}
        for event in self.events:
            bucket = by_model.setdefault(
                event.model, {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
            )
            bucket["prompt_tokens"] += event.prompt_tokens
            bucket["completion_tokens"] += event.completion_tokens
            bucket["calls"] += 1
        return by_model

    @property
    def prompt_tokens(self) -> int:
        return sum(event.prompt_tokens for event in self.events)

    @property
    def completion_tokens(self) -> int:
        return sum(event.completion_tokens for event in self.events)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def extend(self, other: UsageSummary) -> None:
        self.events.extend(event.model_copy() for event in other.events)


class AgentRunResult(BaseModel):
    report: ResearchReport
    usage: UsageSummary = Field(default_factory=UsageSummary)
    tool_calls: int = 0
    traces: list["ToolTrace"] = Field(default_factory=list)


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    WEAK = "weak"
    REJECTED = "rejected"
    UNCHECKED = "unchecked"


class GapKind(str, Enum):
    REJECTED_EVIDENCE = "rejected_evidence"
    UNCHECKED_EVIDENCE = "unchecked_evidence"
    MISSING_EVIDENCE = "missing_evidence"
    UNANSWERED_QUESTION = "unanswered_question"
    ENGINE_MOCK = "engine_mock"


class MomentumCapability(str, Enum):
    CROWDING = "crowding"
    UNWIND_CRASH = "unwind_crash"
    ENGINE_FRESHNESS = "engine_freshness"
    SOURCE_QUALITY = "source_quality"


class GapLedgerStatus(str, Enum):
    OPEN = "OPEN"
    CONSUMED = "CONSUMED"
    CLOSED = "CLOSED"


class ReplayHint(BaseModel):
    """How to replay a stored engine/search observation."""

    method: Literal["engine_snapshot", "stored_observation"]
    source: str | None = None
    source_path: str | None = None
    as_of: str | None = None
    query: str | None = None


class ToolTrace(BaseModel):
    """One replayable engine_query or web_search call."""

    id: str = Field(default_factory=new_trace_id)
    tool: Literal["engine_query", "web_search", "read_url", "market_data"]
    arguments: dict[str, Any] = Field(default_factory=dict)
    observation: str
    observation_sha256: str
    truncated: bool = False
    timestamp: datetime = Field(default_factory=utcnow)
    agent_id: str | None = None
    agent_role: str | None = None
    replay: ReplayHint


class GapEntry(BaseModel):
    """One row in the per-session momentum gap ledger."""

    id: str = Field(default_factory=new_evidence_id)
    kind: GapKind
    claim: str
    notes: str = ""
    evidence_id: str | None = None
    task_id: str | None = None
    status: VerificationStatus | None = None
    trace_ids: list[str] = Field(default_factory=list)


class GapLedgerRow(BaseModel):
    """One line in the cross-session `reports/gap_ledger.jsonl` book."""

    evidence_id: str
    capability: MomentumCapability
    status: GapLedgerStatus = GapLedgerStatus.OPEN
    gap_kind: GapKind
    claim: str
    notes: str = ""
    source_session_id: str | None = None
    consumed_session_id: str | None = None
    consumed_task_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class EvidenceVerdict(BaseModel):
    evidence_id: str
    task_id: str | None = None
    claim: str
    status: VerificationStatus
    notes: str = ""
    issues: list[str] = Field(default_factory=list)
    rechecked_source: str | None = None


class VerificationReport(BaseModel):
    question: str
    overall_status: Literal["pass", "pass_with_caveats", "fail"]
    summary: str
    verdicts: list[EvidenceVerdict] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=utcnow)
    schema_kind: Literal["momentum_gap_ledger"] = "momentum_gap_ledger"
    gaps: list[GapEntry] = Field(default_factory=list)
    traces: list[ToolTrace] = Field(default_factory=list)


class VerificationRunResult(BaseModel):
    report: VerificationReport
    usage: UsageSummary = Field(default_factory=UsageSummary)
    tool_calls: int = 0
    traces: list[ToolTrace] = Field(default_factory=list)


def extract_json_text(text: str) -> str:
    """Strip markdown fences and isolate the outermost JSON object/array."""
    cleaned = text.strip()
    fence = re.match(r"^```(?:json)?\s*\n?(.*)```\s*$", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    start_obj = cleaned.find("{")
    start_arr = cleaned.find("[")
    starts = [index for index in (start_obj, start_arr) if index != -1]
    if not starts:
        return cleaned
    start = min(starts)
    end_char = "}" if cleaned[start] == "{" else "]"
    end = cleaned.rfind(end_char)
    if end == -1:
        return cleaned[start:]
    return cleaned[start : end + 1]


def parse_model_json(model_cls: type[BaseModel], text: str) -> Any:
    return model_cls.model_validate_json(extract_json_text(text))
