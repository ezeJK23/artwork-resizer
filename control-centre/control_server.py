"""
Control Centre – one place to run and manage everything on this Mac.

Back end (vendor):  issue / renew / check licence codes  (uses the private signing key)
Front end (apps):   start/stop Artwork Resizer and Project Builder, manage sign-in users,
                    this Mac's licence, projects and output files.

KEEP THIS FOLDER PRIVATE: it contains the licence signing key.
Run:  python3 control_server.py      then open http://localhost:8770
"""
import json, os, sys, shutil, socket, subprocess, threading, time, urllib.parse, webbrowser, traceback, secrets, hmac, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import manager_server as M          # noqa: E402  licence register, issuing, manager password
import licensing                    # noqa: E402
import auth                         # noqa: E402  sign-in users shared by the two apps
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

PARENT = os.path.dirname(HERE)
APPS = {
    'resizer': dict(name='Artwork Resizer', folder=os.path.join(PARENT, 'Artwork Resizer'), port=8765, code='R'),
    'builder': dict(name='Project Builder', folder=os.path.join(PARENT, 'Project Builder'), port=8766, code='B'),
}
PROJECTS = os.path.join(APPS['resizer']['folder'], 'projects')
REMOVED = os.path.join(APPS['resizer']['folder'], 'projects_removed')
OUTPUT = os.path.join(APPS['resizer']['folder'], 'Output')
LOGS = os.path.join(M.DATA, 'logs'); os.makedirs(LOGS, exist_ok=True)
PORT = int(os.environ.get('PORT', 8770))
PROCS = {}


# ------------------------------------------------------------------ apps
def port_open(port):
    s = socket.socket(); s.settimeout(0.3)
    try:
        return s.connect_ex(('127.0.0.1', port)) == 0
    finally:
        s.close()


def app_status():
    out = {}
    for key, a in APPS.items():
        p = PROCS.get(key)
        mine = p is not None and p.poll() is None
        installed = os.path.isdir(a['folder'])
        state = 'running' if port_open(a['port']) else ('starting' if mine else 'stopped')
        extra = ''
        if key == 'builder' and installed and not os.path.isfile(os.path.join(a['folder'], '.venv', '.ready')):
            extra = 'First start installs its image tools (1–3 minutes, needs internet).'
        out[key] = dict(name=a['name'], installed=installed, state=state, url=f"http://localhost:{a['port']}",
                        started_here=mine, note=extra, folder=a['folder'])
    return out


def start_app(key):
    a = APPS[key]
    if not os.path.isdir(a['folder']):
        raise ValueError(f"{a['name']} is not installed next to this folder.")
    if port_open(a['port']):
        return
    env = dict(os.environ, NO_BROWSER='1')
    log = open(os.path.join(LOGS, f'{key}.log'), 'a')
    if key == 'resizer':
        cmd = [sys.executable if os.path.basename(sys.executable).startswith('python') else 'python3', 'server.py']
    else:
        venv = os.path.join(a['folder'], '.venv', 'bin', 'python')
        if os.path.isfile(venv) and os.path.isfile(os.path.join(a['folder'], '.venv', '.ready')):
            cmd = [venv, 'builder_server.py']
        else:
            cmd = ['bash', 'Start Project Builder.command']      # installs the tools first, then runs
    PROCS[key] = subprocess.Popen(cmd, cwd=a['folder'], env=env, stdout=log, stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL, start_new_session=True)


def stop_app(key):
    p = PROCS.get(key)
    if p is not None and p.poll() is None:
        import signal
        try:
            os.killpg(p.pid, signal.SIGTERM)       # the whole group: launcher script + server
        except Exception:
            p.terminate()
        try:
            p.wait(5)
        except Exception:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except Exception:
                p.kill()
        PROCS.pop(key, None)
        return True
    if port_open(APPS[key]['port']):
        raise ValueError(f"{APPS[key]['name']} was started from its own Terminal window. Close that window to stop it.")
    return False


# ------------------------------------------------------------------ projects & files
def _size(path):
    t = 0
    for r, _, fs in os.walk(path):
        for f in fs:
            try:
                t += os.path.getsize(os.path.join(r, f))
            except OSError:
                pass
    return t


