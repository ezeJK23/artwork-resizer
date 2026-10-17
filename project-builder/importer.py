"""
Project Builder – turns a master layout guide (PDF exported from InDesign) into an
Artwork Resizer project.

Works with guides that show one layout per ratio ("Ratio: 0.75") or per ratio range
("Ratio: 0.71 -> 0.91"), with one or several versions per page (e.g. FR / UK).
Optional link images (TIF, JPG, PNG, PSD, Photoshop EPS) let the background be
reframed from the full picture instead of the guide's cropped copy.
"""
import os, re, io, json, base64, zlib, shutil, tempfile, unicodedata
import numpy as np
import cv2
import pdfplumber
import pypdfium2 as pdfium
from PIL import Image
from pypdf import PdfReader, PdfWriter, PageObject, Transformation
from pypdf.generic import (ContentStream, DecodedStreamObject, NameObject, NumberObject,
                           ArrayObject, DictionaryObject, StreamObject)

MM = 25.4 / 72
PAINT = {b'f', b'F', b'f*', b'S', b's', b'B', b'B*', b'b', b'b*'}
LANG_RE = re.compile(r'\b(FR|UK|EN|DE|IT|ES|PT|NL|CN|ZH|JP|JA|KR|KO|AR|RU|INT|TC|SC)\b')
RANGE_RE = re.compile(r'Ratio\s*:?\s*\[?\s*(\d+[.,]\d+)\s*\]?\s*(?:→|->|–|—|-|g|to|à|a)\s*\[?\s*(\d+[.,]\d+)', re.I)
SINGLE_RE = re.compile(r'Ratio\s*:?\s*\[?\s*(\d+[.,]\d+)\s*\]?', re.I)
IMG_EXT = ('.tif', '.tiff', '.jpg', '.jpeg', '.png', '.psd', '.eps', '.bmp')


def slug(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return re.sub(r'[^A-Za-z0-9]+', '-', s).strip('-').lower()[:60] or 'project'


def _num(s):
    return float(s.replace(',', '.'))


class Log:
    def __init__(self, cb=None):
        self.cb = cb or (lambda *a: None)
    def __call__(self, msg, progress=None):
        self.cb(msg, progress)


# ------------------------------------------------------------------ rendering (PDFium)
class Renderer:
    def __init__(self, path):
        self.doc = pdfium.PdfDocument(path)

    def page(self, index, dpi, crop=None, transparent=False, gray=False):
        """crop = (x0, top, x1, bottom) in pt, top-left origin."""
        pg = self.doc[index]
        W, H = pg.get_size()
        c = (0, 0, 0, 0)
        if crop:
            x0, t, x1, b = crop
            c = (max(0, x0), max(0, H - b), max(0, W - x1), max(0, t))
        im = pg.render(scale=dpi / 72.0, crop=c, fill_color=(0, 0, 0, 0) if transparent else (255, 255, 255, 255),
                       may_draw_forms=False).to_pil()
        if gray:
            return im.convert('L')
        return im.convert('RGBA' if transparent else 'RGB')

    @staticmethod
    def file_page(path, dpi, transparent=False):
        d = pdfium.PdfDocument(path)
        im = d[0].render(scale=dpi / 72.0, fill_color=(0, 0, 0, 0) if transparent else (255, 255, 255, 255),
                         may_draw_forms=False).to_pil()
        return im.convert('RGBA' if transparent else 'RGB')


# ------------------------------------------------------------------ link images
def load_link(path):
    """Return (rgb preview image, info for embedding in PDF) or None."""
    low = path.lower()
    try:
        if low.endswith('.eps'):
            d = open(path, 'rb').read()
            m = re.search(rb'%%BeginBinary:\s*(\d+)\r?\nbeginimage\r?\n', d)
            if not m:
                return None
            e = d.find(b'~>', m.end())
            jpg = base64.a85decode(d[m.end():e].replace(b'\r', b'').replace(b'\n', b''))
            im = Image.open(io.BytesIO(jpg)); im.load()
            if im.mode == 'CMYK':
                rgb = Image.eval(im, lambda v: 255 - v).convert('RGB')
                return rgb, dict(kind='dct_cmyk', data=jpg, w=im.width, h=im.height)
            return im.convert('RGB'), dict(kind='rgb', pixels=im.convert('RGB').tobytes(), icc=im.info.get('icc_profile'),
                                           w=im.width, h=im.height)
        im = Image.open(path); im.load()
        icc = im.info.get('icc_profile')
        if im.mode == 'CMYK':
            return im.convert('RGB'), dict(kind='cmyk', pixels=im.tobytes(), icc=icc, w=im.width, h=im.height)
        rgb = im.convert('RGB')
        return rgb, dict(kind='rgb', pixels=rgb.tobytes(), icc=icc, w=im.width, h=im.height)
    except Exception:
        return None


def write_image_pdf(info, out_path):
    w, h = info['w'], info['h']
    wr = PdfWriter()
    page = PageObject.create_blank_page(width=w, height=h)
    img = StreamObject()
    img.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'),
                NameObject('/Width'): NumberObject(w), NameObject('/Height'): NumberObject(h),
                NameObject('/BitsPerComponent'): NumberObject(8)})
    if info['kind'] == 'dct_cmyk':
        img[NameObject('/ColorSpace')] = NameObject('/DeviceCMYK')
        img[NameObject('/Filter')] = NameObject('/DCTDecode')
        img._data = info['data']
    else:
        n = 4 if info['kind'] == 'cmyk' else 3
        if info.get('icc'):
            prof = StreamObject(); prof[NameObject('/N')] = NumberObject(n)
            prof[NameObject('/Filter')] = NameObject('/FlateDecode'); prof._data = zlib.compress(info['icc'])
            img[NameObject('/ColorSpace')] = ArrayObject([NameObject('/ICCBased'), wr._add_object(prof)])
        else:
            img[NameObject('/ColorSpace')] = NameObject('/DeviceCMYK' if n == 4 else '/DeviceRGB')
        img[NameObject('/Filter')] = NameObject('/FlateDecode')
        img._data = zlib.compress(info['pixels'], 6)
    ref = wr._add_object(img)
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): DictionaryObject({NameObject('/BG'): ref})})
    cs = DecodedStreamObject(); cs.set_data(b'q %d 0 0 %d 0 0 cm /BG Do Q' % (w, h))
    page[NameObject('/Contents')] = wr._add_object(cs)
    wr.add_page(page)
    with open(out_path, 'wb') as f:
        wr.write(f)


