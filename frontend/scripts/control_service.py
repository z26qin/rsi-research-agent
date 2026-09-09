"""Independent localhost service. Never enabled or launched by the frontend build."""
import argparse
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from artifact_watch import default_project_root
from control_manager import ControlManager, atomic_json


def state_directory(project):
    key = hashlib.sha256(str(project.resolve()).encode()).hexdigest()[:16]
    return Path(os.environ.get('MOMENTUM_CONTROL_STATE_DIR') or Path.home() / '.local/state/momentum-ui' / key)


def make_server(manager, token, port=4181, frontend_port=4173):
    origins = {f'http://127.0.0.1:{frontend_port}', f'http://localhost:{frontend_port}'}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Never print provider output, request questions or auth tokens.

        def reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def authorized(self, write=False):
            host = self.headers.get('Host', '')
            origin = self.headers.get('Origin')
            expected = self.headers.get('X-Control-Token', '')
            return (host in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
                    and hmac.compare_digest(expected, token)
                    and (origin in origins if write or origin else True))

        def do_GET(self):
            if not self.authorized():
                return self.reply(403, {'error': 'Local authenticated access required'})
            if self.path != '/status':
                return self.reply(404, {'error': 'Unknown endpoint'})
            self.reply(200, manager.snapshot())

        def do_POST(self):
            if not self.authorized(write=True):
                return self.reply(403, {'error': 'Same-origin authenticated access required'})
            if self.path not in ('/jobs', '/schedule'):
                return self.reply(404, {'error': 'Unknown endpoint'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 16384 or self.headers.get('Transfer-Encoding') or self.headers.get('Content-Type') != 'application/json':
                    return self.reply(400, {'error': 'A bounded JSON body is required'})
                self.connection.settimeout(5)
                body = json.loads(self.rfile.read(size))
                if self.path == '/jobs':
                    result = manager.submit(body)
                else:
                    if not isinstance(body, dict) or set(body) != {'enabled'}:
                        raise ValueError('Only schedule enabled may be changed')
                    result = manager.set_schedule(body['enabled'])
                self.reply(200, result)
            except (ValueError, TypeError):
                self.reply(400, {'error': 'Request rejected: invalid input, duplicate key conflict, or another job is active.'})
            except (OSError, TimeoutError):
                self.reply(503, {'error': 'Local service could not persist or complete this request'})

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=os.environ.get('MOMENTUM_ARTIFACT_PROJECT_ROOT') or default_project_root())
    parser.add_argument('--state-root', type=Path)
    parser.add_argument('--port', type=int, default=4181)
    parser.add_argument('--frontend-port', type=int, default=4173)
    parser.add_argument('--brief-source', choices=['engine', 'etf-proxy'])
    args = parser.parse_args()
    project = args.project_root.resolve()
    if not (project / 'src/momentum_research_agent/cli.py').is_file():
        raise SystemExit('Configured backend project is unavailable')
    sys.path.insert(0, str(project / 'src'))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
    reports = project / 'reports'
    if reports.is_symlink():
        raise SystemExit('Reports directory must not be a symlink')
    reports.mkdir(exist_ok=True)
    lock_fd = os.open(reports / '.control-service.lock', os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Another control service or surviving owned job holds this backend lock')
    state_root = args.state_root or state_directory(project)
    if state_root.is_symlink():
        raise SystemExit('Control state directory must not be a symlink')
    state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state_root, 0o700)
    token = secrets.token_urlsafe(32)
    atomic_json(state_root / 'connection.json', {'token': token, 'port': args.port, 'project': str(project)})
    manager = ControlManager(state_root, project, lock_fd=lock_fd, brief_source=args.brief_source)
    server = make_server(manager, token, args.port, args.frontend_port)
    stopping = threading.Event()
    def stop(*_):
        stopping.set()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    def schedule_loop():
        while not stopping.is_set():
            try:
                manager.tick()
            except Exception:
                # Fail closed, but keep the status endpoint available for the operator.
                with manager.lock:
                    manager.data['schedule'].update(state='error', message='Scheduler check failed; no run was launched')
                    manager._save()
            stopping.wait(5)
    ticker = threading.Thread(target=schedule_loop, daemon=True)
    ticker.start()
    server.timeout = 1
    print(f'Local control listening on 127.0.0.1:{args.port}; schedule state is persisted.', flush=True)
    try:
        while not stopping.is_set():
            server.handle_request()
    finally:
        stopping.set()
        manager.stop()
        ticker.join(35)
        server.server_close()
        os.close(lock_fd)


if __name__ == '__main__':
    main()
