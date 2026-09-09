import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from control_manager import ControlManager
from control_service import make_server


def test_http_auth_origin_and_fixed_routes(tmp_path):
    manager = ControlManager(tmp_path / 'state', tmp_path / 'backend', runner=lambda j: ('completed', 'Done'))
    server = make_server(manager, 'private-token', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def call(endpoint, body=None, token='private-token', origin='http://127.0.0.1:4173', host=None):
        headers = {'X-Control-Token': token, 'Content-Type': 'application/json'}
        if origin:
            headers['Origin'] = origin
        if host:
            headers['Host'] = host
        req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}{endpoint}',
                                     data=None if body is None else json.dumps(body).encode(), headers=headers)
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)
    try:
        assert call('/status', token='wrong')[0] == 403
        assert call('/status', host='evil.example')[0] == 403
        assert call('/schedule', {'enabled': True}, origin=None)[0] == 403
        assert call('/schedule', {'enabled': True}, origin='https://evil.example')[0] == 403
        assert call('/shell', {'command': 'echo bad'})[0] == 404
        assert call('/schedule', {'enabled': 'yes'})[0] == 400
        status, payload = call('/schedule', {'enabled': True})
        assert status == 200 and payload['enabled'] is True
        assert call('/status')[1]['schedule']['timezone'] == 'America/Toronto'
        assert 'private-token' not in json.dumps(call('/status')[1])
    finally:
        server.shutdown()
        server.server_close()
        manager.stop()
