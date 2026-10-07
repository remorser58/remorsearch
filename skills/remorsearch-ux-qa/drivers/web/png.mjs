// Minimal PNG decoder (8-bit grey/RGB/grey+alpha/RGBA, non-interlaced, filters
// 0-4) and per-frame luminance statistics for flash sampling and visual
// feedback detection. Uses node:zlib only.

import zlib from 'node:zlib';

const CHANNELS = { 0: 1, 2: 3, 4: 2, 6: 4 };
const MAX_PIXELS = 40_000_000;

function paeth(a, b, c) {
  const p = a + b - c;
  const pa = Math.abs(p - a);
  const pb = Math.abs(p - b);
  const pc = Math.abs(p - c);
  if (pa <= pb && pa <= pc) return a;
  if (pb <= pc) return b;
  return c;
}

/** Decode a PNG buffer into {width, height, channels, data (Uint8Array)}. */
export function decodePng(buf) {
  if (buf.length < 33 || buf.readUInt32BE(0) !== 0x89504e47 || buf.readUInt32BE(4) !== 0x0d0a1a0a) {
    throw new Error('not a PNG');
  }
  let pos = 8;
  let width = 0;
  let height = 0;
  let colorType = -1;
  const idat = [];
  while (pos + 8 <= buf.length) {
    const len = buf.readUInt32BE(pos);
    const type = buf.toString('latin1', pos + 4, pos + 8);
    const start = pos + 8;
    const end = start + len;
    if (end + 4 > buf.length) throw new Error('truncated PNG chunk');
    if (type === 'IHDR') {
      width = buf.readUInt32BE(start);
      height = buf.readUInt32BE(start + 4);
      const bitDepth = buf[start + 8];
      colorType = buf[start + 9];
      const interlace = buf[start + 12];
      if (bitDepth !== 8) throw new Error(`unsupported PNG bit depth ${bitDepth}`);
      if (!(colorType in CHANNELS)) throw new Error(`unsupported PNG color type ${colorType}`);
      if (interlace !== 0) throw new Error('interlaced PNG not supported');
      if (width <= 0 || height <= 0 || width * height > MAX_PIXELS) throw new Error('PNG dimensions out of range');
    } else if (type === 'IDAT') {
      idat.push(buf.subarray(start, end));
    } else if (type === 'IEND') {
      break;
    }
    pos = end + 4; // skip CRC
  }
  if (colorType < 0) throw new Error('PNG without IHDR');
  const channels = CHANNELS[colorType];
  const stride = width * channels;
  const raw = zlib.inflateSync(Buffer.concat(idat));
  if (raw.length < (stride + 1) * height) throw new Error('PNG image data too short');
  const out = new Uint8Array(stride * height);
  // One loop per row filter (flash frames are decoded many times a second).
  for (let y = 0; y < height; y++) {
    const filter = raw[y * (stride + 1)];
    const src = y * (stride + 1) + 1;
    const dst = y * stride;
    const prev = dst - stride;
    const first = y === 0;
    switch (filter) {
      case 0:
        out.set(raw.subarray(src, src + stride), dst);
        break;
      case 1:
        for (let x = 0; x < stride; x++) out[dst + x] = raw[src + x] + (x >= channels ? out[dst + x - channels] : 0);
        break;
      case 2:
        if (first) out.set(raw.subarray(src, src + stride), dst);
        else for (let x = 0; x < stride; x++) out[dst + x] = raw[src + x] + out[prev + x];
        break;
      case 3:
        for (let x = 0; x < stride; x++) {
          const a = x >= channels ? out[dst + x - channels] : 0;
          const b = first ? 0 : out[prev + x];
          out[dst + x] = raw[src + x] + ((a + b) >> 1);
        }
        break;
      case 4:
        for (let x = 0; x < stride; x++) {
          const a = x >= channels ? out[dst + x - channels] : 0;
          const b = first ? 0 : out[prev + x];
          const c = x >= channels && !first ? out[prev + x - channels] : 0;
          out[dst + x] = raw[src + x] + paeth(a, b, c);
        }
        break;
      default:
        throw new Error(`bad PNG filter ${filter}`);
    }
  }
  return { width, height, channels, data: out };
}

