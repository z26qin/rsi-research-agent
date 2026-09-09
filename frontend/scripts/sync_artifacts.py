#!/usr/bin/env python3
"""Publish a browser-safe, read-only snapshot of whitelisted report artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from artifact_io import (
    RejectedPathError,
    SourceChangedError,
    diagnostic,
    read_json_object,
    read_jsonl_objects,
    read_stable_bytes,
    read_text,
)
from profile_catalog import load_profile_catalog


IGNORED_TOP_LEVEL_DIRECTORIES = {
    "eval_cases",
    "live_evals",
    "policies",
}
SESSION_FILES = ("task_board.json", "verification.json", "synthesis.json", "traces.jsonl")
LEGACY_FILES = ("verification.md", "synthesis.md")
SNAPSHOT_ID_PATTERN = re.compile(r"[0-9a-f]{32}")
OBJECT_NAME_PATTERN = re.compile(r"[0-9a-f]{24}\.json")


def _exists(path: Path) -> bool:
    return os.path.lexists(path)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _read_optional_json(path: Path, root: Path) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    if not _exists(path):
        return None, []
    return read_json_object(path, root)


def _legacy_item(path: Path, session_root: Path, reports_root: Path) -> tuple[dict[str, str] | None, list]:
    text, diagnostics = read_text(path, reports_root)
    if text is None:
        return None, diagnostics
    return {"file": path.relative_to(session_root).as_posix(), "text": text}, diagnostics


def _scan_session(session_root: Path, reports_root: Path, snapshot_at: str) -> dict[str, Any]:
    diagnostics: list[dict[str, str]] = []
    board, item_diagnostics = _read_optional_json(session_root / "task_board.json", reports_root)
    diagnostics.extend(item_diagnostics)
    verification, item_diagnostics = _read_optional_json(session_root / "verification.json", reports_root)
    diagnostics.extend(item_diagnostics)
    synthesis, item_diagnostics = _read_optional_json(session_root / "synthesis.json", reports_root)
    diagnostics.extend(item_diagnostics)

    traces: list[dict[str, Any]] = []
    traces_path = session_root / "traces.jsonl"
    if _exists(traces_path):
        traces, item_diagnostics = read_jsonl_objects(traces_path, reports_root)
        diagnostics.extend(item_diagnostics)
    elif verification is not None and isinstance(verification.get("traces"), list):
        for index, trace in enumerate(verification["traces"]):
            if isinstance(trace, dict):
                traces.append(trace)
            else:
                diagnostics.append(
                    diagnostic(
                        session_root / "verification.json",
                        reports_root,
                        "invalid_verification_trace",
                        f"verification.traces[{index}] is not an object",
                    )
                )
        diagnostics.append(
            diagnostic(
                session_root / "verification.json",
                reports_root,
                "traces_from_verification",
                "Canonical traces.jsonl is missing; using verification.json traces",
            )
        )
    seen_traces: dict[str, dict[str, Any]] = {}
    for trace in traces:
        trace_id = trace.get("id")
        if not isinstance(trace_id, str):
            continue
        prior = seen_traces.get(trace_id)
        if prior is not None and prior != trace:
            diagnostics.append(
                diagnostic(
                    traces_path if _exists(traces_path) else session_root / "verification.json",
                    reports_root,
                    "conflicting_trace_id",
                    f"Trace ID {trace_id!r} occurs with different content",
                )
            )
        else:
            seen_traces[trace_id] = trace

    reports: list[dict[str, Any]] = []
    legacy: list[dict[str, str]] = []
    sub_reports = session_root / "sub_reports"
    if _exists(sub_reports):
        if sub_reports.is_symlink():
            diagnostics.append(
                diagnostic(sub_reports, reports_root, "symlink_rejected", "Symbolic links are not imported")
            )
        elif sub_reports.is_dir():
            json_names: set[str] = set()
            for candidate in sorted(sub_reports.iterdir(), key=lambda item: item.name):
                if candidate.name.startswith(".") or candidate.suffix != ".json":
                    continue
                json_names.add(candidate.stem)
                report, item_diagnostics = read_json_object(candidate, reports_root)
                diagnostics.extend(item_diagnostics)
                if report is not None:
                    reports.append(report)
            for candidate in sorted(sub_reports.iterdir(), key=lambda item: item.name):
                if (
                    candidate.name.startswith(".")
                    or candidate.suffix != ".md"
                    or candidate.stem in json_names
                ):
                    continue
                item, item_diagnostics = _legacy_item(candidate, session_root, reports_root)
                diagnostics.extend(item_diagnostics)
                if item is not None:
                    legacy.append(item)

    for filename in LEGACY_FILES:
        markdown_path = session_root / filename
        json_path = session_root / f"{markdown_path.stem}.json"
        if not _exists(markdown_path) or _exists(json_path):
            continue
        item, item_diagnostics = _legacy_item(markdown_path, session_root, reports_root)
        diagnostics.extend(item_diagnostics)
        if item is not None:
            legacy.append(item)

    return {
        "id": session_root.name,
        "board": board,
        "reports": reports,
        "verification": verification,
        "synthesis": synthesis,
        "traces": traces,
        "legacy": legacy,
        "diagnostics": diagnostics,
        "snapshotAt": snapshot_at,
    }


def _scan_brief(brief_root: Path, reports_root: Path, snapshot_at: str) -> dict[str, Any]:
    brief, diagnostics = read_json_object(brief_root / "brief.json", reports_root)
    if brief and brief.get('schema_version') == 'etf_proxy_brief_v1' and _exists(brief_root / 'factor_context.json'):
        context, errors = read_json_object(brief_root / 'factor_context.json', reports_root)
        diagnostics.extend(errors)
        if context:
            brief['factor_context'] = context
    return {
        "id": brief_root.name,
        "brief": brief,
        "diagnostics": diagnostics,
        "snapshotAt": snapshot_at,
    }


def _is_session_directory(path: Path) -> bool:
    return any(_exists(path / filename) for filename in SESSION_FILES + LEGACY_FILES) or _exists(
        path / "sub_reports"
    )


def _safe_directories(reports_root: Path) -> tuple[list[Path], list[dict[str, str]]]:
    directories: list[Path] = []
    diagnostics: list[dict[str, str]] = []
    for entry in sorted(os.scandir(reports_root), key=lambda item: item.name):
        path = Path(entry.path)
        if entry.name.startswith(".") or entry.name in IGNORED_TOP_LEVEL_DIRECTORIES:
            continue
        if entry.is_symlink():
            diagnostics.append(
                diagnostic(path, reports_root, "symlink_rejected", "Symbolic links are not imported")
            )
            continue
        if entry.is_dir(follow_symlinks=False):
            directories.append(path)
    return directories, diagnostics


def _valid_snapshot_reference(path: Any, snapshot_id: str, output_root: Path) -> bool:
    if not isinstance(path, str):
        return False
    parts = path.split("/")
    if (
        len(parts) != 3
        or parts[0] != "snapshots"
        or parts[1] != snapshot_id
        or OBJECT_NAME_PATTERN.fullmatch(parts[2]) is None
    ):
        return False
    candidate = output_root.joinpath(*parts)
    try:
        resolved_candidate = candidate.resolve(strict=True)
    except (FileNotFoundError, RuntimeError):
        return False
    return (
        output_root == resolved_candidate.parent.parent.parent
        and candidate.is_file()
        and not candidate.is_symlink()
    )


def _valid_previous_manifest(previous: Any, output_root: Path) -> bool:
    if not isinstance(previous, dict):
        return False
    snapshot_id = previous.get("snapshotId")
    if not isinstance(snapshot_id, str) or SNAPSHOT_ID_PATTERN.fullmatch(snapshot_id) is None:
        return False
    if previous.get("schemaVersion") != 1 or previous.get("availability") not in {
        "complete",
        "partial",
        "unavailable",
    }:
        return False
    if not isinstance(previous.get("snapshotAt"), str):
        return False
    for field in ("sessions", "briefs", "gaps", "profiles", "diagnostics"):
        if not isinstance(previous.get(field), list):
            return False
    snapshot_root = output_root / "snapshots" / snapshot_id
    try:
        if (
            snapshot_root.is_symlink()
            or not snapshot_root.is_dir()
            or snapshot_root.resolve(strict=True) != snapshot_root
        ):
            return False
    except (FileNotFoundError, RuntimeError):
        return False
    for collection in ("sessions", "briefs"):
        for entry in previous[collection]:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("id"), str)
                or not _valid_snapshot_reference(entry.get("path"), snapshot_id, output_root)
            ):
                return False
    return True


def _load_previous_manifest(output_root: Path) -> dict[str, Any] | None:
    index_path = output_root / "index.json"
    try:
        previous = json.loads(read_stable_bytes(index_path, output_root).data.decode("utf-8"))
    except (
        FileNotFoundError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        RejectedPathError,
        SourceChangedError,
    ):
        return None
    return previous if _valid_previous_manifest(previous, output_root) else None


def _replace_index(output_root: Path, manifest: dict[str, Any]) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    temporary_index = output_root / f".index-{uuid.uuid4().hex}.tmp"
    temporary_index.write_bytes(_json_bytes(manifest))
    os.replace(temporary_index, output_root / "index.json")


def _ensure_safe_snapshot_parent(output_root: Path) -> Path:
    snapshots_root = output_root / "snapshots"
    if _exists(snapshots_root):
        if (
            snapshots_root.is_symlink()
            or not snapshots_root.is_dir()
            or snapshots_root.resolve(strict=True) != snapshots_root
        ):
            raise ValueError("output snapshots directory must not be a symlink or path escape")
    else:
        snapshots_root.mkdir(parents=True)
    return snapshots_root


def _publish(output_root: Path, manifest: dict[str, Any], objects: list[tuple[str, dict]]) -> None:
    snapshot_root = _ensure_safe_snapshot_parent(output_root) / manifest["snapshotId"]
    snapshot_root.mkdir(parents=True, exist_ok=False)
    for filename, payload in objects:
        (snapshot_root / filename).write_bytes(_json_bytes(payload))
    _replace_index(output_root, manifest)


def _object_filename(kind: str, identifier: str) -> str:
    return f"{hashlib.sha256(f'{kind}:{identifier}'.encode('utf-8')).hexdigest()[:24]}.json"


def _availability(has_artifacts: bool, diagnostics: list[dict[str, str]]) -> str:
    if not has_artifacts:
        return "unavailable"
    return "partial" if diagnostics else "complete"


def sync_artifacts(reports_root: Path, output_root: Path, project_root: Path) -> dict:
    """Read allowed artifacts, publish an immutable snapshot, and return its manifest."""

    reports_root = Path(reports_root).absolute()
    output_root = Path(output_root).absolute()
    project_root = Path(project_root).absolute()
    resolved_reports_root = reports_root.resolve(strict=False)
    resolved_output_root = output_root.resolve(strict=False)
    if resolved_output_root == resolved_reports_root or resolved_reports_root in resolved_output_root.parents:
        raise ValueError("output_root must be outside reports_root")
    output_root = resolved_output_root
    _ensure_safe_snapshot_parent(output_root)
    previous = _load_previous_manifest(output_root)
    snapshot_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    snapshot_id = uuid.uuid4().hex
    diagnostics: list[dict[str, str]] = []
    objects: list[tuple[str, dict]] = []
    session_entries: list[dict[str, str]] = []
    brief_entries: list[dict[str, str]] = []
    gaps: list[dict[str, Any]] = []

    try:
        profiles, profile_diagnostics = load_profile_catalog(project_root)
        diagnostics.extend(profile_diagnostics)

        if not reports_root.exists():
            diagnostics.append(
                diagnostic(reports_root, project_root, "reports_missing", "Configured reports root does not exist")
            )
        elif reports_root.is_symlink() or not reports_root.is_dir():
            diagnostics.append(
                diagnostic(
                    reports_root,
                    project_root,
                    "reports_root_rejected",
                    "Configured reports root must be a real directory, not a symlink",
                )
            )
        else:
            directories, directory_diagnostics = _safe_directories(reports_root)
            diagnostics.extend(directory_diagnostics)
            for directory in directories:
                if _exists(directory / "brief.json"):
                    payload = _scan_brief(directory, reports_root, snapshot_at)
                    filename = _object_filename("brief", directory.name)
                    objects.append((filename, payload))
                    brief_entries.append(
                        {
                            "id": directory.name,
                            "path": f"snapshots/{snapshot_id}/{filename}",
                        }
                    )
                    diagnostics.extend(payload["diagnostics"])
                elif _is_session_directory(directory):
                    payload = _scan_session(directory, reports_root, snapshot_at)
                    filename = _object_filename("session", directory.name)
                    objects.append((filename, payload))
                    session_entries.append(
                        {
                            "id": directory.name,
                            "path": f"snapshots/{snapshot_id}/{filename}",
                        }
                    )
                    diagnostics.extend(payload["diagnostics"])

            gap_path = reports_root / "gap_ledger.jsonl"
            if _exists(gap_path):
                gaps, gap_diagnostics = read_jsonl_objects(gap_path, reports_root)
                diagnostics.extend(gap_diagnostics)
            if not session_entries and not brief_entries and not gaps:
                diagnostics.append(
                    diagnostic(reports_root, project_root, "reports_empty", "No importable report artifacts found")
                )

        manifest = {
            "schemaVersion": 1,
            "snapshotId": snapshot_id,
            "snapshotAt": snapshot_at,
            "availability": _availability(bool(session_entries or brief_entries or gaps), diagnostics),
            "sessions": session_entries,
            "briefs": brief_entries,
            "gaps": gaps,
            "profiles": profiles,
            "diagnostics": diagnostics,
        }
        _publish(output_root, manifest, objects)
        return manifest
    except SourceChangedError as exc:
        stale_diagnostic = diagnostic(
            exc.path,
            reports_root if reports_root in exc.path.parents else project_root,
            "source_changed",
            "Source changed during import; the last published snapshot remains active",
        )
        if previous is not None:
            returned = dict(previous)
            returned["diagnostics"] = [*previous.get("diagnostics", []), stale_diagnostic]
            returned["availability"] = "partial"
            _replace_index(output_root, returned)
            return returned
        manifest = {
            "schemaVersion": 1,
            "snapshotId": snapshot_id,
            "snapshotAt": snapshot_at,
            "availability": "unavailable",
            "sessions": [],
            "briefs": [],
            "gaps": [],
            "profiles": [],
            "diagnostics": [stale_diagnostic],
        }
        _publish(output_root, manifest, [])
        return manifest


def _parser() -> argparse.ArgumentParser:
    repository_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=repository_root)
    parser.add_argument("--reports-root", type=Path, default=repository_root / "reports")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=repository_root / "frontend/.generated/artifacts",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    manifest = sync_artifacts(args.reports_root, args.output_root, args.project_root)
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