def find_window(template_rgb, link_rgb):
    L = cv2.cvtColor(np.asarray(link_rgb), cv2.COLOR_RGB2GRAY).astype(np.float32)
    T = cv2.cvtColor(np.asarray(template_rgb), cv2.COLOR_RGB2GRAY).astype(np.float32)
    f = 400.0 / max(L.shape)
    Ls = cv2.resize(L, (max(1, int(L.shape[1] * f)), max(1, int(L.shape[0] * f))), interpolation=cv2.INTER_AREA)
    tw, th = T.shape[1], T.shape[0]
    best = (-2, None)
    for sw in np.geomspace(0.1, 1.0, 110):
        w = sw * Ls.shape[1]; h = w * th / tw
        if h > Ls.shape[0] or w < 10 or h < 10:
            continue
        Ts = cv2.resize(T, (int(round(w)), int(round(h))), interpolation=cv2.INTER_AREA)
        r = cv2.matchTemplate(Ls, Ts, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(r)
        if mx > best[0]:
            best = (mx, (loc[0] / f, loc[1] / f, Ts.shape[1] / f, Ts.shape[0] / f))
    if best[1] is None:
        return None, -1
    x, y, w, h = best[1]; score = best[0]
    for _ in range(2):
        cand = []
        for dw in np.linspace(0.97, 1.03, 13):
            W2 = w * dw; H2 = W2 * th / tw
            Ts = cv2.resize(T, (max(1, int(round(W2))), max(1, int(round(H2)))),
                            interpolation=cv2.INTER_AREA if W2 < tw else cv2.INTER_CUBIC)
            m = 12
            xa, ya = int(max(0, x - m)), int(max(0, y - m))
            xb, yb = int(min(L.shape[1], x + W2 + m)), int(min(L.shape[0], y + H2 + m))
            region = L[ya:yb, xa:xb]
            if region.shape[0] < Ts.shape[0] or region.shape[1] < Ts.shape[1]:
                continue
            r = cv2.matchTemplate(region, Ts, cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(r)
            cand.append((mx, (xa + loc[0], ya + loc[1], Ts.shape[1], Ts.shape[0])))
        if cand:
            score, (x, y, w, h) = max(cand)
    return (float(x), float(y), float(w), float(h)), float(score)


# ------------------------------------------------------------------ PDF content helpers
def save_single(page, path):
    wr = PdfWriter(); wr.add_page(page)
    p = wr.pages[0]
    try:
        data = p.get_contents().get_data()
        used = set(re.findall(rb'/([^\s/\[\]<>()]+)\s+Do', data))
        xo = p['/Resources'].get('/XObject')
        if xo is not None:
            xo = xo.get_object()
            for k in list(xo.keys()):
                if k[1:].encode() not in used:
                    del xo[k]
    except Exception:
        pass
    try:
        wr.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
    except TypeError:
        wr.compress_identical_objects(remove_identicals=True, remove_orphans=True)
    with open(path, 'wb') as f:
        wr.write(f)


def crop_page(src_page, x0, top, x1, btm, H):
    w, h = x1 - x0, btm - top
    p = PageObject.create_blank_page(width=w, height=h)
    p.merge_transformed_page(src_page, Transformation().translate(-x0, -(H - btm)), over=True, expand=False)
    data = p.get_contents().get_data()
    c = DecodedStreamObject(); c.set_data(b'q 0 0 %.4f %.4f re W n\n' % (w, h) + data + b'\nQ\n')
    p.replace_contents(c)
    if '/Annots' in p:
        del p['/Annots']
    return p


def split_ops(reader, page, bg_names, frames_pt):
    """overlay = page without the background images and without frame outlines;
    background = only the background images (with their clipping)."""
    xobj = page['/Resources'].get('/XObject', {}) if '/Resources' in page else {}
    def is_image(name):
        o = xobj.get(name)
        return o is not None and o.get_object().get('/Subtype') == '/Image'
    cs = ContentStream(page.get_contents(), reader)
    over, bg = [], []
    in_text = False
    path_rects = []
    for operands, op in cs.operations:
        # ---- overlay
        if op == b'Do' and operands[0] in bg_names:
            pass
        elif op in (b'S', b's') and len(path_rects) == 1 and _is_frame_rect(path_rects[0], frames_pt):
            over.append(([], b'n'))           # drop the guide's frame outline
        else:
            over.append((operands, op))
        if op == b're':
            path_rects.append([float(v) for v in operands])
        elif op in PAINT or op in (b'n', b'W', b'W*'):
            if op in PAINT or op == b'n':
                path_rects = []
        elif op in (b'm', b'l', b'c', b'v', b'y', b'h'):
            path_rects.append(None)
        # ---- background
        if op == b'BT':
            in_text = True; continue
        if op == b'ET':
            in_text = False; continue
        if in_text:
            continue
        if op in PAINT:
            bg.append(([], b'n')); continue
        if op in (b'sh', b'BI', b'ID', b'EI', b'gs'):
            continue
        if op == b'Do' and operands[0] not in bg_names:
            continue
        bg.append((operands, op))
    return over, bg


def _is_frame_rect(r, frames_pt):
    if r is None:
        return False
    w, h = abs(r[2]), abs(r[3])
    return any(abs(w - fw) < 3 and abs(h - fh) < 3 for fw, fh in frames_pt)


def page_with_ops(reader, page, ops):
    cs = ContentStream(page.get_contents(), reader)
    cs.operations = ops
    p = PageObject.create_blank_page(width=float(page.mediabox.width), height=float(page.mediabox.height))
    p[NameObject('/Resources')] = page['/Resources']
    p.replace_contents(cs)
    return p


# ------------------------------------------------------------------ analysis
def page_ratio(text):
    m = RANGE_RE.search(text)
    if m:
        a, b = _num(m.group(1)), _num(m.group(2))
        if 0.02 < a < 50 and 0.02 < b < 50 and b >= a:
            return a, b, True
    m = SINGLE_RE.search(text)
    if m:
        r = _num(m.group(1))
        if 0.02 < r < 50:
            return r - 0.005, r + 0.005, False
    return None


def detect_frames(rend, index, W, H):
    DPI = 100
    a = np.asarray(rend.page(index, DPI, gray=True))
    mask = (a < 235).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    out = []
    s = 72.0 / DPI
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w * s < 20 or h * s < 20:
            continue
        if x <= 1 or y <= 1 or x + w >= a.shape[1] - 1 or y + h >= a.shape[0] - 1:
            continue                                  # touches the page edge: navigation, not artwork
        fill = area / float(w * h)
        if fill < 0.6:
            continue                                  # outlines / text blocks, not a filled visual
        out.append([x * s, y * s, (x + w) * s, (y + h) * s])
    return out


def trim_frame(rend, index, x0, t, x1, btm):
    DPI, M = 600, 3.0
    im = rend.page(index, DPI, crop=(x0 - M, t - M, x1 + M, btm + M), gray=True)
    a = np.asarray(im).astype(int)
    def run(v):
        n = 0
        for x in v:
            if x > 245: n += 1
            else: break
        return n
    rows, cols = a.mean(1), a.mean(0); pad = 0.15
    ox, oy = x0 - M, t - M
    nx0 = ox + run(cols) * 72 / DPI + pad
    nx1 = ox + (len(cols) - run(cols[::-1])) * 72 / DPI - pad
    nt = oy + run(rows) * 72 / DPI + pad
    nb = oy + (len(rows) - run(rows[::-1])) * 72 / DPI - pad
    if max(abs(nx0 - x0), abs(nx1 - x1), abs(nt - t), abs(nb - btm)) < 4:
        return nx0, nt, nx1, nb
    return x0, t, x1, btm


def find_elements(rgba, W0, H0, product_boxes):
    sc = rgba.width / W0
    a = np.asarray(rgba)[:, :, 3] > 8
    band = max(1, int(round(1.5 * sc)))                # ignore anything hugging the frame edge
    edge = np.zeros_like(a); edge[:band, :] = edge[-band:, :] = True; edge[:, :band] = edge[:, -band:] = True
    a2 = a & ~edge
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, int(16 * sc)), max(3, int(9 * sc))))
    d = cv2.dilate(a2.astype(np.uint8), k)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(d, 8)
    boxes = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        sub = a[y:y + h, x:x + w] & (lab[y:y + h, x:x + w] == i)
        ys, xs = np.nonzero(sub)
        if len(xs) < 3:
            continue
        boxes.append([(x + xs.min()) / sc, (y + ys.min()) / sc, (x + xs.max() + 1) / sc, (y + ys.max() + 1) / sc])
    changed = True
    while changed:
        changed = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                A, B = boxes[i], boxes[j]
                if A[0] < B[2] + 1 and B[0] < A[2] + 1 and A[1] < B[3] + 1 and B[1] < A[3] + 1:
                    boxes[i] = [min(A[0], B[0]), min(A[1], B[1]), max(A[2], B[2]), max(A[3], B[3])]
                    boxes.pop(j); changed = True; break
            if changed:
                break
    out = []
    for b in sorted(boxes, key=lambda b: (b[1], b[0])):
        area = max(1e-6, (b[2] - b[0]) * (b[3] - b[1]))
        role = 'Text & logo'
        for p in product_boxes:
            ix = max(0, min(b[2], p[2]) - max(b[0], p[0])) * max(0, min(b[3], p[3]) - max(b[1], p[1]))
            if ix / area > 0.5:
                role = 'Product'; break
        out.append(dict(box=[round(v, 3) for v in b], role=role))
    return out


