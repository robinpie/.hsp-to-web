#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Sanity-check a converted site: unresolved assets, dangling links, accessibility.

  hspaudit.py --site site --data <game>/data
"""
import argparse, json, os, re, sys, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hspconv as hc


def luminance(c):
    """WCAG relative luminance of an [r, g, b] triple."""
    out = []
    for v in c[:3]:
        v /= 255.0
        out.append(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    lo, hi = sorted((la, lb))
    return (hi + 0.05) / (lo + 0.05)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--site', required=True)
    ap.add_argument('--data', required=True)
    args = ap.parse_args()

    pages = json.load(open(os.path.join(args.site, 'index.json'), encoding='utf-8'))
    have = {p['path'].lower() for p in pages}
    miss_img = collections.Counter()
    miss_music = collections.Counter()
    music = collections.Counter()
    miss_font = collections.Counter()
    dangling = collections.Counter()
    stats = collections.Counter()
    a11y = collections.Counter()
    worst = []

    pat = re.compile(r'<script id="hsp-data" type="application/json">(.*?)</script>', re.S)
    for p in pages:
        html = open(os.path.join(args.site, p['html']), encoding='utf-8').read()
        d = json.loads(pat.search(html).group(1).replace('<\\/', '</'))
        for e in d['elements']:
            stats[e['type']] += 1
            linked = bool((e.get('link') or {}).get('page'))
            if e['type'] == 'gif':
                if not e['frames']:
                    miss_img[e['gif']] += 1
                for f in e['frames'][:1]:
                    if not os.path.exists(os.path.join(args.data, f)):
                        miss_img['FILE:' + f] += 1
                alt = hc.gif_alt(e)
                a11y['image with alt text' if alt else 'image marked decorative'] += 1
                if linked and not alt:
                    a11y['LINK WITH NO ACCESSIBLE NAME'] += 1
            else:
                if e['font'] not in d['fonts']:
                    miss_font[e['font']] += 1
                if linked and not hc.replace_text(e['text']).strip():
                    a11y['LINK WITH NO ACCESSIBLE NAME'] += 1
                # Contrast is only knowable where the page sets a flat colour;
                # over a background image there is nothing to measure against.
                if d.get('bgColor') and e.get('color'):
                    r = contrast(e['color'], d['bgColor'])
                    a11y['text measured for contrast'] += 1
                    if r < 4.5:
                        a11y['text below 4.5:1'] += 1
                        worst.append((r, d['path'], hc.replace_text(e['text'])[:40]))
            link = e.get('link')
            if link and link.get('href') and not link.get('page'):
                dangling[link['href']] += 1
        if d.get('bg') and not os.path.exists(os.path.join(args.data, d['bg'])):
            miss_img['BG:' + d['bg']] += 1
        mus = d.get('music')
        if not mus:
            music['silent'] += 1
        else:
            music[mus['kind']] += 1
            if not mus.get('src'):
                miss_music[mus['source']] += 1
            else:
                # .ogg lives in the game tree, .hsm renders live in the site
                root = args.data if mus['kind'] == 'ogg' else args.site
                rel = mus['src'][len('assets/'):] if mus['kind'] == 'ogg' else mus['src']
                if not os.path.exists(os.path.join(root, rel)):
                    miss_music['FILE:' + mus['src']] += 1

    print(f"pages: {len(pages)}   elements: {dict(stats)}")
    print(f"music: {dict(music)}")
    def report(title, ctr, limit=15):
        total = sum(ctr.values())
        print(f"\n{title}: {len(ctr)} distinct, {total} references")
        for k, v in ctr.most_common(limit):
            print(f"   {v:5d}  {k!r}")
    report("unresolved images", miss_img)
    report("unresolved fonts", miss_font)
    report("page music with no playable file", miss_music)
    report("links that resolve to no exported page", dangling, 25)

    print("\naccessibility")
    for k in sorted(a11y):
        print(f"   {a11y[k]:5d}  {k}")
    if worst:
        worst.sort()
        print("   lowest-contrast text (a page's own palette, not something the")
        print("   converter can fix -- the text view is the way out):")
        for r, path, txt in worst[:8]:
            print(f"   {r:5.2f}:1  {path}  {txt!r}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
