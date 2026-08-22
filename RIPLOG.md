# Hypnospace Outlaw — asset rip & reverse-engineering log

Goal: understand the `.hsp` page format and render pages as HTML/CSS/JS.

Environment: Arch Linux (kernel 7.1.8-arch1-3), bash, python3.14.
Game: Hypnospace Outlaw, GOG build, installed via Heroic (Wine prefix).
Date started: 2026-08-18.

This is a record of how the formats were actually recovered, kept so the work can be
checked rather than taken on faith. It is not the build guide — for that see
[SETUP.md](SETUP.md), which uses the finished tools. Paths below are from the original
session; substitute your own install. No game asset is included in this repository.

---

## Step 1 — Copy the installed game tree

The game was installed through Heroic Games Launcher. Everything needed lives in the
install directory; no unpacking of an installer is required.

```bash
cp -r "$HOME/Games/Heroic/Hypnospace Outlaw/" hypnospaceFiles
```

Result: 699 MB under `hypnospaceFiles/data`, plus the NW.js runtime at the top level
(`HypnOS.exe`, `nw.dll`, `package.nw`, `Page Builder.exe`, `Sequencer.exe`).

`hypnospaceFiles/data/read this.txt` is a spoiler warning from the devs which also states
they deliberately did **not** encrypt or obfuscate any game data. Confirmed: every asset is
a plain file.

## Step 2 — Locate the page files

```bash
find hypnospaceFiles/data -type f -name "*.hsp" | wc -l   # 1292
```

Layout of `hypnospaceFiles/data`:

| Path | Contents |
|---|---|
| `hs/`, `hsa/`, `hsb/`, `hsc/` | The four in-game Hypnospace eras/chapters, one dir per zone |
| `ex/` | Extra/bonus pages (credits, hints, "history" museum pages, backer pages) |
| `images/` | Page art: gifs/pngs referenced by name from `.hsp` files |
| `audio/`, `video/` | Page media |
| `os/` | OS chrome: cursors, themes, wallpapers, screensavers |
| `misc/` | `*.ini` / `*.txt` game-logic data (ads, emails, cases, progression) |
| `downloads/` | In-game downloadable packs |
| `modpack/` | Bundled example mod ("HypnOS 95") |

`misc/pgbuildtips.txt` is the in-game Page Builder's help text and documents the text escape
codes directly (`/n` line break, `/t` tab, `/p` player name).

## Step 3 — Extract the game code (NW.js)

`package.nw` is a plain zip containing a Construct 2 HTML5 export.

```bash
mkdir -p work/pkg && cd work/pkg && unzip -oq ../../hypnospaceFiles/package.nw
```

Notable files:

- `c2runtime.js` (1.9 MB) — the Construct 2 engine, minified.
- `data.js` (4.5 MB) — the Construct 2 **project model** as JSON with a UTF-8 BOM:
  object types, layouts, and compiled event sheets. This is the authority on how `.hsp`
  files are interpreted.
- `package.json` — NW.js manifest, `"name": "HypnOS"`, version 2.5.

To parse `data.js`:

```python
import json
d = json.loads(open('data.js', encoding='utf-8-sig').read())['project']
```

`project[5]` holds 9 layouts (`BootScreen`, `Menu`, `HypnOS`, `Highway`, `Dummy`, `RSOD`,
`BIOS`, `Y2K`, `ModIO`); `project[6]` holds 16 event sheets. Object-type *names* are
minified to `t0`, `t1`, ... so the event sheets must be read via their preserved string
literals and numeric constants rather than by symbol name.

## Step 4 — Decompile the Construct 2 event sheets

Construct 2 minifies object-type *names* (`t0`, `t1`, …) but keeps every string literal,
numeric constant and ACE reference. `c2runtime.js` ends with an `cr.getObjectRefTable()`
that maps the numeric references in `data.js` back to real plugin/behaviour methods:

```bash
python3 -c '
s=open("work/pkg/c2runtime.js",encoding="utf-8",errors="replace").read()
i=s.index("cr.getObjectRefTable = function () { return [")
j=s.index("[",i); k=s.index("];",j)
print(len([x for x in s[j+1:k].split(",") if x.strip()]), "entries")'
# 854 entries
```

`tools/c2decomp.py` joins the two and prints readable pseudo-code. The expression and
statement grammars were read straight out of `c2runtime.js` (`function ExpNode`,
`function Action`, `function Condition`, `function EventBlock`, `function Parameter`).

```bash
python3 tools/c2decomp.py work/pkg all > sheets.txt          # ~36k lines
python3 tools/c2decomp.py work/pkg HypnOS --grep 'BuildWebpage'
```

The functions that define the `.hsp` format are all in the `HypnOS` sheet:

| function / group | what it told us |
|---|---|
| `LoadWebpage` | path resolution, the `home.hsp` → `zone.hsp` directory fallback |
| `URLtoCurrent` | links are authored against a logical root and served from the *current capture* |
| `BuildWebpage`, `UpdatePage` | the `Webpage` (x=0) fields: title, author, height×32, music, background, cursor |
| `LoadElement`, `UpdateElement` | every `Gif` and `Text` property, and which array slot each comes from |
| `Element Animations and Effects` | the animation formulas |
| `Load Gif` / `LoadGifs` | the image registry: `gifs/`, `static/`, `shapes/`, `wordart/`, and `.speed` files |
| `UpdateZOrder` | z-order is the array order **reversed** |
| `ElementEventWeb` | conditional state selection |
| `ColorToRGB` | colours are packed BGR |
| `Scripts` | the `cmd:param\|cmd:param` mini-language used by links and page onload |

Two things are *not* in the event sheets and had to come from elsewhere:

- **`ReplaceText`** (the `/n`, `/t`, `/p`, `#VAR#` escapes) is native JS —
  `HypnoSpecial_ReplaceText` in `c2runtime.js`.
- **Font geometry** is stored as editor properties on the three `Spritefontanim`
  objects. They are in the layout instance data in `data.js` (cell 7×7 / 14×12 / 21×21,
  8 columns, and the character set). The `replacecolor` tolerances that prove the
  recolour is an exact swap are in the same instance records
  (`[17,17,38, …, 0.01]` for the background, `[0,0,0, …, 0.01]` for text).

## Step 5 — Convert

`tools/hspconv.py` reads the game's `data/` directory and writes a browsable static site.

```bash
# fast: symlinks assets back into the game install (26 MB, needs the game present)
python3 tools/hspconv.py --data hypnospaceFiles/data --out site

# portable: copies only the assets actually referenced
python3 tools/hspconv.py --data hypnospaceFiles/data --out site --pages hs --copy-assets
```

Options: `--pages` picks capture directories (default `hs hsa hsb hsc ex`), `--flags`
sets story flags so conditional element states resolve to something other than `DEFAULT`,
`--limit` caps the page count.

All 1292 pages convert in about 1.5 s. Open `site/index.html`; it works from `file://`
as well as over HTTP.

## Step 6 — Check

```bash
python3 tools/hspaudit.py --site site --data hypnospaceFiles/data
```

```
pages: 1292   elements: {'text': 11979, 'gif': 14668}
unresolved images: 0 distinct, 0 references
unresolved fonts:  0 distinct, 0 references
links that resolve to no exported page: 13 distinct, 48 references
```

Every one of the 14 668 image references and 11 979 font references resolves. The 48
dead links point at 13 pages that are **not in the shipped data at all** — cut content
(`hs\11_the comic shop\illegra.hsp`; there is no comic-shop zone in any capture),
placeholders in the `template2.hsp` pages (`01.hsp`, `02.hsp`), and
`~truetranquilityno.hsp`. They are dead in the game too.

Note that some links look broken but are not: a handful carry the "no link" sentinel
glued to the path (`-1hs\02_the cafe\~thedumpsterhallo.hsp`). `URLtoCurrent` replaces
that entire first segment with the current capture, so they resolve fine — which is why
the converter reproduces the behaviour rather than special-casing it.

## Step 7 — Verify visually

Rendered headlessly and compared against the game's own look:

```bash
chromium --headless --disable-gpu --allow-file-access-from-files \
  --virtual-time-budget=5000 --window-size=320,1000 \
  --screenshot=out.png "file://$PWD/site/pages/hs/02_the cafe/chitchat.html"
```

Two bugs were caught this way and fixed:

1. `-1`, not `0`, is the off-sentinel for the gif sway/dither speeds (`z[12]`–`z[14]`).
   The runtime gates them on `>= 0`, and `0` genuinely does collapse the element — it is
   just that no shipped page uses `0`. Treating `0` as "off" made every affected gif
   render at sub-pixel size.
2. The `alphadither` shader's parameter runs the other way round from what the name
   suggests: `f_dither = 0` is fully transparent, `1` is opaque.

## Step 8 — Page music

Two formats, handled differently.

### `.ogg` pages

450 pages point at one of 79 `.ogg` files in the game's audio tree. Each has a sibling
`.txt` holding `title|artist`, which is what `UpdatePageMusic` reads for the now-playing
line. The converter picks both up; the renderer plays them with a looping `<audio>`.

### `.hsm` pages

