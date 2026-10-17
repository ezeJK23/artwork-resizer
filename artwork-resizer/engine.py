"""
Artwork Resizer – layout engine.

Takes a prepared project (project.json + overlays + backgrounds) and a target size,
picks the layout the master guide defines for that ratio, and builds the artwork:
  * background = the link image, framed exactly like the guide's reference layout
  * overlay elements (logo, titles, claims, legal lines) = vector artwork copied from
    the guide, scaled and pinned to the same edges as in the guide
Output is a vector PDF saved with an .ai extension (opens and edits in Illustrator).
Colour data is copied untouched from the guide and the link images.
"""
import json, os, re, datetime
from pypdf import PdfReader, PdfWriter, PageObject, Transformation
from pypdf.generic import (DecodedStreamObject, NameObject, ArrayObject, FloatObject,
                           DictionaryObject, TextStringObject)

PT_PER = {'mm': 72 / 25.4, 'cm': 72 / 2.54, 'in': 72.0, 'pt': 1.0}


def to_pt(value, unit, dpi=300):
    if unit == 'px':
        return float(value) * 72.0 / float(dpi)
    return float(value) * PT_PER[unit]


class Project:
    def __init__(self, folder):
        self.folder = folder
        self.data = json.load(open(os.path.join(folder, 'project.json')))
        self.layouts = self.data['layouts']
        self._readers = {}

    def reader(self, rel):
        if rel not in self._readers:
            self._readers[rel] = PdfReader(os.path.join(self.folder, rel))
        return self._readers[rel]

    def contexts(self):
        return sorted({l['context'] for l in self.layouts})

    def languages(self):
        return sorted({l['language'] for l in self.layouts})

    def ratio_span(self):
        return min(l['ratio_min'] for l in self.layouts), max(l['ratio_max'] for l in self.layouts)

    def pick_layout(self, ratio, context, language):
        cands = [l for l in self.layouts if l['context'] == context and l['language'] == language]
        inside = [l for l in cands if l['ratio_min'] - 0.005 <= ratio <= l['ratio_max'] + 0.005]
        if inside:
            return min(inside, key=lambda l: abs(l['ref_ratio'] - ratio)), True
        return min(cands, key=lambda l: min(abs(ratio - l['ratio_min']), abs(ratio - l['ratio_max']))), False