// sRGB 8-bit -> linear, and WCAG relative luminance.
const LIN = new Float64Array(256);
for (let i = 0; i < 256; i++) {
  const c = i / 255;
  LIN[i] = c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

/**
 * Reduce a decoded image to per-pixel relative luminance and opaque RGB (alpha
 * composited over white). Returns {width, height, lum: Float32Array, rgb: Uint8Array}.
 */
export function frameFromImage(img) {
  const { width, height, channels, data } = img;
  const n = width * height;
  const lum = new Float32Array(n);
  const rgb = new Uint8Array(n * 3);
  for (let i = 0; i < n; i++) {
    const o = i * channels;
    let r;
    let g;
    let b;
    let a = 255;
    if (channels >= 3) {
      r = data[o]; g = data[o + 1]; b = data[o + 2];
      if (channels === 4) a = data[o + 3];
    } else {
      r = g = b = data[o];
      if (channels === 2) a = data[o + 1];
    }
    if (a < 255) {
      const f = a / 255;
      r = Math.round(r * f + 255 * (1 - f));
      g = Math.round(g * f + 255 * (1 - f));
      b = Math.round(b * f + 255 * (1 - f));
    }
    rgb[i * 3] = r; rgb[i * 3 + 1] = g; rgb[i * 3 + 2] = b;
    lum[i] = 0.2126 * LIN[r] + 0.7152 * LIN[g] + 0.0722 * LIN[b];
  }
  return { width, height, lum, rgb };
}

export const FLASH_DELTA = 0.1; // WCAG 2.3.1: 10% of max relative luminance
export const FLASH_DARK_LIMIT = 0.8; // darker state must be below 0.80

/**
 * Frame statistics. `prev` (same size) enables change metrics:
 *  - changed_fraction: share of pixels whose luminance changed by >= 0.10
 *  - flash_fraction:   same, restricted to WCAG general-flash pairs (darker < 0.80)
 *  - red_fraction:     share of saturated-red pixels (R/(R+G+B) >= 0.8) in this frame
 */
export function frameStats(frame, prev) {
  const n = frame.lum.length;
  let sum = 0;
  let red = 0;
  for (let i = 0; i < n; i++) {
    sum += frame.lum[i];
    const r = frame.rgb[i * 3];
    const s = r + frame.rgb[i * 3 + 1] + frame.rgb[i * 3 + 2];
    if (s > 0 && r / s >= 0.8) red++;
  }
  const out = { mean_luminance: n ? sum / n : 0, changed_fraction: 0, flash_fraction: 0, red_fraction: n ? red / n : 0 };
  if (prev && prev.lum.length === n && n) {
    let changed = 0;
    let flash = 0;
    for (let i = 0; i < n; i++) {
      const a = frame.lum[i];
      const b = prev.lum[i];
      if (Math.abs(a - b) >= FLASH_DELTA) {
        changed++;
        if (Math.min(a, b) < FLASH_DARK_LIMIT) flash++;
      }
    }
    out.changed_fraction = changed / n;
    out.flash_fraction = flash / n;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Block grid for photosensitivity screening. WCAG 2.3.1 counts flashes per
// region (0.006 sr within any 10 degree field), so a local flash or two regions
// flashing in counter-phase must not be averaged away by the whole-viewport
// mean. Each flash sample records, per block: mean relative luminance and the
// share of saturated-red pixels (u8, base64), plus which blocks changed only
// because the page content moved (scrolling is motion, not flashing).
//
// Block size: at least 22 x 40 CSS px (>= 16 columns on a 360 px phone; 40 px
// is about two lines of body text, so text scrolling through a block barely
// changes its mean), enlarged on big viewports so a grid has <= ~820 blocks
// (run.json must stay under ergoqa's 8 MB input limit). The WCAG area threshold
// then spans >= ~13 blocks on every catalogued device at its typical distance.

export const BLOCK_MIN_W_CSS = 22;
export const BLOCK_MIN_H_CSS = 40;
export const BLOCK_MAX = 820;
// Saturated red (WCAG 2.2 red flash: R/(R+G+B) >= 0.8; WCAG 2.0 note: the
// change of (R-G-B)*320 must exceed 20), on linear R, G, B as in the relative
// luminance definition. The excess term keeps near-black pixels out.
export const RED_RATIO = 0.8;
export const RED_EXCESS = 20 / 320;
// A block's change is explained by motion when its mean luminance and red share
// match the previous frame shifted by the global motion within this tolerance.
export const MOTION_MATCH = 0.05;

/**
 * Grid over a downscaled frame (frameW x frameH px) of a viewport (CSS px).
 * Block b = row * cols + col covers frame px [xEdges[col], xEdges[col+1]) x
 * [yEdges[row], yEdges[row+1]) and viewport CSS px of size blockCss.
 */
export function makeBlockGrid(frameW, frameH, viewportW, viewportH) {
  let bw = BLOCK_MIN_W_CSS;
  let bh = BLOCK_MIN_H_CSS;
  const wanted = (viewportW / bw) * (viewportH / bh);
  if (wanted > BLOCK_MAX) {
    const s = Math.sqrt(wanted / BLOCK_MAX);
    bw *= s;
    bh *= s;
  }
  const cols = Math.max(1, Math.min(frameW, Math.round(viewportW / bw)));
  const rows = Math.max(1, Math.min(frameH, Math.round(viewportH / bh)));
  const xEdges = Int32Array.from({ length: cols + 1 }, (_, c) => Math.round((c * frameW) / cols));
  const yEdges = Int32Array.from({ length: rows + 1 }, (_, r) => Math.round((r * frameH) / rows));
  const colOf = new Int32Array(frameW);
  const rowOf = new Int32Array(frameH);
  for (let c = 0; c < cols; c++) for (let x = xEdges[c]; x < xEdges[c + 1]; x++) colOf[x] = c;
  for (let r = 0; r < rows; r++) for (let y = yEdges[r]; y < yEdges[r + 1]; y++) rowOf[y] = r;
  return {
    cols, rows, frameW, frameH, viewportW, viewportH, blockCss: [viewportW / cols, viewportH / rows], xEdges, yEdges, colOf, rowOf,
  };
}

/** Per-pixel saturated-red flags (cached on the frame). */
function redMask(frame) {
  if (!frame.red) {
    const n = frame.lum.length;
    const m = new Uint8Array(n);
    const rgb = frame.rgb;
    for (let i = 0; i < n; i++) {
      const r = LIN[rgb[i * 3]];
      const g = LIN[rgb[i * 3 + 1]];
      const b = LIN[rgb[i * 3 + 2]];
      const s = r + g + b;
      if (s > 0 && r >= RED_RATIO * s && r - g - b > RED_EXCESS) m[i] = 1;
    }
    frame.red = m;
  }
  return frame.red;
}

/** Row and column mean-luminance profiles (cached on the frame). */
function profiles(frame) {
  if (!frame.rowProfile) {
    const { width: w, height: h, lum } = frame;
    const rowP = new Float64Array(h);
    const colP = new Float64Array(w);
    for (let y = 0; y < h; y++) {
      let s = 0;
      for (let x = 0; x < w; x++) {
        const v = lum[y * w + x];
        s += v;
        colP[x] += v;
      }
      rowP[y] = s / w;
    }
    for (let x = 0; x < w; x++) colP[x] /= h;
    frame.rowProfile = rowP;
    frame.colProfile = colP;
  }
  return { rows: frame.rowProfile, cols: frame.colProfile };
}

/** Summed-area tables of luminance and red flags (cached on the frame). */
function integrals(frame) {
  if (!frame.integralLum) {
    const { width: w, height: h, lum } = frame;
    const red = redMask(frame);
    const il = new Float64Array((w + 1) * (h + 1));
    const ir = new Float64Array((w + 1) * (h + 1));
    for (let y = 0; y < h; y++) {
      let sl = 0;
      let sr = 0;
      for (let x = 0; x < w; x++) {
        sl += lum[y * w + x];
        sr += red[y * w + x];
        il[(y + 1) * (w + 1) + x + 1] = il[y * (w + 1) + x + 1] + sl;
        ir[(y + 1) * (w + 1) + x + 1] = ir[y * (w + 1) + x + 1] + sr;
      }
    }
    frame.integralLum = il;
    frame.integralRed = ir;
  }
  return { lum: frame.integralLum, red: frame.integralRed };
}

function rectSum(table, w, x0, y0, x1, y1) {
  const W = w + 1;
  return table[y1 * W + x1] - table[y0 * W + x1] - table[y1 * W + x0] + table[y0 * W + x0];
}

/**
 * Shift d (content moved by d px: cur[i] = prev[i - d]) minimising the mean
 * profile difference, with the errors at no shift and at the mirrored shift -d.
 */
function bestShift(cur, prev) {
  const L = cur.length;
  const max = Math.floor(L / 2);
  const errs = new Float64Array(2 * max + 1);
  for (let d = -max; d <= max; d++) {
    const lo = Math.max(0, d);
    const hi = Math.min(L, L + d);
    let e = 0;
    for (let i = lo; i < hi; i++) e += Math.abs(cur[i] - prev[i - d]);
    errs[d + max] = e / (hi - lo);
  }
  let best = 0;
  for (let d = -max; d <= max; d++) {
    const e = errs[d + max];
    const b = errs[best + max];
    if (e < b - 1e-9 || (e <= b + 1e-9 && Math.abs(d) < Math.abs(best))) best = d;
  }
  return { d: best, err: errs[best + max], err0: errs[max], mirror: errs[max - best] };
}

/**
 * Dominant translation of the frame content since `prev` (page scrolling,
 * carousels), in frame px, or null when no shift explains the change clearly
 * better than no shift (static content, flashes, cross-fades). A shift that the
 * mirrored shift explains about as well is rejected: that is a phase reversal
 * (counter-phase halves, stripes or checkerboards swapping colours), i.e.
 * flicker, not motion.
 */
export function globalShift(cur, prev) {
  if (!prev || prev.width !== cur.width || prev.height !== cur.height) return null;
  const pc = profiles(cur);
  const pp = profiles(prev);
  const cands = [];
  const accept = (s) => s.d !== 0 && s.err0 > 0.002 && s.err <= 0.5 * s.err0 && s.mirror > 2 * s.err + 0.002;
  const v = bestShift(pc.rows, pp.rows);
  if (accept(v)) cands.push({ dx: 0, dy: v.d, q: v.err / v.err0 });
  const hz = bestShift(pc.cols, pp.cols);
  if (accept(hz)) cands.push({ dx: hz.d, dy: 0, q: hz.err / hz.err0 });
  if (!cands.length) return null;
  cands.sort((a, b) => a.q - b.q);
  return [cands[0].dx, cands[0].dy];
}

/**
 * Per-block statistics of one frame for the grid (see makeBlockGrid):
 *  - lum:   Uint8Array, round(255 * mean relative luminance) per block
 *  - red:   Uint8Array, round(255 * share of saturated-red pixels) per block
 *  - moved: bitmask (bit b of byte b >> 3) of blocks whose change since `prev`
 *           is explained by the global shift (or whose content entered the
 *           viewport with it); null when no shift was detected
 *  - shift: [dx, dy] frame px of that global shift ([0, 0] if none)
 * `known` is a shift the caller measured (the page's own scroll between the two
 * frames); it replaces the estimate, which periodic content (a feed of equal cards
 * scrolled by about half a card per frame) makes ambiguous. `known === false` turns
 * motion matching off (the page scrolls back and forth: flicker, not motion).
 */
export function blockStats(frame, grid, prev, known = null) {
  const { cols, rows, colOf, rowOf, xEdges, yEdges } = grid;
  const w = frame.width;
  const h = frame.height;
  if (w !== grid.frameW || h !== grid.frameH) return null;
  const n = cols * rows;
  const lumSum = new Float64Array(n);
  const redSum = new Float64Array(n);
  const count = new Float64Array(n);
  const lum = frame.lum;
  const red = redMask(frame);
  for (let y = 0; y < h; y++) {
    const base = rowOf[y] * cols;
    const o = y * w;
    for (let x = 0; x < w; x++) {
      const b = base + colOf[x];
      lumSum[b] += lum[o + x];
      redSum[b] += red[o + x];
      count[b] += 1;
    }
  }
  const lumU8 = new Uint8Array(n);
  const redU8 = new Uint8Array(n);
  const lumMean = new Float64Array(n);
  const redShare = new Float64Array(n);
  for (let b = 0; b < n; b++) {
    lumMean[b] = count[b] ? lumSum[b] / count[b] : 0;
    redShare[b] = count[b] ? redSum[b] / count[b] : 0;
    lumU8[b] = Math.round(255 * Math.min(1, Math.max(0, lumMean[b])));
    redU8[b] = Math.round(255 * redShare[b]);
  }
  const out = { lum: lumU8, red: redU8, moved: null, shift: [0, 0] };
  if (known === false) return out; // no motion matching (oscillating scroll)
  const shift = known && prev && prev.width === frame.width && prev.height === frame.height ? known : globalShift(frame, prev);
  if (!shift) return out;
  const [dx, dy] = shift;
  const ip = integrals(prev);
  const moved = new Uint8Array(Math.ceil(n / 8));
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const b = r * cols + c;
      const x0 = xEdges[c];
      const x1 = xEdges[c + 1];
      const y0 = yEdges[r];
      const y1 = yEdges[r + 1];
      const sx0 = Math.max(0, x0 - dx);
      const sx1 = Math.min(w, x1 - dx);
      const sy0 = Math.max(0, y0 - dy);
      const sy1 = Math.min(h, y1 - dy);
      const area = Math.max(0, sx1 - sx0) * Math.max(0, sy1 - sy0);
      let explained;
      if (area < 0.5 * (x1 - x0) * (y1 - y0)) {
        explained = true; // new content entered the viewport with the motion
      } else {
        const cl = rectSum(ip.lum, w, sx0, sy0, sx1, sy1) / area;
        const cr = rectSum(ip.red, w, sx0, sy0, sx1, sy1) / area;
        explained = Math.abs(lumMean[b] - cl) <= MOTION_MATCH && Math.abs(redShare[b] - cr) <= MOTION_MATCH;
      }
      if (explained) moved[b >> 3] |= 1 << (b & 7);
    }
  }
  out.moved = moved;
  out.shift = shift;
  return out;
}

/**
 * Visual difference between two frames: share of pixels whose max RGB channel
 * difference is >= `level` (default 16/255). Returns null if sizes differ.
 */
/**
 * Focus-indicator pixels: pixels where ``on`` differs (max channel change >= level)
 * from both unfocused frames ``off1`` and ``off2``, and ``off1`` and ``off2`` differ
 * by less than ``maskLevel`` (pixels that change without focus are animation).
 * Counted inside ``region`` {x0, y0, x1, y1} when given. Frames must share one size;
 * returns null otherwise.
 */
export function indicatorPixels(on, off1, off2, level = 16, maskLevel = 4, region = null) {
  if (!on || !off1 || !off2 || on.rgb.length !== off1.rgb.length || on.rgb.length !== off2.rgb.length) return null;
  const w = on.width;
  const x0 = region ? Math.max(0, region.x0) : 0;
  const y0 = region ? Math.max(0, region.y0) : 0;
  const x1 = region ? Math.min(w, region.x1) : w;
  const y1 = region ? Math.min(on.height, region.y1) : on.height;
  const d = (f, g, o) => Math.max(Math.abs(f.rgb[o] - g.rgb[o]), Math.abs(f.rgb[o + 1] - g.rgb[o + 1]), Math.abs(f.rgb[o + 2] - g.rgb[o + 2]));
  let changed = 0;
  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      const o = (y * w + x) * 3;
      if (d(on, off1, o) >= level && d(on, off2, o) >= level && d(off1, off2, o) < maskLevel) changed++;
    }
  }
  return changed;
}

