// WebSession: one emulated device, one page, one run directory.
//
// Produces ergo-snapshot.v1 files and ergo-run.v1 (docs/ergonomic-swarm-spec.md
// sections 3, 5 and 10) from real Playwright/CDP input events. Everything the
// page reports is treated as data; nothing from the page or from HTTP requests
// is evaluated as code.

import fs from 'node:fs';
import path from 'node:path';

import { openBrowser } from './browser_transport.mjs';
import { resolveDevice } from './devices.mjs';
import { inspectPage } from './inspect.mjs';
import { STATE_KEY, TW_BINDING, armBinaryControl, controlOf, disposeBinaryControl, extractSnapshot, hitTest, idAtPoint, idForElement, pageInit, readBinaryControl } from './page_scripts.mjs';
import {
  BLOCK_MIN_H_CSS, BLOCK_MIN_W_CSS, MOTION_MATCH, RED_EXCESS, RED_RATIO,
  blockStats, changeMask, cssScaleCopy, decodePng, frameFromImage, frameStats, indicatorPixels, indicatorPixelsMulti, makeBlockGrid, resampleImage, visualDiffFraction,
} from './png.mjs';
import { KNOWN_ROLES } from './validate.mjs';
import {
  DriverFailure, epochNow, isoNow, pngSize, round1, sha256, sleep, truncate, writeFileAtomic, writeJsonAtomic,
} from './util.mjs';

export const ELEMENT_CAP = 400;
export const FEEDBACK_WINDOW_MS = 3000;
const FRAME_WIDTH = 160; // downscaled CSS-px width for flash/visual probe frames
const VISUAL_LEVEL = 16; // per-channel change (0-255) that counts as a changed pixel
const TW_POLL_MS = 16;
const DEFAULT_TARGET_TIMEOUT_MS = 5000;
const MAX_FLASH_SAMPLES = 50000;
// Flash samples carry a block grid (~0.4-2.2 KB of base64 each): sampling stops
// (flash_sampling.truncated) once they would push run.json towards ergoqa's
// 8 MB input limit. ~4,500 phone or ~2,000 desktop samples (1.5-3 min at ~24 fps).
const MAX_FLASH_BYTES = 6_000_000;
// Random pause between flash captures: CDP captures are otherwise phase-locked
// to the compositor (~33 ms), so a 30 Hz flicker would alias to a still image.
const FLASH_JITTER_MS = 15;
const MAX_CONSOLE = 500;
// Keyboard focus walk (WCAG 2.4.7 focus visible, 2.4.11 focus not obscured): Tab
// through up to this many stops; a stop's indicator is the pixel change inside its
// box (+4 px) between focused and unfocused states.
const FOCUS_WALK_MAX = 40;
const FOCUS_DIFF_LEVEL = 24;
const FOCUS_SETTLE_MS = 80;
const FOCUS_WALK_BUDGET_MS = 8000;
// Fewer changed pixels than this near the element sends a stop to the viewport-wide
// comparison (an indicator drawn away from the element, ACT oj04fd); at most
// FOCUS_VIEWPORT_MAX such comparisons per walk (full-viewport captures are slow).
const FOCUS_LOCAL_MIN_PX = 4;
const FOCUS_VIEWPORT_MAX = 6;
const FOCUS_VIEWPORT_WIDTH = 480; // viewport-wide captures are downscaled to about this many px wide
// Gap between the two unfocused captures whose difference masks animation, and the
// per-channel change between them that marks a pixel as animated.
const FOCUS_ANIM_GAP_MS = 40;
// Flash sampling: page scroll that reverses more often than this per second is treated
// as flicker, not motion (smooth scrolling in one direction is exempt).
const SCROLL_REVERSALS_PER_S = 3;
// Visual feedback: a per-channel change this small in either adjacent pair of three
// pre-input frames marks a pixel as already moving (left out of the comparison).
const AMBIENT_MOVE_LEVEL = 4;
const SCROLL_REVERSAL_MIN_CSS = 4;
const FOCUS_MASK_LEVEL = 4;
const STEP_PROBE_MAX = 16; // focus probes before clicks, per run

// Reflow (WCAG 1.4.10, AUT-06): each distinct screen's DOM is copied as the run goes
// and re-rendered after the run at 320 CSS px wide with scripts off (a static copy,
// so the run itself is never resized). At most REFLOW_MAX_SCREENS per run.
const REFLOW_WIDTH = 320;
const REFLOW_MAX_SCREENS = 12;
const REFLOW_BUDGET_MS = 40000;
const TEXT_SPACING = Object.freeze({ line_height: 1.5, paragraph_after: 2, letter_spacing: 0.12, word_spacing: 0.16, preserve_larger: true });
const SHORT_HEIGHT = Object.freeze({ height_ratio: 0.5, min_height_css: 256 });

const MEASURED = new Set(['tap', 'click', 'double_tap', 'long_press', 'swipe', 'drag', 'type', 'press', 'scroll', 'gamepad']);
const POINTER = new Set(['tap', 'click', 'double_tap', 'long_press', 'swipe', 'drag', 'scroll']);
// Actions that move content with the pointer (scroll gestures) or hold it down.
const GESTURES = new Set(['long_press', 'swipe', 'drag', 'scroll']);

function firstLine(msg) {
  return truncate(String(msg || '').split('\n')[0], 500);
}

function r4(n) {
  return Math.round(n * 10000) / 10000;
}

function sampleTaskState({ selector, property, expected, key }) {
  const elements = document.querySelectorAll(selector);
  if (elements.length !== 1) return { reason: elements.length ? 'ambiguous_target' : 'missing_target' };
  const el = elements[0];
  const credential = 'input[type="password"], input[type="hidden"], input[type="url"], [data-sensitive], [autocomplete="username"], [autocomplete*="password"], [autocomplete="one-time-code"]';
  if (el.matches(credential) || el.closest('[data-sensitive]') || el.querySelector(credential)
    || /(?:password|passwd|secret|token|credential|api.?key|authorization)/i.test(`${el.getAttribute('name') || ''} ${el.id}`)) return { reason: 'protected_target' };
  if (el.closest('[hidden]') || !el.getClientRects().length || !el.checkVisibility({ opacityProperty: true, visibilityProperty: true })) return { reason: 'hidden_target' };
  for (let ancestor = el; ancestor; ancestor = ancestor.parentElement) {
    const style = getComputedStyle(ancestor);
    if (style.display === 'none' || style.visibility !== 'visible' || Number(style.opacity) === 0) return { reason: 'hidden_target' };
  }
  let actual;
  if (property === 'checked') {
    if (!(el instanceof HTMLInputElement) || !['checkbox', 'radio'].includes(el.type)) return { reason: 'unsupported_property' };
    actual = el.checked;
  } else if (property === 'value') {
    if (!(el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement)) return { reason: 'unsupported_property' };
    actual = el.value;
  } else {
    if (/^(input|textarea|select|script|style|html|body|iframe)$/.test(el.localName)) return { reason: 'unsupported_property' };
    actual = el.innerText;
  }
  const passed = actual === expected;
  return { passed, result: passed ? 'pass' : 'fail', reason: null,
    element_id: window[Symbol.for(key)]?.ids?.get(el) ?? null,
    private_actual: actual, private_node: el };
}

function stripQuery(url) {
  try {
    const u = new URL(url);
    return `${u.origin}${u.pathname}`;
  } catch {
    return truncate(url, 200);
  }
}

/**
 * In-page, on the live screen: a static copy for the reflow pass and a fingerprint of
 * the screen. The copy is the DOM as the browser holds it, not the source text: style
 * elements carry their CSSOM rules (CSS-in-JS libraries insert rules that the element's
 * text never shows), constructed (adopted) sheets become style elements, open shadow
 * roots become declarative ones, and scripts, noscript and meta refresh are dropped
 * (the copy renders with scripts off). `rules` counts the accessible CSS rules, so the
 * pass can tell when the copy lost its styling. The key is the path, fragment, the
 * visible headings, dialogs and landmarks, and the ids of large visible regions, with
 * digits removed: a ticking timer or a counter does not make a new screen.
 */
