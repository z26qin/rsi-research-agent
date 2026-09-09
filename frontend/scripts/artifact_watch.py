"""Local-only read-only artifact polling. Never imports or starts the research runtime."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from sync_artifacts import (
    IGNORED_TOP_LEVEL_DIRECTORIES, SESSION_FILES, LEGACY_FILES,
    _ensure_safe_snapshot_parent, _replace_index, sync_artifacts,
)


def default_project_root() -> Path:
    checkout = Path(__file__).resolve().parents[2]
    try:
        common = subprocess.check_output(
            ['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'],
            cwd=checkout, text=True, stderr=subprocess.DEVNULL, timeout=5,
        ).strip()
        return Path(common).parent
    except (OSError, subprocess.SubprocessError):
        return checkout


def source_signature(reports: Path, project: Path) -> str:
    """Stat only bounded, allowlisted paths; no recursive traversal or symlink reads."""
    rows = []

    def record(p: Path):
        s = p.lstat()
        rows.append((str(p), s.st_mode, s.st_size, s.st_mtime_ns, s.st_ino))

    if not reports.is_dir() or reports.is_symlink():
        raise ValueError('Reports root unavailable')
    # Directory mtime is excluded: changes in ignored trees must not trigger imports.
    for p in sorted(reports.iterdir()):
        if p.name in IGNORED_TOP_LEVEL_DIRECTORIES:
            continue
        if p.name == 'gap_ledger.jsonl':
            record(p)
        elif p.is_symlink():
            record(p)
        elif p.is_dir():
            for name in (*SESSION_FILES, *LEGACY_FILES, 'brief.json', 'factor_context.json'):
                f = p / name
                if os.path.lexists(f):
                    record(f)
            sub = p / 'sub_reports'
            if sub.is_symlink():
                record(sub)
            elif sub.is_dir():
                for f in sorted(sub.iterdir()):
                    if f.suffix in {'.json', '.md'}:
                        record(f)
    for directory in (project / 'profiles', project / 'src/momentum_research_agent/agents/profiles'):
        if directory.is_dir() and not directory.is_symlink():
            for p in sorted(directory.iterdir()):
                if p.suffix == '.md':
                    record(p)
    registry = project / 'src/momentum_research_agent/tools/__init__.py'
    if registry.exists():
        record(registry)
    return hashlib.sha256(repr(rows).encode()).hexdigest()


class ArtifactWatcher:
    def __init__(self, reports: Path, output: Path, project: Path):
        self.reports, self.output, self.project = reports.absolute(), output.absolute(), project.absolute()
        resolved = self.output.resolve()
        if self.output.is_symlink() or resolved == self.reports.resolve() or self.reports.resolve() in resolved.parents:
            raise ValueError('Snapshot output must be outside reports and not a symlink')
        self.output = resolved
        self.output.mkdir(parents=True, exist_ok=True)
        _ensure_safe_snapshot_parent(self.output)
        self.signature = None
        self.status = {'state': 'starting', 'message': 'Waiting for first snapshot', 'snapshotAt': None}

    def tick(self):
        try:
            signature = source_signature(self.reports, self.project)
            if signature != self.signature:
                # Stage the entire import, then expose index last. Malformed/partial
                # writes never replace the last coherent published snapshot.
                with tempfile.TemporaryDirectory(prefix='artifact-stage-', dir=self.output.parent) as temp:
                    stage = Path(temp)
                    manifest = sync_artifacts(self.reports, stage, self.project)
                    fatal = [d for d in manifest['diagnostics'] if d['code'] not in {
                        'reports_empty', 'profile_description_missing', 'traces_from_verification',
                    } and not d['code'].startswith('profile')]
                    if fatal or source_signature(self.reports, self.project) != signature:
                        raise ValueError('Source incomplete or changed; retaining the last snapshot')
                    destination = _ensure_safe_snapshot_parent(self.output) / manifest['snapshotId']
                    (stage / 'snapshots' / manifest['snapshotId']).rename(destination)
                    _replace_index(self.output, manifest)
                self.signature = signature
                self.status = {'state': 'ready', 'message': 'Read-only automatic sync',
                               'snapshotAt': manifest['snapshotAt']}
            else:
                self.status = {**self.status, 'state': 'ready', 'message': 'Read-only automatic sync'}
        except (OSError, ValueError, RuntimeError) as exc:
            self.status = {**self.status, 'state': 'stale',
                           'message': 'Import unavailable; retaining last snapshot (' + type(exc).__name__ + ')'}
        self.status = {**self.status, 'checkedAt': datetime.now(timezone.utc).isoformat()}
        temporary = self.output / '.sync-status.tmp'
        temporary.write_text(json.dumps(self.status))
        temporary.replace(self.output / 'sync-status.json')
        return self.status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path,
                        default=os.environ.get('MOMENTUM_ARTIFACT_PROJECT_ROOT') or default_project_root())
    parser.add_argument('--reports-root', type=Path, default=os.environ.get('MOMENTUM_REPORTS_ROOT'))
    parser.add_argument('--output-root', type=Path,
                        default=Path(__file__).resolve().parents[1] / '.generated/artifacts')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    watcher = ArtifactWatcher(args.reports_root or args.project_root / 'reports', args.output_root, args.project_root)
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        watcher.tick()
        if args.once:
            break
        time.sleep(3)


if __name__ == '__main__':
    main()
