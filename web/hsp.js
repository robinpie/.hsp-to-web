/* SPDX-License-Identifier: CC0-1.0 */
/* Hypnospace .hsp page renderer.
 *
 * Reimplements the parts of HypnOS that draw a page: Construct 2's Spritefont
 * text layout, the gif frame player, and the per-element animations.
 * See ../FORMAT.md for where each formula comes from.
 *
 * The layout is the game's, but the document is a document: every string is
 * real text in the DOM, every link is an <a href>, and the glyphs are painted
 * over that text with CSS masks rather than blitted into a canvas. So the page
 * can be read aloud, searched, translated and tabbed through, and it still
 * comes out pixel for pixel where the game put it.
 */
const HSP = (() => {
'use strict';

const PAGEWIDTH = 300, ROW_H = 32, ANIMFPS = 10, TABWIDTH = 8;
const rad = d => d * Math.PI / 180;
const sin = d => Math.sin(rad(d));
const rgb = c => `rgb(${c[0]},${c[1]},${c[2]})`;
const $ = id => document.getElementById(id);

/* ------------------------------------------------------------------ assets */
const imgCache = new Map();
function loadImage(url) {
  let p = imgCache.get(url);
  if (!p) {
    p = new Promise(res => {
      const im = new Image();
      im.onload = () => res(im);
      im.onerror = () => res(null);
      im.src = url;
    });
    imgCache.set(url, p);
  }
  return p;
}

/* -------------------------------------------------- text escape expansion */
function replaceText(v, playerName) {
  if (v == null) return '';
  v = String(v);
  // Protect the doubled forms, expand the single forms, then restore.
  v = v.replace(/\/\/n/g, '☺').replace(/\/\/N/g, '♂');
  v = v.replace(/\/n/gi, '\n');
  v = v.replace(/\/\/t/g, '☻').replace(/\/\/T/g, '♀');
  v = v.replace(/\/t/gi, '♣');                 // tab glyph
  v = v.replace(/\/\/p/g, '♥').replace(/\/\/P/g, '♪');
  v = v.replace(/\/p/gi, '§' + playerName);
  v = v.replace(/☺/g, '/n').replace(/♂/g, '/N')
       .replace(/☻/g, '/t').replace(/♀/g, '/T')
       .replace(/♥/g, '/p').replace(/♪/g, '/P')
       .replace(/’/g, "'");
  return v;
}

/* The zero-width markers the expansion leaves behind are for the blitter, not
 * for a screen reader; strip them for anything that reads the string as text. */
const plain = s => String(s == null ? '' : s).replace(/§/g, '').replace(/♣/g, '\t');
const humanise = s => String(s == null ? '' : s).replace(/[-_]+/g, ' ').trim();

/* ------------------------------------------------------- Spritefont engine */
class Font {
  constructor(def, sheet, key) {
    this.def = def;
    this.sheet = sheet;                    // HTMLImageElement (black glyphs, alpha)
    this.css = def.css || key;             // custom property in lib/fonts.css
    this.cw = def.cw; this.ch = def.ch;
    this.spacing = def.spacing | 0;
    this.lineHeight = def.lineheight | 0;
    this.clip = new Map();
    const cols = def.cols || 8;
    for (let i = 0; i < def.charset.length; i++) {
      const x = i % cols, y = Math.floor(i / cols);
      this.clip.set(def.charset[i], [x * this.cw, y * this.ch]);
    }
    this.widths = new Map(Object.entries(def.widths || {}));
    // The runtime widens the tab glyph to TABWIDTH-1 spaces.
    this.widths.set('♣', this.charWidth(' ') * (TABWIDTH - 1));
    this.widths.set('←', -2); this.widths.set('→', 2);
    this.widths.set('§', 0);          // zero-width /p marker
  }
  charWidth(ch) {
    const w = this.widths ? this.widths.get(ch) : undefined;
    return w === undefined ? this.cw : w;
  }
  measure(text) {
    let w = 0;
    for (const ch of text) w += this.charWidth(ch) + this.spacing;
    return w > 0 ? w - this.spacing : 0;
  }
}

/* Construct 2's TokeniseWords: breaks after runs of space/tab, and after '-'. */
function tokenise(text) {
  const words = [];
  let cur = '', i = 0;
  while (i < text.length) {
    const ch = text[i];
    if (ch === '\n') {
      if (cur) { words.push(cur); cur = ''; }
      words.push('\n'); i++;
    } else if (ch === ' ' || ch === '\t' || ch === '-') {
      do { cur += text[i]; i++; }
      while (i < text.length && (text[i] === ' ' || text[i] === '\t'));
      words.push(cur); cur = '';
    } else { cur += ch; i++; }
  }
  if (cur) words.push(cur);
  return words;
}

const trimRight = s => s.replace(/\s+$/, '');

function wrap(font, text, width) {
  if (!text) return [];
  if (width <= 2) return [];
  const all = font.measure(text);
  if (all <= width && text.indexOf('\n') === -1) return [{ text, width: all }];
  const words = tokenise(text), lines = [];
  const push = t => lines.push({ text: t, width: font.measure(trimRight(t)) });
  let cur = '', ignoreNewline = false;
  for (const w of words) {
    if (w === '\n') {
      if (ignoreNewline) ignoreNewline = false; else push(cur);
      cur = ''; continue;
    }
    ignoreNewline = false;
    const prev = cur;
    cur += w;
    if (font.measure(trimRight(cur)) > width) {
      if (prev === '') { push(cur); cur = ''; ignoreNewline = true; }
      else { push(prev); cur = w; }
    }
  }
  if (trimRight(cur).length) push(cur);
  return lines;
}

function textHeight(font, nLines) {
  let h = nLines * (font.ch + font.lineHeight);
  if (font.lineHeight < 0) h -= font.lineHeight;
  return h;
}

/* --------------------------------------------------------- text rendering */
/* Two layers over the same box.
 *
 * The reading layer holds the actual characters, one span per laid-out line,
 * transparent and positioned where the line sits. That is what a screen
 * reader announces, what find-in-page matches, and what the pointer selects.
 *
 * The paint layer is one empty span per glyph, each showing its cell of the
 * sheet through a CSS mask filled with the text colour -- the same pixels the
 * game's `replacecolor` effect produces, and the same pixels the old canvas
 * blitter produced, but recolourable in CSS and visible to a high-contrast
 * mode. It carries no text, so nothing is announced or found twice.
 */
function eachGlyph(font, lines, boxW, align, fn) {
  let y = 0;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    let x = align * 0.5 * Math.max(0, boxW - line.width);
    if (i > 0 || font.lineHeight > 0) y += font.lineHeight;
    fn(null, line, Math.round(x), y);
    for (const ch of line.text) {
      const clip = font.clip.get(ch);
      const cwid = font.charWidth(ch);
      if (x + cwid > boxW + 1e-5) break;
      if (clip) fn(clip, null, Math.round(x), y);
      x += cwid + font.spacing;
    }
    y += font.ch;
  }
}

function buildText(font, lines, boxW, align) {
  const frag = document.createDocumentFragment();
  // A fallback font at the glyph height, spaced to the sheet's advance, so a
  // selection or a search hit lands roughly on the pixels it belongs to.
  const ls = (font.cw + font.spacing - font.ch * 0.6).toFixed(2);
  eachGlyph(font, lines, boxW, align, (clip, line, x, y) => {
    if (!line) return;
    const s = document.createElement('span');
    s.className = 'hsp-line';
    s.textContent = plain(line.text);
    s.style.cssText = `left:${x}px;top:${y}px;font-size:${font.ch}px;` +
                      `line-height:${font.ch}px;letter-spacing:${ls}px`;
    frag.appendChild(s);
  });
  return frag;
}

function buildGlyphs(font, lines, boxW, align, noRecolor) {
  const paint = document.createElement('span');
  paint.className = 'hsp-paint ' + (noRecolor ? 'hsp-img' : 'hsp-mask');
  paint.setAttribute('aria-hidden', 'true');
  paint.style.setProperty('--sheet', `var(--f-${font.css})`);
  eachGlyph(font, lines, boxW, align, (clip, line, x, y) => {
    if (!clip) return;
    const g = document.createElement('span');
    g.className = 'hsp-g';
    g.style.cssText = `left:${x}px;top:${y}px;width:${font.cw}px;` +
                      `height:${font.ch}px;--gp:${-clip[0]}px ${-clip[1]}px`;
    paint.appendChild(g);
  });
  return paint;
}

/* --------------------------------------------------------------- elements */
/* A linked element is an <a>, so it is focusable, announced as a link, opens
 * in a new tab on middle click and shows its target in the status bar. */
function linkHref(def, page) {
  const link = def.link;
  if (!link) return null;
  if (link.url) return link.url;                 // leaves the export entirely
  if (link.page) return page.root + 'pages/' + link.page;
  if (link.anchor != null) return '#hsp-y' + Math.round(link.anchor);
  return null;
}

/* A link that opens a new tab has to say so to anyone who cannot watch it
 * happen; the element itself is painted pixels, so the note is text only. */
function externalNote(def) {
  if (!def.link || !def.link.url) return null;
  const note = document.createElement('span');
  note.className = 'hsp-sr';
  note.textContent = ' (opens in a new tab)';
  return note;
}

function makeNode(def, page, cls) {
  const href = linkHref(def, page);
  const node = document.createElement(href ? 'a' : 'div');
  node.className = 'hsp-el ' + cls;
  // UpdateZOrder walks the array back-to-front, so a higher index sits further
  // back. Paint order is z-index; the DOM is in reading order, for tabbing.
  node.style.zIndex = String(9999 - def.i);
  if (href) {
    node.href = href;
    node.classList.add('hsp-link', 'hsp-nav');
    if (def.link.url) {
      node.target = '_blank';
      node.rel = 'noopener noreferrer';
    }
  } else if (def.link) {
    node.classList.add('hsp-link');        // goes nowhere in this export
  }
  const tip = def.link && def.link.tooltip;
  if (tip) node.title = plain(replaceText(tip, page.playerName));
  else if (def.link && !href) node.title = def.link.raw;
  return node;
}

class TextEl {
  constructor(def, font, page) {
    this.d = def; this.font = font; this.page = page;
    this.node = makeNode(def, page, 'hsp-text');
    this.full = replaceText(def.text, page.playerName);
    this.anim = page.motion ? def.anim : 0;
    this.lines = wrap(font, this.full, def.w);
    this.h = Math.max(font.ch, textHeight(font, this.lines.length));
    this.phase = 0;      // instvar 8
    this.offset = 0;     // instvar 9
    this.mix = 0;        // colour lerp position (instvar 13)
    this.mixDir = def.colorSpeed;
    this.shown = this.anim === 1 ? 0 : this.full.length;
    this.timer = 100;
    this.glyphs = null;

    if (this.anim === 3) {                      // marquee: shrink to text width
      const flat = this.full.replace(/\n/g, ' ');
      this.lines = [{ text: flat, width: font.measure(flat) }];
      this.boxW = Math.max(1, this.lines[0].width);
      this.phase = this.boxW;
      this.offset = PAGEWIDTH;
    } else {
      this.boxW = def.w;
    }
    if (this.anim === 2) this.offset = def.y;
    this.paint();
  }
  color() {
    const d = this.d;
    if (!d.color2) return d.color;
    const t = this.mix * 0.01;
    return [0, 1, 2].map(i => Math.round(d.color[i] + (d.color2[i] - d.color[i]) * t));
  }
  paint() {
    const d = this.d;
    const lines = this.anim === 1
      ? wrap(this.font, this.full.slice(0, this.shown), this.boxW)
      : this.lines;
    this.node.textContent = '';
    this.node.appendChild(buildText(this.font, lines, this.boxW, d.align));
    this.glyphs = buildGlyphs(this.font, lines, this.boxW, d.align, d.noRecolor);
    this.node.appendChild(this.glyphs);
    // The colour lives on the element, not the paint layer, so that the
    // fallbacks in hsp.css -- no mask support, or a forced-colours mode --
    // inherit it for the real text they show instead of the glyphs.
    if (!d.noRecolor) this.node.style.color = rgb(this.color());
    const note = externalNote(d);
    if (note) this.node.appendChild(note);
    this.node.style.width = Math.max(1, Math.ceil(this.boxW)) + 'px';
    this.node.style.height = Math.max(1, Math.ceil(this.h)) + 'px';
    this.place();
  }
  place() {
    const d = this.d;
    let x = d.x, y = d.y;
    if (this.anim === 3) { x = -2 + this.offset; }
    if (this.anim === 2) { y = this.offset + this.h * 0.25 * sin(this.phase); }
    this.node.style.left = x + 'px';
    this.node.style.top = y + 'px';
  }
  tick(dt) {
    const d = this.d, k = 60 * dt;
    let repaint = false;
    if (this.anim === 1) {                                // typewriter
      this.timer -= d.animSpeed * k;
      if (this.timer <= 0) {
        this.timer = 100;
        const len = this.full.length;
        if (this.phase < len) { this.shown = ++this.phase; repaint = true; }
        else if (this.phase === len) { this.timer = 800; this.phase++; }
        else {
          this.shown = Math.max(0, len - (this.phase - len)); this.phase++;
          repaint = true;
          if (this.phase >= len * 2) { this.timer = 800; this.phase = 0; this.shown = 0; }
        }
      }
    } else if (this.anim === 2) {                         // vertical bob
      this.phase += d.animSpeed * 0.4 * k;
      this.place();
    } else if (this.anim === 3) {                         // marquee
      this.offset -= d.animSpeed * 0.1 * k;
      if (this.offset < -this.phase) this.offset = PAGEWIDTH;
      this.place();
    }
    if (repaint) { this.paint(); return; }
    // A colour cycle is now just a property on the paint layer, so it costs
    // nothing to run -- no relayout, no rebuilt glyphs.
    if (d.color2 && !d.noRecolor) {
      this.mix = Math.max(0, Math.min(100, this.mix + this.mixDir * 0.1 * k));
      if (this.mix >= 100 || this.mix <= 0) this.mixDir = -this.mixDir;
      this.node.style.color = rgb(this.color());
    }
  }
}

class GifEl {
  constructor(def, frames, page) {
    this.d = def; this.frames = frames; this.page = page;
    this.node = makeNode(def, page, 'hsp-gif');
    this.motion = page.motion;
    this.img = document.createElement('img');
    this.img.draggable = false;
    this.img.alt = gifAlt(def, page);
    this.node.appendChild(this.img);
    const note = externalNote(def);
    if (note) this.node.appendChild(note);
    this.i = 0; this.acc = 0;
    this.phaseX = 0; this.phaseY = 0; this.phaseD = 0; this.phaseR = 0;
    this.hover = false; this.held = false;
    this.node.addEventListener('pointerenter', () => this.hover = true);
    this.node.addEventListener('pointerleave', () => { this.hover = false; this.held = false; });
    this.node.addEventListener('pointerdown', () => this.held = true);
    this.node.addEventListener('pointerup', () => this.held = false);
    // A keyboard user gets the hover frames too, while the link has focus.
    this.node.addEventListener('focus', () => this.hover = true);
    this.node.addEventListener('blur', () => { this.hover = false; this.held = false; });
    const first = frames[0];
    this.w = first ? first.naturalWidth : 0;
    this.h = first ? first.naturalHeight : 0;
    this.setFrame(this.startFrame());
    this.node.style.left = def.x + 'px';
    this.node.style.top = def.y + 'px';
    if (def.hsl) {
      // The shader's three parameters are C2 percentages: each is the stored
      // number over 100. `huerotate` is then added to the HSL hue, which runs
      // 0..1 over the whole wheel -- so 100 is a full turn, not 100 degrees.
      const [hue, sat, lum] = def.hsl;
      this.img.style.filter =
        `hue-rotate(${hue * 3.6}deg) saturate(${sat}%) brightness(${lum}%)`;
    }
    this.render();
  }
  startFrame() {
    const d = this.d;
    if (d.animMode === -1 || d.animMode === -2 || d.animMode > 0)
      return Math.max(0, Math.min(this.frames.length - 1, d.frame));
    return Math.max(0, d.frame) % Math.max(1, this.frames.length);
  }
  setFrame(i) {
    if (!this.frames.length) return;
    i = Math.max(0, Math.min(this.frames.length - 1, i));
    if (this.i === i && this.img.src) return;
    this.i = i;
    this.img.src = this.frames[i].src;
    this.w = this.frames[i].naturalWidth;
    this.h = this.frames[i].naturalHeight;
  }
  render() {
    const d = this.d, moving = this.motion;
    let w = this.w * d.scale, h = this.h * d.scale;
    // The mirror/flip flags are folded into the sway phase so that a mirrored
    // copy sways in antiphase, exactly as the game does it.
    if (moving && d.swayX !== null) w = this.w * d.scale * sin(this.phaseX + 180 * (d.mirror ? 1 : 0));
    if (moving && d.swayY !== null) h = this.h * d.scale * sin(this.phaseY + 180 * (d.flip ? 1 : 0));
    let sx = d.mirror ? -1 : 1, sy = d.flip ? -1 : 1;
    if (w < 0) { w = -w; sx = -sx; }
    if (h < 0) { h = -h; sy = -sy; }

    let angle = d.angle;
    if (moving && d.rotMode === 1) angle = d.angle + sin(this.phaseR) * 20;
    else if (moving && d.rotMode === 2) angle = d.angle + this.phaseR;

    this.img.style.width = Math.abs(w) + 'px';
    this.img.style.height = Math.abs(h) + 'px';
    this.node.style.transform =
      `translate(-50%,-50%) rotate(${angle}deg) scale(${sx},${sy})`;
    if (moving && d.dither !== null) {
      // alphadither: f_dither 0 => fully transparent, 1 => opaque.
      const p = this.phaseD >= 100 ? this.phaseD - 100 : 100 - this.phaseD;
      this.node.style.opacity = String(Math.max(0, Math.min(1, p * 0.01)));
    }
  }
  tick(dt) {
    const d = this.d, k = 60 * dt;
    const base = this.startFrame();
    if (!this.motion) {
      // Frozen, but the hover and press frames stay: those are the user's own
      // doing, not something moving at them.
      if (d.animMode === -2) this.setFrame(base + (this.held ? 2 : this.hover ? 1 : 0));
      else if (d.animMode > 0 && this.hover) this.advance(dt, 15);
      else this.setFrame(base);
      return;
    }
    if (d.swayX !== null) this.phaseX += d.swayX * 0.1 * k;
    if (d.swayY !== null) this.phaseY += d.swayY * 0.1 * k;
    if (d.dither !== null) { this.phaseD += d.dither * 0.1 * k; if (this.phaseD >= 200) this.phaseD -= 200; }
    if (d.rotMode === 1) this.phaseR += d.rotSpeed * 0.25 * k;
    else if (d.rotMode === 2) { this.phaseR += d.rotSpeed * 0.1 * k; if (this.phaseR >= 360) this.phaseR -= 360; }

    if (d.animMode === -2) {
      this.setFrame(base + (this.held ? 2 : this.hover ? 1 : 0));
    } else if (d.animMode === -1) {
      this.setFrame(base);
    } else if (d.animMode > 0) {
      if (this.hover) this.advance(dt, 15); else this.setFrame(base);
    } else if (d.fps > 0 && this.frames.length > 1) {
      this.advance(dt, d.fps);
    }
    if (d.swayX !== null || d.swayY !== null || d.dither !== null || d.rotMode) this.render();
  }
  advance(dt, fps) {
    this.acc += dt * fps;
    if (this.acc >= 1) {
      const step = Math.floor(this.acc);
      this.acc -= step;
      this.setFrame((this.i + step) % this.frames.length);
    }
  }
}

/* Alt text. Mirrors gif_alt() in tools/hspconv.py -- see the note there. */
const DECORATION =
  /gradient|dither|fade|blank|spacer|divider|separator|border|shadow|filler|^bg[-_0-9]|[-_]bg$/i;

function gifAlt(def, page) {
  const link = def.link || {};
  if (link.tooltip) return plain(replaceText(link.tooltip, page.playerName));
  if (link.pageTitle) return 'link to ' + link.pageTitle;
  const name = def.gif || '';
  if (link.href) return humanise(name);
  if (def.kind === 'shape' || DECORATION.test(name)) return '';
  return ['gif', 'wordart', 'static'].indexOf(def.kind) !== -1 ? humanise(name) : '';
}

/* ------------------------------------------------------------------ music */
/* Page music is either a plain .ogg from the game or a .hsm tracker module
 * bounced down by tools/hsmrender.py. Either way it loops, as it does in game.
 *
 * Browsers refuse to start audio without a user gesture, so the first click or
 * keypress starts it and the choice then rides along in sessionStorage, close
 * to how the game's Autoplay setting behaves. Because it starts on its own and
 * runs for longer than a moment, there is a real button for it in the bar --
 * a key binding alone is not a control anyone can find. */
const AUTOPLAY_KEY = 'hsp:autoplay';

function wanted() {
  try { return sessionStorage.getItem(AUTOPLAY_KEY) !== '0'; } catch (e) { return true; }
}
function remember(on) {
  try { sessionStorage.setItem(AUTOPLAY_KEY, on ? '1' : '0'); } catch (e) { /* private mode */ }
}

function setupMusic(page) {
  const m = page.data.music;
  const btn = $('hsp-music');
  if (!m || !m.src) { if (btn) btn.remove(); return null; }

  const audio = new Audio(page.root + m.src);
  audio.loop = true;
  audio.preload = 'auto';

  const label = btn ? (btn.dataset.label || '') : '';
  const sync = () => {
    if (!btn) return;
    const on = !audio.paused;
    btn.textContent = on ? 'Pause music' : 'Play music';
    btn.setAttribute('aria-label',
      (on ? 'Pause music: ' : 'Play music: ') + (label || 'page music'));
  };
  audio.addEventListener('play', sync);
  audio.addEventListener('pause', sync);
  sync();

  const tryPlay = () => { if (wanted()) audio.play().catch(() => { /* needs a gesture */ }); };
  tryPlay();

  // Any deliberate interaction counts as the gesture the autoplay policy waits
  // for -- but tabbing to the controls is navigation, not a decision to listen.
  const nav = ['Tab', 'Shift', 'Control', 'Alt', 'Meta', 'Escape',
               'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'];
  const once = e => {
    if (e.type === 'keydown' && nav.indexOf(e.key) !== -1) return;
    document.removeEventListener('pointerdown', once);
    document.removeEventListener('keydown', once);
    tryPlay();
  };
  document.addEventListener('pointerdown', once);
  document.addEventListener('keydown', once);

  audio.toggle = () => {
    if (audio.paused) { remember(true); audio.play().catch(() => {}); }
    else { remember(false); audio.pause(); }
  };
  if (btn) btn.addEventListener('click', () => audio.toggle());
  return audio;
}

/* ----------------------------------------------------------------- motion */
/* Marquees, bobbing headlines, typewriters, swaying and pulsing gifs: all of
 * it starts on its own and none of it stops. Anyone who has asked their system
 * for less of that gets a still page, and everyone else gets a button. */
const MOTION_KEY = 'hsp:motion';
const reduceMotion = () =>
  window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function motionDefault() {
  let saved = null;
  try { saved = localStorage.getItem(MOTION_KEY); } catch (e) { /* ignore */ }
  if (saved !== null) return saved === '1';
  return !reduceMotion();
}

function setupMotion(page) {
  const btn = $('hsp-motion');
  const sync = () => {
    if (btn) btn.textContent = page.motion ? 'Pause motion' : 'Play motion';
  };
  page.toggleMotion = () => {
    page.setMotion(!page.motion);
    try { localStorage.setItem(MOTION_KEY, page.motion ? '1' : '0'); } catch (e) { /* ignore */ }
    sync();
  };
  sync();
  if (btn) btn.addEventListener('click', page.toggleMotion);
  return sync;
}

/* ------------------------------------------------------------ text view */
/* The pixel page cannot reflow and cannot take a text size: it is 300 fixed
 * pixels of 7-pixel type. The converter writes a plain-HTML version of the
 * same page into the document, and this switches between them. */
const READ_KEY = 'hsp:read';

function setupReader() {
  const btn = $('hsp-read-btn');
  const root = document.documentElement;
  const sync = on => {
    root.classList.toggle('hsp-read', on);
    if (btn) {
      btn.textContent = on ? 'Page view' : 'Text view';
      btn.setAttribute('aria-label', on ? 'Show the page as drawn'
                                        : 'Show this page as plain text');
    }
  };
  let on = location.hash === '#text';
  if (!on) {
    try { on = localStorage.getItem(READ_KEY) === '1'; } catch (e) { /* ignore */ }
  }
  sync(on);
  if (btn) btn.addEventListener('click', () => {
    on = !on;
    sync(on);
    try { localStorage.setItem(READ_KEY, on ? '1' : '0'); } catch (e) { /* ignore */ }
    const target = on ? document.querySelector('#hsp-reader h1') : $('hsp-stage');
    if (target) {
      target.setAttribute('tabindex', '-1');
      target.focus({ preventScroll: false });
    }
  });
  return () => { on = !on; sync(on); };
}

/* ------------------------------------------------------------------- zoom */
/* The game renders a 480x270 screen scaled up by a whole number; do the same
 * so the page's pixels stay square. +/- adjusts it, as it does in game. */
const SCALE_KEY = 'hsp:scale';
const MAX_SCALE = 6;
const FIT_HEIGHT = 240;   // ask for roughly a game screen of page per scale step

function fitScale() {
  const w = (window.innerWidth - 24) / PAGEWIDTH;
  const h = (window.innerHeight - 24) / FIT_HEIGHT;
  return Math.max(1, Math.min(MAX_SCALE, Math.floor(Math.min(w, h))));
}

function storedScale() {
  try { return parseInt(localStorage.getItem(SCALE_KEY), 10) || 0; } catch (e) { return 0; }
}

function setupZoom() {
  let scale = 0;
  const out = $('hsp-zout'), zin = $('hsp-zin'), val = $('hsp-zval');
  const apply = (n, persist) => {
    scale = Math.max(1, Math.min(MAX_SCALE, n));
    document.documentElement.style.setProperty('--hsp-scale', String(scale));
    if (val) val.textContent = scale + '×';
    if (out) out.disabled = scale <= 1;
    if (zin) zin.disabled = scale >= MAX_SCALE;
    // Only a deliberate zoom is remembered, so that a page opened on a
    // different-sized window still fits by default.
    if (persist) {
      try { localStorage.setItem(SCALE_KEY, String(scale)); } catch (e) { /* ignore */ }
    }
  };
  apply(storedScale() || fitScale(), false);
  const zoom = {
    get: () => scale,
    bump: d => apply(scale + d, true),
    fit: () => apply(fitScale(), false),
    reset: () => {
      try { localStorage.removeItem(SCALE_KEY); } catch (e) { /* ignore */ }
      apply(fitScale(), false);
    },
  };
  if (out) out.addEventListener('click', () => zoom.bump(-1));
  if (zin) zin.addEventListener('click', () => zoom.bump(1));
  return zoom;
}

/* -------------------------------------------------------------- the bar */
/* A disclosure, closed to a single button by default: the page is the point,
 * and a permanent strip of chrome over it is not. Everything the runtime does
 * lives inside it, so there is one place to look rather than two. The key
 * bindings work whether it is open or shut, so nothing is only reachable by
 * opening it first. */
const BAR_KEY = 'hsp:bar';

function setupBar() {
  const btn = $('hsp-bar-btn'), root = document.documentElement;
  let open = false;
  try { open = localStorage.getItem(BAR_KEY) === '1'; } catch (e) { /* ignore */ }
  const sync = () => {
    root.classList.toggle('hsp-open', open);
    if (btn) btn.setAttribute('aria-expanded', String(open));
  };
  const set = v => {
    open = v;
    sync();
    try { localStorage.setItem(BAR_KEY, open ? '1' : '0'); } catch (e) { /* ignore */ }
  };
  sync();
  if (btn) btn.addEventListener('click', () => set(!open));
  return {
    isOpen: () => open,
    toggle: () => set(!open),
    close: () => { if (open) { set(false); if (btn) btn.focus(); } },
  };
}

/* --------------------------------------------------------------- keyboard */
function setupKeys(page, zoom, toggleReader, bar) {
  document.addEventListener('keydown', e => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === 'Escape') {
      if (bar.isOpen()) { bar.close(); e.preventDefault(); }
      return;
    }
    // Never eat a key that belongs to whatever the user is actually using.
    const t = e.target;
    if (t && t.closest && t.closest('input, textarea, select, button, a, [contenteditable]'))
      return;
    switch (e.key) {
      case '+': case '=': zoom.bump(1); break;
      case '-': case '_': zoom.bump(-1); break;
      case '0': zoom.reset(); break;
      case 'm': case 'M': if (page.audio) page.audio.toggle(); break;
      case 'p': case 'P': page.toggleMotion(); break;
      case 't': case 'T': toggleReader(); break;
      case '?': bar.toggle(); break;
      default: return;
    }
    e.preventDefault();
  });
}

