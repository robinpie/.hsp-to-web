#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Convert Hypnospace Outlaw .hsp pages into HTML/CSS/JS.

See FORMAT.md for the format spec this implements.

  hspconv.py --data <game>/data --out site [--pages hs] [--copy-assets]

Produces a directory that can be opened straight from the filesystem
(no server needed) or served statically.
"""
import argparse, json, os, posixpath, re, shutil, sys
from collections import OrderedDict

PAGEWIDTH = 300
ROW_H = 32
IMG_EXT = ('.png', '.gif', '.jpg', '.jpeg', '.bmp')
# Character sets baked into the three Spritefontanim objects (t152/t153/t154).
BASE_CHARSET = ("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
                ".,;:?!-_~#\"'&()[]|`\\/@°+=*$£€<>")
FONT_SIZES = {
    0: {'cw': 7,  'ch': 7,  'charset': BASE_CHARSET + "%■▲"},
    1: {'cw': 14, 'ch': 12, 'charset': BASE_CHARSET},
    2: {'cw': 21, 'ch': 21, 'charset': BASE_CHARSET},
}
FONT_COLS = 8


def norm(p):
    """Game paths use backslashes; make them posix and lowercase."""
    return p.replace('\\', '/').strip().lower()


# --------------------------------------------------------------------------- #
# asset registry
# --------------------------------------------------------------------------- #
def build_image_registry(data):
    """Replicate the LoadGifs scan: gifs/, static/, shapes/, wordart/."""
    reg = OrderedDict()
    img = os.path.join(data, 'images')

    def add_dir(kind, sub, default_fps):
        root = os.path.join(img, sub)
        if not os.path.isdir(root):
            return
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            key = name.lower()
            if os.path.isdir(path):
                frames, fps = [], default_fps
                for f in sorted(os.listdir(path)):
                    if f.endswith('.speed'):
                        m = re.match(r'(\d{1,2})', f)
                        if m:
                            fps = int(m.group(1))
                    elif f.lower().endswith(IMG_EXT):
                        frames.append(f'images/{sub}/{name}/{f}')
                if frames and key not in reg:
                    reg[key] = {'frames': frames, 'fps': fps, 'kind': kind}
            elif name.lower().endswith(IMG_EXT):
                key = os.path.splitext(name)[0].lower()
                if key not in reg:
                    reg[key] = {'frames': [f'images/{sub}/{name}'], 'fps': 0, 'kind': kind}

    add_dir('gif', 'gifs', 5)
    add_dir('static', 'static', 0)
    add_dir('shape', 'shapes', 0)
    add_dir('wordart', 'wordart', 0)
    return reg


def parse_charwidths(spec):
    """`chars^width^chars^width...` -> {char: width}."""
    out, parts = {}, spec.split('^')
    for i in range(0, len(parts) - 1, 2):
        try:
            w = int(parts[i + 1])
        except ValueError:
            continue
        for ch in parts[i]:
            out[ch] = w
    return out


def build_font_table(data):
    """Parse fontdata.ini and pair each entry with its sprite sheet."""
    ini = os.path.join(data, 'images', 'fonts', 'fontdata.ini')
    fonts, cur = {}, None
    with open(ini, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.rstrip('\n')
            m = re.match(r'^\[(.+)\]\s*$', line)
            if m:
                cur = m.group(1)
                fonts[cur.lower()] = {'name': cur, 'spacing': 0, 'lineheight': 0, 'widths': {}}
                continue
            if cur is None or '=' not in line:
                continue
            k, v = line.split('=', 1)
            k = k.strip().lower()
            if k == 'spacing':
                fonts[cur.lower()]['spacing'] = int(v or 0)
            elif k == 'lineheight':
                fonts[cur.lower()]['lineheight'] = int(v or 0)
            elif k == 'charwidths':
                fonts[cur.lower()]['widths'] = parse_charwidths(v)

    for key, f in list(fonts.items()):
        m = re.match(r'^(.*)([012])([nb])$', key)
        if not m:
            del fonts[key]
            continue
        size = int(m.group(2))
        sheet = f'images/fonts/{key}.png'
        if not os.path.exists(os.path.join(data, sheet)):
            del fonts[key]
            continue
        f.update(FONT_SIZES[size], size=size, sheet=sheet, cols=FONT_COLS)
    return fonts


# --------------------------------------------------------------------------- #
# .hsp parsing
# --------------------------------------------------------------------------- #
def cell(row, i):
    v = row[i] if i < len(row) else ''
    return v if isinstance(v, str) else ('' if v is None else str(v))


# Construct 2's int()/float() are parseInt()/parseFloat(): they take the leading
# numeric prefix and ignore the rest, which some cells rely on.
_INT_RE = re.compile(r'[+-]?\d+')
_FLOAT_RE = re.compile(r'[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?')


def as_int(v, default=0):
    if isinstance(v, (int, float)):
        return int(v)
    m = _INT_RE.match(str(v).strip())
    return int(m.group(0)) if m else default


def as_float(v, default=0.0):
    if isinstance(v, (int, float)):
        return float(v)
    m = _FLOAT_RE.match(str(v).strip())
    return float(m.group(0)) if m else default


def off_neg(v):
    """Sway/dither speeds are disabled with -1; the runtime enables them on `>= 0`."""
    f = as_float(v, -1)
    return None if f < 0 else f


def unpack_color(v):
    """Packed decimal colour, BGR order (low byte = red)."""
    c = as_int(v, 0)
    if c < 0:
        return None
    return [c & 255, (c >> 8) & 255, (c >> 16) & 255]


def pick_state(el, flags):
    """ElementEventWeb: last matching state row wins, DEFAULT is row 1."""
    chosen = 1
    for y in range(1, len(el)):
        name = cell(el[y], 0).strip().upper()
        if name == '':
            break
        if name in flags:
            chosen = y
    return el[chosen] if chosen < len(el) else el[1]


def parse_link(raw):
    """`cmd:param|cmd:param`, or a bare page path."""
    raw = (raw or '').strip()
    if raw in ('', '-1', '0'):
        return None
    out = {'raw': raw, 'cmds': [], 'href': None, 'tooltip': None, 'anchor': None}
    for part in raw.split('|'):
        if ':' in part:
            cmd, _, param = part.partition(':')
            cl = cmd.strip().lower()
            # A Windows drive-ish or path-ish token is a bare link, not a command.
            out['cmds'].append({'cmd': cl, 'param': param})
            if cl == 'webpage':
                out['href'] = param
            elif cl == 'tooltip':
                out['tooltip'] = param
            elif cl == 'anchor':
                out['anchor'] = as_float(param, 0) * ROW_H
        elif part.strip():
            tok = part.strip()
            looks_like_path = (tok.lower().endswith('.hsp')
                               or '\\' in tok or '/' in tok)
            out['cmds'].append({'cmd': 'webpage' if looks_like_path else 'unknown',
                                'param': tok})
            if looks_like_path and out['href'] is None:
                out['href'] = tok
    return out


CAPTURES = ('hs', 'hsa', 'hsb', 'hsc')


def link_candidates(href, src_rel):
    """Every path an in-game link could mean, best first.

    `URLtoCurrent` rewrites the first path segment to the *current capture*
    unless it is `ex` or is itself a filename -- every link is authored against
    a logical root and served from whichever chapter directory is live. A path
    that names a directory then resolves to `home.hsp`, falling back to
    `zone.hsp` (see `LoadWebpage`).
    """
    raw = href.replace('\\', '/').strip()
    t = raw.strip('/')
    if not t:
        return []
    is_dir = raw.endswith('/') or not t.lower().endswith('.hsp')
    parts = t.split('/')
    capture = src_rel.split('/')[0]
    src_dir = posixpath.dirname(src_rel)
    head = parts[0].lower()

    bases = []
    if len(parts) == 1 and not is_dir:
        # A bare filename is relative to the linking page's own folder.
        bases.append(posixpath.join(src_dir, parts[0]))
    else:
        if head != 'ex' and not head.endswith('.hsp'):
            bases.append('/'.join([capture] + parts[1:]))   # URLtoCurrent
        bases.append(t)
        bases.append(posixpath.join(src_dir, t))

    out = []
    for b in bases:
        b = posixpath.normpath(b)
        if b.lower().endswith('.hsp'):
            out.append(b)
        else:
            out.append(b + '/home.hsp')
            out.append(b + '/zone.hsp')
    return out


def resolve_link(href, src_rel, page_index):
    # Note: a few shipped links have the "no link" sentinel glued to the front
    # (`-1hs\zone\page.hsp`). They still work, because URLtoCurrent replaces
    # that whole first segment with the current capture.
    for cand in link_candidates(href, src_rel):
        hit = page_index.get(cand.lower())
        if hit:
            return hit
    return None


def load_hsm_manifest(path):
    """Modules rendered to audio by tools/hsmrender.py, keyed by source path."""
    idx = os.path.join(path, 'index.json')
    if not os.path.exists(idx):
        return {}
    with open(idx, encoding='utf-8') as fh:
        return json.load(fh)


def resolve_music(raw, data, hsm):
    """Page music is either a plain .ogg or a .hsm tracker module.

    A .ogg sits in the game's audio tree with a sibling `.txt` holding
    `title|artist` -- exactly what UpdatePageMusic reads for the now-playing
    line. A .hsm is a tracker module, so we point at the file hsmrender.py
    bounced it down to and take its metadata from the module header.
    """
    m = norm(raw)
    if m in ('', '0', '-1'):
        return None
    if m.endswith('.hsm'):
        entry = hsm.get(m)
        if not entry:
            return {'src': None, 'title': '', 'artist': '', 'kind': 'hsm',
                    'source': m, 'missing': True}
        return {'src': 'media/hsm/' + entry['file'], 'kind': 'hsm', 'source': m,
                'title': entry['title'], 'artist': entry['artist'],
                'seconds': entry['seconds']}

    src = 'assets/' + m
    title = artist = ''
    side = os.path.join(data, m[:-4] + '.txt')
    if os.path.exists(side):
        txt = open(side, encoding='utf-8', errors='replace').read().strip()
        parts = txt.split('|')
        title = parts[0].strip() if parts else ''
        artist = parts[1].strip() if len(parts) > 1 else ''
    return {'src': src, 'kind': 'ogg', 'source': m,
            'title': title, 'artist': artist,
            'missing': not os.path.exists(os.path.join(data, m))}


def parse_page(path, registry, flags, data_dir='', hsm=None):
    with open(path, encoding='utf-8', errors='replace') as fh:
        doc = json.load(fh)
    data = doc['data']
    page_el = data[0]
    p = pick_state(page_el, flags)

    bg_name = cell(p, 5).strip()
    bg_color = unpack_color(cell(p, 7)) if bg_name.lower() == '000.png' else None
    tags_raw = cell(p, 8)
    blurb, _, keywords = tags_raw.partition('>')

    page = {
        'title': cell(p, 1),
        'author': cell(p, 2).lstrip('*'),
        'width': PAGEWIDTH,
        'height': max(as_int(cell(p, 3), 1), 1) * ROW_H,
        'music': resolve_music(cell(p, 4), data_dir, hsm or {}),
        'bg': ('images/bgs/' + bg_name.lower()) if bg_name else None,
        'bgColor': bg_color,
        'cursor': as_int(cell(p, 6), 0),
        'blurb': blurb.strip(),
        'keywords': keywords.strip(),
        'icon': as_int(cell(p, 9), -1),
        'isHomepage': as_int(cell(p, 10), 0) == 1,
        'script': parse_link(cell(p, 11)),
        'elements': [],
    }

    missing = set()
    for x in range(1, len(data)):
        el = data[x]
        kind = cell(el[0], 0)
        if kind not in ('Gif', 'Text'):
            continue
        s = pick_state(el, flags)
        base = {
            'i': x,
            'name': cell(el[0], 2),
            'link': parse_link(cell(s, 10)),
            'lawTag': as_int(cell(s, 11), 0),
        }
        if kind == 'Gif':
            gname = cell(s, 5).strip().lower()
            entry = registry.get(gname)
            if entry is None:
                missing.add(gname)
            hsl = cell(s, 3)
            base.update({
                'type': 'gif',
                'gif': gname,
                'frames': entry['frames'] if entry else [],
                'fps': entry['fps'] if entry else 0,
                'x': as_int(cell(s, 1)),
                'y': as_int(cell(s, 2)),
                'scale': as_float(cell(s, 6), 1) or 1,
                'angle': as_float(cell(s, 7), 0),
                'mirror': as_int(cell(s, 8)) == 1,
                'flip': as_int(cell(s, 9)) == 1,
                # -1 is the off-sentinel for these; the runtime gates on ">= 0".
                'swayX': off_neg(cell(s, 12)),
                'swayY': off_neg(cell(s, 13)),
                'dither': off_neg(cell(s, 14)),
                'rotMode': as_int(cell(s, 15), 0),
                'rotSpeed': as_float(cell(s, 16), 0),
                'frame': as_int(cell(s, 18), 0),
                'sync': as_int(cell(s, 19)) == 1,
                'animMode': as_int(cell(s, 20), 0),
                'hsl': [as_int(t) for t in hsl.split(',')] if ',' in str(hsl) else None,
            })
        else:
            style = cell(s, 8) or '0n'
            font = cell(s, 7) or 'HypnoFont'
            wpct = as_int(cell(s, 3), 0)
            w = PAGEWIDTH if wpct == 0 else int(PAGEWIDTH * min(wpct * 0.01, 100))
            col2 = cell(s, 14)
            base.update({
                'type': 'text',
                'text': cell(s, 5),
                'font': (font + style).lower(),
                'fontName': font,
                'size': as_int(style[:1], 0),
                'w': w,
                'x': int((PAGEWIDTH - w) / 2) + as_int(cell(s, 1)) * (PAGEWIDTH * 0.01),
                'y': as_int(cell(s, 2)),
                'color': unpack_color(cell(s, 6)) or [0, 0, 0],
                'align': as_int(cell(s, 9), 0),
                'anim': as_int(cell(s, 12), 0),
                'animSpeed': as_float(cell(s, 13), 10),
                'color2': None if as_int(col2, -1) == -1 else unpack_color(col2),
                'colorSpeed': as_float(cell(s, 15), 10),
                'noRecolor': as_int(cell(s, 16)) == 1 or font.lower() == 'designelements',
            })
        page['elements'].append(base)
    return page, missing


# --------------------------------------------------------------------------- #
# output
# --------------------------------------------------------------------------- #
HTML = """<!DOCTYPE html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="{root}lib/hsp.css">
<script src="{root}lib/hsp.js"></script>
<body>
<div id="hsp-stage"><div id="hsp-page"></div></div>
<script id="hsp-data" type="application/json">{data}</script>
<script>HSP.boot({{root:{root_js}}});</script>
"""


def rel_root(depth):
    return '../' * depth if depth else ''


def html_escape(s):
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True, help="the game's data/ directory")
    ap.add_argument('--out', required=True)
    ap.add_argument('--pages', nargs='*', default=['hs', 'hsa', 'hsb', 'hsc', 'ex'],
                    help='subdirectories of data/ to convert')
    ap.add_argument('--flags', nargs='*', default=[],
                    help='story flags to treat as true when resolving element states')
    ap.add_argument('--copy-assets', action='store_true',
                    help='copy referenced assets instead of symlinking data/')
    ap.add_argument('--hsm', help='directory of rendered .hsm audio '
                    '(default <out>/media/hsm, produced by tools/hsmrender.py)')
    ap.add_argument('--limit', type=int, default=0)
    args = ap.parse_args()

    data = os.path.abspath(args.data)
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)

    hsm = load_hsm_manifest(args.hsm or os.path.join(out, 'media', 'hsm'))
    sys.stderr.write(f'scanning assets... ({len(hsm)} rendered .hsm modules)\n')
    registry = build_image_registry(data)
    fonts = build_font_table(data)
    sys.stderr.write(f'  {len(registry)} images, {len(fonts)} fonts\n')

    flags = {'DEFAULT'} | {f.strip().upper() for f in args.flags}

    hsps = []
    for sub in args.pages:
        root = os.path.join(data, sub)
        for dirpath, _, files in os.walk(root):
            for f in sorted(files):
                if f.lower().endswith('.hsp'):
                    hsps.append(os.path.join(dirpath, f))
    hsps.sort()
    if args.limit:
        hsps = hsps[:args.limit]
    sys.stderr.write(f'  {len(hsps)} pages\n')

    sys.stderr.write('parsing...\n')
    parsed, missing_all = [], set()
    for src in hsps:
        rel = os.path.relpath(src, data).replace(os.sep, '/')
        page, missing = parse_page(src, registry, flags, data, hsm)
        missing_all |= missing
        page['path'] = rel
        parsed.append(page)

    page_index = {p['path'].lower(): p['path'] for p in parsed}
    dead = 0
    for page in parsed:
        for link in [e['link'] for e in page['elements']] + [page['script']]:
            if not link or not link.get('href'):
                continue
            hit = resolve_link(link['href'], page['path'], page_index)
            link['page'] = os.path.splitext(hit)[0] + '.html' if hit else None
            if hit is None:
                dead += 1
    sys.stderr.write(f'  {dead} links with no matching page in this export\n')

    used, index = set(), []
    for page in parsed:
        rel = page['path'].replace('/', os.sep)
        page['fonts'] = {e['font']: fonts[e['font']] for e in page['elements']
                         if e['type'] == 'text' and e['font'] in fonts}

        for f in page['fonts'].values():
            used.add(f['sheet'])
        if page['bg']:
            used.add(page['bg'])
        mus = page['music']
        if mus and mus['kind'] == 'ogg' and mus['src']:
            used.add(mus['src'][len('assets/'):])
        for e in page['elements']:
            used.update(e.get('frames', []))

        dst = os.path.join(out, 'pages', os.path.splitext(rel)[0] + '.html')
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        depth = len(os.path.relpath(dst, out).split(os.sep)) - 1
        root_rel = rel_root(depth)
        with open(dst, 'w', encoding='utf-8') as fh:
            fh.write(HTML.format(
                title=html_escape(page['title'] or os.path.basename(rel)),
                data=json.dumps(page, ensure_ascii=False).replace('</', '<\\/'),
                root=root_rel, root_js=json.dumps(root_rel)))
        index.append({'path': page['path'],
                      'html': 'pages/' + os.path.splitext(rel)[0].replace(os.sep, '/') + '.html',
                      'title': page['title'], 'author': page['author'],
                      'blurb': page['blurb'], 'n': len(page['elements'])})

    # assets
    if args.copy_assets:
        sys.stderr.write(f'copying {len(used)} assets...\n')
        for a in sorted(used):
            s, d = os.path.join(data, a), os.path.join(out, 'assets', a)
            if os.path.exists(s):
                os.makedirs(os.path.dirname(d), exist_ok=True)
                if not os.path.exists(d):
                    shutil.copy2(s, d)
    else:
        link = os.path.join(out, 'assets')
        if os.path.islink(link):
            os.unlink(link)
        if not os.path.exists(link):
            os.symlink(data, link)

    with open(os.path.join(out, 'index.json'), 'w', encoding='utf-8') as fh:
        json.dump(index, fh, ensure_ascii=False)
    write_index(out, index)

    libsrc = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'web')
    libdst = os.path.join(out, 'lib')
    os.makedirs(libdst, exist_ok=True)
    for f in os.listdir(libsrc):
        shutil.copy2(os.path.join(libsrc, f), os.path.join(libdst, f))

    if missing_all:
        sys.stderr.write(f'note: {len(missing_all)} unresolved image names, e.g. '
                         + ', '.join(sorted(m for m in missing_all if m)[:6]) + '\n')
    sys.stderr.write(f'wrote {len(index)} pages to {out}\n')


INDEX_HTML = """<!DOCTYPE html>
<meta charset="utf-8">
<title>Hypnospace pages</title>
<link rel="stylesheet" href="lib/hsp.css">
<body class="hsp-index">
<h1>Hypnospace Outlaw — {n} pages</h1>
<p class="sub">Rendered from <code>.hsp</code> sources. <input id="q" placeholder="filter…" autofocus></p>
<ul id="list">{rows}</ul>
<script>
const q=document.getElementById('q'),items=[...document.querySelectorAll('#list li')];
q.addEventListener('input',()=>{{const v=q.value.toLowerCase();
  for(const li of items) li.hidden = v && !li.dataset.k.includes(v);}});
</script>
"""


def write_index(out, index):
    rows = []
    for it in index:
        key = f"{it['path']} {it['title']} {it['author']} {it['blurb']}".lower()
        rows.append(
            '<li data-k="{k}"><a href="{h}">{t}</a>'
            '<span class="p">{p}</span>{a}</li>'.format(
                k=html_escape(key), h=html_escape(it['html']),
                t=html_escape(it['title'] or '(untitled)'),
                p=html_escape(it['path']),
                a=('<span class="au">' + html_escape(it['author']) + '</span>') if it['author'] else ''))
    with open(os.path.join(out, 'index.html'), 'w', encoding='utf-8') as fh:
        fh.write(INDEX_HTML.format(n=len(index), rows='\n'.join(rows)))


if __name__ == '__main__':
    main()