function reflowCopy({ redactSelectors = [] } = {}) {
  const VOID = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr']);
  const esc = (t) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/ /g, '&nbsp;');
  const escAttr = (t) => t.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/ /g, '&nbsp;');
  let rules = 0;
  let inaccessibleStyles = 0;
  const sheetText = (sheet) => {
    try {
      const list = sheet.cssRules;
      rules += list.length;
      let t = '';
      for (const r of list) t += `${r.cssText}\n`;
      return t;
    } catch (e) {
      inaccessibleStyles++;
      return null; // a cross-origin sheet: its link reloads in the copy
    }
  };
  const styleTag = (t) => `<style>${t.replace(/<\/style/gi, '<\\/style')}</style>`;
  const out = [];
  const redacted = [];
  for (const selector of redactSelectors) {
    try { redacted.push(...document.querySelectorAll(selector)); } catch { /* invalid CSS stays unevaluable */ }
  }
  const privateNode = (node) => {
    for (let current = node; current; current = current.parentNode || current.host || null) {
      if (redacted.includes(current) || (current.matches && current.matches('input, textarea, select, [contenteditable], [data-sensitive], [data-private]'))) return true;
    }
    return false;
  };
  const adopted = (root) => {
    for (const sheet of root.adoptedStyleSheets || []) {
      const t = sheetText(sheet);
      if (t) out.push(styleTag(t));
    }
  };
  const walk = (node) => {
    for (const c of node.childNodes) {
      if (c.nodeType === 3) {
        out.push(privateNode(c) ? '[redacted]' : esc(c.nodeValue));
        continue;
      }
      if (c.nodeType !== 1) continue;
      const tag = c.localName;
      if (tag === 'script' || tag === 'noscript') continue;
      if (tag === 'meta' && /refresh/i.test(c.getAttribute('http-equiv') || '')) continue;
      out.push(`<${tag}`);
      for (const a of c.attributes) {
        if (privateNode(c) && (['value', 'title', 'aria-label', 'placeholder'].includes(a.name) || a.name.startsWith('data-'))) continue;
        out.push(` ${a.name}="${escAttr(a.value)}"`);
      }
      out.push('>');
      if (VOID.has(tag)) continue;
      if (tag === 'style') {
        const t = c.sheet ? sheetText(c.sheet) : null;
        out.push((t === null ? c.textContent : t).replace(/<\/style/gi, '<\\/style'), '</style>');
        continue;
      }
      if (c.shadowRoot) {
        out.push('<template shadowrootmode="open">');
        adopted(c.shadowRoot);
        walk(c.shadowRoot);
        out.push('</template>');
      }
      if (tag === 'template') {
        walk(c.content);
      } else if (tag === 'textarea' || tag === 'title') {
        out.push(privateNode(c) ? '[redacted]' : esc(c.textContent));
      } else {
        // The parser drops one newline right after <pre>, <listing> and <textarea>.
        if ((tag === 'pre' || tag === 'listing') && c.firstChild && c.firstChild.nodeType === 3 && c.firstChild.nodeValue[0] === '\n') out.push('\n');
        walk(c);
      }
      if (tag === 'head') adopted(document);
      out.push(`</${tag}>`);
    }
  };
  const dt = document.doctype;
  if (dt) {
    const ids = dt.publicId ? ` PUBLIC "${dt.publicId}"${dt.systemId ? ` "${dt.systemId}"` : ''}` : dt.systemId ? ` SYSTEM "${dt.systemId}"` : '';
    out.push(`<!DOCTYPE ${dt.name}${ids}>`);
  }
  walk(document);
  // Rules of sheets whose text is served (links): counted here and in the copy alike.
  for (const sheet of document.styleSheets) if (sheet.ownerNode && sheet.ownerNode.localName !== 'style') sheetText(sheet);
  const strip = (t) => (typeof t === 'string' ? t : '').replace(/\s+/g, ' ').replace(/[0-9]+/g, '#').trim().slice(0, 60);
  // The id attribute, not the property: a form's `id` property returns a control named "id".
  const idOf = (n) => n.getAttribute('id') || '';
  const shown = (n) => n.getClientRects().length > 0 && getComputedStyle(n).visibility === 'visible';
  const parts = [location.pathname.replace(/[0-9]+/g, '#'), strip(location.hash)];
  const marks = 'h1, h2, h3, [role="heading"], legend, dialog[open], [role="dialog"], [role="alertdialog"], [aria-modal="true"], [role="tabpanel"], main[id], form[id], section[id]';
  for (const n of document.querySelectorAll(marks)) {
    if (!shown(n)) continue;
    const titled = /^(h[1-3]|legend)$/.test(n.localName) || n.getAttribute('role') === 'heading';
    parts.push(`${n.localName}${idOf(n) ? `#${strip(idOf(n))}` : ''}${titled ? `:${strip(n.textContent)}` : ''}`);
    if (parts.length >= 80) break;
  }
  // Major regions with an id (half the width, a good part of the height): a step of a
  // form shown in place, a panel that opened. Small messages do not count.
  const major = new Set();
  for (const n of document.body ? document.body.querySelectorAll('[id]') : []) {
    const r = n.getBoundingClientRect();
    if (r.width < 0.5 * innerWidth || r.height < Math.min(120, 0.15 * innerHeight) || !shown(n)) continue;
    major.add(strip(idOf(n)));
    if (major.size >= 30) break;
  }
  parts.push(...[...major].sort().map((id) => `@${id}`));
  // Messages on screen (alerts, status, live regions with text): a toast or an error
  // is a state of its own, which a later copy without it must not replace.
  let alerts = 0;
  for (const n of document.querySelectorAll('[role="alert"], [role="status"], [aria-live="assertive"], [aria-live="polite"]')) {
    if (alerts >= 10 || !shown(n) || !(n.textContent || '').trim()) continue;
    parts.push(`!${n.localName}${idOf(n) ? `#${strip(idOf(n))}` : ''}`);
    alerts += 1;
  }
  return { html: out.join(''), rules, inaccessibleStyles, key: parts.join('|'),
    viewport: { width: innerWidth, height: innerHeight, dpr: devicePixelRatio, scale: visualViewport?.scale ?? 1 } };
}

/** In-page, on a reflow copy: the accessible CSS rules (document and open shadow roots, nested too). */
function reflowRuleCount() {
  let rules = 0;
  const count = (sheets) => {
    for (const sheet of sheets || []) {
      try {
        rules += sheet.cssRules.length;
      } catch (e) { /* cross-origin */ }
    }
  };
  count(document.styleSheets);
  count(document.adoptedStyleSheets);
  const visit = (root) => {
    for (const n of root.querySelectorAll('*')) {
      if (!n.shadowRoot) continue;
      count(n.shadowRoot.styleSheets);
      count(n.shadowRoot.adoptedStyleSheets);
      visit(n.shadowRoot);
    }
  };
  visit(document);
  return rules;
}

/**
 * In-page, on a static copy (1.4.10). Elements are indexed in one order across the
 * renders of a copy (document order, open shadow roots after their host), so a render
 * at the device width can be compared with the renders at 320 px.
 *
 * mode 'scan' (device width): for each element that owns text, the share of its box
 * left visible (null when it is not visible at all), and whether each element lies
 * entirely off screen sideways (off-canvas by design).
 * Otherwise (320 px): whether the page scrolls sideways, the outermost elements past
 * the right edge (two-dimensional content, inert and aria-hidden content exempt; inside
 * a fixed bar they count even when the page does not scroll, since a fixed box cannot be
 * scrolled to, unless the fixed box is wholly off screen: an off-canvas menu), and text
 * visible at the device width but cut away here ("lost"). `exempt_right` is the right
 * edge of the widest exempt element, so a page that scrolls only because of a table is
 * not reported as a page that does not reflow.
 */
function reflowInfo(arg) {
  const CAP = 20000;
  const up = (m) => m.assignedSlot || m.parentElement || (m.parentNode && m.parentNode.host) || null;
  // The id attribute, not the property: a form's `id` property returns a control named "id".
  const idOf = (n) => (n.getAttribute && n.getAttribute('id')) || '';
  const all = [];
  let capped = false;
  const visit = (root) => {
    for (const n of root.querySelectorAll('*')) {
      if (all.length >= CAP) {
        capped = true;
        return;
      }
      all.push(n);
      if (n.shadowRoot) visit(n.shadowRoot);
    }
  };
  if (document.body) visit(document.body);
  const top = (m) => !m || m === document.body || m === document.documentElement;
  const vw = window.innerWidth;
  const shown = (n) => (n.checkVisibility
    ? n.checkVisibility({ opacityProperty: true, visibilityProperty: true, checkOpacity: true, checkVisibilityCSS: true })
    : getComputedStyle(n).visibility === 'visible');
  // Regions a control points to (aria-controls: a collapsed disclosure, a carousel's
  // previous/next buttons, tabs): their clipped content is reachable through it.
  const controlledIds = new Set();
  for (const t of document.querySelectorAll('[aria-controls]')) for (const id of t.getAttribute('aria-controls').split(/\s+/)) if (id) controlledIds.add(id);
  const CAROUSEL = /(^|[\s_-])(carousel|swiper|slick|splide|glide|flickity|slider)([\s_-]|$)/i;
  const carousel = (m) => /carousel|slide/i.test(m.getAttribute('aria-roledescription') || '') || CAROUSEL.test(typeof m.className === 'string' ? m.className : '');
  // For an element that owns text, the share of its box left visible by clipping
  // ancestors up to the first scroll container (content there is reachable), and by the
  // viewport sideways when a fixed box holds it. Null when it owns no text, is not
  // visible, sits in a collapsed disclosure or a carousel track (reachable through its
  // controls), or in a fixed box wholly off screen (an off-canvas menu).
  const share = (n) => {
    let own = false;
    for (const c of n.childNodes) {
      if (c.nodeType === 3 && c.nodeValue.trim()) {
        own = true;
        break;
      }
    }
    if (!own) return null;
    const r = n.getBoundingClientRect();
    if (r.width <= 1 || r.height <= 1 || !shown(n)) return null;
    let x0 = r.left;
    let y0 = r.top;
    let x1 = r.right;
    let y1 = r.bottom;
    let fixed = getComputedStyle(n).position === 'fixed';
    let fixedBox = fixed ? r : null;
    for (let m = up(n); !fixed && !top(m); m = up(m)) {
      const cs = getComputedStyle(m);
      if (['auto', 'scroll'].includes(cs.overflowX) || ['auto', 'scroll'].includes(cs.overflowY)) break;
      const clipX = ['hidden', 'clip'].includes(cs.overflowX);
      const clipY = ['hidden', 'clip'].includes(cs.overflowY);
      if (clipX || clipY) {
        if (controlledIds.has(idOf(m)) || carousel(m)) return null;
        const a = m.getBoundingClientRect();
        if ((clipX && a.width <= 1) || (clipY && (a.height <= 1 || cs.maxHeight === '0px'))) return null; // collapsed
        if (clipX) {
          x0 = Math.max(x0, a.left);
          x1 = Math.min(x1, a.right);
        }
        if (clipY) {
          y0 = Math.max(y0, a.top);
          y1 = Math.min(y1, a.bottom);
        }
      }
      // Boxes above a fixed one do not clip it (it is placed against the viewport).
      if (cs.position === 'fixed') {
        fixed = true;
        fixedBox = m.getBoundingClientRect();
      }
    }
    if (fixed) {
      if (fixedBox.right <= 0 || fixedBox.left >= vw) return null; // off-canvas
      x0 = Math.max(x0, 0);
      x1 = Math.min(x1, vw);
    }
    return Math.round(100 * Math.max(0, x1 - x0) * Math.max(0, y1 - y0) / (r.width * r.height)) / 100;
  };
  if (arg.mode === 'scan' && !arg.probe) {
    const vis = [];
    const off = [];
    for (const n of all) {
      vis.push(share(n));
      const r = n.getBoundingClientRect();
      off.push(r.width > 1 && r.height > 1 && (r.right <= 0 || r.left >= vw) ? 1 : 0);
    }
    return { vis, off, count: all.length, capped };
  }
  const limit = arg.limit;
  const full = arg.full || { vis: [], off: [] };
  const se = document.scrollingElement || document.documentElement;
  const cw = se.clientWidth;
  const sw = se.scrollWidth;
  const clipX = (n) => ['hidden', 'clip'].includes(getComputedStyle(n).overflowX);
  const rootClips = clipX(document.documentElement) || (document.body ? clipX(document.body) : false);
  const out = { client_width: cw, scroll_width: sw, root_clips: rootClips, offenders: [], lost: [], exempt_right: null, scan_capped: capped || !!full.capped };
  const ids = (n) => {
    const list = [];
    for (let m = up(n); m && list.length < 6; m = up(m)) if (idOf(m)) list.push(idOf(m));
    return list;
  };
  const hidden = (n) => {
    for (let m = n; m && m.nodeType === 1 && m !== document.body; m = up(m)) if (m.getAttribute('aria-hidden') === 'true' || m.inert) return true;
    return false;
  };
  const TWO_D = new Set(['table', 'canvas', 'video', 'iframe', 'svg', 'pre', 'code', 'map', 'object', 'embed', 'math']);
  const twoD = (n) => {
    for (let m = n; m && m.nodeType === 1 && m !== document.body; m = up(m)) {
      const role = m.getAttribute('role') || '';
      if (TWO_D.has(m.localName) || ['img', 'application', 'grid', 'treegrid', 'table', 'toolbar'].includes(role)) return true;
    }
    return false;
  };
  const box = (r) => ({ x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) });
  const sel = (n) => {
    if (idOf(n)) return `#${CSS.escape(idOf(n))}`;
    const parts = [];
    for (let m = n; m && m.nodeType === 1 && m !== document.body && parts.length < 5; m = m.parentElement) {
      if (idOf(m)) {
        parts.unshift(`#${CSS.escape(idOf(m))}`);
        break;
      }
      const sib = m.parentElement ? [...m.parentElement.children].filter((c) => c.tagName === m.tagName) : [];
      parts.unshift(sib.length > 1 ? `${m.localName}:nth-of-type(${sib.indexOf(m) + 1})` : m.localName);
    }
    return parts.join(' > ');
  };
  // Additional conditions use text Range rectangles (the element's own box can
  // remain unchanged while glyphs are clipped). Scroll ranges describe the best
  // reachable position, so content below a fold is not automatically lost.
  if (arg.probe) {
    const gaps = new Set();
    const states = [];
    const plans = [];
    const textNodes = (n) => [...n.childNodes].filter((c) => c.nodeType === 3 && c.nodeValue.trim());
    const control = (n) => n.matches('button, a[href], input, select, textarea, summary, [role="button"], [tabindex]');
    const metric = (n) => {
      const cs = getComputedStyle(n);
      return { font_size: parseFloat(cs.fontSize), line_height: parseFloat(cs.lineHeight),
        paragraph_after: n.localName === 'p' ? parseFloat(cs.marginBlockEnd) : 0,
        letter_spacing: cs.letterSpacing === 'normal' ? 0 : parseFloat(cs.letterSpacing),
        word_spacing: cs.wordSpacing === 'normal' ? 0 : parseFloat(cs.wordSpacing) };
    };
    const eligible = (n) => {
      if (hidden(n) || !shown(n) || !n.getClientRects().length) return false;
      if (n.matches('canvas, iframe, object, embed, svg') || n.namespaceURI !== 'http://www.w3.org/1999/xhtml') {
        gaps.add('unsupported_content');
        return false;
      }
      if (getComputedStyle(n).writingMode !== 'horizontal-tb') { gaps.add('unsupported_script'); return false; }
      for (let m = n; m && !top(m); m = up(m)) {
        const cs = getComputedStyle(m);
        if (carousel(m) || (controlledIds.has(idOf(m)) && ['hidden', 'clip'].includes(cs.overflowY))) {
          gaps.add('alternate_access_unverified');
          return false;
        }
        const r = m.getBoundingClientRect();
        if ((r.width <= 1 || r.height <= 1) && (['hidden', 'clip'].includes(cs.overflowX) || ['hidden', 'clip'].includes(cs.overflowY))) return false;
        if (cs.position === 'fixed' && (r.right <= 0 || r.left >= vw)) return false;
      }
      return true;
    };
    // Read all authored values before changing any inherited property.
    if (arg.apply) {
      for (const n of all) {
        const nodes = textNodes(n);
        if ((!nodes.length && n.localName !== 'p') || !eligible(n)) continue;
        if (n.matches('input, textarea, select, option') || /\p{Co}/u.test(nodes.map((c) => c.nodeValue).join(''))) { gaps.add('unsupported_text'); continue; }
        const text = nodes.map((c) => c.nodeValue).join('');
        if (/[\p{Script=Arabic}\p{Script=Syriac}\p{Script=Thaana}]/u.test(text)) { gaps.add('unsupported_script'); continue; }
        const before = metric(n);
        if (!Object.values(before).every(Number.isFinite) || before.font_size <= 0) { gaps.add('unsupported_text_metrics'); continue; }
        const lang = (n.closest('[lang]')?.getAttribute('lang') || document.documentElement.lang).toLowerCase();
        plans.push({ n, before, paragraph: n.localName === 'p' && !/^(ja|zh)(-|$)/.test(lang), words: /\S\s+\S/u.test(text) });
      }
      for (const { n, before, paragraph, words } of plans) {
        for (const [property, key] of [['line-height', 'line_height'], ['letter-spacing', 'letter_spacing'], ...(words ? [['word-spacing', 'word_spacing']] : []), ...(paragraph ? [['margin-block-end', 'paragraph_after']] : [])]) {
          n.style.setProperty(property, `${Math.max(before[key], arg.spacing[key] * before.font_size)}px`, 'important');
        }
      }
    }
    const overlap = (a, b, lo, hi, min, max) => {
      // Union of positions accessible across ordinary scrolling. A long line
      // can be read in pieces; it need not fit one viewport simultaneously.
      // scrollWidth/clientWidth and their height counterparts are integer CSS
      // pixels, unlike Range coordinates. Allow their one-pixel edge rounding
      // only on axes with an observed scroll range; hidden clips retain exact bounds.
      const rounding = max > min ? 1 : 0;
      return Math.max(0, Math.min(b, hi - min + rounding) - Math.max(a, lo - max - rounding));
    };
    const visibleArea = (n, r) => {
      let w = r.width, h = r.height;
      let xmin = 0, xmax = 0, ymin = 0, ymax = 0, fixed = false;
      for (let m = n; m && m.nodeType === 1; m = up(m)) {
        const cs = getComputedStyle(m);
        const b = m.getBoundingClientRect();
        // Native scroll extents, including the current position, are independent
        // per axis. Never stop at a scroll box and ignore a clipping outer shell.
        if (m !== se && ['auto', 'scroll'].includes(cs.overflowX)) { xmin += m.scrollLeft - Math.max(0, m.scrollWidth - m.clientWidth); xmax += m.scrollLeft; }
        if (m !== se && ['auto', 'scroll'].includes(cs.overflowY)) { ymin += m.scrollTop - Math.max(0, m.scrollHeight - m.clientHeight); ymax += m.scrollTop; }
        if (['hidden', 'clip', 'auto', 'scroll'].includes(cs.overflowX)) w = Math.min(w, overlap(r.left, r.right, b.left + m.clientLeft, b.left + m.clientLeft + m.clientWidth, xmin, xmax));
        if (['hidden', 'clip', 'auto', 'scroll'].includes(cs.overflowY)) h = Math.min(h, overlap(r.top, r.bottom, b.top + m.clientTop, b.top + m.clientTop + m.clientHeight, ymin, ymax));
        if (cs.position === 'fixed') { fixed = true; break; }
      }
      const locked = [document.documentElement, document.body].filter(Boolean).some((m) => ['hidden', 'clip'].includes(getComputedStyle(m).overflowY));
      if (!fixed && !locked) { ymin += se.scrollTop - Math.max(0, se.scrollHeight - se.clientHeight); ymax += se.scrollTop; }
      if (!fixed && !rootClips) { xmin += se.scrollLeft - Math.max(0, se.scrollWidth - se.clientWidth); xmax += se.scrollLeft; }
      w = Math.min(w, overlap(r.left, r.right, 0, vw, xmin, xmax));
      h = Math.min(h, overlap(r.top, r.bottom, 0, innerHeight, ymin, ymax));
      return Math.max(0, w * h);
    };
    for (let i = 0; i < all.length; i++) {
      const n = all[i];
      const nodes = textNodes(n);
      const isControl = arg.probe === 'short_height' && control(n);
      if ((!nodes.length && !isControl) || !eligible(n)) continue;
      if (arg.probe === 'text_spacing' && (n.matches('input, textarea, select, option') || /\p{Co}/u.test(nodes.map((c) => c.nodeValue).join('')))) { gaps.add('unsupported_text'); continue; }
      const rects = [];
      if (isControl) rects.push(n.getBoundingClientRect());
      else for (const node of nodes) { const range = document.createRange(); range.selectNodeContents(node); rects.push(...range.getClientRects()); }
      if (rects.length > 1000 || states.length >= 2000) { capped = true; gaps.add('scan_capped'); break; }
      let area = 0, visible = 0;
      for (const r of rects) { if (r.width <= 0 || r.height <= 0) continue; area += r.width * r.height; visible += visibleArea(n, r); }
      if (!area) continue;
      const style = metric(n);
      if (arg.probe === 'text_spacing' && (!Object.values(style).every(Number.isFinite) || style.font_size <= 0)) { gaps.add('unsupported_text_metrics'); continue; }
      const plan = plans.find((p) => p.n === n);
      const applied = arg.apply ? !!plan && ['line_height', 'letter_spacing', ...(plan.words ? ['word_spacing'] : []), ...(plan.paragraph ? ['paragraph_after'] : [])].every((key) => style[key] + 0.05 >= Math.max(plan.before[key], arg.spacing[key] * style.font_size)) : false;
      if (arg.apply && !applied) { gaps.add('override_unverified'); continue; }
      states.push({ index: i, selector: sel(n), dom_id: idOf(n) || null, ancestor_ids: ids(n), tag: n.localName,
        kind: isControl ? 'control' : 'text', area, visible_area: visible, visible_fraction: Math.min(1, visible / area), box: box(n.getBoundingClientRect()),
        ...(arg.probe === 'text_spacing' ? { style, ...(plan ? { applied, properties: ['line_height', 'letter_spacing', ...(plan.words ? ['word_spacing'] : []), ...(plan.paragraph ? ['paragraph_after'] : [])] } : {}) } : {}) });
    }
    const lost = [];
    const baseline = new Map((arg.baseline?.states || []).map((s) => [s.index, s]));
    const changedIndices = new Set(states.map((s) => s.index));
    for (const before of baseline.values()) if (!changedIndices.has(before.index) && before.area - before.visible_area <= 0.25) gaps.add('content_disappeared_unverified');
    for (const after of states) {
      const before = baseline.get(after.index);
      // 0.25 CSS px² is numerical tolerance, independent of text length; a
      // percentage cutoff could overlook a clipped word in a long paragraph.
      if (!before || before.selector !== after.selector || before.area - before.visible_area > 0.25 || after.area - after.visible_area <= 0.25) continue;
      if (lost.length < 20) lost.push({ selector: after.selector, dom_id: after.dom_id, ancestor_ids: after.ancestor_ids, tag: after.tag, kind: after.kind,
        reason: after.kind === 'text' ? 'text_clipped' : 'control_clipped', before, after });
      else { gaps.add('findings_capped'); break; }
    }
    return { states, lost, count: all.length, evaluated: states.length, scan_capped: capped, applied: arg.apply ? plans.length > 0 && !gaps.has('override_unverified') : false, gaps: [...gaps] };
  }
  // Text visible at the device width but cut away by clipping containers here.
  if (full.vis.length) {
    for (let i = 0; i < all.length && out.lost.length < limit; i++) {
      if (full.vis[i] == null || full.vis[i] < 0.9) continue;
      const now = share(all[i]);
      if (now == null || now >= 0.5) continue;
      const n = all[i];
      if (twoD(n) || hidden(n)) continue;
      out.lost.push({ dom_id: idOf(n) || null, ancestor_ids: ids(n), tag: n.localName, visible_full: full.vis[i], visible_320: now,
        box: box(n.getBoundingClientRect()), text: (n.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 60) });
    }
  }
  const pageOverflow = sw > cw + 4 || rootClips;
  // How an element past the edge stays out of reach: 'page' (the page scrolls or the
  // root clips), 'fixed' (a fixed box holds it), or null (its own scroll or clipping
  // box). Boxes above a fixed one do not clip it.
  const reach = (n) => {
    if (getComputedStyle(n).position === 'fixed') return n.getBoundingClientRect().left >= cw - 1 ? null : 'fixed'; // null: off-canvas
    for (let m = up(n); !top(m); m = up(m)) {
      const cs = getComputedStyle(m);
      if (cs.overflowX === 'auto' || cs.overflowX === 'scroll') return null; // scrolls inside its own box
      if ((cs.overflowX === 'hidden' || cs.overflowX === 'clip') && m.getBoundingClientRect().right <= cw + 1) return null; // clipped by a box that fits
      if (cs.position === 'fixed') return m.getBoundingClientRect().left >= cw - 1 ? null : 'fixed'; // null: an off-canvas menu
    }
    return pageOverflow ? 'page' : null;
  };
  const hits = new Map();
  for (let i = 0; i < all.length; i++) {
    const n = all[i];
    const r = n.getBoundingClientRect();
    if (r.width <= 1 || r.height <= 1 || r.right <= cw + 4) continue; // 4 px tolerance (borders, rounding)
    const cs = getComputedStyle(n);
    if (cs.display === 'none' || cs.visibility !== 'visible' || parseFloat(cs.opacity) === 0) continue;
    // Off screen at the device width too (off-canvas by design), two-dimensional or hidden.
    if (full.off[i] || twoD(n) || hidden(n)) {
      out.exempt_right = Math.max(out.exempt_right || 0, Math.round(r.right));
      continue;
    }
    if (!(n.innerText || '').trim() && !['img', 'input', 'button', 'select', 'textarea'].includes(n.localName)) continue;
    const how = reach(n);
    if (how) hits.set(n, how);
  }
  for (const [n, how] of hits) {
    let outer = true;
    for (let m = up(n); m; m = up(m)) {
      if (hits.has(m)) {
        outer = false;
        break;
      }
    }
    if (!outer) continue;
    out.offenders.push({ selector: sel(n), dom_id: idOf(n) || null, ancestor_ids: ids(n), tag: n.localName, fixed: how === 'fixed',
      box: box(n.getBoundingClientRect()), text: (n.innerText || n.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 60) });
    if (out.offenders.length >= limit) break;
  }
  return out;
}

/**
 * In-page, on the element a click will land on: the focusable control it belongs to,
 * marked for focusProbe, with its box and small wrappers. Skipped (with a reason) when
 * there is none, when it is a text-entry field (the caret shows focus there), when it
 * already has focus, or when a text-entry field or editor has focus: taking focus from
 * it would fire its blur (validation that moves the layout) before the click, and
 * Chromium re-rasterises page text when an editable element loses focus, so the
 * captures would differ without any indicator.
 */
function probeTarget(start) {
  const FOCUSABLE = 'a[href], area[href], button, input, select, textarea, summary, [tabindex], [contenteditable=""], [contenteditable="true"]';
  const node = start && start.nodeType === 1 ? start : start && start.parentElement;
  // Roving-focus popups manage focus themselves (menus, listboxes).
  if (node && node.closest('[role="menu"], [role="menubar"], [role="listbox"], [role="tree"], [role="grid"]')) return { skip: 'managed_focus' };
  const el = node ? node.closest(FOCUSABLE) : null;
  if (!el || el.disabled || el.tabIndex < 0 || el.closest('[inert]')) return { skip: 'not_focusable' };
  const pressable = ['button', 'submit', 'reset', 'checkbox', 'radio', 'image', 'file', 'color', 'range'];
  const textEntry = (n) => !!n && n.nodeType === 1 && (n.tagName === 'TEXTAREA' || n.isContentEditable
    || (n.tagName === 'INPUT' && !pressable.includes((n.getAttribute('type') || 'text').toLowerCase())));
  if (textEntry(el)) return { skip: 'text_entry' };
  let active = document.activeElement;
  while (active && active.shadowRoot && active.shadowRoot.activeElement) active = active.shadowRoot.activeElement;
  if (active === el || (active && el.contains(active))) return { skip: 'already_focused' };
  const prev = active && active !== document.body && active !== document.documentElement ? active : null;
  // A focused text field or editor: before a button, the driver takes its focus away
  // first (its blur would run at the click anyway) and measures again. Not before other
  // targets, and not from a field with suggestions: a suggestion list that hides on
  // blur would be gone before the click.
  const field = textEntry(prev);
  const buttonLike = el.localName === 'button' || el.getAttribute('role') === 'button'
    || (el.localName === 'input' && ['submit', 'button', 'image', 'reset'].includes((el.getAttribute('type') || '').toLowerCase()));
  const suggests = !!prev && (prev.getAttribute('role') === 'combobox' || prev.hasAttribute('aria-autocomplete') || prev.hasAttribute('list')
    || prev.hasAttribute('aria-controls') || prev.hasAttribute('aria-owns'));
  if (field && (!buttonLike || suggests)) return { skip: 'field_focused' };
  const inFlat = (root, n) => {
    for (let x = n; x; x = x.assignedSlot || x.parentNode || x.host) if (x === root) return true;
    return false;
  };
  // Focus goes back to the previous element after the probe only where losing it would
  // change the page (an open menu or disclosure trigger, a dialog or popup that traps
  // focus); elsewhere the target is blurred, so a ring the restored focus would draw in
  // keyboard modality is not on screen when the click's feedback is measured.
  const keepPrev = !!prev && !field && (prev.getAttribute('aria-expanded') === 'true'
    || !!prev.closest('[role="dialog"], [role="alertdialog"], dialog[open], [aria-modal="true"], [role="menu"], [role="listbox"], [popover]'));
  // Boxes relative to the screen (the visual viewport, panned inside a wider layout
  // viewport when content is wider than the screen), like screenshot clips.
  const vvp = window.visualViewport;
  const one = !!vvp && Math.abs(vvp.scale - 1) < 0.01;
  const dx = one ? vvp.offsetLeft : 0;
  const dy = one ? vvp.offsetTop : 0;
  const r = el.getBoundingClientRect();
  const boxes = [{ x: r.left - dx, y: r.top - dy, w: r.width, h: r.height }];
  for (let n = el.parentElement, i = 0; n && n.nodeType === 1 && i < 3; n = n.parentElement, i++) {
    const a = n.getBoundingClientRect();
    if (a.width * a.height > 4 * Math.max(1, r.width * r.height)) break;
    boxes.push({ x: a.left - dx, y: a.top - dy, w: a.width, h: a.height });
  }
  // The previously focused control and its small wrappers: its own focus style goes
  // away when the target takes focus, so those pixels are not the target's indicator.
  // Not when it holds the target (a dialog or page container that took focus: its ring,
  // if any, stays with focus inside), and a wrapper that also holds the target keeps any
  // :focus-within style and is not masked (two buttons in one small group). A large
  // previous element is masked along its edges only (where a ring is drawn).
  const prevBoxes = [];
  if (prev && !field && !inFlat(prev, el)) {
    const p = prev.getBoundingClientRect();
    const large = p.width * p.height > 4 * Math.max(1, r.width * r.height);
    prevBoxes.push({ x: p.left - dx, y: p.top - dy, w: p.width, h: p.height, band: large });
    for (let n = prev.parentElement, i = 0; !large && n && n.nodeType === 1 && i < 3; n = n.parentElement, i++) {
      const a = n.getBoundingClientRect();
      if (inFlat(n, el) || a.width * a.height > 4 * Math.max(1, p.width * p.height)) break;
      prevBoxes.push({ x: a.left - dx, y: a.top - dy, w: a.width, h: a.height });
    }
  }
  window.__ergoProbeEl = el;
  window.__ergoProbePrev = prev;
  window.__ergoProbeKeep = keepPrev;
  return { boxes, prevBoxes, field, keepPrev, vw: one ? vvp.width : window.innerWidth, vh: one ? vvp.height : window.innerHeight, scroll: [window.scrollX, window.scrollY] };
}

