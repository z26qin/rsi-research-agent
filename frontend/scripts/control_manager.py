"""Restricted local CLI supervision and durable Daily Brief scheduling."""
from __future__ import annotations

import copy
import json
import os
import re
import signal
import subprocess
import sys
import threading
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from control_calendar import TORONTO, is_session, latest_completed, next_morning


def utcnow():
    return datetime.now(timezone.utc)


def validate_request(raw, now):
    if not isinstance(raw, dict) or raw.get('confirmed') is not True:
        raise ValueError('Explicit run confirmation required')
    common = {'kind', 'confirmed', 'request_id'}
    if not isinstance(raw.get('request_id'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', raw['request_id']):
        raise ValueError('A valid idempotency key is required')
    if raw.get('kind') == 'research':
        if set(raw) != common | {'question', 'mode', 'agents'}:
            raise ValueError('Unsupported research parameters')
        if not isinstance(raw['question'], str) or not 1 <= len(raw['question'].strip()) <= 4000:
            raise ValueError('Question must contain 1–4000 characters')
        if raw['mode'] not in ('single', 'team') or type(raw['agents']) is not int or not 1 <= raw['agents'] <= 4:
            raise ValueError('Select single/team mode and 1–4 agents')
        return {**raw, 'question': raw['question'].strip(), 'agents': 1 if raw['mode'] == 'single' else raw['agents']}
    if raw.get('kind') == 'brief':
        if set(raw) != common | {'as_of'} or not isinstance(raw['as_of'], str):
            raise ValueError('Unsupported brief parameters')
        day = date.fromisoformat(raw['as_of'])
        if day.isoformat() != raw['as_of'] or not is_session(day) or day > latest_completed(now):
            raise ValueError('Choose a completed NYSE trading session')
        return dict(raw)
    raise ValueError('Only research and brief runs are permitted')


def atomic_json(path, value):
    temporary = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


class ControlManager:
    def __init__(self, state_root, project_root, runner=None, readiness=None, lock_fd=None, brief_source=None):
        self.root = Path(project_root).resolve()
        self.reports = self.root / 'reports'
        if self.reports.is_symlink():
            raise ValueError('Reports directory must not be a symlink')
        self.state_root = Path(state_root).resolve()
        self.state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.state_root / 'state.json'
        self.lock = threading.RLock()
        self.lock_fd = lock_fd
        self.processes = {}
        self.threads = []
        self.stopping = False
        self.runner = runner or self._run_job
        self.readiness = readiness or self._readiness
        if self.path.exists():
            # Corrupted durable state is an operator error, never reset dedupe silently.
            self.data = json.loads(self.path.read_text())
            if self.data.get('version') != 1 or not isinstance(self.data.get('jobs'), list) or not isinstance(self.data.get('schedule'), dict):
                raise ValueError('Control state is invalid; automatic recovery is disabled')
            self._validate_state()
            for job in self.data['jobs']:
                if job['state'] in ('starting', 'running'):
                    job.update(state='interrupted', message='Service restarted; this run was not replayed.')
        else:
            self.data = {'version': 1, 'project_root': str(self.root), 'jobs': [], 'schedule': {
                'enabled': False, 'timezone': 'America/Toronto', 'time': '08:00',
                'state': 'disabled', 'message': 'Schedule disabled', 'checks': 0,
                'not_before': None, 'next_check': None, 'day': None, 'targets': {},
            }}
        prior_source = self.data.get('brief_source', 'engine')
        self.brief_source = brief_source or prior_source
        if self.brief_source not in ('engine', 'etf-proxy'):
            raise ValueError('Unsupported brief source')
        self.data['brief_source'] = self.brief_source
        if self.brief_source != prior_source and self.data['schedule']['enabled']:
            start = next_morning(utcnow()).isoformat()
            self.data['schedule'].update(state='scheduled', message='Brief source changed; next morning collection scheduled',
                                         not_before=start, next_check=start, checks=0, day=None)
            self.data['schedule'].pop('target', None)
        self._save()

    def _validate_state(self):
        def require(condition):
            if not condition:
                raise ValueError('Invalid durable control state')
        try:
            s = self.data['schedule']
            require(self.data['project_root'] == str(self.root))
            require(type(s['enabled']) is bool and s['timezone'] == 'America/Toronto' and s['time'] == '08:00')
            require(type(s['checks']) is int and 0 <= s['checks'] <= 9)
            require(isinstance(s['targets'], dict))
            require(all(isinstance(k, str) and isinstance(v, str) for k, v in s['targets'].items()))
            for field in ('not_before', 'next_check'):
                if s[field] is not None:
                    require(datetime.fromisoformat(s[field]).tzinfo is not None)
                elif s['enabled']:
                    raise ValueError('Enabled schedule missing timing')
            for job in self.data['jobs']:
                require(re.fullmatch(r'[0-9a-f]{32}', job['id']))
                require(re.fullmatch(r'(brief_)?[0-9]{8}_[0-9]{6}_[0-9a-f]{8}', job['artifact_id']))
                require(job['state'] in ('starting', 'running', 'completed', 'unavailable', 'failed', 'timed_out', 'interrupted'))
                validate_request(job['request'], datetime.fromisoformat(job['created_at']))
        except (KeyError, TypeError, ValueError, AssertionError):
            raise ValueError('Control state is invalid; repair it before starting the service') from None

    def _save(self):
        atomic_json(self.path, self.data)

    def _busy(self):
        return any(j['state'] in ('starting', 'running') for j in self.data['jobs'])

    def snapshot(self, now=None):
        with self.lock:
            result = copy.deepcopy(self.data)
        result['jobs'] = list(reversed(result['jobs']))
        result.update(service='online', checked_at=(now or utcnow()).isoformat(),
                      calendar='NYSE 2026–2028', limits={'research_seconds': 900, 'brief_seconds': 180})
        return result

    def submit(self, raw, now=None, scheduled=False):
        now = now or utcnow()
        request = validate_request(raw, now)
        with self.lock:
            for job in self.data['jobs']:
                if job['request']['request_id'] == request['request_id']:
                    if job['request'] != request:
                        raise ValueError('Idempotency key already belongs to a different request')
                    return copy.deepcopy(job)
            if self.stopping or self._busy():
                raise ValueError('Another service-owned job is active; wait before submitting')
            identifier = uuid.uuid4().hex
            artifact = ('brief_' if request['kind'] == 'brief' else '') + now.strftime('%Y%m%d_%H%M%S_') + identifier[:8]
            job = {'id': identifier, 'artifact_id': artifact, 'request': request,
                   'brief_source': self.brief_source if request['kind'] == 'brief' else None,
                   'state': 'starting', 'message': 'Starting backend CLI', 'scheduled': scheduled,
                   'created_at': now.isoformat(), 'finished_at': None}
            self.data['jobs'].append(job)
            if request['kind'] == 'brief':
                # A scheduled attempt is consumed before execution (at most once).
                if scheduled:
                    self.data['schedule']['targets'][self._target_key(request['as_of'])] = identifier
            self._save()
            thread = threading.Thread(target=self._execute, args=(job,), daemon=True)
            self.threads.append(thread)
            thread.start()
            return copy.deepcopy(job)

    def _execute(self, job):
        try:
            state, message = self.runner(job)
            if state not in ('completed', 'unavailable', 'failed', 'timed_out', 'interrupted'):
                raise ValueError('Invalid runner outcome')
        except Exception:
            state, message = 'failed', 'Backend run failed; inspect its saved artifacts locally.'
        with self.lock:
            job.update(state=state, message=message, finished_at=utcnow().isoformat())
            self._save()

    def _environment(self):
        return {**os.environ, 'PYTHONPATH': str(self.root / 'src')}

    def _command(self, job):
        r = job['request']
        output = self.reports / job['artifact_id']
        if self.reports.is_symlink() or output.exists() or output.is_symlink():
            raise ValueError('Output must be a new local artifact directory')
        if r['kind'] == 'brief' and job.get('brief_source', 'engine') == 'etf-proxy':
            return [sys.executable, str(Path(__file__).with_name('proxy_control_worker.py')),
                    str(self.root), r['as_of'], str(output)]
        argv = [sys.executable, '-m', 'momentum_research_agent.cli', '--session-dir', str(output)]
        if r['kind'] == 'research':
            argv += ['--mode', r['mode'], '--max-sub-agents', str(r['agents']), '--', r['question']]
        else:
            argv += ['--daily-brief', '--as-of', r['as_of']]
            previous = self._previous_brief(r['as_of'])
            if previous:
                argv += ['--previous-brief', str(previous)]
        return argv

    def _previous_brief(self, as_of):
        from momentum_research_agent.daily_brief import DailyBrief
        candidates = []
        if self.reports.exists():
            for folder in self.reports.iterdir():
                p = folder / 'brief.json'
                if folder.is_symlink() or not folder.is_dir() or p.is_symlink() or not p.is_file():
                    continue
                try:
                    b = DailyBrief.model_validate_json(p.read_text())
                    if b.status == 'partial' and b.requested_as_of.isoformat() < as_of:
                        candidates.append((b.requested_as_of.isoformat(), p))
                except (OSError, ValueError):
                    continue
        return max(candidates, key=lambda row: row[0])[1] if candidates else None

    def _run_job(self, job):
        argv = self._command(job)
        process = None
        try:
            with self.lock:
                if self.stopping:
                    return 'interrupted', 'Service is stopping'
                process = subprocess.Popen(argv, cwd=self.root, env=self._environment(),
                                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           start_new_session=True, pass_fds=(() if self.lock_fd is None else (self.lock_fd,)))
                self.processes[job['id']] = process
                job.update(state='running', message='Backend process is running')
                self._save()
            code = process.wait(timeout=180 if job['request']['kind'] == 'brief' else 900)
            if self.stopping:
                return 'interrupted', 'Service stopped; run was not replayed'
            return self._classify(job, code)
        except subprocess.TimeoutExpired:
            self._terminate(process)
            return 'timed_out', 'Execution deadline reached; no automatic retry'
        finally:
            if process is not None:
                self._terminate(process)
            with self.lock:
                self.processes.pop(job['id'], None)

    def _classify(self, job, code):
        folder = self.reports / job['artifact_id']
        if job['request']['kind'] == 'brief' and job.get('brief_source', 'engine') == 'etf-proxy':
            try:
                from proxy_control_worker import validate_proxy
                b = validate_proxy(folder, job['request']['as_of'])
                if b.status == 'unavailable':
                    return 'unavailable', 'Required ETF observations unavailable; no stale substitution'
                if code == 0:
                    return 'completed', 'ETF market observations available; original model assessment unavailable'
            except (OSError, ValueError, KeyError, TypeError):
                pass
            return 'failed', 'Proxy artifact or saved-table validation failed'
        if job['request']['kind'] == 'brief':
            try:
                from momentum_research_agent.daily_brief import DailyBrief
                b = DailyBrief.model_validate_json((folder / 'brief.json').read_text())
                if b.requested_as_of.isoformat() != job['request']['as_of']:
                    raise ValueError('Wrong as-of')
                if b.status == 'unavailable':
                    return 'unavailable', 'Assessment withheld; see brief limitations'
                if code == 0 and b.delivery_contract.get('verdict') == 'pass':
                    return 'completed', 'Partial market/book brief available; not independently verified'
            except (OSError, ValueError):
                pass
            return 'failed', 'Brief did not produce a valid successful artifact'
        # Exit success is a process result, never a verifier claim.
        if code == 0 and (folder / 'task_board.json').is_file():
            return 'completed', 'Research process finished; inspect reports and independent verification'
        return 'failed', 'Research process failed; check backend configuration and saved artifacts'

    @staticmethod
    def _terminate(process):
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        except ProcessLookupError:
            pass
        # The leader exiting does not prove its descendants exited. Always
        # escalate the owned group, including after normal leader completion.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)

    def wait_idle(self, timeout=10):
        for thread in list(self.threads):
            thread.join(timeout)

    def stop(self):
        with self.lock:
            self.stopping = True
            processes = list(self.processes.values())
        for process in processes:
            self._terminate(process)
        self.wait_idle()

    def _readiness(self, day):
        if self.brief_source == 'etf-proxy':
            return True, 'Bounded ETF collection permitted; source coverage checked during generation'
        try:
            result = subprocess.run([sys.executable, str(Path(__file__).with_name('control_probe.py')),
                                     str(self.root), day], cwd=self.root, env=self._environment(),
                                    capture_output=True, text=True, timeout=30)
            value = json.loads(result.stdout)
            return result.returncode == 0 and value.get('ready') is True, str(value.get('message', 'Input coverage unavailable'))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return False, 'Input readiness check failed or timed out'

    def set_schedule(self, enabled, now=None):
        if type(enabled) is not bool:
            raise ValueError('enabled must be boolean')
        now = now or utcnow()
        with self.lock:
            s = self.data['schedule']
            if enabled != s['enabled']:
                start = next_morning(now).isoformat() if enabled else None
                s.update(enabled=enabled, state='scheduled' if enabled else 'disabled',
                         message='Next morning check scheduled' if enabled else 'Schedule disabled; active jobs are unaffected',
                         not_before=start, next_check=start, day=None, checks=0)
                self._save()
            return copy.deepcopy(s)

    def _already_available(self, target):
        # Include valid existing CLI-produced briefs, not just service history.
        from momentum_research_agent.daily_brief import DailyBrief
        if not self.reports.is_dir() or self.reports.is_symlink():
            return False
        for folder in self.reports.iterdir():
            p = folder / 'brief.json'
            if folder.is_symlink() or not folder.is_dir() or p.is_symlink() or not p.is_file():
                continue
            try:
                if self.brief_source == 'etf-proxy':
                    from proxy_control_worker import validate_proxy
                    if validate_proxy(folder, target).status == 'partial':
                        return True
                    continue
                brief = DailyBrief.model_validate_json(p.read_text())
                if brief.requested_as_of.isoformat() == target and brief.status == 'partial' and brief.delivery_contract.get('verdict') == 'pass':
                    return True
            except (OSError, ValueError):
                continue
        return False

    def _target_key(self, target):
        return ('etf-proxy:' if self.brief_source == 'etf-proxy' else '') + target

    def tick(self, now=None):
        actual_clock = now is None
        now = now or utcnow()
        with self.lock:
            s = self.data['schedule']
            if not s['enabled'] or self.stopping or now < datetime.fromisoformat(s['not_before']):
                return
            local = now.astimezone(TORONTO)
            morning = datetime.combine(local.date(), time(8), TORONTO)
            end = datetime.combine(local.date(), time(10), TORONTO)
            if local < morning or (s['next_check'] and now < datetime.fromisoformat(s['next_check'])):
                return
            if s['day'] != local.date().isoformat():
                s.update(day=local.date().isoformat(), checks=0)
            if local > end or s['checks'] >= 9:
                s.update(state='expired', message='Morning input window missed or exhausted; no catch-up run', next_check=next_morning(now).isoformat())
                self._save()
                return
            try:
                target = latest_completed(morning).isoformat()
                if self._target_key(target) in s['targets'] or self._already_available(target):
                    s.update(state='skipped', message='This trading date already has a brief or scheduled attempt', next_check=next_morning(now).isoformat())
                    self._save()
                    return
            except (ValueError, OSError):
                s.update(state='error', message='Trading calendar or prior artifacts unavailable', next_check=next_morning(now).isoformat())
                self._save()
                return
            s.update(checks=s['checks'] + 1, target=target, state='checking_inputs',
                     message='Checking cached input coverage', next_check=(now + timedelta(minutes=15)).isoformat())
            self._save()
            generation = s['not_before']
        ready, message = self.readiness(target)
        with self.lock:
            s = self.data['schedule']
            if not s['enabled'] or self.stopping or s['not_before'] != generation:
                return
            if actual_clock and utcnow().astimezone(TORONTO) > end:
                s.update(state='expired', message='Input check finished after the morning window; no run launched', next_check=next_morning(utcnow()).isoformat())
                self._save()
                return
            if not ready or self._busy():
                s.update(state='waiting_inputs' if not ready else 'waiting_job', message=message if not ready else 'Waiting for current service-owned job')
            else:
                self.submit({'kind': 'brief', 'as_of': target, 'confirmed': True,
                             'request_id': 'scheduled-' + self.brief_source + '-' + target}, now, scheduled=True)
                s.update(state='submitted', message='Daily Brief submitted; outcome appears in run history', next_check=next_morning(now).isoformat())
            self._save()
