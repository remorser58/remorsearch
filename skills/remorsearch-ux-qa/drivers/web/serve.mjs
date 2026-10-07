// Interactive HTTP session for an LLM persona agent (spec section 10).
//
// Binds 127.0.0.1 only. Requests are JSON with a small size cap; Host/Origin
// are checked (DNS-rebinding and cross-site POST defence); POST bodies must be
// application/json. Only validated action objects reach the browser. No
// endpoint evaluates JavaScript, navigates to request-supplied URLs or reads
// files named by a request.

import http from 'node:http';

import { ActionError, DriverFailure, isPlainObject } from './util.mjs';
import { normalizeAction } from './validate.mjs';

const MAX_BODY = 64 * 1024;
const NOTE_KEYS = new Set(['intent', 'expected', 'observed', 'confusion', 'step_index', 'severity', 'failure_class', 'evidence', 'corroborated', 'anchor']);
// persona-agent-protocol.md: ux_issue | agent_limitation | environment | unknown
const FAILURE_CLASSES = new Set(['ux_issue', 'agent_limitation', 'environment', 'unknown']);
const SEVERITIES = new Set(['P0', 'P1', 'P2', 'P3']);

class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function send(res, status, obj, headers = {}) {
  const body = JSON.stringify(obj);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
    'Content-Length': Buffer.byteLength(body),
    ...headers,
  });
  res.end(body);
}

function readJson(req) {
  const type = String(req.headers['content-type'] || '').toLowerCase();
  if (!type.startsWith('application/json')) {
    return Promise.reject(new HttpError(415, 'Content-Type must be application/json'));
  }
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    let failed = false;
    req.on('data', (chunk) => {
      if (failed) return;
      size += chunk.length;
      if (size > MAX_BODY) {
        failed = true;
        reject(new HttpError(413, `request body exceeds ${MAX_BODY} bytes`));
        req.resume();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => {
      if (failed) return;
      const text = Buffer.concat(chunks).toString('utf8');
      let value;
      try {
        value = text.trim() ? JSON.parse(text) : {};
      } catch (err) {
        reject(new HttpError(400, `invalid JSON: ${err.message}`));
        return;
      }
      if (!isPlainObject(value)) {
        reject(new HttpError(400, 'JSON body must be an object'));
        return;
      }
      resolve(value);
    });
    req.on('error', (err) => reject(new HttpError(400, err.message)));
  });
}

function validateNote(body, maxStep) {
  for (const k of Object.keys(body)) if (!NOTE_KEYS.has(k)) throw new HttpError(400, `unknown key ${JSON.stringify(k)}; allowed: ${[...NOTE_KEYS].join(', ')}`);
  for (const k of ['intent', 'expected', 'observed']) {
    if (body[k] !== undefined && (typeof body[k] !== 'string' || body[k].length > 4000)) throw new HttpError(400, `${k} must be a string (<= 4000 chars)`);
  }
  if (typeof body.confusion !== 'boolean') throw new HttpError(400, 'confusion (boolean) is required');
  if (body.step_index !== undefined && (!Number.isInteger(body.step_index) || body.step_index < 0 || body.step_index > maxStep)) {
    throw new HttpError(400, `step_index must be an integer within 0..${maxStep}`);
  }
  if (body.severity !== undefined && !SEVERITIES.has(body.severity)) throw new HttpError(400, 'severity must be one of P0, P1, P2, P3');
  if (body.failure_class !== undefined && !FAILURE_CLASSES.has(body.failure_class)) {
    throw new HttpError(400, `failure_class must be one of ${[...FAILURE_CLASSES].join(', ')}`);
  }
  if (body.evidence !== undefined && (typeof body.evidence !== 'string' || body.evidence.length > 200)) throw new HttpError(400, 'evidence must be a string (<= 200 chars)');
  if (body.corroborated !== undefined && typeof body.corroborated !== 'boolean') throw new HttpError(400, 'corroborated must be a boolean');
  // anchor: what the note is about. "acted" (default) = the element the step acted on;
  // {"point": {x, y}} or {"box": {x, y, w, h}} in CSS px of the current screenshot.
  const a = body.anchor;
  if (a !== undefined && a !== 'acted') {
    const num = (v) => typeof v === 'number' && Number.isFinite(v);
    const okPoint = a && typeof a === 'object' && a.point && num(a.point.x) && num(a.point.y);
    const okBox = a && typeof a === 'object' && a.box && [a.box.x, a.box.y, a.box.w, a.box.h].every(num) && a.box.w > 0 && a.box.h > 0;
    if (!okPoint && !okBox) throw new HttpError(400, 'anchor must be "acted", {"point": {x, y}} or {"box": {x, y, w, h}}');
  }
  return body;
}

// Replies to a screenshot-channel operator carry only what a person sees: no
// snapshot JSON path, element count or DOM grounding flags (LAT-02), so runs on
// different input channels stay independent views for corroboration.
const DOM_REPLY_KEYS = ['snapshot', 'elements', 'target_element_id', 'target_hit', 'feedback_latency_ms', 'feedback_source'];

export function snapshotReply(snap, extra = {}, channel = null) {
  const out = {
    snapshot: snap.jsonPath,
    png: snap.pngPath,
    snapshot_id: snap.id,
    step_index: snap.snap.step_index,
    url: snap.snap.surface.url,
    title: snap.snap.surface.title,
    elements: snap.snap.elements.length,
    ...extra,
  };
  if (channel === 'screenshot') for (const k of DOM_REPLY_KEYS) delete out[k];
  return out;
}

