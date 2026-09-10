import asyncio
import hashlib
import importlib
import json
import socket
import sys

import pytest

from momentum_research_agent.tools import authorize_tools, registered_names
from momentum_research_agent.tools.registry import ToolContext, set_tool_context


def test_reader_is_an_explicit_authorized_tool():
    assert 'read_url' in registered_names()
    assert 'read_url' in authorize_tools('momentum_analyst')
    assert 'read_url' in authorize_tools('verifier')


def test_reader_keeps_table_cells_and_links_not_scripts():
    from momentum_research_agent.tools.public_web import extract
    text, links = extract(b'<h1>Holdings as of 2026-09-08</h1><script>fake weight</script><table><tr><td>AAA</td><td>10%</td></tr></table><a href="/holdings.csv">Download</a>', 'text/html', 'https://example.com/fund')
    assert 'AAA' in text and '10%' in text and '2026-09-08' in text
    assert 'fake weight' not in text
    assert links == ['https://example.com/holdings.csv']


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'http://example.com', 'https://a:b@example.com', 'https://example.com:8443', 'https://127.0.0.1', 'https://[::1]', 'https://169.254.169.254/latest', 'https://224.0.0.1'])
def test_reader_rejects_unsafe_destinations(url):
    from momentum_research_agent.tools.public_web import destination
    with pytest.raises(ValueError):
        destination(url)


def test_reader_checks_all_dns_answers_and_pins_public_address(monkeypatch):
    from momentum_research_agent.tools.public_web import destination
    def dns(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]
    monkeypatch.setattr(socket, 'getaddrinfo', dns)
    assert destination('https://example.com/a?q=b#c') == ('example.com', '93.184.216.34', '/a?q=b')
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: dns() + [(socket.AF_INET, 1, 6, '', ('10.0.0.1',443))])
    with pytest.raises(ValueError): destination('https://example.com')


@pytest.mark.asyncio
async def test_reader_archives_content_hash_and_returns_real_text(tmp_path, monkeypatch):
    module = importlib.import_module('momentum_research_agent.tools.read_url')
    async def fetch(url):
        return {'url':url,'text':'AAA 10% as of 2026-09-08','links':[], 'content_type':'text/csv','truncated':False}
    monkeypatch.setattr(module, '_fetch', fetch)
    set_tool_context(ToolContext(project_root=tmp_path, session_dir=tmp_path))
    result = json.loads(await module.read_url('https://example.com/holdings.csv'))
    assert result['status'] == 'ok' and result['evidence_kind'] == 'page_content'
    assert 'AAA 10%' in result['text']
    raw = (tmp_path / result['artifact']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == result['sha256']
    assert json.loads(raw)['fetched_at'] == result['fetched_at']


@pytest.mark.asyncio
async def test_reader_bounds_attempts_and_preserves_cancellation(tmp_path, monkeypatch):
    module = importlib.import_module('momentum_research_agent.tools.read_url')
    ctx = ToolContext(project_root=tmp_path, session_dir=tmp_path)
    set_tool_context(ctx)
    async def fail(url): raise ValueError('Blocked response')
    monkeypatch.setattr(module, '_fetch', fail)
    for _ in range(3):
        assert json.loads(await module.read_url('https://example.com'))['status'] == 'unavailable'
    assert json.loads(await module.read_url('https://example.com'))['budget_exhausted']
    set_tool_context(ToolContext(project_root=tmp_path, session_dir=tmp_path))
    async def cancel(url): raise asyncio.CancelledError
    monkeypatch.setattr(module, '_fetch', cancel)
    with pytest.raises(asyncio.CancelledError): await module.read_url('https://example.com')


@pytest.mark.parametrize('body, content_type, expected', [
    (b'AAA,10%', 'text/csv', 'AAA,10%'), (b'{"weight":10}', 'application/json', '"weight":10'),
    (b'hello', 'text/plain', 'hello'), (b'<p>hi</p>', 'application/xhtml+xml', 'hi'),
])
def test_supported_source_formats(body, content_type, expected):
    from momentum_research_agent.tools.public_web import extract
    assert expected in extract(body, content_type, 'https://example.com')[0]


@pytest.mark.parametrize('status, headers, body, error', [
    (403, {}, b'', 'HTTP 403'), (200, {'Content-Encoding':'gzip'}, b'', 'Compressed'),
    (200, {'Content-Type':'application/pdf'}, b'%PDF', 'Unsupported'),
    (200, {'Content-Type':'text/plain'}, b'', 'Empty'),
    (200, {'Content-Type':'text/plain'}, b'a'*512001, 'byte limit'),
    (302, {}, b'', 'Redirect missing'),
    (302, {'Location':'https://127.0.0.1/private'}, b'', 'Non-public'),
])
def test_fetch_rejects_bad_responses_and_redirects(monkeypatch, status, headers, body, error):
    from momentum_research_agent.tools import public_web as module
    monkeypatch.setattr(socket, 'getaddrinfo', lambda host, *a, **k: [(2,1,6,'',('127.0.0.1' if host == '127.0.0.1' else '93.184.216.34',443))])
    class Response:
        def getheader(self, name, default=None): return headers.get(name, default)
        def read(self, limit): return body[:limit]
    response = Response(); response.status = status
    class Connection:
        def __init__(self, host, ip): pass
        def request(self, method, target, headers): pass
        def getresponse(self): return response
        def close(self): pass
    monkeypatch.setattr(module, 'PublicHTTPS', Connection)
    with pytest.raises(ValueError, match=error): module.fetch('https://example.com')


def test_fetch_retains_full_body_and_marks_text_truncation(monkeypatch):
    import base64
    from momentum_research_agent.tools import public_web as module
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(2,1,6,'',('93.184.216.34',443))])
    body = b'A'*13000
    class Connection:
        status = 200
        def __init__(self, host, ip): assert ip == '93.184.216.34'
        def request(self, method, target, headers):
            assert method == 'GET' and 'Authorization' not in headers
        def getresponse(self): return self
        def getheader(self, name, default=None): return 'text/plain' if name == 'Content-Type' else default
        def read(self, limit): return body
        def close(self): pass
    monkeypatch.setattr(module, 'PublicHTTPS', Connection)
    result = module.fetch('https://example.com')
    assert result['truncated'] and len(result['text']) == 12000
    assert base64.b64decode(result['body_base64']) == body


@pytest.mark.asyncio
async def test_worker_error_and_cancellation_leave_no_process(monkeypatch):
    module = importlib.import_module('momentum_research_agent.tools.read_url')
    create = asyncio.create_subprocess_exec
    children = []
    async def launch(*args, **kwargs):
        child = await create(sys.executable,'-c','import time;time.sleep(60)', stdout=asyncio.subprocess.PIPE)
        children.append(child)
        return child
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', launch)
    task = asyncio.create_task(module._fetch('https://example.com'))
    while not children: await asyncio.sleep(.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert children[0].returncode is not None
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', create)
    with pytest.raises(ValueError): await module._fetch('file:///etc/passwd')
