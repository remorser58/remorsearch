// Input validation for ergo-scenario.v1, ergo-profile.v1 and driver actions.
// Fail closed on anything the driver would have to guess; unknown optional keys
// in scripted scenarios are reported as warnings, in /act they are rejected.

import { ActionError, UsageError, isPlainObject } from './util.mjs';

export const KNOWN_ROLES = [
  'primary', 'destructive', 'irreversible', 'critical_message', 'error_message', 'status',
  'navigation', 'ad_like', 'hud', 'game_control', 'timed',
];

const METADATA_KEYS = ['note', 'label', 'comment', 'description', 'id', 'intent', 'expected'];
const COMMON_KEYS = ['action', 'settle_ms', 'feedback_timeout_ms', 'timeout_ms', 'auto_scroll', ...METADATA_KEYS];

const SPEC = {
  tap: { req: ['target'], opt: ['offset'] },
  click: { req: ['target'], opt: ['offset'] },
  double_tap: { req: ['target'], opt: ['offset'] },
  long_press: { req: ['target'], opt: ['offset', 'ms', 'duration_ms'] },
  swipe: { req: [], opt: ['target', 'offset', 'to', 'dx', 'dy', 'direction', 'distance', 'duration_ms'] },
  drag: { req: ['target'], opt: ['offset', 'to', 'dx', 'dy', 'direction', 'distance', 'duration_ms', 'hold_ms'] },
  type: { req: ['text'], opt: ['target', 'offset', 'delay_ms', 'clear', 'redact'] },
  press: { req: ['key'], opt: ['hold_ms', 'repeat'] },
  scroll: { req: [], opt: ['target', 'offset', 'dx', 'dy', 'direction', 'distance', 'duration_ms'] },
  wait: { req: ['ms'], opt: [] },
  snapshot: { req: [], opt: [] },
  gamepad: { req: [], opt: ['button', 'key', 'keys', 'hold_ms'] },
};
export const ACTIONS = Object.keys(SPEC);
const DIRECTIONS = ['up', 'down', 'left', 'right'];
const MS_LIMITS = {
  ms: 120000, duration_ms: 10000, hold_ms: 10000, delay_ms: 1000, settle_ms: 10000, feedback_timeout_ms: 10000, timeout_ms: 60000,
};

function fail(msg) {
  throw new ActionError(msg);
}

function finite(v) {
  return typeof v === 'number' && Number.isFinite(v);
}

function checkPoint(v, where) {
  if (!isPlainObject(v)) fail(`${where} must be {x, y}`);
  for (const k of Object.keys(v)) if (k !== 'x' && k !== 'y') fail(`${where} has unknown key ${JSON.stringify(k)}`);
  if (!finite(v.x) || !finite(v.y)) fail(`${where}.x and ${where}.y must be finite numbers`);
  if (Math.abs(v.x) > 100000 || Math.abs(v.y) > 100000) fail(`${where} is out of range`);
  return { x: v.x, y: v.y };
}

export function checkTarget(v, where) {
  if (typeof v === 'string') {
    if (!v.trim() || v.length > 1000 || /[\u0000-\u001f]/.test(v)) fail(`${where} must be a non-empty selector (<= 1000 chars, no control characters)`);
    if (v.startsWith('hotspot:') && !/^hotspot:[^\s]{1,128}$/.test(v)) fail(`${where} hotspot id is invalid`);
    return v;
  }
  return checkPoint(v, where);
}

function checkKey(v, where) {
  if (typeof v !== 'string' || v.length < 1 || v.length > 64 || /[\u0000-\u001f]/.test(v)) fail(`${where} must be a key name (1-64 chars)`);
  return v;
}

