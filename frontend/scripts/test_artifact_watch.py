import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from artifact_watch import ArtifactWatcher, default_project_root


def test_publish_changes_only_and_keep_last_good_on_partial_write(tmp_path):
    reports = tmp_path / 'reports'
    session = reports / 'session'
    session.mkdir(parents=True)
    board = session / 'task_board.json'
    board.write_text('{"question":"First","tasks":[]}')
    output = tmp_path / 'output'
    watcher = ArtifactWatcher(reports, output, tmp_path)
    assert watcher.tick()['state'] == 'ready'
    first = json.loads((output / 'index.json').read_text())
    watcher.tick()
    assert json.loads((output / 'index.json').read_text())['snapshotId'] == first['snapshotId']
    board.write_text('{')
    assert watcher.tick()['state'] == 'stale'
    assert json.loads((output / 'index.json').read_text()) == first
    board.write_text('{"question":"Second","tasks":[]}')
    assert watcher.tick()['state'] == 'ready'
    new = json.loads((output / 'index.json').read_text())
    assert new['snapshotId'] != first['snapshotId']
    assert json.loads((output / new['sessions'][0]['path']).read_text())['board']['question'] == 'Second'
    assert board.read_text() == '{"question":"Second","tasks":[]}'


def test_ignored_changes_and_missing_root_do_not_replace_snapshot(tmp_path):
    reports = tmp_path / 'reports'
    reports.mkdir()
    watcher = ArtifactWatcher(reports, tmp_path / 'out', tmp_path)
    watcher.tick()
    initial = (tmp_path / 'out/index.json').read_bytes()
    (reports / 'policies').mkdir()
    (reports / 'policies/active.json').write_text('{"private":true}')
    watcher.tick()
    assert (tmp_path / 'out/index.json').read_bytes() == initial
    reports.rename(tmp_path / 'moved')
    assert watcher.tick()['state'] == 'stale'
    assert (tmp_path / 'out/index.json').read_bytes() == initial
    (tmp_path / 'moved').rename(reports)
    assert watcher.tick()['state'] == 'ready'


def test_tool_catalog_changes_trigger_reimport(tmp_path):
    reports = tmp_path / 'reports'
    reports.mkdir()
    tools = tmp_path / 'src/momentum_research_agent/tools'
    tools.mkdir(parents=True)
    registry = tools / '__init__.py'
    registry.write_text('PROFILE_TOOLS = {"flow_analyst": ["web_search"]}')
    output = tmp_path / 'out'
    watcher = ArtifactWatcher(reports, output, tmp_path)
    watcher.tick()
    registry.write_text('PROFILE_TOOLS = {"flow_analyst": ["web_search", "engine_query"]}')
    watcher.tick()
    manifest = json.loads((output / 'index.json').read_text())
    assert manifest['profiles'][0]['tools'] == ['web_search', 'engine_query']


def test_rejects_output_inside_reports_and_symlink(tmp_path):
    import pytest
    reports = tmp_path / 'reports'
    reports.mkdir()
    with pytest.raises(ValueError):
        ArtifactWatcher(reports, reports / 'out', tmp_path)
    alias = tmp_path / 'alias'
    alias.symlink_to(reports, target_is_directory=True)
    with pytest.raises(ValueError):
        ArtifactWatcher(reports, alias, tmp_path)


def test_default_root_resolves_main_checkout():
    root = default_project_root()
    assert (root / '.git').is_dir()


def test_legacy_verification_traces_are_imported_with_notice(tmp_path):
    reports = tmp_path / 'reports'
    (reports / 'legacy').mkdir(parents=True)
    (reports / 'legacy/verification.json').write_text('{"traces":[]}')
    output = tmp_path / 'out'
    watcher = ArtifactWatcher(reports, output, tmp_path)
    assert watcher.tick()['state'] == 'ready'
    manifest = json.loads((output / 'index.json').read_text())
    assert manifest['sessions'][0]['id'] == 'legacy'
    assert any(d['code'] == 'traces_from_verification' for d in manifest['diagnostics'])


def test_daemon_detects_new_brief_and_stops_on_signal(tmp_path):
    import subprocess
    import time
    reports, output = tmp_path / 'reports', tmp_path / 'out'
    reports.mkdir()
    process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('artifact_watch.py')),
                                '--project-root', str(tmp_path), '--reports-root', str(reports),
                                '--output-root', str(output)], stdout=subprocess.DEVNULL)
    def wait_for(predicate):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.1)
        raise AssertionError('Watcher did not publish in time')
    try:
        wait_for(lambda: (output / 'index.json').exists())
        (reports / 'brief_example').mkdir()
        (reports / 'brief_example/brief.json').write_text('{"status":"unavailable"}')
        wait_for(lambda: bool(json.loads((output / 'index.json').read_text())['briefs']))
        assert json.loads((output / 'index.json').read_text())['briefs'][0]['id'] == 'brief_example'
    finally:
        process.terminate()
        process.wait(timeout=5)
    assert process.returncode == 0
