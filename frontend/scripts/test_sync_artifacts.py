from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from sync_artifacts import main, sync_artifacts  # noqa: E402
from artifact_io import read_json_object  # noqa: E402


def _write_profile_catalog(project_root: Path) -> None:
    tools = project_root / "src/momentum_research_agent/tools/__init__.py"
    tools.parent.mkdir(parents=True, exist_ok=True)
    tools.write_text(
        "PROFILE_TOOLS: dict[str, list[str]] = {\n"
        '    "momentum_analyst": ["engine_query", "market_data"],\n'
        '    "verifier": ["engine_query"],\n'
        "}\n"
    )
    profiles = project_root / "src/momentum_research_agent/agents/profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    (profiles / "momentum_analyst.md").write_text(
        "You are a momentum factor analyst.\n\nYour expertise:\n- momentum\n"
    )
    (profiles / "verifier.md").write_text(
        "You are an independent research verifier.\n\nApproach:\n- verify\n"
    )


def _sync(tmp_path: Path, source: Path | None = None) -> tuple[dict, Path]:
    project = tmp_path / "project"
    _write_profile_catalog(project)
    reports = source or project / "reports"
    output = tmp_path / "generated"
    return sync_artifacts(reports, output, project), output


def _read_object(output: Path, manifest: dict, collection: str, index: int = 0) -> dict:
    relative = manifest[collection][index]["path"]
    assert relative.startswith(f'snapshots/{manifest["snapshotId"]}/')
    return json.loads((output / relative).read_text())


def test_sync_publishes_exact_complete_contract_and_raw_session(tmp_path: Path) -> None:
    reports = tmp_path / "project/reports"
    session = reports / "20260908_120000_ab12cd34"
    sub_reports = session / "sub_reports"
    sub_reports.mkdir(parents=True)
    board = {"session_id": session.name, "question": "Risk?", "tasks": []}
    report = {"agent": "momentum_analyst", "findings": [{"evidence_id": "e-1"}]}
    verification = {"gaps": [], "verdicts": [{"evidence_id": "e-1", "status": "VERIFIED"}]}
    synthesis = {"summary": "Measured risk."}
    (session / "task_board.json").write_text(json.dumps(board))
    (sub_reports / "task-1_momentum_analyst.json").write_text(json.dumps(report))
    (session / "verification.json").write_text(json.dumps(verification))
    (session / "synthesis.json").write_text(json.dumps(synthesis))
    (session / "traces.jsonl").write_text('{"id":"t-1","tool":"engine_query"}\n')
    (reports / "gap_ledger.jsonl").write_text('{"evidence_id":"g-1","status":"OPEN"}\n')

    manifest, output = _sync(tmp_path, reports)

    assert set(manifest) == {
        "schemaVersion",
        "snapshotId",
        "snapshotAt",
        "availability",
        "sessions",
        "briefs",
        "gaps",
        "profiles",
        "diagnostics",
    }
    assert manifest["schemaVersion"] == 1
    assert manifest["availability"] == "complete"
    assert manifest["sessions"][0]["id"] == session.name
    assert manifest["gaps"] == [{"evidence_id": "g-1", "status": "OPEN"}]
    assert manifest["profiles"] == [
        {
            "name": "momentum_analyst",
            "displayName": "Momentum Analyst",
            "description": "You are a momentum factor analyst.",
            "tools": ["engine_query", "market_data"],
            "kind": "research",
        },
        {
            "name": "verifier",
            "displayName": "Verifier",
            "description": "You are an independent research verifier.",
            "tools": ["engine_query"],
            "kind": "verification",
        },
    ]
    payload = _read_object(output, manifest, "sessions")
    assert set(payload) == {
        "id",
        "board",
        "reports",
        "verification",
        "synthesis",
        "traces",
        "legacy",
        "diagnostics",
        "snapshotAt",
    }
    assert payload["board"] == board
    assert payload["reports"] == [report]
    assert payload["verification"] == verification
    assert payload["synthesis"] == synthesis
    assert payload["traces"] == [{"id": "t-1", "tool": "engine_query"}]
    assert payload["legacy"] == []
    assert json.loads((output / "index.json").read_text()) == manifest


def test_brief_only_directory_is_indexed_as_brief_not_session(tmp_path: Path) -> None:
    reports = tmp_path / "project/reports"
    brief_dir = reports / "brief_20260908_120000_ab12cd34"
    brief_dir.mkdir(parents=True)
    brief = {"schema_version": "daily_brief_v1", "requested_as_of": "2026-09-08"}
    (brief_dir / "brief.json").write_text(json.dumps(brief))

    manifest, output = _sync(tmp_path, reports)

    assert manifest["sessions"] == []
    assert manifest["briefs"][0]["id"] == brief_dir.name
    assert _read_object(output, manifest, "briefs") == {
        "id": brief_dir.name,
        "brief": brief,
        "diagnostics": [],
        "snapshotAt": manifest["snapshotAt"],
    }


