"""Immutable, file-backed research-policy versions."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Collection, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from momentum_research_agent.models.schemas import MomentumCapability, utcnow

MAX_POLICY_TEXT_LENGTH = 2_000
VERSION_ID_RE = re.compile(r"^[0-9a-f]{12}$")
EXPERIMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class ToolPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: str
    capability: MomentumCapability
    preferred_tools: list[str] = Field(default_factory=list, max_length=8)
    required_tools: list[str] = Field(default_factory=list, max_length=8)


class PolicyPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_overlays: dict[str, str] = Field(default_factory=dict, max_length=24)
    task_templates: dict[MomentumCapability, str] = Field(default_factory=dict, max_length=4)
    tool_policies: list[ToolPolicy] = Field(default_factory=list, max_length=24)


class PolicyEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_fixes: list[str] = Field(default_factory=list)
    aggregate_score: float
    case_results: dict[str, bool]


class ResearchPolicy(PolicyPatch):
    schema_kind: Literal["research_policy_v1"] = "research_policy_v1"
    version_id: str
    parent_version_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    trigger_ids: list[str] = Field(default_factory=list, max_length=24)
    evaluation: PolicyEvaluation | None = None


def _canonical_payload(
    patch: PolicyPatch,
    parent_version_id: str | None,
    trigger_ids: list[str],
) -> dict[str, Any]:
    return {
        "policy": patch.model_dump(mode="json"),
        "parent_version_id": parent_version_id,
        "trigger_ids": trigger_ids,
    }


def _version_id(
    patch: PolicyPatch,
    parent_version_id: str | None,
    trigger_ids: list[str],
) -> str:
    canonical = json.dumps(
        _canonical_payload(patch, parent_version_id, trigger_ids),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _expected_version_id(policy: ResearchPolicy) -> str:
    patch = PolicyPatch(
        prompt_overlays=policy.prompt_overlays,
        task_templates=policy.task_templates,
        tool_policies=policy.tool_policies,
    )
    return _version_id(patch, policy.parent_version_id, policy.trigger_ids)


def _validate_version_id(version_id: str) -> None:
    if not VERSION_ID_RE.fullmatch(version_id):
        raise ValueError("version_id must be 12 lowercase hexadecimal characters")


def _validate_experiment_id(experiment_id: str) -> None:
    if not EXPERIMENT_ID_RE.fullmatch(experiment_id):
        raise ValueError("experiment_id must be a safe filename identifier")


def _check_text(value: str, label: str) -> None:
    if len(value) > MAX_POLICY_TEXT_LENGTH:
        raise ValueError(f"{label} exceeds {MAX_POLICY_TEXT_LENGTH} characters")


def validate_policy(
    patch: PolicyPatch,
    profile_tools: Mapping[str, Collection[str]],
) -> None:
    """Reject policy content that can exceed existing research authorization."""
    if not (patch.prompt_overlays or patch.task_templates or patch.tool_policies):
        raise ValueError("policy patch must not be empty")

    for profile, overlay in patch.prompt_overlays.items():
        _check_text(profile, "profile")
        _check_text(overlay, f"prompt overlay for {profile}")
        if profile == "verifier":
            raise ValueError("verifier overlays are not allowed")
        if profile not in profile_tools:
            raise ValueError(f"unknown profile: {profile}")

    for capability, template in patch.task_templates.items():
        _check_text(capability.value, "capability")
        _check_text(template, f"task template for {capability.value}")

    for rule in patch.tool_policies:
        _check_text(rule.profile, "profile")
        if rule.profile == "verifier":
            raise ValueError("verifier tool policies are not allowed")
        if rule.profile not in profile_tools:
            raise ValueError(f"unknown profile: {rule.profile}")
        authorized = set(profile_tools[rule.profile])
        for tool in [*rule.preferred_tools, *rule.required_tools]:
            _check_text(tool, "tool")
            if tool not in authorized:
                raise ValueError(f"unknown tool for {rule.profile}: {tool}")


def merge_policy_patch(
    base: ResearchPolicy,
    patch: PolicyPatch,
    *,
    trigger_ids: list[str],
) -> ResearchPolicy:
    """Return a new content-addressed version without changing ``base``."""
    tool_policies = {
        (rule.profile, rule.capability): rule.model_copy(deep=True)
        for rule in base.tool_policies
    }
    tool_policies.update(
        {
            (rule.profile, rule.capability): rule.model_copy(deep=True)
            for rule in patch.tool_policies
        }
    )
    merged = PolicyPatch(
        prompt_overlays={**base.prompt_overlays, **patch.prompt_overlays},
        task_templates={**base.task_templates, **patch.task_templates},
        tool_policies=list(tool_policies.values()),
    )
    copied_triggers = list(trigger_ids)
    return ResearchPolicy(
        **merged.model_dump(),
        version_id=_version_id(merged, base.version_id, copied_triggers),
        parent_version_id=base.version_id,
        trigger_ids=copied_triggers,
    )


def compiled_overlay(
    policy: ResearchPolicy,
    profile: str,
    capability: MomentumCapability | None = None,
) -> str:
    """Compile one profile's non-authoritative research guidance."""
    if profile == "verifier":
        return ""
    lines: list[str] = []
    overlay = policy.prompt_overlays.get(profile)
    if overlay:
        lines.append(overlay)
    for rule in policy.tool_policies:
        if rule.profile != profile or (capability is not None and rule.capability != capability):
            continue
        preferred = ", ".join(rule.preferred_tools)
        required = ", ".join(rule.required_tools)
        if preferred:
            lines.append(f"Preferred tools for {rule.capability.value}: {preferred}.")
        if required:
            lines.append(f"Required tools for {rule.capability.value}: {required}.")
    return "\n".join(lines)