def list_projects():
    out = []
    if not os.path.isdir(PROJECTS):
        return out
    for d in sorted(os.listdir(PROJECTS)):
        pj = os.path.join(PROJECTS, d, 'project.json')
        if not os.path.isfile(pj):
            continue
        try:
            data = json.load(open(pj))
        except Exception:
            continue
        lays = data.get('layouts', [])
        bgs = data.get('backgrounds', {})
        linked = sum(1 for l in lays if bgs.get(l.get('background'), {}).get('source') not in (None, 'guide'))
        thumb = None
        if lays:
            mid = lays[len(lays) // 2]
            thumb = f"/projects/{d}/previews/{mid['id']}_guide.jpg"
        out.append(dict(id=d, name=data.get('name', d), guide=data.get('guide', ''), layouts=len(lays),
                        ratio=[min(l['ratio_min'] for l in lays), max(l['ratio_max'] for l in lays)] if lays else None,
                        versions=sorted({l['language'] for l in lays}),
                        sections=len({l['context'] for l in lays}), linked=linked,
                        size_mb=round(_size(os.path.join(PROJECTS, d)) / 1048576, 1),
                        updated=datetime.datetime.fromtimestamp(os.path.getmtime(pj)).strftime('%Y-%m-%d'),
                        thumb=thumb))
    return out


def rename_project(pid, name):
    name = (name or '').strip()
    if not name:
        raise ValueError('Enter a name.')
    pj = os.path.join(PROJECTS, os.path.basename(pid), 'project.json')
    data = json.load(open(pj)); data['name'] = name[:80]
    json.dump(data, open(pj, 'w'), indent=1)


def remove_project(pid):
    src = os.path.join(PROJECTS, os.path.basename(pid))
    if not os.path.isdir(src):
        raise ValueError('Project not found.')
    os.makedirs(REMOVED, exist_ok=True)
    dst = os.path.join(REMOVED, os.path.basename(pid) + time.strftime('-%Y%m%d-%H%M%S'))
    shutil.move(src, dst)
    return dst


def list_outputs():
    if not os.path.isdir(OUTPUT):
        return []
    rows = []
    for f in os.listdir(OUTPUT):
        p = os.path.join(OUTPUT, f)
        if os.path.isfile(p) and not f.startswith('.'):
            rows.append(dict(name=f, size_kb=round(os.path.getsize(p) / 1024),
                             modified=datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime('%Y-%m-%d %H:%M')))
    return sorted(rows, key=lambda r: r['modified'], reverse=True)[:200]


def open_in_finder(path):
    if sys.platform == 'darwin':
        subprocess.Popen(['open', path])
    elif os.name == 'nt':
        os.startfile(path)  # noqa
    else:
        raise ValueError('Opening folders is only available on the Mac.')


# ------------------------------------------------------------------ overview
def overview():
    rows = M.history()
    latest = {}
    for r in rows:
        k = r['licensee'].lower()
        if k not in latest or r['end'] > latest[k]['end']:
            latest[k] = r
    due = [r for r in latest.values() if r['days_left'] <= 30 and r['days_left'] >= -60]
    return dict(apps=app_status(),
                licences=dict(active=sum(1 for r in rows if r['state'] in ('Active', 'Ends soon')),
                              soon=sum(1 for r in rows if r['state'] == 'Ends soon'),
                              expired=sum(1 for r in rows if r['state'] == 'Expired'),
                              total=len(rows), customers=len(latest), due=sorted(due, key=lambda r: r['days_left'])),
                mac_licence={k: licensing.status(a['code']) for k, a in APPS.items()},
                users=len(auth.list_users()), projects=len(list_projects()), outputs=len(list_outputs()),
                folders=dict(projects=PROJECTS, output=OUTPUT, register=M.LOG, parent=PARENT))


# ------------------------------------------------------------------ HTTP
class H(M.H):
    def translate_path(self, path):
        p = urllib.parse.urlparse(path).path
        if p.startswith('/projects/'):
            full = os.path.normpath(os.path.join(PROJECTS, urllib.parse.unquote(p[len('/projects/'):])))
            if full.startswith(os.path.normpath(PROJECTS) + os.sep):
                return full
        return super().translate_path(path)

    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path
        if p == '/':
            self.path = '/ui/control.html'
            return SimpleHTTPRequestHandler.do_GET(self)
        if p.startswith('/projects/'):
            if not self._signed_in():
                return self.send_error(401)
            return SimpleHTTPRequestHandler.do_GET(self)
        routes = {'/api/overview': overview, '/api/users': lambda: dict(users=auth.list_users()),
                  '/api/projects': lambda: dict(projects=list_projects(), folder=PROJECTS),
                  '/api/outputs': lambda: dict(files=list_outputs(), folder=OUTPUT),
                  '/api/mac-licence': lambda: {k: licensing.status(a['code']) for k, a in APPS.items()}}
        if p in routes:
            if not self._signed_in():
                return self._json(dict(error='Please sign in.'), 401)
            try:
                return self._json(routes[p]())
            except Exception as e:
                traceback.print_exc()
                return self._json(dict(error=str(e)), 500)
        return super().do_GET()

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        extra = ('/api/apps', '/api/users', '/api/projects', '/api/mac-licence', '/api/open', '/api/manager-password')
        if p not in extra:
            return super().do_POST()
        if not self._signed_in():
            return self._json(dict(error='Please sign in.'), 401)
        try:
            req = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
            if p == '/api/apps':
                key = req.get('app')
                if key not in APPS:
                    raise ValueError('Unknown app.')
                if req.get('action') == 'start':
                    start_app(key)
                else:
                    stop_app(key)
                time.sleep(0.6)
                return self._json(dict(apps=app_status()))
            if p == '/api/users':
                a = req.get('action')
                if a == 'add':
                    auth.create_user(req.get('uid'), req.get('password'), 'admin' if req.get('role') == 'admin' else 'user')
                elif a == 'delete':
                    auth.delete_user(req.get('uid'), '__control_centre__')
                elif a == 'reset':
                    if not any(u['id'] == req.get('uid') for u in auth.list_users()):
                        raise ValueError('No such user.')
                    auth.set_password(req.get('uid'), req.get('password'))
                elif a == 'role':
                    _set_role(req.get('uid'), req.get('role'))
                return self._json(dict(users=auth.list_users()))
            if p == '/api/projects':
                if req.get('action') == 'rename':
                    rename_project(req.get('id'), req.get('name'))
                elif req.get('action') == 'remove':
                    remove_project(req.get('id'))
                return self._json(dict(projects=list_projects(), folder=PROJECTS))
            if p == '/api/mac-licence':
                licensing.install(req.get('code', ''), 'R' if 'R' in licensing.decode(req.get('code', ''))['product_codes'] else 'B')
                return self._json({k: licensing.status(a['code']) for k, a in APPS.items()})
            if p == '/api/open':
                what = req.get('what')
                path = {'projects': PROJECTS, 'output': OUTPUT, 'register': os.path.dirname(M.LOG),
                        'resizer': APPS['resizer']['folder'], 'builder': APPS['builder']['folder']}.get(what)
                if not path:
                    raise ValueError('Unknown folder.')
                os.makedirs(path, exist_ok=True)
                open_in_finder(path)
                return self._json(dict(ok=True))
            if p == '/api/manager-password':
                d = json.load(open(M.PWD))
                if not hmac.compare_digest(d['hash'], M._hash(req.get('old', ''), d['salt'])):
                    raise ValueError('Your current password is incorrect.')
                if len(req.get('new', '')) < 10:
                    raise ValueError('The new password needs at least 10 characters.')
                salt = secrets.token_hex(16)
                json.dump(dict(salt=salt, hash=M._hash(req['new'], salt)), open(M.PWD, 'w'))
                return self._json(dict(ok=True))
        except ValueError as e:
            return self._json(dict(error=str(e)), 400)
        except Exception as e:
            traceback.print_exc()
            return self._json(dict(error=str(e)), 500)


def _set_role(uid, role):
    role = 'admin' if role == 'admin' else 'user'
    with auth._lock:
        data = auth._load()
        if uid not in data['users']:
            raise ValueError('No such user.')
        if role == 'user' and data['users'][uid]['role'] == 'admin' and \
                sum(1 for u in data['users'].values() if u['role'] == 'admin') == 1:
            raise ValueError('Keep at least one administrator.')
        data['users'][uid]['role'] = role
        auth._save(data)


if __name__ == '__main__':
    if not os.path.isfile(M.KEY_FILE):
        print('private_key.hex is missing - licence codes cannot be created.'); sys.exit(1)
    srv = ThreadingHTTPServer(('127.0.0.1', PORT), H)
    url = f'http://localhost:{PORT}'
    print(f'Control Centre is running at {url}  (press Ctrl+C to stop)')
    if os.environ.get('NO_BROWSER') != '1':
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for k in list(PROCS):
            try:
                stop_app(k)
            except Exception:
                pass