/**
 * Indicator pixels against several unfocused frames: a pixel counts when ``on`` differs
 * (max channel change >= level) from every frame in ``offs`` while the ``offs`` agree
 * with each other (max change < maskLevel; animation and anything that changed during
 * the capture sequence are masked). Pixels inside ``exclude`` rectangles ({x0, y0, x1,
 * y1}, frame px) are not counted. ``stats``, when given, receives the pixel total and
 * how many were excluded or masked as moving, within ``stats.roi`` when it is set.
 */
export function indicatorPixelsMulti(on, offs, level = 16, maskLevel = 4, exclude = [], stats = null) {
  if (!on || !offs.length || offs.some((f) => !f || f.rgb.length !== on.rgb.length)) return null;
  const w = on.width;
  const d = (f, g, o) => Math.max(Math.abs(f.rgb[o] - g.rgb[o]), Math.abs(f.rgb[o + 1] - g.rgb[o + 1]), Math.abs(f.rgb[o + 2] - g.rgb[o + 2]));
  const roi = stats && stats.roi;
  const inRoi = (x, y) => !roi || (x >= roi.x0 && x < roi.x1 && y >= roi.y0 && y < roi.y1);
  let changed = 0;
  let total = 0;
  let excluded = 0;
  let animated = 0;
  for (let y = 0; y < on.height; y++) {
    for (let x = 0; x < w; x++) {
      const counted = inRoi(x, y);
      if (counted) total++;
      if (exclude.some((r) => x >= r.x0 && x < r.x1 && y >= r.y0 && y < r.y1)) {
        if (counted) excluded++;
        continue;
      }
      const o = (y * w + x) * 3;
      let moving = false;
      for (let i = 1; i < offs.length && !moving; i++) if (d(offs[0], offs[i], o) >= maskLevel) moving = true;
      if (moving) {
        if (counted) animated++;
        continue;
      }
      let ok = true;
      for (let i = 0; i < offs.length && ok; i++) if (d(on, offs[i], o) < level) ok = false;
      if (ok) changed++;
    }
  }
  if (stats) Object.assign(stats, { total, excluded, animated });
  return changed;
}

