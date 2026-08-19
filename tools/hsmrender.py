#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Render Hypnospace `.hsm` tracker modules to audio files.

`.hsm` is a Construct 2 array holding a sample-based tracker module. This
reimplements HypnOS's own playback path (the "Play Music Sounds" group and the
`BPM Timer` sheet) closely enough to bounce each module down to a loopable file.

  hsmrender.py --data <game>/data --out site/assets/audio/hsm --format ogg

Reproduced: the pattern sequence, per-pattern BPM and length, the instrument
table, note pitches via the FREQOUT resampling table, per-step and per-track
volume and pan, and the note-length gate.

Not reproduced: the per-step effect slots (echo, arpeggio, pitch-shift,
vibrato, filter) held in z[4]..z[16] of each step. They are rare in the shipped
modules and are left for a future pass.
"""
import argparse, json, os, subprocess, sys
import numpy as np

SR = 44100
# Note -> playback rate table, verbatim from the FREQOUT global. Index 24 is
# 44100, i.e. the sample's own pitch, and it is by far the most used note.
FREQOUT = [11025, 11680, 12375, 13111, 13890, 14716, 15591, 16518, 17501, 18541,
           19644, 20812, 22050, 23361, 24750, 26222, 27781, 29433, 31183, 33037,
           35002, 37083, 39288, 41624, 44100, 46722, 49500, 52444, 55562, 58866,
           62366, 66075, 70004, 74167, 78577, 83249, 88200, 93444, 99001, 104887,
           111123, 117731, 124732, 132149, 140007, 148332, 157152, 166497, 176398,
           186887, 198000, 209773, 222247, 235463, 249464, 264298, 280014, 296664,
           314305, 332995]
NOTE_REST = 100          # a step whose note is 100 is skipped
TRACKS = (1, 2, 3, 4, 5)
MUTE_DB = -200.0


def cell(a, x, y, z):
    try:
        v = a[x][y][z]
    except IndexError:
        return ''
    return v if isinstance(v, str) else ('' if v is None else str(v))


def num(v, default=0.0):
    try:
        return float(str(v).strip())
    except (ValueError, TypeError):
        return default


def db_to_amp(db):
    return 0.0 if db <= MUTE_DB else 10.0 ** (db / 20.0)


def step_duration(v):
    """Instrument duration field: 0-100 -> a count of steps.

    From the envelope block: ceil(lerp(0, 34, v/100)), after which 1 and 2 are
    reinterpreted as fractional steps.
    """
    n = int(np.ceil(34.0 * v / 100.0))
    if n == 1:
        return 0.25
    if n == 2:
        return 0.5
    return max(0.0, n - 2)


class SampleBank:
    """Decodes each referenced sample once, to mono float32 at 44.1 kHz."""

    def __init__(self, data_dir):
        self.root = data_dir
        self.cache = {}

    def get(self, rel):
        key = rel.lower()
        if key in self.cache:
            return self.cache[key]
        path = os.path.join(self.root, 'audio', rel.replace('\\', '/') + '.ogg')
        buf = None
        if os.path.exists(path):
            try:
                raw = subprocess.run(
                    ['ffmpeg', '-v', 'quiet', '-i', path,
                     '-f', 'f32le', '-ac', '1', '-ar', str(SR), '-'],
                    check=True, stdout=subprocess.PIPE).stdout
                buf = np.frombuffer(raw, dtype='<f4').astype(np.float32)
            except subprocess.CalledProcessError:
                buf = None
        self.cache[key] = buf
        return buf


def resample(buf, rate, want):
    """Linear-interpolated resample -- the game simply varies playback rate."""
    if rate == 1.0:
        return buf[:want]
    idx = np.arange(want, dtype=np.float64) * rate
    idx = idx[idx < len(buf) - 1]
    if len(idx) == 0:
        return np.zeros(0, dtype=np.float32)
    lo = idx.astype(np.int64)
    frac = (idx - lo).astype(np.float32)
    return (buf[lo] * (1.0 - frac) + buf[lo + 1] * frac).astype(np.float32)


def parse_module(path):
    with open(path, encoding='utf-8', errors='replace') as fh:
        a = json.load(fh)['data']
    W, H = len(a), len(a[0])

    instruments = {}
    for x in range(1, W):
        name = cell(a, x, 0, 0).strip()
        if not name or name == '0':
            continue
        instruments[x] = {
            'sample': name,
            'loop': num(cell(a, x, 0, 1)),
            'stop': num(cell(a, x, 0, 2)),
            'sustain': num(cell(a, x, 0, 3)),
            'attack': num(cell(a, x, 0, 4)),
        }

    # The pattern sequence shares row y=0: slot z=10 of each x holds that
    # sequence position's pattern index + 1, and 0 means an empty slot.
    sequence = [int(num(cell(a, x, 0, 10))) - 1
                for x in range(W) if int(num(cell(a, x, 0, 10))) > 0]

    return {'title': cell(a, 0, 0, 0), 'artist': cell(a, 0, 0, 1),
            'array': a, 'W': W, 'H': H,
            'instruments': instruments, 'sequence': sequence}


def pattern_header(a, p):
    """Pattern p's header shares row 5p+1 with track 1's pan and volume."""
    y = 5 * p + 1
    return {'bpm': num(cell(a, 0, y, 0), 120) or 120,
            'steps': int(num(cell(a, 0, y, 1), 32)) or 32}


def build_events(mod):
    """Flatten the pattern sequence into absolutely-timed note events."""
    a, events, t = mod['array'], [], 0.0
    for p in mod['sequence']:
        if 5 * p + 1 >= mod['H']:
            continue
        hdr = pattern_header(a, p)
        sps = 15.0 / hdr['bpm']                   # 1/(bpm/60)/4 -- a 16th note
        for s in range(hdr['steps']):
            for tr in TRACKS:
                y = 5 * p + tr
                if y >= mod['H']:
                    continue
                slot = int(num(cell(a, s + 1, y, 0)))
                if slot <= 0 or slot not in mod['instruments']:
                    continue
                note = int(num(cell(a, s + 1, y, 1), NOTE_REST))
                if note == NOTE_REST:
                    continue
                events.append({
                    'time': t + s * sps, 'sps': sps,
                    'inst': mod['instruments'][slot], 'note': note,
                    'pan_step': num(cell(a, s + 1, y, 2), 50),
                    'vol_step': num(cell(a, s + 1, y, 3), 75),
                    'pan_track': num(cell(a, 0, y, 4), 50),
                    'vol_track': num(cell(a, 0, y, 5), 75),
                })
        t += hdr['steps'] * sps
    return events, t


def render(mod, bank, master_vol=100.0, tail=4.0):
    if not mod['sequence']:
        return None
    events, song_len = build_events(mod)
    if song_len <= 0:
        return None

    n = int((song_len + tail) * SR) + 1
    out = np.zeros((n, 2), dtype=np.float32)

    for ev in events:
        buf = bank.get(ev['inst']['sample'])
        if buf is None or len(buf) < 2:
            continue
        k = ev['note'] % 100
        rate = FREQOUT[k] / 44100.0 if k < len(FREQOUT) else 1.0

        # Volume. The game runs track gain through log10(x)/0.04 and step gain
        # through log10(x)/0.02, which as amplitudes are x^1.25 and x^2.5.
        tv = int(master_vol * ev['vol_track'] * 0.01) / 100.0
        sv = ev['vol_step'] / 100.0
        track_db = MUTE_DB if tv <= 0 else np.log10(tv) / 0.04
        step_db = MUTE_DB if sv <= 0 else np.log10(sv) / 0.02
        amp = db_to_amp(track_db + step_db)
        if amp <= 0.0:
            continue

        # Pan: track and step each map 0..100 onto -1..+1, and the two are summed.
        pan = float(np.clip(((0.02 * ev['pan_track']) - 1.0)
                            + ((0.02 * ev['pan_step']) - 1.0), -1.0, 1.0))
        left = np.cos((pan + 1.0) * np.pi / 4.0)
        right = np.sin((pan + 1.0) * np.pi / 4.0)

        # Note length. `stop` gates the note. The game's envelope block has a
        # quirk where a non-zero `sustain` writes over the stop length instead
        # of its own slot, so reproduce that rather than the intent.
        inst = ev['inst']
        gate = None
        if inst['stop'] > 0:
            gate = step_duration(inst['stop']) * ev['sps']
        if inst['sustain'] > 0:
            gate = step_duration(inst['sustain']) * ev['sps']

        natural = (len(buf) / rate) / SR
        loop_period = None
        if inst['loop'] == 100:
            loop_period = natural
        elif inst['loop'] > 0:
            loop_period = int(np.ceil(32.0 * inst['loop'] / 100.0)) * ev['sps']

        total = gate if gate is not None else natural
        if loop_period is None:
            total = min(total, natural)
        total = min(total, song_len + tail - ev['time'])
        if total <= 0:
            continue

        starts = [0.0]
        if loop_period and loop_period > 0.001:
            off = loop_period
            while off < total:
                starts.append(off)
                off += loop_period

        for off in starts:
            want = int(min(natural, total - off) * SR)
            if want <= 1:
                continue
            seg = resample(buf, rate, want)
            if len(seg) == 0:
                continue
            if gate is not None and len(seg) > 64:
                f = min(256, len(seg))          # short fade so a cut note does not click
                seg = seg.copy()
                seg[-f:] *= np.linspace(1.0, 0.0, f, dtype=np.float32)
            start = int((ev['time'] + off) * SR)
            end = min(start + len(seg), n)
            if end <= start:
                continue
            s = seg[:end - start] * amp
            out[start:end, 0] += s * left
            out[start:end, 1] += s * right

    # Fold whatever is still ringing past the end back over the start, so the
    # file loops seamlessly the way the page loop does in game.
    loop_n = int(song_len * SR)
    if 0 < loop_n < n:
        overflow = out[loop_n:]
        m = min(len(overflow), loop_n)
        out[:m] += overflow[:m]
        out = out[:loop_n]

    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > 1.0:
        out /= peak
    return out


def encode(pcm, path, fmt):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    args = ['ffmpeg', '-v', 'quiet', '-y', '-f', 'f32le', '-ar', str(SR),
            '-ac', '2', '-i', '-']
    args += {'ogg': ['-c:a', 'libvorbis', '-q:a', '4'],
             'opus': ['-c:a', 'libopus', '-b:a', '96k'],
             'm4a': ['-c:a', 'aac', '-b:a', '128k']}[fmt]
    args.append(path)
    subprocess.run(args, input=pcm.astype('<f4').tobytes(), check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True, help="the game's data/ directory")
    ap.add_argument('--out', required=True, help='directory to write rendered audio into')
    ap.add_argument('--format', default='ogg', choices=['ogg', 'opus', 'm4a'])
    ap.add_argument('--only', help='render only modules whose path contains this')
    args = ap.parse_args()

    data = os.path.abspath(args.data)
    mods = []
    for dirpath, _, files in os.walk(os.path.join(data, 'audio', 'hsm')):
        for f in sorted(files):
            p = os.path.join(dirpath, f)
            if (f.lower().endswith('.hsm') and os.path.getsize(p) > 0
                    and (not args.only or args.only in p)):
                mods.append(p)
    mods.sort()

    bank = SampleBank(data)
    written = skipped = 0
    manifest = {}
    for i, p in enumerate(mods, 1):
        rel = os.path.relpath(p, data).replace(os.sep, '/')
        try:
            mod = parse_module(p)
            pcm = render(mod, bank)
        except Exception as exc:                  # noqa: BLE001 -- report and keep going
            sys.stderr.write(f'  !! {rel}: {type(exc).__name__}: {exc}\n')
            skipped += 1
            continue
        if pcm is None or not pcm.size:
            sys.stderr.write(f'  -- {rel}: no pattern sequence, skipped\n')
            skipped += 1
            continue
        dst = os.path.join(args.out, os.path.splitext(os.path.basename(rel))[0] + '.' + args.format)
        encode(pcm, dst, args.format)
        manifest[rel.lower()] = {'file': os.path.basename(dst),
                                 'title': mod['title'], 'artist': mod['artist'],
                                 'seconds': round(len(pcm) / SR, 2)}
        written += 1
        sys.stderr.write(f'  [{i}/{len(mods)}] {os.path.basename(dst):40s} '
                         f'{len(pcm)/SR:6.1f}s  {mod["title"]}\n')

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, 'index.json'), 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    sys.stderr.write(f'rendered {written} modules, skipped {skipped}\n')


if __name__ == '__main__':
    main()