export function isTaskSelector(value) {
  return typeof value === 'string' && value.trim().length > 0 && value.length <= 1000
    && !/[\u0000-\u001f]|\\|["'=]/.test(value)
    && !/\[\s*(?:value|href|src)\b|(?:https?:\/\/|password|passwd|secret|token|credential|api.?key|authorization)/i.test(value);
}

/**
 * Validate and normalise one action object. Returns {action, warnings}.
 * strict=true rejects unknown keys (HTTP /act); strict=false drops them with a warning.
 */
export function normalizeAction(raw, { strict, where = 'action' } = {}) {
  if (!isPlainObject(raw)) fail(`${where} must be an object`);
  const kind = raw.action;
  if (typeof kind !== 'string' || !SPEC[kind]) fail(`${where}.action must be one of ${ACTIONS.join(', ')}`);
  const spec = SPEC[kind];
  const allowed = new Set([...COMMON_KEYS, ...spec.req, ...spec.opt]);
  const warnings = [];
  const out = { action: kind };
  for (const key of Object.keys(raw)) {
    if (!allowed.has(key)) {
      if (strict) fail(`${where}: key ${JSON.stringify(key)} is not allowed for ${kind}; allowed: ${[...allowed].join(', ')}`);
      warnings.push(`${where}: ignored unknown key ${JSON.stringify(key)} for ${kind}`);
    }
  }
  for (const key of spec.req) if (!(key in raw)) fail(`${where}.${key} is required for ${kind}`);
  for (const key of Object.keys(raw)) {
    if (!allowed.has(key) || key === 'action') continue;
    const v = raw[key];
    const at = `${where}.${key}`;
    if (METADATA_KEYS.includes(key)) {
      if (typeof v !== 'string' || v.length > 2000) fail(`${at} must be a string (<= 2000 chars)`);
      out[key] = v;
    } else if (key === 'target' || key === 'to') {
      out[key] = checkTarget(v, at);
    } else if (key === 'offset') {
      out[key] = checkPoint(v, at);
    } else if (key in MS_LIMITS) {
      if (!finite(v) || v < 0 || v > MS_LIMITS[key]) fail(`${at} must be a number within 0..${MS_LIMITS[key]}`);
      out[key] = v;
    } else if (key === 'dx' || key === 'dy' || key === 'distance') {
      if (!finite(v) || Math.abs(v) > 100000 || (key === 'distance' && v <= 0)) fail(`${at} must be a finite number${key === 'distance' ? ' > 0' : ''}`);
      out[key] = v;
    } else if (key === 'direction') {
      if (!DIRECTIONS.includes(v)) fail(`${at} must be one of ${DIRECTIONS.join(', ')}`);
      out[key] = v;
    } else if (key === 'text') {
      if (typeof v !== 'string' || v.length > 5000) fail(`${at} must be a string (<= 5000 chars)`);
      out[key] = v;
    } else if (key === 'key') {
      out[key] = checkKey(v, at);
    } else if (key === 'keys') {
      if (!Array.isArray(v) || v.length < 1 || v.length > 8) fail(`${at} must be an array of 1-8 key names`);
      out[key] = v.map((k, i) => checkKey(k, `${at}[${i}]`));
    } else if (key === 'button') {
      if (typeof v !== 'string' || !v || v.length > 32) fail(`${at} must be a short string`);
      out[key] = v;
    } else if (key === 'repeat') {
      if (!Number.isInteger(v) || v < 1 || v > 50) fail(`${at} must be an integer within 1..50`);
      out[key] = v;
    } else if (key === 'clear' || key === 'auto_scroll' || key === 'redact') {
      if (typeof v !== 'boolean') fail(`${at} must be a boolean`);
      out[key] = v;
    }
  }
  if (kind === 'gamepad' && !out.key && !out.keys) fail(`${where}: gamepad needs "key" or "keys" (the keyboard mapping for the button)`);
  if ((kind === 'swipe' || kind === 'drag') && !('to' in out) && !('dx' in out) && !('dy' in out) && !out.direction) {
    fail(`${where}: ${kind} needs "to", "dx"/"dy" or "direction"`);
  }
  if (kind === 'scroll' && !('dx' in out) && !('dy' in out) && !out.direction) fail(`${where}: scroll needs "dx"/"dy" or "direction"`);
  if (out.redact && (!isTaskSelector(out.target) || out.target.startsWith('hotspot:'))) fail(`${where}: redacted typing requires plain CSS without literals, escapes or selector engines`);
  return { action: out, warnings };
}

function usage(msg) {
  throw new UsageError(msg);
}

function strOrList(v, where) {
  const list = typeof v === 'string' ? [v] : v;
  if (!Array.isArray(list) || !list.length || !list.every((s) => typeof s === 'string' && s.length > 0 && s.length <= 1000)) {
    usage(`${where} must be a non-empty string or list of strings`);
  }
  return list;
}

function checkBox(b, where) {
  if (!isPlainObject(b) || ![b.x, b.y, b.w, b.h].every(finite) || b.w < 0 || b.h < 0) usage(`${where} must be {x, y, w, h} with w, h >= 0`);
  return { x: b.x, y: b.y, w: b.w, h: b.h };
}

export const SUCCESS_KEYS = ['selector_visible', 'url_contains', 'text_present', 'task_checks'];

const TASK_CHECK_KEYS = new Set(['id', 'selector', 'property', 'after_step', 'expected', 'from_step', 'severity', 'consequence', 'redact']);

function taskChecks(value, steps, requireSteps) {
  if (!Array.isArray(value) || value.length < 1 || value.length > 64) usage('scenario.success.task_checks must contain 1..64 checks');
  const ids = new Set();
  const checkpoints = new Set();
  const checks = value.map((c, i) => {
    const at = `scenario.success.task_checks[${i}]`;
    if (!isPlainObject(c) || Object.keys(c).some((key) => !TASK_CHECK_KEYS.has(key))) usage(`${at} has an invalid shape`);
    if (typeof c.id !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(c.id) || ids.has(c.id)) usage(`${at}.id must be a unique identifier`);
    ids.add(c.id);
    if (!isTaskSelector(c.selector)) usage(`${at}.selector must be plain CSS without literals, escapes or credentials`);
    if (!['value', 'text', 'checked'].includes(c.property)) usage(`${at}.property must be value, text or checked`);
    if (c.after_step !== undefined && (!Number.isInteger(c.after_step) || c.after_step < 1 || c.after_step > 10000 || (requireSteps && c.after_step > steps.length))) usage(`${at}.after_step must name a reachable 1-based action index`);
    const checkpoint = JSON.stringify([c.selector, c.property, c.after_step ?? 'final']);
    if (checkpoints.has(checkpoint)) usage(`${at} duplicates a selector/property/checkpoint`);
    checkpoints.add(checkpoint);
    if (('expected' in c) === ('from_step' in c)) usage(`${at} needs exactly one of expected or from_step`);
    if ('expected' in c && (c.property === 'checked' ? typeof c.expected !== 'boolean' : typeof c.expected !== 'string' || c.expected.length > 5000)) usage(`${at}.expected has the wrong type or exceeds 5000 characters`);
    if ('from_step' in c && (c.property === 'checked' || !Number.isInteger(c.from_step) || c.from_step < 1 || c.from_step > steps.length || steps[c.from_step - 1]?.action !== 'type' || (c.after_step !== undefined && c.from_step > c.after_step))) usage(`${at}.from_step must reference an authored type action at or before the checkpoint`);
    if (!['P0', 'P1', 'P2', 'P3'].includes(c.severity)) usage(`${at}.severity must be an authored P0..P3 task impact`);
    if (typeof c.consequence !== 'string' || !c.consequence.trim() || c.consequence.length > 1000) usage(`${at}.consequence must describe the task impact in 1..1000 characters without field values`);
    if (c.redact !== undefined && typeof c.redact !== 'boolean') usage(`${at}.redact must be a boolean`);
    if (c.redact === true && 'from_step' in c) {
      const source = steps[c.from_step - 1];
      if (!isTaskSelector(source.target) || source.target.startsWith('hotspot:')) usage(`${at}.from_step redaction requires plain CSS on the authored type action`);
      steps[c.from_step - 1] = normalizeAction({ ...source, redact: true }, { strict: true, where: `${at}.from_step` }).action;
    }
    return { ...c };
  });
  return checks.map((c) => ({ ...c, redact: c.redact === true || ('from_step' in c && steps[c.from_step - 1].redact === true) }));
}

export function normalizeBuildId(value, where = 'build_id') {
  if (typeof value !== 'string' || !value.trim() || value.length > 256 || /[\u0000-\u001f]/.test(value)
    || ['unknown', 'unrecorded'].includes(value.trim().toLowerCase())) {
    usage(`${where} must be a known commit/version/deploy or source identity (1-256 characters)`);
  }
  return value;
}

/** Validate an ergo-scenario.v1 document and substitute {BASE}. */
export function normalizeScenario(doc, { base, requireSteps }) {
  const warnings = [];
  if (!isPlainObject(doc)) usage('scenario must be a JSON object');
  if (doc.schema_version !== 'ergo-scenario.v1') usage(`scenario schema_version must be "ergo-scenario.v1" (got ${JSON.stringify(doc.schema_version)})`);
  if (typeof doc.scenario_id !== 'string' || !doc.scenario_id.trim() || doc.scenario_id.length > 200) usage('scenario_id must be a non-empty string');
  const surface = doc.surface;
  if (!isPlainObject(surface)) usage('scenario.surface must be an object');
  // Browser-hosted games (canvas/WebGL) are driven like web pages; native apps are not.
  if (surface.kind !== 'web' && surface.kind !== 'game') usage(`this driver only drives web pages and browser games (surface.kind=${JSON.stringify(surface.kind)})`);
  if (typeof surface.url !== 'string' || !surface.url) usage('scenario.surface.url must be a string');
  const subst = (s) => {
    if (!s.includes('{BASE}')) return s;
    if (!base) usage(`scenario uses "{BASE}" (${s}); pass --base http://127.0.0.1:PORT`);
    return s.split('{BASE}').join(base);
  };
  const url = subst(surface.url);
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    usage(`scenario.surface.url is not a valid URL: ${url}`);
  }
  if (!['http:', 'https:', 'file:'].includes(parsed.protocol)) usage(`surface url protocol ${parsed.protocol} is not allowed (http, https, file only)`);

  const targets = {};
  if (doc.targets !== undefined) {
    if (!isPlainObject(doc.targets)) usage('scenario.targets must be an object of role -> [selectors]');
    for (const [role, sels] of Object.entries(doc.targets)) {
      if (!Array.isArray(sels)) usage(`scenario.targets.${role} must be an array`);
      if (!KNOWN_ROLES.includes(role)) {
        warnings.push(`scenario.targets: unknown role ${JSON.stringify(role)} ignored (allowed: ${KNOWN_ROLES.join(', ')})`);
        continue;
      }
      const list = [];
      sels.forEach((s, i) => {
        if (typeof s !== 'string' || !s.trim() || s.length > 1000) {
          warnings.push(`scenario.targets.${role}[${i}] is not a selector string; ignored`);
        } else {
          list.push(s);
        }
      });
      targets[role] = list;
    }
  }

  const hotspots = [];
  const hotspotIds = new Set();
  for (const [i, h] of (Array.isArray(doc.hotspots) ? doc.hotspots : []).entries()) {
    if (!isPlainObject(h) || typeof h.id !== 'string' || !h.id || h.id.length > 128) usage(`scenario.hotspots[${i}].id must be a non-empty string`);
    if (hotspotIds.has(h.id)) usage(`scenario.hotspots[${i}].id duplicates ${h.id}`);
    hotspotIds.add(h.id);
    const roles = Array.isArray(h.roles) ? h.roles.filter((r) => typeof r === 'string') : [];
    for (const r of roles) if (!KNOWN_ROLES.includes(r)) warnings.push(`scenario.hotspots[${i}]: unknown role ${JSON.stringify(r)} ignored`);
    hotspots.push({
      id: h.id,
      name: typeof h.name === 'string' ? h.name : h.id,
      box: checkBox(h.box, `scenario.hotspots[${i}].box`),
      roles: roles.filter((r) => KNOWN_ROLES.includes(r)),
    });
  }
  if (doc.hotspots !== undefined && !Array.isArray(doc.hotspots)) usage('scenario.hotspots must be an array');

  const steps = [];
  if (doc.steps !== undefined && !Array.isArray(doc.steps)) usage('scenario.steps must be an array');
  if (requireSteps && !Array.isArray(doc.steps)) usage('scenario.steps is required for "run"');
  for (const [i, s] of (doc.steps || []).entries()) {
    try {
      const { action, warnings: w } = normalizeAction(s, { strict: false, where: `scenario.steps[${i}]` });
      steps.push(action);
      warnings.push(...w);
    } catch (err) {
      if (err instanceof ActionError) usage(err.message);
      throw err;
    }
  }

  const windows = [];
  const windowIds = new Set();
  if (doc.timing_windows !== undefined && !Array.isArray(doc.timing_windows)) usage('scenario.timing_windows must be an array');
  for (const [i, w] of (doc.timing_windows || []).entries()) {
    if (!isPlainObject(w) || typeof w.id !== 'string' || !w.id || w.id.length > 128) usage(`scenario.timing_windows[${i}].id must be a non-empty string`);
    if (typeof w.selector !== 'string' || !w.selector || w.selector.length > 1000) usage(`scenario.timing_windows[${i}].selector must be a selector string`);
    if (windowIds.has(w.id)) usage(`scenario.timing_windows[${i}].id duplicates ${w.id}`);
    windowIds.add(w.id);
    const measure = typeof w.measure === 'string' ? w.measure : 'visible_duration';
    if (measure !== 'visible_duration') warnings.push(`timing window ${w.id}: measure ${JSON.stringify(measure)} is not implemented; visible duration is measured instead`);
    windows.push({
      id: w.id,
      selector: w.selector,
      measure,
      kind: typeof w.kind === 'string' ? w.kind : null,
      text: typeof w.text === 'string' ? w.text : null,
    });
  }

  let success = null;
  const unevaluable = [];
  if (doc.success !== undefined && doc.success !== null) {
    if (!isPlainObject(doc.success)) usage('scenario.success must be an object');
    success = {};
    for (const [k, v] of Object.entries(doc.success)) {
      if (SUCCESS_KEYS.includes(k)) {
        success[k] = k === 'task_checks' ? taskChecks(v, steps, requireSteps) : strOrList(k === 'url_contains' ? (Array.isArray(v) ? v.map((x) => (typeof x === 'string' ? subst(x) : x)) : (typeof v === 'string' ? subst(v) : v)) : v, `scenario.success.${k}`);
      } else {
        unevaluable.push(k);
        warnings.push(`scenario.success.${k} is not supported by this driver (supported: ${SUCCESS_KEYS.join(', ')}); success cannot be established`);
      }
    }
    if (!Object.keys(success).length && !unevaluable.length) usage('scenario.success must declare at least one condition');
  }

  const deviceIds = Array.isArray(doc.device_ids) ? doc.device_ids.filter((d) => typeof d === 'string') : [];
  return {
    scenario: {
      scenario_id: doc.scenario_id,
      surface_kind: surface.kind,
      build_id: surface.build_id === undefined ? null : normalizeBuildId(surface.build_id, 'scenario.surface.build_id'),
      url,
      origin: parsed,
      task_goal_ko: typeof doc.task_goal_ko === 'string' ? doc.task_goal_ko : '',
      device_ids: deviceIds,
      targets,
      hotspots,
      steps,
      timing_windows: windows,
      success,
      success_unevaluable: unevaluable,
    },
    warnings,
  };
}

/** Minimal ergo-profile.v1 check for the fields the driver uses. */
export function normalizeProfile(doc) {
  if (!isPlainObject(doc)) usage('profile must be a JSON object');
  if (doc.schema_version !== 'ergo-profile.v1') usage(`profile schema_version must be "ergo-profile.v1" (got ${JSON.stringify(doc.schema_version)})`);
  if (typeof doc.profile_id !== 'string' || !/^[^\s/\\]{1,128}$/.test(doc.profile_id)) usage('profile_id must be a non-empty string without spaces or slashes');
  const a = doc.attributes;
  if (!isPlainObject(a)) usage('profile.attributes must be an object');
  if (a.device_id !== undefined && typeof a.device_id !== 'string') usage('profile.attributes.device_id must be a string');
  if (a.orientation !== undefined && !['portrait', 'landscape'].includes(a.orientation)) usage('profile.attributes.orientation must be portrait or landscape');
  return { profile_id: doc.profile_id, device_id: a.device_id || null, orientation: a.orientation || null };
}
