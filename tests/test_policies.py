from __future__ import annotations

from pathlib import Path

import pytest

from momentum_research_agent.state.policies import (
    PolicyPatch,
    PolicyStore,
    merge_policy_patch,
)


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