def task_template_addition(policy: ResearchPolicy, capability: MomentumCapability) -> str:
    """Return bounded task guidance for a capability, if a version supplies it."""
    return policy.task_templates.get(capability, "")


class PolicyStore:
    """Disk-backed immutable versions with an atomically replaced active pointer."""

    def __init__(self, project_root: Path) -> None:
        self.root = project_root / "reports" / "policies"
        self.versions_path = self.root / "versions"
        self.experiments_path = self.root / "experiments"
        self.active_path = self.root / "active.json"

    def version_path(self, version_id: str) -> Path:
        _validate_version_id(version_id)
        return self.versions_path / f"{version_id}.json"

    @staticmethod
    def _json_text(payload: Any) -> str:
        return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)

    def write_version(self, policy: ResearchPolicy) -> Path:
        _validate_version_id(policy.version_id)
        expected_version_id = _expected_version_id(policy)
        if policy.version_id != expected_version_id:
            raise ValueError("version_id does not match canonical policy content")
        path = self.version_path(policy.version_id)
        text = self._json_text(policy.model_dump(mode="json"))
        if path.exists():
            if path.read_text(encoding="utf-8") != text:
                raise ValueError(f"version {policy.version_id} has a different payload")
            return path
        self._atomic_write(path, text)
        return path

    def load_version(self, version_id: str) -> ResearchPolicy:
        _validate_version_id(version_id)
        payload = json.loads(self.version_path(version_id).read_text(encoding="utf-8"))
        policy = ResearchPolicy.model_validate(payload)
        _validate_version_id(policy.version_id)
        if policy.version_id != version_id or policy.version_id != _expected_version_id(policy):
            raise ValueError("version_id does not match canonical policy content")
        return policy

    def load_active(self) -> ResearchPolicy:
        if not self.active_path.exists():
            baseline_patch = PolicyPatch()
            baseline_version_id = _version_id(baseline_patch, None, [])
            baseline_path = self.version_path(baseline_version_id)
            if baseline_path.exists():
                baseline = self.load_version(baseline_version_id)
                self.activate(baseline.version_id)
                return baseline
            baseline = ResearchPolicy(
                **baseline_patch.model_dump(),
                version_id=baseline_version_id,
            )
            self.write_version(baseline)
            self.activate(baseline.version_id)
            return baseline
        pointer = json.loads(self.active_path.read_text(encoding="utf-8"))
        return self.load_version(pointer["version_id"])

    def activate(self, version_id: str) -> None:
        try:
            self.load_version(version_id)
        except ValueError as error:
            raise FileNotFoundError(version_id) from error
        self._atomic_write(self.active_path, self._json_text({"version_id": version_id}))

    def write_experiment(self, experiment_id: str, payload: Mapping[str, Any]) -> Path:
        _validate_experiment_id(experiment_id)
        path = self.experiments_path / f"{experiment_id}.json"
        self._atomic_write(path, self._json_text(dict(payload)))
        return path