/* ------------------------------------------------------------------- page */
/* Reading order, not paint order: the array is drawn back to front, which has
 * little to do with the order a person takes the page in. Elements go into the
 * DOM top to bottom and left to right -- so that is the order they are read
 * and tabbed in -- and keep their painted stacking through z-index. */
function readingOrder(elements) {
  return elements
    .map((e, n) => [e, n])
    .sort((a, b) => (Math.floor((a[0].y || 0) / 8) - Math.floor((b[0].y || 0) / 8))
                 || ((a[0].x || 0) - (b[0].x || 0)) || (a[1] - b[1]))
    .map(pair => pair[0]);
}

class Page {
  constructor(data, opts) {
    this.data = data;
    this.root = opts.root || '';
    this.playerName = opts.playerName || 'Outlaw';
    this.els = [];
    this.raf = 0;
    this.motion = motionDefault();
    this.layer = $('hsp-page');
    this.layer.style.width = data.width + 'px';
    this.layer.style.height = data.height + 'px';
    if (data.bgColor) this.layer.style.background = rgb(data.bgColor);
    if (data.bg && !data.bgColor) {
      this.layer.style.backgroundImage = `url("${this.asset(data.bg)}")`;
    }
    this.anchors();
  }
  asset(p) { return this.root + 'assets/' + p; }

