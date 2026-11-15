"""Bounded public HTTPS GETs. Honest user agent, robots, no retries, credentials or bypass."""
from datetime import datetime, timezone
import ipaddress
import json
import re
import socket
import subprocess
import time
from urllib.parse import urljoin, urlsplit, urldefrag
from urllib.robotparser import RobotFileParser

UA = 'RIPPLEResearch/0.2 (limited public financial research; no authenticated access)'
MAX_BYTES = 25 * 1024 * 1024
MAX_TOTAL = 300 * 1024 * 1024
MARK = b'\n__RIPPLE_META__'


def now():
    return datetime.now(timezone.utc).isoformat()


def safe_url(url):
    p = urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443):
        raise ValueError('Only public credential-free HTTPS URLs are allowed')
    if p.hostname == 'localhost' or p.hostname.endswith(('.local', '.internal')):
        raise ValueError('Private host rejected')
    try:
        if not ipaddress.ip_address(p.hostname).is_global: raise ValueError('Private address rejected')
    except ValueError as exc:
        if re.fullmatch(r'[0-9.:]+', p.hostname): raise exc
    if re.search(r'(api[_-]?key|token|password|signature|credential)=', p.query, re.I):
        raise ValueError('Credential-bearing query rejected')
    return urldefrag(url)[0]


class Client:
    def __init__(self, offline=False):
        self.cache = {}; self.robots = {}; self.last = {}; self.requests = 0; self.total = 0
        self.offline = offline

    def raw(self, url, limit=MAX_BYTES):
        url = safe_url(url)
        if self.requests >= 180 or self.total >= MAX_TOTAL:
            return {'status': 'pending_limit', 'url': url, 'reason': 'Batch budget exhausted'}
        host = urlsplit(url).hostname
        # Check actual DNS before curl, without accepting local/private network addresses.
        try:
            addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            if any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                return {'status': 'blocked_private_network', 'url': url}
        except OSError:
            return {'status': 'pending_network', 'url': url, 'reason': 'Public host DNS unavailable'}
        time.sleep(max(0, 1.0 - (time.monotonic() - self.last.get(host, 0))))
        self.last[host] = time.monotonic(); self.requests += 1
        args = ['/usr/bin/curl', '-q', '--silent', '--show-error', '--proto', '=https',
                '--connect-timeout', '8', '--max-time', '30', '--max-filesize', str(limit),
                '--user-agent', UA, '--write-out', '\n__RIPPLE_META__%{json}', url]
        try:
            r = subprocess.run(args, capture_output=True, timeout=35)
            body, marker, meta = r.stdout.rpartition(MARK)
            if not marker: return {'status': 'pending_network', 'url': url, 'reason': 'No HTTP receipt'}
            m = json.loads(meta)
            fallback = None
            # A transport failure before any HTTP response is not an access denial.
            # Retry this one protocol error with HTTP/1.1; never retry 401/403/429.
            if r.returncode == 92 and int(m.get('http_code', 0)) == 0 and self.requests < 180:
                fallback = {'curl_exit': 92, 'http_status': 0, 'reason': 'HTTP2_transport_error_before_response'}
                time.sleep(1.0); self.last[host] = time.monotonic(); self.requests += 1
                r = subprocess.run(args[:-1] + ['--http1.1', url], capture_output=True, timeout=35)
                body, marker, meta = r.stdout.rpartition(MARK)
                if not marker: return {'status': 'pending_network', 'url': url, 'reason': 'No HTTP receipt after protocol fallback'}
                m = json.loads(meta)
            code = int(m.get('http_code', 0)); self.total += len(body)
            receipt = {'url': url, 'http_status': code, 'content_type': m.get('content_type'),
                       'redirect_url': m.get('redirect_url'), 'retrieved_at': now(), 'curl_exit': r.returncode}
            if fallback: receipt['transport_fallback'] = fallback
            if len(body) > limit or self.total > MAX_TOTAL: return dict(receipt, status='pending_limit')
            if code in (301, 302, 303, 307, 308): return dict(receipt, status='redirect')
            if code in (401, 403, 429): return dict(receipt, status='blocked_http')
            if code in (404, 410): return dict(receipt, status='unavailable_http')
            if code != 200 or r.returncode: return dict(receipt, status='pending_network')
            return dict(receipt, status='downloaded', body=body)
        except (subprocess.SubprocessError, ValueError):
            return {'status': 'pending_network', 'url': url, 'reason': 'Request failed within limits'}

    def allowed(self, url):
        p = urlsplit(url); origin = f'{p.scheme}://{p.netloc}'
        if origin not in self.robots:
            response = self.raw(origin + '/robots.txt', 1_000_000)
            redirects = []
            # Follow only bounded HTTPS redirects within the same publisher host.
            for _ in range(3):
                if response['status'] != 'redirect': break
                redirects.append({k: v for k, v in response.items() if k != 'body'})
                try: destination = safe_url(urljoin(response.get('url', origin + '/robots.txt'), response.get('redirect_url') or ''))
                except ValueError: break
                if urlsplit(destination).hostname.removeprefix('www.') != p.hostname.removeprefix('www.'): break
                response = self.raw(destination, 1_000_000)
            if redirects: response = dict(response, robots_redirect_chain=redirects)
            parser = None
            if response['status'] == 'downloaded':
                text = response['body'].decode('utf-8', errors='replace')
                if '<html' not in text[:500].lower():
                    parser = RobotFileParser(); parser.parse(text.splitlines())
            self.robots[origin] = (response, parser)
        r, parser = self.robots[origin]
        if r.get('http_status') in (404, 410): return True, 'robots_not_published'
        if parser is None: return False, 'robots_unavailable_manual_review'
        if not parser.can_fetch('RIPPLEResearch', url): return False, 'robots_disallowed'
        delay = parser.crawl_delay('RIPPLEResearch')
        if delay and delay > 10: return False, 'robots_crawl_delay_requires_scheduled_run'
        if delay: time.sleep(max(0, delay - (time.monotonic() - self.last.get(p.hostname, 0))))
        return True, 'robots_allowed'

    def get(self, url, allowed_hosts):
        original = safe_url(url)
        if original in self.cache: return self.cache[original]
        if self.offline: return {'status': 'pending_offline', 'url': original, 'reason': 'Offline mode prohibits network requests'}
        chain = []
        for _ in range(5):
            try: url = safe_url(url)
            except ValueError:
                r = {'status': 'blocked_unsafe_redirect', 'url': original, 'reason': 'Redirect leaves permitted HTTPS policy; not followed'}; break
            if urlsplit(url).hostname not in allowed_hosts:
                r = {'status': 'pending_redirect_host', 'url': url}; break
            ok, policy = self.allowed(url)
            if not ok: r = {'status': 'blocked_robots', 'url': url, 'reason': policy}; break
            r = self.raw(url); r['robots_policy'] = policy
            chain.append({k: v for k, v in r.items() if k != 'body'})
            if r['status'] != 'redirect': break
            url = urljoin(url, r['redirect_url'])
        else: r = {'status': 'pending_redirect_limit', 'url': url}
        if r.get('body') and not r['body'].startswith(b'%PDF'):
            prefix = r['body'][:15000].lower()
            if any(x in prefix for x in [b'<title>access denied', b'<title>just a moment',
                    b'unusual traffic', b'request rate threshold exceeded', b'verify you are human',
                    b'<title>robot', b'captcha-container']):
                r = {k: v for k, v in r.items() if k != 'body'}; r['status'] = 'blocked_challenge'
        r['original_url'] = original; r['redirect_chain'] = chain
        self.cache[original] = r
        return r