function focusInfo() {
  let el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return null;
  let ox = 0;
  let oy = 0;
  let doc = document;
  const chain = [];
  for (let depth = 0; depth < 8; depth++) {
    chain.push(el);
    if (el.shadowRoot && el.shadowRoot.activeElement) {
      el = el.shadowRoot.activeElement;
      continue;
    }
    if (el.tagName === 'IFRAME') {
      let inner = null;
      try {
        inner = el.contentDocument && el.contentDocument.activeElement;
      } catch (e) {
        inner = null; // cross-origin frame: stop at the frame element
      }
      if (inner && inner !== el.contentDocument.body) {
        const fr = el.getBoundingClientRect();
        ox += fr.left + el.clientLeft;
        oy += fr.top + el.clientTop;
        doc = el.contentDocument;
        el = inner;
        continue;
      }
    }
    break;
  }
  const view = doc.defaultView || window;
  const r0 = el.getBoundingClientRect();
  const r = { left: r0.left + ox, top: r0.top + oy, width: r0.width, height: r0.height };
  r.right = r.left + r.width;
  r.bottom = r.top + r.height;
  // The screen is the visual viewport; at scale 1 it can be panned inside a wider
  // layout viewport (content wider than the screen). Sampling uses layout coordinates;
  // boxes are reported relative to the screen, like snapshot boxes and screenshot clips.
  const vvp = window.visualViewport;
  const panned = !!vvp && Math.abs(vvp.scale - 1) < 0.01
    && (vvp.offsetLeft > 0.5 || vvp.offsetTop > 0.5 || vvp.width < window.innerWidth - 1 || vvp.height < window.innerHeight - 1);
  const VX0 = panned ? vvp.offsetLeft : 0;
  const VY0 = panned ? vvp.offsetTop : 0;
  const vw = panned ? vvp.width : window.innerWidth;
  const vh = panned ? vvp.height : window.innerHeight;
  const esc = (v) => (window.CSS && CSS.escape ? CSS.escape(v) : v);
  let sel = el.id ? `#${esc(el.id)}` : null;
  if (!sel) {
    const parts = [];
    for (let n = el; n && n.nodeType === 1 && n !== doc.body && parts.length < 6; n = n.parentElement) {
      const tag = n.tagName.toLowerCase();
      if (n.id) {
        parts.unshift(`#${esc(n.id)}`);
        break;
      }
      const sib = n.parentElement ? [...n.parentElement.children].filter((c) => c.tagName === n.tagName) : [];
      parts.unshift(sib.length > 1 ? `${tag}:nth-of-type(${sib.indexOf(n) + 1})` : tag);
    }
    sel = parts.join(' > ');
  }
  const pathOf = (n) => {
    const out = [];
    for (let m = n; m && m.nodeType === 1; m = m.parentElement) out.unshift(m.parentElement ? [...m.parentElement.children].indexOf(m) : 0);
    return out.join('.');
  };
  const path = chain.map(pathOf).join('/');
  const inVp = r.width > 0 && r.height > 0 && r.right > VX0 && r.bottom > VY0 && r.left < VX0 + vw && r.top < VY0 + vh;
  const paints = (n) => {
    const cs = view.getComputedStyle(n);
    const bg = cs.backgroundColor || '';
    const alpha = /rgba\(.*,\s*([\d.]+)\)/.exec(bg);
    if (bg && bg !== 'transparent' && !(alpha && parseFloat(alpha[1]) === 0)) return true;
    if (cs.backgroundImage && cs.backgroundImage !== 'none') return true;
    if (['IMG', 'SVG', 'CANVAS', 'VIDEO'].includes(n.tagName.toUpperCase())) return true;
    for (const c of n.childNodes) if (c.nodeType === 3 && c.nodeValue.trim()) return true;
    return false;
  };
  // Content the user disclosed (WCAG 2.4.11 note): a layer tied to an expanded
  // trigger (aria-expanded="true" + aria-controls) or to a popovertarget button.
  const disclosed = [];
  for (const t of document.querySelectorAll('[aria-expanded="true"][aria-controls]')) {
    for (const id of (t.getAttribute('aria-controls') || '').split(/\s+/)) {
      const target = id && document.getElementById(id);
      if (target) disclosed.push(target);
    }
  }
  for (const t of document.querySelectorAll('[popovertarget]')) {
    const target = document.getElementById(t.getAttribute('popovertarget'));
    let open = false;
    try {
      open = !!target && target.matches(':popover-open');
    } catch (e) {
      open = false;
    }
    if (open) disclosed.push(target);
  }
  const userOpened = (layer) => disclosed.some((d) => d.contains(layer) || layer.contains(d));
  let covered = 0;
  let coveredBy = null;
  let coveredUserOpened = true;
  if (inVp && doc === document) {
    for (const fx of [0.15, 0.5, 0.85]) {
      for (const fy of [0.2, 0.5, 0.8]) {
        const px = Math.min(VX0 + vw - 1, Math.max(VX0, r.left + r.width * fx));
        const py = Math.min(VY0 + vh - 1, Math.max(VY0, r.top + r.height * fy));
        let hit = document.elementFromPoint(px, py);
        while (hit && hit.shadowRoot) {
          const inner = hit.shadowRoot.elementFromPoint(px, py);
          if (!inner || inner === hit) break;
          hit = inner;
        }
        if (!hit || hit === el || el.contains(hit) || hit.contains(el) || chain.includes(hit)) continue;
        let layer = null;
        for (let n = hit; n && n.nodeType === 1; n = n.parentElement) {
          const pos = getComputedStyle(n).position;
          // Fixed or sticky layers, and non-modal dialogs placed with position:absolute.
          const dialog = n.tagName === 'DIALOG' || ['dialog', 'alertdialog'].includes(n.getAttribute('role'));
          if (pos === 'fixed' || pos === 'sticky' || (pos === 'absolute' && dialog && n.getAttribute('aria-modal') !== 'true')) {
            layer = n;
            break;
          }
        }
        // A fixed dialog or sticky header that contains the focused element is its own
        // layer, not a cover; transparent click-catchers do not hide anything.
        if (layer && !layer.contains(el) && !chain.some((c) => layer.contains(c)) && (paints(hit) || paints(layer))) {
          covered += 1;
          if (!coveredBy) coveredBy = layer.id ? `#${esc(layer.id)}` : layer.tagName.toLowerCase();
          if (!userOpened(layer)) coveredUserOpened = false;
        }
      }
    }
  }
  const tag = el.tagName.toLowerCase();
  const field = ['input', 'select', 'textarea'].includes(tag);
  const txt = (n) => (n ? (n.innerText ?? n.textContent ?? '') : '').replace(/\s+/g, ' ').trim();
  const lb = (el.getAttribute('aria-labelledby') || '').split(/\s+/).map((id) => id && (el.getRootNode().getElementById
    ? el.getRootNode().getElementById(id) : doc.getElementById(id))).filter(Boolean).map(txt).join(' ').trim();
  const labels = el.labels && el.labels.length ? [...el.labels].map(txt).join(' ').trim() : '';
  const name = (lb || (el.getAttribute('aria-label') || '').trim() || labels || (el.getAttribute('title') || '').trim()
    || (field ? (el.getAttribute('placeholder') || '').trim() : el.isContentEditable ? '' : txt(el))).slice(0, 80);
  // Wrappers that draw the focus style (:focus-within borders): the nearest ancestors
  // up to 4x the element's area, so the indicator region includes them.
  const wraps = [];
  for (let n = el.parentElement, i = 0; n && n.nodeType === 1 && i < 3; n = n.parentElement, i++) {
    const a = n.getBoundingClientRect();
    if (a.width * a.height > 4 * Math.max(1, r0.width * r0.height)) break;
    wraps.push({ x: a.left + ox - VX0, y: a.top + oy - VY0, w: a.width, h: a.height });
  }
  return {
    selector: sel, dom_id: el.id || null, tag, role: el.getAttribute('role') || tag, name, path,
    frame: doc === document ? null : 'iframe',
    box: { x: Math.round((r.left - VX0) * 100) / 100, y: Math.round((r.top - VY0) * 100) / 100, w: Math.round(r.width * 100) / 100, h: Math.round(r.height * 100) / 100 },
    wrap_boxes: wraps,
    in_viewport: inVp, obscured_fraction: inVp && doc === document ? Math.round((covered / 9) * 1000) / 1000 : null, obscured_by: coveredBy,
    obscured_user_opened: covered > 0 ? coveredUserOpened : null, vw, vh,
  };
}

export class WebSession {
  constructor({ pw, pwInfo, scenario, deviceRequest, profileId, runId, runDir, mode, options, warnings }) {
    this.pw = pw;
    this.pwInfo = pwInfo;
    this.scenario = scenario;
    this.deviceRequest = deviceRequest;
    this.profileId = profileId;
    this.runId = runId;
    this.runDir = runDir;
    this.mode = mode;
    this.opts = options;
    this.warnings = [...(warnings || [])];
    this.warned = new Set();
    this.steps = [];
    this.taskCheckResults = new Map();
    this.authoredInputs = new Set();
    this.mismatchedInputs = new Set();
    this.privateValues = new Set();
    this.redactSelectors = new Set();
    for (const action of scenario.steps) this.rememberPrivateAction(action);
    for (const check of scenario.success?.task_checks || []) {
      if (check.redact) {
        this.redactSelectors.add(check.selector);
        if (typeof check.expected === 'string' && check.expected) this.privateValues.add(check.expected);
      }
    }
    this.snapshots = [];
    this.snapElements = new Map();
    this.personaNotes = [];
    this.consoleAll = [];
    this.consolePending = [];
    this.navEvents = [];
    this.navRequestPending = false;
    this.flashSamples = [];
    this.flashBytes = 0;
    this.flashTruncated = null;
    this.flashGrid = null;
    this.flashPrev = null; // last flash frame (across bursts) for block motion
    this.focusWalks = [];
    this.reflowScreens = [];
    this.reflowDropped = new Set();
    this.reflow = [];
    this.adaptation = [];
    this.frameIndex = 0;
    this.blocked = [];
    this.blockedCount = 0;
    this.blockedConsole = 0;
    this.blockReasons = [];
    this.snapSeq = 0;
    this.inspectSeq = 0;
    this.lastSnapshotId = null;
    this.focusPoint = null;
    this.lastActive = null;
    this.clockOffset = 0;
    this.clockRtt = null;
    this.needCalibrate = false;
    this.crashed = false;
    this.finished = null;
    this.startedAt = isoNow();
    this.runStartEpoch = epochNow();
    this.httpStatus = null;
    this.twPollers = [];
    this.tw = new Map(scenario.timing_windows.map((w) => [w.id, {
      def: w, cur: null, intervals: [], starts: [], appearances: 0, firstVisible: null, text: null, method: 'in-page-poll', fallback: false, error: null,
    }]));
    const allowed = new Set(['http:', 'https:'].includes(scenario.origin.protocol) ? [scenario.origin.origin] : []);
    for (const o of options.allowOrigins || []) allowed.add(o);
    this.allowedOrigins = allowed;
  }

  warnOnce(key, msg) {
    if (this.warned.has(key)) return;
    this.warned.add(key);
    this.warnings.push(msg);
  }

  block(reason) {
    this.blockReasons.push(reason);
  }

  rel(epoch) {
    return Math.max(0, round1(epoch - this.runStartEpoch));
  }

  rememberPrivateAction(action) {
    if (action.redact) {
      if (action.text) this.privateValues.add(action.text);
      if (typeof action.target === 'string') this.redactSelectors.add(action.target);
    }
  }

  redactRecord(record, key = '') {
    if (typeof record === 'string') {
      if (key === 'notes' && record === 'task_check_final') return record;
      if (key && !['text', 'value', 'selected', 'described_by_text', 'name', 'title', 'error', 'message', 'stack', 'intent', 'expected', 'observed', 'consequence', 'description', 'note', 'notes', 'warnings', 'blocked_reasons', 'console_errors'].includes(key)) return record;
      for (const value of this.privateValues) record = record.split('[redacted]').map((part) => part.split(value).join('[redacted]')).join('[redacted]');
      return record;
    }
    if (Array.isArray(record)) return record.map((value) => this.redactRecord(value, key));
    if (record && typeof record === 'object') return Object.fromEntries(Object.entries(record).map(([field, value]) => [field, key === 'driver' && field === 'name' ? value : this.redactRecord(value, field)]));
    return record;
  }

  // ------------------------------------------------------------------ lifecycle

  async start() {
    this.browserTransport = await openBrowser(this.pw, this.pwInfo, { headless: !this.opts.headed, timeout: 60000 });
    this.browser = this.browserTransport.browser;
    this.browserVersion = this.browserTransport.browserVersion;
    const dev = resolveDevice({
      ...this.deviceRequest,
      pwDevices: this.pw.devices,
      chromeMajor: parseInt(this.browserVersion, 10),
    });
    this.dev = dev;
    for (const w of dev.warnings) this.warnOnce(`dev:${w}`, w);
    this.vw = dev.contextOptions.viewport.width;
    this.vh = dev.contextOptions.viewport.height;
    this.context = await this.browser.newContext({
      ...dev.contextOptions,
      locale: this.opts.locale,
      timezoneId: this.opts.timezoneId,
      colorScheme: 'light',
      reducedMotion: 'no-preference',
      serviceWorkers: 'block',
      acceptDownloads: false,
    });
    await this.context.route('**/*', (route) => this.onRoute(route));
    await this.context.routeWebSocket(/.*/, (ws) => this.onWebSocket(ws));
    const windows = this.scenario.timing_windows;
    if (windows.length) {
      await this.context.exposeBinding(TW_BINDING, (source, payload) => this.onTimingWindow(source, payload));
    }
    await this.context.addInitScript(pageInit, {
      key: STATE_KEY,
      binding: windows.length ? TW_BINDING : null,
      windows: windows.map((w) => ({ id: w.id, selector: w.selector })),
      pollMs: TW_POLL_MS,
    });
    this.page = await this.context.newPage();
    this.cdp = await this.context.newCDPSession(this.page);
    this.page.on('console', (msg) => {
      if (msg.type() === 'error') this.pushConsole('console', msg.text(), msg.location());
    });
    this.page.on('pageerror', (err) => this.pushConsole('pageerror', err && err.message ? err.message : String(err), null));
    this.page.on('crash', () => {
      this.crashed = true;
      this.block('page crashed');
    });
    this.page.on('request', (req) => {
      try {
        if (req.isNavigationRequest() && req.frame() === this.page.mainFrame()) {
          this.navEvents.push(epochNow());
          this.navRequestPending = true;
        }
      } catch { /* request without frame (service worker) */ }
    });
    this.page.on('framenavigated', (frame) => {
      if (frame !== this.page.mainFrame()) return;
      const t = epochNow();
      this.navEvents.push(t);
      if (this.navRequestPending) {
        // A new document replaced the old one: its timed elements are gone.
        this.navRequestPending = false;
        for (const w of this.tw.values()) if (w.cur) this.applyTransition(w, false, t, null);
        this.needCalibrate = true;
      }
    });

    this.runStartEpoch = epochNow();
    this.startedAt = isoNow();
    let response = null;
    try {
      response = await this.page.goto(this.scenario.url, { waitUntil: 'load', timeout: 30000 });
    } catch (err) {
      this.block(`initial navigation failed: ${firstLine(err.message)}`);
    }
    this.httpStatus = response ? response.status() : null;
    if (response && response.status() >= 400) this.block(`initial navigation returned HTTP ${response.status()}`);
    await this.calibrate().catch(() => {});
    this.needCalibrate = false;
    await sleep(this.opts.settleMs);
    if (this.opts.flashSampleMs > 0) {
      await this.probeFrames({ dispatch: epochNow(), stepIndex: 0, flashMs: this.opts.flashSampleMs, visual: null, fb: { done: true } });
    }
    await this.snapshot(0, []);
  }

  reflowEnabled() {
    if (this.opts.reflow === false) return false;
    // 1.4.10 is about zooming to 320 CSS px; TVs and handheld consoles have no browser zoom.
    return this.scenario.surface_kind !== 'game' && !['tv', 'handheld_console'].includes(this.dev.snapshotDevice.form_factor);
  }

  /**
   * Keep a static copy of a screen for the reflow pass: one per screen fingerprint
   * (reflowCopy's key), the newest copy replacing an older one, at most
   * REFLOW_MAX_SCREENS screens; later new screens are counted as dropped.
   */
  async keepForReflow(snapshotId) {
    if (!this.reflowEnabled()) return;
    try {
      const copy = await this.page.evaluate(reflowCopy, { redactSelectors: [...this.redactSelectors] });
      copy.html = this.redactRecord(copy.html);
      const url = this.page.url();
      const key = `${stripQuery(url)}|${copy.key}`;
      const kept = this.reflowScreens.find((s) => s.key === key);
      if (kept) {
        Object.assign(kept, { ...copy, key, snapshot_id: snapshotId, url });
      } else if (this.reflowScreens.length < REFLOW_MAX_SCREENS) {
        this.reflowScreens.push({ ...copy, key, snapshot_id: snapshotId, url });
      } else if (!this.reflowDropped.has(key)) {
        this.reflowDropped.add(key);
      }
    } catch (err) {
      // Navigating: the next snapshot keeps the screen. Anything else is worth a note.
      if (!/navigat|context was destroyed|Target closed/i.test(String(err && err.message))) {
        this.warnOnce('reflow-copy', `reflow copy failed: ${firstLine(err && err.message)}`);
      }
    }
  }

