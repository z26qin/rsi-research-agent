import json

import pytest

from momentum_research_agent.eval.research_world import (
    load_approved_worlds,
)


def test_manifest_rejects_runtime_tampering(tmp_path) -> None:
    fixture_dir = tmp_path / "research_worlds"
    fixture_dir.mkdir()
    packaged = load_approved_worlds()[0]
    (fixture_dir / "world.json").write_text(
        packaged.model_dump_json(), encoding="utf-8"
    )
    (fixture_dir / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "worlds": {"world.json": "0" * 64}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="hash"):
        load_approved_worlds(fixture_dir)
