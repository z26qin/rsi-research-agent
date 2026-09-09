from pathlib import Path
import sys
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from control_manager import ControlManager


def test_proxy_mode_collects_without_waiting_for_frozen_engine_panels(tmp_path):
    m = ControlManager(tmp_path / 'state', tmp_path / 'backend', brief_source='etf-proxy',
                       runner=lambda job: ('unavailable', 'Provider unavailable'))
    m.set_schedule(True, datetime.fromisoformat('2026-09-08T20:00:00-04:00'))
    m.tick(datetime.fromisoformat('2026-09-09T08:00:00-04:00'))
    m.wait_idle()
    job = m.snapshot()['jobs'][0]
    assert job['brief_source'] == 'etf-proxy'
    assert job['request']['as_of'] == '2026-09-08'
    argv = m._command(job)
    assert Path(argv[1]).name == 'proxy_control_worker.py'
    assert argv[2:] == [str(m.root), '2026-09-08', str(m.reports / job['artifact_id'])]
    m.tick(datetime.fromisoformat('2026-09-09T09:00:00-04:00'))
    assert len(m.snapshot()['jobs']) == 1


def test_proxy_artifact_is_not_completed_just_because_exit_code_is_zero(tmp_path):
    m = ControlManager(tmp_path / 'state', tmp_path / 'backend', brief_source='etf-proxy')
    folder = m.reports / 'brief_invalid'
    folder.mkdir(parents=True)
    (folder / 'brief.json').write_text('{"schema_version":"etf_proxy_brief_v1","status":"partial"}')
    job = {'artifact_id': folder.name, 'brief_source':'etf-proxy', 'request':{'kind':'brief','as_of':'2026-09-08'}}
    assert m._classify(job, 0)[0] == 'failed'


def test_source_choice_survives_restart_without_touching_research_destination(tmp_path):
    m = ControlManager(tmp_path / 'state', tmp_path / 'backend', brief_source='etf-proxy')
    restored = ControlManager(tmp_path / 'state', tmp_path / 'backend')
    assert restored.snapshot()['brief_source'] == 'etf-proxy'
    argv = restored._command({'artifact_id':'20260909_120000_12345678', 'request':{'kind':'research','mode':'team','agents':2,'question':'Risk?'}})
    assert argv[1:3] == ['-m', 'momentum_research_agent.cli']
    assert restored.root == m.root
