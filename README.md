# hsphtml

Reverse-engineered **Hypnospace Outlaw**'s `.hsp` page format and `.hsm` tracker music
format, plus a converter that renders the game's 1292 pages as plain HTML/CSS/JS.

- **[FORMAT.md](FORMAT.md)** — the format specification.
- **[RIPLOG.md](RIPLOG.md)** — how the formats were decoded from the game's own code,
  reproducibly, step by step.
- **[SETUP.md](SETUP.md)** — detailed setup, platform notes and troubleshooting.

## This repository contains no game assets

Hypnospace Outlaw is a commercial game and its pages, art, fonts and music are the
copyrighted work of Tendershoot, M. Jones and No More Robots. **None of it is
distributed here.** What you get is the specification and the tools; you supply the
game, which you must own, and the tools rebuild the export locally on your machine.
Nothing is uploaded anywhere and the game's files are only ever read.

## Quick start

You need **Python 3.8+**, and for the tracker music **ffmpeg** and **numpy**.

```bash
./build.sh "/path/to/Hypnospace Outlaw"
xdg-open site/index.html
```

Point it at the game's install directory (or its `data/` subdirectory — either works).
`./build.sh --help` lists the usual install locations for Steam, GOG/Heroic and itch.
The whole thing takes a few minutes, most of it rendering music.

That is equivalent to running the three tools by hand:

```bash
GAME="/path/to/Hypnospace Outlaw/data"
python3 tools/hsmrender.py --data "$GAME" --out site/media/hsm   # tracker music
python3 tools/hspconv.py   --data "$GAME" --out site             # pages
python3 tools/hspaudit.py  --site site    --data "$GAME"         # verify
```

Run `hsmrender.py` first: `hspconv.py` reads the manifest it leaves behind, so that
pages backed by a `.hsm` come out with a real `<audio>` source and a track title.

By default `site/assets` is a symlink to the game's `data/` directory, so the export
stays small and no asset is ever duplicated. Pass `--copy-assets` to `build.sh` (or to
`hspconv.py`) for a self-contained directory you can move or serve — but note that such
a directory *does* then contain game assets, so keep it to yourself.

### Checking it worked

`hspaudit.py` re-reads the export and reports anything that failed to resolve. Against
an unmodified copy of the game it should print:

```
pages: 1292   elements: {'text': 11979, 'gif': 14668}
unresolved images: 0 distinct, 0 references
unresolved fonts:  0 distinct, 0 references
links that resolve to no exported page: 13 distinct, 48 references
```

Those 48 dead links are expected: they point at 13 pages that are not in the shipped
game data at all — cut content that survived only as links. Everything else resolves.

## What it does

A `.hsp` file is a Construct 2 array export describing a 300-px-wide page: a metadata
row plus a list of `Gif` and `Text` elements, each with up to 20 conditional states.
The converter resolves one state per element, looks every image and bitmap font up in
the same registry the game builds at startup, resolves links the way `URLtoCurrent`
does, and emits one HTML file per page.

Page music comes in two forms. 450 pages reference a plain `.ogg`; 527 reference a
`.hsm`, which is a sample-based tracker module. `tools/hsmrender.py` bounces those down
to looping audio offline, so both end up as an ordinary `<audio>` element.

### The viewer

An exported page is **just the page** — no title bar, caption or player. It is 300
device pixels wide, scaled up by a whole number the way the game scales its 480×270
screen, with `image-rendering: pixelated` throughout so it stays crisp.

Hovering a link draws a marching-ants box 2px around it, and only around the one under
the pointer. That is what the game does: each linked element gets a nine-patch box
(`pagelinkgif-sheet0.png`) that is created hidden and shown by the `Links` group only
while `Mouse.IsOverObject` holds. The dashes are reproduced from that sprite — 1px
light blue over a 1px dark drop shadow, 2px on / 2px off, stepping one pixel clockwise
at 8fps. On a rotated `Gif` the box turns with the image, where the game keeps it
axis-aligned; that affects 89 of the 3971 linked elements.

Everything else is on the keyboard:

| key | |
|---|---|
| <kbd>+</kbd> / <kbd>-</kbd> | zoom in / out (the game binds these too) |
| <kbd>0</kbd> | back to auto-fit |
| <kbd>m</kbd> | toggle music |
| <kbd>Esc</kbd> | back to the index |
| <kbd>?</kbd> | page title, source path and this list |

Music has no visible player. Browsers refuse to start audio without a user gesture, so
the first click or keypress starts it and the choice then rides along in `sessionStorage`
— roughly how the game's own Autoplay setting behaves.

`web/hsp.js` reimplements the parts of HypnOS that draw a page — Construct 2's
Spritefont word-wrap and glyph blitting onto a canvas, the frame-sequence gif player,
and the sway / spin / marquee / typewriter / colour-cycle animations — so pages animate
and link to each other as they do in game.

## Tools

| | |
|---|---|
| `build.sh` | one-shot rebuild from your game copy |
| `tools/hspconv.py` | `.hsp` → static site |
| `tools/hsmrender.py` | render `.hsm` tracker modules to looping audio |
| `tools/hspaudit.py` | verify a converted site (unresolved assets, music, dead links) |
| `tools/c2decomp.py` | general-purpose Construct 2 `data.js` decompiler, used to read the game's logic |

`c2decomp.py` is not part of the build. It is the tool the format was reverse-engineered
*with*, kept here so the work in RIPLOG.md can be repeated and checked.

## Docs

`docs/hsp-format.html` is FORMAT.md as a standalone web page.

## Licence

The tools, viewer runtime and documentation here are original work, released into the
public domain under **[CC0 1.0 Universal](LICENSE)**. Do what you like with them; no
attribution required, though it is always welcome.

That dedication covers *this repository only*. It cannot and does not extend to
Hypnospace Outlaw itself — the game's pages, art, fonts and music remain the copyright
of their authors, are not included here, and are not mine to license. An export you
build is made from your own copy for your own use; the CC0 grant does not make it
redistributable.