/**
 * Start the HTTP server. `onDone(result)` is called once after /finish, an idle
 * timeout or a driver failure has written run.json.
 */
export function startServer({ session, port, idleTimeoutS, onReady, onDone }) {
  const channel = session.opts?.agentInfo?.input_channel ?? null;
  let queue = Promise.resolve();
  let finished = false;
  let idleTimer = null;
  const enqueue = (fn) => {
    const p = queue.then(fn);
    queue = p.catch(() => {});
    return p;
  };
  const finishWith = (opts) => {
    finished = true;
    clearTimeout(idleTimer);
    return enqueue(async () => {
      const result = await session.finish(opts);
      setImmediate(() => {
        server.close();
        onDone(result);
      });
      return result;
    });
  };
  const resetIdle = () => {
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => {
      if (!finished) finishWith({ reason: `idle timeout: no request for ${idleTimeoutS}s` });
    }, idleTimeoutS * 1000);
  };

  const server = http.createServer((req, res) => {
    handle(req, res).catch((err) => {
      if (err instanceof HttpError) send(res, err.status, { error: err.message });
      else send(res, 500, { error: `internal error: ${String(err && err.message ? err.message : err).split('\n')[0]}` });
    });
  });

  async function handle(req, res) {
    const actual = server.address().port;
    const host = String(req.headers.host || '');
    if (host !== `127.0.0.1:${actual}` && host !== `localhost:${actual}`) throw new HttpError(421, 'unexpected Host header');
    const origin = req.headers.origin;
    if (origin !== undefined && origin !== `http://127.0.0.1:${actual}` && origin !== `http://localhost:${actual}`) {
      throw new HttpError(403, 'cross-origin requests are not accepted');
    }
    const site = req.headers['sec-fetch-site'];
    if (site !== undefined && site !== 'same-origin' && site !== 'none') throw new HttpError(403, 'cross-site requests are not accepted');
    const { pathname } = new URL(req.url, `http://127.0.0.1:${actual}`);
    const allow = { '/health': 'GET', '/snapshot': 'GET', '/inspect': 'GET', '/act': 'POST', '/note': 'POST', '/finish': 'POST' }[pathname];
    if (!allow) throw new HttpError(404, 'unknown endpoint; use GET /health, GET /snapshot, GET /inspect, POST /act, POST /note, POST /finish');
    if (req.method !== allow) {
      send(res, 405, { error: `${pathname} accepts ${allow} only` }, { Allow: allow });
      return;
    }
    resetIdle();
    if (pathname === '/health') {
      send(res, 200, {
        ok: true, run_id: session.runId, run_dir: session.runDir, steps: session.steps.length,
        last_snapshot_id: session.lastSnapshotId, finished,
      });
      return;
    }
    if (finished) throw new HttpError(409, 'session already finished');
    if (pathname === '/inspect') {
      if (channel === 'screenshot') throw new HttpError(403, 'inspect returns DOM evidence; start a separate serve session with an a11y or screenshot+a11y input_channel in --agent-json');
      const state = await enqueue(() => session.inspect());
      send(res, 200, state);
      return;
    }
    if (pathname === '/snapshot') {
      const snap = await enqueue(() => session.snapshot(session.steps.length, ['on_demand']));
      send(res, 200, snapshotReply(snap, { result: 'ok' }, channel));
      return;
    }
    const body = await readJson(req);
    if (pathname === '/act') {
      let action;
      try {
        ({ action } = normalizeAction(body, { strict: true, where: 'body' }));
      } catch (err) {
        if (err instanceof ActionError) throw new HttpError(400, err.message);
        throw err;
      }
      let out;
      try {
        out = await enqueue(() => session.act(action));
      } catch (err) {
        if (err instanceof DriverFailure) {
          const result = await finishWith({ reason: err.message });
          send(res, 500, { error: err.message, run: result.runPath, status: result.status });
          return;
        }
        throw err;
      }
      const { step, snap } = out;
      send(res, 200, snapshotReply(snap, {
        result: step.result,
        error: step.error,
        step_index: step.step_index,
        before: step.before,
        point: step.point,
        target_element_id: step.target_element_id,
        target_hit: step.target_hit ?? null,
        feedback_latency_ms: step.feedback_latency_ms,
        feedback_source: step.feedback_source ?? null,
        auto_scrolled: !!step.auto_scrolled,
      }, channel));
      return;
    }
    if (pathname === '/note') {
      const note = validateNote(body, session.steps.length);
      const index = session.addNote(note);
      send(res, 200, { ok: true, note_index: index, step_index: session.personaNotes[index].step_index });
      return;
    }
    // /finish
    for (const k of Object.keys(body)) if (k !== 'success') throw new HttpError(400, `unknown key ${JSON.stringify(k)}; allowed: success`);
    if (body.success !== undefined && typeof body.success !== 'boolean') throw new HttpError(400, 'success must be a boolean');
    const result = await finishWith({ personaSuccess: body.success });
    send(res, 200, {
      run: result.runPath, status: result.status, success: result.success,
      success_basis: result.run.success_basis, exit_code: result.exitCode,
    });
  }

  server.on('clientError', (err, socket) => {
    try {
      socket.end('HTTP/1.1 400 Bad Request\r\n\r\n');
    } catch { /* ignore */ }
  });
  server.listen(port, '127.0.0.1', () => {
    resetIdle();
    onReady(server.address().port);
  });
  server.on('error', (err) => {
    onDone(null, err);
  });
  return server;
}
