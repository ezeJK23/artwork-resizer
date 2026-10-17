"""
Sign-in and licence gate shared by Artwork Resizer and Project Builder.

* Accounts are stored on this computer (user id + salted PBKDF2 password hash).
  The first account created becomes the administrator; administrators can add or remove users.
* Every page and API call needs a valid licence for the app and a signed-in user.
"""
import hashlib, hmac, json, os, secrets, threading, time, urllib.parse, http.cookies, re
import licensing

USERS_FILE = os.path.join(licensing.config_dir(), 'users.json')
SESSION_HOURS = 12
_sessions = {}
_lock = threading.Lock()
_fails = {}
PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'auth_page.html')
UID_RE = re.compile(r'^[A-Za-z0-9._@\-]{3,40}$')


# ------------------------------------------------------------------ users
def _load():
    try:
        return json.load(open(USERS_FILE))
    except Exception:
        return {'users': {}}


def _save(data):
    tmp = USERS_FILE + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, USERS_FILE)


def _hash(pw, salt):
    return hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), bytes.fromhex(salt), 200_000).hex()


def has_users():
    return bool(_load()['users'])


def create_user(uid, pw, role='user'):
    uid = (uid or '').strip()
    if not UID_RE.match(uid):
        raise ValueError('User ID must be 3–40 characters: letters, numbers, dot, dash, underscore or @.')
    if len(pw or '') < 8:
        raise ValueError('Password must be at least 8 characters.')
    with _lock:
        data = _load()
        if uid.lower() in (u.lower() for u in data['users']):
            raise ValueError('That user ID is already taken.')
        salt = secrets.token_hex(16)
        data['users'][uid] = dict(salt=salt, hash=_hash(pw, salt), role=role, created=time.strftime('%Y-%m-%d'))
        _save(data)


def check_password(uid, pw):
    data = _load()
    for name, u in data['users'].items():
        if name.lower() == (uid or '').strip().lower():
            if hmac.compare_digest(u['hash'], _hash(pw or '', u['salt'])):
                return name, u['role']
            return None
    _hash(pw or '', '00' * 16)              # same timing for unknown users
    return None


def set_password(uid, pw):
    if len(pw or '') < 8:
        raise ValueError('Password must be at least 8 characters.')
    with _lock:
        data = _load()
        salt = secrets.token_hex(16)
        data['users'][uid].update(salt=salt, hash=_hash(pw, salt))
        _save(data)


def delete_user(uid, acting):
    with _lock:
        data = _load()
        if uid not in data['users']:
            raise ValueError('No such user.')
        if uid == acting:
            raise ValueError('You cannot remove your own account.')
        if data['users'][uid]['role'] == 'admin' and sum(1 for u in data['users'].values() if u['role'] == 'admin') == 1:
            raise ValueError('Keep at least one administrator.')
        del data['users'][uid]
        _save(data)


def list_users():
    return [dict(id=k, role=v['role'], created=v.get('created', '')) for k, v in sorted(_load()['users'].items())]


# ------------------------------------------------------------------ sessions
def _cookie_name(app_code):
    return f'ar_session_{app_code}'


def _session(handler, app_code):
    raw = handler.headers.get('Cookie', '')
    c = http.cookies.SimpleCookie()
    try:
        c.load(raw)
    except Exception:
        return None
    m = c.get(_cookie_name(app_code))
    if not m:
        return None
    with _lock:
        s = _sessions.get(m.value)
        if not s or s['exp'] < time.time():
            _sessions.pop(m.value, None)
            return None
        s['exp'] = time.time() + SESSION_HOURS * 3600
        role = next((u['role'] for u in list_users() if u['id'] == s['uid']), None)
        if role is None:
            _sessions.pop(m.value, None)
            return None
        return dict(uid=s['uid'], role=role, token=m.value)


def _start_session(uid):
    tok = secrets.token_urlsafe(32)
    with _lock:
        _sessions[tok] = dict(uid=uid, exp=time.time() + SESSION_HOURS * 3600)
    return tok


# ------------------------------------------------------------------ HTTP integration
def _send(handler, code, body, ctype='application/json', headers=None):
    if isinstance(body, (dict, list)):
        body = json.dumps(body).encode()
    elif isinstance(body, str):
        body = body.encode()
    handler.send_response(code)
    handler.send_header('Content-Type', ctype)
    handler.send_header('Content-Length', str(len(body)))
    handler.send_header('Cache-Control', 'no-store')
    for k, v in (headers or {}).items():
        handler.send_header(k, v)
    handler.end_headers()
    handler.wfile.write(body)


