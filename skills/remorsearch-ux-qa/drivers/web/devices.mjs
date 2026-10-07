// Device emulation table for the live web driver.
//
// Mirrors ergoqa/devices.py (id, form_factor, viewport_css, dpr, input,
// playwright_device, native orientation). Viewport and DPR always come from this
// table; a Playwright descriptor, when named, contributes only its userAgent
// (the same rule as the Python catalog). `node selftest.mjs` cross-checks this
// table against `ergoqa.devices` when Python is available.

export const ROTATABLE = new Set(['phone', 'tablet', 'foldable']);
export const INPUTS = new Set(['touch', 'mouse', 'keyboard', 'gamepad', 'remote']);
export const FORM_FACTORS = new Set(['phone', 'tablet', 'foldable', 'desktop', 'laptop', 'tv', 'handheld_console']);

// [id, form_factor, [w, h], dpr, input, playwright_device]
const TABLE = [
  ['galaxy-s24', 'phone', [360, 780], 3.0, 'touch', 'Galaxy S24'],
  ['galaxy-s24-ultra', 'phone', [384, 824], 3.75, 'touch', null],
  ['galaxy-a55', 'phone', [412, 892], 2.625, 'touch', null],
  ['galaxy-z-flip6', 'foldable', [412, 1006], 2.625, 'touch', null],
  ['galaxy-z-fold6-inner', 'foldable', [707, 823], 2.625, 'touch', null],
  ['iphone-15', 'phone', [393, 852], 3.0, 'touch', 'iPhone 15'],
  ['iphone-15-pro-max', 'phone', [430, 932], 3.0, 'touch', 'iPhone 15 Pro Max'],
  ['pixel-8', 'phone', [412, 915], 2.625, 'touch', null],
  ['galaxy-tab-s9', 'tablet', [800, 1280], 2.0, 'touch', null],
  ['desktop-1920', 'desktop', [1920, 1080], 1.0, 'mouse', 'Desktop Chrome'],
  ['laptop-1440', 'laptop', [1440, 900], 2.0, 'mouse', null],
  ['tv-55-1080', 'tv', [1920, 1080], 1.0, 'remote', null],
  ['switch-handheld', 'handheld_console', [1280, 720], 1.0, 'gamepad', null],
];

export const CATALOG = new Map(TABLE.map(([id, form, vp, dpr, input, pw]) => [id, {
  id,
  form_factor: form,
  viewport_css: vp,
  dpr,
  input,
  playwright_device: pw,
  native_orientation: ROTATABLE.has(form) ? 'portrait' : 'landscape',
}]));

// Same rules as Device.has_touch / Device.is_mobile in ergoqa/devices.py.
export function hasTouch(dev) {
  return dev.input === 'touch' || ['phone', 'tablet', 'foldable', 'handheld_console'].includes(dev.form_factor);
}

export function isMobile(dev) {
  return ['phone', 'tablet', 'foldable'].includes(dev.form_factor);
}

function reducedUa(dev, chromeMajor) {
  // Chrome's reduced User-Agent strings (no model or OS build detail), so no
  // specific vendor build is impersonated.
  const v = `${chromeMajor || 141}.0.0.0`;
  if (dev.form_factor === 'phone' || dev.form_factor === 'foldable') {
    return `Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${v} Mobile Safari/537.36`;
  }
  if (dev.form_factor === 'tablet') {
    return `Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${v} Safari/537.36`;
  }
  return `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${v} Safari/537.36`;
}

export class DeviceError extends Error {}

/** Validate a device object supplied as JSON (a Device.to_dict() from ergoqa). */
export function deviceFromJson(obj) {
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) throw new DeviceError('device JSON must be an object');
  const id = obj.id;
  if (typeof id !== 'string' || !/^[A-Za-z0-9._-]{1,64}$/.test(id)) throw new DeviceError('device JSON: id must match [A-Za-z0-9._-]{1,64}');
  if (!FORM_FACTORS.has(obj.form_factor)) throw new DeviceError(`device JSON: unknown form_factor ${JSON.stringify(obj.form_factor)}`);
  if (!INPUTS.has(obj.input)) throw new DeviceError(`device JSON: unknown input ${JSON.stringify(obj.input)}`);
  const vp = obj.viewport_css;
  if (!Array.isArray(vp) || vp.length !== 2 || !vp.every((n) => Number.isFinite(n) && n >= 100 && n <= 8000)) {
    throw new DeviceError('device JSON: viewport_css must be [w, h] with 100 <= w,h <= 8000');
  }
  if (!Number.isFinite(obj.dpr) || obj.dpr < 0.5 || obj.dpr > 5) throw new DeviceError('device JSON: dpr must be within 0.5..5');
  const pw = obj.playwright_device ?? null;
  if (pw !== null && typeof pw !== 'string') throw new DeviceError('device JSON: playwright_device must be a string or null');
  const native = obj.orientation === 'landscape' || obj.orientation === 'portrait'
    ? obj.orientation
    : (vp[0] > vp[1] ? 'landscape' : 'portrait');
  return {
    id,
    form_factor: obj.form_factor,
    viewport_css: [Math.round(vp[0]), Math.round(vp[1])],
    dpr: obj.dpr,
    input: obj.input,
    playwright_device: pw,
    native_orientation: native,
  };
}

/**
 * Resolve the emulation settings for a device id (or a supplied device object)
 * and requested orientation. Returns the Playwright context options plus the
 * snapshot `device` block.
 */
export function resolveDevice({ id, device, orientation, pwDevices, chromeMajor }) {
  const warnings = [];
  const base = device || CATALOG.get(id);
  if (!base) {
    throw new DeviceError(`unknown device id ${JSON.stringify(id)}; known: ${[...CATALOG.keys()].join(', ')}`);
  }
  let [w, h] = base.viewport_css;
  let actual = base.native_orientation;
  if (orientation && orientation !== base.native_orientation) {
    if (ROTATABLE.has(base.form_factor)) {
      [w, h] = [h, w];
      actual = orientation;
    } else {
      warnings.push(`${base.id} (${base.form_factor}) has a fixed ${base.native_orientation} orientation; requested ${orientation} ignored`);
    }
  }
  let userAgent = null;
  let uaSource = 'reduced-chrome-ua';
  if (base.playwright_device) {
    const desc = pwDevices ? pwDevices[base.playwright_device] : null;
    if (desc && desc.userAgent) {
      userAgent = desc.userAgent;
      uaSource = `playwright:${base.playwright_device}`;
    } else {
      warnings.push(`Playwright descriptor ${JSON.stringify(base.playwright_device)} not found; using a reduced Chrome UA`);
    }
  }
  if (!userAgent) userAgent = reducedUa(base, chromeMajor);
  const touch = hasTouch(base);
  const mobile = isMobile(base);
  return {
    base,
    warnings,
    contextOptions: {
      viewport: { width: w, height: h },
      screen: { width: w, height: h },
      deviceScaleFactor: base.dpr,
      hasTouch: touch,
      isMobile: mobile,
      userAgent,
    },
    snapshotDevice: {
      id: base.id,
      viewport_css: [w, h],
      dpr: base.dpr,
      orientation: actual,
      input: base.input,
      form_factor: base.form_factor,
    },
    emulation: {
      user_agent: userAgent,
      user_agent_source: uaSource,
      has_touch: touch,
      is_mobile: mobile,
      input: base.input,
    },
  };
}
