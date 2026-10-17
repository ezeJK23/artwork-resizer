"""
Artwork Resizer – local app.
Run:  python3 server.py      then open http://localhost:8765
"""
import json, os, sys, subprocess, threading, webbrowser, urllib.parse, datetime, traceback
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'vendor'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'common'))
import auth  # noqa: E402
import engine  # noqa: E402

PROJECTS_DIR = os.path.join(HERE, 'projects')
OUTPUT_DIR = os.path.join(HERE, 'Output')
os.makedirs(OUTPUT_DIR, exist_ok=True)
PORT = int(os.environ.get('PORT', 8765))
_projects = {}
_lock = threading.Lock()


def project(pid):
    with _lock:
        if pid not in _projects:
            _projects[pid] = engine.Project(os.path.join(PROJECTS_DIR, pid))
        return _projects[pid]


def list_projects():
    out = []
    for d in sorted(os.listdir(PROJECTS_DIR)):
        pj = os.path.join(PROJECTS_DIR, d, 'project.json')
        if os.path.isfile(pj):
            data = json.load(open(pj))
            out.append(dict(id=d, name=data.get('name', d)))
    return out


def make_plan(req):
    pr = project(req['project'])
    unit, dpi = req.get('unit', 'mm'), float(req.get('dpi') or 300)
    W = engine.to_pt(req['width'], unit, dpi)
    H = engine.to_pt(req['height'], unit, dpi)
    b = engine.to_pt(req.get('bleed') or 0, 'mm')
    if W <= 0 or H <= 0:
        raise ValueError('Width and height must be more than 0.')
    p = engine.plan(pr, W, H, b, req['context'], req['language'])
    return pr, p


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

    def do_GET(self):
        if auth.handle(self, 'R', 'Artwork Resizer'):
            return
        path = urllib.parse.urlparse(self.path).path
        if path == '/':
            self.path = '/ui/index.html'
            return super().do_GET()
        if path == '/api/projects':
            return self._json(list_projects())
        if path.startswith('/api/project/'):
            pid = path.split('/')[-1]
            pr = project(pid)
            lo, hi = pr.ratio_span()
            return self._json(dict(id=pid, name=pr.data['name'], contexts=pr.contexts(), languages=pr.languages(),
                                   context_labels=pr.data.get('context_labels', {}), language_labels=pr.data.get('language_labels', {}),
                                   ratio_span=[lo, hi], backgrounds=pr.data['backgrounds'],
                                   layouts=[{k: l[k] for k in ('id', 'context', 'language', 'ratio_min', 'ratio_max',
                                                               'ref_ratio', 'ref_width_pt', 'ref_height_pt', 'guide_page')}
                                            for l in pr.layouts], output_dir=OUTPUT_DIR))
        if path.startswith('/projects/') or path.startswith('/ui/'):
            return super().do_GET()
        self.send_error(404)

    def do_POST(self):
        if auth.handle(self, 'R', 'Artwork Resizer'):
            return
        path = urllib.parse.urlparse(self.path).path
        try:
            req = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
            if path == '/api/plan':
                _, p = make_plan(req)
                return self._json(p)
            if path == '/api/generate':
                results = []
                for item in req.get('items', [req]):
                    item = {**req, **item}; item.pop('items', None)
                    pr, p = make_plan(item)
                    name = engine.file_name(p, item['context'], item['language'], float(item['width']),
                                            float(item['height']), item.get('unit', 'mm'),
                                            job=pr.data.get('job_code') or item['project'])
                    out_dir = req.get('output_dir') or OUTPUT_DIR
                    os.makedirs(out_dir, exist_ok=True)
                    path_out = os.path.join(out_dir, name)
                    engine.build(pr, p, path_out, title=name[:-3])
                    results.append(dict(file=name, path=path_out, layout=p['layout'], ratio=p['ratio'],
                                        warnings=p['warnings'], size_kb=round(os.path.getsize(path_out) / 1024)))
                return self._json(dict(results=results))
            if path == '/api/open-output':
                folder = req.get('output_dir') or OUTPUT_DIR
                if sys.platform == 'darwin':
                    subprocess.Popen(['open', folder])
                elif os.name == 'nt':
                    os.startfile(folder)  # noqa
                return self._json(dict(ok=True))
            self.send_error(404)
        except Exception as e:
            traceback.print_exc()
            return self._json(dict(error=str(e)), 400)


if __name__ == '__main__':
    srv = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    url = f'http://localhost:{PORT}'
    print(f'Artwork Resizer is running at {url}  (press Ctrl+C to stop)')
    if os.environ.get('NO_BROWSER') != '1':
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
