import sys
import json
from datetime import datetime
from pathlib import Path
from threading import Event

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from control_calendar import latest_completed, next_morning
from control_manager import ControlManager, validate_request


def test_failed_research_surfaces_typed_cause_not_sensitive_exception(tmp_path):
    m = manager(tmp_path)
    folder = m.reports / 'failed_case'
    folder.mkdir(parents=True)
    (folder/'task_board.json').write_text(json.dumps({'tasks':[{'status':'BLOCKED', 'error_type':'AgentDeadlineExceeded', 'error':'secret-provider-body'}]}))
    state, message = m._classify({'artifact_id':'failed_case','request':{'kind':'research'}},1)
    assert state == 'failed' and 'deadline' in message.lower()
    assert 'secret-provider-body' not in message


def test_auto_lookup_dispatches_single_and_completion_is_not_answer(tmp_path):
    m = manager(tmp_path)
    raw = {**request(), 'mode':'auto', 'question':'MTUM top 10 holdings'}
    validated = validate_request(raw, at('2026-09-09T08:00:00-04:00'))
    command = m._command({'artifact_id':'new_session','request':validated})
    assert command[command.index('--mode')+1] == 'single'
    assert command[command.index('--max-sub-agents')+1] == '1'
    folder=m.reports/'new_session';folder.mkdir(parents=True)
    (folder/'task_board.json').write_text(json.dumps({'tasks':[]}))
    assert m._research_outcome('new_session') == 'unanswered'


def at(value):
    return datetime.fromisoformat(value)


def test_coverage_accounts_for_missing_or_blocked_team_dimensions(tmp_path):
    m=manager(tmp_path)
    folder=m.reports/'coverage_case';sub=folder/'sub_reports';sub.mkdir(parents=True)
    (sub/'a.json').write_text(json.dumps({'task_id':'a','title':'Context','agent_role':'momentum_analyst','summary':'Context',
        'findings':[{'claim':'Context','category':'other','stance':'neutral'}],'status':'complete'}))
    board=folder/'task_board.json'
    board.write_text(json.dumps({'tasks':[{'id':'a','status':'COMPLETED'},{'id':'b','status':'BLOCKED'}]}))
    assert m._research_outcome('coverage_case') == 'partial'
    board.write_text(json.dumps({'tasks':[{'id':'a','status':'COMPLETED'}]}))
    assert m._research_outcome('coverage_case') == 'answer_available'


@pytest.mark.parametrize('now, expected', [
    ('2026-09-08T08:00:00-04:00', '2026-09-04'),
    ('2026-09-09T08:00:00-04:00', '2026-09-08'),
    ('2026-07-06T08:00:00-04:00', '2026-07-02'),
    ('2026-11-27T08:00:00-05:00', '2026-11-25'),
    ('2026-11-27T14:00:00-05:00', '2026-11-27'),
])
def test_completed_session_calendar(now, expected):
    assert latest_completed(at(now)).isoformat() == expected


def test_dst_and_calendar_expiry():
    assert next_morning(at('2026-03-07T15:00:00-05:00')).isoformat() == '2026-03-08T08:00:00-04:00'
    with pytest.raises(ValueError):
        latest_completed(at('2029-01-08T08:00:00-05:00'))


def request(key='request-12345678', **kwargs):
    return dict(kind='research', question='Explain momentum risk', mode='team', agents=2,
                confirmed=True, request_id=key, **kwargs)


@pytest.mark.parametrize('change', [
    {'kind': 'shell'}, {'confirmed': False}, {'question': ' '}, {'agents': 0},
    {'agents': True}, {'agents': 5}, {'mode': 'arbitrary'}, {'output': '/tmp/other'},
])
def test_rejects_unapproved_inputs(change):
    with pytest.raises(ValueError):
        validate_request({**request(), **change}, at('2026-09-09T08:00:00-04:00'))


def manager(tmp_path, runner=None, readiness=None):
    return ControlManager(tmp_path / 'state', tmp_path / 'backend',
                          runner=runner or (lambda job: ('completed', 'Test artifact available')),
                          readiness=readiness or (lambda day: (True, 'Ready')))


