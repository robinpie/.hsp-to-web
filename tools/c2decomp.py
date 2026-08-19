#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Decompile a Construct 2 `data.js` project model into readable pseudo-code.

Used to reverse-engineer how HypnOS interprets .hsp files.
Usage: c2decomp.py <pkgdir> [sheet-name-or-'all'] [--grep PATTERN]
"""
import json, sys, re, os

def load(pkgdir):
    proj = json.loads(open(os.path.join(pkgdir,'data.js'), encoding='utf-8-sig').read())['project']
    src  = open(os.path.join(pkgdir,'c2runtime.js'), encoding='utf-8', errors='replace').read()
    i = src.index('cr.getObjectRefTable = function () { return [')
    j = src.index('[', i); k = src.index('];', j)
    ref = [x.strip() for x in src[j+1:k].split(',') if x.strip()]
    return proj, ref

class D:
    def __init__(self, proj, ref):
        self.p, self.ref = proj, ref
        self.types = proj[3]
    def oname(self, idx):
        if idx == -1: return 'System'
        t = self.types[idx]
        plug = self.ref[t[1]].replace('cr.plugins_.','').replace('cr.behaviors.','')
        return f'{t[0]}<{plug}>'
    def fn(self, idx):
        return self.ref[idx].replace('cr.plugins_.','').replace('cr.system_object.prototype.','sys.').replace('cr.behaviors.','')
    # ---- expressions ----
    BIN = {4:'+',5:'-',6:'*',7:'/',8:'%',9:'^',10:'&&',11:'||',12:'==',13:'!=',14:'<',15:'<=',16:'>',17:'>='}
    def ex(self, m):
        if m is None: return 'null'
        t = m[0]
        if t in (0,1): return repr(m[1])
        if t == 2: return json.dumps(m[1])
        if t == 3: return f'-({self.ex(m[1])})'
        if t in self.BIN: return f'({self.ex(m[1])} {self.BIN[t]} {self.ex(m[2])})'
        if t == 18: return f'({self.ex(m[1])} ? {self.ex(m[2])} : {self.ex(m[3])})'
        if t == 19:
            args = ', '.join(self.ex(a) for a in m[2]) if len(m) == 3 else ''
            return f'{self.fn(m[1])}({args})'
        if t == 20:
            args = ', '.join(self.ex(a) for a in m[5]) if len(m) == 6 else ''
            inst = f'[{self.ex(m[4])}]' if m[4] else ''
            return f'{self.oname(m[1])}{inst}.{self.fn(m[2])}({args})'
        if t == 21:
            inst = f'[{self.ex(m[3])}]' if m[3] else ''
            return f'{self.oname(m[1])}{inst}.instvar#{m[4]}'
        if t == 22: return f'{self.oname(m[1])}.{m[2]}.{self.fn(m[3])}(...)'
        if t == 23: return f'${m[1]}'
        return f'<exp{t}:{json.dumps(m)[:60]}>'
    def par(self, m):
        t = m[0]
        if t in (0,1,5,7): return self.ex(m[1])
        if t in (3,8): return f'combo:{m[1]}'
        if t == 6: return f'layout:{m[1]}'
        if t == 9: return f'key:{m[1]}'
        if t == 4: return f'obj:{self.oname(m[1])}'
        if t == 10: return f'var:{m[1]}'
        if t == 11: return f'var:{m[1]}'
        if t == 12: return f'audio:{m[1]}'
        if t == 13: return ', '.join(self.par(x) for x in m[1:])
        return f'p{t}:{json.dumps(m[1:])[:50]}'
    # ---- statements ----
    def act(self, m):
        ps = ', '.join(self.par(x) for x in (m[5] if len(m) == 6 else []))
        beh = f'.{m[2]}' if m[2] else ''
        return f'{self.oname(m[0])}{beh}.{self.fn(m[1])}({ps})'
    def cnd(self, m):
        ps = ', '.join(self.par(x) for x in (m[9] if len(m) == 10 else []))
        beh = f'.{m[2]}' if m[2] else ''
        neg = 'NOT ' if m[5] else ''
        trg = '>>' if m[3] > 0 else ''
        return f'{trg}{neg}{self.oname(m[0])}{beh}.{self.fn(m[1])}({ps})'
    def blk(self, m, ind=0, out=None):
        pad = '  ' * ind
        if m[0] == 0:       # event block
            if m[1]:
                out.append(f'{pad}GROUP "{m[1][1]}" (active={bool(m[1][0])})')
            else:
                orb = ' [OR]' if m[2] else ''
                for i, c in enumerate(m[5]):
                    out.append(f'{pad}{"IF" if i==0 else "AND"}{orb} {self.cnd(c)}')
                if not m[5]: out.append(f'{pad}ALWAYS')
            for a in m[6]: out.append(f'{pad}  DO {self.act(a)}')
            for s in (m[7] if len(m) > 7 and m[7] else []): self.blk(s, ind+1, out)
        elif m[0] == 1:     # variable
            out.append(f'{pad}VAR {m[1]} = {json.dumps(m[3])} (type {m[2]}, static={m[4]})')
        elif m[0] == 2:     # include
            out.append(f'{pad}INCLUDE sheet#{m[1]}')
        elif m[0] == 3:     # script
            out.append(f'{pad}SCRIPT {json.dumps(m[1])[:200]}')
        else:
            out.append(f'{pad}<blk{m[0]}> {json.dumps(m)[:120]}')
        return out

def main():
    pkg = sys.argv[1]
    want = sys.argv[2] if len(sys.argv) > 2 else 'all'
    grep = None
    if '--grep' in sys.argv: grep = sys.argv[sys.argv.index('--grep')+1]
    proj, ref = load(pkg)
    d = D(proj, ref)
    for name, body in proj[6]:
        if want not in ('all', name): continue
        out = [f'######## SHEET: {name} ########']
        for ev in body: d.blk(ev, 0, out)
        text = '\n'.join(out)
        if grep:
            lines = text.split('\n')
            for i, l in enumerate(lines):
                if re.search(grep, l, re.I):
                    print('\n'.join(lines[max(0,i-2):i+3])); print('   ...')
        else:
            print(text)

if __name__ == '__main__': main()
