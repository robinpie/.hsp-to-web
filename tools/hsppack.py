#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Pack a custom .hsp page into a standalone site with only the assets it uses.

Where hspconv.py converts the whole game, this takes one page you wrote
yourself (or a handful) and pulls in exactly the images, fonts and music it
references -- nothing else.

  hsppack.py --data <game>/data mypage.hsp --out mypage

The result is self-contained: every asset is copied in, so the directory can be
moved, zipped or served anywhere. That also means it contains game art, so it
is yours to keep, not to redistribute -- see README.md.
"""
import argparse, json, os, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hspconv as hc


def collect(hsp_args):
    """Expand file and directory arguments into a sorted list of .hsp paths."""
    out = []
    for a in hsp_args:
        if os.path.isdir(a):
            for dirpath, _, files in os.walk(a):
                out += [os.path.join(dirpath, f) for f in sorted(files)
                        if f.lower().endswith('.hsp')]
        elif os.path.isfile(a):
            out.append(a)
        else:
            sys.exit(f'error: no such file or directory: {a}')
    return sorted(set(os.path.abspath(p) for p in out))


def page_paths(hsps):
    """Name each page relative to the pages' common parent.

    Links between the packed pages then resolve the way they do in game: a bare
    filename against the page's own folder, a longer path against the root.
    """
    base = os.path.dirname(hsps[0]) if len(hsps) == 1 else os.path.commonpath(hsps)
    return [os.path.relpath(p, base).replace(os.sep, '/') for p in hsps]


def render_music(data, out, sources, fmt):
    """Render just the .hsm modules these pages ask for, via hsmrender.py."""
    hsmdir = os.path.join(out, 'media', 'hsm')
    manifest = {}
    for src in sorted(sources):
        tool = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hsmrender.py')
        r = subprocess.run([sys.executable, tool, '--data', data, '--out', hsmdir,
                            '--format', fmt, '--only', os.path.basename(src)],
                           stderr=subprocess.DEVNULL)
        if r.returncode == 0:
            manifest.update(hc.load_hsm_manifest(hsmdir))
    # hsmrender rewrites index.json per run, so keep the union of every run.
    if manifest:
        with open(os.path.join(hsmdir, 'index.json'), 'w', encoding='utf-8') as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=1)
    return manifest


def main():
    ap = argparse.ArgumentParser(
        description='Pack custom .hsp pages into a standalone site with only '
                    'the assets they reference.')
    ap.add_argument('hsp', nargs='+', help='.hsp files, or directories of them')
    ap.add_argument('--data', required=True,
                    help="the game's data/ directory, where assets are looked up")
    ap.add_argument('--out', required=True, help='directory to write')
    ap.add_argument('--flags', nargs='*', default=[],
                    help='story flags to treat as true when resolving element states')
    ap.add_argument('--no-music', action='store_true',
                    help='skip audio entirely (no ffmpeg/numpy needed)')
    ap.add_argument('--format', default='ogg', choices=['ogg', 'opus', 'm4a'],
                    help='encoding for rendered .hsm music (default ogg)')
    args = ap.parse_args()

    data = os.path.abspath(args.data)
    if os.path.isdir(os.path.join(data, 'data', 'hs')):
        data = os.path.join(data, 'data')
    if not os.path.isdir(os.path.join(data, 'images')):
        sys.exit(f'error: {data} has no images/ -- point --data at the game\'s '
                 "data/ directory (the one holding hs/, images/, misc/)")

    hsps = collect(args.hsp)
    if not hsps:
        sys.exit('error: no .hsp files found')
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)

    registry = hc.build_image_registry(data)
    fonts = hc.build_font_table(data)
    sys.stderr.write(f'{len(registry)} images, {len(fonts)} fonts available\n')
    flags = {'DEFAULT'} | {f.strip().upper() for f in args.flags}

    # First pass: parse, so we know which .hsm modules are worth rendering.
    parsed, missing_gifs = [], set()
    for src, rel in zip(hsps, page_paths(hsps)):
        try:
            page, missing = hc.parse_page(src, registry, flags, data, {})
        except (ValueError, KeyError, IndexError) as exc:
            sys.exit(f'error: {src} is not a readable .hsp '
                     f'({type(exc).__name__}: {exc}) -- see FORMAT.md')
        page['path'] = rel
        missing_gifs |= missing
        parsed.append(page)

    hsm = {}
    if not args.no_music:
        want = {p['music']['source'] for p in parsed
                if p['music'] and p['music']['kind'] == 'hsm'}
        if want:
            sys.stderr.write(f'rendering {len(want)} tracker module(s)...\n')
            hsm = render_music(data, out, want, args.format)

    # Second pass: re-resolve music now that the manifest exists, then collect
    # every asset the pages actually name.
    used, missing_assets = set(), []
    index = []
    page_index = {p['path'].lower(): p['path'] for p in parsed}
    dead = []
    for page in parsed:
        rel = page['path']
        mus = page['music'] = None if args.no_music else page['music']
        if mus and mus['kind'] == 'hsm' and mus.get('missing') and mus['source'] in hsm:
            entry = hsm[mus['source']]
            mus.update(src='media/hsm/' + entry['file'], title=entry['title'],
                       artist=entry['artist'], seconds=entry['seconds'])
            del mus['missing']
        page['fonts'] = {}
        for e in page['elements']:
            if e['type'] == 'text':
                if e['font'] in fonts:
                    page['fonts'][e['font']] = fonts[e['font']]
                else:
                    missing_assets.append(f"font {e['fontName']} ({e['font']})")
            used.update(e.get('frames', []))
        used.update(f['sheet'] for f in page['fonts'].values())
        if page['bg']:
            used.add(page['bg'])
        if mus and mus['kind'] == 'ogg' and mus['src']:
            used.add(mus['src'][len('assets/'):])
        if mus and mus.get('missing'):
            missing_assets.append(f"music {mus['source']}")

        for link in [e['link'] for e in page['elements']] + [page['script']]:
            if not link or not link.get('href'):
                continue
            hit = hc.resolve_link(link['href'], rel, page_index)
            link['page'] = os.path.splitext(hit)[0] + '.html' if hit else None
            if hit is None:
                dead.append(link['href'])

        dst = os.path.join(out, 'pages', os.path.splitext(rel)[0] + '.html')
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        root = hc.rel_root(len(os.path.relpath(dst, out).split(os.sep)) - 1)
        with open(dst, 'w', encoding='utf-8') as fh:
            fh.write(hc.HTML.format(
                title=hc.html_escape(page['title'] or os.path.basename(rel)),
                data=json.dumps(page, ensure_ascii=False).replace('</', '<\\/'),
                root=root, root_js=json.dumps(root)))
        index.append({'path': rel,
                      'html': 'pages/' + os.path.splitext(rel)[0] + '.html',
                      'title': page['title'], 'author': page['author'],
                      'blurb': page['blurb'], 'n': len(page['elements'])})

    # Copy in only what was named above.
    copied = 0
    for a in sorted(used):
        s, d = os.path.join(data, a), os.path.join(out, 'assets', a)
        if not os.path.exists(s):
            missing_assets.append(f'image {a}')
            continue
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(s, d)
        copied += 1

    with open(os.path.join(out, 'index.json'), 'w', encoding='utf-8') as fh:
        json.dump(index, fh, ensure_ascii=False)

    libsrc = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'web')
    libdst = os.path.join(out, 'lib')
    os.makedirs(libdst, exist_ok=True)
    for f in os.listdir(libsrc):
        shutil.copy2(os.path.join(libsrc, f), os.path.join(libdst, f))

    size = sum(os.path.getsize(os.path.join(dp, f))
               for dp, _, fs in os.walk(out) for f in fs)
    sys.stderr.write(f'\npacked {len(index)} page(s), {copied} assets '
                     f'({size / 1024:.0f} KiB total)\n')
    for name in sorted(m for m in missing_gifs if m):
        sys.stderr.write(f'  !! no image named "{name}" in the game data\n')
    for m in sorted(set(missing_assets)):
        sys.stderr.write(f'  !! missing {m}\n')
    for h in sorted(set(dead)):
        sys.stderr.write(f'  -- link to "{h}" is not one of the packed pages\n')
    sys.stderr.write(f'open {os.path.join(out, index[0]["html"])}\n')


if __name__ == '__main__':
    main()
