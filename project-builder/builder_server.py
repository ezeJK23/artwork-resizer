"""
Project Builder – local app that turns a master layout guide into an Artwork Resizer project.
Run:  python3 builder_server.py      then open http://localhost:8766
"""
import json, os, sys, threading, uuid, shutil, urllib.parse, webbrowser, traceback, time, re
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'common'))
import auth  # noqa: E402
import importer  # noqa: E402

SIBLING = os.path.join(os.path.dirname(HERE), 'Artwork Resizer', 'projects')
PROJECTS_DIR = os.environ.get('PROJECTS_DIR') or (SIBLING if os.path.isdir(SIBLING) else os.path.join(HERE, 'projects'))
os.makedirs(PROJECTS_DIR, exist_ok=True)
JOBS_DIR = os.path.join(HERE, 'uploads')
os.makedirs(JOBS_DIR, exist_ok=True)
PORT = int(os.environ.get('PORT', 8766))
JOBS = {}
SAFE = re.compile(r'[^A-Za-z0-9._ \-()]+')


def job_dir(jid):
    d = os.path.join(JOBS_DIR, re.sub(r'[^a-f0-9]', '', jid))
    os.makedirs(os.path.join(d, 'links'), exist_ok=True)
    return d


def list_projects():
    out = []
    for d in sorted(os.listdir(PROJECTS_DIR)):
        pj = os.path.join(PROJECTS_DIR, d, 'project.json')
        if os.path.isfile(pj):
            data = json.load(open(pj))
            out.append(dict(id=d, name=data.get('name', d), layouts=len(data.get('layouts', [])),
                            guide=data.get('guide', ''), updated=os.path.getmtime(pj)))
    return sorted(out, key=lambda p: -p['updated'])


def summary(pid):
    pj = json.load(open(os.path.join(PROJECTS_DIR, pid, 'project.json')))
    lays = pj['layouts']
    linked = sum(1 for l in lays if pj['backgrounds'][l['background']].get('source') != 'guide')
    return dict(id=pid, name=pj['name'], layouts=len(lays),
                contexts=pj.get('context_labels', {}), versions=pj.get('language_labels', {}),
                ratio_span=[min(l['ratio_min'] for l in lays), max(l['ratio_max'] for l in lays)],
                linked=linked,
                items=[dict(id=l['id'], ratio=[l['ratio_min'], l['ratio_max']], page=l['guide_page'],
                            context=l['context'], version=l['language'], elements=len(l['elements']),
                            products=sum(1 for e in l['elements'] if e.get('role') == 'Product'),
                            picture=pj['backgrounds'][l['background']].get('source'),
                            preview=f"/projects/{pid}/previews/{l['id']}_guide.jpg") for l in lays])


def run_build(jid, name):
    job = JOBS[jid]
    d = job_dir(jid)
    guide = job.get('guide')

    def log(msg, progress):
        job['log'].append(msg)
        job['log'] = job['log'][-400:]
        if progress is not None:
            job['progress'] = progress
    try:
        has_links = any(True for _ in os.scandir(os.path.join(d, 'links')))
        pid, _ = importer.build_project(guide, os.path.join(d, 'links') if has_links else None, PROJECTS_DIR, name, importer.Log(log))
        job['result'] = summary(pid)
        job['state'] = 'done'
    except Exception as e:
        traceback.print_exc()
        job['state'] = 'error'
        job['error'] = str(e)
    finally:
        shutil.rmtree(d, ignore_errors=True)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=HERE, **k)

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def translate_path(self, path):
        p = urllib.parse.urlparse(path).path
        if p.startswith('/projects/'):
            rel = urllib.parse.unquote(p[len('/projects/'):])
            full = os.path.normpath(os.path.join(PROJECTS_DIR, rel))
            if full.startswith(os.path.normpath(PROJECTS_DIR)):
                return full
        return super().translate_path(path)

    def do_GET(self):
        if auth.handle(self, 'B', 'Project Builder'):
            return
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == '/':
            self.path = '/ui/index.html'
            return super().do_GET()
        if u.path == '/api/projects':
            return self._json(dict(projects=list_projects(), projects_dir=PROJECTS_DIR))
        if u.path == '/api/summary':
            return self._json(summary(q['id'][0]))
        if u.path == '/api/status':
            j = JOBS.get(q.get('job', [''])[0])
            if not j:
                return self._json(dict(error='Unknown job'), 404)
            return self._json({k: v for k, v in j.items() if k != 'guide'})
        if u.path.startswith('/ui/') or u.path.startswith('/projects/'):
            return super().do_GET()
        self.send_error(404)

    def do_POST(self):
        if auth.handle(self, 'B', 'Project Builder'):
            return
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path == '/api/new-job':
                jid = uuid.uuid4().hex
                JOBS[jid] = dict(state='uploading', progress=0, log=[], files=[])
                job_dir(jid)
                return self._json(dict(job=jid))
            if u.path == '/api/upload':
                jid = q['job'][0]; kind = q['kind'][0]
                name = SAFE.sub('_', os.path.basename(q['name'][0]))
                d = job_dir(jid)
                dest = os.path.join(d, 'guide.pdf') if kind == 'guide' else os.path.join(d, 'links', name)
                n = int(self.headers.get('Content-Length', 0))
                with open(dest, 'wb') as f:
                    while n > 0:
                        chunk = self.rfile.read(min(n, 1 << 20))
                        if not chunk:
                            break
                        f.write(chunk); n -= len(chunk)
                if kind == 'guide':
                    with open(dest, 'rb') as f:
                        if f.read(5) != b'%PDF-':
                            os.remove(dest)
                            return self._json(dict(error='The master guide must be a PDF file.'), 400)
                    JOBS[jid]['guide'] = dest
                JOBS[jid]['files'].append(dict(kind=kind, name=name))
                return self._json(dict(ok=True))
            if u.path == '/api/build':
                req = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
                jid = req['job']; name = (req.get('name') or '').strip()
                if not name:
                    return self._json(dict(error='Give the project a name.'), 400)
                if not JOBS.get(jid, {}).get('guide'):
                    return self._json(dict(error='Add the master guide PDF first.'), 400)
                JOBS[jid]['state'] = 'building'
                threading.Thread(target=run_build, args=(jid, name), daemon=True).start()
                return self._json(dict(ok=True))
            self.send_error(404)
        except Exception as e:
            traceback.print_exc()
            return self._json(dict(error=str(e)), 400)


if __name__ == '__main__':
    srv = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    url = f'http://localhost:{PORT}'
    print(f'Project Builder is running at {url}  (press Ctrl+C to stop)')
    print(f'Projects are saved to: {PROJECTS_DIR}')
    if os.environ.get('NO_BROWSER') != '1':
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
