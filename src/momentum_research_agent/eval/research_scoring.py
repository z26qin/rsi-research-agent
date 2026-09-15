"""Conservative deterministic outcome scoring; hidden facts stay here."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from momentum_research_agent.eval.research_arena import ArenaRun
from momentum_research_agent.eval.research_world import FrozenResearchWorld
from momentum_research_agent.eval.withholding import missing_concepts_acknowledged
from momentum_research_agent.models.schemas import EvidenceStance, VerificationStatus

SCORING_VERSION = "extractive_v3"


class ResearchCapabilityScore(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)
    scoring_version: Literal["extractive_v1", "extractive_v2", "extractive_v3"] = "extractive_v1"
    interpretation_error_count: int = Field(default=0, ge=0)
    verified_claim_recall: float = Field(ge=0, le=1)
    unsupported_claim_count: int = Field(ge=0)
    contradiction_handling: float = Field(ge=0, le=1)
    required_evidence_coverage: float = Field(ge=0, le=1)
    correct_withholding: float = Field(ge=0, le=1)
    source_quality: float = Field(ge=0, le=1)
    unnecessary_tool_calls: int = Field(ge=0)
    research_budget_used: dict[str, int | float]
    completion_status: str
    verified_fact_ids: list[str] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            self.completion_status == "complete"
            and self.verified_claim_recall == 1
            and self.unsupported_claim_count == 0
            and self.interpretation_error_count == 0
            and self.contradiction_handling == 1
            and self.required_evidence_coverage == 1
            and self.correct_withholding == 1
        )


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold().rstrip(".")


def _date(value) -> str:
    if isinstance(value, datetime):
        return value.isoformat()[:10]
    return str(value)[:10]


def _score_run_v1(world: FrozenResearchWorld, run: ArenaRun) -> ResearchCapabilityScore:
    sources = {s.url: s for s in world.sources}
    reads: dict[str, set[str]] = {"research": set(), "verifier": set()}
    used = set()
    duplicate_calls = 0
    for trace in run.traces:
        key = (
            trace.agent_role,
            trace.tool,
            json.dumps(trace.arguments, sort_keys=True),
        )
        duplicate_calls += key in used
        used.add(key)
        if trace.tool != "read_url":
            continue
        try:
            data = json.loads(trace.observation)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("status") == "ok":
            reads["verifier" if trace.agent_role == "verifier" else "research"].add(
                trace.arguments.get("url")
            )
    verdicts = (
        {v.evidence_id: v for v in run.verification.verdicts}
        if run.verification
        else {}
    )
    verified = set()
    unsupported = 0
    qualities = {}
    # Count attempted unsupported claims even if production grounding removed them.
    for report in run.submitted_reports:
        for item in report.findings:
            source = sources.get(item.source_url)
            verdict = verdicts.get(item.id)
            match = next(
                (
                    f
                    for f in world.hidden_facts
                    if f.source_url == item.source_url
                    and _norm(f.quote) == _norm(item.excerpt or "")
                    and _norm(item.claim) in {_norm(f.claim), _norm(f.quote)}
                    and f.stance == item.stance
                    and f.category == item.category
                ),
                None,
            )
            grounded = (
                source is not None
                and item.excerpt
                and item.excerpt in source.text
                and item.source_url in reads["research"]
                and item.source_url in reads["verifier"]
                and item.published_at is not None
                and _date(item.published_at) == _date(source.published_at)
                and _date(source.published_at) <= world.as_of
                and _date(report.as_of) == world.as_of
            )
            # Non-target source sentences may be legitimate findings without earning
            # recall. Never let that path override an annotated fact's stance/claim.
            annotated_quote = any(
                f.source_url == item.source_url
                and _norm(f.quote) == _norm(item.excerpt or "")
                for f in world.hidden_facts
            )
            sentences = (
                {s.strip() for s in re.split(r"(?<=[.!?])\s+", source.text.strip())}
                if source
                else set()
            )
            extractive_other = (
                not annotated_quote
                and item.excerpt in sentences
                and _norm(item.claim) == _norm(item.excerpt or "")
            )
            if (
                (match or extractive_other)
                and grounded
                and run.verifier_completed
                and verdict
                and verdict.status is VerificationStatus.VERIFIED
            ):
                if match:
                    verified.add(match.fact_id)
                    qualities[match.fact_id] = source.quality
            else:
                unsupported += 1
    required = {f.fact_id for f in world.hidden_facts if f.required}
    covered = {
        f.fact_id
        for f in world.hidden_facts
        if f.required and f.source_url in reads["research"]
    }
    recall = len(verified & required) / len(required) if required else 1.0
    coverage = len(covered & required) / len(required) if required else 1.0
    contradictions = set(world.contradiction_fact_ids)
    contradiction = float(
        not contradictions
        or (contradictions <= verified and any(r.contradictions for r in run.reports))
    )
    withholding = 1.0
    if world.require_withholding:
        missing = _norm(
            " ".join(
                q
                for r in run.reports
                for q in [*r.unanswered_questions, *r.limitations]
            )
        )
        withholding = float(
            bool(run.reports)
            and all(r.status != "complete" for r in run.reports)
            and all(_norm(q) in missing for q in world.missing_evidence)
            and unsupported == 0
        )
    failures = []
    if recall < 1:
        failures.append("verified_claim_recall")
    if unsupported:
        failures.append("unsupported_claims")
    if coverage < 1:
        failures.append("required_evidence_coverage")
    if contradiction < 1:
        failures.append("contradiction_handling")
    if withholding < 1:
        failures.append("correct_withholding")
    complete = (
        run.completion_status
        if run.verifier_completed and run.world_hash == world.content_hash
        else "failed"
    )
    if complete != "complete":
        failures.append("incomplete_or_world_binding")
    return ResearchCapabilityScore(
        verified_claim_recall=recall,
        unsupported_claim_count=unsupported,
        contradiction_handling=contradiction,
        required_evidence_coverage=coverage,
        correct_withholding=withholding,
        source_quality=(
            sum(qualities.get(fid, 0) for fid in required) / len(required)
            if required
            else 0
        ),
        unnecessary_tool_calls=duplicate_calls,
        research_budget_used={
            "tokens": run.usage.total_tokens,
            "reserved_tokens": run.budget_tokens_reserved,
            "tool_calls": run.tool_calls,
            "llm_requests": run.llm_requests,
            "latency_ms": run.latency_ms,
        },
        completion_status=complete,
        verified_fact_ids=sorted(verified),
        failures=failures,
    )


def _extractive_norm(text: str) -> str:
    """Normalize presentation only; retain punctuation and complete sentences."""
    return re.sub(r"\s+", " ", text).strip().casefold()


def score_run(
    world: FrozenResearchWorld,
    run: ArenaRun,
    *,
    version: str = SCORING_VERSION,
) -> ResearchCapabilityScore:
    """Dispatch sealed experiments to their original deterministic scorer."""
    if version == "extractive_v1":
        return _score_run_v1(world, run)
    if version in {"extractive_v2", "extractive_v3"}:
        return _score_extractive(world, run, version=version)
    raise ValueError(f"unknown scoring version: {version}")


def _score_extractive(
    world: FrozenResearchWorld, run: ArenaRun, *, version: str
) -> ResearchCapabilityScore:
    category_aligned_recall = version == "extractive_v2"
    sources = {s.url: s for s in world.sources}
    reads: dict[str, set[str]] = {"research": set(), "verifier": set()}
    used = set()
    duplicate_calls = 0
    for trace in run.traces:
        key = (
            trace.agent_role,
            trace.tool,
            json.dumps(trace.arguments, sort_keys=True),
        )
        duplicate_calls += key in used
        used.add(key)
        if trace.tool != "read_url":
            continue
        try:
            data = json.loads(trace.observation)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("status") == "ok":
            reads["verifier" if trace.agent_role == "verifier" else "research"].add(
                trace.arguments.get("url")
            )
    verdicts = (
        {v.evidence_id: v for v in run.verification.verdicts}
        if run.verification
        else {}
    )
    verified = set()
    interpreted = set()
    unsupported = 0
    interpretation_errors = 0
    qualities = {}
    # Count attempted unsupported claims even if production grounding removed them.
    for report in run.submitted_reports:
        for item in report.findings:
            # Retrieval metadata is neither a research claim nor recall credit.
            if item.kind == "retrieval":
                continue
            source = sources.get(item.source_url)
            verdict = verdicts.get(item.id)
            quote = _extractive_norm(item.excerpt or "")
            extractive = bool(quote) and _extractive_norm(item.claim) == quote
            annotations = [
                fact
                for fact in world.hidden_facts
                if fact.source_url == item.source_url
                and _extractive_norm(fact.quote) == quote
            ]
            if extractive and any(
                {fact.stance, item.stance}
                == {EvidenceStance.SUPPORTING, EvidenceStance.CONTRADICTING}
                for fact in annotations
            ):
                interpretation_errors += 1
            sentences = (
                {
                    _extractive_norm(sentence)
                    for sentence in re.split(r"(?<=[.!?])\s+", source.text.strip())
                    if sentence.strip()
                }
                if source
                else set()
            )
            supported = (
                source is not None
                and extractive
                and quote in sentences
                and item.source_url in reads["research"]
                and item.source_url in reads["verifier"]
                and item.published_at is not None
                and _date(item.published_at) == _date(source.published_at)
                and _date(source.published_at) <= world.as_of
                and _date(report.as_of) == world.as_of
                and run.verifier_completed
                and verdict is not None
                and verdict.status is VerificationStatus.VERIFIED
            )
            if not supported:
                unsupported += 1
                continue
            # v2 retains historical annotation-aligned recall. In v3 exact
            # verified propositions earn factual recall independently of the
            # overlapping category enum; interpretation remains a separate gate.
            for fact in annotations:
                aligned = fact.stance == item.stance and (
                    not category_aligned_recall or fact.category == item.category
                )
                if aligned:
                    interpreted.add(fact.fact_id)
                if aligned or not category_aligned_recall:
                    verified.add(fact.fact_id)
                    qualities[fact.fact_id] = source.quality
    required = {f.fact_id for f in world.hidden_facts if f.required}
    covered = {
        f.fact_id
        for f in world.hidden_facts
        if f.required and f.source_url in reads["research"]
    }
    recall = len(verified & required) / len(required) if required else 1.0
    coverage = len(covered & required) / len(required) if required else 1.0
    contradictions = set(world.contradiction_fact_ids)
    contradiction = float(
        not contradictions
        or (contradictions <= interpreted and any(r.contradictions for r in run.reports))
    )
    withholding = 1.0
    if world.require_withholding:
        statements = [
            q for r in run.reports for q in [*r.unanswered_questions, *r.limitations]
        ]
        withholding = float(
            bool(run.reports)
            and all(r.status != "complete" for r in run.reports)
            and missing_concepts_acknowledged(world.missing_evidence, statements)
            and unsupported == 0
            and interpretation_errors == 0
        )
    failures = []
    if recall < 1:
        failures.append("verified_claim_recall")
    if unsupported:
        failures.append("unsupported_claims")
    if interpretation_errors:
        failures.append("interpretation_errors")
    if coverage < 1:
        failures.append("required_evidence_coverage")
    if contradiction < 1:
        failures.append("contradiction_handling")
    if withholding < 1:
        failures.append("correct_withholding")
    complete = (
        run.completion_status
        if run.verifier_completed and run.world_hash == world.content_hash
        else "failed"
    )
    if complete != "complete":
        failures.append("incomplete_or_world_binding")
    return ResearchCapabilityScore(
        scoring_version=version,
        interpretation_error_count=interpretation_errors,
        verified_claim_recall=recall,
        unsupported_claim_count=unsupported,
        contradiction_handling=contradiction,
        required_evidence_coverage=coverage,
        correct_withholding=withholding,
        source_quality=(
            sum(qualities.get(fid, 0) for fid in required) / len(required)
            if required
            else 0
        ),
        unnecessary_tool_calls=duplicate_calls,
        research_budget_used={
            "tokens": run.usage.total_tokens,
            "reserved_tokens": run.budget_tokens_reserved,
            "tool_calls": run.tool_calls,
            "llm_requests": run.llm_requests,
            "latency_ms": run.latency_ms,
        },
        completion_status=complete,
        verified_fact_ids=sorted(verified),
        failures=failures,
    )


class ArenaDecision(BaseModel):
    promote: bool
    reasons: list[str] = Field(default_factory=list)
    target_improvements: list[str] = Field(default_factory=list)


def compare_arena_runs(
    baseline: list[ArenaRun],
    candidate: list[ArenaRun],
    baseline_scores: dict[str, ResearchCapabilityScore],
    candidate_scores: dict[str, ResearchCapabilityScore],
    *,
    target_ids: set[str],
    guard_ids: set[str],
    engine_guards_passed: bool,
) -> ArenaDecision:
    reasons, improvements = [], []
    b = {r.world_id: r for r in baseline}
    c = {r.world_id: r for r in candidate}
    if not engine_guards_passed:
        reasons.append("deterministic_engine_guards_failed")
    if (
        not b
        or set(b) != set(c)
        or len(b) != len(baseline)
        or len(c) != len(candidate)
        or set(b) != set(baseline_scores)
        or set(c) != set(candidate_scores)
        or not target_ids
        or not target_ids <= set(b)
        or not guard_ids <= set(b)
    ):
        return ArenaDecision(
            promote=False, reasons=[*reasons, "invalid_world_selection"]
        )
    versions = {
        score.scoring_version
        for score in [*baseline_scores.values(), *candidate_scores.values()]
    }
    if len(versions) != 1:
        reasons.append("inconsistent_scoring_versions")
    all_runs = [*baseline, *candidate]
    requested_models = {run.requested_model for run in all_runs}
    resolved_models = {model for run in all_runs for model in run.response_model_ids}
    if (
        len(requested_models) != 1
        or "" in requested_models
        or len(resolved_models) != 1
        or resolved_models.intersection({"", "unknown"})
    ):
        reasons.append("experiment_model_drift")
    capability_dimensions = (
        "verified_claim_recall",
        "contradiction_handling",
        "correct_withholding",
    )
    guard_dimensions = (
        *capability_dimensions,
        "required_evidence_coverage",
        "source_quality",
    )
    for wid, left in b.items():
        right = c[wid]
        old, new = baseline_scores[wid], candidate_scores[wid]
        if left.world_hash != right.world_hash:
            reasons.append(f"{wid}:world_hash_mismatch")
        if (
            left.controls != right.controls
            or left.profile_hashes != right.profile_hashes
        ):
            reasons.append(f"{wid}:controls_or_profiles_mismatch")
        if (
            left.requested_model != right.requested_model
            or len(left.response_model_ids) != 1
            or left.response_model_ids != right.response_model_ids
            or "unknown" in left.response_model_ids
        ):
            reasons.append(f"{wid}:resolved_model_mismatch")
        if any(
            r.completion_status != "complete" or not r.verifier_completed
            for r in (left, right)
        ) or any(s.completion_status != "complete" for s in (old, new)):
            reasons.append(f"{wid}:incomplete")
        for r in (left, right):
            if (
                r.tool_calls > r.controls.max_tool_calls
                or r.llm_requests > r.controls.max_llm_requests
                or r.budget_tokens_reserved > r.controls.max_total_tokens
                or r.usage.total_tokens > r.controls.max_total_tokens
                or r.latency_ms > r.controls.overall_deadline_s * 1000
                or r.schema_repair_requests > r.controls.max_schema_repairs
            ):
                reasons.append(f"{wid}:bounds_exceeded")
        if new.unsupported_claim_count > old.unsupported_claim_count:
            reasons.append(f"{wid}:unsupported_claims_increased")
        if new.interpretation_error_count > old.interpretation_error_count:
            reasons.append(f"{wid}:interpretation_errors_increased")
        for dim in ("contradiction_handling", "correct_withholding"):
            if getattr(new, dim) < getattr(old, dim):
                reasons.append(f"{wid}:{dim}_regressed")
        if wid in guard_ids and any(
            getattr(new, k) < getattr(old, k) for k in guard_dimensions
        ):
            reasons.append(f"{wid}:guard_regression")
        if (
            wid in target_ids
            and any(getattr(new, k) > getattr(old, k) for k in capability_dimensions)
            and all(getattr(new, k) >= getattr(old, k) for k in guard_dimensions)
            and new.unsupported_claim_count <= old.unsupported_claim_count
            and new.interpretation_error_count <= old.interpretation_error_count
        ):
            improvements.append(wid)
    if not improvements:
        reasons.append("no_target_capability_improvement")
    return ArenaDecision(
        promote=not reasons,
        reasons=sorted(reasons),
        target_improvements=sorted(improvements),
    )