/**
 * Pixels that changed between two frames by at least ``level`` in any channel, grown
 * by one pixel: content that was already moving before an input (a pulsing button, a
 * slowly shifting gradient). Returns a Uint8Array (1 = moving) or null.
 */
export function changeMask(a, b, level = 4) {
  if (!a || !b || a.rgb.length !== b.rgb.length) return null;
  const w = a.width;
  const h = a.height;
  const hit = new Uint8Array(w * h);
  let any = false;
  for (let i = 0; i < w * h; i++) {
    const o = i * 3;
    if (Math.max(Math.abs(a.rgb[o] - b.rgb[o]), Math.abs(a.rgb[o + 1] - b.rgb[o + 1]), Math.abs(a.rgb[o + 2] - b.rgb[o + 2])) >= level) {
      hit[i] = 1;
      any = true;
    }
  }
  if (!any) return null;
  const out = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      if (!hit[y * w + x]) continue;
      for (let yy = Math.max(0, y - 1); yy <= Math.min(h - 1, y + 1); yy++) {
        for (let xx = Math.max(0, x - 1); xx <= Math.min(w - 1, x + 1); xx++) out[yy * w + xx] = 1;
      }
    }
  }
  return out;
}

export function visualDiffFraction(a, b, level = 16, mask = null, moving = null) {
  if (!a || !b || a.rgb.length !== b.rgb.length) return null;
  const n = a.rgb.length / 3;
  const w = a.width;
  let changed = 0;
  for (let i = 0; i < n; i++) {
    if (moving && moving[i]) continue;
    if (mask) {
      const x = i % w;
      const y = (i - x) / w;
      if (x >= mask.x0 && x < mask.x1 && y >= mask.y0 && y < mask.y1) continue;
    }
    const o = i * 3;
    const d = Math.max(
      Math.abs(a.rgb[o] - b.rgb[o]),
      Math.abs(a.rgb[o + 1] - b.rgb[o + 1]),
      Math.abs(a.rgb[o + 2] - b.rgb[o + 2]),
    );
    if (d >= level) changed++;
  }
  return n ? changed / n : 0;
}