def test_idempotency_serialization_and_recovery(tmp_path):
    release = Event()
    m = manager(tmp_path, runner=lambda job: (release.wait(2) and 'completed', 'Done'))
    now = at('2026-09-09T08:00:00-04:00')
    first = m.submit(request(), now)
    assert m.submit(request(), now)['id'] == first['id']
    with pytest.raises(ValueError):
        m.submit({**request(), 'question': 'different'}, now)
    with pytest.raises(ValueError):
        m.submit(request('request-abcdefgh'), now)
    release.set()
    m.wait_idle(3)
    assert m.snapshot(now)['jobs'][0]['state'] == 'completed'
    restored = manager(tmp_path)
    assert restored.submit(request(), now)['id'] == first['id']


def test_schedule_waits_for_inputs_runs_once_and_never_replays(tmp_path):
    ready = [False]
    m = manager(tmp_path, readiness=lambda day: (ready[0], 'Input coverage missing'))
    m.set_schedule(True, at('2026-09-08T20:00:00-04:00'))
    m.tick(at('2026-09-09T07:59:00-04:00'))
    assert not m.snapshot(at('2026-09-09T07:59:00-04:00'))['jobs']
    m.tick(at('2026-09-09T08:00:00-04:00'))
    assert m.snapshot(at('2026-09-09T08:00:00-04:00'))['schedule']['state'] == 'waiting_inputs'
    ready[0] = True
    m.tick(at('2026-09-09T08:15:00-04:00'))
    m.wait_idle(3)
    m.tick(at('2026-09-09T08:30:00-04:00'))
    restored = manager(tmp_path)
    restored.tick(at('2026-09-09T09:00:00-04:00'))
    jobs = restored.snapshot(at('2026-09-09T09:00:00-04:00'))['jobs']
    assert len(jobs) == 1
    assert jobs[0]['request']['as_of'] == '2026-09-08'
    assert jobs[0]['request']['kind'] == 'brief'


def test_schedule_has_bounded_wait_and_no_afternoon_catchup(tmp_path):
    m = manager(tmp_path, readiness=lambda day: (False, 'Missing inputs'))
    m.set_schedule(True, at('2026-09-08T20:00:00-04:00'))
    for hour in (8, 9, 10):
        for minute in (0, 15, 30, 45):
            m.tick(at(f'2026-09-09T{hour:02}:{minute:02}:00-04:00'))
    result = m.snapshot(at('2026-09-09T12:00:00-04:00'))
    assert not result['jobs']
    assert result['schedule']['checks'] <= 9
    assert result['schedule']['state'] in ('expired', 'missed')
    m.tick(at('2026-09-10T15:00:00-04:00'))
    assert not m.snapshot(at('2026-09-10T15:00:00-04:00'))['jobs']


def test_invalid_persisted_schedule_fails_closed(tmp_path):
    import json
    m = manager(tmp_path)
    m.data['schedule']['enabled'] = 'yes'
    m.path.write_text(json.dumps(m.data))
    with pytest.raises(ValueError):
        manager(tmp_path)


def test_disable_then_reenable_during_readiness_does_not_launch_old_check(tmp_path):
    entered, release = Event(), Event()
    def readiness(day):
        entered.set()
        release.wait(3)
        return True, 'Ready'
    m = manager(tmp_path, readiness=readiness)
    m.set_schedule(True, at('2026-09-08T20:00:00-04:00'))
    import threading
    t = threading.Thread(target=m.tick, args=(at('2026-09-09T08:00:00-04:00'),))
    t.start()
    assert entered.wait(2)
    m.set_schedule(False, at('2026-09-09T08:00:01-04:00'))
    m.set_schedule(True, at('2026-09-09T08:00:02-04:00'))
    release.set()
    t.join(3)
    m.wait_idle(3)
    assert not m.snapshot(at('2026-09-09T08:00:03-04:00'))['jobs']


def test_fixed_cli_arguments_preserve_question_as_data(tmp_path):
    m = manager(tmp_path)
    job = {'artifact_id': '20260909_080000_12345678', 'request': {**request(), 'question': '--eval $(touch /tmp/not-executed)'}}
    argv = m._command(job)
    assert argv[-2:] == ['--', '--eval $(touch /tmp/not-executed)']
    assert argv[:3] == [sys.executable, '-m', 'momentum_research_agent.cli']


def test_process_exit_zero_does_not_establish_brief_success(tmp_path):
    import json
    m = manager(tmp_path)
    folder = m.reports / 'brief_test'
    folder.mkdir(parents=True)
    job = {'artifact_id': 'brief_test', 'request': {'kind': 'brief', 'as_of': '2026-05-29'}}
    (folder / 'brief.json').write_text(json.dumps({'schema_version': 'wrong', 'status': 'partial'}))
    assert m._classify(job, 0)[0] == 'failed'