def _body(handler):
    try:
        return json.loads(handler.rfile.read(int(handler.headers.get('Content-Length', 0))) or b'{}')
    except Exception:
        return {}


def handle(handler, app_code, app_name):
    """Call first in do_GET / do_POST. Returns True when the request was answered here
    (sign-in pages, licence screens, redirects). Returns False when the request may go on."""
    u = urllib.parse.urlparse(handler.path)
    path = u.path
    method = handler.command
    lic = licensing.status(app_code)
    sess = _session(handler, app_code) if lic['valid'] else None

    if path == '/auth':
        html = open(PAGE, encoding='utf-8').read().replace('{{APP_NAME}}', app_name)
        _send(handler, 200, html, 'text/html; charset=utf-8')
        return True
    if path.startswith('/auth/'):
        try:
            return _api(handler, app_code, app_name, path, method, lic, sess)
        except ValueError as e:
            _send(handler, 400, dict(error=str(e)))
            return True

    if lic['valid'] and sess:
        handler.auth_user = sess
        return False
    # not allowed yet
    if path.startswith('/api/'):
        _send(handler, 401, dict(error='Please sign in again.', need='license' if not lic['valid'] else 'login'))
    else:
        _send(handler, 302, b'', 'text/plain', {'Location': '/auth'})
    return True


def _api(handler, app_code, app_name, path, method, lic, sess):
    if path == '/auth/state':
        _send(handler, 200, dict(app=app_name, license=lic, has_users=has_users(),
                                 user=dict(id=sess['uid'], role=sess['role']) if sess else None))
        return True
    if method != 'POST':
        _send(handler, 405, dict(error='Not allowed'))
        return True
    req = _body(handler)
    if path == '/auth/license':
        st = licensing.install(req.get('code', ''), app_code)
        _send(handler, 200, dict(license=st))
        return True
    if not lic['valid']:
        _send(handler, 403, dict(error=lic.get('reason', 'A valid licence is needed.'), need='license'))
        return True
    if path == '/auth/setup':
        if has_users():
            raise ValueError('An administrator account already exists. Sign in instead.')
        create_user(req.get('uid'), req.get('password'), 'admin')
        tok = _start_session(req['uid'].strip())
        _send(handler, 200, dict(ok=True), headers={'Set-Cookie': _cookie(app_code, tok)})
        return True
    if path == '/auth/login':
        key = handler.client_address[0]
        recent = [t for t in _fails.get(key, []) if t > time.time() - 300]
        if len(recent) >= 8:
            raise ValueError('Too many attempts. Wait 5 minutes and try again.')
        ok = check_password(req.get('uid'), req.get('password'))
        if not ok:
            _fails[key] = recent + [time.time()]
            raise ValueError('User ID or password is incorrect.')
        _fails.pop(key, None)
        tok = _start_session(ok[0])
        _send(handler, 200, dict(ok=True), headers={'Set-Cookie': _cookie(app_code, tok)})
        return True
    if not sess:
        _send(handler, 401, dict(error='Please sign in.', need='login'))
        return True
    if path == '/auth/logout':
        with _lock:
            _sessions.pop(sess['token'], None)
        _send(handler, 200, dict(ok=True), headers={'Set-Cookie': _cookie(app_code, '', expire=True)})
        return True
    if path == '/auth/password':
        if not check_password(sess['uid'], req.get('old')):
            raise ValueError('Your current password is incorrect.')
        set_password(sess['uid'], req.get('new'))
        _send(handler, 200, dict(ok=True))
        return True
    if path == '/auth/users':
        if sess['role'] != 'admin':
            raise ValueError('Only an administrator can manage users.')
        action = req.get('action', 'list')
        if action == 'add':
            create_user(req.get('uid'), req.get('password'), 'admin' if req.get('role') == 'admin' else 'user')
        elif action == 'delete':
            delete_user(req.get('uid'), sess['uid'])
        elif action == 'reset':
            set_password(req.get('uid'), req.get('password'))
        _send(handler, 200, dict(users=list_users()))
        return True
    _send(handler, 404, dict(error='Not found'))
    return True


def _cookie(app_code, tok, expire=False):
    c = f'{_cookie_name(app_code)}={tok}; Path=/; HttpOnly; SameSite=Strict'
    if expire:
        c += '; Max-Age=0'
    return c