// ---------------------------------------------------------------------------
// CSS-scale copy of a screenshot for fast Python analysis (conspicuity grid).
// Box-averages device pixels down by an integer factor near the DPR and writes a
// filter-0 RGB PNG (cheap to decode without native code).

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, body) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(body.length);
  const tb = Buffer.concat([Buffer.from(type, 'ascii'), body]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(tb));
  return Buffer.concat([len, tb, crc]);
}

export function encodeRgbPng(width, height, rgb) {
  const raw = Buffer.alloc((width * 3 + 1) * height);
  for (let y = 0; y < height; y++) {
    raw[y * (width * 3 + 1)] = 0;
    rgb.copy ? rgb.copy(raw, y * (width * 3 + 1) + 1, y * width * 3, (y + 1) * width * 3)
      : raw.set(rgb.subarray(y * width * 3, (y + 1) * width * 3), y * (width * 3 + 1) + 1);
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; ihdr[9] = 2; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr),
    chunk('IDAT', zlib.deflateSync(raw, { level: 6 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

/**
 * Box-average an image (from decodePng) to exactly `w` x `h` pixels, 3 channels (alpha
 * over white, as frameFromImage does). Used to give every capture of a session the same
 * frame size whatever path produced it.
 */
export function resampleImage(img, w, h) {
  const { width: sw, height: sh, channels: ch, data } = img;
  const out = Buffer.alloc(w * h * 3);
  if (sw % w === 0 && sh % h === 0 && ch >= 3) {
    // Integer factor (the usual case: CSS-px capture to the frame width): plain sums.
    const fx = sw / w;
    const fy = sh / h;
    const n = fx * fy;
    const acc = new Float64Array(w * 3);
    for (let oy = 0; oy < h; oy++) {
      acc.fill(0);
      for (let y = oy * fy; y < (oy + 1) * fy; y++) {
        let i = y * sw * ch;
        for (let ox = 0; ox < w; ox++) {
          let r = 0, g = 0, b = 0;
          for (let k = 0; k < fx; k++, i += ch) {
            let pr = data[i], pg = data[i + 1], pb = data[i + 2];
            if (ch === 4 && data[i + 3] < 255) {
              const f = data[i + 3] / 255;
              pr = pr * f + 255 * (1 - f); pg = pg * f + 255 * (1 - f); pb = pb * f + 255 * (1 - f);
            }
            r += pr; g += pg; b += pb;
          }
          acc[ox * 3] += r; acc[ox * 3 + 1] += g; acc[ox * 3 + 2] += b;
        }
      }
      for (let ox = 0; ox < w; ox++) {
        const o = (oy * w + ox) * 3;
        out[o] = Math.round(acc[ox * 3] / n); out[o + 1] = Math.round(acc[ox * 3 + 1] / n); out[o + 2] = Math.round(acc[ox * 3 + 2] / n);
      }
    }
    return { width: w, height: h, channels: 3, data: out };
  }
  for (let oy = 0; oy < h; oy++) {
    const y0 = Math.floor((oy * sh) / h);
    const y1 = Math.max(y0 + 1, Math.floor(((oy + 1) * sh) / h));
    for (let ox = 0; ox < w; ox++) {
      const x0 = Math.floor((ox * sw) / w);
      const x1 = Math.max(x0 + 1, Math.floor(((ox + 1) * sw) / w));
      let r = 0, g = 0, b = 0, n = 0;
      for (let y = y0; y < y1 && y < sh; y++) {
        for (let x = x0; x < x1 && x < sw; x++) {
          const i = (y * sw + x) * ch;
          let pr, pg, pb;
          if (ch >= 3) { pr = data[i]; pg = data[i + 1]; pb = data[i + 2]; } else { pr = pg = pb = data[i]; }
          const a = ch === 4 ? data[i + 3] : ch === 2 ? data[i + 1] : 255;
          if (a < 255) {
            const f = a / 255;
            pr = pr * f + 255 * (1 - f); pg = pg * f + 255 * (1 - f); pb = pb * f + 255 * (1 - f);
          }
          r += pr; g += pg; b += pb; n++;
        }
      }
      const o = (oy * w + ox) * 3;
      out[o] = Math.round(r / n); out[o + 1] = Math.round(g / n); out[o + 2] = Math.round(b / n);
    }
  }
  return { width: w, height: h, channels: 3, data: out };
}

export function cssScaleCopy(pngBuf, dpr) {
  const img = decodePng(pngBuf);
  const f = Math.max(1, Math.round(dpr));
  const ow = Math.max(1, Math.floor(img.width / f));
  const oh = Math.max(1, Math.floor(img.height / f));
  const ch = img.channels;
  const out = Buffer.alloc(ow * oh * 3);
  for (let oy = 0; oy < oh; oy++) {
    for (let ox = 0; ox < ow; ox++) {
      let r = 0, g = 0, b = 0;
      for (let dy = 0; dy < f; dy++) {
        const row = (oy * f + dy) * img.width;
        for (let dx = 0; dx < f; dx++) {
          const i = (row + ox * f + dx) * ch;
          if (ch >= 3) { r += img.data[i]; g += img.data[i + 1]; b += img.data[i + 2]; }
          else { r += img.data[i]; g += img.data[i]; b += img.data[i]; }
        }
      }
      const n = f * f;
      const o = (oy * ow + ox) * 3;
      out[o] = Math.round(r / n); out[o + 1] = Math.round(g / n); out[o + 2] = Math.round(b / n);
    }
  }
  return { width: ow, height: oh, factor: f, png: encodeRgbPng(ow, oh, out) };
}

