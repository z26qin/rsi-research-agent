"""Bounded, credential-free public HTTPS reader; also runs as a killable worker."""
from __future__ import annotations

import base64
import http.client
import ipaddress
import json
import socket
import ssl
import sys
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlsplit

MAX_BYTES = 512_000
MAX_TEXT = 12_000


def destination(url: str) -> tuple[str, str, str]:
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 33 for c in url):
        raise ValueError('Invalid public URL')
    p = urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443):
        raise ValueError('Only public HTTPS on port 443 without credentials is supported')
    host = p.hostname.encode('idna').decode('ascii')
    answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    ips = [row[4][0] for row in answers]
    if not ips or any(not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).is_multicast for ip in ips):
        raise ValueError('Non-public network destination blocked')
    target = quote(p.path or '/', safe='/%:@!$&\'()*+,;=-._~')
    if p.query:
        target += '?' + quote(p.query, safe='/%?:@!$&\'()*+,;=-._~')
    return host, ips[0], target


class PublicHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, ip: str):
        super().__init__(host, timeout=6, context=ssl.create_default_context())
        self.ip = ip

    def connect(self):
        # Pin the validated address: no second DNS lookup / rebinding window.
        sock = socket.create_connection((self.ip, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


class PageText(HTMLParser):
    def __init__(self, url: str):
        super().__init__(convert_charrefs=True)
        self.url = url
        self.hidden = 0
        self.parts: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'noscript', 'template'}:
            self.hidden += 1
        if not self.hidden:
            if tag == 'a':
                href = dict(attrs).get('href')
                if href:
                    link = urljoin(self.url, href)
                    if link.startswith('https://') and len(link) <= 2048 and link not in self.links and len(self.links) < 30:
                        self.links.append(link)
            if tag in {'tr', 'p', 'div', 'br', 'h1', 'h2', 'h3', 'li'}:
                self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'noscript', 'template'}:
            self.hidden = max(0, self.hidden - 1)
        if not self.hidden and tag in {'td', 'th'}:
            self.parts.append(' | ')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def extract(body: bytes, content_type: str, url: str) -> tuple[str, list[str]]:
    text = body.decode('utf-8-sig', errors='replace')
    if content_type in {'text/html', 'application/xhtml+xml'}:
        parser = PageText(url)
        parser.feed(text)
        return '\n'.join(' '.join(row.split()) for row in ''.join(parser.parts).splitlines() if row.strip()), parser.links[:30]
    if content_type in {'text/plain', 'text/csv', 'application/json'}:
        return text, []
    raise ValueError('Unsupported content type; HTML, UTF-8 text, CSV and JSON only')


def fetch(url: str) -> dict:
    for _ in range(4):
        host, ip, target = destination(url)
        connection = PublicHTTPS(host, ip)
        try:
            connection.request('GET', target, headers={
                'User-Agent': 'MomentumResearch/1.0 (personal research)',
                'Accept': 'text/html,text/plain,text/csv,application/json',
                'Accept-Encoding': 'identity',
            })
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader('Location')
                if not location:
                    raise ValueError('Redirect missing destination')
                url = urljoin(url, location)
                continue  # Every redirect is validated and pinned independently.
            if response.status != 200:
                raise ValueError(f'HTTP {response.status}; no content retrieved')
            if response.getheader('Content-Encoding', 'identity') != 'identity':
                raise ValueError('Compressed content unsupported')
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise ValueError('Page exceeds byte limit')
            content_type = response.getheader('Content-Type', '').split(';')[0].strip().lower()
            text, links = extract(body, content_type, url)
            if not text.strip():
                raise ValueError('Empty page content')
            return {'url': url, 'text': text[:MAX_TEXT], 'links': links,
                    'content_type': content_type, 'truncated': len(text) > MAX_TEXT,
                    'body_base64': base64.b64encode(body).decode('ascii')}
        finally:
            connection.close()
    raise ValueError('Redirect limit reached')


if __name__ == '__main__':
    try:
        print(json.dumps(fetch(sys.argv[1])))
    except Exception as exc:
        # Do not include arbitrary response bodies, credentials or exception URLs.
        print(json.dumps({'error': str(exc) if isinstance(exc, ValueError) else 'Public HTTPS retrieval failed'}))