def plan(project, width_pt, height_pt, bleed_pt, context, language):
    """Work out every placement. All output coordinates are in points, origin top-left of the
    full sheet (trim + bleed)."""
    W, H, b = float(width_pt), float(height_pt), float(bleed_pt)
    ratio = W / H
    lay, in_range = project.pick_layout(ratio, context, language)
    W0, H0 = lay['ref_width_pt'], lay['ref_height_pt']
    s = min(W / W0, H / H0)                       # one scale for the whole composition
    PW, PH = W + 2 * b, H + 2 * b
    warnings = []
    lo, hi = project.ratio_span()
    if not (lo - 0.005 <= ratio <= hi + 0.005):
        warnings.append(f'Ratio {ratio:.2f} is outside the guide ({lo:.2f}–{hi:.2f}). The closest layout is used; check with the brand before printing.')
    elif not in_range:
        warnings.append(f"Ratio {ratio:.2f} falls between two guide ranges; using {lay['ratio_min']:.2f}–{lay['ratio_max']:.2f}.")

    # ---- background window in link pixels
    bg = project.data['backgrounds'][lay['background']]
    lw, lh = bg['width_px'], bg['height_px']
    wx, wy, ww, wh = lay['window_px']
    k = ww / W0                                   # link px per reference pt
    cx, cy = wx + ww / 2, wy + wh / 2             # keep the guide's framing centre
    nw, nh = PW / s * k, PH / s * k
    zoom = 1.0
    if nw > lw or nh > lh:                        # not enough picture: enlarge just enough
        zoom = max(nw / lw, nh / lh)
        nw, nh = nw / zoom, nh / zoom
        if zoom > 1.01:
            warnings.append(f'The picture had to be enlarged {100 * (zoom - 1):.1f}% to fill this size.')
    nx = min(max(cx - nw / 2, 0), lw - nw)
    ny = min(max(cy - nh / 2, 0), lh - nh)
    shift = ((nx + nw / 2 - cx) / k * s, (ny + nh / 2 - cy) / k * s)
    if max(abs(shift[0]), abs(shift[1])) > 0.5:
        warnings.append(f'The picture was shifted {abs(shift[0]) * 25.4 / 72:.1f} mm / {abs(shift[1]) * 25.4 / 72:.1f} mm to stay inside the image edges.')
    g = PW / nw                                   # output pt per link px
    ppi = 72.0 * bg.get('px_per_unit', 1.0) / g
    if ppi < 250:
        warnings.append(f'Picture resolution at this size is {ppi:.0f} ppi (print needs about 300). '
                        'Swap the low-res links for the high-res files before final output.')

    # ---- overlay elements, pinned like the guide
    els = []
    for i, e in enumerate(lay['elements']):
        x0, y0, x1, y1 = e['box']
        e = dict(e, h_anchor=_anchor(x0, x1, W0, 'left', 'right', 'center'),
                 v_anchor=_anchor(y0, y1, H0, 'top', 'bottom', 'middle'))
        ew, eh = (x1 - x0) * s, (y1 - y0) * s
        if e['h_anchor'] == 'left':
            nx0 = x0 * s
        elif e['h_anchor'] == 'right':
            nx0 = W - (W0 - x1) * s - ew
        else:
            nx0 = W / 2 + ((x0 + x1) / 2 - W0 / 2) * s - ew / 2
        if e['v_anchor'] == 'top':
            ny0 = y0 * s
        elif e['v_anchor'] == 'bottom':
            ny0 = H - (H0 - y1) * s - eh
        else:
            ny0 = H / 2 + ((y0 + y1) / 2 - H0 / 2) * s - eh / 2
        els.append(dict(index=i, src_box=e['box'], box=[b + nx0, b + ny0, b + nx0 + ew, b + ny0 + eh],
                        h_anchor=e['h_anchor'], v_anchor=e['v_anchor'], role=e.get('role', 'Text & logo')))

    exact = abs(ratio - lay['ref_ratio']) < 0.0005
    return dict(layout=lay['id'], guide_page=lay['guide_page'], ratio=round(ratio, 4),
                ref_ratio=lay['ref_ratio'], ratio_range=[lay['ratio_min'], lay['ratio_max']],
                exact_reference=exact, scale=s, trim=[W, H], bleed=b, sheet=[PW, PH],
                background=dict(name=lay['background'], window=[nx, ny, nw, nh], link_size=[lw, lh],
                                pt_per_px=g, zoom=zoom, colour=bg['colour'], effective_ppi=round(ppi)),
                elements=els, ref_size=[W0, H0], overlay_png=lay['overlay_png'],
                guide_preview=f"previews/{lay['id']}_guide.jpg", warnings=warnings)


EDGE = 0.12   # elements this close to an edge stay pinned to it; the rest move with the picture


def _anchor(a0, a1, size, near, far, mid):
    if a1 - a0 > 0.6 * size:          # spans most of the frame: keep it centred
        return mid
    if a0 <= EDGE * size and size - a1 > a0:
        return near
    if size - a1 <= EDGE * size:
        return far
    return mid


def _clip_wrap(page, rect_pdf):
    x, y, w, h = rect_pdf
    data = page.get_contents().get_data() if page.get_contents() is not None else b''
    c = DecodedStreamObject()
    c.set_data(b'q %.4f %.4f %.4f %.4f re W n\n' % (x, y, w, h) + data + b'\nQ\n')
    page.replace_contents(c)


def _layer_wrap(page, tag):
    data = page.get_contents().get_data()
    c = DecodedStreamObject()
    c.set_data(b'/OC /%s BDC\n' % tag.encode() + data + b'\nEMC\n')
    page.replace_contents(c)


