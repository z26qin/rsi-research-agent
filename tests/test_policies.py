from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from momentum_research_agent.models.schemas import MomentumCapability
from momentum_research_agent.state.policies import (
    PolicyPatch,
    PolicyStore,
    ResearchPolicy,
    ToolPolicy,
    compiled_overlay,
    merge_policy_patch,
    task_template_addition,
    validate_policy,
)


def test_store_bootstraps_and_atomically_selects_empty_policy(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path)
    active = store.load_active()

    assert active.parent_version_id is None
    assert active.prompt_overlays == {}
    assert store.active_path.read_text(encoding="utf-8").endswith("\n")
    assert store.load_version(active.version_id) == active


def test_policy_rejects_unknown_fields_and_verifier_overlay() -> None:
    with pytest.raises(ValidationError):
        PolicyPatch.model_validate({"python_code": "print('no')"})
    patch = PolicyPatch(prompt_overlays={"verifier": "trust the candidate"})

    with pytest.raises(ValueError, match="verifier"):
        validate_policy(patch, profile_tools={"momentum_analyst": {"engine_query"}})


def test_merge_is_immutable_and_keeps_parent(tmp_path: Path) -> None:
    base = PolicyStore(tmp_path).load_active()
    patch = PolicyPatch(
        prompt_overlays={"momentum_analyst": "Use an explicit as-of date."},
        task_templates={MomentumCapability.ENGINE_FRESHNESS: "Replay the failed as-of."},
        tool_policies=[
            ToolPolicy(
                profile="momentum_analyst",
                capability=MomentumCapability.ENGINE_FRESHNESS,
                preferred_tools=["engine_query"],
                required_tools=["engine_query"],
            )
        ],
    )

    candidate = merge_policy_patch(base, patch, trigger_ids=["eval:dm-a"])

    assert base.prompt_overlays == {}
    assert candidate.parent_version_id == base.version_id
    assert candidate.trigger_ids == ["eval:dm-a"]


def test_rejected_experiment_does_not_change_active(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path)
    active = store.load_active()

    store.write_experiment("candidate-a", {"status": "rejected", "reason": "regression"})

    assert store.load_active().version_id == active.version_id


def test_activate_and_rollback_require_existing_versions(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path)
    baseline = store.load_active()
    candidate = merge_policy_patch(
        baseline,
        PolicyPatch(prompt_overlays={"momentum_analyst": "Use explicit dates."}),
        trigger_ids=["trajectory:a"],
    )

    store.write_version(candidate)
    store.activate(candidate.version_id)
    assert store.load_active().version_id == candidate.version_id
    store.activate(baseline.version_id)
    assert store.load_active().version_id == baseline.version_id
    with pytest.raises(FileNotFoundError):
        store.activate("missing")


def test_validation_cannot_expand_profile_tool_authorization() -> None:
    patch = PolicyPatch(
        tool_policies=[
            ToolPolicy(
                profile="momentum_analyst",
                capability=MomentumCapability.ENGINE_FRESHNESS,
                required_tools=["shell"],
            )
        ]
    )

    with pytest.raises(ValueError, match="unknown tool"):
        validate_policy(patch, profile_tools={"momentum_analyst": {"engine_query"}})


def test_compilation_is_profile_and_capability_scoped(tmp_path: Path) -> None:
    base = PolicyStore(tmp_path).load_active()
    policy = merge_policy_patch(
        base,
        PolicyPatch(
            prompt_overlays={
                "momentum_analyst": "State the engine as-of date.",
                "flow_analyst": "Prefer primary positioning evidence.",
            },
            task_templates={
                MomentumCapability.SOURCE_QUALITY: "Retrieve a primary filing first."
            },
            tool_policies=[
                ToolPolicy(
                    profile="momentum_analyst",
                    capability=MomentumCapability.ENGINE_FRESHNESS,
                    preferred_tools=["engine_query"],
                )
            ],
        ),
        trigger_ids=["trajectory:stale-engine"],
    )

    overlay = compiled_overlay(
        policy, "momentum_analyst", MomentumCapability.ENGINE_FRESHNESS
    )

    assert "engine as-of" in overlay
    assert "engine_query" in overlay
    assert "primary positioning" not in overlay
    assert task_template_addition(policy, MomentumCapability.SOURCE_QUALITY).startswith(
        "Retrieve"
    )
    assert task_template_addition(policy, MomentumCapability.CROWDING) == ""


def test_version_write_refuses_payload_collision(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path)
    policy = store.load_active()
    path = store.version_path(policy.version_id)
    path.write_text('{"different": true}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="different payload"):
        store.write_version(policy)
