#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Sanity-check a converted site: unresolved images/fonts and dangling page links.

  hspaudit.py --site site --data <game>/data
"""
import argparse, json, os, re, sys, collections

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

    pat = re.compile(r'<script id="hsp-data" type="application/json">(.*?)</script>', re.S)
    for p in pages:
        html = open(os.path.join(args.site, p['html']), encoding='utf-8').read()
        d = json.loads(pat.search(html).group(1).replace('<\\/', '</'))
        for e in d['elements']:
            stats[e['type']] += 1
            if e['type'] == 'gif':
                if not e['frames']:
                    miss_img[e['gif']] += 1
                for f in e['frames'][:1]:
                    if not os.path.exists(os.path.join(args.data, f)):
                        miss_img['FILE:' + f] += 1
            else:
                if e['font'] not in d['fonts']:
                    miss_font[e['font']] += 1
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
    return 0

if __name__ == '__main__':
    sys.exit(main())