def test_proxy_factor_context_is_imported_without_rewriting_original(tmp_path):
    reports = tmp_path / 'project/reports'
    folder = reports / 'brief_proxy'
    folder.mkdir(parents=True)
    original = '{"schema_version":"etf_proxy_brief_v1"}'
    (folder / 'brief.json').write_text(original)
    context = {'model_status':'unavailable','inputs':{'french':{'as_of':'2026-07-31'}}}
    (folder / 'factor_context.json').write_text(json.dumps(context))
    manifest, output = _sync(tmp_path, reports)
    assert _read_object(output, manifest, 'briefs')['brief']['factor_context'] == context
    assert (folder / 'brief.json').read_text() == original


def test_missing_reports_publishes_explicit_unavailable_manifest(tmp_path: Path) -> None:
    missing = tmp_path / "project/reports"

    manifest, output = _sync(tmp_path, missing)

    assert manifest["availability"] == "unavailable"
    assert manifest["sessions"] == []
    assert manifest["briefs"] == []
    assert manifest["gaps"] == []
    assert any(d["code"] == "reports_missing" for d in manifest["diagnostics"])
    assert json.loads((output / "index.json").read_text()) == manifest


def test_invalid_json_is_diagnosed_without_markdown_fallback(tmp_path: Path) -> None:
    reports = tmp_path / "project/reports"
    session = reports / "session-a"
    sub_reports = session / "sub_reports"
    sub_reports.mkdir(parents=True)
    (session / "task_board.json").write_text('{"session_id":')
    (sub_reports / "task-1.json").write_text("not-json")
    (sub_reports / "task-1.md").write_text("must not mask broken JSON")
    (sub_reports / "task-2.md").write_text("legacy-only report")

    manifest, output = _sync(tmp_path, reports)

    payload = _read_object(output, manifest, "sessions")
    assert manifest["availability"] == "partial"
    assert payload["board"] is None
    assert payload["reports"] == []
    assert payload["legacy"] == [{"file": "sub_reports/task-2.md", "text": "legacy-only report"}]
    assert {d["code"] for d in payload["diagnostics"]} == {"invalid_json"}
    assert not any(item["file"] == "sub_reports/task-1.md" for item in payload["legacy"])


def test_malformed_jsonl_keeps_valid_rows_and_marks_partial(tmp_path: Path) -> None:
    reports = tmp_path / "project/reports"
    session = reports / "session-a"
    session.mkdir(parents=True)
    (session / "task_board.json").write_text('{"session_id":"session-a"}')
    (session / "traces.jsonl").write_text(
        '{"id":"t-1"}\nnot-json\n["not", "an", "object"]\n{"id":"t-2"}\n'
    )
    (reports / "gap_ledger.jsonl").write_text('{"evidence_id":"g-1"}\nbroken\n')

    manifest, output = _sync(tmp_path, reports)

    payload = _read_object(output, manifest, "sessions")
    assert payload["traces"] == [{"id": "t-1"}, {"id": "t-2"}]
    assert manifest["gaps"] == [{"evidence_id": "g-1"}]
    assert manifest["availability"] == "partial"
    assert [d["code"] for d in payload["diagnostics"]] == [
        "invalid_jsonl_line",
        "invalid_jsonl_object",
    ]
    assert any(d["code"] == "invalid_jsonl_line" for d in manifest["diagnostics"])


def test_verification_traces_are_used_only_when_canonical_trace_file_is_missing(
    tmp_path: Path,
) -> None:
    reports = tmp_path / "project/reports"
    session = reports / "session-a"
    session.mkdir(parents=True)
    (session / "task_board.json").write_text('{"session_id":"session-a"}')
    fallback_trace = {"id": "fallback-1", "tool": "web_search"}
    (session / "verification.json").write_text(json.dumps({"traces": [fallback_trace]}))

    manifest, output = _sync(tmp_path, reports)

    payload = _read_object(output, manifest, "sessions")
    assert payload["traces"] == [fallback_trace]
    assert any(d["code"] == "traces_from_verification" for d in payload["diagnostics"])

    (session / "traces.jsonl").write_text("broken\n")
    manifest, output = _sync(tmp_path, reports)
    payload = _read_object(output, manifest, "sessions")
    assert payload["traces"] == []
    assert not any(d["code"] == "traces_from_verification" for d in payload["diagnostics"])