527 pages point at a `.hsm`, which turned out to be a **sample-based tracker module** —
another `c2array`. See [FORMAT.md §10](FORMAT.md#10-page-music-and-the-hsm-format).

The playback engine lives in the HypnOS sheets, not the Sequencer, so the same
decompilation covered it:

| where | what it gave |
|---|---|
| `Play Music Sounds` group | axis layout: `x` = step+1, `y` = 5×pattern + track, `z` = parameter |
| `BPM Timer` sheet | `secPerStep = 1/(BPM/60)/4` — a step is a sixteenth |
| `Step` function | the pattern sequence lives in row `y=0`, slot `z=10`, one entry per `x` |
| `FREQOUT` global | the 60-entry note → resampling-rate table |
| the envelope block | note gate, loop period, and the sustain-writes-to-stop bug |

`Sequencer.exe` and `Page Builder.exe` each have their own NW.js package appended to the
binary, which is worth knowing about:

```bash
mkdir -p work/seq && cd work/seq && unzip -oq ../../hypnospaceFiles/Sequencer.exe
```

Both were exported **with script minification on**, unlike the main game — their
`c2runtime.js` has no `getObjectRefTable` and mangled identifiers, so `c2decomp.py` cannot
read them. They were not needed in the end; the main game's playback code was enough.

Rendering:

```bash
python3 tools/hsmrender.py --data hypnospaceFiles/data --out site/media/hsm
```

Decodes each referenced sample once through ffmpeg, mixes the sequence with numpy, and
encodes back to Ogg Vorbis. 103 of 108 modules render in about two minutes and 51 MB. The
five that do not have an empty pattern sequence — they are dev scratch files
(`echotest`, `looptest`, `newmusic`, …) that would be silent in game too, and no page
references them.

Notes are re-triggered per event and mixed with linear-interpolated resampling; whatever
is still ringing past the end of the sequence is folded back over the start so the file
loops seamlessly, which is how the page loop behaves in game.

**Order matters**: render before converting, because `hspconv.py` reads
`<out>/media/hsm/index.json` to attach titles and artists.

Verified in a real browser rather than by inspection, since autoplay and codec support are
where this breaks:

```bash
chromium --headless --allow-file-access-from-files \
  --autoplay-policy=no-user-gesture-required --virtual-time-budget=25000 \
  --dump-dom "file://$PWD/site/pages/.../page.html"
# meta dur=349.5 loop=true | PLAYING | play() resolved
```

`--virtual-time-budget` fast-forwards timers but not audio playback, so the test has to be
event-driven (`loadedmetadata`, `playing`) rather than "wait N seconds then read
`currentTime`".

Known gaps: one page-referenced module, `artie-globalgroove.hsm`, is absent from the game
data entirely (2 pages), and the per-step effect slots are not rendered. Safari does not
support Ogg Vorbis — `hsmrender.py --format m4a` or `opus` covers that if needed.

## Step 9 — Strip the viewer back to the page

The first exports wrapped each page in a title bar, a caption line and a music player.
Useful while reverse-engineering, wrong for looking at the result: a Hypnospace page is
300 pixels of art with no frame around it.

The viewer now renders the page alone, scaled by an integer factor derived the way the
game derives its own (its screen is 480&times;270 and scales up whole), with everything
else moved to the keyboard &mdash; see the table in [README.md](README.md).

Two things worth recording, both found by screenshotting rather than reading:

- **Auto-fit needs a real viewport.** Headless Chromium at `--window-size=1100,760`
  reports `innerHeight` of 673, not 760, so a fit rule tuned against the window size
  picks a scale that is one step too small in real browsers.
- **The page needed a stacking context.** Elements carry `z-index` up to 9999 to
  reproduce the game's paint order. `#hsp-page` was `position: relative` with no
  `z-index`, which does *not* create a stacking context, so those 9999s competed
  directly with the fixed-position help overlay and painted straight over it.
  `isolation: isolate` on the page container contains them.

Zoom is only remembered in `localStorage` when it is chosen deliberately, so a page
opened later on a differently-sized window still fits itself by default.

## Files

| path | what |
|---|---|
| `FORMAT.md` | the format specification |
| `SETUP.md` | how to rebuild the export from your own copy of the game |
| `build.sh` | one-shot rebuild: music, pages, audit |
| `tools/c2decomp.py` | Construct 2 `data.js` → readable pseudo-code |
| `tools/hspconv.py` | `.hsp` → static HTML site |
| `tools/hsmrender.py` | `.hsm` tracker modules → looping audio files |
| `tools/hspaudit.py` | checks a converted site for unresolved assets, music and dead links |
| `tools/hsppack.py` | packs a custom `.hsp` into a standalone page with only the assets it uses |
| `web/hsp.js` | browser runtime: spritefont layout, gif player, animations |
| `web/hsp.css` | page styling: integer zoom, pixel scaling, link marching-ants |
| `hypnospaceFiles/` | the copied game install (never in version control) |
| `work/pkg/` | unzipped `package.nw` (not in version control) |
