import http.client, json, os, sqlite3, subprocess, sys, tempfile, threading, time, unittest
import shorty

TOKEN = 'tok-123'
H = {'Authorization': 'Bearer ' + TOKEN}


class ShortyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, 's.db')
        self.srv = shorty.Shorty(('127.0.0.1', 0), self.db, 'http://s.example/', TOKEN)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown(); self.srv.server_close(); self.tmp.cleanup()

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        c.request(method, path, body=body, headers=headers or {})
        r = c.getresponse(); data = r.read(); c.close()
        self.assertIsNone(r.getheader('Set-Cookie'))
        return r.status, (json.loads(data) if data else None), r

    def make(self, url='https://ex.com/a', code=None):
        body = {'url': url} if code is None else {'url': url, 'code': code}
        return self.req('POST', '/api/links', body, H)

    def test_deep_nesting_is_400(self):
        deep = '[' * 100000 + ']' * 100000
        for body in [deep, '{"url": %s}' % deep, '{"url": "https://x.io", "code": %s}' % deep]:
            self.assertEqual(self.req('POST', '/api/links', body, H)[0], 400)

    def test_create_and_statuses(self):
        self.assertEqual(self.req('POST', '/api/links', {'url': 'https://x.io'})[0], 401)
        self.assertEqual(self.req('POST', '/api/links', {'url': 'https://x.io'},
                                  {'Authorization': 'Bearer no'})[0], 401)
        self.assertEqual(self.req('POST', '/api/links', 'nope', {'Authorization': 'Bearer no'})[0], 401)
        for bad in ['[1]', 'not json', '"s"', '{}', '{"url": 5}']:
            self.assertEqual(self.req('POST', '/api/links', bad, H)[0], 400, bad)
        for url in ['ftp://x.io', 'https://', 'x.io', 'http://' + 'a' * 2048,
                    'https://x.io/\r\nSet-Cookie: a=b']:
            self.assertEqual(self.make(url)[0], 400, url)
        for code in ['', 'ab', 'a' * 33, 'api', 'a b', 5, 'abc/d']:
            self.assertEqual(self.make(code=code)[0], 400, code)
        s, b, _ = self.make(code='abc')
        self.assertEqual((s, b), (201, {'code': 'abc', 'short': 'http://s.example/abc'}))
        self.assertEqual(self.make(code='abc')[0], 409)
        s, b, _ = self.req('POST', '/api/links', {'url': 'http://x.io', 'code': None}, H)
        self.assertEqual(s, 201); self.assertRegex(b['code'], r'^[A-Za-z0-9]{7}$')
        self.assertEqual(b['short'], 'http://s.example/' + b['code'])

    def test_redirect_and_stats(self):
        self.make('https://ex.com/a', 'abc')
        s, _, r = self.req('GET', '/abc')
        self.assertEqual((s, r.getheader('Location')), (302, 'https://ex.com/a'))
        self.assertEqual(self.req('GET', '/zzz')[0], 404)
        self.assertEqual(self.req('GET', '/api/links/abc/stats')[0], 401)
        self.assertEqual(self.req('GET', '/api/links/zzz/stats', headers=H)[0], 404)
        self.assertEqual(self.req('GET', '/api/links/zzz/stats')[0], 401)
        ref = 'https://user:PWSECRET9@a.example:8443/p?t=SECRET#x'
        for _ in range(3):
            self.assertEqual(self.req('GET', '/abc', headers={'Referer': ref})[0], 302)
        self.req('GET', '/abc', headers={'Referer': 'javascript:alert(1)'})
        s, b, _ = self.req('GET', '/api/links/abc/stats', headers=H)
        self.assertEqual(s, 200)
        self.assertEqual(b['clicks'], 5)
        self.assertEqual(sum(b['by_day'].values()), 5)
        self.assertEqual(b['top_referrers'], [['https://a.example:8443', 3]])
        for suffix in ('', '-wal', '-journal'):
            if os.path.exists(self.db + suffix):
                with open(self.db + suffix, 'rb') as fh:
                    self.assertNotIn(b'SECRET', fh.read())
        c = sqlite3.connect(self.db)
        for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            for col in c.execute('PRAGMA table_info(%s)' % t):
                for bad in ('ip', 'agent', 'cookie'):
                    self.assertNotIn(bad, col[1].lower())
        c.close()

    def test_top10_ties(self):
        self.make('https://ex.com', 'abc')
        for i, n in enumerate([1, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1]):
            for _ in range(n):
                self.req('GET', '/abc', headers={'Referer': 'http://r%02d.example/path/%d' % (i, i)})
        top = self.req('GET', '/api/links/abc/stats', headers=H)[1]['top_referrers']
        self.assertEqual(top[:2], [['http://r01.example', 2], ['http://r02.example', 2]])
        self.assertEqual(len(top), 10)
        self.assertEqual(top[2][0], 'http://r00.example')

    def test_clean_referer(self):
        f = shorty.clean_referer
        for bad in (None, '', 'ftp://a/b', 'http://a:99999/', 'javascript:alert(1)',
                    'http:///x', 'https://a\x01b.example/', 'https://' + 'a' * 300 + '/'):
            self.assertIsNone(f(bad), bad)
        self.assertEqual(f('HTTP://u:pw@A.Example/x;y?q#f'), 'http://a.example')
        self.assertEqual(f('https://a.example:8443/p;jsessionid=SECRET'), 'https://a.example:8443')
        self.assertEqual(f('https://a.example/reset/SECRET'), 'https://a.example')
        self.assertEqual(f('https://a.example/' + 'x' * 60000), 'https://a.example')
        self.assertEqual(f('https://a.example/p\x01'), 'https://a.example')
        self.assertEqual(f('https://a.example:443/x'), 'https://a.example')
        self.assertEqual(f('http://a.example:80'), 'http://a.example')
        self.assertEqual(f('http://[::1]:8080/x'), 'http://[::1]:8080')

    def test_no_path_reaches_db(self):
        self.make('https://ex.com', 'abc')
        for p in ('reset/SECRET', 'p;jsessionid=SECRET', 'SECRET' * 9999, 'SECRET\x01'):
            self.req('GET', '/abc', headers={'Referer': 'https://a.example/' + p})
        c = sqlite3.connect(self.db)
        self.assertEqual(c.execute('SELECT referrer, COUNT(*) FROM clicks GROUP BY 1')
                         .fetchall(), [('https://a.example', 4)])
        c.close()

    def test_cli_token_and_silence(self):
        env = dict(os.environ); env.pop('SHORTY_TOKEN', None)
        args = [sys.executable, shorty.__file__, '--db', self.db + '2', '--host',
                '127.0.0.1', '--port', '0', '--base', 'http://b']
        self.assertEqual(subprocess.run(args, env=env, capture_output=True).returncode, 2)
        env['SHORTY_TOKEN'] = ''
        self.assertEqual(subprocess.run(args, env=env, capture_output=True).returncode, 2)
        import socket
        s = socket.socket(); s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]; s.close()
        args[args.index('0')] = str(port)
        env['SHORTY_TOKEN'] = TOKEN
        p = subprocess.Popen(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for _ in range(100):
                try:
                    c = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
                    c.request('GET', '/nope'); c.getresponse().read(); break
                except OSError:
                    time.sleep(0.05)
            c = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
            c.request('POST', '/api/links', body='garbage', headers=H); c.getresponse().read()
        finally:
            p.terminate(); out, err = p.communicate(timeout=10)
        self.assertEqual((out, err), (b'', b''))


if __name__ == '__main__':
    unittest.main()
