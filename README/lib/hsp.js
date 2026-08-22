/* SPDX-License-Identifier: CC0-1.0 */
/* Hypnospace .hsp page renderer.
 *
 * Reimplements the parts of HypnOS that draw a page: Construct 2's Spritefont
 * text layout, the gif frame player, and the per-element animations.
 * See ../FORMAT.md for where each formula comes from.
 */
const HSP = (() => {
'use strict';

const PAGEWIDTH = 300, ROW_H = 32, ANIMFPS = 10, TABWIDTH = 8;
const rad = d => d * Math.PI / 180;
const sin = d => Math.sin(rad(d));
const rgb = c => `rgb(${c[0]},${c[1]},${c[2]})`;

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

/* ------------------------------------------------------- Spritefont engine */
class Font {
  constructor(def, sheet) {
    this.def = def;
    this.sheet = sheet;                    // HTMLImageElement (black glyphs, alpha)
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

/* Draw laid-out lines into a canvas, then recolour by filling the glyph mask. */
function renderText(font, lines, boxW, boxH, align, color, noRecolor) {
  const cv = document.createElement('canvas');
  cv.width = Math.max(1, Math.ceil(boxW));
  cv.height = Math.max(1, Math.ceil(boxH));
  const ctx = cv.getContext('2d');
  ctx.imageSmoothingEnabled = false;
  let y = 0;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    let x = align * 0.5 * Math.max(0, boxW - line.width);
    if (i > 0 || font.lineHeight > 0) y += font.lineHeight;
    for (const ch of line.text) {
      const clip = font.clip.get(ch);
      const cwid = font.charWidth(ch);
      if (x + cwid > boxW + 1e-5) break;
      if (clip) ctx.drawImage(font.sheet, clip[0], clip[1], font.cw, font.ch,
                              Math.round(x), Math.round(y), font.cw, font.ch);
      x += cwid + font.spacing;
    }
    y += font.ch;
  }
  if (!noRecolor) {
    // replacecolor with source (0,0,0) and tolerance 0.01 == fill the mask.
    ctx.globalCompositeOperation = 'source-in';
    ctx.fillStyle = rgb(color);
    ctx.fillRect(0, 0, cv.width, cv.height);
    ctx.globalCompositeOperation = 'source-over';
  }
  return cv;
}

/* --------------------------------------------------------------- elements */
class TextEl {
  constructor(def, font, page) {
    this.d = def; this.font = font; this.page = page;
    this.node = document.createElement('div');
    this.node.className = 'hsp-el hsp-text';
    this.node.style.zIndex = String(9999 - def.i);
    this.canvas = null;
    this.full = replaceText(def.text, page.playerName);
    this.lines = wrap(font, this.full, def.w);
    this.h = Math.max(font.ch, textHeight(font, this.lines.length));
    this.phase = 0;      // instvar 8
    this.offset = 0;     // instvar 9
    this.mix = 0;        // colour lerp position (instvar 13)
    this.mixDir = def.colorSpeed;
    this.shown = 0;
    this.timer = 100;

    if (def.anim === 3) {                       // marquee: shrink to text width
      const w = Math.max(1, this.lines.reduce((a, l) => Math.max(a, l.width), 0));
      this.lines = [{ text: this.full.replace(/\n/g, ' '), width: font.measure(this.full.replace(/\n/g, ' ')) }];
      this.boxW = this.lines[0].width;
      this.phase = this.boxW;
      this.offset = PAGEWIDTH;
    } else {
      this.boxW = def.w;
    }
    if (def.anim === 2) this.offset = def.y;
    this.paint();
    applyLink(this.node, def, page);
    page.layer.appendChild(this.node);
  }
  color() {
    const d = this.d;
    if (!d.color2) return d.color;
    const t = this.mix * 0.01;
    return [0, 1, 2].map(i => Math.round(d.color[i] + (d.color2[i] - d.color[i]) * t));
  }
  paint() {
    const d = this.d;
    let lines = this.lines;
    if (d.anim === 1) {
      const txt = this.full.slice(0, this.shown);
      lines = wrap(this.font, txt, this.boxW);
    }
    const cv = renderText(this.font, lines, this.boxW, this.h, d.align,
                          this.color(), d.noRecolor);
    if (this.canvas) this.node.removeChild(this.canvas);
    this.canvas = cv;
    this.node.appendChild(cv);
    this.node.style.width = cv.width + 'px';
    this.node.style.height = cv.height + 'px';
    this.place();
  }
  place() {
    const d = this.d;
    let x = d.x, y = d.y;
    if (d.anim === 3) { x = -2 + this.offset; }
    if (d.anim === 2) { y = this.offset + this.h * 0.25 * sin(this.phase); }
    this.node.style.left = x + 'px';
    this.node.style.top = y + 'px';
  }
  tick(dt) {
    const d = this.d, k = 60 * dt;
    let repaint = false;
    if (d.anim === 1) {                                   // typewriter
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
    } else if (d.anim === 2) {                            // vertical bob
      this.phase += d.animSpeed * 0.4 * k;
      this.place();
    } else if (d.anim === 3) {                            // marquee
      this.offset -= d.animSpeed * 0.1 * k;
      if (this.offset < -this.phase) this.offset = PAGEWIDTH;
      this.place();
    }
    if (d.color2) {
      this.mix = Math.max(0, Math.min(100, this.mix + this.mixDir * 0.1 * k));
      if (this.mix >= 100 || this.mix <= 0) this.mixDir = -this.mixDir;
      repaint = true;
    }
    if (repaint) this.paint();
  }
}

class GifEl {
  constructor(def, frames, page) {
    this.d = def; this.frames = frames; this.page = page;
    this.node = document.createElement('div');
    this.node.className = 'hsp-el hsp-gif';
    // UpdateZOrder walks the array back-to-front, so a higher index sits further back.
    this.node.style.zIndex = String(9999 - def.i);
    this.img = document.createElement('img');
    this.img.draggable = false;
    this.node.appendChild(this.img);
    this.i = 0; this.acc = 0;
    this.phaseX = 0; this.phaseY = 0; this.phaseD = 0; this.phaseR = 0;
    this.hover = false; this.held = false;
    this.node.addEventListener('pointerenter', () => this.hover = true);
    this.node.addEventListener('pointerleave', () => { this.hover = false; this.held = false; });
    this.node.addEventListener('pointerdown', () => this.held = true);
    this.node.addEventListener('pointerup', () => this.held = false);
    const first = frames[0];
    this.w = first ? first.naturalWidth : 0;
    this.h = first ? first.naturalHeight : 0;
    this.setFrame(this.startFrame());
    this.node.style.left = def.x + 'px';
    this.node.style.top = def.y + 'px';
    if (def.hsl) {
      const [hue, sat, lum] = def.hsl;
      this.img.style.filter =
        `hue-rotate(${hue}deg) saturate(${sat}%) brightness(${lum}%)`;
    }
    this.render();
    applyLink(this.node, def, page);
    page.layer.appendChild(this.node);
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
    const d = this.d;
    let w = this.w * d.scale, h = this.h * d.scale;
    // The mirror/flip flags are folded into the sway phase so that a mirrored
    // copy sways in antiphase, exactly as the game does it.
    if (d.swayX !== null) w = this.w * d.scale * sin(this.phaseX + 180 * (d.mirror ? 1 : 0));
    if (d.swayY !== null) h = this.h * d.scale * sin(this.phaseY + 180 * (d.flip ? 1 : 0));
    let sx = d.mirror ? -1 : 1, sy = d.flip ? -1 : 1;
    if (w < 0) { w = -w; sx = -sx; }
    if (h < 0) { h = -h; sy = -sy; }

    let angle = d.angle;
    if (d.rotMode === 1) angle = d.angle + sin(this.phaseR) * 20;
    else if (d.rotMode === 2) angle = d.angle + this.phaseR;

    this.img.style.width = Math.abs(w) + 'px';
    this.img.style.height = Math.abs(h) + 'px';
    this.node.style.transform =
      `translate(-50%,-50%) rotate(${angle}deg) scale(${sx},${sy})`;
    if (d.dither !== null) {
      // alphadither: f_dither 0 => fully transparent, 1 => opaque.
      const p = this.phaseD >= 100 ? this.phaseD - 100 : 100 - this.phaseD;
      this.node.style.opacity = String(Math.max(0, Math.min(1, p * 0.01)));
    }
  }
  tick(dt) {
    const d = this.d, k = 60 * dt;
    if (d.swayX !== null) this.phaseX += d.swayX * 0.1 * k;
    if (d.swayY !== null) this.phaseY += d.swayY * 0.1 * k;
    if (d.dither !== null) { this.phaseD += d.dither * 0.1 * k; if (this.phaseD >= 200) this.phaseD -= 200; }
    if (d.rotMode === 1) this.phaseR += d.rotSpeed * 0.25 * k;
    else if (d.rotMode === 2) { this.phaseR += d.rotSpeed * 0.1 * k; if (this.phaseR >= 360) this.phaseR -= 360; }

    const base = this.startFrame();
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

/* ------------------------------------------------------------------ music */
/* Page music is either a plain .ogg from the game or a .hsm tracker module
 * bounced down by tools/hsmrender.py. Either way it loops, as it does in game.
 *
 * There is no visible player: browsers refuse to start audio without a user
 * gesture, so the first click or keypress anywhere starts it, and from then on
 * the choice rides along in sessionStorage so later pages start on their own.
 * That is close to how the game's Autoplay setting behaves. */
const AUTOPLAY_KEY = 'hsp:autoplay';

function wanted() {
  try { return sessionStorage.getItem(AUTOPLAY_KEY) !== '0'; } catch (e) { return true; }
}
function remember(on) {
  try { sessionStorage.setItem(AUTOPLAY_KEY, on ? '1' : '0'); } catch (e) { /* private mode */ }
}

function setupMusic(page) {
  const m = page.data.music;
  if (!m || !m.src) return null;

  const audio = new Audio(page.root + m.src);
  audio.loop = true;
  audio.preload = 'auto';

  const tryPlay = () => { if (wanted()) audio.play().catch(() => { /* needs a gesture */ }); };
  tryPlay();

  // Any interaction counts as the gesture the autoplay policy is waiting for.
  const once = () => {
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
  return audio;
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
  const apply = (n, persist) => {
    scale = Math.max(1, Math.min(MAX_SCALE, n));
    document.documentElement.style.setProperty('--hsp-scale', String(scale));
    // Only a deliberate zoom is remembered, so that a page opened on a
    // different-sized window still fits by default.
    if (persist) {
      try { localStorage.setItem(SCALE_KEY, String(scale)); } catch (e) { /* ignore */ }
    }
  };
  apply(storedScale() || fitScale(), false);
  return {
    get: () => scale,
    bump: d => apply(scale + d, true),
    fit: () => apply(fitScale(), false),
    reset: () => {
      try { localStorage.removeItem(SCALE_KEY); } catch (e) { /* ignore */ }
      apply(fitScale(), false);
    },
  };
}

/* --------------------------------------------------------------- keyboard */
function helpPanel(page, zoom) {
  const el = document.createElement('div');
  el.id = 'hsp-help';
  el.hidden = true;
  el.innerHTML =
    '<b>' + escapeHtml(page.data.title || '(untitled)') + '</b>'
    + (page.data.author ? ' &middot; @' + escapeHtml(page.data.author) : '')
    + '<br>' + escapeHtml(page.data.path)
    + (page.data.music ? '<br>music: ' + escapeHtml(page.data.music.source) : '')
    + '<hr style="border:0;border-top:1px solid #333349;margin:8px 0">'
    + '<kbd>+</kbd> <kbd>-</kbd> zoom &middot; <kbd>0</kbd> fit<br>'
    + '<kbd>m</kbd> music &middot; <kbd>Esc</kbd> index &middot; <kbd>?</kbd> close';
  document.body.appendChild(el);
  return el;
}

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function setupKeys(page, zoom) {
  let help = null;
  document.addEventListener('keydown', e => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    switch (e.key) {
      case '+': case '=': zoom.bump(1); break;
      case '-': case '_': zoom.bump(-1); break;
      case '0': zoom.reset(); break;
      case 'm': case 'M': if (page.audio) page.audio.toggle(); break;
      case 'Escape': location.href = page.root + 'index.html'; break;
      case '?': case '/':
        if (!help) help = helpPanel(page, zoom);
        help.hidden = !help.hidden;
        break;
      default: return;
    }
    e.preventDefault();
  });
}

/* ------------------------------------------------------------------ links */
function applyLink(node, def, page) {
  const link = def.link;
  if (!link) return;
  node.classList.add('hsp-link');
  if (link.tooltip) node.title = replaceText(link.tooltip, page.playerName);
  if (link.page) {
    const target = page.root + 'pages/' + link.page;
    if (target) {
      node.dataset.href = target;
      node.addEventListener('click', () => { location.href = target; });
      node.classList.add('hsp-nav');
    } else {
      node.title = (node.title ? node.title + '\n' : '') + link.raw;
    }
  } else {
    node.title = node.title || link.raw;
  }
  if (link.anchor != null) {
    node.addEventListener('click', () => window.scrollTo({ top: link.anchor, behavior: 'smooth' }));
  }
}

/* ------------------------------------------------------------------- page */
class Page {
  constructor(data, opts) {
    this.data = data;
    this.root = opts.root || '';
    this.playerName = opts.playerName || 'Outlaw';
    this.els = [];
    this.layer = document.getElementById('hsp-page');
    this.layer.style.width = data.width + 'px';
    this.layer.style.height = data.height + 'px';
    if (data.bgColor) this.layer.style.background = rgb(data.bgColor);
    if (data.bg && !data.bgColor) {
      this.layer.style.backgroundImage = `url("${this.asset(data.bg)}")`;
    }
  }
  asset(p) { return this.root + 'assets/' + p; }
  async build() {
    const d = this.data;
    const fonts = {};
    await Promise.all(Object.entries(d.fonts || {}).map(async ([k, def]) => {
      const sheet = await loadImage(this.asset(def.sheet));
      if (sheet) fonts[k] = new Font(def, sheet);
    }));
    for (const e of d.elements) {
      if (e.type === 'text') {
        const f = fonts[e.font];
        if (f) this.els.push(new TextEl(e, f, this));
      } else {
        const frames = (await Promise.all(e.frames.map(f => loadImage(this.asset(f)))))
          .filter(Boolean);
        if (frames.length) this.els.push(new GifEl(e, frames, this));
        else this.els.push(new GifEl(e, [], this));
      }
    }
    this.animate();
  }
  animate() {
    let last = performance.now();
    const step = now => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      for (const el of this.els) el.tick(dt);
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
}

/* ------------------------------------------------------------------- boot */
function boot(opts = {}) {
  const data = JSON.parse(document.getElementById('hsp-data').textContent);
  const page = new Page(data, opts);
  page.build();
  page.audio = setupMusic(page);
  page.zoom = setupZoom();
  setupKeys(page, page.zoom);
  window.addEventListener('resize', () => {
    if (!storedScale()) page.zoom.fit();   // only auto-fit if no zoom was chosen
  });
  window.hspPage = page;
  return page;
}

return { boot, Page, Font, wrap, replaceText, renderText };
})();