def build(project, p, out_path, title='Artwork'):
    lay = next(l for l in project.layouts if l['id'] == p['layout'])
    PW, PH = p['sheet']; W, H = p['trim']; b = p['bleed']; s = p['scale']
    W0, H0 = p['ref_size']
    out = PageObject.create_blank_page(width=PW, height=PH)
    layers = []

    # background
    bg_reader = project.reader(f"backgrounds/{p['background']['name']}.pdf")
    bg_page = bg_reader.pages[0]
    nx, ny, nw, nh = p['background']['window']; lh = p['background']['link_size'][1]
    g = p['background']['pt_per_px']
    tmp = PageObject.create_blank_page(width=PW, height=PH)
    tmp.merge_transformed_page(bg_page, Transformation().scale(g, g).translate(-g * nx, PH - g * (lh - ny)), expand=False)
    _clip_wrap(tmp, (0, 0, PW, PH))
    layers.append(('Background', tmp))

    # overlay elements
    ov_page = project.reader(lay['overlay_pdf']).pages[0]
    names = _element_names(p['elements'], H0)
    for e, name in zip(p['elements'], names):
        sx0, sy0, sx1, sy1 = e['src_box']
        X0, Y0, X1, Y1 = e['box']
        tx = X0 - s * sx0
        ty = PH - Y0 - s * (H0 - sy0)
        tmp = PageObject.create_blank_page(width=PW, height=PH)
        tmp.merge_transformed_page(ov_page, Transformation().scale(s, s).translate(tx, ty), expand=False)
        pad = 1.2 * s
        _clip_wrap(tmp, (X0 - pad, PH - Y1 - pad, (X1 - X0) + 2 * pad, (Y1 - Y0) + 2 * pad))
        layers.append((name, tmp))

    # assemble with PDF layers (optional content groups)
    wr = PdfWriter()
    ocgs, props = [], DictionaryObject()
    for i, (name, pg) in enumerate(layers):
        ocg = DictionaryObject({NameObject('/Type'): NameObject('/OCG'), NameObject('/Name'): TextStringObject(name)})
        ref = wr._add_object(ocg); ocgs.append(ref)
        tag = f'L{i}'
        props[NameObject('/' + tag)] = ref
        _layer_wrap(pg, tag)
        out.merge_page(pg, expand=False)
    res = out['/Resources']
    res[NameObject('/Properties')] = props
    for box in ('/MediaBox', '/CropBox', '/BleedBox'):
        out[NameObject(box)] = ArrayObject([FloatObject(0), FloatObject(0), FloatObject(PW), FloatObject(PH)])
    out[NameObject('/TrimBox')] = ArrayObject([FloatObject(b), FloatObject(b), FloatObject(b + W), FloatObject(b + H)])
    out[NameObject('/ArtBox')] = out['/TrimBox']
    wr.add_page(out)
    wr._root_object[NameObject('/OCProperties')] = DictionaryObject({
        NameObject('/OCGs'): ArrayObject(ocgs),
        NameObject('/D'): DictionaryObject({NameObject('/Order'): ArrayObject(ocgs), NameObject('/ON'): ArrayObject(ocgs)})})
    try:
        wr.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
    except TypeError:
        wr.compress_identical_objects(remove_identicals=True, remove_orphans=True)
    wr.add_metadata({'/Title': title, '/Creator': 'Artwork Resizer', '/Subject':
                     f"{p['layout']} | guide p{p['guide_page']} | ratio {p['ratio']}"})
    with open(out_path, 'wb') as f:
        wr.write(f)
    return out_path


def _element_names(elements, H0):
    names = []
    for e in elements:
        y = (e['src_box'][1] + e['src_box'][3]) / 2
        pos = 'top' if y < H0 * 0.33 else ('bottom' if y > H0 * 0.67 else 'middle')
        names.append(f"{e.get('role', 'Text & logo')} – {pos} {e['h_anchor']}")
    seen = {}
    out = []
    for n in names:
        seen[n] = seen.get(n, 0) + 1
        out.append(n if seen[n] == 1 else f'{n} {seen[n]}')
    return out


def file_name(p, context, language, width, height, unit, job='artwork'):
    dims = f"{width:g}x{height:g}{unit}"
    return re.sub(r'[^A-Za-z0-9_.\-]+', '_', f"{job}_{context}_{language}_{dims}") + '.ai'