def test_previous_brief_skips_invalid_structures(tmp_path):
    m = manager(tmp_path)
    (m.reports / 'bad').mkdir(parents=True)
    p = m.reports / 'bad/brief.json'
    for content in ('[]', '{"status":"partial","requested_as_of":null}'):
        p.write_text(content)
        assert m._previous_brief('2026-09-08') is None


def test_termination_escalates_for_descendants_even_after_leader_exits(monkeypatch):
    import signal
    signals = []
    monkeypatch.setattr('control_manager.os.killpg', lambda pid, sig: signals.append(sig))
    class Process:
        pid = 12345
        def poll(self):
            return None
        def wait(self, timeout):
            return -15
    ControlManager._terminate(Process())
    assert signals == [signal.SIGTERM, signal.SIGKILL]


def test_valid_brief_classification_prior_selection_and_duplicate_skip(tmp_path):
    from momentum_research_agent.daily_brief import DailyBrief
    m = manager(tmp_path)
    folder = m.reports / 'brief_fixture'
    folder.mkdir(parents=True)
    brief = DailyBrief(requested_as_of='2026-09-08', status='partial', delivery_contract={'verdict': 'pass'})
    (folder / 'brief.json').write_text(brief.model_dump_json())
    job = {'artifact_id': folder.name, 'request': {'kind': 'brief', 'as_of': '2026-09-08'}}
    assert m._classify(job, 0)[0] == 'completed'
    assert m._classify(job, 1)[0] == 'failed'
    assert m._previous_brief('2026-09-09') == folder / 'brief.json'
    m.set_schedule(True, at('2026-09-08T20:00:00-04:00'))
    m.tick(at('2026-09-09T08:00:00-04:00'))
    assert m.data['schedule']['state'] == 'skipped'
    assert not m.data['jobs']
    brief.status = 'unavailable'
    (folder / 'brief.json').write_text(brief.model_dump_json())
    assert m._classify(job, 1)[0] == 'unavailable'


def test_supervisor_timeout_uses_fixed_argv_and_cleans_group(tmp_path, monkeypatch):
    import subprocess
    seen = []
    class Process:
        pid = 12345
        calls = 0
        def wait(self, timeout):
            self.calls += 1
            if self.calls == 1:
                assert timeout == 900
                raise subprocess.TimeoutExpired('controlled-worker', timeout)
            return -15
    def popen(argv, **kwargs):
        seen.append((argv, kwargs))
        return Process()
    monkeypatch.setattr('control_manager.subprocess.Popen', popen)
    monkeypatch.setattr('control_manager.os.killpg', lambda *args: None)
    m = ControlManager(tmp_path / 'state', tmp_path / 'backend')
    m.submit(request(), at('2026-09-09T08:00:00-04:00'))
    m.wait_idle(3)
    assert m.data['jobs'][0]['state'] == 'timed_out'
    assert seen[0][1]['start_new_session'] is True
    assert seen[0][0][-2:] == ['--', 'Explain momentum risk']
    assert not m.processes


def test_restart_marks_active_interrupted_without_replaying(tmp_path):
    m = manager(tmp_path)
    m.submit(request(), at('2026-09-09T08:00:00-04:00'))
    m.wait_idle(3)
    m.data['jobs'][0]['state'] = 'running'
    m._save()
    restored = manager(tmp_path, runner=lambda _: pytest.fail('Must not replay'))
    assert restored.snapshot()['jobs'][0]['state'] == 'interrupted'


def test_persist_failure_after_spawn_still_terminates_owned_process(tmp_path, monkeypatch):
    m = manager(tmp_path)
    process = object()
    cleaned = []
    monkeypatch.setattr('control_manager.subprocess.Popen', lambda *a, **kw: process)
    monkeypatch.setattr(m, '_terminate', lambda p: cleaned.append(p))
    def fail_save():
        raise OSError('Disk full')
    monkeypatch.setattr(m, '_save', fail_save)
    job = {'id': 'test-id', 'artifact_id': '20260909_080000_12345678', 'request': request()}
    with pytest.raises(OSError):
        m._run_job(job)
    assert cleaned == [process]
    assert not m.processes
