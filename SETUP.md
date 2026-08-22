# Setup

This repository ships the tools and the specification, not the game. To get a browsable
export you supply your own copy of Hypnospace Outlaw and rebuild locally. Nothing leaves
your machine, and the game's files are only ever read.

## 1. Requirements

| | | |
|---|---|---|
| Python | 3.8+ | `hspconv.py`, `hsppack.py` and `hspaudit.py` need nothing but the standard library |
| numpy | any recent | only for `hsmrender.py` (tracker music) |
| ffmpeg | any recent | only for `hsmrender.py`, to decode samples and encode the result |

```bash
# Arch
sudo pacman -S python python-numpy ffmpeg
# Debian/Ubuntu
sudo apt install python3 python3-numpy ffmpeg
# macOS
brew install python numpy ffmpeg
```

Or keep numpy local to the project:

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install numpy
```

Without ffmpeg and numpy everything still builds — `build.sh` says so and carries on —
but the 527 pages scored with a `.hsm` tracker module come out silent. The 450 pages
using a plain `.ogg` are unaffected, since those are copied rather than rendered.

## 2. Find your game install

You need the directory containing `data/`, which in turn contains `hs/`, `images/` and
`misc/`. Typical locations:

| Store | Path |
|---|---|
| Steam (Linux) | `~/.steam/steam/steamapps/common/Hypnospace Outlaw` |
| Steam (macOS) | `~/Library/Application Support/Steam/steamapps/common/Hypnospace Outlaw` |
| Steam (Windows) | `C:\Program Files (x86)\Steam\steamapps\common\Hypnospace Outlaw` |
| GOG (Windows) | `C:\GOG Games\Hypnospace Outlaw` |
| GOG via Heroic | `~/Games/Heroic/Hypnospace Outlaw` |
| itch.io app | `~/.config/itch/apps/hypnospace-outlaw` |

In Steam you can always get there with *right-click the game → Manage → Browse local
files*. If none of these match, search for the marker file:

```bash
find ~ -name "read this.txt" -path "*Hypnospace*" 2>/dev/null
```

All builds — Steam, GOG, itch, Windows, Linux and macOS — carry the same `data/` tree,
so any of them works. The build reads only `data/`; the NW.js runtime around it
(`HypnOS.exe`, `package.nw`, the DLLs) is not touched.

## 3. Build

```bash
./build.sh "/path/to/Hypnospace Outlaw"
```

It validates the path, checks the toolchain, renders the tracker music, converts all
1292 pages and then audits the result. Expect a few minutes, most of it music.

Useful flags:

| flag | |
|---|---|
| `--out DIR` | write somewhere other than `./site` |
| `--no-music` | skip the tracker render |
| `--copy-assets` | self-contained export (see below) |
| `--pages hs` | convert one chapter only — handy for a quick test |

Then open `site/index.html`. It is a plain static directory: no server needed, though
`python3 -m http.server` from inside `site/` works too.

### Symlinked vs. copied assets

By default `site/assets` is a **symlink** to the game's `data/` directory. The export is
then about 1 MB of HTML plus the rendered music, and no game asset is duplicated. The
trade-off is that the export only works on this machine, with the game still installed
at that path.

`--copy-assets` instead copies the ~14 700 referenced files into `site/assets`, giving a
directory you can move to another machine or serve from a web host. Bear in mind that
such an export **does** contain the game's copyrighted art and audio, so it is for your
own use — don't publish it.

## 4. Verify

```bash
python3 tools/hspaudit.py --site site --data "/path/to/Hypnospace Outlaw/data"
```

Against an unmodified copy this reports 1292 pages, zero unresolved images, zero
unresolved fonts, and 48 links pointing at 13 pages that do not exist in the game data.
Those are cut content and are expected — see RIPLOG.md step 7.

## Troubleshooting

**`does not look like a Hypnospace Outlaw install`** — point at the directory that
*contains* `data/`, or at `data/` itself. If you passed a `.exe`, a shortcut or the
Steam library root, go one level in.

**Pages render but every image is missing** — the `site/assets` symlink is dangling
because the game moved or was uninstalled. Rebuild, or re-point the link:

```bash
ln -sfn "/new/path/to/Hypnospace Outlaw/data" site/assets
```

**Music never starts** — browsers refuse to play audio before the user interacts with
the page. Click anywhere, or press <kbd>m</kbd>. After the first gesture the preference
follows you from page to page for the rest of the session.

**Some pages are silent** — either they have no music (315 of them), or the `.hsm`
render was skipped. Check that `site/media/hsm/index.json` exists and re-run
`hsmrender.py` if not.

**`no image named "..."` when packing your own page** — the name in the `.hsp` must
match a file or folder under `data/images/{gifs,static,shapes,wordart}`, without its
extension and case-insensitively. `hsppack.py` prints every name it could not find.

**`ffmpeg: command not found` during the music render** — install ffmpeg (see above), or
pass `--no-music`.

**Opening a page directly with `file://` shows nothing** — some browsers block the
`fetch` of page data over `file://`. Serve the directory instead:

```bash
cd site && python3 -m http.server 8000   # then visit localhost:8000
```

## Reproducing the reverse engineering

The build above just *uses* the format. To check the work rather than trust it, RIPLOG.md
walks through how the format was recovered from the game's own code — unpacking the NW.js
bundle, decompiling the Construct 2 event sheets with `tools/c2decomp.py`, and reading the
routines that load a page. Every step is a command you can re-run against your own copy.