  /* Targets for the page's own in-page links, so they are ordinary fragment
   * links: they scroll correctly under zoom, and the back button undoes them. */
  anchors() {
    const seen = new Set();
    for (const e of this.data.elements) {
      const a = e.link && e.link.anchor;
      if (a == null || !e.link || e.link.page) continue;
      const y = Math.round(a);
      if (seen.has(y)) continue;
      seen.add(y);
      const t = document.createElement('span');
      t.className = 'hsp-anchor';
      t.id = 'hsp-y' + y;
      t.style.top = y + 'px';
      this.layer.appendChild(t);
    }
  }

  async build() {
    const d = this.data;
    const fonts = {};
    await Promise.all(Object.entries(d.fonts || {}).map(async ([k, def]) => {
      const sheet = await loadImage(this.asset(def.sheet));
      if (sheet) fonts[k] = new Font(def, sheet, k);
    }));
    const made = new Map();
    for (const e of d.elements) {
      if (e.type === 'text') {
        const f = fonts[e.font];
        if (f) made.set(e, new TextEl(e, f, this));
      } else {
        const frames = (await Promise.all(e.frames.map(f => loadImage(this.asset(f)))))
          .filter(Boolean);
        made.set(e, new GifEl(e, frames, this));
      }
    }
    const frag = document.createDocumentFragment();
    for (const e of readingOrder(d.elements)) {
      const el = made.get(e);
      if (el) { this.els.push(el); frag.appendChild(el.node); }
    }
    this.layer.appendChild(frag);
  }

  setMotion(on) {
    if (on === this.motion) return;
    this.motion = on;
    for (const el of this.els) el.node.remove();
    this.els = [];
    this.build();
  }
  toggleMotion() { this.setMotion(!this.motion); }   // replaced by setupMotion

  animate() {
    let last = performance.now();
    const step = now => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      for (const el of this.els) el.tick(dt);
      this.raf = requestAnimationFrame(step);
    };
    this.raf = requestAnimationFrame(step);
  }
}

/* ------------------------------------------------------------------- boot */
function boot(opts = {}) {
  const data = JSON.parse($('hsp-data').textContent);
  const page = new Page(data, opts);
  page.build();
  page.audio = setupMusic(page);
  page.zoom = setupZoom();
  setupMotion(page);
  setupKeys(page, page.zoom, setupReader(), setupBar());
  page.animate();
  window.addEventListener('resize', () => {
    if (!storedScale()) page.zoom.fit();   // only auto-fit if no zoom was chosen
  });
  window.hspPage = page;
  return page;
}

return { boot, Page, Font, wrap, replaceText, buildGlyphs, buildText, readingOrder };
})();