def test_conflicting_duplicate_trace_ids_are_diagnosed_without_rewriting_rows(tmp_path: Path) -> None:
    reports = tmp_path / "project/reports"
    session = reports / "session-a"
    session.mkdir(parents=True)
    (session / "task_board.json").write_text('{"session_id":"session-a"}')
    rows = [
        {"id": "t-1", "tool": "web_search", "observation": "first"},
        {"id": "t-1", "tool": "web_search", "observation": "changed"},
    ]
    (session / "traces.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))

    manifest, output = _sync(tmp_path, reports)

    payload = _read_object(output, manifest, "sessions")
    assert payload["traces"] == rows
    assert any(d["code"] == "conflicting_trace_id" for d in payload["diagnostics"])


def test_symlinks_and_unknown_trees_are_not_followed(tmp_path: Path) -> None:
    reports = tmp_path / "project/reports"
    session = reports / "session-a"
    session.mkdir(parents=True)
    outside = tmp_path / "secret.json"
    outside.write_text('{"secret":"do-not-copy"}')
    (session / "task_board.json").symlink_to(outside)
    (session / "engine_runs").symlink_to(tmp_path, target_is_directory=True)
    hidden = reports / ".private"
    hidden.mkdir(parents=True)
    (hidden / "task_board.json").write_text(outside.read_text())
    policy = reports / "policies/version"
    policy.mkdir(parents=True)
    (policy / "task_board.json").write_text(outside.read_text())

    manifest, output = _sync(tmp_path, reports)

    assert manifest["availability"] == "partial"
    assert manifest["sessions"][0]["id"] == "session-a"
    payload = _read_object(output, manifest, "sessions")
    assert payload["board"] is None
    assert any(d["code"] == "symlink_rejected" for d in payload["diagnostics"])
    generated = "\n".join(p.read_text() for p in output.rglob("*.json"))
    assert "do-not-copy" not in generated
    assert not any(item["id"] in {".private", "policies"} for item in manifest["sessions"])


def test_artifact_reader_rejects_direct_outside_root_path(tmp_path: Path) -> None:
    allowed_root = tmp_path / "reports"
    allowed_root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text('{"secret":true}')

    value, diagnostics = read_json_object(outside, allowed_root)

    assert value is None
    assert diagnostics == [
        {
            "file": "outside.json",
            "code": "outside_root",
            "message": "Path is outside the configured root",
        }
    ]


def test_profile_catalog_fails_closed_when_literal_is_missing(tmp_path: Path) -> None:
    project = tmp_path / "project"
    tools = project / "src/momentum_research_agent/tools/__init__.py"
    tools.parent.mkdir(parents=True)
    tools.write_text("DEFAULT_TOOLS = ['shell']\n")
    reports = project / "reports"
    session = reports / "session-a"
    session.mkdir(parents=True)
    (session / "task_board.json").write_text('{"session_id":"session-a"}')

    manifest = sync_artifacts(reports, tmp_path / "generated", project)

    assert manifest["profiles"] == []
    assert manifest["availability"] == "partial"
    assert any(d["code"] == "profile_tools_missing" for d in manifest["diagnostics"])


def test_profile_catalog_rejects_invalid_literal_entries_without_importing_defaults(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    tools = project / "src/momentum_research_agent/tools/__init__.py"
    tools.parent.mkdir(parents=True)
    tools.write_text("PROFILE_TOOLS = {'momentum_analyst': ['market_data'], 7: ['shell']}\n")
    reports = project / "reports/session-a"
    reports.mkdir(parents=True)
    (reports / "task_board.json").write_text('{"session_id":"session-a"}')

    manifest = sync_artifacts(project / "reports", tmp_path / "generated", project)

    assert manifest["profiles"] == []
    assert any(d["code"] == "profile_tools_invalid" for d in manifest["diagnostics"])


def test_concurrent_source_change_preserves_last_published_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports = tmp_path / "project/reports"
    session = reports / "session-a"
    session.mkdir(parents=True)
    board = session / "task_board.json"
    board.write_text('{"session_id":"session-a","question":"first"}')
    first, output = _sync(tmp_path, reports)
    session_path = output / first["sessions"][0]["path"]
    session_before = session_path.read_bytes()

    import sync_artifacts as sync_module

    original_reader = sync_module.read_json_object

    def unstable_reader(path: Path, root: Path):
        if path == board:
            raise sync_module.SourceChangedError(path)
        return original_reader(path, root)

    monkeypatch.setattr(sync_module, "read_json_object", unstable_reader)
    returned = sync_module.sync_artifacts(reports, output, tmp_path / "project")

    assert returned["snapshotId"] == first["snapshotId"]
    assert any(d["code"] == "source_changed" for d in returned["diagnostics"])
    assert returned["availability"] == "partial"
    assert json.loads((output / "index.json").read_text()) == returned
    assert session_path.read_bytes() == session_before


def test_sync_never_changes_source(tmp_path: Path) -> None:
    source = tmp_path / "reports"
    session = source / "session-a"
    session.mkdir(parents=True)
    board = session / "task_board.json"
    original = b'{"session_id":"session-a","question":"Risk?","tasks":[]}'
    board.write_bytes(original)
    project = tmp_path / "project"
    _write_profile_catalog(project)

    sync_artifacts(source, tmp_path / "generated", project)

    assert board.read_bytes() == original
    assert sorted(p.relative_to(source).as_posix() for p in source.rglob("*") if p.is_file()) == [
        "session-a/task_board.json"
    ]


def test_output_root_inside_reports_is_rejected_without_writing(tmp_path: Path) -> None:
    source = tmp_path / "reports"
    session = source / "session-a"
    session.mkdir(parents=True)
    board = session / "task_board.json"
    original = b'{"session_id":"session-a"}'
    board.write_bytes(original)
    project = tmp_path / "project"
    _write_profile_catalog(project)

    with pytest.raises(ValueError, match="outside reports_root"):
        sync_artifacts(source, source / ".generated", project)

    assert board.read_bytes() == original
    assert not (source / ".generated").exists()


def test_output_symlink_resolving_inside_reports_is_rejected_without_writing(tmp_path: Path) -> None:
    source = tmp_path / "reports"
    session = source / "session-a"
    session.mkdir(parents=True)
    board = session / "task_board.json"
    original = b'{"session_id":"session-a"}'
    board.write_bytes(original)
    output_target = source / "generated-target"
    output_target.mkdir()
    output_link = tmp_path / "generated-link"
    output_link.symlink_to(output_target, target_is_directory=True)
    project = tmp_path / "project"
    _write_profile_catalog(project)

    with pytest.raises(ValueError, match="outside reports_root"):
        sync_artifacts(source, output_link, project)

    assert board.read_bytes() == original
    assert list(output_target.iterdir()) == []


def test_snapshot_parent_symlink_cannot_redirect_writes_into_reports(tmp_path: Path) -> None:
    source = tmp_path / "reports"
    session = source / "session-a"
    session.mkdir(parents=True)
    board = session / "task_board.json"
    original = b'{"session_id":"session-a"}'
    board.write_bytes(original)
    redirected = source / "redirected-output"
    redirected.mkdir()
    output = tmp_path / "generated"
    output.mkdir()
    (output / "snapshots").symlink_to(redirected, target_is_directory=True)
    project = tmp_path / "project"
    _write_profile_catalog(project)

    with pytest.raises(ValueError, match="snapshots directory"):
        sync_artifacts(source, output, project)

    assert board.read_bytes() == original
    assert list(redirected.iterdir()) == []


def test_unsafe_previous_manifest_is_not_reused_on_concurrent_source_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports = tmp_path / "project/reports"
    session = reports / "session-a"
    session.mkdir(parents=True)
    board = session / "task_board.json"
    board.write_text('{"session_id":"session-a"}')
    output = tmp_path / "generated"
    output.mkdir()
    (output / "snapshots" / ("a" * 32)).mkdir(parents=True)
    malicious = {
        "schemaVersion": 1,
        "snapshotId": "a" * 32,
        "snapshotAt": "2026-09-08T00:00:00Z",
        "availability": "complete",
        "sessions": [{"id": "escape", "path": "../../reports/session-a/task_board.json"}],
        "briefs": [],
        "gaps": [],
        "profiles": [],
        "diagnostics": [],
    }
    (output / "index.json").write_text(json.dumps(malicious))
    project = tmp_path / "project"
    _write_profile_catalog(project)

    import sync_artifacts as sync_module

    def unstable_reader(path: Path, root: Path):
        if path == board:
            raise sync_module.SourceChangedError(path)
        return read_json_object(path, root)

    monkeypatch.setattr(sync_module, "read_json_object", unstable_reader)
    returned = sync_module.sync_artifacts(reports, output, project)

    assert returned["snapshotId"] != malicious["snapshotId"]
    assert returned["sessions"] == []
    assert returned["availability"] == "unavailable"
    assert "../" not in (output / "index.json").read_text()


def test_cli_treats_unavailable_manifest_as_a_valid_demo_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "project"
    _write_profile_catalog(project)
    output = tmp_path / "generated"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sync_artifacts.py",
            "--project-root",
            str(project),
            "--reports-root",
            str(project / "missing-reports"),
            "--output-root",
            str(output),
        ],
    )

    assert main() == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["availability"] == "unavailable"
    assert (output / "index.json").is_file()
