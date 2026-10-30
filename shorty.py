"""shorty: one-file short-link service with a click counter (stdlib only)."""
import argparse, contextlib, hmac, json, os, re, secrets, sqlite3, string, sys, threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

CODE_RE = re.compile(r'[A-Za-z0-9_-]{3,32}')
ALPHA = string.ascii_letters + string.digits
SCHEMA = """CREATE TABLE IF NOT EXISTS links(code TEXT PRIMARY KEY, url TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS clicks(code TEXT NOT NULL, ts TEXT NOT NULL, referrer TEXT);
CREATE INDEX IF NOT EXISTS clicks_code ON clicks(code);"""


def valid_url(u):
    if not isinstance(u, str) or not u or len(u) > 2048:
        return False
    # printable ASCII only: a CR/LF or non-latin-1 char in Location would
    # split or break the 302 response (header injection, e.g. Set-Cookie)
    if any(not 0x21 <= ord(c) <= 0x7e for c in u):
        return False
    try:
        p = urlsplit(u)
        return p.scheme.lower() in ('http', 'https') and bool(p.hostname)
    except ValueError:
        return False


def clean_referer(r):
    """scheme://host[:port]/path; no userinfo, query or fragment; else None."""
    if not r:
        return None
    try:
        p = urlsplit(r.strip())
        port = p.port
    except ValueError:
        return None
    if p.scheme.lower() not in ('http', 'https') or not p.hostname:
        return None
    host = p.hostname
    if ':' in host:
        host = '[' + host + ']'
    return '%s://%s%s%s' % (p.scheme.lower(), host,
                            ':%d' % port if port is not None else '', p.path)


class Shorty(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, db, base, token):
        self.db, self.base, self.token = db, base.rstrip('/'), token
        self.lock = threading.Lock()
        with self.conn() as c:
            c.executescript(SCHEMA)
        super().__init__(addr, Handler)

    @contextlib.contextmanager
    def conn(self):
        c = sqlite3.connect(self.db, timeout=30)
        try:
            with c:
                yield c
        finally:
            c.close()

    def handle_error(self, request, client_address):
        pass  # never print tracebacks


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, status, obj=None, location=None):
        body = b'' if obj is None else json.dumps(obj).encode()
        self.send_response(status)
        if location:
            self.send_header('Location', location)
        if obj is not None:
            self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def authed(self):
        got = self.headers.get('Authorization', '')
        return hmac.compare_digest(got.encode('utf-8', 'replace'),
                                   ('Bearer ' + self.server.token).encode())

    def path_only(self):
        return self.path.split('?', 1)[0].split('#', 1)[0]

    def do_POST(self):
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = -1
        raw = self.rfile.read(n) if n > 0 else b''
        if self.path_only() != '/api/links':
            return self.reply(404, {'error': 'not found'})
        if not self.authed():
            return self.reply(401, {'error': 'unauthorized'})
        try:
            data = json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            data = None
        if not isinstance(data, dict) or not valid_url(data.get('url')):
            return self.reply(400, {'error': 'bad url'})
        code, gen = data.get('code'), data.get('code') is None
        if not gen and (not isinstance(code, str) or code == 'api'
                        or not CODE_RE.fullmatch(code)):
            return self.reply(400, {'error': 'bad code'})
        with self.server.lock, self.server.conn() as c:
            while True:
                if gen:
                    code = ''.join(secrets.choice(ALPHA) for _ in range(7))
                try:
                    c.execute('INSERT INTO links(code, url) VALUES (?, ?)',
                              (code, data['url']))
                    break
                except sqlite3.IntegrityError:
                    if not gen:
                        return self.reply(409, {'error': 'code taken'})
        self.reply(201, {'code': code, 'short': self.server.base + '/' + code})

    def do_GET(self):
        path = self.path_only()
        m = re.fullmatch(r'/api/links/([^/]+)/stats', path)
        if m:
            return self.stats(m.group(1))
        code = path[1:]
        if '/' in code or not CODE_RE.fullmatch(code) or code == 'api':
            return self.reply(404, {'error': 'not found'})
        with self.server.conn() as c:
            row = c.execute('SELECT url FROM links WHERE code=?', (code,)).fetchone()
            if row is None:
                return self.reply(404, {'error': 'not found'})
            ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
            c.execute('INSERT INTO clicks(code, ts, referrer) VALUES (?, ?, ?)',
                      (code, ts, clean_referer(self.headers.get('Referer'))))
        self.reply(302, location=row[0])

    def stats(self, code):
        if not self.authed():
            return self.reply(401, {'error': 'unauthorized'})
        with self.server.conn() as c:
            row = c.execute('SELECT url FROM links WHERE code=?', (code,)).fetchone()
            if row is None:
                return self.reply(404, {'error': 'not found'})
            clicks = c.execute('SELECT COUNT(*) FROM clicks WHERE code=?',
                               (code,)).fetchone()[0]
            by_day = dict(c.execute(
                'SELECT substr(ts, 1, 10), COUNT(*) FROM clicks WHERE code=? '
                'GROUP BY 1 ORDER BY 1', (code,)))
            top = [list(r) for r in c.execute(
                'SELECT referrer, COUNT(*) n FROM clicks WHERE code=? AND '
                'referrer IS NOT NULL GROUP BY referrer '
                'ORDER BY n DESC, referrer ASC LIMIT 10', (code,))]
        self.reply(200, {'url': row[0], 'clicks': clicks, 'by_day': by_day,
                         'top_referrers': top})


def main(argv=None):
    ap = argparse.ArgumentParser()
    for f in ('--db', '--host', '--port', '--base'):
        ap.add_argument(f, required=True, type=int if f == '--port' else str)
    a = ap.parse_args(argv)
    token = os.environ.get('SHORTY_TOKEN', '')
    if not token:
        sys.exit(2)
    srv = Shorty((a.host, a.port), a.db, a.base, token)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == '__main__':
    main()