  /**
   * Load a kept copy in the reflow page under its own URL (fulfilled from memory, so
   * the site's CSS and fonts load same-origin as in the run), scripts off.
   */
  async loadReflowCopy(page, screen) {
    // Transitions would animate the resize to 320 px; the copy carries a rule that turns
    // them off (written into the HTML: with scripts off, an injected tag never reports load).
    const noTransitions = '<style>*, *::before, *::after { transition: none !important; }</style>';
    const html = /<\/head>/i.test(screen.html) ? screen.html.replace(/<\/head>/i, (m) => `${noTransitions}${m}`) : `${noTransitions}${screen.html}`;
    let target = null;
    try {
      const u = new URL(screen.url);
      if (u.protocol === 'http:' || u.protocol === 'https:') {
        u.hash = '';
        target = u.href;
      }
    } catch { /* not a URL */ }
    await page.goto('about:blank').catch(() => {});
    if (!target) {
      const base = `<base href="${screen.url.replace(/"/g, '&quot;')}">`;
      const withBase = /<base\s/i.test(html) ? html
        : /<head[^>]*>/i.test(html) ? html.replace(/<head[^>]*>/i, (m) => `${m}${base}`) : `${base}${html}`;
      await page.setContent(withBase, { waitUntil: 'load', timeout: 8000 });
      return;
    }
    const match = (u) => u.href === target;
    const handler = (route) => {
      const req = route.request();
      if (req.isNavigationRequest() && req.frame() === page.mainFrame()) {
        return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body: html });
      }
      return route.fallback();
    };
    await page.route(match, handler);
    try {
      await page.goto(screen.url, { waitUntil: 'load', timeout: 8000 });
    } finally {
      await page.unroute(match, handler).catch(() => {});
    }
    // Web fonts load on first use; wait briefly so text is measured in its own font (the
    // time limit is kept here: page timers may not run with scripts off).
    await Promise.race([page.evaluate(() => document.fonts.ready.then(() => true)).catch(() => false), sleep(1500)]);
  }

  /** Auxiliary snapshots use the existing PNG/JSON and QA receipt path. They
   * never advance the live task's capture, focus, input, or screen-copy state. */
  async adaptationCapture(page, screen, kind, condition) {
    const id = `S-${this.runId}-${String(this.snapSeq++).padStart(3, '0')}`;
    const png = await page.screenshot({ type: 'png', scale: 'device', timeout: 15000 });
    const ex = await page.evaluate(extractSnapshot, { key: STATE_KEY, cap: ELEMENT_CAP, knownRoles: KNOWN_ROLES,
      redactSelectors: [...this.redactSelectors], privateValues: [...this.privateValues, '[redacted]'] });
    const { width, height } = pngSize(png);
    const viewport = page.viewportSize();
    const snap = this.redactRecord({
      schema_version: 'ergo-snapshot.v1', snapshot_id: id, run_id: this.runId,
      step_index: this.snapshots.find((s) => s.snapshot_id === screen.snapshot_id)?.step_index ?? 0, captured_at: isoNow(),
      surface: { kind: 'web', url: screen.url, title: await page.title(), app_id: null, scroll: ex.scroll, visual: ex.visual,
        ...(this.opts.buildId ? { build_id: this.opts.buildId, build_id_basis: 'operator_supplied', build_id_source: this.opts.buildIdSource } : {}) },
      device: { ...this.dev.snapshotDevice, viewport_css: [viewport.width, viewport.height], probe: 'adaptation' },
      adaptation: { kind, source_snapshot_id: screen.snapshot_id, condition },
      screenshot: { path: `${id}.png`, sha256: sha256(png), width_px: width, height_px: height },
      elements: ex.elements, focus_point: null, console_errors: [], notes: ['static_copy', ...(ex.truncated ? ['elements capped in auxiliary capture'] : [])],
    });
    writeFileAtomic(path.join(this.runDir, `${id}.png`), png);
    writeJsonAtomic(path.join(this.runDir, `${id}.json`), snap);
    this.snapshots.push({ snapshot_id: id, step_index: snap.step_index, path: `${id}.json`, png: `${id}.png` });
    return id;
  }

  async adaptationPass() {
    if (!this.reflowScreens.length) return;
    let context;
    const deadline = epochNow() + REFLOW_BUDGET_MS;
    try {
      context = await this.browser.newContext({ ...this.dev.contextOptions, javaScriptEnabled: false,
        locale: this.opts.locale, timezoneId: this.opts.timezoneId, colorScheme: 'light', serviceWorkers: 'block', acceptDownloads: false });
      await this.installNetworkPolicy(context, false);
      const page = await context.newPage();
      for (const screen of this.reflowScreens) {
        const baselineViewport = [this.vw, this.vh];
        const shortHeight = Math.max(SHORT_HEIGHT.min_height_css, Math.floor(this.vh * SHORT_HEIGHT.height_ratio));
        for (const [kind, condition, height] of [['text_spacing', TEXT_SPACING, this.vh], ['short_height', SHORT_HEIGHT, shortHeight]]) {
          const rec = { kind, condition, source_snapshot_id: screen.snapshot_id, baseline_snapshot_id: null, snapshot_id: null,
            baseline_viewport_css: baselineViewport, viewport_css: [this.vw, height], dpr: this.dev.snapshotDevice.dpr,
            status: 'unevaluable', applied: false, evaluable: false, scan_capped: false, gaps: [], lost: [], evaluated_elements: 0 };
          this.adaptation.push(rec);
          if (kind === 'short_height' && this.vh <= SHORT_HEIGHT.min_height_css) { rec.status = 'inapplicable'; rec.gaps.push('baseline_already_short'); continue; }
          if (epochNow() > deadline) { rec.gaps.push('budget_exhausted'); continue; }
          try {
            if (screen.viewport.width !== this.vw || screen.viewport.height !== this.vh || screen.viewport.dpr !== rec.dpr || screen.viewport.scale !== 1) { rec.gaps.push('capture_mapping_unverified'); continue; }
            await page.setViewportSize({ width: this.vw, height: this.vh });
            await this.loadReflowCopy(page, screen);
            const rules = await page.evaluate(reflowRuleCount);
            rec.styles = { live_rules: screen.rules, copy_rules: rules, complete: !screen.inaccessibleStyles && rules >= screen.rules };
            if (!rec.styles.complete) { rec.gaps.push('styles_incomplete'); continue; }
            const before = await page.evaluate(reflowInfo, { probe: kind });
            rec.baseline_snapshot_id = await this.adaptationCapture(page, screen, 'baseline', null);
            if (kind === 'short_height') await page.setViewportSize({ width: this.vw, height });
            const after = await page.evaluate(reflowInfo, { probe: kind, baseline: before, apply: kind === 'text_spacing', spacing: TEXT_SPACING });
            rec.applied = kind === 'short_height' || after.applied;
            rec.evaluated_elements = after.evaluated;
            if (kind === 'text_spacing') rec.overrides = after.states.filter((s) => s.applied).slice(0, 20)
              .map((s) => ({ selector: s.selector, before: before.states.find((b) => b.index === s.index)?.style ?? null, after: s.style, properties: s.properties }));
            rec.scan_capped = before.scan_capped || after.scan_capped;
            rec.gaps = [...new Set([...before.gaps, ...after.gaps, ...(rec.scan_capped ? ['scan_capped'] : []), ...(before.count !== after.count ? ['copy_disconnected'] : [])])];
            if (!rec.applied) rec.gaps.push('condition_unverified');
            if (!after.evaluated) rec.gaps.push('no_supported_content');
            rec.evaluable = rec.applied && !rec.scan_capped && before.count === after.count && after.evaluated > 0 && !rec.gaps.includes('content_disappeared_unverified');
            rec.snapshot_id = await this.adaptationCapture(page, screen, kind, condition);
            rec.status = rec.evaluable ? 'measured' : 'unevaluable';
            if (rec.evaluable) rec.lost = after.lost;
          } catch (err) {
            rec.status = 'unevaluable'; rec.evaluable = false; rec.lost = []; rec.gaps.push('probe_failed');
            this.warnOnce('adaptation-failed', `adaptation copy failed: ${firstLine(err.message)}`);
          }
        }
      }
    } finally {
      if (context) await context.close().catch(() => {});
    }
  }

  /**
   * Re-render the kept screens at 320 CSS px, scripts off, and record what sticks out
   * or is cut away. A copy that lost most of its CSS rules (a sheet failed to load) is
   * recorded as styles_lost and not measured.
   */
  async reflowPass() {
    if (this.reflowDropped.size) {
      this.warnings.push(`reflow: ${this.reflowDropped.size} screen(s) after the first ${REFLOW_MAX_SCREENS} were not re-rendered at 320 px`);
    }
    if (!this.reflowScreens.length) return;
    let context = null;
    const deadline = epochNow() + REFLOW_BUDGET_MS;
    try {
      const touch = this.dev.snapshotDevice.input === 'touch';
      context = await this.browser.newContext({
        viewport: { width: REFLOW_WIDTH, height: touch ? 568 : 256 }, deviceScaleFactor: 1, javaScriptEnabled: false,
        locale: this.opts.locale, timezoneId: this.opts.timezoneId, colorScheme: 'light', serviceWorkers: 'block', acceptDownloads: false,
      });
      await this.installNetworkPolicy(context, false);
      const page = await context.newPage();
      for (const screen of this.reflowScreens) {
        if (epochNow() > deadline) {
          this.warnings.push(`reflow pass stopped at its ${REFLOW_BUDGET_MS} ms budget`);
          break;
        }
        const rec = { snapshot_id: screen.snapshot_id, url: screen.url, width: REFLOW_WIDTH };
        try {
          // The copy at the device width first, then at 320 px with the same height, so
          // only the narrower width can cut text away (a 100vh app shell with
          // overflow:hidden would otherwise lose content to the shorter viewport alone).
          // Sideways overflow is then measured at 320 px by the short zoomed height.
          await page.setViewportSize({ width: this.vw, height: this.vh });
          await this.loadReflowCopy(page, screen);
          const rules = await page.evaluate(reflowRuleCount).catch(() => null);
          if (screen.rules >= 20 && rules !== null && rules < 0.9 * screen.rules) {
            this.reflow.push({ ...rec, styles_lost: { live_rules: screen.rules, copy_rules: rules } });
            this.warnings.push(`reflow copy of ${screen.snapshot_id} kept ${rules} of ${screen.rules} CSS rules; not measured`);
            continue;
          }
          const full = await page.evaluate(reflowInfo, { mode: 'scan' });
          await page.setViewportSize({ width: REFLOW_WIDTH, height: this.vh });
          await sleep(50);
          const narrow = await page.evaluate(reflowInfo, { limit: 20, full: { vis: full.vis, off: [], capped: full.capped } });
          await page.setViewportSize({ width: REFLOW_WIDTH, height: touch ? 568 : 256 });
          await sleep(50);
          const info = await page.evaluate(reflowInfo, { limit: 20, full: { vis: [], off: full.off, capped: full.capped } });
          this.reflow.push({ ...rec, ...info, lost: narrow.lost, lost_height: this.vh, scan_capped: info.scan_capped || narrow.scan_capped });
        } catch (err) {
          this.reflow.push({ ...rec, error: firstLine(err.message) });
        }
      }
    } catch (err) {
      this.warnings.push(`reflow pass failed: ${firstLine(err.message)}`);
    } finally {
      if (context) await context.close().catch(() => {});
      this.reflowScreens = [];
    }
  }

  /**
   * A layer that opened without focus inside at the after-snapshot: dialogs often move
   * focus after their entrance transition. Poll focus until one second after the input
   * (after a wait or snapshot step: 0.7 s from now, since a dialog seen at its end may
   * be mid-transition), at least once; layers focus reached are listed on the step
   * (focus_late_layers). Focus on the layer's overlay root counts only when the root is
   * an ancestor of the layer (a portal that focuses itself), as in the extract.
   */
  async lateLayerFocus(step, layersBefore, waitStep = false) {
    if (this.scenario.surface_kind === 'game') return;
    const pending = (this.lastLayers || []).filter((l) => !layersBefore.has(l.selector) && !l.contains_focus)
      .map((l) => ({ sel: l.selector, root: l.overlay_root || null }));
    if (!pending.length) return;
    const deadline = waitStep ? epochNow() + 700 : Math.max(this.runStartEpoch + step.t_start_ms + 1000, epochNow() + 100);
    const reached = new Set();
    do {
      await sleep(50);
      const inside = await this.page.evaluate((layers) => {
        let deep = document.activeElement;
        while (deep && deep.shadowRoot && deep.shadowRoot.activeElement) deep = deep.shadowRoot.activeElement;
        if (!deep || deep === document.body) return [];
        const inFlat = (root, n) => {
          for (let x = n; x; x = x.assignedSlot || x.parentNode || x.host) if (x === root) return true;
          return false;
        };
        const find = (sel) => {
          try {
            return sel ? document.querySelector(sel) : null;
          } catch (e) {
            return null;
          }
        };
        return layers.filter(({ sel, root }) => {
          const node = find(sel);
          if (!node) return false;
          const r = find(root);
          return inFlat(node, deep) || (!!r && inFlat(r, deep) && inFlat(deep, node));
        }).map(({ sel }) => sel);
      }, pending).catch(() => []);
      for (const sel of inside) reached.add(sel);
    } while (epochNow() < deadline && reached.size < pending.length);
    if (reached.size) step.focus_late_layers = [...reached];
  }

  /** A step target the scenario declares timed (a timing window or a timed/game target). */
  timedTarget(target) {
    if (typeof target !== 'string') return false;
    if ((this.scenario.timing_windows || []).some((w) => w.selector === target)) return true;
    const t = this.scenario.targets || {};
    return ['timed', 'game_control'].some((role) => (t[role] || []).includes(target));
  }

  focusWalkEnabled() {
    if (this.opts.focusWalk === true || this.opts.focusWalk === false) return this.opts.focusWalk;
    return !!this.dev && ['mouse', 'keyboard'].includes(this.dev.base.input);
  }

  /** Network policy for a context: HTTP and WebSocket. `count` = add blocks to run.json. */
  async installNetworkPolicy(context, count) {
    if (count) {
      await context.route('**/*', (route) => this.onRoute(route));
      await context.routeWebSocket(/.*/, (ws) => this.onWebSocket(ws));
      return;
    }
    await context.route('**/*', (route) => (this.isAllowed(route.request().url()) ? route.continue() : route.abort('blockedbyclient')).catch(() => {}));
    await context.routeWebSocket(/.*/, (ws) => {
      if (this.isAllowed(ws.url().replace(/^ws/, 'http'))) ws.connectToServer();
      else ws.close({ code: 1008, reason: 'blocked by ergoqa network policy' }).catch(() => {});
    });
  }

  /** Focus walk of the initial screen in a separate context, so the run's page keeps its state. */
  async focusWalkFresh() {
    let context = null;
    try {
      context = await this.browser.newContext({
        ...this.dev.contextOptions, locale: this.opts.locale, timezoneId: this.opts.timezoneId, colorScheme: 'light',
        reducedMotion: 'no-preference', serviceWorkers: 'block', acceptDownloads: false,
      });
      await this.installNetworkPolicy(context, false);
      const page = await context.newPage();
      await page.goto(this.scenario.url, { waitUntil: 'load', timeout: 30000 });
      await sleep(this.opts.settleMs);
      await this.focusWalk(page, 'load', this.snapshots.length ? this.snapshots[0].snapshot_id : null);
    } catch (err) {
      this.warnings.push(`focus walk (load) failed: ${firstLine(err.message)}`);
    } finally {
      if (context) await context.close().catch(() => {});
    }
  }

  /** Clip of the page (or the whole viewport) at CSS scale, decoded (focus indicator comparison). */
  async clipFrame(page, clip, animations = 'disabled') {
    const opts = { scale: 'css', animations, caret: 'hide', timeout: 5000 };
    const buf = await page.screenshot(clip ? { ...opts, clip } : opts);
    return frameFromImage(decodePng(buf));
  }

  /** The whole screen downscaled to about FOCUS_VIEWPORT_WIDTH px wide (CDP; fast). */
  async viewportFrame(cdp) {
    return this.visualFrame(cdp, FOCUS_VIEWPORT_WIDTH);
  }

  /**
   * What the screen shows (the visual viewport), downscaled to `targetW` px wide, always
   * the same size for a session. CDP clips are in document coordinates, so the clip
   * starts at the visual viewport's page position (a clip at 0,0 would capture the top
   * of a scrolled document). A clip also snaps a visual viewport that is panned inside
   * a wider layout viewport (content wider than the screen) back to the layout
   * viewport, which moves the page under the next tap; a panned viewport is therefore
   * captured whole, without a clip, and downscaled here. A downscaling clip also stops
   * a scroll gesture in progress on an inner scroll container (touch or wheel: the
   * content does not move at all), so during gesture steps (wholeFrames) frames are
   * captured whole too.
   */
  async visualFrame(cdp, targetW) {
    const w = Math.max(1, Math.round(Math.min(this.vw, targetW)));
    const h = Math.max(1, Math.round((this.vh * w) / this.vw));
    const m = await cdp.send('Page.getLayoutMetrics').catch(() => null);
    const v = m && (m.cssVisualViewport || m.visualViewport);
    let r;
    if (this.wholeFrames || (v && (Math.abs(v.offsetX) > 0.5 || Math.abs(v.offsetY) > 0.5))) {
      r = await cdp.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false, optimizeForSpeed: true });
    } else {
      const cw = v ? v.clientWidth : this.vw;
      const chh = v ? v.clientHeight : this.vh;
      r = await cdp.send('Page.captureScreenshot', {
        format: 'png', clip: { x: v ? v.pageX : 0, y: v ? v.pageY : 0, width: cw, height: chh, scale: Math.min(1, w / cw) },
        captureBeyondViewport: false, optimizeForSpeed: true,
      });
    }
    let img = decodePng(Buffer.from(r.data, 'base64'));
    if (img.width !== w || img.height !== h) img = resampleImage(img, w, h);
    const frame = frameFromImage(img);
    // Where the screen is on the page, and CSS px per frame px: the page's own scroll
    // between two frames is then a known motion (flash sampling).
    frame.page = v ? [v.pageX, v.pageY] : null;
    frame.cssPerPx = [(v ? v.clientWidth : this.vw) / w, (v ? v.clientHeight : this.vh) / h];
    return frame;
  }

  /** Blur the deepest focused element (kept for refocus); false when nothing is focused. */
  async blurFocused(page) {
    return page.evaluate(() => {
      let el = document.activeElement;
      while (el && el.shadowRoot && el.shadowRoot.activeElement) el = el.shadowRoot.activeElement;
      if (!el || el === document.body) return false;
      el.blur();
      window.__ergoFocusEl = el;
      return true;
    });
  }

  async refocus(page) {
    await page.evaluate(() => {
      const el = window.__ergoFocusEl;
      if (el) el.focus({ preventScroll: true });
    });
  }

  /**
   * Tab through the page from the top: per stop, the focused element, how many pixels
   * its focus changes (focused vs blurred, same scroll position, animation masked) in
   * its box and its small wrappers (indicator_px) and, when that is nearly nothing, in
   * the whole viewport (indicator_any_px), and whether a painting fixed or sticky layer
   * or a non-modal absolute dialog covers it (and, in the end state, whether Escape
   * reveals it when the user opened that layer). Bounded by FOCUS_WALK_MAX stops and
   * FOCUS_WALK_BUDGET_MS.
   */
  async focusWalk(page, phase, snapshotId) {
    const stops = [];
    let ended = 'max_stops';
    const deadline = epochNow() + FOCUS_WALK_BUDGET_MS;
    // Smooth scrolling would leave focused elements mid-animation when measured.
    await page.addStyleTag({ content: 'html, body { scroll-behavior: auto !important; }' }).catch(() => {});
    // Reset the sequential focus navigation starting point to the top of the document
    // (blur alone keeps it at the last focused or autofocused element).
    await page.evaluate(() => {
      window.scrollTo(0, 0);
      const b = document.body;
      if (!b) return;
      const had = b.getAttribute('tabindex');
      b.tabIndex = -1;
      b.focus({ preventScroll: true });
      b.blur();
      if (had === null) b.removeAttribute('tabindex');
      else b.setAttribute('tabindex', had);
    });
    const seen = new Set();
    let lastPath = null;
    let repeats = 0;
    let viewportChecks = 0;
    let cdp = null;
    for (let i = 0; i < FOCUS_WALK_MAX; i++) {
      if (epochNow() > deadline) {
        ended = 'time_budget';
        break;
      }
      await page.keyboard.press('Tab');
      await this.settleScroll(page);
      const info = await page.evaluate(focusInfo);
      if (!info) {
        ended = 'left_document';
        break;
      }
      if (info.path === lastPath) {
        // Focus moved inside a cross-origin frame (the frame element stays active).
        if (++repeats >= 3) {
          ended = 'opaque_frame';
          break;
        }
        continue;
      }
      repeats = 0;
      lastPath = info.path;
      if (seen.has(info.path)) {
        ended = 'cycle';
        break;
      }
      seen.add(info.path);
      const boxes = [info.box, ...(info.wrap_boxes || [])];
      const x0 = Math.max(0, Math.floor(Math.min(...boxes.map((b) => b.x)) - 4));
      const y0 = Math.max(0, Math.floor(Math.min(...boxes.map((b) => b.y)) - 4));
      const x1 = Math.min(info.vw, Math.ceil(Math.max(...boxes.map((b) => b.x + b.w)) + 4));
      const y1 = Math.min(info.vh, Math.ceil(Math.max(...boxes.map((b) => b.y + b.h)) + 4));
      const stop = { ...info, path: undefined, wrap_boxes: undefined, vw: undefined, vh: undefined, indicator_px: null, clip_px: null,
        indicator_any_px: null };
      if (info.in_viewport && x1 - x0 >= 2 && y1 - y0 >= 2) {
        // ACT oj04fd: focused vs blurred (blur, not Shift+Tab, so the previous stop's
        // indicator is not mixed in); pixels that change between two blurred captures
        // are animation and are masked.
        const clip = { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
        const on = await this.clipFrame(page, clip);
        const blurred = await this.blurFocused(page);
        let off = null;
        let off2 = null;
        if (blurred) {
          off = await this.clipFrame(page, clip);
          await sleep(FOCUS_ANIM_GAP_MS);
          off2 = await this.clipFrame(page, clip);
        }
        stop.indicator_px = off ? indicatorPixels(on, off, off2, FOCUS_DIFF_LEVEL, FOCUS_MASK_LEVEL) : null;
        stop.clip_px = [clip.width, clip.height];
        if (blurred && stop.indicator_px !== null && stop.indicator_px < FOCUS_LOCAL_MIN_PX && viewportChecks < FOCUS_VIEWPORT_MAX
            && (info.obscured_fraction || 0) < 0.999) {
          // Nothing near the element: look for an indicator anywhere in the viewport.
          // Focus is restored by keyboard (Shift+Tab, Tab from the blurred starting point)
          // so :focus-visible styles apply as they did; the comparison is kept only when
          // the same element is focused at the same scroll position.
          viewportChecks += 1;
          if (!cdp) cdp = await page.context().newCDPSession(page);
          const scroll = () => page.evaluate(() => [window.scrollX, window.scrollY]);
          // The focused capture is bracketed by two unfocused ones, so an animation
          // changes the pair and is masked.
          const before = await scroll();
          const allOff = await this.viewportFrame(cdp);
          await page.keyboard.press('Shift+Tab');
          await page.keyboard.press('Tab');
          await this.settleScroll(page);
          const back = await page.evaluate(focusInfo);
          const after = await scroll();
          if (back && back.path === info.path && before[0] === after[0] && before[1] === after[1]
              && Math.abs(back.box.x - info.box.x) < 1 && Math.abs(back.box.y - info.box.y) < 1) {
            const allOn = await this.viewportFrame(cdp);
            const reblurred = await this.blurFocused(page);
            const allOff2 = reblurred ? await this.viewportFrame(cdp) : null;
            if (reblurred) await this.refocus(page);
            stop.indicator_any_px = allOff2 ? indicatorPixels(allOn, allOff, allOff2, FOCUS_DIFF_LEVEL, FOCUS_MASK_LEVEL) : null;
            stop.indicator_any_scale = Math.round(Math.min(1, FOCUS_VIEWPORT_WIDTH / info.vw) * 1000) / 1000;
          } else if (!back || back.path !== info.path) {
            await this.refocus(page);
          }
        } else if (blurred) {
          await this.refocus(page);
        }
        await page.evaluate(() => {
          window.__ergoFocusEl = null;
        });
      }
      if (phase === 'end' && info.obscured_user_opened === true && (info.obscured_fraction || 0) >= 0.999) {
        // WCAG 2.4.11 note: content the user opened may cover the focused element if the
        // user can reveal it without moving focus (for example with Escape).
        await page.keyboard.press('Escape');
        await this.settleScroll(page);
        const again = await page.evaluate(focusInfo);
        stop.escape_reveals = !!again && again.path === info.path && (again.obscured_fraction || 0) < 0.999;
      }
      stops.push(stop);
    }
    if (cdp) await cdp.detach().catch(() => {});
    this.focusWalks.push({ phase, snapshot_id: snapshotId, url: page.url(), ended, stops });
  }

  /**
   * Before a click on a control (mouse and keyboard devices): its focus indicator as a
   * keyboard user sees it on this screen, which the walks (initial and end screens)
   * do not reach. The control and its small wrappers, and the viewport, are captured
   * twice unfocused; an F24 key press gives keyboard modality (:focus-visible and
   * modality scripts; Tab-only scripts are not triggered), the
   * control is focused and captured, focus goes back to the element that had it (so a
   * menu trigger keeps its menu open; the click then moves focus as it would), and a
   * third unfocused capture follows. A pixel counts when the focused frame differs from
   * all three unfocused frames and they agree; the previous control's box is masked
   * (its own focus style goes away). A focused text field is blurred first and the
   * control measured again. Skipped for text-entry targets, controls inside roving
   * focus popups, game screens and timed targets. At most STEP_PROBE_MAX per run.
   */
  async focusProbe(resolved, step) {
    if ((this.stepProbes || 0) >= STEP_PROBE_MAX) return;
    const page = this.page;
    let handle = resolved.handle || null;
    let own = false;
    if (!handle) {
      handle = await page.evaluateHandle((pt) => {
        const v = window.visualViewport;
        const one = !!v && Math.abs(v.scale - 1) < 0.01;
        return document.elementFromPoint(pt.x + (one ? v.offsetLeft : 0), pt.y + (one ? v.offsetTop : 0));
      }, resolved.point).catch(() => null);
      own = true;
    }
    let cdp = null;
    try {
      let target = handle ? await handle.evaluate(probeTarget).catch(() => null) : null;
      if (!target || target.skip) {
        step.focus_probe = { skipped: target ? target.skip : 'no_element' };
        return;
      }
      let afterField = false;
      if (target.field) {
        // Take focus from the text field first (its blur runs at the click anyway; a
        // validation message may move the layout), let the page settle, measure again.
        await page.evaluate(() => {
          const p = window.__ergoProbePrev;
          window.__ergoProbePrev = null;
          if (p) p.blur();
        }).catch(() => {});
        await sleep(FOCUS_SETTLE_MS * 2);
        target = await handle.evaluate(probeTarget).catch(() => null);
        if (!target || target.skip || target.field) {
          // after_field: the page may have changed; the click's target is checked again.
          step.focus_probe = { skipped: target ? (target.skip || 'field_focused') : 'no_element', after_field: true };
          return;
        }
        afterField = true;
      }
      const boxes = target.boxes;
      const x0 = Math.max(0, Math.floor(Math.min(...boxes.map((b) => b.x)) - 4));
      const y0 = Math.max(0, Math.floor(Math.min(...boxes.map((b) => b.y)) - 4));
      const x1 = Math.min(target.vw, Math.ceil(Math.max(...boxes.map((b) => b.x + b.w)) + 4));
      const y1 = Math.min(target.vh, Math.ceil(Math.max(...boxes.map((b) => b.y + b.h)) + 4));
      if (x1 - x0 < 2 || y1 - y0 < 2) {
        step.focus_probe = { skipped: 'outside_viewport' };
        return;
      }
      this.stepProbes = (this.stepProbes || 0) + 1;
      const clip = { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
      cdp = await page.context().newCDPSession(page);
      // Page animations run on (a fast-forward would end timers driven by CSS
      // animations on the live page); the unfocused frames mask them.
      const grab = () => this.clipFrame(page, clip, 'allow');
      const off = await grab();
      const allOff = await this.viewportFrame(cdp);
      await sleep(FOCUS_ANIM_GAP_MS);
      const off2 = await grab();
      const allOff2 = await this.viewportFrame(cdp);
      // Modality scripts mark the root (data-whatinput, a "user-is-tabbing" class): its
      // attributes are put back after the probe, so the click does not flip them back
      // and pass for a response.
      const rootAttrs = await page.evaluate(() => [document.documentElement, document.body].map((n) => (n
        ? Object.fromEntries([...n.attributes].map((a) => [a.name, a.value])) : null))).catch(() => null);
      // Keyboard modality: F24 (CDP; no browser action, on no physical keyboard). Shift
      // gives Chromium's :focus-visible but modality scripts ignore modifier keys
      // (what-input's ignore list, Angular CDK), so pages that hide rings in "mouse"
      // mode would read as having none.
      for (const type of ['rawKeyDown', 'keyUp']) {
        await cdp.send('Input.dispatchKeyEvent', { type, key: 'F24', code: 'F24', windowsVirtualKeyCode: 135, nativeVirtualKeyCode: 135 });
      }
      const got = await page.evaluate(() => {
        const el = window.__ergoProbeEl;
        if (!el || !el.isConnected) return null;
        el.focus({ preventScroll: true });
        let a = document.activeElement;
        while (a && a.shadowRoot && a.shadowRoot.activeElement) a = a.shadowRoot.activeElement;
        return { focused: a === el, visible: el.matches(':focus-visible'), scroll: [window.scrollX, window.scrollY] };
      });
      const restore = () => page.evaluate((attrs) => {
        // Give focus back to what had it where losing it would change the page (see
        // probeTarget); else leave none.
        const el = window.__ergoProbeEl;
        const p = window.__ergoProbePrev;
        const keep = window.__ergoProbeKeep;
        window.__ergoProbeEl = null;
        window.__ergoProbePrev = null;
        window.__ergoProbeKeep = null;
        if (keep && p && p.isConnected && p !== el) p.focus({ preventScroll: true });
        else if (el) el.blur();
        [document.documentElement, document.body].forEach((n, i) => {
          const was = attrs && attrs[i];
          if (!n || !was) return;
          for (const a of [...n.attributes]) if (!(a.name in was)) n.removeAttribute(a.name);
          for (const [k, v] of Object.entries(was)) if (n.getAttribute(k) !== v) n.setAttribute(k, v);
        });
      }, rootAttrs).catch(() => {});
      if (!got || !got.focused) {
        await restore();
        step.focus_probe = { skipped: 'focus_refused' };
        return;
      }
      await sleep(FOCUS_SETTLE_MS);
      const info = await page.evaluate(focusInfo);
      const on = await grab();
      const allOn = await this.viewportFrame(cdp);
      await restore();
      await sleep(FOCUS_ANIM_GAP_MS);
      // An unfocused frame after the focused one too: anything that changed during the
      // probe (a ticking clock) differs between the before and after frames and is masked.
      const off3 = await grab();
      const allOff3 = await this.viewportFrame(cdp);
      const moved = got.scroll[0] !== target.scroll[0] || got.scroll[1] !== target.scroll[1];
      if (moved) {
        // A focus handler scrolled the page: put it back so the click lands where the
        // step resolved it; the captures no longer line up and are not used.
        await page.evaluate((xy) => window.scrollTo(xy[0], xy[1]), target.scroll).catch(() => {});
      }
      // The previously focused control's own focus style: not the target's indicator.
      // Rectangles in CSS px, 8 px beyond the box; a large element only along its edges.
      const rects = [];
      for (const b of target.prevBoxes || []) {
        const [bx0, by0, bx1, by1] = [b.x - 8, b.y - 8, b.x + b.w + 8, b.y + b.h + 8];
        if (!b.band) rects.push([bx0, by0, bx1, by1]);
        else rects.push([bx0, by0, bx1, b.y + 8], [bx0, b.y + b.h - 8, bx1, by1], [bx0, by0, b.x + 8, by1], [b.x + b.w - 8, by0, bx1, by1]);
      }
      const sx = allOn.width / this.vw;
      const sy = allOn.height / this.vh;
      const prevLocal = rects.map(([a, b, c, d]) => ({ x0: Math.floor(a - clip.x), y0: Math.floor(b - clip.y), x1: Math.ceil(c - clip.x), y1: Math.ceil(d - clip.y) }));
      const prevAll = rects.map(([a, b, c, d]) => ({ x0: Math.floor(a * sx), y0: Math.floor(b * sy), x1: Math.ceil(c * sx), y1: Math.ceil(d * sy) }));
      // Share of the target's own box (+4 px, where its ring is drawn) that is masked.
      const own = target.boxes[0];
      const near = { roi: { x0: Math.floor(own.x - 4 - clip.x), y0: Math.floor(own.y - 4 - clip.y), x1: Math.ceil(own.x + own.w + 4 - clip.x), y1: Math.ceil(own.y + own.h + 4 - clip.y) } };
      let px = moved ? null : indicatorPixelsMulti(on, [off, off2, off3], FOCUS_DIFF_LEVEL, FOCUS_MASK_LEVEL, prevLocal, near);
      const anyPx = moved ? null : indicatorPixelsMulti(allOn, [allOff, allOff2, allOff3], FOCUS_DIFF_LEVEL, FOCUS_MASK_LEVEL, prevAll);
      // Most of the area masked (the previous control's box, or content that kept
      // moving: a pulsing button): a missing indicator cannot be told from a hidden one.
      let inconclusive = null;
      if (typeof px === 'number' && px < 4 && near.total && (near.excluded + near.animated) > 0.5 * near.total) {
        inconclusive = near.animated > near.excluded ? 'animated' : 'masked';
        px = null;
      }
      step.focus_probe = {
        snapshot_id: step.before, selector: info ? info.selector : null, dom_id: info ? info.dom_id : null, tag: info ? info.tag : null,
        role: info ? info.role : null, name: info ? info.name : null, box: info ? info.box : null, in_viewport: info ? info.in_viewport : null,
        focus_visible: got.visible, moved, after_field: afterField, restored: target.keepPrev ? 'previous' : 'blur',
        clip_px: [clip.width, clip.height], masked_prev: prevLocal.length > 0,
        indicator_px: px, indicator_any_px: inconclusive ? null : anyPx, ...(inconclusive ? { inconclusive } : {}),
        indicator_any_scale: Math.round(Math.min(1, FOCUS_VIEWPORT_WIDTH / target.vw) * 1000) / 1000,
      };
    } catch (err) {
      step.focus_probe = { skipped: 'error', error: firstLine(err.message) };
    } finally {
      if (cdp) await cdp.detach().catch(() => {});
      if (own && handle) await handle.dispose().catch(() => {});
    }
  }

  /** Wait until the page stops scrolling after a focus move (max ~600 ms). */
  async settleScroll(page) {
    let prev = null;
    for (let i = 0; i < 12; i++) {
      await sleep(i === 0 ? FOCUS_SETTLE_MS : 50);
      const pos = await page.evaluate(() => [window.scrollX, window.scrollY]).catch(() => null);
      if (pos && prev && pos[0] === prev[0] && pos[1] === prev[1]) return;
      prev = pos;
    }
  }

  /** Run a walk with a hard deadline; a hung page cannot stop run.json from being written. */
  async boundedWalk(fn, phase) {
    let timer = null;
    try {
      await Promise.race([fn(), new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error('deadline')), FOCUS_WALK_BUDGET_MS + 5000);
      })]);
    } catch (err) {
      this.warnings.push(`focus walk (${phase}) stopped: ${firstLine(err.message)}`);
    } finally {
      clearTimeout(timer);
    }
  }

  async calibrate() {
    let best = null;
    for (let i = 0; i < 5; i++) {
      const t0 = epochNow();
      const pageEpoch = await this.page.evaluate(() => performance.timeOrigin + performance.now());
      const t1 = epochNow();
      if (!best || t1 - t0 < best.rtt) best = { rtt: t1 - t0, offset: pageEpoch - (t0 + t1) / 2 };
    }
    this.clockOffset = best.offset;
    this.clockRtt = best.rtt;
  }

  pushConsole(type, text, location) {
    const msg = String(text ?? '');
    if (this.blockedCount > 0 && msg.includes('ERR_BLOCKED_BY_CLIENT')) {
      this.blockedConsole++;
      return; // caused by the driver's network policy, not by the page
    }
    const entry = {
      t_ms: this.rel(epochNow()),
      type,
      text: truncate(msg, 1000),
      url: location && location.url ? stripQuery(location.url) : null,
    };
    if (this.consoleAll.length < MAX_CONSOLE) this.consoleAll.push(entry);
    if (this.consolePending.length < 100) this.consolePending.push(`[${type}] ${truncate(msg, 500)}`);
  }

  isAllowed(url) {
    let u;
    try {
      u = new URL(url);
    } catch {
      return false;
    }
    if (['data:', 'blob:', 'about:'].includes(u.protocol)) return true;
    if (u.protocol === 'file:') {
      const s = this.scenario.origin;
      if (s.protocol !== 'file:') return false;
      const dir = s.pathname.slice(0, s.pathname.lastIndexOf('/') + 1);
      return u.pathname.startsWith(dir);
    }
    return this.allowedOrigins.has(u.origin);
  }

  onRoute(route) {
    const req = route.request();
    const url = req.url();
    if (this.isAllowed(url)) return route.continue().catch(() => {});
    this.blockedCount++;
    if (this.blocked.length < 50) this.blocked.push({ t_ms: this.rel(epochNow()), url: stripQuery(url), resource_type: req.resourceType() });
    return route.abort('blockedbyclient').catch(() => {});
  }

  onWebSocket(ws) {
    const url = ws.url();
    const asHttp = url.replace(/^ws/, 'http');
    if (this.isAllowed(asHttp)) {
      ws.connectToServer();
      return;
    }
    this.blockedCount++;
    if (this.blocked.length < 50) this.blocked.push({ t_ms: this.rel(epochNow()), url: stripQuery(url), resource_type: 'websocket' });
    ws.close({ code: 1008, reason: 'blocked by ergoqa network policy' }).catch(() => {});
  }

  // ------------------------------------------------------------------ timing windows

  onTimingWindow(source, payload) {
    try {
      if (!source || source.frame !== this.page.mainFrame()) return;
    } catch {
      return;
    }
    if (!payload || typeof payload !== 'object' || typeof payload.id !== 'string') return;
    const w = this.tw.get(payload.id);
    if (!w || w.fallback) return;
    if (payload.v === null) {
      this.startFallbackPoll(w);
      return;
    }
    if (typeof payload.v !== 'boolean' || typeof payload.t !== 'number' || !Number.isFinite(payload.t)) return;
    const text = typeof payload.text === 'string' ? payload.text.slice(0, 500) : null;
    const b = payload.box;
    if (payload.v && b && [b.x, b.y, b.w, b.h].every((n) => typeof n === 'number' && Number.isFinite(n))) {
      const area = b.w * b.h;
      if (!w.appearBox || area > w.appearBox.w * w.appearBox.h) {
        w.appearBox = { x: Math.round(b.x * 100) / 100, y: Math.round(b.y * 100) / 100, w: Math.round(b.w * 100) / 100, h: Math.round(b.h * 100) / 100 };
        w.appearBg = typeof payload.bg === 'string' ? payload.bg.slice(0, 64) : null;
      }
    }
    if (payload.v && payload.off === true && !w.cur) w.offscreenAppearances = (w.offscreenAppearances || 0) + 1;
    this.applyTransition(w, payload.v, payload.t - this.clockOffset, text);
  }

  applyTransition(w, visible, t, text) {
    if (visible && !w.cur) {
      w.cur = { since: t };
      w.appearances++;
      if (w.starts.length < 2000) w.starts.push(t);
      if (w.firstVisible === null) w.firstVisible = t;
      if (text && !w.text) w.text = text;
    } else if (!visible && w.cur) {
      w.intervals.push(Math.max(0, t - w.cur.since));
      w.cur = null;
    }
  }

  startFallbackPoll(w) {
    // Not a CSS selector (e.g. "text=..."): poll with Playwright every 16 ms.
    w.fallback = true;
    w.method = 'playwright-poll';
    let busy = false;
    const timer = setInterval(async () => {
      if (busy || this.finished || this.crashed) return;
      busy = true;
      try {
        const t0 = epochNow();
        const n = await this.page.locator(w.def.selector).filter({ visible: true }).count();
        const t1 = epochNow();
        let text = null;
        if (n > 0 && !w.cur && !w.text) {
          text = await this.page.locator(w.def.selector).filter({ visible: true }).first().innerText({ timeout: 200 }).catch(() => null);
        }
        this.applyTransition(w, n > 0, (t0 + t1) / 2, text ? text.replace(/\s+/g, ' ').trim() : null);
      } catch (err) {
        w.error = firstLine(err.message);
      } finally {
        busy = false;
      }
    }, TW_POLL_MS);
    this.twPollers.push(timer);
  }

  timingWindowsOut(endEpoch) {
    const out = [];
    for (const w of this.tw.values()) {
      const closed = w.intervals.map(round1);
      const open = w.cur ? round1(endEpoch - w.cur.since) : null;
      out.push({
        id: w.def.id,
        selector: w.def.selector,
        measure: w.def.measure,
        ...(w.def.kind ? { kind: w.def.kind } : {}),
        ...(w.def.text || w.text ? { text: w.def.text || w.text } : {}),
        // Shortest completed visible interval (the tightest window a user got);
        // null when the element never both appeared and disappeared.
        visible_ms: closed.length ? Math.min(...closed) : null,
        intervals_ms: closed,
        min_visible_ms: closed.length ? Math.min(...closed) : null,
        max_visible_ms: closed.length ? Math.max(...closed) : null,
        appearances: w.appearances,
        // Appearances whose whole box was outside the viewport (could not be read there).
        offscreen_appearances: w.offscreenAppearances || 0,
        // Appearance start times relative to run start (flash-rate estimation).
        starts_ms: w.starts.map((t) => round1(this.rel(t))),
        ...(w.appearBox ? { appear_box: w.appearBox, appear_bg: w.appearBg } : {}),
        open_interval_ms: open,
        first_visible_t_ms: w.firstVisible !== null ? this.rel(w.firstVisible) : null,
        poll_interval_ms: TW_POLL_MS,
        method: w.method,
        error: w.error,
      });
    }
    return out;
  }

  // ------------------------------------------------------------------ page state helpers

  async firstMutation(t0, t1) {
    try {
      const v = await this.page.evaluate(({ key, a, b }) => {
        const s = window[Symbol.for(key)];
        return s && s.firstMutationAfter ? s.firstMutationAfter(a, b) : null;
      }, { key: STATE_KEY, a: t0 + this.clockOffset, b: t1 + this.clockOffset });
      return v === null ? null : v - this.clockOffset;
    } catch {
      return null;
    }
  }

  async countMutations(t0, t1) {
    try {
      return await this.page.evaluate(({ key, a, b }) => {
        const s = window[Symbol.for(key)];
        return s && s.countMutations ? s.countMutations(a, b) : 0;
      }, { key: STATE_KEY, a: t0 + this.clockOffset, b: t1 + this.clockOffset });
    } catch {
      return null;
    }
  }

  async scrollPos() {
    try {
      return await this.page.evaluate(() => ({ x: window.scrollX, y: window.scrollY }));
    } catch {
      return null;
    }
  }

  async captureFrame() {
    return this.visualFrame(this.cdp, FRAME_WIDTH);
  }

  visualThreshold(frame) {
    const n = frame.width * frame.height;
    return Math.max(3 / n, 0.0004);
  }

  /** Capture downscaled frames after `dispatch` for flash sampling and/or visual feedback. */
  async probeFrames({ dispatch, stepIndex, flashMs, visual, fb }) {
    let prev = null;
    for (;;) {
      if (!this.page || this.crashed || this.page.isClosed()) return;
      const now = epochNow();
      const wantFlash = flashMs > 0 && now < dispatch + flashMs;
      const wantVisual = !!visual && fb.visual == null && !fb.done && now < visual.deadline;
      if (!wantFlash && !wantVisual) return;
      const t0 = epochNow();
      let frame;
      try {
        frame = await this.captureFrame();
      } catch {
        await sleep(16);
        continue;
      }
      const t1 = epochNow();
      const tm = (t0 + t1) / 2;
      if (wantVisual && visual.pre) {
        // The frame reflects the page when the capture was requested (t0): the
        // change happened before t0 and after the previous capture started.
        const d = visualDiffFraction(frame, visual.pre, VISUAL_LEVEL, visual.mask, visual.moving);
        if (d !== null && d >= this.visualThreshold(frame)) fb.visual = t0;
      }
      if (wantFlash && this.flashSamples.length < MAX_FLASH_SAMPLES && this.flashBytes < MAX_FLASH_BYTES) {
        const st = frameStats(frame, prev);
        const sample = {
          t_ms: this.rel(tm),
          mean_luminance: r4(st.mean_luminance),
          changed_fraction: prev ? r4(st.changed_fraction) : 0,
          flash_fraction: prev ? r4(st.flash_fraction) : 0,
          red_fraction: r4(st.red_fraction),
          frame_index: this.frameIndex++,
          step_index: stepIndex,
          capture_ms: round1(t1 - t0),
        };
        this.addBlockStats(sample, frame);
        this.flashSamples.push(sample);
        this.flashBytes += JSON.stringify(sample).length + 160; // + pretty-print indentation in run.json
        prev = frame;
        this.flashPrev = frame;
      } else if (wantFlash && !this.flashTruncated) {
        this.flashTruncated = { t_ms: this.rel(tm), step_index: stepIndex, samples: this.flashSamples.length };
      }
      if (wantFlash) await sleep(Math.random() * FLASH_JITTER_MS);
    }
  }

  /** Block grid statistics of a flash frame (png.mjs blockStats), base64 encoded into the sample. */
  addBlockStats(sample, frame) {
    if (!this.flashGrid) this.flashGrid = makeBlockGrid(frame.width, frame.height, this.vw, this.vh);
    // Page scroll measured between the frames: content moved by -delta (frame px).
    const prev = this.flashPrev;
    let known = null;
    if (prev && prev.page && frame.page && frame.cssPerPx) {
      const dx = frame.page[0] - prev.page[0];
      const dy = frame.page[1] - prev.page[1];
      if (Math.abs(dx) >= 0.5 || Math.abs(dy) >= 0.5) {
        sample.page_scroll_css = [round1(dx), round1(dy)];
        if (this.scrollOscillates(sample.t_ms, dx, dy)) {
          // Scrolling back and forth is not smooth motion in one direction (ITC/Ofcom,
          // ISO 9241-391): count what it does to each region, without motion matching.
          known = false;
          sample.page_scroll_oscillating = true;
        } else {
          known = [Math.round(-dx / frame.cssPerPx[0]), Math.round(-dy / frame.cssPerPx[1])];
        }
      }
    }
    const bs = blockStats(frame, this.flashGrid, prev, known);
    if (!bs) return; // frame size changed: no grid for this sample
    sample.block_lum = Buffer.from(bs.lum).toString('base64');
    sample.block_red = Buffer.from(bs.red).toString('base64');
    if (bs.moved) {
      sample.block_moved = Buffer.from(bs.moved).toString('base64');
      sample.motion_css = [round1((bs.shift[0] * this.vw) / frame.width), round1((bs.shift[1] * this.vh) / frame.height)];
    }
  }

  /**
   * Page scroll between flash frames that reverses direction more than
   * SCROLL_REVERSALS_PER_S times within one second (a shaking or bouncing page).
   */
  scrollOscillates(t, dx, dy) {
    // A reversal counts after at least SCROLL_REVERSAL_MIN_CSS of travel the other way,
    // so sub-pixel corrections (virtual lists, sticky headers settling) are not shaking.
    const h = this.scrollSigns || (this.scrollSigns = { x: 0, y: 0, runX: 0, runY: 0, times: [] });
    for (const [axis, d] of [['x', dx], ['y', dy]]) {
      if (Math.abs(d) < 0.5) continue;
      const sign = Math.sign(d);
      const run = axis === 'x' ? 'runX' : 'runY';
      if (h[axis] && sign !== h[axis]) {
        if (h[run] >= SCROLL_REVERSAL_MIN_CSS) h.times.push(t);
        h[run] = 0;
      }
      h[axis] = sign;
      h[run] += Math.abs(d);
    }
    while (h.times.length && h.times[0] < t - 1000) h.times.shift();
    return h.times.length > SCROLL_REVERSALS_PER_S;
  }

  /** Sampling coverage: bursts are runs of samples of one step (one sampling window). */
  flashCoverage() {
    const s = this.flashSamples;
    const gaps = [];
    let sampled = 0;
    let bursts = s.length ? 1 : 0;
    let first = s.length ? s[0].t_ms : 0;
    for (let i = 1; i <= s.length; i++) {
      if (i === s.length || s[i].step_index !== s[i - 1].step_index) {
        sampled += s[i - 1].t_ms - first;
        if (i < s.length) {
          bursts++;
          first = s[i].t_ms;
        }
      } else {
        gaps.push(s[i].t_ms - s[i - 1].t_ms);
      }
    }
    return {
      bursts,
      sampled_ms: round1(sampled),
      mean_fps: sampled > 0 ? round1((gaps.length * 1000) / sampled) : null,
      max_gap_ms: gaps.length ? round1(Math.max(...gaps)) : null,
      mean_interval_ms: gaps.length ? round1(gaps.reduce((a, b) => a + b, 0) / gaps.length) : null,
    };
  }

  flashGridOut() {
    const g = this.flashGrid;
    if (!g) return null;
    return {
      cols: g.cols,
      rows: g.rows,
      block_css: [Math.round(g.blockCss[0] * 100) / 100, Math.round(g.blockCss[1] * 100) / 100],
      viewport_css: [g.viewportW, g.viewportH],
      frame_px: [g.frameW, g.frameH],
      min_block_css: [BLOCK_MIN_W_CSS, BLOCK_MIN_H_CSS],
      order: 'row-major: block index = row * cols + col, from the viewport top-left',
      block_lum: 'base64, one byte per block: round(255 * mean WCAG relative luminance)',
      block_red: `base64, one byte per block: round(255 * share of saturated-red pixels: linear R/(R+G+B) >= ${RED_RATIO} and (R-G-B)*320 > ${Math.round(RED_EXCESS * 320)})`,
      block_moved: `base64 bitmask, bit (b & 7) of byte (b >> 3): block b changed since the previous flash frame only because the content moved by motion_css (mean luminance and red share match the shifted previous frame within ${MOTION_MATCH}, or the content entered the viewport); absent when no content shift was detected`,
    };
  }

  // ------------------------------------------------------------------ snapshots

  async inspect() {
    if (this.crashed || !this.page || this.page.isClosed()) throw new DriverFailure('cannot inspect a closed or crashed page');
    const state = await this.page.evaluate(inspectPage, { redactSelectors: [...this.redactSelectors] });
    const inspection = path.join(this.runDir, `I-${this.runId}-${String(this.inspectSeq++).padStart(3, '0')}.json`);
    const record = { run_id: this.runId, step_index: this.steps.length, last_snapshot_id: this.lastSnapshotId, observed_at: isoNow(), ...state };
    writeJsonAtomic(inspection, this.redactRecord(record), 0o600);
    return { result: 'ok', inspection, ...this.redactRecord(record) };
  }

  async targetGroups() {
    const groups = [];
    const handlesToDispose = [];
    const hotspotRoles = {};
    for (const [role, sels] of Object.entries(this.scenario.targets)) {
      const handles = [];
      for (const sel of sels) {
        if (sel.startsWith('hotspot:')) {
          const id = sel.slice('hotspot:'.length);
          (hotspotRoles[id] ||= []).push(role);
          continue;
        }
        try {
          const hs = await this.page.locator(sel).elementHandles();
          handles.push(...hs.slice(0, 50));
          handlesToDispose.push(...hs);
        } catch (err) {
          this.warnOnce(`target:${sel}`, `target selector ${JSON.stringify(sel)} (${role}) could not be evaluated: ${firstLine(err.message)}`);
        }
      }
      groups.push({ role, handles });
    }
    return { groups, hotspotRoles, handlesToDispose };
  }

  async extract() {
    const { groups, hotspotRoles, handlesToDispose } = await this.targetGroups();
    try {
      const snapshot = await this.page.evaluate(extractSnapshot, {
        key: STATE_KEY,
        cap: ELEMENT_CAP,
        groups,
        hotspots: this.scenario.hotspots,
        hotspotRoles,
        knownRoles: KNOWN_ROLES,
        redactSelectors: [...this.redactSelectors],
        privateValues: [...this.privateValues],
      });
      if (this.redactSelectors.size) {
        const ids = await this.page.evaluate(({ selectors, key }) => {
          const ids = new Set();
          const state = window[Symbol.for(key)];
          const descendants = (el) => {
            if (state?.ids?.get(el)) ids.add(state.ids.get(el));
            for (const child of el.children || []) descendants(child);
            if (el.shadowRoot) for (const child of el.shadowRoot.children) descendants(child);
          };
          for (const selector of selectors) {
            let elements;
            try { elements = document.querySelectorAll(selector); } catch { continue; }
            for (const el of elements) {
              descendants(el);
              for (let parent = el.parentElement; parent; parent = parent.parentElement) ids.add(state?.ids?.get(parent));
            }
          }
          return [...ids].filter(Boolean);
        }, { selectors: [...this.redactSelectors], key: STATE_KEY });
        for (const element of snapshot.elements) {
          if (ids.includes(element.id)) {
            element.text = '[redacted]';
            element.name = '[redacted]';
          }
        }
      }
      return snapshot;
    } finally {
      await Promise.all(handlesToDispose.map((h) => h.dispose().catch(() => {})));
    }
  }

  async snapshot(stepIndex, notes, taskCheckpoint, taskStepResult = 'ok') {
    if (this.needCalibrate) {
      this.needCalibrate = false;
      await this.calibrate().catch(() => {});
    }
    const seq = this.snapSeq++;
    const id = `S-${this.runId}-${String(seq).padStart(3, '0')}`;
    let png;
    let ex;
    let taskSamples = new Map();
    for (let attempt = 0; ; attempt++) {
      try {
        if (taskCheckpoint !== undefined) taskSamples = await this.sampleTaskChecks(taskCheckpoint, taskStepResult);
        const selectors = this.redactSelectors.size ? await this.page.evaluate((selectors) => selectors.filter((selector) => {
          try { document.querySelectorAll(selector); return true; } catch { return false; }
        }), [...this.redactSelectors]) : [];
        png = await this.page.screenshot({ type: 'png', scale: 'device', animations: 'allow', caret: 'initial', timeout: 15000,
          mask: selectors.map((selector) => this.page.locator(`css=${selector}`)) });
        ex = await this.extract();
        break;
      } catch (err) {
        for (const handle of taskSamples.values()) await handle?.dispose().catch(() => {});
        taskSamples.clear();
        if (attempt >= 2 || this.crashed || this.page.isClosed()) {
          throw new DriverFailure(this.privateValues.size ? `snapshot ${id} failed during redacted capture` : `snapshot ${id} failed: ${firstLine(err.message)}`);
        }
        await this.page.waitForLoadState('load', { timeout: 10000 }).catch(() => {});
      }
    }
    const capturedAt = isoNow();
    const allNotes = [...notes];
    if (ex.truncated) allNotes.push(`elements capped at ${ELEMENT_CAP} of ${ex.candidates} candidates (roles and interactive elements first)`);
    if (ex.pageHotspotError) allNotes.push(ex.pageHotspotError);
    for (const r of ex.unknownRoles) this.warnOnce(`role:${r}`, `unknown role ${JSON.stringify(r)} (data-ergo-role or hotspot) ignored; allowed: ${KNOWN_ROLES.join(', ')}`);
    const { width, height } = pngSize(png);
    const ew = Math.round(this.vw * this.dev.base.dpr);
    const eh = Math.round(this.vh * this.dev.base.dpr);
    if (Math.abs(width - ew) > 1 || Math.abs(height - eh) > 1) allNotes.push(`screenshot is ${width}x${height}, expected about ${ew}x${eh}`);
    if (ex.viewport.w !== this.vw || ex.viewport.h !== this.vh) {
      allNotes.push(`page reports viewport ${ex.viewport.w}x${ex.viewport.h} (layout zoom or meta viewport); boxes are in page CSS px`);
    }
    this.lastActive = ex.active;
    this.lastLayers = ex.layers || [];
    let title = null;
    try {
      title = await this.page.title();
    } catch { /* navigating */ }
    // CSS-scale copy for fast analysis in Python (derived from the same capture).
    let cssCopy = null;
    try {
      cssCopy = cssScaleCopy(png, this.dev.base.dpr);
    } catch (err) {
      allNotes.push(`css-scale copy failed: ${firstLine(err.message)}`);
    }
    const snap = {
      schema_version: 'ergo-snapshot.v1',
      snapshot_id: id,
      run_id: this.runId,
      step_index: stepIndex,
      captured_at: capturedAt,
      surface: { kind: this.scenario.surface_kind === 'game' ? 'game' : 'web', url: this.page.url(), title, app_id: null, scroll: ex.scroll, visual: ex.visual || null,
        ...(this.opts.buildId ? { build_id: this.opts.buildId, build_id_basis: 'operator_supplied', build_id_source: this.opts.buildIdSource } : {}) },
      device: this.dev.snapshotDevice,
      screenshot: {
        path: `${id}.png`, sha256: sha256(png), width_px: width, height_px: height,
        ...(cssCopy ? { css: { path: `${id}.css.png`, sha256: sha256(cssCopy.png), width_px: cssCopy.width, height_px: cssCopy.height, factor: cssCopy.factor } } : {}),
      },
      elements: ex.elements,
      focus_point: this.focusPoint,
      focus: ex.focus,
      layers: ex.layers,
      console_errors: this.consolePending.splice(0),
      notes: allNotes,
    };
    const pngPath = path.join(this.runDir, `${id}.png`);
    const jsonPath = path.join(this.runDir, `${id}.json`);
    writeFileAtomic(pngPath, png);
    if (cssCopy) writeFileAtomic(path.join(this.runDir, `${id}.css.png`), cssCopy.png);
    const safeSnap = this.redactRecord(snap);
    writeJsonAtomic(jsonPath, safeSnap);
    this.snapshots.push({ snapshot_id: id, step_index: stepIndex, path: `${id}.json`, png: `${id}.png` });
    this.lastSnapshotId = id;
    if (taskCheckpoint !== undefined) await this.evaluateTaskChecks(taskCheckpoint, { id, snap: safeSnap }, taskStepResult, taskSamples);
    await this.keepForReflow(id);
    // Keep recent element lists to anchor persona notes (note -> element -> selector).
    this.snapElements.set(id, { elements: safeSnap.elements, url: safeSnap.surface.url });
    if (this.snapElements.size > 64) this.snapElements.delete(this.snapElements.keys().next().value);
    return { id, jsonPath, pngPath, snap: safeSnap };
  }

  // ------------------------------------------------------------------ targets

  inViewport(p) {
    return p.x >= 0 && p.y >= 0 && p.x < this.vw && p.y < this.vh;
  }

  clampPoint(p) {
    return { x: Math.min(this.vw - 1, Math.max(0, p.x)), y: Math.min(this.vh - 1, Math.max(0, p.y)) };
  }

  async resolveTarget(target, offset, timeoutMs) {
    const rp = (p) => ({ x: Math.round(p.x * 100) / 100, y: Math.round(p.y * 100) / 100 });
    if (typeof target === 'object') {
      const hit = await this.page.evaluate(idAtPoint, { key: STATE_KEY, x: target.x, y: target.y }).catch(() => ({ id: null }));
      return { kind: 'point', point: rp(target), elementId: hit.id, handle: null, waited: false };
    }
    if (target.startsWith('hotspot:')) {
      const id = target.slice('hotspot:'.length);
      const spot = await this.page.evaluate(({ id: hid, declared }) => {
        try {
          const api = window.__ergoqa__;
          if (api && typeof api.hotspots === 'function') {
            const list = api.hotspots();
            if (Array.isArray(list)) {
              const h = list.find((x) => x && x.id === hid);
              if (h && h.box && [h.box.x, h.box.y, h.box.w, h.box.h].every((n) => typeof n === 'number' && Number.isFinite(n))) {
                return { box: { x: h.box.x, y: h.box.y, w: h.box.w, h: h.box.h }, origin: 'page' };
              }
            }
          }
        } catch (e) { /* fall back to the scenario declaration */ }
        const d = declared.find((x) => x.id === hid);
        return d ? { box: d.box, origin: 'scenario' } : null;
      }, { id, declared: this.scenario.hotspots }).catch(() => null);
      if (!spot) return { kind: 'missing', error: `hotspot ${JSON.stringify(id)} is declared neither by the scenario nor by window.__ergoqa__.hotspots()` };
      const b = spot.box;
      const point = offset ? { x: b.x + offset.x, y: b.y + offset.y } : { x: b.x + b.w / 2, y: b.y + b.h / 2 };
      return {
        kind: 'hotspot', point: rp(point), elementId: `hs-${id.replace(/[^A-Za-z0-9._-]/g, '_')}`, handle: null, box: b, origin: spot.origin, waited: false,
      };
    }
    const deadline = epochNow() + timeoutMs;
    let waited = false;
    for (;;) {
      let handle = null;
      let any = 0;
      try {
        const loc = this.page.locator(target);
        const vis = loc.filter({ visible: true });
        if ((await vis.count()) > 0) handle = await vis.first().elementHandle({ timeout: 1000 });
        else any = await loc.count();
      } catch (err) {
        const msg = firstLine(err.message);
        if (/selector|parse|Unexpected token|Unknown engine/i.test(msg)) return { kind: 'missing', error: `invalid selector ${JSON.stringify(target)}: ${msg}` };
      }
      if (handle) {
        const box = await handle.boundingBox().catch(() => null);
        if (box && box.width > 0 && box.height > 0) {
          const point = offset ? { x: box.x + offset.x, y: box.y + offset.y } : { x: box.x + box.width / 2, y: box.y + box.height / 2 };
          const info = await handle.evaluate(idForElement, STATE_KEY).catch(() => ({ id: null, exact: false, interactive: false }));
          return {
            kind: 'selector', point: rp(point), elementId: info.id, exact: info.exact, interactive: info.interactive, handle, box, waited,
          };
        }
        await handle.dispose().catch(() => {});
      }
      if (epochNow() > deadline) {
        return {
          kind: 'missing',
          error: any ? `${JSON.stringify(target)} matched ${any} element(s) but none is visible` : `no element matches ${JSON.stringify(target)}`,
        };
      }
      waited = true;
      await sleep(50);
    }
  }

  // ------------------------------------------------------------------ input

  pointerMode() {
    if (this.dev.contextOptions.hasTouch) return 'touch';
    if (this.dev.base.input === 'mouse') return 'mouse';
    this.warnOnce('pointer-fallback', `${this.dev.base.id} has no pointer (input=${this.dev.base.input}); pointer actions were sent as mouse events (fallback)`);
    return 'mouse(fallback)';
  }

  async touchPath(start, end, durationMs, holdStartMs, holdEndMs) {
    const steps = Math.max(2, Math.round(durationMs / 16));
    await this.cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: start.x, y: start.y }] });
    if (holdStartMs) await sleep(holdStartMs);
    for (let i = 1; i <= steps; i++) {
      const f = i / steps;
      await this.cdp.send('Input.dispatchTouchEvent', {
        type: 'touchMove',
        touchPoints: [{ x: start.x + (end.x - start.x) * f, y: start.y + (end.y - start.y) * f }],
      });
      await sleep(durationMs / steps);
    }
    if (holdEndMs) await sleep(holdEndMs);
    await this.cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  }

  async mousePath(start, end, durationMs, holdStartMs, holdEndMs) {
    const steps = Math.max(2, Math.round(durationMs / 16));
    await this.page.mouse.move(start.x, start.y);
    await this.page.mouse.down();
    if (holdStartMs) await sleep(holdStartMs);
    for (let i = 1; i <= steps; i++) {
      const f = i / steps;
      await this.page.mouse.move(start.x + (end.x - start.x) * f, start.y + (end.y - start.y) * f);
      await sleep(durationMs / steps);
    }
    if (holdEndMs) await sleep(holdEndMs);
    await this.page.mouse.up();
  }

  async gestureEnd(action, start) {
    if (action.to !== undefined) {
      const r = await this.resolveTarget(action.to, undefined, 2000);
      if (r.kind === 'missing') throw new Error(`gesture destination: ${r.error}`);
      if (r.handle) await r.handle.dispose().catch(() => {});
      return this.clampPoint(r.point);
    }
    let dx = action.dx ?? 0;
    let dy = action.dy ?? 0;
    if (action.direction) {
      const vertical = action.direction === 'up' || action.direction === 'down';
      const d = action.distance ?? (vertical ? this.vh : this.vw) * 0.5;
      dx = action.direction === 'right' ? d : action.direction === 'left' ? -d : 0;
      dy = action.direction === 'down' ? d : action.direction === 'up' ? -d : 0;
    }
    return this.clampPoint({ x: start.x + dx, y: start.y + dy });
  }

  async doScroll(action, anchorIn) {
    let dx = action.dx ?? 0;
    let dy = action.dy ?? 0;
    if (action.direction) {
      const vertical = action.direction === 'up' || action.direction === 'down';
      const d = action.distance ?? (vertical ? this.vh : this.vw) * 0.6;
      dx = action.direction === 'right' ? d : action.direction === 'left' ? -d : 0;
      dy = action.direction === 'down' ? d : action.direction === 'up' ? -d : 0;
    }
    const anchor = anchorIn || { x: this.vw / 2, y: this.vh / 2 };
    const mode = this.pointerMode();
    if (mode === 'touch') {
      // Finger moves opposite to the content; slow strokes with a final hold avoid
      // fling. Each stroke loses the touch slop (~10-15 CSS px in Chromium), so
      // strokes are lengthened by SLOP and, when the window is the scroller, up to
      // three corrective strokes close the remaining distance (scroll_delta
      // records what actually happened).
      const SLOP = 14;
      const maxY = Math.max(40, Math.min(this.vh * 0.6, 2 * Math.min(anchor.y, this.vh - anchor.y) - 16)) - SLOP;
      const maxX = Math.max(40, Math.min(this.vw * 0.6, 2 * Math.min(anchor.x, this.vw - anchor.x) - 16)) - SLOP;
      const stroke = async (cx, cy) => {
        const fx = cx === 0 ? 0 : cx + Math.sign(cx) * SLOP;
        const fy = cy === 0 ? 0 : cy + Math.sign(cy) * SLOP;
        const start = this.clampPoint({ x: anchor.x + fx / 2, y: anchor.y + fy / 2 });
        const end = this.clampPoint({ x: anchor.x - fx / 2, y: anchor.y - fy / 2 });
        await this.touchPath(start, end, action.duration_ms ?? 350, 0, 120);
        await sleep(60);
      };
      const origin = await this.scrollPos();
      let remX = dx;
      let remY = dy;
      for (let i = 0; i < 40 && (Math.abs(remX) > 0.5 || Math.abs(remY) > 0.5); i++) {
        const cx = Math.max(-maxX, Math.min(maxX, remX));
        const cy = Math.max(-maxY, Math.min(maxY, remY));
        await stroke(cx, cy);
        remX -= cx;
        remY -= cy;
      }
      for (let k = 0; origin && k < 3; k++) {
        const cur = await this.scrollPos();
        if (!cur || (cur.x === origin.x && cur.y === origin.y)) break; // not the window scroller
        const rx = dx - (cur.x - origin.x);
        const ry = dy - (cur.y - origin.y);
        if (Math.abs(rx) <= 2 && Math.abs(ry) <= 2) break;
        await stroke(Math.max(-maxX, Math.min(maxX, rx)), Math.max(-maxY, Math.min(maxY, ry)));
        const next = await this.scrollPos();
        if (!next || (Math.abs(next.x - cur.x) < 1 && Math.abs(next.y - cur.y) < 1)) break; // at the scroll limit
      }
      return 'touch';
    }
    await this.page.mouse.move(anchor.x, anchor.y);
    await this.page.mouse.wheel(dx, dy);
    await sleep(150);
    return mode;
  }

  async dispatchInput(action, resolved) {
    const kind = action.action;
    const p = resolved ? resolved.point : null;
    const center = { x: this.vw / 2, y: this.vh / 2 };
    const mode = POINTER.has(kind) || (kind === 'type' && p) ? this.pointerMode() : null;
    const touch = mode === 'touch';
    switch (kind) {
      case 'tap':
      case 'click':
        if (touch) await this.page.touchscreen.tap(p.x, p.y);
        else await this.page.mouse.click(p.x, p.y);
        return mode;
      case 'double_tap':
        if (touch) {
          await this.page.touchscreen.tap(p.x, p.y);
          await sleep(120);
          await this.page.touchscreen.tap(p.x, p.y);
        } else {
          await this.page.mouse.dblclick(p.x, p.y);
        }
        return mode;
      case 'long_press': {
        const ms = action.ms ?? action.duration_ms ?? 800;
        if (touch) {
          await this.cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: p.x, y: p.y }] });
          await sleep(ms);
          await this.cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
        } else {
          await this.page.mouse.move(p.x, p.y);
          await this.page.mouse.down();
          await sleep(ms);
          await this.page.mouse.up();
        }
        return mode;
      }
      case 'swipe':
      case 'drag': {
        const start = p || center;
        const end = await this.gestureEnd(action, start);
        const duration = action.duration_ms ?? (kind === 'swipe' ? 200 : 600);
        const holdStart = kind === 'drag' ? (action.hold_ms ?? 250) : 0;
        const holdEnd = kind === 'drag' ? 100 : 0;
        if (touch) await this.touchPath(start, end, duration, holdStart, holdEnd);
        else await this.mousePath(start, end, duration, holdStart, holdEnd);
        return { input: mode, start, end };
      }
      case 'type':
        if (p) {
          if (touch) await this.page.touchscreen.tap(p.x, p.y);
          else await this.page.mouse.click(p.x, p.y);
          await sleep(80);
        }
        if (action.clear) {
          await this.page.keyboard.press('ControlOrMeta+A');
          await this.page.keyboard.press('Backspace');
        }
        await this.page.keyboard.type(action.text, { delay: action.delay_ms ?? 25 });
        return p ? `${mode}+keyboard` : 'keyboard';
      case 'press':
        for (let i = 0; i < (action.repeat ?? 1); i++) {
          await this.page.keyboard.press(action.key, { delay: action.hold_ms ?? 0 });
        }
        return 'keyboard';
      case 'gamepad':
        for (const k of action.keys ?? [action.key]) {
          await this.page.keyboard.down(k);
          await sleep(action.hold_ms ?? 80);
          await this.page.keyboard.up(k);
        }
        return 'keyboard(gamepad-mapping)';
      case 'scroll':
        return this.doScroll(action, p);
      default:
        throw new Error(`unsupported action ${kind}`);
    }
  }

  /** Wait until a DOM mutation or main-frame navigation follows `dispatch`, or the deadline. */
  async waitForFeedback(dispatch, deadline) {
    while (epochNow() < deadline) {
      if (this.navEvents.some((t) => t >= dispatch)) return;
      if ((await this.firstMutation(dispatch, deadline + 1e6)) !== null) return;
      await sleep(16);
    }
  }

  /**
   * Arm native checkbox/radio activation evidence for an action target (see
   * armBinaryControl). Same resolution for handle and point targets, so the
   * scripted and /act flows share one implementation. A control the protected-
   * target rule or an opted-out region covers is never armed (no state, no id).
   */
  async armNativeBinary(resolved) {
    try {
      const redactSelectors = [...this.redactSelectors];
      const armed = resolved.handle
        ? await resolved.handle.evaluate(armBinaryControl, { key: STATE_KEY, redactSelectors })
        : await this.page.evaluate(armBinaryControl, { x: resolved.point.x, y: resolved.point.y, key: STATE_KEY, redactSelectors });
      return armed && armed.protected ? null : armed;
    } catch {
      return null;
    }
  }

  async readNativeBinary(dispatch, windowEnd) {
    try {
      // t0 and the returned event time live in the page's clock; this.clockOffset
      // (from calibrate()) is the only page↔Node conversion, as for DOM mutations.
      return await this.page.evaluate(readBinaryControl, {
        key: STATE_KEY, t0: dispatch + this.clockOffset, t1: windowEnd + this.clockOffset, stable_ms: 60,
      });
    } catch {
      return null;
    }
  }

  async disposeNativeBinary() {
    try {
      await this.page.evaluate(disposeBinaryControl, { key: STATE_KEY });
    } catch {
      /* page gone: nothing armed survives it */
    }
  }

  async performInput(action, resolved, step) {
    const kind = action.action;
    const fbTimeout = action.feedback_timeout_ms ?? (kind === 'scroll' ? 0 : this.opts.feedbackTimeoutMs);
    const visualOn = this.opts.visualFeedback && fbTimeout > 0 && MEASURED.has(kind);
    // Frames taken while a gesture scrolls something must not use a downscaling clip.
    this.wholeFrames = GESTURES.has(kind);
    let pre = null;
    let visualAmbient = false;
    let mask = null;
    let moving = null;
    if (visualOn) {
      // A focused text field's caret blinks: changes inside that field are not
      // feedback (typed characters are, through input events). Screen coordinates.
      mask = await this.page.evaluate(() => {
        let a = document.activeElement;
        while (a && a.shadowRoot && a.shadowRoot.activeElement) a = a.shadowRoot.activeElement;
        if (!a || a === document.body || a === document.documentElement) return null;
        const t = (a.getAttribute('type') || 'text').toLowerCase();
        const pressable = ['button', 'submit', 'reset', 'checkbox', 'radio', 'image', 'file', 'color', 'range'];
        if (!(a.tagName === 'TEXTAREA' || a.isContentEditable || (a.tagName === 'INPUT' && !pressable.includes(t)))) return null;
        const r = a.getBoundingClientRect();
        const v = window.visualViewport;
        const one = !!v && Math.abs(v.scale - 1) < 0.01;
        return { x: r.left - (one ? v.offsetLeft : 0), y: r.top - (one ? v.offsetTop : 0), w: r.width, h: r.height };
      }).catch(() => null);
      try {
        // A reversing animation can have the same color in the last two frames
        // (opposite sides of its turning point). An earlier sample identifies its
        // moving pixels without raising thresholds or masking static responses.
        const history = await this.captureFrame();
        await sleep(40);
        const a = await this.captureFrame();
        await sleep(40);
        pre = await this.captureFrame();
        if (mask) {
          const sx = pre.width / this.vw;
          const sy = pre.height / this.vh;
          mask = { x0: Math.floor((mask.x - 2) * sx), y0: Math.floor((mask.y - 2) * sy), x1: Math.ceil((mask.x + mask.w + 2) * sx), y1: Math.ceil((mask.y + mask.h + 2) * sy) };
        }
        const d = visualDiffFraction(a, pre, VISUAL_LEVEL, mask);
        visualAmbient = d !== null && d >= this.visualThreshold(pre);
        // Slow or reversing animations: union both pre-input motion masks. Keep
        // the ambient flag based on the last pair, as before.
        moving = changeMask(a, pre, AMBIENT_MOVE_LEVEL);
        const earlier = changeMask(history, a, AMBIENT_MOVE_LEVEL);
        if (earlier) moving = moving ? moving.map((v, i) => v || earlier[i]) : earlier;
      } catch {
        pre = null;
      }
    }
    const scrollBefore = ['scroll', 'swipe', 'drag'].includes(kind) ? await this.scrollPos() : null;
    // Native binary-control activation evidence: a small checkbox/radio whose
    // state changes without a DOM mutation can paint too little for the
    // downsampled visual diff; its boolean change plus a trusted input/change
    // event is recorded separately from the DOM/visual feedback below.
    const nativeArmed = ['tap', 'click', 'double_tap', 'long_press'].includes(kind) && resolved && (resolved.handle || resolved.point)
      ? await this.armNativeBinary(resolved) : null;
    // The watch is consumed exactly once: readNativeBinary clears it on every
    // return, and any failure between arming and the read (probe, navigation
    // wait, dispatch) disposes it here instead of leaving listeners behind.
    try {
    const dispatch = epochNow();
    step.t_start_ms = this.rel(dispatch);
    const fb = { visual: null, done: false };
    const probe = this.probeFrames({
      dispatch,
      stepIndex: step.step_index,
      flashMs: this.opts.flashSampleMs,
      visual: visualOn && pre && !visualAmbient ? { pre, mask, moving, deadline: dispatch + fbTimeout } : null,
      fb,
    });
    let inputErr = null;
    try {
      const r = await this.dispatchInput(action, resolved);
      if (r && typeof r === 'object') {
        step.input = r.input;
        if (!step.point) step.point = { x: round1(r.start.x), y: round1(r.start.y) };
        step.end_point = { x: round1(r.end.x), y: round1(r.end.y) };
      } else {
        step.input = r;
      }
    } catch (err) {
      inputErr = err;
    }
    const inputEnd = epochNow();
    if (fbTimeout > 0 && !inputErr) await this.waitForFeedback(dispatch, dispatch + fbTimeout);
    fb.done = true;
    await probe;
    this.wholeFrames = false;
    if (this.navEvents.some((t) => t >= dispatch)) {
      await this.page.waitForLoadState('load', { timeout: 10000 }).catch(() => {});
    }
    const early = [this.navEvents.find((t) => t >= dispatch)].filter((t) => t != null);
    const domEarly = await this.firstMutation(dispatch, epochNow());
    if (domEarly !== null) early.push(domEarly);
    if (!early.length && fb.visual != null) early.push(fb.visual);
    const anchor = Math.max(inputEnd, early.length ? Math.min(...early) : inputEnd);
    await sleep(anchor + (action.settle_ms ?? this.opts.settleMs) - epochNow());
    const end = epochNow();
    step.t_end_ms = Math.max(step.t_start_ms, this.rel(end));

    // Feedback latency (spec): first DOM mutation or main-frame navigation after
    // dispatch, within 3000 ms and before the after-snapshot. Only when neither
    // happened does a visual change of the viewport count (canvas/CSS-only
    // feedback); focus/caret or tap-highlight changes would otherwise mask
    // missing application feedback on DOM pages.
    const windowEnd = Math.min(dispatch + FEEDBACK_WINDOW_MS, end);
    const cands = [];
    const dom = await this.firstMutation(dispatch, windowEnd);
    if (dom !== null) cands.push({ t: dom, src: 'dom_mutation' });
    const nav = this.navEvents.find((t) => t >= dispatch && t <= windowEnd);
    if (nav !== undefined) cands.push({ t: nav, src: 'navigation' });
    cands.sort((a, b) => a.t - b.t);
    let first = cands[0] || null;
    if (!first && fb.visual != null && fb.visual <= windowEnd) first = { t: fb.visual, src: 'visual_change' };
    step.feedback_latency_ms = first ? round1(Math.max(0, first.t - dispatch)) : null;
    step.feedback_source = first ? first.src : null;
    step.feedback_dom_ms = dom !== null ? round1(Math.max(0, dom - dispatch)) : null;
    step.feedback_visual_ms = fb.visual != null ? round1(Math.max(0, fb.visual - dispatch)) : null;
    step.feedback_window_ms = round1(windowEnd - dispatch);
    step.feedback_ambient_mutations = await this.countMutations(dispatch - 500, dispatch);
    step.feedback_visual_ambient = visualOn ? visualAmbient : null;
    if (moving) step.feedback_visual_moving_px = moving.reduce((a, v) => a + v, 0);
    // State/semantic acknowledgment of a native checkbox/radio activation: the
    // boolean before/after and the trusted input/change event time for the same
    // control. Never a claim of visible paint, perceptibility or an announced
    // response: those stay with the DOM/visual evidence above.
    if (nativeArmed) {
      const native = await this.readNativeBinary(dispatch, windowEnd);
      if (native) {
        step.feedback_native_state = {
          source: 'native_state_change',
          via: native.via, type: native.type, dom_id: native.dom_id,
          before: native.before, after: native.after, changed: native.changed,
          event: native.event,
          // Event time arrives in the page clock; bring it to the Node clock
          // (the same single calibration offset the DOM path uses) before
          // subtracting the Node dispatch time.
          latency_ms: native.event_ms != null ? round1(Math.max(0, native.event_ms - this.clockOffset - dispatch)) : null,
        };
        if (native.stable === false) step.feedback_native_state.stable = false;
      }
    }
    if (scrollBefore) {
      const after = await this.scrollPos();
      if (after) step.scroll_delta = { x: round1(after.x - scrollBefore.x), y: round1(after.y - scrollBefore.y) };
    }
    if (inputErr) throw inputErr;
    } finally {
      if (nativeArmed) await this.disposeNativeBinary();
    }
  }

  /** Execute one validated action; always ends with an after-snapshot. */
  async act(action) {
    if (this.crashed) throw new DriverFailure('page crashed');
    if (action.action === 'type' && this.scenario.steps[this.steps.length]?.redact) action = { ...action, redact: true };
    this.rememberPrivateAction(action);
    if (action.redact && !(await this.page.evaluate((selector) => {
      try { document.querySelectorAll(selector); return true; } catch { return false; }
    }, action.target))) throw new DriverFailure('redacted typing requires valid plain CSS');
    const stepIndex = this.steps.length + 1;
    if (action.action === 'type') {
      this.authoredInputs.add(stepIndex);
      if (this.scenario.steps[stepIndex - 1]?.action === 'type' && this.scenario.steps[stepIndex - 1].text !== action.text) this.mismatchedInputs.add(stepIndex);
    }
    const step = {
      step_index: stepIndex,
      action: action.redact ? { ...this.redactRecord(action), text: '[redacted]' } : action,
      target_element_id: null,
      point: null,
      before: this.lastSnapshotId,
      after: null,
      t_start_ms: null,
      t_end_ms: null,
      feedback_latency_ms: null,
      result: 'ok',
      error: null,
      input: null,
    };
    let resolved = null;
    try {
      const kind = action.action;
      if (kind === 'wait') {
        const t0 = epochNow();
        step.t_start_ms = this.rel(t0);
        if (this.opts.flashSampleMs > 0) {
          // Flash sampling covers the whole wait: effects often play while the user waits.
          await this.probeFrames({ dispatch: t0, stepIndex, flashMs: action.ms, visual: null, fb: { done: true } });
        }
        await sleep(t0 + action.ms - epochNow());
        step.t_end_ms = Math.max(step.t_start_ms, this.rel(epochNow()));
      } else if (kind === 'snapshot') {
        const t0 = epochNow();
        step.t_start_ms = this.rel(t0);
        if (this.opts.flashSampleMs > 0) {
          await this.probeFrames({ dispatch: t0, stepIndex, flashMs: this.opts.flashSampleMs, visual: null, fb: { done: true } });
        }
        step.t_end_ms = Math.max(step.t_start_ms, this.rel(epochNow()));
      } else {
        if (action.target !== undefined) {
          const timeout = action.timeout_ms ?? DEFAULT_TARGET_TIMEOUT_MS;
          resolved = await this.resolveTarget(action.target, action.offset, timeout);
          const allowScroll = action.auto_scroll ?? this.opts.autoScroll;
          if (resolved.kind !== 'missing' && !this.inViewport(resolved.point) && allowScroll) {
            if (resolved.handle) {
              await resolved.handle.scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => {});
              await resolved.handle.dispose().catch(() => {});
              step.auto_scrolled = true;
            } else if (resolved.kind === 'hotspot' && resolved.origin === 'page') {
              // Live page hotspots follow the document; scenario boxes are fixed viewport coordinates.
              const p = resolved.point;
              await this.page.evaluate(({ dx, dy }) => window.scrollBy(dx, dy), {
                dx: p.x < 0 || p.x >= this.vw ? p.x - this.vw / 2 : 0,
                dy: p.y < 0 || p.y >= this.vh ? p.y - this.vh / 2 : 0,
              }).catch(() => {});
              step.auto_scrolled = true;
            }
            if (step.auto_scrolled) {
              await sleep(150);
              resolved = await this.resolveTarget(action.target, action.offset, timeout);
            }
          }
          const stale = resolved.kind === 'selector' && (resolved.elementId == null || (!resolved.exact && resolved.interactive));
          if (resolved.kind !== 'missing' && (resolved.waited || step.auto_scrolled || stale)) {
            // The target appeared or moved after the last snapshot: capture what the
            // user saw right before acting, and re-read ids from that snapshot.
            const why = step.auto_scrolled ? 'pre_action_auto_scroll' : 'pre_action_target_appeared';
            const pre = await this.snapshot(stepIndex, [why]);
            step.before = pre.id;
            if (resolved.handle) await resolved.handle.dispose().catch(() => {});
            resolved = await this.resolveTarget(action.target, action.offset, 1000);
          }
          if (resolved.kind === 'missing') {
            step.result = 'no_target';
            step.error = resolved.error;
          } else if (!this.inViewport(resolved.point)) {
            step.result = 'no_target';
            step.error = `target point (${resolved.point.x}, ${resolved.point.y}) is outside the ${this.vw}x${this.vh} viewport${allowScroll ? '' : ' (auto_scroll disabled)'}`;
            step.point = resolved.point;
            step.target_element_id = resolved.elementId || null;
          } else {
            step.point = resolved.point;
            step.target_element_id = resolved.elementId || null;
            if (['tap', 'click', 'double_tap', 'long_press'].includes(kind)) {
              step.target_control = resolved.handle
                ? await resolved.handle.evaluate(controlOf).catch(() => null)
                : await this.page.evaluate(controlOf, { x: resolved.point.x, y: resolved.point.y }).catch(() => null);
            }
            const hit = await this.page.evaluate(idAtPoint, { key: STATE_KEY, x: resolved.point.x, y: resolved.point.y }).catch(() => ({ id: null }));
            step.hit_element_id = hit.id;
            if (resolved.handle) step.target_hit = await resolved.handle.evaluate(hitTest, resolved.point).catch(() => null);
            else step.target_hit = resolved.elementId ? hit.id === resolved.elementId : null;
          }
        }
        if (step.result === 'ok' && ['tap', 'click'].includes(kind) && this.focusWalkEnabled() && this.pointerMode() !== 'touch') {
          if (this.scenario.surface_kind === 'game' || this.timedTarget(action.target)) {
            step.focus_probe = { skipped: this.scenario.surface_kind === 'game' ? 'game' : 'timed' };
          } else {
            await this.focusProbe(resolved, step);
            if (step.focus_probe && (!step.focus_probe.skipped || step.focus_probe.after_field) && resolved.handle) {
              // The probe must not change where the click lands: if the control moved or
              // something now covers it, resolve it again (and say so).
              const still = await resolved.handle.evaluate(hitTest, resolved.point).catch(() => null);
              if (still === false) {
                step.focus_probe.disturbed = true;
                const again = await this.resolveTarget(action.target, action.offset, 1000);
                if (again.kind !== 'missing' && this.inViewport(again.point)) {
                  await resolved.handle.dispose().catch(() => {});
                  resolved = again;
                  step.point = again.point;
                } else if (again.handle) {
                  await again.handle.dispose().catch(() => {});
                }
              }
            }
          }
        }
        if (step.result === 'ok') await this.performInput(action, resolved, step);
      }
    } catch (err) {
      if (err instanceof DriverFailure) throw new DriverFailure(this.redactRecord(err.message));
      step.result = 'error';
      step.error = action.redact ? 'redacted input action failed' : firstLine(err.message);
    } finally {
      if (resolved && resolved.handle) await resolved.handle.dispose().catch(() => {});
    }
    // focus_point: last pointer point; keyboard actions use the focused element.
    if (step.point && step.result === 'ok') {
      this.focusPoint = step.end_point ? { x: round1(step.end_point.x), y: round1(step.end_point.y) } : { ...step.point };
    } else if (['press', 'gamepad', 'type'].includes(action.action) && step.result === 'ok' && this.lastActive) {
      this.focusPoint = { ...this.lastActive };
    }
    let snap = null;
    const layersBefore = new Set((this.lastLayers || []).map((l) => l.selector));
    try {
      snap = await this.snapshot(stepIndex, [], stepIndex, step.result);
      step.after = snap.id;
      if (['tap', 'click', 'double_tap', 'long_press', 'press', 'wait', 'snapshot'].includes(action.action) && step.result === 'ok' && step.t_start_ms !== null) {
        await this.lateLayerFocus(step, layersBefore, ['wait', 'snapshot'].includes(action.action));
      }
      if (!step.point && ['press', 'gamepad', 'type'].includes(action.action) && this.lastActive && step.result === 'ok') {
        // Keyboard focus moved during the step: update for the next snapshot.
        this.focusPoint = { ...this.lastActive };
      }
    } catch (err) {
      step.result = 'error';
      step.error = step.error || firstLine(err.message);
      this.steps.push(step);
      throw err;
    }
    step.url_after = this.page.url();
    this.steps.push(step);
    return { step: this.redactRecord(step), snap };
  }

  // ------------------------------------------------------------------ notes / finish

  addNote(note) {
    const entry = {
      step_index: note.step_index ?? this.steps.length,
      intent: note.intent ?? '',
      expected: note.expected ?? '',
      observed: note.observed ?? '',
      confusion: note.confusion,
      snapshot_id: this.lastSnapshotId,
      t_ms: this.rel(epochNow()),
      basis: 'judgment',
    };
    // The agent's own severity and corroboration are claims, not evidence: stored
    // under *_claimed and never used for severity or tier (corroboration is computed
    // across runs by model family and input channel).
    if (note.severity) entry.severity_claimed = note.severity;
    if (note.failure_class) entry.failure_class = note.failure_class;
    if (note.evidence) entry.evidence = note.evidence;
    if (note.corroborated !== undefined) entry.corroborated_claimed = note.corroborated;
    Object.assign(entry, this.resolveAnchor(note.anchor ?? 'acted', entry.step_index));
    this.personaNotes.push(entry);
    return this.personaNotes.length - 1;
  }

  /** Resolve a note anchor to element ids and selectors in a recorded snapshot. */
  resolveAnchor(anchor, stepIndex) {
    const out = { anchor, anchor_snapshot_id: null, anchor_element_ids: [], anchor_selectors: [], screen_key: null };
    const screenKey = (snapId) => {
      const s = this.snapElements.get(snapId);
      if (!s) return null;
      let pathname = '';
      try {
        pathname = new URL(s.url).pathname;
      } catch { /* keep empty */ }
      const heads = s.elements.filter((e) => e.role === 'heading' && e.visible && e.in_viewport).map((e) => e.text).slice(0, 4).join('|');
      const modal = s.elements.some((e) => e.inert_by_modal) ? '+modal' : '';
      return `${pathname}#${sha256(Buffer.from(heads)).slice(0, 8)}${modal}`;
    };
    if (anchor === 'acted') {
      const step = [...this.steps].reverse().find((st) => st.step_index <= stepIndex && st.target_element_id);
      if (step) {
        const s = this.snapElements.get(step.before);
        const el = s && s.elements.find((e) => e.id === step.target_element_id);
        if (el) {
          out.anchor_snapshot_id = step.before;
          out.anchor_element_ids = [el.id];
          out.anchor_selectors = el.selector ? [el.selector] : [];
        }
        out.screen_key = screenKey(step.after || step.before);
      }
      return out;
    }
    const snapId = this.lastSnapshotId;
    const s = this.snapElements.get(snapId);
    out.anchor_snapshot_id = snapId;
    out.screen_key = screenKey(snapId);
    if (!s) return out;
    const vis = s.elements.filter((e) => e.visible && e.box && e.box.w > 0 && e.box.h > 0);
    let pick = null;
    if (anchor.point) {
      const { x, y } = anchor.point;
      const inside = vis.filter((e) => x >= e.box.x && x <= e.box.x + e.box.w && y >= e.box.y && y <= e.box.y + e.box.h);
      pick = inside.sort((a, b) => a.box.w * a.box.h - b.box.w * b.box.h)[0] || null;
    } else if (anchor.box) {
      const b = anchor.box;
      const iou = (e) => {
        const ix = Math.max(0, Math.min(b.x + b.w, e.box.x + e.box.w) - Math.max(b.x, e.box.x));
        const iy = Math.max(0, Math.min(b.y + b.h, e.box.y + e.box.h) - Math.max(b.y, e.box.y));
        const inter = ix * iy;
        return inter / (b.w * b.h + e.box.w * e.box.h - inter);
      };
      const best = vis.map((e) => [iou(e), e]).sort((p, q) => q[0] - p[0])[0];
      pick = best && best[0] >= 0.3 ? best[1] : null;
    }
    if (pick) {
      out.anchor_element_ids = [pick.id];
      out.anchor_selectors = pick.selector ? [pick.selector] : [];
    }
    return out;
  }

  async sampleTaskChecks(checkpoint, stepResult) {
    const samples = new Map();
    if (stepResult !== 'ok') return samples;
    for (const c of this.scenario.success?.task_checks || []) {
      if ((c.after_step ?? 'final') !== checkpoint || this.taskCheckResults.has(c.id)) continue;
      if ('from_step' in c && (!this.authoredInputs.has(c.from_step) || this.mismatchedInputs.has(c.from_step)
        || (c.from_step !== checkpoint && this.steps[c.from_step - 1]?.result !== 'ok'))) continue;
      try {
        samples.set(c.id, await this.page.evaluateHandle(sampleTaskState, { selector: c.selector, property: c.property,
          expected: 'from_step' in c ? this.scenario.steps[c.from_step - 1].text : c.expected, key: STATE_KEY }));
      } catch { samples.set(c.id, null); }
    }
    return samples;
  }

  async evaluateTaskChecks(checkpoint, snapshot, stepResult = 'ok', beforeSamples = new Map()) {
    for (const criterion of this.scenario.success?.task_checks || []) {
      if ((criterion.after_step ?? 'final') !== checkpoint || this.taskCheckResults.has(criterion.id)) continue;
      const result = {
        kind: 'task_check', id: criterion.id, selector: criterion.selector, property: criterion.property,
        checkpoint, step_index: snapshot?.snap.step_index ?? this.steps.length,
        snapshot_id: snapshot?.id ?? null, element_id: null, passed: null, result: 'unevaluable', reason: null,
        severity: criterion.severity, consequence: criterion.consequence,
      };
      const expected = 'from_step' in criterion ? this.scenario.steps[criterion.from_step - 1].text : criterion.expected;
      if (stepResult !== 'ok') result.reason = 'action_failed';
      else if ('from_step' in criterion && !this.authoredInputs.has(criterion.from_step)) result.reason = 'source_step_unvisited';
      else if ('from_step' in criterion && criterion.from_step !== checkpoint && this.steps[criterion.from_step - 1]?.result !== 'ok') result.reason = 'source_step_failed';
      else if ('from_step' in criterion && this.mismatchedInputs.has(criterion.from_step)) result.reason = 'source_input_mismatch';
      else if (!snapshot || !this.page || this.crashed || this.page.isClosed()) result.reason = 'capture_unavailable';
      else {
        try {
          // Only explicitly selected CSS targets are read, and only the comparison leaves the DOM.
          const before = beforeSamples.get(criterion.id);
          if (!before) result.reason = 'capture_unavailable';
          else {
            const after = await this.page.evaluateHandle(sampleTaskState, { selector: criterion.selector, property: criterion.property, expected, key: STATE_KEY });
            try {
              Object.assign(result, await after.evaluate((last, first) => {
                if (last.reason !== first.reason || !Object.is(last.private_actual, first.private_actual) || last.private_node !== first.private_node) return { reason: 'capture_state_changed' };
                // Private browser handles are disposed below; values/nodes never enter the result.
                return last.reason ? { reason: last.reason } : { passed: last.passed, result: last.result, reason: null, element_id: last.element_id };
              }, before));
            } finally { await after.dispose().catch(() => {}); }
          }
        } catch {
          result.reason = 'evaluation_error'; // Exception text can carry a field value.
        }
      }
      this.taskCheckResults.set(criterion.id, this.redactRecord(result));
      await beforeSamples.get(criterion.id)?.dispose().catch(() => {});
    }
  }

  async evaluateSuccess() {
    const sc = this.scenario.success;
    const unevaluable = [...this.scenario.success_unevaluable];
    if (!sc && !unevaluable.length) return { success: null, detail: null };
    const results = [];
    const check = async (kind, value, fn) => {
      try {
        results.push({ kind, value, passed: !!(await fn()) });
      } catch (err) {
        results.push({ kind, value, passed: false, error: firstLine(err.message) });
      }
    };
    if (this.page && !this.crashed && !this.page.isClosed()) {
      for (const sel of sc?.selector_visible || []) {
        await check('selector_visible', sel, async () => (await this.page.locator(sel).filter({ visible: true }).count()) > 0);
      }
      for (const s of sc?.url_contains || []) await check('url_contains', s, async () => this.page.url().includes(s));
      if (sc?.text_present) {
        const body = await this.page.evaluate(() => (document.body ? document.body.innerText : '')).catch(() => '');
        for (const s of sc.text_present) await check('text_present', s, async () => body.includes(s));
      }
    }
    for (const criterion of sc?.task_checks || []) {
      const result = this.taskCheckResults.get(criterion.id) || {
        kind: 'task_check', id: criterion.id, selector: criterion.selector, property: criterion.property,
        checkpoint: criterion.after_step ?? 'final', step_index: criterion.after_step ?? this.steps.length,
        snapshot_id: null, element_id: null, passed: null, result: 'unevaluable', reason: 'checkpoint_unvisited',
        severity: criterion.severity, consequence: criterion.consequence,
      };
      results.push(this.redactRecord(result));
      if (result.passed === null) unevaluable.push(criterion.id);
    }
    const allPassed = results.length > 0 && results.every((r) => r.passed);
    const anyFailed = results.some((r) => r.passed === false) || (this.crashed && results.length === 0);
    let success;
    if (anyFailed) success = false;
    else if (unevaluable.length || !results.length) success = null;
    else success = allPassed;
    return { success, detail: { criteria: results, unevaluable } };
  }

  async finish({ personaSuccess, reason } = {}) {
    if (this.finished) return this.finished;
    const finishing = (async () => {
      if (reason) this.block(reason);
      for (const t of this.twPollers) clearInterval(t);
      const end = epochNow();
      let success = null;
      let detail = null;
      let basis = null;
      try {
        if (this.scenario.success?.task_checks?.some((c) => c.after_step === undefined)) {
          const complete = !this.crashed && !this.blockReasons.length && (this.mode !== 'scripted' || this.steps.every((s) => s.result === 'ok'));
          try { await this.snapshot(this.steps.length, ['task_check_final'], 'final', complete ? 'ok' : 'incomplete'); }
          catch { this.block('final task check capture unavailable'); }
        }
        ({ success, detail } = await this.evaluateSuccess());
        if (detail) basis = 'measured';
      } catch (err) {
        this.warnings.push(`success evaluation failed: ${firstLine(err.message)}`);
      }
      // Focus walks run after the task (so they never delay step 1) and only when the
      // run ended normally: at the end state, then the initial screen in a fresh context.
      if (this.focusWalkEnabled() && !reason && !this.crashed && this.page && !this.blockReasons.length) {
        await this.boundedWalk(() => this.focusWalk(this.page, 'end', this.lastSnapshotId), 'end');
        await this.boundedWalk(() => this.focusWalkFresh(), 'load');
      }
      if (!reason && !this.crashed && !this.blockReasons.length && this.dev && this.reflowEnabled()) {
        await this.adaptationPass().catch((err) => this.warnOnce('adaptation-pass', `adaptation pass failed: ${firstLine(err.message)}`));
        await this.reflowPass();
      }
      if (success === null && !detail && typeof personaSuccess === 'boolean') {
        success = personaSuccess;
        basis = 'judgment';
      }
      let finalUrl = null;
      let title = null;
      try {
        finalUrl = this.page.url();
        title = await this.page.title();
      } catch { /* page gone */ }
      let status = 'completed';
      if (this.blockReasons.length) status = 'blocked';
      else if (this.mode === 'scripted' && this.steps.some((s) => s.result !== 'ok')) status = 'failed';
      if (status !== 'completed') success = false;
      const flashCov = this.flashCoverage();
      const run = {
        schema_version: 'ergo-run.v1',
        run_id: this.runId,
        scenario_id: this.scenario.scenario_id,
        profile_id: this.profileId,
        driver: {
          name: 'playwright-web',
          version: this.pwInfo.version,
          browser: 'chromium',
          browser_version: this.browserVersion || null,
          browser_connected: this.browserTransport?.connected || false,
          playwright_client_version: this.pwInfo.version,
          playwright_path: this.pwInfo.path,
          emulation: this.dev ? { ...this.dev.emulation, locale: this.opts.locale, timezone: this.opts.timezoneId } : null,
          network_policy: {
            allowed_origins: [...this.allowedOrigins],
            blocked_requests: this.blockedCount,
            blocked_sample: this.blocked,
            blocked_console_messages_suppressed: this.blockedConsole,
          },
          clock: { page_offset_ms: round1(this.clockOffset), calibration_rtt_ms: round1(this.clockRtt) },
          feedback: {
            window_ms: FEEDBACK_WINDOW_MS,
            wait_ms: this.opts.feedbackTimeoutMs,
            sources: ['dom_mutation', 'navigation', ...(this.opts.visualFeedback ? ['visual_change'] : [])],
            state_acknowledgment: 'native_state_change: feedback_native_state on tap/click steps records a checkbox/radio boolean change with the trusted input/change event time of the same control, taken at event time and converted through the calibrated page clock (state/semantic acknowledgment; not calibrated visible paint or an announced response). Protected controls and opted-out regions are never recorded; an unstable end state is marked stable: false.',
            visual_frame_width_css: FRAME_WIDTH,
            visual_pixel_level: VISUAL_LEVEL,
          },
          element_cap: ELEMENT_CAP,
        },
        device: this.dev ? this.dev.snapshotDevice : null,
        mode: this.mode,
        agent: this.opts.agentInfo ? { ...this.opts.agentInfo, ...(this.opts.agent ? { description: this.opts.agent } : {}) }
          : this.opts.agent ? { description: this.opts.agent } : (this.mode === 'interactive' ? { description: 'unrecorded' } : null),
        started_at: this.startedAt,
        ended_at: isoNow(),
        status,
        success,
        success_basis: basis,
        success_detail: detail,
        ...(this.mode === 'interactive' ? { persona_claimed_success: typeof personaSuccess === 'boolean' ? personaSuccess : null } : {}),
        surface: { kind: this.scenario.surface_kind === 'game' ? 'game' : 'web', url: this.scenario.url, final_url: finalUrl, title, http_status: this.httpStatus,
          ...(this.opts.buildId ? { build_id: this.opts.buildId, build_id_basis: 'operator_supplied', build_id_source: this.opts.buildIdSource } : {}) },
        steps: this.steps,
        timing_windows: this.timingWindowsOut(end),
        flash_samples: this.flashSamples,
        focus_walks: this.focusWalks,
        reflow: this.reflow,
        adaptation: this.adaptation,
        ...(this.reflowDropped.size ? { reflow_screens_dropped: this.reflowDropped.size } : {}),
        flash_sampling: this.opts.flashSampleMs > 0 ? {
          enabled: true,
          per_step_ms: this.opts.flashSampleMs,
          // After page load, after each input and during snapshot steps for per_step_ms;
          // during wait steps for the whole wait.
          during: ['load', 'input', 'snapshot', 'wait'],
          method: `CDP Page.captureScreenshot of the visual viewport (clip at its page position; whole capture when panned), downscaled to ~${FRAME_WIDTH} CSS px wide, optimizeForSpeed, random 0-${FLASH_JITTER_MS} ms pause between captures`,
          jitter_ms: [0, FLASH_JITTER_MS],
          frames: this.flashSamples.length,
          bursts: flashCov.bursts,
          sampled_ms: flashCov.sampled_ms,
          mean_fps: flashCov.mean_fps,
          max_gap_ms: flashCov.max_gap_ms,
          run_ms: this.rel(end),
          mean_interval_ms: flashCov.mean_interval_ms,
          max_interval_ms: flashCov.max_gap_ms,
          truncated: this.flashTruncated,
          caps: { samples: MAX_FLASH_SAMPLES, bytes: MAX_FLASH_BYTES },
          block_grid: this.flashGridOut(),
          changed_fraction: 'share of pixels with |delta relative luminance| >= 0.10 vs the previous frame of the same burst (0 for the first frame)',
          flash_fraction: 'changed pixels whose darker state is < 0.80 (WCAG 2.3.1 general-flash pair condition)',
        } : { enabled: false },
        persona_notes: this.personaNotes,
        snapshots: this.snapshots,
        console_errors: this.consoleAll,
        blocked_reasons: this.blockReasons,
        warnings: this.warnings,
      };
      try {
        if (!run.device) run.device = this.deviceRequest.fallbackDevice;
        writeJsonAtomic(path.join(this.runDir, 'run.json'), this.redactRecord(run));
      } finally {
        if (this.browserTransport) await this.browserTransport.close([this.context]);
      }
      let exitCode = 3;
      if (status === 'blocked') exitCode = 4;
      else if (status === 'completed' && success === true) exitCode = 0;
      return { status, success, runPath: path.join(this.runDir, 'run.json'), exitCode, run };
    })();
    this.finished = finishing;
    return finishing;
  }
}

export function ensureRunDir(dir) {
  if (fs.existsSync(dir)) {
    const st = fs.lstatSync(dir);
    if (!st.isDirectory() || st.isSymbolicLink()) return `run directory ${dir} exists and is not a plain directory`;
    if (fs.readdirSync(dir).length) return `run directory ${dir} already exists and is not empty (evidence is never overwritten)`;
    return null;
  }
  fs.mkdirSync(dir, { recursive: true });
  return null;
}
