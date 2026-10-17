"""
License Manager – vendor tool for issuing yearly licence codes for Artwork Resizer / Project Builder.
KEEP THIS FOLDER PRIVATE: it contains the signing key. Anyone with it can create licence codes.
Run:  python3 manager_server.py      then open http://localhost:8770
"""
import json, os, sys, csv, datetime, secrets, hashlib, hmac, threading, time, urllib.parse, http.cookies, webbrowser, traceback
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import licensing  # noqa: E402

DATA = os.path.join(HERE, 'data'); os.makedirs(DATA, exist_ok=True)
KEY_FILE = os.path.join(HERE, 'private_key.hex')
LOG = os.path.join(DATA, 'issued_licences.csv')
PWD = os.path.join(DATA, 'manager_password.json')
PORT = int(os.environ.get('PORT', 8770))
FIELDS = ['issued_on', 'id', 'licensee', 'email', 'products', 'start', 'end', 'notes', 'code']
SESS = {}


def private_key():
    return bytes.fromhex(open(KEY_FILE).read().strip())


def _hash(pw, salt):
    return hashlib.pbkdf2_hmac('sha256', pw.encode(), bytes.fromhex(salt), 200_000).hex()


def history():
    if not os.path.isfile(LOG):
        return []
    rows = list(csv.DictReader(open(LOG, newline='', encoding='utf-8')))
    today = datetime.date.today()
    for r in rows:
        end = datetime.date.fromisoformat(r['end']); start = datetime.date.fromisoformat(r['start'])
        days = (end - today).days
        r['days_left'] = days
        r['state'] = 'Not started' if today < start else ('Expired' if days < 0 else ('Ends soon' if days <= 30 else 'Active'))
    return list(reversed(rows))


def issue(req):
    licensee = (req.get('licensee') or '').strip()
    if not licensee:
        raise ValueError('Enter who the licence is for.')
    prods = ''.join(c for c in (req.get('products') or 'RB') if c in licensing.PRODUCTS)
    if not prods:
        raise ValueError('Choose at least one app.')
    start = datetime.date.fromisoformat(req.get('start') or datetime.date.today().isoformat())
    try:
        end = start.replace(year=start.year + 1) - datetime.timedelta(days=1)
    except ValueError:                                  # 29 February
        end = start + datetime.timedelta(days=364)
    lic_id = 'L' + start.strftime('%y%m') + '-' + secrets.token_hex(2).upper()
    code = licensing.make_code(private_key(), lic_id, licensee, start, end, prods)
    licensing.decode(code)                              # self-check with the apps' public key
    new = not os.path.isfile(LOG)
    with open(LOG, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(dict(issued_on=datetime.date.today().isoformat(), id=lic_id, licensee=licensee,
                        email=(req.get('email') or '').strip(), products=prods, start=start.isoformat(),
                        end=end.isoformat(), notes=(req.get('notes') or '').strip(), code=code))
    return dict(id=lic_id, licensee=licensee, start=start.isoformat(), end=end.isoformat(), products=prods, code=code)


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=HERE, **k)

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200, headers=None):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(b))); self.send_header('Cache-Control', 'no-store')
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers(); self.wfile.write(b)

    def _signed_in(self):
        c = http.cookies.SimpleCookie()
        try:
            c.load(self.headers.get('Cookie', ''))
        except Exception:
            return False
        m = c.get('lm_session')
        return bool(m and SESS.get(m.value, 0) > time.time())

    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path
        if p == '/':
            self.path = '/ui/index.html'; return super().do_GET()
        if p.startswith('/ui/'):
            return super().do_GET()
        if p == '/api/state':
            return self._json(dict(has_password=os.path.isfile(PWD), signed_in=self._signed_in(),
                                   key_ok=os.path.isfile(KEY_FILE), products=licensing.PRODUCTS))
        if p == '/api/history':
            if not self._signed_in():
                return self._json(dict(error='Please sign in.'), 401)
            return self._json(dict(rows=history(), log_file=LOG))
        self.send_error(404)

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        try:
            req = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
            if p == '/api/set-password':
                if os.path.isfile(PWD):
                    raise ValueError('A password is already set.')
                if len(req.get('password', '')) < 10:
                    raise ValueError('Use at least 10 characters.')
                salt = secrets.token_hex(16)
                json.dump(dict(salt=salt, hash=_hash(req['password'], salt)), open(PWD, 'w'))
                p = '/api/login'
            if p == '/api/login':
                d = json.load(open(PWD))
                if not hmac.compare_digest(d['hash'], _hash(req.get('password', ''), d['salt'])):
                    time.sleep(1)
                    raise ValueError('Wrong password.')
                tok = secrets.token_urlsafe(32); SESS[tok] = time.time() + 8 * 3600
                return self._json(dict(ok=True), headers={'Set-Cookie': f'lm_session={tok}; Path=/; HttpOnly; SameSite=Strict'})
            if not self._signed_in():
                return self._json(dict(error='Please sign in.'), 401)
            if p == '/api/issue':
                return self._json(issue(req))
            if p == '/api/check':
                return self._json(licensing.decode(req.get('code', '')))
            if p == '/api/logout':
                return self._json(dict(ok=True), headers={'Set-Cookie': 'lm_session=; Path=/; Max-Age=0'})
            self.send_error(404)
        except ValueError as e:
            return self._json(dict(error=str(e)), 400)
        except Exception as e:
            traceback.print_exc()
            return self._json(dict(error=str(e)), 500)


if __name__ == '__main__':
    if not os.path.isfile(KEY_FILE):
        print('private_key.hex is missing - licence codes cannot be created.'); sys.exit(1)
    srv = ThreadingHTTPServer(('127.0.0.1', PORT), H)
    url = f'http://localhost:{PORT}'
    print(f'License Manager is running at {url}  (press Ctrl+C to stop)')
    if os.environ.get('NO_BROWSER') != '1':
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