def heading(words, W, H):
    lines = {}
    for w in words:
        if w['top'] > H * 0.14:
            continue
        key = round(w['top'] / 3)
        lines.setdefault(key, []).append(w)
    best = ''
    for ws in lines.values():
        t = ' '.join(x['text'] for x in sorted(ws, key=lambda x: x['x0']))
        if len(t) > len(best) and not SINGLE_RE.search(t):
            best = t
    return best.strip()


def version_label(words, frame, n_frames, idx):
    """Language/version label: the closest text line above the frame that names a language."""
    x0, t, x1, b = frame
    lines = {}
    for w in words:
        if t - 160 <= w['bottom'] <= t + 1 and w['x1'] > x0 - 20 and w['x0'] < x1 + 20:
            lines.setdefault(round(w['bottom']), []).append(w['text'])
    for bottom in sorted(lines, reverse=True):
        m = LANG_RE.search(' '.join(lines[bottom]).upper())
        if m:
            return m.group(1)
    return 'Default' if n_frames == 1 else f'Version {idx + 1}'


# ------------------------------------------------------------------ main entry
def build_project(guide_path, links_dir, projects_dir, name, log=None):
    log = log or Log()
    pid = slug(name)
    out = os.path.join(projects_dir, pid)
    tmp_out = out + '.building'
    shutil.rmtree(tmp_out, ignore_errors=True)
    for d in ('overlays', 'backgrounds', 'previews'):
        os.makedirs(os.path.join(tmp_out, d), exist_ok=True)
    tmpdir = tempfile.mkdtemp()

    log('Reading the guide…', 0)
    plumb = pdfplumber.open(guide_path)
    reader = PdfReader(guide_path)
    rend = Renderer(guide_path)
    n_pages = len(plumb.pages)

    # links
    links = {}
    if links_dir and os.path.isdir(links_dir):
        files = [os.path.join(r, f) for r, _, fs in os.walk(links_dir) for f in fs if f.lower().endswith(IMG_EXT)]
        for i, f in enumerate(sorted(files)):
            log(f'Loading picture {os.path.basename(f)}…', 0)
            got = load_link(f)
            if got:
                rgb, info = got
                links[os.path.basename(f)] = dict(rgb=rgb, info=info, written=False, path=f)
        log(f'{len(links)} link picture(s) loaded.', 0)

    project = dict(name=name, guide=os.path.basename(guide_path), layouts=[], backgrounds={}, contexts={}, languages={})
    ratio_pages = 0
    for pi in range(n_pages):
        pl = plumb.pages[pi]
        try:
            text = pl.dedupe_chars().extract_text() or ''
        except Exception:
            text = pl.extract_text() or ''
        rr = page_ratio(text)
        if not rr:
            continue
        lo, hi, is_range = rr
        W, H = float(pl.width), float(pl.height)
        frames = detect_frames(rend, pi, W, H)
        if not frames:
            log(f'Page {pi + 1}: ratio found but no artwork frame, skipped.', (pi + 1) / n_pages)
            continue
        words = pl.dedupe_chars().extract_words()
        ctx_label = heading(words, W, H) or 'Main'
        ctx = slug(ctx_label)[:40] or 'main'
        project['contexts'][ctx] = ctx_label
        images = [im for im in pl.images]
        # order frames: rows top->bottom, then left->right
        frames.sort(key=lambda f: (round(f[1] / 40), f[0]))
        snapped, bg_names = [], set()
        for fr in frames:
            best, best_ov = None, 0
            for im in images:
                ib = [float(im['x0']), float(im['top']), float(im['x1']), float(im['bottom'])]
                ix = max(0, min(ib[2], fr[2]) - max(ib[0], fr[0])) * max(0, min(ib[3], fr[3]) - max(ib[1], fr[1]))
                cover = ix / max(1e-6, (fr[2] - fr[0]) * (fr[3] - fr[1]))
                if cover > best_ov:
                    best, best_ov = (im, ib), cover
            if best and best_ov > 0.85:
                snapped.append((fr, best[1], '/' + best[0]['name']))
                bg_names.add('/' + best[0]['name'])
            # frames without a placed picture are icons/decoration, not artwork
        if not snapped:
            continue
        ratio_pages += 1
        frames_pt = [(f[1][2] - f[1][0], f[1][3] - f[1][1]) for f in snapped]
        page = reader.pages[pi]
        over_ops, bg_ops = split_ops(reader, page, bg_names, frames_pt)
        over_page = page_with_ops(reader, page, over_ops)
        bg_page = page_with_ops(reader, page, bg_ops)
        bg_tmp = os.path.join(tmpdir, f'bg_{pi}.pdf'); save_single(bg_page, bg_tmp)
        bg_rend = Renderer(bg_tmp)

        for fi, (fr, img_box, bg_name) in enumerate(snapped):
            x0, t, x1, btm = trim_frame(rend, pi, *img_box)
            W0, H0 = x1 - x0, btm - t
            lang = version_label(words, fr, len(snapped), fi)
            project['languages'][lang] = lang
            rlabel = f'{lo:.2f}-{hi:.2f}' if is_range else f'{(lo + hi) / 2:.2f}'
            lid = f'{ctx}_{slug(lang)}_{rlabel}_p{pi + 1}'
            # product images: other placed images inside this frame
            prods = []
            for im in images:
                if '/' + im['name'] == bg_name:
                    continue
                ib = [float(im['x0']) - x0, float(im['top']) - t, float(im['x1']) - x0, float(im['bottom']) - t]
                if ib[2] > 0 and ib[0] < W0 and ib[3] > 0 and ib[1] < H0:
                    prods.append(ib)

            # ---- background
            bg_entry = None
            if bg_name and links:
                tpl = bg_rend.page(0, 150, crop=tuple(img_box))
                best = (-1, None, None)
                for lname, L in links.items():
                    win, score = find_window(tpl, L['rgb'])
                    if win and score > best[0]:
                        best = (score, lname, win)
                if best[0] > 0.75:
                    score, lname, (wx, wy, ww, wh) = best
                    L = links[lname]; bname = os.path.splitext(lname)[0]
                    if not L['written']:
                        write_image_pdf(L['info'], os.path.join(tmp_out, 'backgrounds', bname + '.pdf'))
                        prev = L['rgb'].copy(); prev.thumbnail((2400, 2400))
                        prev.save(os.path.join(tmp_out, 'backgrounds', bname + '.jpg'), quality=88)
                        L['written'] = True
                        project['backgrounds'][bname] = dict(
                            source=lname, width_px=L['info']['w'], height_px=L['info']['h'],
                            colour={'dct_cmyk': 'CMYK', 'cmyk': 'CMYK'}.get(L['info']['kind'], 'RGB'),
                            preview_scale=prev.width / L['info']['w'], px_per_unit=1.0)
                    kx = ww / (img_box[2] - img_box[0]); ky = wh / (img_box[3] - img_box[1])
                    win = [wx + (x0 - img_box[0]) * kx, wy + (t - img_box[1]) * ky, W0 * kx, H0 * ky]
                    bg_entry = dict(background=bname, window_px=[round(v, 3) for v in win], match_score=round(score, 4))
            if bg_entry is None:
                # use the guide's own picture, cropped to the frame
                bname = lid + '_bg'
                bgp = crop_page(bg_page, x0, t, x1, btm, H)
                save_single(bgp, os.path.join(tmp_out, 'backgrounds', bname + '.pdf'))
                prev = bg_rend.page(0, 150, crop=(x0, t, x1, btm))
                prev.save(os.path.join(tmp_out, 'backgrounds', bname + '.jpg'), quality=88)
                native = 1.0
                for im in images:
                    if '/' + im['name'] == bg_name:
                        native = im['srcsize'][0] / max(1e-6, float(im['x1']) - float(im['x0']))
                project['backgrounds'][bname] = dict(source='guide', width_px=W0, height_px=H0,
                                                     colour='as in guide', preview_scale=prev.width / W0,
                                                     px_per_unit=native)
                bg_entry = dict(background=bname, window_px=[0, 0, W0, H0], match_score=None)

            # ---- overlay
            ov = crop_page(over_page, x0, t, x1, btm, H)
            ov_rel = f'overlays/{lid}.pdf'
            save_single(ov, os.path.join(tmp_out, ov_rel))
            rgba = Renderer.file_page(os.path.join(tmp_out, ov_rel), 288, transparent=True)
            rgba.save(os.path.join(tmp_out, 'overlays', lid + '.png'))
            elements = find_elements(rgba, W0, H0, prods)
            ref = rend.page(pi, 150, crop=(x0, t, x1, btm))
            ref.save(os.path.join(tmp_out, 'previews', lid + '_guide.jpg'), quality=85)

            project['layouts'].append(dict(
                id=lid, context=ctx, language=lang, ratio_min=round(lo, 4), ratio_max=round(hi, 4),
                guide_page=pi + 1, ref_width_pt=round(W0, 4), ref_height_pt=round(H0, 4), ref_ratio=round(W0 / H0, 4),
                overlay_pdf=ov_rel, overlay_png=f'overlays/{lid}.png', elements=elements, **bg_entry))
        log(f'Page {pi + 1}: {len(snapped)} layout(s), ratio {lo:.2f}–{hi:.2f}', (pi + 1) / n_pages)

    if not project['layouts']:
        shutil.rmtree(tmp_out, ignore_errors=True)
        raise ValueError('No layouts found. The guide needs pages with a "Ratio" label and the artwork drawn on the page.')
    project['context_labels'] = project.pop('contexts')
    project['language_labels'] = project.pop('languages')
    json.dump(project, open(os.path.join(tmp_out, 'project.json'), 'w'), indent=1)
    shutil.rmtree(out, ignore_errors=True)
    os.replace(tmp_out, out)
    shutil.rmtree(tmpdir, ignore_errors=True)
    log(f'Done: {len(project["layouts"])} layouts from {ratio_pages} pages.', 1)
    return pid, project
