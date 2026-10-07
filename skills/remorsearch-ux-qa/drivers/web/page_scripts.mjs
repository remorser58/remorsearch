// Functions that run inside the page under test. They are serialized by
// Playwright (addInitScript / evaluate), so each must be self-contained: no
// closures over module scope. None of them evaluates strings or request data;
// they only read the DOM and computed styles, and keep a small driver state
// object under a non-enumerable Symbol.for(key) property of `window`.

export const STATE_KEY = 'ergoqa.driver.v1';
export const TW_BINDING = '__ergoqaDriverTimingWindow';

/**
 * Installed with addInitScript before any page script runs (main frame only):
 * - MutationObserver ring buffer of callback timestamps (epoch ms) for
 *   feedback-latency measurement (input events count too: a field's value change);
 * - optional timing-window poller (every cfg.pollMs, default 16 ms) that reports
 *   visibility transitions of CSS selectors through an exposed binding.
 */
export function pageInit(cfg) {
  try {
    if (window.top !== window) return;
  } catch (e) {
    return;
  }
  const KEY = Symbol.for(cfg.key);
  if (window[KEY]) return;
  const now = () => performance.timeOrigin + performance.now();
  const N = 8192;
  const times = new Float64Array(N);
  let head = 0;
  let count = 0;
  const scan = (t0, t1, visit) => {
    for (let i = 1; i <= count; i++) {
      const v = times[(head - i + N) % N];
      if (v < t0) break;
      if (v <= t1) visit(v);
    }
  };
  const state = {
    ids: new WeakMap(),
    mutations: 0,
    now,
    firstMutationAfter(t0, t1) {
      let best = null;
      scan(t0, t1, (v) => { best = v; });
      return best;
    },
    countMutations(t0, t1) {
      let c = 0;
      scan(t0, t1, () => { c++; });
      return c;
    },
  };
  Object.defineProperty(window, KEY, { value: state, enumerable: false, configurable: false, writable: false });
  const record = () => {
    times[head] = now();
    head = (head + 1) % N;
    if (count < N) count++;
    state.mutations++;
  };
  // Only real changes count: a script that writes an attribute or text node with the
  // value it already has (a style re-set) changes nothing on screen. Attributes of <html>
  // and <body> are page-state markers (input modality, scroll lock, theme): what they
  // change on screen, if anything, is seen by the visual comparison.
  const changed = (m) => {
    if (m.type === 'childList') return m.addedNodes.length > 0 || m.removedNodes.length > 0;
    if (m.type === 'attributes') {
      if (m.target === document.documentElement || m.target === document.body) return false;
      return m.oldValue !== m.target.getAttribute(m.attributeName);
    }
    return m.oldValue !== m.target.data;
  };
  try {
    new MutationObserver((list) => {
      if (list.some(changed)) record();
    }).observe(document, {
      subtree: true, childList: true, attributes: true, characterData: true, attributeOldValue: true, characterDataOldValue: true,
    });
  } catch (e) { /* no document yet: nothing to observe */ }
  // A field's value changing (typed or deleted characters) is feedback too, and it is
  // not a DOM mutation. The driver masks the focused field in visual comparisons (the
  // caret blinks), so this is how typing echo is seen.
  // Checkbox, radio, range, colour, file and select changes show nothing by themselves.
  const NO_ECHO = ['checkbox', 'radio', 'range', 'color', 'file'];
  try {
    window.addEventListener('input', (e) => {
      const t = e.target;
      if (t && (t.tagName === 'SELECT' || (t.tagName === 'INPUT' && NO_ECHO.includes((t.type || '').toLowerCase())))) return;
      record();
    }, true);
  } catch (e) { /* ignore */ }

  // A script that changes a field's value (an amount chip filling the amount field)
  // changes what is on screen without a DOM mutation or an input event.
  for (const C of [window.HTMLInputElement, window.HTMLTextAreaElement]) {
    try {
      const d = C && Object.getOwnPropertyDescriptor(C.prototype, 'value');
      if (!d || !d.get || !d.set || !d.configurable) continue;
      Object.defineProperty(C.prototype, 'value', {
        configurable: true,
        enumerable: d.enumerable,
        get() { return d.get.call(this); },
        set(v) {
          const before = d.get.call(this);
          d.set.call(this, v);
          if (this.isConnected && d.get.call(this) !== before && !NO_ECHO.includes((this.type || '').toLowerCase())) record();
        },
      });
    } catch (e) { /* leave the property as it is */ }
  }

  const windows = Array.isArray(cfg.windows) ? cfg.windows : [];
  if (!windows.length || !cfg.binding) return;
  // Rendered, whether or not it is inside the viewport: a message that appears
  // off-screen is itself a finding (it cannot be read), so it must be recorded.
  const shown = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    if (typeof el.checkVisibility === 'function') {
      return el.checkVisibility({ opacityProperty: true, visibilityProperty: true });
    }
    const cs = getComputedStyle(el);
    return cs.display !== 'none' && cs.visibility === 'visible' && parseFloat(cs.opacity) > 0;
  };
  const last = new Map();
  const tick = () => {
    const fn = window[cfg.binding];
    if (typeof fn !== 'function') return;
    const t = now();
    for (const w of windows) {
      let v = false;
      let text = null;
      let box = null;
      let bg = null;
      let off = null;
      try {
        for (const el of document.querySelectorAll(w.selector)) {
          if (shown(el)) {
            v = true;
            if (last.get(w.id) !== true) {
              text = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 500);
              // Geometry and own fill at appearance: elements that flash between
              // snapshots are never captured by them.
              const r = el.getBoundingClientRect();
              box = { x: r.left, y: r.top, w: r.width, h: r.height };
              bg = getComputedStyle(el).backgroundColor || null;
              off = r.bottom <= 0 || r.right <= 0 || r.top >= window.innerHeight || r.left >= window.innerWidth;
            }
            break;
          }
        }
      } catch (e) {
        v = null; // not a CSS selector: the driver falls back to Playwright polling
      }
      if (!last.has(w.id) || last.get(w.id) !== v) {
        last.set(w.id, v);
        try {
          Promise.resolve(fn({ id: w.id, v, t, text, box, bg, off })).catch(() => {});
        } catch (e) { /* binding gone during unload */ }
      }
    }
  };
  setInterval(tick, cfg.pollMs || 16);
}

/**
 * Element extraction for one snapshot (spec section 10). `args`:
 *   key, cap, groups: [{role, handles: [ElementHandle]}], hotspots (scenario),
 *   hotspotRoles: {hotspotId: [role]}, knownRoles: [role]
 * Returns {elements, candidates, truncated, viewport, scroll, active, pageHotspotError, unknownRoles}.
 */
