# The Hypnospace Outlaw `.hsp` page format

Reverse-engineered from the shipped game (GOG build, HypnOS 2.5). Every claim below is
traced to the game's own code — see [RIPLOG.md](RIPLOG.md) for how to reproduce the
extraction, and `tools/c2decomp.py` for the decompiler used to read it.

## 1. Container

A `.hsp` file is a **Construct 2 Array export**: UTF-8 JSON, no BOM, one object.

```json
{"c2array": true, "size": [W, 21, 21], "data": [ ... ]}
```

`data` is indexed `data[x][y][z]`:

| axis | range | meaning |
|---|---|---|
| `x` | `0 .. W-1` | **element index**. `x = 0` is always the page itself. |
| `y` | `0 .. 20` | `y = 0` is the element *header*; `y >= 1` are **states** |
| `z` | `0 .. 20` | property slot |

All 1292 shipped pages use `size[1] == size[2] == 21`, so there is room for one header
row plus 20 states, each with 21 properties. Unused cells are the empty string `""`.
Values are stored as JSON strings almost everywhere; a few are stored as JSON numbers.
The runtime coerces with `int()`, so **treat every cell as a string and parse it
yourself** — never rely on the JSON type.

### Header row (`y = 0`)

| z | meaning |
|---|---|
| 0 | element type: `"Webpage"`, `"Gif"`, or `"Text"` (those three, plus blank, are all that exist) |
| 1 | element id (author's numbering; the runtime overwrites this slot with a live object UID) |
| 2 | element name — the label shown in the Page Builder's element list |

`x = 0` always has type `Webpage` and carries the page's own metadata; its header row is
otherwise empty.

### State rows (`y >= 1`)

`z = 0` of each state row is the **state name**. `y = 1` is always `"DEFAULT"`.
Later rows are conditional variants — story flags (`TRUETRANQUILITY`, `ABBYDETAINED`,
`MINDCRASH`, `GOOPERREMOVED`, …) or authoring scratch slots (`TEMP 01` … `TEMP 17`).
57 distinct names appear across the shipped pages.

**State selection** (`ElementEventWeb`): walk `y = 1, 2, 3, …` until the state name is
empty; the **last** row whose (trimmed, upper-cased) name is a currently-true flag wins.
`DEFAULT` is always true, so `y = 1` is the fallback. Each element resolves its state
independently. For a static export, use `y = 1`.

## 2. Coordinate system

The page is **`PAGEWIDTH = 300` px wide**. Page height is `max(int(Webpage z[3]), 1) * 32` px.

## 3. `Webpage` (x = 0) properties

| z | name | notes |
|---|---|---|
| 1 | title | shown in the browser title bar |
| 2 | author | citizen ID; `""` or `"0"` means no author. A leading `*` is stripped for display |
| 3 | height | page height **in 32-px units** |
| 4 | music | path to an `.ogg` or a `.hsm` tracker module — see §10. `0` / `-1` / `""` = silence |
| 5 | background | file in `images/bgs/`, tiled. The literal `000.png` means "flat colour" |
| 6 | cursor | page cursor id, `0` = default |
| 7 | bg colour | packed colour, **only used when `z[5] == "000.png"`** |
| 8 | tags | search text. Everything after the first `>` is the keyword list; the part before it is the human-readable blurb |
| 9 | icon | frame index of the `zoneselectorb` gif used for this page in zone-hub listings |
| 10 | isHomepage | `1` = this is a citizen's homepage (affects search indexing) |
| 11 | onload script | `cmd:param\|cmd:param` — see §7 |

## 4. Common element properties (`Gif` and `Text`)

| z | `Gif` | `Text` |
|---|---|---|
| 1 | **x**, px, of the image **centre** | **x offset**, in *percent of PAGEWIDTH*, from the centred box |
| 2 | **y**, px, of the image **centre** | **y**, px, of the box's **top-left** |
| 3 | HSL adjust (see below) | box **width in percent** of PAGEWIDTH; `0` means 100% |
| 5 | gif/image name (see §6) | the text (see §5) |
| 10 | link / action string (§7); `-1` or `""` = none | same |
| 11 | law category tag (`6`/`99` mark law-violating elements) | same |

`Gif z[3]` is *only* read when it contains a comma. `h,s,l` then feeds the `AdjustHSL`
shader (hue rotate, saturation %, lightness %, e.g. `0,500,100`). Anything else
(`-1`, `60`, …) disables the effect and is ignored — those are leftovers.

`Gif` z[4] and z[17] are **not read by the shipped runtime at all**. They hold legacy
data (case names, an old animation-speed field).

### `Gif`-specific

| z | meaning |
|---|---|
| 6 | scale multiplier (`1`, `0.5`, `0.25`, …) |
| 7 | angle in degrees |
| 8 | `1` = mirror horizontally |
| 9 | `1` = flip vertically |
| 12 | horizontal sway speed; `0` = off. `width = imgW * scale * sin(phase)`, `phase += z12*0.1*60*dt`, applied at 10 fps |
| 13 | vertical sway speed; same but on height |
| 14 | dither/fade pulse speed; drives the `NewDither` shader's alpha, ping-ponging over a 0–200 phase |
| 15 | rotation mode: `0` none, `1` wobble (`angle = base + sin(phase)*20`, `phase += z16*0.25*60*dt`), `2` spin (`angle = base + phase`, `phase += z16*0.1*60*dt`) |
| 16 | rotation speed |
| 18 | **frame index** — the still frame for static/button modes, or the start-frame offset while animating |
| 19 | `1` = sync: the element's animation is restarted in lockstep with every other synced gif |
| 20 | animation mode: `0` loop, `-1` still (show frame `z[18]`), `-2` three-state button (`z[18]`, `+1` on hover, `+2` while held), `>0` animate only while hovered |

Positive `sin()` is in **degrees** throughout (Construct 2 convention).

### `Text`-specific

| z | meaning |
|---|---|
| 6 | text colour (packed, §8) |
| 7 | font name, e.g. `HypnoFont`, `Bookstore`, `ClownHand` |
| 8 | style: first char is the size class `0`/`1`/`2`, second is `n` (normal) or `b` (bold) — e.g. `0n`, `1b` |
| 9 | horizontal align: `0` left, `1` centre, `2` right |
| 12 | animation: `0` none, `1` typewriter (types out, pauses, deletes, repeats), `2` vertical sine bob (`y += height*0.25*sin(phase)`), `3` horizontal marquee (scrolls right-to-left across the page) |
| 13 | animation speed (default `10`) |
| 14 | second colour; `-1` = none. Otherwise the colour ping-pongs between `z[6]` and `z[14]` |
| 15 | colour-cycle speed (default `10`) |
| 16 | `1` = do not recolour (draw the font sheet's own pixels). Also forced when the font is `DesignElements` |

Layout: the text box is first centred in the page, then offset:

```
boxWidth = (z3 == 0) ? 300 : 300 * min(int(z3) * 0.01, 100)
boxX     = int((300 - boxWidth) / 2) + int(z1) * 3      // 3 == 300 * 0.01
boxY     = int(z2)
```

The box's origin is its **top-left**; a `Gif`'s origin is its **centre**.

## 5. Text escapes

Implemented natively as `HypnoSpecial_ReplaceText`. Applied in order:

| input | output |
|---|---|
| `/n` | line break |
| `//n` | a literal `/n` (likewise `//N`) |
| `/t` | tab — one glyph, `8 - 1` space-widths wide |
| `//t` | a literal `/t` (likewise `//T`) |
| `/p` | the player's name (prefixed with a zero-width `§` marker) |
| `//p` | a literal `/p` (likewise `//P`) |
| `’` | `'` |
| `#NAME#` | the value of script variable `NAME` |
| `#ConsoleA#` … `#ConsoleY#` | gamepad button glyphs |

## 6. Image lookup

`Gif z[5]` is a **name**, matched case-insensitively against a registry built at startup
by scanning four directories under `data/images/`, in this order:

1. `gifs/<name>/` — a **directory** of frames. Files are used in listing order; those not
   ending in `.gif/.jpg/.jpeg/.bmp/.png` are skipped. A file named `NN.speed` sets the
   frame rate (`int` of its first two characters); the default is **5 fps**.
2. `static/<name>.<ext>` — single image, 0 fps.
3. `shapes/<name>.<ext>` — single image, 0 fps.
4. `wordart/<name>/` — directories of per-letter glyph images.

Page backgrounds come from `images/bgs/<Webpage z[5]>` (lower-cased) and tile.

## 7. Links, actions and scripts

`z[10]` on an element, and `z[11]` on the page, hold a `|`-separated list of
`command:parameter` pairs. A bare path with no `:` is a page link. Commands seen in the
shipped data and confirmed in the script dispatcher include:

| command | effect |
|---|---|
| `webpage:<path>` | navigate to another `.hsp` (backslash-separated, zone-relative) |
| `func:<Name>` | invoke a built-in UI function (`Inbox`, `Cases`, `Downloads`, …) |
| `anchor:<n>` | scroll the page to `n * 32` px |
| `tooltip:<text>` | hover text |
| `sfx:<path>` | play a sound |
| `downloadfile:` `openfile:` `password:` `wait:` `signal:` `waitsignal:` `buy:` `groupactive:` `outlawreward:` `hypii:` `hypiispeak:` `day:` | game-logic commands |
| `SearchGo:<query>` | run a search |
| `Event:<state>,...` | set a story flag (this is what switches elements to a non-`DEFAULT` state) |
| `virus:<name>,<n>` | infect the page |
| `setloadspeed:<n>` | override the simulated load time |

Command names are matched case-insensitively.

### How a link looks

Every linked element gets a nine-patch box pinned to it — `t160` for a `Gif`, `t161` for
a `Text`, both drawn from `pagelinkgif-sheet0.png`. For text it is created at
`X-2, Y-2` sized `W+4, H+4`, i.e. sitting 2px outside the element.

The box is marching ants. Its `Default` animation is **4 frames at 8 fps, looping**, with
9-patch margins of 4 on every side, so the edge tile is 4px: two pixels of dash, two of
gap, stepping one pixel per frame — a full cycle twice a second. The step direction is
clockwise (the top edge moves right, the left edge moves up). Each dash is one pixel of
`#9ac7f5` with a one-pixel `rgba(33,33,73,.63)` drop shadow down and to the right.

(The sheet also holds a 16-frame `Old` animation of 24×24 frames. It is not the one the
object uses.)

It is created with `SetVisible(0)` and stays hidden. The `Links` group shows it only
while the pointer is over it: the whole reveal sits under `Mouse.IsOverObject`, the
matching `Else` hides every box, and a sweep hides any box whose UID is not the hovered
`linkUID`. So exactly one box is ever on screen, and only while hovered — links are
otherwise unmarked.

(`t415` is the *family* grouping `t160` and `t161`, which is what the hover logic
actually picks.)

## 8. Colours

Colours are packed decimal integers in **BGR** order — the low byte is red:

```
r =  c        & 255
g = (c >>  8) & 255
b = (c >> 16) & 255
```

(From `ColorToRGB`: `b = floor(c/65536)`, `g = floor((c - b*65536)/256)`, `r = rest`.)

Recolouring uses Construct 2's `replacecolor` shader with a **tolerance of 0.01**, i.e.
an exact swap of one source colour:

- **Text**: source is pure black `(0,0,0)`. The font sheets are black glyphs on
  transparency, so this is equivalent to filling the glyph mask with the target colour.
- **Page background**: source is `(17,17,38)` — the exact colour of `images/bgs/000.png`.
  So a page whose background is `000.png` is simply a flat fill of `Webpage z[7]`.

## 9. Fonts

Fonts are **bitmap sprite sheets**, not vector fonts: `images/fonts/<name><size><style>.png`
(all lower-case), e.g. `hypnofont0n.png`, `clownhand1b.png`.

Each sheet is a grid, **8 columns**, filled row-major with this character set:

```
ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.,;:?!-_~#"'&()[]|`\/@°+=*$£€<>
```

Size class 0 additionally appends `%■▲`.

| size class | cell | sheet |
|---|---|---|
| `0` | 7 × 7 | 56 × 84 |
| `1` | 14 × 12 | 112 × 144 |
| `2` | 21 × 21 | 168 × 252 |

Per-font metrics live in `images/fonts/fontdata.ini`, keyed by `<Font><size><style>`:

```ini
[HypnoFont0n]
spacing=0
lineheight=1
charwidths=.,li^2^|;:!'` [(^3^)]<>ITZjcnrtxt1^4^...
```

`charwidths` is a `^`-separated alternating list of *character set* and *pixel width*.
Any character not listed keeps the cell width (7, 14 or 21). `spacing` is added between
characters, `lineheight` between lines (it may be negative).

Text layout is Construct 2's `Spritefont` algorithm: word-wrap at the box width
(breaking on space, tab and `-`), `measureWidth = Σ(charWidth * scale + spacing) - spacing`,
and lines are aligned inside the box using `z[9]`.

## 10. Page music and the `.hsm` format

`Webpage z[4]` names either a plain `.ogg` or a `.hsm` module. The runtime branches on
the extension: an `.ogg` is handed to the audio plugin and its `title|artist` comes from a
sibling `.txt`; anything else is `JSONLoad`ed as an array and sequenced.

Across the shipped pages: 450 use an `.ogg` (79 distinct files), 527 use a `.hsm`
(68 distinct modules), and 315 are silent.

### Container

A `.hsm` is another `c2array`, and like `.hsp` it overloads its axes:

| axis | meaning |
|---|---|
| `x` | step within the pattern, **1-based** (`PlayStep = CurrentStep + 1`) |
| `y` | `5 × pattern + track`, with tracks numbered **1..5** |
| `z` | per-step parameter |

Row `y = 0` and column `x = 0` are used for something else entirely:

- **`x = 0, y = 0`** — `[title, artist]`.
- **`y = 0`, any `x`** — the **instrument table**. Slot `x` holds `z[0]` sample path
  (relative to `audio/`, no extension — always `.ogg` in practice), then `z[1]` loop
  period, `z[2]` stop, `z[3]` sustain, `z[4]` attack.
- **`y = 0`, `z = 10`** — doubling as the **pattern sequence**. Position `x` holds that
  slot's pattern index **plus one**; `0` means an empty slot. Playback walks `x` upward,
  skipping empties, and loops at the end.
- **`x = 0, y = 5p + 1`** — pattern `p`'s header: `z[0]` BPM, `z[1]` steps per pattern
  (always 32 in shipped modules), `z[2]` beat division. It shares that row with track 1,
  whose pan and volume sit at `z[4]` and `z[5]`.

Track pan and volume for track `t` of pattern `p` are at `x = 0, y = 5p + t`, `z[4]`
and `z[5]`.

### Steps

A step is a sixteenth note: `secPerStep = 1 / (BPM / 60) / 4`.

| z | meaning |
|---|---|
| 0 | instrument slot. **`0` means no note** — this is the gate the runtime tests |
| 1 | note. `100` is a rest |
| 2 | pan, 0–100 |
| 3 | volume, 0–100 |
| 4–16 | per-step effects: echo, arpeggio, pitch shift, vibrato, filter. Each is stored 0–100 and `lerp`ed into its own range |

### Pitch

Notes are **resampling ratios**, not MIDI numbers. A 60-entry frequency table (`FREQOUT`,
`11025 … 332995`) is indexed by `note % 100`, and the playback rate is that value over
44100. Index 24 is exactly 44100, so note 24 plays the sample at its own pitch — and it
is by far the most common note in the shipped modules.

### Gain

Track and step gain run through two different log divisors, which as amplitudes are
different curves:

```
trackAmp = (masterVol/100 × trackVol/100) ^ 1.25     # log10(x)/0.04
stepAmp  = (stepVol/100) ^ 2.5                       # log10(x)/0.02
```

Pan is summed, not averaged: track and step each map 0–100 onto −1…+1 and the two are
added, so 50/50 is centre.

### An envelope bug worth reproducing

The instrument envelope block converts each duration field with
`ceil(lerp(0, 34, v/100))`, after which `1` and `2` are reinterpreted as 0.25 and 0.5
steps. The `sustain` branch then writes its result into the **stop** slot rather than its
own — a genuine bug in the shipped game. It rarely matters (934 of 1003 instruments leave
sustain at zero), but a renderer that "fixes" it will not match what players heard.

## 11. What this does *not* cover

- `wordart/` elements are stored as ordinary `Gif`s pointing at a word-art directory;
  the per-letter composition happens in the Page Builder, not at page-load.
- The `.hsm` per-step effect slots (`z[4]`..`z[16]`) are parsed but not rendered. They
  drive echo, arpeggio, pitch-shift, vibrato and filter timers in the game.
- The `NewDither` and `AdjustHSL` shaders are reproduced approximately in the HTML
  renderer (CSS `filter`), not pixel-exactly.
- Story-flag state selection needs game save state; the exporter always resolves to
  `DEFAULT` unless told otherwise.
