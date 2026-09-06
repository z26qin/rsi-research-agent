"""Render and compile the active immutable research policy.

Ledger failures remain decomposition data. Only promoted policy content reaches
research profiles, and verifier prompts never receive an overlay.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from momentum_research_agent.config import reports_root
from momentum_research_agent.state.policies import (
    PolicyStore,
    ResearchPolicy,
    compiled_overlay,
)


def evolution_path(project_root: Path) -> Path:
    return reports_root(project_root) / "prompt_evolution.json"


def hints_path(project_root: Path) -> Path:
    return reports_root(project_root) / "profile_hints.md"


def _ledger_path(project_root: Path) -> Path:
    return reports_root(project_root) / "gap_ledger.jsonl"


def _load_ledger_rows(project_root: Path) -> list[dict[str, Any]]:
    path = _ledger_path(project_root)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def refresh_profile_hints(
    project_root: Path,
    *,
    extra_failures: list[dict[str, Any]] | None = None,
) -> Path:
    """Render active policy metadata for operators without changing prompts.

    ``extra_failures`` is intentionally retained for compatibility with eval
    callers. Failures require policy promotion before they can affect prompts.
    """
    del extra_failures
    policy = PolicyStore(project_root).load_active()
    payload = {
        "schema": "prompt_evolution_v2",
        "policy": policy.model_dump(mode="json"),
    }
    evo = evolution_path(project_root)
    evo.parent.mkdir(parents=True, exist_ok=True)
    evo.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Runtime profile hints (generated; do not commit analyst profiles)",
        "",
        f"Policy version: `{policy.version_id}`",
        f"Parent version: `{policy.parent_version_id or '(baseline)'}`",
        "",
    ]
    lines.extend(["## Profile overlays", ""])
    if policy.prompt_overlays:
        for profile, overlay in sorted(policy.prompt_overlays.items()):
            lines.extend([f"### {profile}", "", overlay, ""])
    else:
        lines.extend(["(none)", ""])
    lines.extend(["## Task additions", ""])
    if policy.task_templates:
        for capability, addition in sorted(policy.task_templates.items(), key=lambda item: item[0].value):
            lines.append(f"- `{capability.value}`: {addition}")
    else:
        lines.append("(none)")
    lines.extend(["", "## Tool guidance", ""])
    if policy.tool_policies:
        for rule in policy.tool_policies:
            preferred = ", ".join(rule.preferred_tools) or "(none)"
            required = ", ".join(rule.required_tools) or "(none)"
            lines.append(
                f"- `{rule.profile}` / `{rule.capability.value}`: "
                f"preferred={preferred}; required={required}"
            )
    else:
        lines.append("(none)")
    hints = hints_path(project_root)
    hints.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return hints


def overlay_text(
    project_root: Path,
    profile: str,
    *,
    policy: ResearchPolicy | None = None,
) -> str:
    """Compile only a requested research profile from a pinned policy."""
    selected = policy or PolicyStore(project_root).load_active()
    return compiled_overlay(selected, profile.removesuffix(".md"))


def failure_brief(project_root: Path) -> str:
    """Short OPEN-gap brief for decompose. Reads jsonl directly."""
    open_rows = [
        row
        for row in _load_ledger_rows(project_root)
        if str(row.get("status") or "") == "OPEN"
    ]
    if not open_rows:
        return ""
    lines = ["Prior-session OPEN gaps (not a second follow-up):"]
    for row in open_rows[:6]:
        lines.append(
            f"- {row.get('capability')}: {row.get('claim')} "
            f"(evidence_id={row.get('evidence_id')})"
        )
    return "\n".join(lines)