export function extractSnapshot(args) {
  const KEY = Symbol.for(args.key);
  let state = window[KEY];
  if (!state) {
    state = { ids: new WeakMap() };
    try {
      Object.defineProperty(window, KEY, { value: state, enumerable: false });
    } catch (e) { /* ignore */ }
  }
  // The screen shows the visual viewport. At scale 1 it can be smaller than the layout
  // viewport (content wider than the screen widens the layout viewport) and panned
  // inside it. Geometry is computed in layout coordinates (elementFromPoint) against
  // the screen's bounds [VX0, VX1) x [VY0, VY1), and reported relative to the screen, so
  // boxes line up with the screenshot and with input coordinates.
  const vvp = window.visualViewport;
  const panned = !!vvp && Math.abs(vvp.scale - 1) < 0.01
    && (vvp.offsetLeft > 0.5 || vvp.offsetTop > 0.5 || vvp.width < window.innerWidth - 1 || vvp.height < window.innerHeight - 1);
  const VX0 = panned ? vvp.offsetLeft : 0;
  const VY0 = panned ? vvp.offsetTop : 0;
  const vw = panned ? vvp.width : window.innerWidth;
  const vh = panned ? vvp.height : window.innerHeight;
  const VX1 = VX0 + vw;
  const VY1 = VY0 + vh;
  const known = new Set(args.knownRoles || []);
  const unknownRoles = new Set();
  const round2 = (n) => Math.round(n * 100) / 100;

  // ---------- colours
  let probe = null;
  const colorCache = new Map();
  const parseColor = (str) => {
    if (!str) return null;
    if (colorCache.has(str)) return colorCache.get(str);
    let out = null;
    const m = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:\s*[,/]\s*([\d.]+)(%?))?\s*\)$/.exec(str);
    if (m) {
      let a = m[4] === undefined ? 1 : parseFloat(m[4]);
      if (m[5] === '%') a /= 100;
      out = { r: +m[1], g: +m[2], b: +m[3], a: Math.max(0, Math.min(1, a)) };
    } else if (str === 'transparent') {
      out = { r: 0, g: 0, b: 0, a: 0 };
    } else {
      try {
        if (!probe) {
          const c = typeof OffscreenCanvas === 'function' ? new OffscreenCanvas(1, 1) : document.createElement('canvas');
          probe = c.getContext('2d', { willReadFrequently: true });
        }
        probe.clearRect(0, 0, 1, 1);
        probe.fillStyle = '#000';
        probe.fillStyle = str;
        probe.fillRect(0, 0, 1, 1);
        const d = probe.getImageData(0, 0, 1, 1).data;
        out = { r: d[0], g: d[1], b: d[2], a: d[3] / 255 };
      } catch (e) {
        out = null;
      }
    }
    colorCache.set(str, out);
    return out;
  };
  const over = (top, bottom) => ({
    r: top.r * top.a + bottom.r * (1 - top.a),
    g: top.g * top.a + bottom.g * (1 - top.a),
    b: top.b * top.a + bottom.b * (1 - top.a),
  });
  const mix = (a, b, t) => ({ r: a.r + (b.r - a.r) * t, g: a.g + (b.g - a.g) * t, b: a.b + (b.b - a.b) * t });
  const hex = (c) => {
    if (!c) return null;
    const h = (v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0');
    return `#${h(c.r)}${h(c.g)}${h(c.b)}`;
  };

  const styleCache = new Map();
  const style = (el) => {
    let cs = styleCache.get(el);
    if (!cs) {
      cs = getComputedStyle(el);
      styleCache.set(el, cs);
    }
    return cs;
  };
  const parentOf = (n) => n.parentElement || (n.getRootNode && n.getRootNode() !== document ? n.getRootNode().host : null) || null;
  const MEDIA = new Set(['img', 'video', 'canvas', 'svg', 'iframe', 'picture', 'object', 'embed']);

  let canvasBase = null;
  const baseColor = () => {
    if (canvasBase) return canvasBase;
    let c = { r: 255, g: 255, b: 255 };
    const root = document.documentElement;
    const body = document.body;
    const rootBg = root ? parseColor(style(root).backgroundColor) : null;
    if (rootBg && rootBg.a > 0) c = over(rootBg, c);
    else if (body) {
      const bodyBg = parseColor(style(body).backgroundColor);
      if (bodyBg && bodyBg.a > 0) c = over(bodyBg, c);
    }
    canvasBase = c;
    return c;
  };

  // Layers from `el` downward in paint order (el first).
  const layersBelow = (el, rect) => {
    const ancestors = [];
    for (let n = el; n; n = parentOf(n)) ancestors.push(n);
    const ix0 = Math.max(VX0, rect.left);
    const ix1 = Math.min(VX1, rect.right);
    const iy0 = Math.max(VY0, rect.top);
    const iy1 = Math.min(VY1, rect.bottom);
    if (ix1 - ix0 >= 1 && iy1 - iy0 >= 1) {
      let stack = [];
      try {
        stack = document.elementsFromPoint((ix0 + ix1) / 2, (iy0 + iy1) / 2);
      } catch (e) {
        stack = [];
      }
      let idx = stack.indexOf(el);
      if (idx >= 0) return { chain: stack.slice(idx), ancestors };
      idx = stack.findIndex((n) => n !== el && n.contains && n.contains(el));
      if (idx >= 0) {
        const container = stack[idx];
        const head = [];
        for (const n of ancestors) {
          if (n === container) break;
          head.push(n);
        }
        return { chain: head.concat(stack.slice(idx)), ancestors };
      }
    }
    return { chain: ancestors, ancestors };
  };

  // Effective opaque colours with group opacity for ancestors (spec: walk ancestors,
  // composite rgba over white; null when an image/gradient/canvas is underneath).
  const colorsFor = (el, rect, cs, svgPaint = false) => {
    const unknownMedia = (n) => MEDIA.has(n.tagName?.toLowerCase()) && !(svgPaint && n.tagName?.toLowerCase() === 'svg');
    // SVG shapes/groups do not paint CSS box backgrounds. The outer <svg> does.
    const svgGraphic = (n) => svgPaint && n instanceof SVGElement && n.tagName.toLowerCase() !== 'svg';
    const background = (n, ncs) => svgGraphic(n) ? null : parseColor(ncs.backgroundColor);
    const imageBackground = (n, ncs) => !svgGraphic(n) && ncs.backgroundImage && ncs.backgroundImage !== 'none';
    const { chain, ancestors } = layersBelow(el, rect);
    const anc = new Set(ancestors);
    let color = baseColor();
    const groups = [];
    let outer = null;
    // Start at the topmost fully opaque solid layer at or below the element when no
    // translucent group sits above it: whatever is under an opaque fill (canvas,
    // image, gradient) cannot show through, so it must not null the colour.
    let start = chain.length - 1;
    for (let i = 0; i < chain.length; i++) {
      const n = chain[i];
      const tag = n.tagName ? n.tagName.toLowerCase() : '';
      const ncs = style(n);
      if (unknownMedia(n) || imageBackground(n, ncs)) break;
      if ((parseFloat(ncs.opacity) || 0) < 1) break;
      const bg = background(n, ncs);
      if (bg && bg.a >= 0.999) {
        start = i;
        break;
      }
    }
    for (let i = start; i >= 0; i--) {
      const n = chain[i];
      const tag = n.tagName ? n.tagName.toLowerCase() : '';
      if (unknownMedia(n)) return null;
      // A different SVG shape behind this one is not a uniform CSS backdrop.
      if (svgPaint && n instanceof SVGElement && n !== el && !n.contains(el) && n.tagName.toLowerCase() !== 'svg') return null;
      const ncs = style(n);
      if (imageBackground(n, ncs)) return null;
      const op = parseFloat(ncs.opacity);
      const bg = background(n, ncs);
      if (n === el) outer = { color, groups: groups.slice() };
      if (anc.has(n)) {
        if (op < 1) groups.push({ backdrop: color, alpha: op });
        if (bg && bg.a > 0) color = over(bg, color);
      } else if (bg && bg.a > 0) {
        let cum = 1;
        for (let p = n; p; p = parentOf(p)) cum *= parseFloat(style(p).opacity) || 0;
        color = over({ ...bg, a: bg.a * cum }, color);
      }
    }
    const fgRaw = parseColor(cs.color) || { r: 0, g: 0, b: 0, a: 1 };
    let bgC = color;
    let fgC = over(fgRaw, color);
    for (let i = groups.length - 1; i >= 0; i--) {
      bgC = mix(groups[i].backdrop, bgC, groups[i].alpha);
      fgC = mix(groups[i].backdrop, fgC, groups[i].alpha);
    }
    let containerC = null;
    if (outer) {
      containerC = outer.color;
      for (let i = outer.groups.length - 1; i >= 0; i--) {
        containerC = mix(outer.groups[i].backdrop, containerC, outer.groups[i].alpha);
      }
    }
    if (start === 0 && chain.length > 1) {
      // The element's own fill is opaque, so the loop above started at the element and
      // `outer` fell back to the page base colour. Composite the layers below it instead.
      let below = chain.length - 1;
      let blocked = false;
      for (let i = 1; i < chain.length; i++) {
        const n = chain[i];
        const tag = n.tagName ? n.tagName.toLowerCase() : '';
        const ncs = style(n);
        if (unknownMedia(n) || imageBackground(n, ncs)) { blocked = true; break; }
        const bg = background(n, ncs);
        if (bg && bg.a >= 0.999) { below = i; break; }
      }
      if (blocked) containerC = null;
      else {
        let c = baseColor();
        for (let i = below; i >= 1; i--) {
          const bg = background(chain[i], style(chain[i]));
          if (bg && bg.a > 0) c = over(bg, c);
        }
        containerC = c;
      }
    }
    const composite = (raw, backdrop = color) => {
      let c = over(raw, backdrop);
      for (let i = groups.length - 1; i >= 0; i--) c = mix(groups[i].backdrop, c, groups[i].alpha);
      return c;
    };
    return { fg: fgC, bg: bgC, container: containerC, composite, rawBg: color };
  };

  const borderFor = (cs, bg) => {
    let best = null;
    for (const side of ['Top', 'Right', 'Bottom', 'Left']) {
      const w = parseFloat(cs[`border${side}Width`]) || 0;
      const st = cs[`border${side}Style`];
      if (w <= 0 || st === 'none' || st === 'hidden') continue;
      if (!best || w > best.w) best = { w, c: parseColor(cs[`border${side}Color`]) };
    }
    if (!best || !best.c || best.c.a <= 0) return { color: null, width: 0, raw: null };
    return { color: bg ? hex(over(best.c, bg)) : hex(best.c), width: round2(best.w), raw: best.c };
  };

  // ---------- semantics
  const text = (n) => (n ? (n.innerText ?? n.textContent ?? '').replace(/\s+/g, ' ').trim() : '');
  const implicitRole = (el) => {
    const tag = el.tagName.toLowerCase();
    switch (tag) {
      case 'a': return el.hasAttribute('href') ? 'link' : 'generic';
      case 'button': case 'summary': return 'button';
      case 'select': return el.multiple || el.size > 1 ? 'listbox' : 'combobox';
      case 'textarea': return 'textbox';
      case 'h1': case 'h2': case 'h3': case 'h4': case 'h5': case 'h6': return 'heading';
      case 'p': return 'paragraph';
      case 'li': return 'listitem';
      case 'img': return 'img';
      case 'nav': return 'navigation';
      case 'dialog': return 'dialog';
      case 'option': return 'option';
      case 'td': return 'cell';
      case 'th': return 'columnheader';
      case 'output': return 'status';
      case 'input': {
        const t = (el.getAttribute('type') || 'text').toLowerCase();
        if (['submit', 'button', 'reset', 'image'].includes(t)) return 'button';
        if (t === 'checkbox') return 'checkbox';
        if (t === 'radio') return 'radio';
        if (t === 'range') return 'slider';
        if (t === 'number') return 'spinbutton';
        if (t === 'search') return 'searchbox';
        return 'textbox';
      }
      default: return 'generic';
    }
  };
  const roleOf = (el) => {
    const explicit = (el.getAttribute('role') || '').trim().split(/\s+/)[0];
    return explicit || implicitRole(el);
  };
  // Accessible name and where it came from (accname 1.2 order, simplified): the
  // source lets checks tell a label-in-name mismatch (aria-label overriding the
  // visible text) from a placeholder-only field or an unnamed icon button.
  // Ids resolve in the element's own tree (document or shadow root).
  const byId = (el, id) => {
    const root = el.getRootNode();
    return (root && typeof root.getElementById === 'function' ? root.getElementById(id) : null) || document.getElementById(id);
  };
  // SVG has no innerText; its textContent includes <style> and <script>. Its name comes
  // from a <title> child only.
  const svgTitle = (el) => {
    const t = [...el.children].find((c) => c.tagName && c.tagName.toLowerCase() === 'title');
    return t ? t.textContent.replace(/\s+/g, ' ').trim() : '';
  };
  // Roles whose name comes from the author only, never from their content (ARIA 1.2
  // "Name From: author"): a role=textbox div's text is its value, not its name.
  const AUTHOR_ONLY = new Set(['textbox', 'searchbox', 'combobox', 'listbox', 'spinbutton', 'slider', 'progressbar', 'meter', 'scrollbar',
    'tree', 'treegrid', 'grid', 'table', 'menu', 'menubar', 'radiogroup', 'tablist', 'toolbar', 'dialog', 'alertdialog', 'img', 'group']);
  const accNameSrc = (el) => {
    const lb = el.getAttribute('aria-labelledby');
    if (lb) {
      const t = lb.split(/\s+/).map((id) => byId(el, id)).filter(Boolean).map(text).join(' ').trim();
      if (t) return [t, 'aria-labelledby'];
    }
    const al = (el.getAttribute('aria-label') || '').trim();
    if (al) return [al, 'aria-label'];
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (tag === 'img' || (tag === 'input' && type === 'image')) {
      const alt = (el.getAttribute('alt') || '').trim();
      if (alt) return [alt, 'alt'];
    }
    if (tag === 'input' && ['submit', 'button', 'reset'].includes(type)) {
      const v = (el.value || (type === 'submit' ? 'Submit' : type === 'reset' ? 'Reset' : '')).trim();
      if (v) return [v, 'value'];
    } else if (['input', 'select', 'textarea'].includes(tag)) {
      if (el.labels && el.labels.length) {
        const t = [...el.labels].map(text).join(' ').trim();
        if (t) return [t, 'label'];
      }
      // HTML-AAM order: title before placeholder.
      const ti = (el.getAttribute('title') || '').trim();
      if (ti) return [ti, 'title'];
      const ph = (el.getAttribute('placeholder') || '').trim();
      if (ph) return [ph, 'placeholder'];
    } else if (typeof SVGElement !== 'undefined' && el instanceof SVGElement) {
      const t = svgTitle(el);
      if (t) return [t, 'content'];
    } else if (!AUTHOR_ONLY.has((el.getAttribute('role') || '').trim().split(/\s+/)[0])) {
      const t = nameFromContent(el) || text(el);
      if (t) return [t.slice(0, 300), 'content'];
      const img = el.querySelector && el.querySelector('img[alt]');
      if (img && img.alt.trim()) return [img.alt.trim(), 'content'];
      const svgTitle = el.querySelector && el.querySelector('svg title');
      if (svgTitle && svgTitle.textContent.trim()) return [svgTitle.textContent.trim(), 'content'];
    }
    const title = (el.getAttribute('title') || '').trim();
    return title ? [title, 'title'] : ['', 'none'];
  };
  const accName = (el) => accNameSrc(el)[0];
  // Visually hidden (the "visually-hidden" pattern, display:none, visibility:hidden).
  const visuallyHidden = (n) => {
    const cs = style(n);
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.visibility === 'collapse') return true;
    if (/inset\(\s*50%/.test(cs.clipPath || '') || /rect\(\s*0(px)?,?\s*0(px)?,?\s*0(px)?,?\s*0(px)?\s*\)/.test(cs.clip || '')) return true;
    const r = n.getBoundingClientRect();
    return r.width <= 1 && r.height <= 1 && (cs.overflow === 'hidden' || cs.overflow === 'clip');
  };
  // ACT "visible inner text": text a sighted user sees inside the element.
  const visibleInnerText = (el) => {
    const out = [];
    let budget = 400;
    const walk = (n) => {
      for (const c of n.childNodes) {
        if (budget-- <= 0) return;
        if (c.nodeType === 3) out.push(c.nodeValue);
        else if (c.nodeType === 1 && !visuallyHidden(c) && c.tagName.toLowerCase() !== 'style' && c.tagName.toLowerCase() !== 'script') {
          // Inline boxes join their text ("A", "C", "T" reads "ACT"); block boxes and
          // <br> break words, as innerText does.
          const block = c.tagName.toLowerCase() === 'br' || !/^inline/.test(style(c).display || 'inline');
          if (block) out.push(' ');
          walk(c);
          if (block) out.push(' ');
        }
      }
    };
    walk(el);
    return out.join('').replace(/\s+/g, ' ').trim().slice(0, 300);
  };
  // Name from content (accname 1.2 step 2F, simplified): text, plus the names of
  // descendant images and labelled elements; hidden descendants contribute nothing.
  const nameFromContent = (el) => {
    const out = [];
    let budget = 400;
    const walk = (n) => {
      for (const c of n.childNodes) {
        if (budget-- <= 0) return;
        if (c.nodeType === 3) {
          out.push(c.nodeValue);
          continue;
        }
        if (c.nodeType !== 1) continue;
        const tag = c.tagName.toLowerCase();
        if (tag === 'style' || tag === 'script') continue;
        const cs = style(c);
        if (cs.display === 'none' || cs.visibility === 'hidden' || c.getAttribute('aria-hidden') === 'true') continue;
        const lb = c.getAttribute('aria-labelledby');
        const lbText = lb ? lb.split(/\s+/).map((id) => byId(c, id)).filter(Boolean).map(text).join(' ').trim() : '';
        const al = (c.getAttribute('aria-label') || '').trim();
        if (lbText) out.push(lbText);
        else if (al) out.push(al);
        else if (tag === 'img' || (tag === 'input' && (c.getAttribute('type') || '').toLowerCase() === 'image')) {
          out.push((c.getAttribute('alt') || '').trim() || (c.getAttribute('title') || '').trim());
        } else if (typeof SVGElement !== 'undefined' && c instanceof SVGElement) out.push(svgTitle(c) || (c.getAttribute('title') || ''));
        else {
          const before = out.length;
          walk(c);
          if (out.slice(before).join('').trim() === '' && c.getAttribute('title')) out.push(c.getAttribute('title').trim());
        }
      }
    };
    walk(el);
    return out.join(' ').replace(/\s+/g, ' ').trim();
  };
  const NATIVE_FOCUSABLE = new Set(['a', 'button', 'input', 'select', 'textarea', 'summary']);
  // Programmatic state a check can read without a screen reader (WCAG 4.1.2, 3.3.1).
  const a11yOf = (el) => {
    const tag = el.tagName.toLowerCase();
    const ids = (attr) => (el.getAttribute(attr) || '').split(/\s+/).filter((id) => id && byId(el, id));
    const tabAttr = el.getAttribute('tabindex');
    const native = NATIVE_FOCUSABLE.has(tag) && !(tag === 'a' && !el.hasAttribute('href'));
    let disabled = false;
    try {
      disabled = el.matches(':disabled');
    } catch (e) {
      disabled = false;
    }
    return {
      name_source: accNameSrc(el)[1],
      invalid: el.getAttribute('aria-invalid') === 'true',
      user_invalid: (() => {
        try {
          return el.matches(':user-invalid');
        } catch (e) {
          return false;
        }
      })(),
      described_by: ids('aria-describedby').slice(0, 8),
      visible_label: tag === 'textarea' ? '' : visibleInnerText(el),
      // Hidden from assistive technology (aria-hidden or inert on it or an ancestor).
      hidden: !!(el.closest && (el.closest('[aria-hidden="true"]') || el.closest('[inert]'))),
      // Rendered (not display:none, not visibility:hidden), even with a zero-size box: such
      // an element is still in the accessibility tree (AUT-20). Opacity does not count.
      rendered: (() => {
        if (typeof el.checkVisibility === 'function') return el.checkVisibility({ visibilityProperty: true });
        const cs = style(el);
        return cs.display !== 'none' && cs.visibility === 'visible' && el.getClientRects().length > 0;
      })(),
      // Visible text drawn by an icon font (ligatures such as "menu"): not a text label.
      icon_font: (() => {
        const ICON = /icon|material|awesome|symbol|glyph|fontello|ionicon|bootstrap-icons/i;
        const nodes = [el, ...el.querySelectorAll('span, i, em')].slice(0, 6);
        return nodes.some((n) => n.textContent && n.textContent.trim() && ICON.test(style(n).fontFamily || ''));
      })(),
      error_message: ids('aria-errormessage')[0] || null,
      required: el.required === true || el.getAttribute('aria-required') === 'true',
      focusable: !disabled && (tabAttr !== null ? parseInt(tabAttr, 10) >= 0 : native || el.isContentEditable),
      tabindex: tabAttr !== null && Number.isFinite(parseInt(tabAttr, 10)) ? parseInt(tabAttr, 10) : null,
    };
  };
  // Text cut off by its own box (XCTest textClipped; WCAG 1.4.4/1.4.12 symptoms).
  const clippedOf = (el, cs) => {
    const hide = (v) => v === 'hidden' || v === 'clip';
    let x = hide(cs.overflowX) && el.scrollWidth > el.clientWidth + 1;
    let y = hide(cs.overflowY) && el.scrollHeight > el.clientHeight + 1;
    let by = null;
    let ellipsis = cs.textOverflow === 'ellipsis';
    if (!x && !y) {
      // ACT 59br37: text cut by an ancestor that clips (a fixed-width chip or label),
      // within three levels. The text must be partly visible: a slide that is wholly
      // outside its carousel is not cut text. A scroll container is reachable.
      const r = el.getBoundingClientRect();
      for (let n = el.parentElement, i = 0; n && n.nodeType === 1 && i < 3 && n !== document.body; n = n.parentElement, i++) {
        const ncs = style(n);
        const ax = ncs.overflowX;
        const ay = ncs.overflowY;
        if (ax === 'auto' || ax === 'scroll' || ay === 'auto' || ay === 'scroll') break;
        if (!hide(ax) && !hide(ay)) continue;
        const a = n.getBoundingClientRect();
        const cutX = hide(ax) && (r.right > a.right + 1 || r.left < a.left - 1) && r.left < a.right && r.right > a.left;
        const cutY = hide(ay) && (r.bottom > a.bottom + 1 || r.top < a.top - 1) && r.top < a.bottom && r.bottom > a.top;
        if (cutX || cutY) {
          x = cutX;
          y = cutY;
          by = n;
          ellipsis = ellipsis || ncs.textOverflow === 'ellipsis';
          break;
        }
      }
      if (!x && !y) return null;
    }
    const clamp = cs.webkitLineClamp && cs.webkitLineClamp !== 'none';
    // ACT 59br37's exceptions, on the clipping box: sideways, one line that does not
    // wrap and ends in a marker (white-space nowrap, text-overflow other than clip);
    // vertically, a box one line high (used line-height >= its height, content box for
    // overflow-y clip) whose glyphs fit in it. Clipped this way the text is cut cleanly.
    const cb = by || el;
    const bcs = by ? style(by) : cs;
    // text-overflow draws its marker only in a block container (not a flex or grid box).
    const markerShown = bcs.textOverflow !== 'clip' && ['block', 'inline-block', 'list-item', 'flow-root', 'table-cell', 'table-caption'].includes(bcs.display);
    const exemptX = !x || (/^nowrap/.test(bcs.whiteSpace) && markerShown);
    const fontPx = parseFloat(cs.fontSize) || 16;
    // A "normal" line height depends on the font (about 1.45 em for Korean fonts): take
    // the height of the text's first line box instead of assuming 1.2 em.
    let lineH = parseFloat(bcs.lineHeight);
    if (!(lineH > 0)) {
      lineH = 1.2 * fontPx;
      try {
        const rg = document.createRange();
        rg.selectNodeContents(el);
        const first = rg.getClientRects()[0];
        if (first && first.height > 0) lineH = first.height;
      } catch (e) { /* keep the estimate */ }
    }
    const boxH = bcs.overflowY === 'clip'
      ? cb.clientHeight - (parseFloat(bcs.paddingTop) || 0) - (parseFloat(bcs.paddingBottom) || 0)
      : cb.getBoundingClientRect().height;
    const exemptY = !y || (lineH >= boxH - 0.5 && fontPx <= boxH + 0.5);
    if (by && !markerShown) ellipsis = false; // declared but not drawn
    // Tickers and marquees clip by design: text that moves (CSS animation on the element
    // or a close ancestor, or <marquee>) is recorded as animated.
    let animated = false;
    for (let n = el, i = 0; n && n.nodeType === 1 && i < 4; n = n.parentElement, i++) {
      const ncs = style(n);
      if (n.tagName.toLowerCase() === 'marquee' || (ncs.animationName && ncs.animationName !== 'none')
        || (typeof n.getAnimations === 'function' && n.getAnimations().length)) {
        animated = true;
        break;
      }
    }
    return { x, y, ellipsis: ellipsis || !!clamp, line_clamp: !!clamp, animated, by: by ? (by.getAttribute('id') ? `#${by.getAttribute('id')}` : by.tagName.toLowerCase()) : null,
      act: exemptX && exemptY ? 'passed' : 'failed' };
  };
  const visibleText = (el) => {
    const tag = el.tagName.toLowerCase();
    if (tag === 'input') {
      const type = (el.getAttribute('type') || '').toLowerCase();
      return ['submit', 'button', 'reset'].includes(type) ? (el.value || '').trim() : '';
    }
    if (tag === 'textarea') return '';
    if (tag === 'select') {
      const opt = el.selectedOptions && el.selectedOptions[0];
      return opt ? text(opt) : '';
    }
    return text(el).slice(0, 300);
  };
  const hasDirectText = (el) => {
    for (const n of el.childNodes) {
      if (n.nodeType === 3 && n.nodeValue.trim()) return true;
    }
    return false;
  };

  // Canvas bounds describe glyphs in a matching CSS font, not DOM raster pixels
  // or line layout. Keep actual displayed text separate from fixed font probes.
  let fontContext = null;
  const fontProbeCache = new Map();
  const privateFontNodes = new Set();
  const fontProperties = ['fontFamily', 'fontSize', 'fontWeight', 'fontStyle', 'fontStretch',
    'fontVariant', 'fontFeatureSettings', 'fontVariationSettings', 'fontOpticalSizing',
    'fontKerning', 'letterSpacing', 'wordSpacing', 'textTransform', 'direction', 'writingMode'];
  const fontMetricsFor = (el, displayedText) => {
    const gaps = new Set(['dom_ink_unmeasured', 'font_fallback_unverified']);
    const result = { method: 'canvas-textmetrics-v1', unit: 'css_px', status: 'unavailable',
      body_height_px: null, probes: null, limitations: [] };
    const finish = () => ({ ...result, limitations: [...gaps].sort() });
    const privateControl = (n) => ['input', 'textarea', 'select'].includes(n.tagName?.toLowerCase()) || n.isContentEditable
      || ['textbox', 'searchbox', 'combobox', 'listbox', 'spinbutton'].includes(n.getAttribute('role'))
      || n.hasAttribute('data-sensitive') || n.hasAttribute('data-private') || privateFontNodes.has(n);
    if ((args.privateValues || []).some((value) => typeof value === 'string' && value && displayedText.includes(value))) {
      gaps.add('private_control'); return finish();
    }
    for (let n = el, count = 0; n; n = parentOf(n)) {
      if (++count > 64) { gaps.add('node_cap'); return finish(); }
      if (privateControl(n)) { gaps.add('private_control'); return finish(); }
      const cs = style(n);
      if ((cs.transform && cs.transform !== 'none') || ['scale', 'rotate', 'translate'].some((k) => cs[k] && cs[k] !== 'none')
        || (cs.zoom && Number(cs.zoom) !== 1)) { gaps.add('transform_or_zoom'); return finish(); }
    }
    if (vvp && Math.abs(vvp.scale - 1) > 0.001) { gaps.add('transform_or_zoom'); return finish(); }
    const cs = style(el);
    if (cs.writingMode !== 'horizontal-tb') { gaps.add('vertical_text'); return finish(); }
    const font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    const signature = fontProperties.map((k) => cs[k]).join('|');
    const chunks = [];
    let visited = 0;
    let characters = 0;
    const walk = (n) => {
      if (++visited > 64) { gaps.add('node_cap'); return; }
      if (n.nodeType === 3) {
        const value = n.nodeValue || '';
        characters += value.length;
        if (characters > 300) { gaps.add('text_cap'); return; }
        chunks.push(value);
        return;
      }
      if (n.nodeType !== 1) return;
      const tag = n.tagName.toLowerCase();
      if (privateControl(n)) { gaps.add('private_control'); return; }
      if (['script', 'style', 'template', 'noscript'].includes(tag) || visuallyHidden(n)) return;
      if (!(n instanceof HTMLElement) || n.shadowRoot) { gaps.add('unsupported_text'); return; }
      const ns = style(n);
      if (fontProperties.map((k) => ns[k]).join('|') !== signature) { gaps.add('mixed_font_or_style'); return; }
      if (ns.textTransform !== 'none' || !['normal', '0px'].includes(ns.letterSpacing) || !['normal', '0px'].includes(ns.wordSpacing)
        || ns.fontVariant !== 'normal' || ns.fontFeatureSettings !== 'normal' || ns.fontVariationSettings !== 'normal'
        || !['normal', '100%'].includes(ns.fontStretch) || (ns.fontSizeAdjust && ns.fontSizeAdjust !== 'none')
        || (ns.textShadow && ns.textShadow !== 'none') || parseFloat(ns.webkitTextStrokeWidth) > 0
        || ns.transform !== 'none' || ['scale', 'rotate', 'translate'].some((k) => ns[k] && ns[k] !== 'none')
        || (ns.zoom && Number(ns.zoom) !== 1)) gaps.add('unsupported_text');
      for (const pseudo of ['::before', '::after']) {
        const content = getComputedStyle(n, pseudo).content;
        if (content && !['none', 'normal', '""'].includes(content)) gaps.add('pseudo_text');
      }
      if (tag === 'br' || (n !== el && !/^inline/.test(ns.display))) chunks.push(' ');
      for (const child of n.childNodes) {
        if (visited >= 64 || characters > 300) { gaps.add(visited >= 64 ? 'node_cap' : 'text_cap'); break; }
        walk(child);
      }
      if (n !== el && !/^inline/.test(ns.display)) chunks.push(' ');
    };
    walk(el);
    const measuredText = chunks.join('').replace(/\s+/g, ' ').trim();
    if (!measuredText || measuredText !== displayedText) gaps.add('text_mismatch');
    if (gaps.size > 2) return finish();
    try {
      if (!document.fonts || document.fonts.status !== 'loaded' || !document.fonts.check(font, measuredText)) {
        gaps.add('font_not_loaded'); return finish();
      }
      if (!fontContext) fontContext = document.createElement('canvas').getContext('2d');
      if (!fontContext || !CSS.supports('font', font)) { gaps.add('canvas_unavailable'); return finish(); }
      fontContext.font = font;
      fontContext.textBaseline = 'alphabetic';
      fontContext.direction = cs.direction;
      fontContext.fontKerning = cs.fontKerning;
      const height = (value) => {
        const m = fontContext.measureText(value);
        const h = m.actualBoundingBoxAscent + m.actualBoundingBoxDescent;
        if (!Number.isFinite(h) || h <= 0 || h > 10000) throw new Error('unsupported text bounds');
        return h;
      };
      let probes = fontProbeCache.get(signature);
      if (!probes) {
        probes = { cap_H_px: height('H'), x_height_px: height('x'), body_Hg_px: height('Hg'), hangul_px: height('한') };
        fontProbeCache.set(signature, probes);
      }
      result.body_height_px = height(measuredText);
      result.probes = probes;
      result.status = 'matched_font';
    } catch (e) { gaps.add('canvas_unavailable'); }
    return finish();
  };

  // ---------- selectors
  const cssStr = (v) => String(v).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  const uniqueSelector = (el) => {
    const root = el.getRootNode();
    const q = (s) => {
      try {
        return root.querySelectorAll(s);
      } catch (e) {
        return [];
      }
    };
    const only = (s) => {
      const r = q(s);
      return r.length === 1 && r[0] === el;
    };
    const tag = el.tagName.toLowerCase();
    if (el.id) {
      const s = `#${CSS.escape(el.id)}`;
      if (only(s)) return s;
    }
    for (const attr of ['data-testid', 'data-test', 'data-qa', 'data-ergo-id', 'name', 'aria-label']) {
      const v = el.getAttribute(attr);
      if (v && v.length <= 80) {
        const s = `${tag}[${attr}="${cssStr(v)}"]`;
        if (only(s)) return s;
      }
    }
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1) {
      if (cur !== el && cur.id && q(`#${CSS.escape(cur.id)}`).length === 1) {
        parts.unshift(`#${CSS.escape(cur.id)}`);
        if (only(parts.join(' > '))) break;
        parts.shift();
      }
      let part = cur.tagName.toLowerCase();
      const parent = cur.parentElement;
      if (parent) {
        const same = [...parent.children].filter((c) => c.tagName === cur.tagName);
        if (same.length > 1) part += `:nth-of-type(${same.indexOf(cur) + 1})`;
      }
      parts.unshift(part);
      const s = parts.join(' > ');
      if (only(s)) return s;
      cur = parent;
    }
    return parts.join(' > ');
  };

  // ---------- candidates
  const INTERACTIVE = 'a, button, input:not([type="hidden"]), select, textarea, summary, canvas, '
    + '[role="button"], [role="link"], [role="tab"], [role="checkbox"], [role="radio"], [role="switch"], '
    + '[role="menuitem"], [role="slider"], [role="textbox"], [role="searchbox"], [role="combobox"], [role="listbox"], '
    + '[role="spinbutton"], [role="option"], [role="menuitemcheckbox"], [role="menuitemradio"], [role="treeitem"], '
    + '[role="gridcell"][tabindex], [onclick], [contenteditable=""], [contenteditable="true"]';
  const isInteractive = (el) => {
    try {
      if (el.matches(INTERACTIVE)) return true;
    } catch (e) {
      return false;
    }
    return el.hasAttribute('tabindex') && el.tabIndex >= 0;
  };
  const ALWAYS_TEXT = new Set(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'label', 'legend', 'figcaption', 'caption']);
  const DIRECT_TEXT = new Set(['span', 'div', 'small', 'strong', 'em', 'b', 'i', 'td', 'th', 'dt', 'dd', 'blockquote', 'output', 'pre', 'code', 'section', 'article', 'header', 'footer', 'main', 'aside']);

  const all = [];
  const walk = (root) => {
    for (const el of root.querySelectorAll('*')) {
      all.push(el);
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  };
  walk(document);
  for (const root of [document, ...all.map((n) => n.shadowRoot).filter(Boolean)]) {
    for (const selector of args.redactSelectors || []) {
      try { for (const node of root.querySelectorAll(selector)) privateFontNodes.add(node); } catch (e) { /* no valid selector */ }
    }
  }
  const order = new Map(all.map((el, i) => [el, i]));

  const roleMap = new Map();
  const addRole = (el, role) => {
    if (!known.has(role)) {
      unknownRoles.add(role);
      return;
    }
    if (!roleMap.has(el)) roleMap.set(el, new Set());
    roleMap.get(el).add(role);
  };
  for (const g of args.groups || []) {
    for (const h of g.handles || []) if (h && h.nodeType === 1) addRole(h, g.role);
  }
  for (const el of all) {
    const v = el.getAttribute('data-ergo-role');
    if (v) for (const r of v.split(/[\s,]+/).filter(Boolean)) addRole(el, r);
  }

  const geometry = new Map();
  const geo = (el) => {
    let g = geometry.get(el);
    if (g) return g;
    const r = el.getBoundingClientRect();
    let vis = r.width > 0 && r.height > 0;
    if (vis) {
      if (typeof el.checkVisibility === 'function') {
        vis = el.checkVisibility({ opacityProperty: true, visibilityProperty: true });
      } else {
        const cs = style(el);
        vis = cs.display !== 'none' && cs.visibility === 'visible' && parseFloat(cs.opacity) > 0;
      }
    }
    const inVp = r.width > 0 && r.height > 0 && r.right > VX0 && r.bottom > VY0 && r.left < VX1 && r.top < VY1;
    g = { r, vis, inVp };
    geometry.set(el, g);
    return g;
  };

  // Gaze uses the viewport/overflow intersection, while target-size and reach
  // retain the authored bounding box. Non-rectangular clipping stays unknown.
  const visibleBoxOf = (el) => {
    const r = geo(el).r;
    let x0 = Math.max(VX0, r.left), y0 = Math.max(VY0, r.top);
    let x1 = Math.min(VX1, r.right), y1 = Math.min(VY1, r.bottom);
    let clipped = false;
    for (let p = el; p; p = p.assignedSlot || parentOf(p)) {
      const cs = style(p);
      if ((cs.clipPath && cs.clipPath !== 'none') || (cs.clip && cs.clip !== 'auto')
        || (cs.maskImage && cs.maskImage !== 'none')
        // Individual rotate (including axis/3D forms) is separate from transform.
        || (cs.rotate && cs.rotate !== 'none')) return { visible_box: null, visible_geometry: 'unsupported' };
      if (cs.transform && cs.transform !== 'none') {
        const m = new DOMMatrixReadOnly(cs.transform);
        if (!m.is2D || Math.abs(m.b) > 1e-6 || Math.abs(m.c) > 1e-6) return { visible_box: null, visible_geometry: 'unsupported' };
      }
      if (p === el) continue; // an element's own overflow clips its children
      const clipX = ['hidden', 'clip', 'auto', 'scroll'].includes(cs.overflowX);
      const clipY = ['hidden', 'clip', 'auto', 'scroll'].includes(cs.overflowY);
      if (!clipX && !clipY) continue;
      const pr = geo(p).r;
      if (!p.offsetWidth || !p.offsetHeight) return { visible_box: null, visible_geometry: 'unsupported' };
      const sx = pr.width / p.offsetWidth, sy = pr.height / p.offsetHeight;
      const left = pr.left + p.clientLeft * sx, top = pr.top + p.clientTop * sy;
      const right = left + p.clientWidth * sx, bottom = top + p.clientHeight * sy;
      const old = [x0, y0, x1, y1];
      if (clipX) { x0 = Math.max(x0, left); x1 = Math.min(x1, right); }
      if (clipY) { y0 = Math.max(y0, top); y1 = Math.min(y1, bottom); }
      if (old.some((v, i) => v !== [x0, y0, x1, y1][i])) clipped = true;
    }
    if (x1 <= x0 || y1 <= y0) return { visible_box: null, visible_geometry: 'empty' };
    return { visible_box: { x: round2(x0), y: round2(y0), w: round2(x1 - x0), h: round2(y1 - y0) },
      visible_geometry: clipped ? 'ancestor_clipped' : 'measured' };
  };

  // Open modal layers: <dialog> opened with showModal() or a visible [aria-modal="true"].
  const modals = all.filter((el) => {
    try {
      if (el.matches(':modal')) return true;
    } catch (e) { /* :modal unsupported */ }
    if (el.getAttribute('aria-modal') !== 'true') return false;
    const g = geo(el);
    return g.vis && g.inVp;
  });
  const inertByModal = (el) => modals.length > 0 && !modals.some((m) => m === el || m.contains(el) || el.contains(m));
  // Fraction of sample points inside the visible box where another element is on top
  // (not the element, a descendant or an ancestor): a sheet, scrim or overlay.
  const occlusion = (el, r) => {
    // Hit testing cannot see elements that ignore pointer events (HUD and subtitle
    // overlays): elementFromPoint returns what lies BELOW them, so their occlusion is unknown.
    if (style(el).pointerEvents === 'none') return { fraction: null, by: null };
    const x0 = Math.max(VX0, r.left), x1 = Math.min(VX1, r.right), y0 = Math.max(VY0, r.top), y1 = Math.min(VY1, r.bottom);
    if (x1 - x0 < 1 || y1 - y0 < 1) return { fraction: null, by: null };
    const pts = [[0.5, 0.5], [0.25, 0.25], [0.75, 0.25], [0.25, 0.75], [0.75, 0.75]];
    let covered = 0;
    let by = null;
    for (const [fx, fy] of pts) {
      let top = null;
      try {
        top = document.elementFromPoint(x0 + (x1 - x0) * fx, y0 + (y1 - y0) * fy);
      } catch (e) {
        top = null;
      }
      if (!top || top === el || el.contains(top) || top.contains(el)) continue;
      // Hit testing also returns transparent layers (stretched-link ::after, click
      // catchers, input layers). Only a layer that paints, or a modal, hides the element.
      if (!paintsOver(top, el)) continue;
      covered += 1;
      if (!by) by = top;
    }
    return { fraction: covered / pts.length, by };
  };
  const paintsOver = (top, el) => {
    for (let n = top; n && !n.contains(el); n = parentOf(n)) {
      if (n.nodeType !== 1) continue;
      const tag = n.tagName.toLowerCase();
      const cs = style(n);
      if ((parseFloat(cs.opacity) || 0) <= 0.01 || cs.visibility !== 'visible') continue;
      if (tag === 'dialog' || n.getAttribute('aria-modal') === 'true') return true;
      if (MEDIA.has(tag)) return true;
      if (cs.backgroundImage && cs.backgroundImage !== 'none') return true;
      const bg = parseColor(cs.backgroundColor);
      if (bg && bg.a > 0.05) return true;
    }
    return false;
  };

  // Bounded solid-paint evidence, not a general rendering model. CSS `color` is
  // included only when a text node actually occupies a rendered glyph box.
  const paintFor = (el) => {
    const parts = [];
    const gaps = new Set();
    if (!geo(el).vis) return { source: 'dom-solid-v1', parts, gaps: [], decorative: false };
    const graphic = ['switch', 'slider', 'checkbox', 'radio', 'status', 'alert'].includes(roleOf(el))
      || [...(roleMap.get(el) || [])].some((r) => ['status', 'error_message', 'critical_message'].includes(r));
    if (!isInteractive(el) && el.closest('[aria-hidden="true"], [role="presentation"], [role="none"]')) {
      return { source: 'dom-solid-v1', parts, gaps: [], decorative: true };
    }
    const symbolOnly = /^[\s×✕✗✓✔+−\-→←↑↓⋯…☰]*$/.test(visibleText(el));
    const scanChildren = graphic || (isInteractive(el) && (!visibleText(el) || symbolOnly || a11yOf(el).icon_font));
    let visited = 0;
    const add = (node, key, kind, color, background, shape = null) => {
      if (parts.length >= 16) { gaps.add('part_cap'); return; }
      const r = geo(node).r;
      if (!color || !background) { gaps.add('unknown_background'); return; }
      parts.push({ key, kind, color: hex(color), background: hex(background), shape,
        box: { x: round2(r.left), y: round2(r.top), w: round2(r.width), h: round2(r.height) } });
    };
    const walkPaint = (node, key) => {
      if (++visited > 64) { gaps.add('node_cap'); return; }
      if (node !== el && isInteractive(node)) return; // another control owns its paint
      if (!geo(node).vis) return;
      const cs = style(node);
      const tag = node.tagName.toLowerCase();
      if (['style', 'script', 'title', 'desc', 'defs'].includes(tag)) return;
      const r = geo(node).r;
      for (let p = parentOf(node); p; p = parentOf(p)) {
        const ps = style(p), pr = geo(p).r;
        const clipX = ['hidden', 'clip'].includes(ps.overflowX), clipY = ['hidden', 'clip'].includes(ps.overflowY);
        if ((clipX && (r.right <= pr.left || r.left >= pr.right)) || (clipY && (r.bottom <= pr.top || r.top >= pr.bottom))) return;
        if ((clipX && (r.left < pr.left || r.right > pr.right)) || (clipY && (r.top < pr.top || r.bottom > pr.bottom))) {
          gaps.add('clipped_paint'); return;
        }
      }
      const cover = geo(node).inVp ? occlusion(node, r).fraction : null;
      if (cover === 1) return;
      if (cover > 0) { gaps.add('occluded_paint'); return; }
      if (node.shadowRoot) gaps.add('shadow_paint');
      for (const pseudo of ['::before', '::after']) {
        const ps = getComputedStyle(node, pseudo);
        if (ps.display !== 'none' && ps.visibility === 'visible' && ps.content && !['none', 'normal'].includes(ps.content)) gaps.add('pseudo_paint');
      }
      for (let p = node; p; p = parentOf(p)) {
        const ps = style(p);
        if ((ps.filter && ps.filter !== 'none') || (ps.mixBlendMode && ps.mixBlendMode !== 'normal')
          || (ps.maskImage && ps.maskImage !== 'none') || (ps.clipPath && ps.clipPath !== 'none')) {
          gaps.add('unsupported_effect'); return;
        }
      }
      if (node === el && ['input', 'select'].includes(tag) && cs.appearance !== 'none'
        && (tag === 'select' || ['checkbox', 'radio', 'range', 'color', 'file'].includes(node.type))) {
        gaps.add('native_appearance'); return;
      }
      const svgShape = node instanceof SVGElement && ['rect', 'circle', 'ellipse', 'path', 'polygon', 'polyline', 'line'].includes(tag);
      const colors = colorsFor(node, geo(node).r, cs, node instanceof SVGElement);
      if (svgShape) {
        const attributes = { rect: ['x', 'y', 'width', 'height', 'rx', 'ry'], circle: ['cx', 'cy', 'r'],
          ellipse: ['cx', 'cy', 'rx', 'ry'], line: ['x1', 'y1', 'x2', 'y2'], path: ['d'], polygon: ['points'], polyline: ['points'] }[tag];
        const geometry = [];
        let validGeometry = true;
        for (const attr of attributes) {
          const value = (node.getAttribute(attr) || '').trim();
          if (attr === 'd' || attr === 'points') {
            const allowed = attr === 'd' ? /^[MmLlHhVvCcSsQqTtAaZzEe\d+.,\s-]+$/ : /^[Ee\d+.,\s-]+$/;
            if (!value || value.length > 400 || !allowed.test(value)) { validGeometry = false; break; }
            const numbers = value.match(/[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?/g) || [];
            if (!numbers.length || numbers.some((v) => !Number.isFinite(Number(v)) || Math.abs(Number(v)) > 1e6)) { validGeometry = false; break; }
            if (attr === 'points' && (numbers.length % 2 || numbers.length < (tag === 'polygon' ? 6 : 4))) { validGeometry = false; break; }
            if (attr === 'd') {
              const tokens = value.match(/[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?/g) || [];
              const arity = { m: 2, l: 2, h: 1, v: 1, c: 6, s: 4, q: 4, t: 2, a: 7, z: 0 };
              let command = null, count = 0;
              validGeometry = /^[Mm]/.test(tokens[0] || '') && value.replace(/[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?/g, '').replace(/[\s,]/g, '') === '';
              for (const token of tokens) {
                if (token.toLowerCase() in arity) {
                  if (command && arity[command] && (!count || count % arity[command])) validGeometry = false;
                  command = token.toLowerCase(); count = 0;
                } else {
                  if (!command || !arity[command] || (command === 'a' && [3, 4].includes(count % 7) && ![0, 1].includes(Number(token)))) validGeometry = false;
                  count++;
                }
              }
              if (command && arity[command] && (!count || count % arity[command])) validGeometry = false;
              if (!validGeometry) break;
            }
            geometry.push(value.replace(/[\s,]+/g, ' '));
          } else {
            const numeric = value ? Number(value) : 0;
            if ((value && !/^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$/.test(value)) || !Number.isFinite(numeric) || Math.abs(numeric) > 1e6
              || (['width', 'height', 'r', 'rx', 'ry'].includes(attr) && numeric < 0)) { validGeometry = false; break; }
            geometry.push(String(numeric));
          }
        }
        const signature = [tag, ...geometry].join('|');
        if (!validGeometry || signature.length > 512 || node.closest('svg')?.querySelector('use, image, foreignObject')) {
          gaps.add('unsupported_svg'); return;
        }
        for (const channel of ['fill', 'stroke']) {
          if (cs[channel] === 'none' || (channel === 'stroke' && !(parseFloat(cs.strokeWidth) > 0))) continue;
          if (!cs[channel] || /url\(/.test(cs[channel])) { gaps.add('unsupported_svg'); continue; }
          const parsed = parseColor(cs[channel]);
          if (!parsed || parsed.a <= 0) continue;
          const raw = { ...parsed };
          raw.a *= parseFloat(cs[channel === 'fill' ? 'fillOpacity' : 'strokeOpacity']);
          if (raw.a > 0) add(node, `${key}:${channel}`, 'graphic', colors?.composite(raw), colors?.bg, signature);
        }
      } else if (!(node instanceof SVGElement)) {
        const rawBg = parseColor(cs.backgroundColor);
        const hasText = hasDirectText(node);
        if (cs.backgroundImage && cs.backgroundImage !== 'none') gaps.add('unknown_background');
        // Label wrappers are not state-indicator parts. Their own text is extracted
        // separately; textless track/thumb boxes supply the graphical channels.
        if (node === el || !hasText) {
          if (rawBg && rawBg.a > 0) add(node, `${key}:fill`, 'boundary', colors?.bg, colors?.container);
          const border = borderFor(cs, null);
          if (border.raw) add(node, `${key}:border`, 'boundary', colors?.composite(border.raw), colors?.container);
        }
        if (hasText && parseFloat(cs.fontSize) > 0 && (parseColor(cs.color)?.a || 0) > 0) {
          let glyph = false;
          for (const child of node.childNodes) {
            if (child.nodeType !== 3 || !child.nodeValue.trim()) continue;
            const range = document.createRange(); range.selectNodeContents(child);
            if ([...range.getClientRects()].some((r) => r.width > 0 && r.height > 0)) { glyph = true; break; }
          }
          if (glyph) add(node, `${key}:text`, 'text', colors?.fg, colors?.bg);
        }
      } else if (tag !== 'svg' && !svgShape) gaps.add('unsupported_svg');
      if (!scanChildren) return;
      let i = 0;
      for (const child of node.children) {
        if (visited >= 64) { gaps.add('node_cap'); break; }
        walkPaint(child, `${key}/${i++}`);
      }
    };
    walkPaint(el, 'self');
    if (graphic && !parts.some((p) => p.kind !== 'text') && !gaps.size) gaps.add('no_graphic_paint');
    return { source: 'dom-solid-v1', parts, gaps: [...gaps].sort(), decorative: false };
  };

  const candidates = [];
  for (const el of all) {
    const tag = el.tagName.toLowerCase();
    if (['script', 'style', 'template', 'noscript', 'head', 'meta', 'link', 'title', 'html', 'body', 'br', 'option'].includes(tag)) continue;
    const tagged = roleMap.has(el);
    const interactive = isInteractive(el);
    const explicitRole = (el.getAttribute('role') || '').trim();
    const alertStatus = explicitRole === 'alert' || explicitRole === 'status';
    let group = -1;
    if (tagged) group = 0;
    else if (interactive) group = 1;
    else if (alertStatus) group = 2;
    else if ((ALWAYS_TEXT.has(tag) || DIRECT_TEXT.has(tag)) && hasDirectText(el)) {
      // Only elements that own a text node: a <li> whose text sits in a child button
      // would otherwise report the child's text with its own (inherited) font size.
      const host = el.parentElement ? el.parentElement.closest(INTERACTIVE) : null;
      if (host) continue; // text inside a control is reported through the control
      group = 3;
    }
    if (group < 0) continue;
    const g = geo(el);
    if (group === 3 && (!g.vis || !text(el))) continue;
    const visRank = g.vis && g.inVp ? 0 : (g.vis ? 1 : 2);
    candidates.push({ el, group, visRank, interactive, order: order.get(el) });
  }

  // Hotspots: page-provided (live) boxes win over scenario-declared ones.
  let pageHotspotError = null;
  const spots = new Map();
  const addSpot = (h, source) => {
    if (!h || typeof h !== 'object' || typeof h.id !== 'string' || !h.id || h.id.length > 128) return false;
    const b = h.box;
    if (!b || ![b.x, b.y, b.w, b.h].every((n) => typeof n === 'number' && Number.isFinite(n)) || b.w < 0 || b.h < 0) return false;
    const prev = spots.get(h.id);
    const roles = new Set(prev ? prev.roles : []);
    for (const r of Array.isArray(h.roles) ? h.roles : []) {
      if (typeof r === 'string') {
        if (known.has(r)) roles.add(r);
        else unknownRoles.add(r);
      }
    }
    spots.set(h.id, {
      id: h.id,
      name: typeof h.name === 'string' ? h.name.slice(0, 200) : (prev ? prev.name : h.id),
      box: { x: b.x, y: b.y, w: b.w, h: b.h },
      roles,
      visible: h.visible === false ? false : true,
      enabled: h.enabled === false ? false : true,
      origin: source,
    });
    return true;
  };
  for (const h of args.hotspots || []) addSpot(h, 'scenario');
  try {
    const api = window.__ergoqa__;
    if (api && typeof api.hotspots === 'function') {
      const list = api.hotspots();
      if (Array.isArray(list)) {
        const live = new Set();
        for (const h of list.slice(0, 200)) {
          if (!addSpot(h, 'page')) pageHotspotError = 'some page hotspots were malformed and skipped';
          else live.add(h.id);
        }
        // The page reports its live hotspots; a scenario fallback it does not list is not
        // on screen in this state (e.g. attack/jump on a menu screen).
        for (const s of spots.values()) if (s.origin === 'scenario' && !live.has(s.id)) s.visible = false;
      } else {
        pageHotspotError = 'window.__ergoqa__.hotspots() did not return an array';
      }
    }
  } catch (e) {
    pageHotspotError = `window.__ergoqa__.hotspots() threw: ${String(e && e.message || e).slice(0, 200)}`;
  }
  for (const [id, roles] of Object.entries(args.hotspotRoles || {})) {
    const s = spots.get(id);
    if (s) for (const r of roles) if (known.has(r)) s.roles.add(r);
  }

  candidates.sort((a, b) => a.group - b.group || a.visRank - b.visRank || a.order - b.order);
  const cap = Math.max(0, (args.cap || 400) - spots.size);
  const kept = candidates.slice(0, cap).sort((a, b) => a.order - b.order);

  const ids = new WeakMap();
  const elements = [];
  let n = 0;
  for (const c of kept) {
    const el = c.el;
    const id = `el-${++n}`;
    ids.set(el, id);
    const g = geo(el);
    const cs = style(el);
    const tag = el.tagName.toLowerCase();
    const colors = colorsFor(el, g.r, cs);
    const fgRaw = parseColor(cs.color);
    const isControl = ['input', 'select', 'textarea', 'button'].includes(tag)
      || ['button', 'textbox', 'combobox', 'checkbox', 'radio', 'switch', 'searchbox', 'slider'].includes(roleOf(el));
    const border = isControl ? borderFor(cs, colors ? colors.container || colors.bg : null) : { color: null, width: 0 };
    let cumOpacity = 1;
    for (let p = el; p; p = parentOf(p)) cumOpacity *= parseFloat(style(p).opacity);
    const disabled = (() => {
      try {
        return el.matches(':disabled') || el.getAttribute('aria-disabled') === 'true' || !!el.closest('[inert]');
      } catch (e) {
        return false;
      }
    })();
    const fw = parseInt(cs.fontWeight, 10);
    const fs = parseFloat(cs.fontSize);
    const displayedText = visibleText(el);
    elements.push({
      id,
      role: roleOf(el),
      name: accName(el).slice(0, 300),
      text: displayedText,
      tag,
      selector: uniqueSelector(el),
      dom_id: el.id ? String(el.id).slice(0, 120) : null,
      box: { x: round2(g.r.left), y: round2(g.r.top), w: round2(g.r.width), h: round2(g.r.height) },
      ...visibleBoxOf(el),
      interactive: c.interactive,
      visible: g.vis,
      enabled: !disabled,
      in_viewport: g.inVp,
      font_size_px: Number.isFinite(fs) ? round2(fs) : null,
      font_weight: Number.isFinite(fw) ? Math.max(1, Math.min(1000, fw)) : null,
      font_metrics: fontMetricsFor(el, displayedText),
      color_fg: colors ? hex(colors.fg) : hex(fgRaw),
      color_bg: colors ? hex(colors.bg) : null,
      container_bg: colors && colors.container ? hex(colors.container) : null,
      border_color: border.color,
      border_width_px: border.width,
      opacity: Math.round(cumOpacity * 1000) / 1000,
      paint: paintFor(el),
      // Associated <label> boxes accept the same click (HTML activation behaviour),
      // so they are part of the control's target (WCAG 2.5.8 "target").
      ...(() => {
        if (!el.labels || !el.labels.length) return {};
        const boxes = [];
        for (const lab of el.labels) {
          const lr = lab.getBoundingClientRect();
          if (lr.width > 0 && lr.height > 0) boxes.push({ x: round2(lr.left), y: round2(lr.top), w: round2(lr.width), h: round2(lr.height) });
        }
        return boxes.length ? { hit_boxes: boxes.slice(0, 4) } : {};
      })(),
      ...(() => {
        const o = g.vis && g.inVp ? occlusion(el, g.r) : { fraction: null, by: null };
        return {
          occluded_fraction: o.fraction,
          occluded_by: o.by ? uniqueSelector(o.by) : null,
          inert_by_modal: inertByModal(el),
        };
      })(),
      ...(c.interactive || ['input', 'select', 'textarea'].includes(tag) ? { a11y: a11yOf(el) } : {}),
      ...(() => {
        const clip = !c.interactive && hasDirectText(el) ? clippedOf(el, cs) : null;
        return clip ? { clipped: clip } : {};
      })(),
      roles: roleMap.has(el) ? [...roleMap.get(el)].sort() : [],
      // Ids of the nearest ancestors (grouping context such as a toolbar or chip row).
      ancestor_ids: (() => {
        const ids = [];
        for (let p = el.parentElement; p && ids.length < 3; p = p.parentElement) {
          if (p.id && p !== document.body && p !== document.documentElement) ids.push(p.id);
        }
        return ids;
      })(),
      source: 'dom',
    });
  }
  for (const s of spots.values()) {
    const b = s.box;
    const inVp = b.w > 0 && b.h > 0 && b.x + b.w > 0 && b.y + b.h > 0 && b.x < vw && b.y < vh;
    elements.push({
      id: `hs-${s.id.replace(/[^A-Za-z0-9._-]/g, '_')}`,
      role: 'hotspot',
      name: s.name || s.id,
      text: '',
      tag: 'hotspot',
      selector: `hotspot:${s.id}`,
      box: { x: round2(b.x), y: round2(b.y), w: round2(b.w), h: round2(b.h) },
      interactive: true,
      visible: s.visible,
      enabled: s.enabled,
      in_viewport: inVp,
      font_size_px: null,
      font_weight: null,
      color_fg: null,
      color_bg: null,
      border_color: null,
      roles: [...s.roles].sort(),
      source: 'manual',
      hotspot_origin: s.origin,
    });
  }
  state.ids = ids;
  state.hotspots = [...spots.values()].map((s) => ({ id: s.id, box: s.box, elementId: `hs-${s.id.replace(/[^A-Za-z0-9._-]/g, '_')}` }));

  let active = null;
  const ae = document.activeElement;
  if (ae && ae !== document.body && ae !== document.documentElement && ae.getBoundingClientRect) {
    const r = ae.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) active = { x: round2(r.left + r.width / 2), y: round2(r.top + r.height / 2) };
  }
  // Layers that take over the screen (FM-02): declared dialogs, and fixed or absolute
  // painted boxes covering at least 40 % of the viewport. Records whether keyboard
  // focus is inside each one; values are never read.
  let deep = document.activeElement;
  while (deep && deep.shadowRoot && deep.shadowRoot.activeElement) deep = deep.shadowRoot.activeElement;
  const focusOnBody = !deep || deep === document.body || deep === document.documentElement;
  const layers = [];
  const vpArea = Math.max(1, vw * vh);
  const painted = (n) => {
    const cs = style(n);
    const bg = cs.backgroundColor || '';
    const a = /rgba\(.*,\s*([\d.]+)\)/.exec(bg);
    return (bg && bg !== 'transparent' && !(a && parseFloat(a[1]) === 0)) || (cs.backgroundImage && cs.backgroundImage !== 'none');
  };
  for (const n of all) {
    if (layers.length >= 8) break;
    if (n === document.body || n === document.documentElement) continue;
    const role = (n.getAttribute('role') || '').trim();
    let modal = false;
    try {
      modal = n.matches(':modal');
    } catch (e) { /* unsupported */ }
    const declared = modal || n.getAttribute('aria-modal') === 'true' || role === 'dialog' || role === 'alertdialog'
      || (n.tagName.toLowerCase() === 'dialog' && n.open);
    let kind = null;
    const g = geo(n);
    if (!g.vis) continue;
    if (declared) kind = modal || n.getAttribute('aria-modal') === 'true' ? 'modal' : 'dialog';
    else {
      // Area first (cheap, from the cached box), then the computed style.
      const r = g.r;
      const w = Math.max(0, Math.min(r.right, VX1) - Math.max(r.left, VX0));
      const h = Math.max(0, Math.min(r.bottom, VY1) - Math.max(r.top, VY0));
      if ((w * h) / vpArea < 0.4) continue;
      const pos = style(n).position;
      if ((pos === 'fixed' || pos === 'absolute') && painted(n)) {
        // An overlay sits over content that is still rendered underneath; a screen that
        // replaced the previous one (display:none swaps) covers nothing.
        let over = 0;
        for (const c of candidates) {
          if (over >= 1) break;
          if (n.contains(c.el) || c.el.contains(n)) continue;
          const cg = geo(c.el);
          if (!cg.vis) continue;
          const cx = cg.r.left + cg.r.width / 2;
          const cy = cg.r.top + cg.r.height / 2;
          if (cx < r.left || cx > r.right || cy < r.top || cy > r.bottom || cx < VX0 || cy < VY0 || cx >= VX1 || cy >= VY1) continue;
          const top = document.elementFromPoint(cx, cy);
          if (top && n.contains(top)) over += 1;
        }
        if (over) kind = 'sheet';
      }
    }
    if (!kind) continue;
    if (layers.some((l) => l.node.contains(n))) continue; // keep the outermost
    for (let i = layers.length - 1; i >= 0; i--) if (n.contains(layers[i].node)) layers.splice(i, 1);
    layers.push({ node: n, kind });
  }
  // Containment in the flat tree (slotted content, dialogs inside shadow roots).
  const inFlat = (root, n) => {
    for (let x = n; x; x = x.assignedSlot || x.parentNode || x.host) if (x === root) return true;
    return false;
  };
  // A layer's overlay root: its outermost fixed ancestor below <body> that is not the
  // app shell (most content lies outside it), e.g. a portal holding a dialog container
  // that keeps focus on itself and the role=dialog paper inside it (MUI).
  const overlayRoot = (node) => {
    let root = node;
    for (let n = node.parentElement; n && n !== document.body && n !== document.documentElement; n = n.parentElement) {
      if (style(n).position === 'fixed') root = n;
    }
    if (root === node) return node;
    const inside = candidates.filter((c) => root.contains(c.el)).length;
    return inside <= candidates.length / 2 ? root : node;
  };
  // The next element Tab reaches from the focused one (document order, tabindex >= 0).
  let nextTab = null;
  if (!focusOnBody) {
    const tabbable = [...document.querySelectorAll('a[href], button, input, select, textarea, summary, [tabindex], [contenteditable=""], [contenteditable="true"]')]
      .filter((t) => t.tabIndex >= 0 && !t.disabled && t.getClientRects().length > 0 && !(t.closest && t.closest('[inert]')));
    nextTab = tabbable.find((t) => deep.compareDocumentPosition(t) & Node.DOCUMENT_POSITION_FOLLOWING && !deep.contains(t)) || null;
  }
  const layerOut = layers.map(({ node, kind }) => {
    const root = overlayRoot(node);
    return {
      selector: uniqueSelector(node), dom_id: node.id || null, kind,
      box: { x: round2(geo(node).r.left), y: round2(geo(node).r.top), w: round2(geo(node).r.width), h: round2(geo(node).r.height) },
      // Focus on the overlay root counts only when the root wraps the layer (a portal or
      // dialog container that focuses itself), not when it merely holds the trigger too.
      contains_focus: !focusOnBody && (inFlat(node, deep) || (root !== node && inFlat(root, deep) && inFlat(deep, node))),
      follows_focus: !!nextTab && inFlat(node, nextTab),
      overlay_root: root !== node ? uniqueSelector(root) : null,
    };
  });
  if (panned && (VX0 || VY0)) {
    // Report DOM geometry relative to the screen (hotspots keep their own coordinates).
    const shift = (b) => { if (b) { b.x = round2(b.x - VX0); b.y = round2(b.y - VY0); } };
    for (const e of elements) {
      if (e.source !== 'dom') continue;
      shift(e.box);
      shift(e.visible_box);
      for (const hb of e.hit_boxes || []) shift(hb);
      for (const p of e.paint?.parts || []) shift(p.box);
    }
    if (active) { active.x = round2(active.x - VX0); active.y = round2(active.y - VY0); }
    for (const l of layerOut) shift(l.box);
  }
  const se = document.scrollingElement || document.documentElement;
  return {
    elements,
    candidates: candidates.length + spots.size,
    truncated: candidates.length > cap,
    viewport: { w: vw, h: vh },
    scroll: { x: round2(window.scrollX), y: round2(window.scrollY), width: se ? se.scrollWidth : null, height: se ? se.scrollHeight : null },
    visual: vvp ? { offset_x: round2(vvp.offsetLeft), offset_y: round2(vvp.offsetTop), width: round2(vvp.width), height: round2(vvp.height), scale: round2(vvp.scale) } : null,
    active,
    focus: {
      on_body: focusOnBody, tag: focusOnBody ? null : deep.tagName.toLowerCase(), dom_id: focusOnBody ? null : (deep.id || null),
      expanded: !focusOnBody && deep.getAttribute('aria-expanded') === 'true',
      controls: focusOnBody ? [] : (deep.getAttribute('aria-controls') || '').split(/\s+/).filter(Boolean).slice(0, 8),
    },
    layers: layerOut,
    pageHotspotError,
    unknownRoles: [...unknownRoles],
  };
}

/**
 * Nearest extracted element id for a DOM element (walks up to ancestors, e.g. a
 * text match inside a button). `exact` is false when an ancestor supplied the id.
 */
export function idForElement(el, key) {
  const state = window[Symbol.for(key)];
  let interactive = false;
  try {
    interactive = el.matches('a, button, input, select, textarea, summary, canvas, [role], [onclick], [tabindex]');
  } catch (e) { /* ignore */ }
  if (!state || !state.ids) return { id: null, exact: false, interactive };
  for (let n = el; n; n = n.parentElement || (n.getRootNode && n.getRootNode() !== document ? n.getRootNode().host : null)) {
    const id = state.ids.get(n);
    if (id) return { id, exact: n === el, interactive };
  }
  return { id: null, exact: false, interactive };
}

/** Element id at a viewport point: hotspots first (last declared on top), then the DOM hit. */
export function idAtPoint(args) {
  const state = window[Symbol.for(args.key)];
  if (!state) return { id: null, hotspot: false };
  const spots = state.hotspots || [];
  for (let i = spots.length - 1; i >= 0; i--) {
    const b = spots[i].box;
    if (args.x >= b.x && args.x <= b.x + b.w && args.y >= b.y && args.y <= b.y + b.h) return { id: spots[i].elementId, hotspot: true };
  }
  // Points are screen (visual viewport) coordinates; hit testing takes layout ones.
  const vvp = window.visualViewport;
  const lx = args.x + (vvp && Math.abs(vvp.scale - 1) < 0.01 ? vvp.offsetLeft : 0);
  const ly = args.y + (vvp && Math.abs(vvp.scale - 1) < 0.01 ? vvp.offsetTop : 0);
  let n = document.elementFromPoint(lx, ly);
  while (n && n.shadowRoot) {
    const inner = n.shadowRoot.elementFromPoint(lx, ly);
    if (!inner || inner === n) break;
    n = inner;
  }
  for (; n; n = n.parentElement || (n.getRootNode && n.getRootNode() !== document ? n.getRootNode().host : null)) {
    const id = state.ids ? state.ids.get(n) : null;
    if (id) return { id, hotspot: false };
  }
  return { id: null, hotspot: false };
}

/**
 * What a click landed on (SM-08): the element (a handle, or the top-most element at
 * {x, y}), whether it or an ancestor within five levels is a control a keyboard or
 * screen reader can operate (native control, widget role, tabindex >= 0, a label with
 * a control, contenteditable), whether it contains one, and its ancestor ids.
 * Never reads values.
 */
export function controlOf(arg) {
  // Points are screen (visual viewport) coordinates; hit testing takes layout ones.
  const vvp = window.visualViewport;
  const lx = arg && arg.nodeType !== 1 ? arg.x + (vvp && Math.abs(vvp.scale - 1) < 0.01 ? vvp.offsetLeft : 0) : 0;
  const ly = arg && arg.nodeType !== 1 ? arg.y + (vvp && Math.abs(vvp.scale - 1) < 0.01 ? vvp.offsetTop : 0) : 0;
  let el = arg && arg.nodeType === 1 ? arg : (arg ? document.elementFromPoint(lx, ly) : null);
  while (el && el.shadowRoot && arg && arg.nodeType !== 1) {
    const inner = el.shadowRoot.elementFromPoint(lx, ly);
    if (!inner || inner === el) break;
    el = inner;
  }
  if (!el) return null;
  const NATIVE = ['button', 'input', 'select', 'textarea', 'summary', 'option', 'details', 'video', 'audio', 'iframe', 'canvas'];
  const WIDGET = ['button', 'link', 'checkbox', 'radio', 'switch', 'tab', 'menuitem', 'menuitemcheckbox', 'menuitemradio', 'option',
    'slider', 'spinbutton', 'textbox', 'searchbox', 'combobox', 'listbox', 'treeitem', 'gridcell', 'scrollbar'];
  const LANDMARK = ['body', 'main', 'nav', 'header', 'footer', 'aside', 'form'];
  // Flat-tree parent: through slots and out of shadow roots (web components).
  const up = (n) => n.assignedSlot || n.parentElement || (n.getRootNode && n.getRootNode() instanceof ShadowRoot ? n.getRootNode().host : null);
  // A native control the keyboard can reach: not type=hidden, rendered, not
  // visibility:hidden, not inert (opacity:0 or clipped inputs still take focus).
  const usable = (c) => !!c && !(c.tagName === 'INPUT' && (c.type || '').toLowerCase() === 'hidden') && c.getClientRects().length > 0
    && (typeof c.checkVisibility !== 'function' || c.checkVisibility({ visibilityProperty: true })) && !(c.closest && c.closest('[inert]'));
  const plain = (n) => {
    const tag = n.tagName.toLowerCase();
    if (NATIVE.includes(tag)) return usable(n);
    if (tag === 'a' && n.hasAttribute('href')) return true;
    if (tag === 'label') return !!n.control && usable(n.control);
    const role = (n.getAttribute('role') || '').trim().split(/\s+/)[0];
    if (WIDGET.includes(role)) return true;
    const t = n.getAttribute('tabindex');
    return (t !== null && parseInt(t, 10) >= 0) || n.isContentEditable;
  };
  // A web component is a control when it delegates focus or holds one in its open shadow tree.
  const isControl = (n) => plain(n) || (!!n.shadowRoot && (n.shadowRoot.delegatesFocus || [...n.shadowRoot.querySelectorAll('*')].slice(0, 200).some(plain)));
  const holds = (root) => [...root.querySelectorAll('*')].slice(0, 300).some(isControl);
  let control = false;
  for (let n = el, i = 0; n && n.nodeType === 1 && i < 5; n = up(n), i++) {
    if (isControl(n)) {
      control = true;
      break;
    }
  }
  // Links and buttons at any depth (a heading inside a large link card).
  for (let n = el; !control && n && n.nodeType === 1; n = up(n)) {
    const tag = n.tagName.toLowerCase();
    const role = (n.getAttribute('role') || '').trim().split(/\s+/)[0];
    if ((tag === 'a' && n.hasAttribute('href')) || tag === 'button' || tag === 'summary' || role === 'button' || role === 'link') control = true;
  }
  let contains = holds(el);
  // The child of `root` on the way up from `node`.
  const branch = (root, node) => {
    let b = node;
    while (b && up(b) !== root) b = up(b);
    return b;
  };
  const peers = (root) => {
    const cb = branch(root, el);
    if (!cb) return false;
    const rb = cb.getBoundingClientRect();
    const ac = rb.width * rb.height;
    return [...root.querySelectorAll('*')].slice(0, 300).filter(isControl).some((c) => {
      const b = branch(root, c);
      if (!b || b === cb || !isControl(b)) return false;
      const r = b.getBoundingClientRect();
      const ab = r.width * r.height;
      return ab > 0 && ac > 0 && ab < 3 * ac && ac < 3 * ab && Math.abs(r.height - rb.height) <= 0.5 * Math.max(r.height, rb.height);
    });
  };
  // A card whose own link or button the keyboard reaches: the click on its image or
  // price has a keyboard equivalent right there.
  let card = null;
  if (!control && !contains) {
    const r0 = el.getBoundingClientRect();
    const area0 = Math.max(48 * 48, r0.width * r0.height);
    for (let n = up(el), i = 0; n && n.nodeType === 1 && i < 8; n = up(n), i++) {
      const tag = n.tagName.toLowerCase();
      if (LANDMARK.includes(tag) || ['main', 'navigation', 'banner', 'contentinfo', 'complementary', 'form'].includes(n.getAttribute('role') || '')) break;
      const r = n.getBoundingClientRect();
      if (r.width * r.height > 4 * area0) break;
      if (holds(n)) {
        // Not a card when what was clicked looks operable on its own (a pointer cursor
        // the candidate card does not have), or when a control there is a peer item of
        // it (a chip row where one chip is a role-less div): another option, not the
        // card's own link.
        const own = getComputedStyle(el).cursor === 'pointer' && getComputedStyle(n).cursor !== 'pointer';
        // The card's own way in: a link, or its one control. A card whose only controls are
        // side actions (wishlist, add to cart) leaves its main click without a keyboard way.
        const ctrls = [...n.querySelectorAll('*')].slice(0, 300).filter(isControl);
        const link = ctrls.some((c) => (c.localName === 'a' && c.hasAttribute('href')) || (c.getAttribute('role') || '').split(/\s+/)[0] === 'link');
        if (!own && (link || ctrls.length === 1) && !peers(n)) card = n;
        break;
      }
    }
  }
  const ids = [];
  for (let n = el.parentElement; n && ids.length < 6; n = n.parentElement) if (n.id) ids.push(n.id);
  return {
    tag: el.tagName.toLowerCase(), role: (el.getAttribute('role') || '').trim() || null, dom_id: el.id || null, control,
    contains_control: contains || !!card, card_control: !!card, hidden: !!(el.closest && el.closest('[aria-hidden="true"],[inert]')),
    ancestor_ids: ids, text: (el.innerText || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 40),
  };
}

// Native boolean evidence reuses the protected-target rule the task-state
// sampler applies (inlined in armBinaryControl: evaluate() ships only the
// function body): a credential-like or explicitly protected control's state
// must not be recorded even when its label looks harmless.

/**
 * Arm native binary-control activation evidence for one action: resolve the
 * checkbox/radio input the action activates — the element itself, or the control
 * of an associated <label> (explicit `for` or nested; `label.control`, the same
 * label rule controlOf uses) within five flat-tree levels — snapshot its boolean
 * `checked` state, and timestamp the control's own trusted `input`/`change`
 * events together with the boolean observed at event time. Reads only
 * tag/type/id and the boolean: never text or field values. opts.redactSelectors
 * are the run's opted-out regions; a control or label inside one is not armed.
 * Returns a bounded descriptor, `{protected: true}` for a protected control,
 * or null when the target is no binary control. Self-contained: no module
 * references (evaluate() ships only this function's source).
 */
export function armBinaryControl(arg, keyArg) {
  const opts = keyArg && typeof keyArg === 'object' ? keyArg : { key: keyArg };
  const key = arg && arg.nodeType === 1 ? opts.key : arg && arg.key;
  const state = key ? window[Symbol.for(key)] : null;
  if (!state) return null;
  // Every new arm replaces the previous action's watch, including no-op and
  // protected targets. The helper stays inside this page-evaluated function.
  const disposeWatch = (w) => {
    w.closed = true;
    for (const timer of w.timers || []) clearTimeout(timer);
    try { w.el.removeEventListener('input', w.onInput, true); } catch (e) { /* element gone */ }
    try { w.el.removeEventListener('change', w.onChange, true); } catch (e) { /* element gone */ }
  };
  if (state.binaryWatch) disposeWatch(state.binaryWatch);
  state.binaryWatch = null;
  const now = () => performance.timeOrigin + performance.now();
  const vvp = window.visualViewport;
  let el = arg && arg.nodeType === 1 ? arg : null;
  if (!el && arg) {
    // Points are screen (visual viewport) coordinates; hit testing takes layout ones.
    const lx = arg.x + (vvp && Math.abs(vvp.scale - 1) < 0.01 ? vvp.offsetLeft : 0);
    const ly = arg.y + (vvp && Math.abs(vvp.scale - 1) < 0.01 ? vvp.offsetTop : 0);
    el = document.elementFromPoint(lx, ly);
    while (el && el.shadowRoot) {
      const inner = el.shadowRoot.elementFromPoint(lx, ly);
      if (!inner || inner === el) break;
      el = inner;
    }
  }
  if (!el) return null;
  const binary = (n) => !!n && n.tagName === 'INPUT' && ['checkbox', 'radio'].includes((n.type || '').toLowerCase());
  const up = (n) => n.assignedSlot || n.parentElement || (n.getRootNode && n.getRootNode() instanceof ShadowRoot ? n.getRootNode().host : null);
  let ctl = null;
  let via = null;
  let label = null;
  for (let n = el, i = 0; n && n.nodeType === 1 && i < 5 && !ctl; n = up(n), i++) {
    if (binary(n)) {
      ctl = n;
      via = 'direct';
    } else if (n.tagName === 'LABEL' && binary(n.control)) {
      ctl = n.control;
      label = n;
      via = n.contains(n.control) ? 'nested_label' : 'label_for';
    }
  }
  if (!ctl) return null;
  // Privacy boundary (fail closed), the protected-target rule the task-state
  // sampler already applies: a credential-like or opted-out control's boolean
  // state is never recorded, whatever harmless element the action targeted —
  // the baseline exposing a raw id does not authorize a new state leak.
  const credential = 'input[type="password"], input[type="hidden"], input[type="url"], [data-sensitive], [data-private], [autocomplete="username"], [autocomplete*="password"], [autocomplete="one-time-code"]';
  const sensitiveId = /(?:password|passwd|secret|token|credential|api.?key|authorization)/i;
  try {
    const inside = (node, selector) => {
      for (let n = node; n && n.nodeType === 1; n = up(n)) if (n.matches(selector)) return true;
      return false;
    };
    if (ctl.matches(credential) || inside(ctl, '[data-sensitive], [data-private]')
      || (label && inside(label, '[data-sensitive], [data-private]'))
      || sensitiveId.test(`${ctl.getAttribute('name') || ''} ${ctl.id}`)
      || (label && sensitiveId.test(`${label.getAttribute('name') || ''} ${label.id}`))) return { protected: true };
    for (const selector of opts.redactSelectors || (arg && arg.redactSelectors) || []) {
      if (inside(ctl, selector) || (label && inside(label, selector))) return { protected: true };
    }
  } catch (e) { return { protected: true }; }
  const watch = {
    el: ctl, via, type: (ctl.type || '').toLowerCase(), dom_id: ctl.id && ctl.id.length <= 200 ? ctl.id : null,
    before: !!ctl.checked, events: [], timers: new Set(), closed: false,
  };
  // Only browser-trusted events on the resolved control count, and each records
  // the boolean observed at event time: a handler that immediately restores the
  // old state must not lend its timestamp to a later untrusted change.
  const rec = (kind) => (e) => {
    if (!e || !e.isTrusted || e.target !== ctl || watch.closed || watch.events.length + watch.timers.size >= 64) return;
    const event = { kind, t: now(), checked: !!ctl.checked };
    // A native event's capture listener runs before page handlers. Confirm the
    // exact event-time state after dispatch completes; a synchronous restoration
    // (including a microtask) cannot lend its timestamp to a later property flip.
    const timer = setTimeout(() => {
      watch.timers.delete(timer);
      if (!watch.closed && ctl.checked === event.checked) watch.events.push(event);
    }, 0);
    watch.timers.add(timer);
  };
  watch.onInput = rec('input');
  watch.onChange = rec('change');
  try {
    ctl.addEventListener('input', watch.onInput, true);
    ctl.addEventListener('change', watch.onChange, true);
  } catch (e) { disposeWatch(watch); return null; }
  watch.dispose = () => disposeWatch(watch);
  state.binaryWatch = watch;
  return { via: watch.via, type: watch.type, dom_id: watch.dom_id, before: watch.before };
}

/**
 * Read and clear the watch armed by armBinaryControl: the boolean state after
 * the action, whether it truly changed and stayed changed (`stable`), and the
 * first trusted input/change event for the same control not earlier than
 * args.t0 (page-clock epoch ms) whose state-at-event both differs from the
 * armed state and matches the observed end state — the event that evidences
 * the reported transition. Other trusted events are not reported: their
 * timestamps must not be inherited by a later programmatic change.
 */
export async function readBinaryControl(args) {
  const state = window[Symbol.for(args.key)];
  const w = state && state.binaryWatch;
  if (!w) return null;
  if (w.timers.size) await new Promise((resolve) => setTimeout(resolve, 0));
  if (state.binaryWatch === w) state.binaryWatch = null;
  try { w.dispose(); } catch (e) { /* element gone */ }
  const after = !!w.el.checked;
  if (args.stable_ms > 0) await new Promise((resolve) => setTimeout(resolve, args.stable_ms));
  const settled = !!w.el.checked;
  const ev = w.events.find((e) => (args.t0 == null || e.t >= args.t0) && (args.t1 == null || e.t <= args.t1)
    && e.checked !== w.before && e.checked === after) || null;
  return {
    via: w.via, type: w.type, dom_id: w.dom_id,
    before: w.before, after, changed: after !== w.before, stable: settled === after,
    event: ev ? ev.kind : null, event_ms: ev ? ev.t : null,
  };
}

/** Drop a watch that a failed action left armed: listeners off, state cleared. */
export function disposeBinaryControl(args) {
  const state = window[Symbol.for(args.key)];
  const w = state && state.binaryWatch;
  if (!w) return false;
  state.binaryWatch = null;
  try { w.dispose(); } catch (e) { /* element gone */ }
  return true;
}

/** Is the top-most element at (x, y) the target element or inside it? */
export function hitTest(el, pt) {
  // Points are screen (visual viewport) coordinates; hit testing takes layout ones.
  const vvp = window.visualViewport;
  const lx = pt.x + (vvp && Math.abs(vvp.scale - 1) < 0.01 ? vvp.offsetLeft : 0);
  const ly = pt.y + (vvp && Math.abs(vvp.scale - 1) < 0.01 ? vvp.offsetTop : 0);
  let n = document.elementFromPoint(lx, ly);
  while (n && n.shadowRoot) {
    const inner = n.shadowRoot.elementFromPoint(lx, ly);
    if (!inner || inner === n) break;
    n = inner;
  }
  for (; n; n = n.parentElement || (n.getRootNode && n.getRootNode() !== document ? n.getRootNode().host : null)) {
    if (n === el) return true;
  }
  return false;
}
