#!/usr/bin/env node
// Read-only render of one public URL (rung R3 of the public-page reader,
// references/research/public-page-access.md section 10). Writes one
// ux-page-read.v1 document (schemas/ux-page-read.v1.schema.json).
//
//   node drivers/web/read_page.mjs URL [--out FILE] [--device ID] [--max-wait-ms 15000]
//                                  [--scrolls 8] [--timeout-s 30] [--allow-local]
//
// What it does: a fresh anonymous browser context (no stored cookies or sign-in),
// the browser's own user agent (no stealth, no disguise), images, media and fonts
// blocked, then scrolling only. It never clicks, types or presses keys. A check
// of any kind stops the render immediately, even when it would clear by itself.
// --max-wait-ms is accepted for compatibility but never waits out a check.
// A password field is reported (the reader's verdict decides whether the page is gated).
//
// Exit codes (the reader's scheme): 0 read (document written); 3 stopped at a
// browser or human check (document written with empty text); 2 usage
// or refused address; 4 unread (navigation failed, no document, browser missing).

import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { CATALOG, hasTouch, isMobile } from './devices.mjs';
import { openBrowser } from './browser_transport.mjs';
import { loadPlaywright } from './playwright_loader.mjs';
import { capturePage } from './read_capture.mjs';
import { isoNow, sleep, writeJsonAtomic } from './util.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const MARKERS = path.join(HERE, '..', '..', 'uxresearch', 'data', 'markers.json');
const DRIVER_VERSION = 'read_page/2';
const TEXT_MAX = 409600;
const JSON_LD_MAX_BLOCKS = 10;
const JSON_LD_MAX_CHARS = 1_000_000;
const WAIT_CAP_MS = 15000;
const SCROLL_CAP = 50;
const SCROLL_PAUSE_MS = 400;
const BLOCKED = ['image', 'media', 'font'];
const CHECK_BINDING = '__remorsearchPageReadCheck';

const USAGE = `usage: node drivers/web/read_page.mjs URL [--out FILE] [--device ID] [--max-wait-ms N<=15000]
                                     [--scrolls N<=50] [--timeout-s N] [--allow-local]
Writes one ux-page-read.v1 document to FILE (or stdout). Exit 0 read, 3 stopped at a
browser or human check, 2 usage or refused address, 4 unread.
--max-wait-ms is accepted for compatibility; checks are never waited out.`;

class Usage extends Error {}

function parseArgs(argv) {
  const out = { url: null, out: null, device: 'desktop-1920', maxWait: WAIT_CAP_MS, scrolls: 8, timeoutS: 30, allowLocal: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const val = () => {
      if (i + 1 >= argv.length) throw new Usage(`${a} needs a value`);
      return argv[++i];
    };
    const int = (name, lo, hi) => {
      const v = Number(val());
      if (!Number.isInteger(v) || v < lo || v > hi) throw new Usage(`${name} must be an integer within ${lo}..${hi}`);
      return v;
    };
    if (a === '--out') out.out = val();
    else if (a === '--device') out.device = val();
    else if (a === '--max-wait-ms') out.maxWait = int(a, 0, WAIT_CAP_MS);
    else if (a === '--scrolls') out.scrolls = int(a, 0, SCROLL_CAP);
    else if (a === '--timeout-s') out.timeoutS = int(a, 5, 120);
    else if (a === '--allow-local') out.allowLocal = true;
    else if (a === '--help' || a === '-h') throw new Usage('');
    else if (a.startsWith('--')) throw new Usage(`unknown option ${a}`);
    else if (!out.url) out.url = a;
    else throw new Usage(`unexpected argument ${a}`);
  }
  if (!out.url) throw new Usage('URL is required');
  if (!CATALOG.has(out.device)) throw new Usage(`unknown device ${out.device}`);
  return out;
}

/** Loopback, private, link-local and unspecified addresses are refused unless --allow-local. */
function isLocalHost(host) {
  const h = host.replace(/^\[|\]$/g, '').toLowerCase();
  if (h === 'localhost' || h.endsWith('.localhost') || h.endsWith('.local') || h.endsWith('.internal')) return true;
  if (net.isIPv4(h)) {
    const [a, b] = h.split('.').map(Number);
    return a === 10 || a === 127 || a === 0 || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168)
      || (a === 100 && b >= 64 && b <= 127);
  }
  if (net.isIPv6(h)) return h === '::1' || h === '::' || h.startsWith('fc') || h.startsWith('fd') || h.startsWith('fe80') || h.startsWith('::ffff:');
  return false;
}

function checkUrl(raw, allowLocal) {
  let u;
  try {
    u = new URL(raw);
  } catch {
    throw new Usage(`not a URL: ${raw}`);
  }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') throw new Usage(`only http and https URLs are read (${u.protocol})`);
  if (u.username || u.password) throw new Usage('URLs with credentials are refused');
  if (!allowLocal && isLocalHost(u.hostname)) throw new Usage(`refused: ${u.hostname} is a local or private address`);
  return u.href;
}

function loadMarkers() {
  try {
    const m = JSON.parse(fs.readFileSync(MARKERS, 'utf8'));
    const strings = (v) => Array.isArray(v) && v.every((s) => typeof s === 'string' && s.trim().length > 0);
    const pick = (k) => {
      const set = m && m[k];
      if (!set || typeof set !== 'object' || Array.isArray(set)
        || !strings(set.src) || !strings(set.idents)
        || (set.inputs !== undefined && !strings(set.inputs))
        || !set.words || typeof set.words !== 'object' || Array.isArray(set.words)
        || !Object.values(set.words).every(strings)) throw new Error(`invalid ${k} marker data`);
      const words = Object.values(set.words).flat();
      if (!set.src.length || !set.idents.length || !words.length) throw new Error(`empty ${k} marker data`);
      return { src: set.src, idents: set.idents, inputs: set.inputs || [], words };
    };
    const human = pick('human_check'), js = pick('js_check');
    if (typeof m.version !== 'string' || !m.version.trim()) throw new Error('missing markers version');
    const tokens = (k) => {
      const section = m[k];
      const list = Array.isArray(section) ? section : section?.tokens;
      if (!strings(list) || !list.length) throw new Error(`invalid or empty ${k} marker data`);
      return list.map((s) => s.toLowerCase());
    };
    const structure = { chrome: tokens('chrome_idents'), author: tokens('author_idents'),
      item: tokens('item_idents'), keep: tokens('keep_in_author_idents') };
    // privacy.profile_href also uses these packaged host/path shapes; route
    // overrides extend the same chrome/author tokens as extract._platform_tokens.
    const data = path.dirname(MARKERS);
    const suffixes = JSON.parse(fs.readFileSync(path.join(data, 'suffixes.json'), 'utf8'));
    const routes = JSON.parse(fs.readFileSync(path.join(data, 'routes.json'), 'utf8'));
    if (!Array.isArray(suffixes.path_hosted) || !strings(suffixes.profile_hosts) || !strings(suffixes.hosting_suffixes)
      || !Array.isArray(routes.platforms)) throw new Error('invalid profile URL data');
    const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const pathHosts = new Set([...suffixes.path_hosted.map((p) => p.host), ...suffixes.profile_hosts]);
    const subHosts = new Set(suffixes.hosting_suffixes);
    const parts = [];
    structure.overrides = [];
    for (const p of routes.platforms) {
      if (!strings(p.hosts)) throw new Error('invalid platform hosts');
      for (const h of p.hosts) {
        if (p.author_from === 'subdomain' && h.startsWith('*.')) subHosts.add(h.slice(2));
        else if (p.author_from === 'path_segment' && !h.startsWith('*.')) pathHosts.add(h);
      }
      const paths = (p.profile_paths || []).filter((s) => typeof s === 'string' && /^[\w.-]+$/.test(s));
      if (paths.length) for (const h of p.hosts.filter((s) => !s.startsWith('*.'))) {
        parts.push(`${esc(h)}/(?:${paths.map(esc).join('|')})/[^\\s<>\"'/)]+[^\\s<>\"')]*`);
      }
      if (p.drop !== undefined || p.author !== undefined) {
        if (!strings(p.drop || []) || !strings(p.author || [])) throw new Error('invalid platform structure tokens');
        structure.overrides.push({ hosts: p.hosts.map((h) => h.toLowerCase()),
          drop: (p.drop || []).map((s) => s.toLowerCase()), author: (p.author || []).map((s) => s.toLowerCase()) });
      }
    }
    for (const h of pathHosts) {
      if (typeof h !== 'string' || !h) throw new Error('invalid profile host');
      parts.push(`(?:www\\.|m\\.)?${esc(h)}/[^\\s<>\"'/)]+[^\\s<>\"')]*`);
    }
    for (const h of subHosts) parts.push(`[a-z0-9-]+(?:\\.[a-z0-9-]+)*\\.${esc(h)}(?![a-z0-9.-])(?:/[^\\s<>\"')]*)?`);
    structure.profilePatterns = [String.raw`^https?://[^\s<>"')]+/(?:@[\p{L}\p{N}_.-]+|(?:user|users|u|profile|profiles|member|members|people|author|authors|mypage)/[^\s<>"')]*)`,
      `^https?://(?:${parts.join('|')})`];
    return { human, js, version: m.version, structure };
  } catch (err) {
    throw new Error(`cannot read or parse challenge markers at ${MARKERS}: ${err.message}`);
  }
}

/** In-page: which challenge markers are present (scripts, frames, ids, classes, inputs, visible text). */
function findMarkers(markers) {
  if (markers.watch) {
    if (window !== window.top) return;
    // Use the same detector while navigation/load/scroll is pending, so a late
    // check cannot disappear during a wait and be mistaken for an open page.
    const inspect = () => {
      const hits = findMarkers({ human: markers.human, js: markers.js });
      if (hits.human.length || hits.js.length) {
        observer.disconnect();
        window[markers.binding](hits).catch(() => {});
      }
    };
    const observer = new MutationObserver(inspect);
    observer.observe(document, { subtree: true, childList: true, attributes: true, characterData: true });
    window.addEventListener('load', inspect, { once: true });
    window.addEventListener('scroll', inspect, { passive: true });
    inspect();
    return;
  }
  const lower = (s) => String(s || '').toLowerCase();
  const text = lower(document.body ? document.body.innerText : '').slice(0, 20000);
  const srcs = [...document.querySelectorAll('script[src], iframe[src]')].map((n) => lower(n.getAttribute('src')));
  const idents = [];
  for (const n of document.querySelectorAll('[id], [class]')) {
    if (n.id) idents.push(lower(n.id));
    for (const c of n.classList || []) idents.push(lower(c));
    if (idents.length > 5000) break;
  }
  const inputs = [...document.querySelectorAll('input[name], textarea[name]')].map((n) => lower(n.getAttribute('name')));
  const hits = (set) => {
    const out = [];
    for (const s of set.src) if (srcs.some((x) => x.includes(lower(s)))) out.push(`src:${s}`);
    for (const s of set.idents) if (idents.includes(lower(s))) out.push(`ident:${s}`);
    for (const s of set.inputs) if (inputs.includes(lower(s))) out.push(`input:${s}`);
    for (const s of set.words) if (text.includes(lower(s))) out.push(`word:${s}`);
    return out;
  };
  return { human: hits(markers.human), js: hits(markers.js) };
}

async function main() {
  let args;
  try {
    args = parseArgs(process.argv.slice(2));
    args.url = checkUrl(args.url, args.allowLocal);
  } catch (err) {
    if (!(err instanceof Usage)) throw err;
    if (err.message) process.stderr.write(`read_page: ${err.message}\n`);
    process.stderr.write(`${USAGE}\n`);
    return 2;
  }
  const report = (exit, extra) => process.stdout.write(`${JSON.stringify({ event: 'read_page', exit, url: args.url, ...extra })}\n`);
  let markers;
  try {
    markers = loadMarkers();
  } catch (err) {
    report(4, { reason: 'invalid_markers', detail: err.message });
    return 4;
  }
  let pw;
  let pwInfo;
  try {
    ({ pw, info: pwInfo } = loadPlaywright());
  } catch (err) {
    report(4, { reason: 'no_browser', detail: String(err.message).slice(0, 300) });
    return 4;
  }
  const dev = CATALOG.get(args.device);
  const startedAt = isoNow();
  let browser = null;
  let transport = null;
  let context = null;
  try {
    transport = await openBrowser(pw, pwInfo, { headless: true, timeout: 60000 });
    browser = transport.browser;
    // Viewport only: the browser keeps its own user agent (no disguise).
    context = await browser.newContext({
      viewport: { width: dev.viewport_css[0], height: dev.viewport_css[1] },
      deviceScaleFactor: dev.dpr,
      hasTouch: hasTouch(dev),
      isMobile: isMobile(dev),
      serviceWorkers: 'block',
      acceptDownloads: false,
      javaScriptEnabled: true,
    });
    await context.route('**/*', (route) => (BLOCKED.includes(route.request().resourceType()) ? route.abort() : route.continue()));
    let observed = null;
    let stopCheck;
    const checkSeen = new Promise((resolve) => { stopCheck = resolve; });
    await context.exposeBinding(CHECK_BINDING, (source, hits) => {
      if (source.frame.parentFrame() || !hits || !Array.isArray(hits.human) || !Array.isArray(hits.js)
        || ![...hits.human, ...hits.js].every((s) => typeof s === 'string') || (!hits.human.length && !hits.js.length)) return;
      observed = { human: [...new Set([...(observed?.human || []), ...hits.human])],
        js: [...new Set([...(observed?.js || []), ...hits.js])] };
      stopCheck();
    });
    await context.addInitScript(findMarkers, { ...markers, watch: true, binding: CHECK_BINDING });
    const page = await context.newPage();
    page.on('dialog', (d) => d.dismiss().catch(() => {}));
    let response;
    page.on('response', (r) => {
      const req = r.request();
      if (req.isNavigationRequest() && req.frame() === page.mainFrame()) response = r;
    });
    try {
      const navigated = await Promise.race([
        page.goto(args.url, { waitUntil: 'domcontentloaded', timeout: args.timeoutS * 1000 }),
        checkSeen.then(() => null),
      ]);
      if (navigated) response = navigated;
    } catch (err) {
      report(4, { reason: 'navigation_failed', detail: String(err.message).split('\n')[0].slice(0, 300) });
      return 4;
    }
    if (!response) {
      report(4, { reason: 'no_document' });
      return 4;
    }
    const hasCheck = (hits) => hits.human.length > 0 || hits.js.length > 0;
    // Inspect before any load wait: a self-clearing check is still a stop.
    const inspect = async () => {
      if (observed) return observed;
      const hits = await page.evaluate(findMarkers, markers);
      return observed || hits;
    };
    let found = await inspect();
    if (!hasCheck(found)) {
      await Promise.race([page.waitForLoadState('load', { timeout: 5000 }).catch(() => {}), checkSeen]);
      found = await inspect();
    }
    const redirects = [];
    for (let req = response.request().redirectedFrom(); req && redirects.length < 20; req = req.redirectedFrom()) {
      const r = await req.response().catch(() => null);
      redirects.unshift({ status: r ? r.status() : 0, url: req.url().slice(0, 8192) });
    }
    let scrolls = 0;
    if (!hasCheck(found)) {
      for (; scrolls < args.scrolls;) {
        found = await inspect();
        if (hasCheck(found)) break;
        const atEnd = await page.evaluate(() => {
          const before = window.scrollY;
          window.scrollBy(0, Math.max(200, Math.floor(window.innerHeight * 0.9)));
          return window.scrollY === before || window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
        });
        scrolls += 1;
        found = await inspect();
        if (hasCheck(found)) break;
        await Promise.race([sleep(SCROLL_PAUSE_MS), checkSeen]);
        found = await inspect();
        if (hasCheck(found) || atEnd) break;
      }
    }
    if (!hasCheck(found)) found = await inspect();
    // A stopped page contributes only navigation and challenge metadata.
    const emptyCapture = { title: '', lang: '', text: '', json_ld: [], og: {}, login_form: false };
    let cap = hasCheck(found) ? emptyCapture
      : await page.evaluate(capturePage, { blocks: JSON_LD_MAX_BLOCKS, chars: JSON_LD_MAX_CHARS, structure: markers.structure });
    let headers = hasCheck(found) ? {} : await response.allHeaders().catch(() => ({}));
    if (!hasCheck(found)) found = await inspect();
    const stopped = hasCheck(found);
    const interactive = found.human.length > 0;
    if (stopped) { cap = emptyCapture; headers = {}; }
    const tdm = cap.tdm ?? (headers['tdm-reservation'] !== undefined ? String(headers['tdm-reservation']) : null);
    const meta = { og: cap.og, tdm_reservation: tdm };
    if (cap.description) meta.description = cap.description.slice(0, 2000);
    if (cap.robots) meta.robots = cap.robots;
    const doc = {
      schema_version: 'ux-page-read.v1',
      url: args.url,
      final_url: page.url().slice(0, 8192),
      status: response.status(),
      redirects,
      title: cap.title,
      lang: cap.lang,
      text: cap.text.slice(0, TEXT_MAX),
      json_ld: cap.json_ld,
      meta,
      challenge: { interactive, markers: [...found.human, ...found.js].slice(0, 20).map((m) => m.slice(0, 100)) },
      login_form: cap.login_form,
      context: 'anonymous',
      waited_ms: 0,
      scrolls,
      blocked_types: BLOCKED,
      device_id: args.device,
      driver_version: `${DRIVER_VERSION}; markers/${markers.version}`,
      browser_connected: transport.connected,
      browser_version: transport.browserVersion,
      playwright_client_version: transport.playwrightVersion,
      started_at: startedAt,
      finished_at: isoNow(),
    };
    if (args.out) writeJsonAtomic(args.out, doc, 0o600);
    else process.stdout.write(`${JSON.stringify(doc)}\n`);
    const exit = stopped ? 3 : 0;
    if (args.out) report(exit, { out: args.out, status: doc.status, chars: doc.text.length, challenge: stopped, login_form: doc.login_form });
    return exit;
  } catch (err) {
    report(4, { reason: 'browser_error', detail: String(err.message).split('\n')[0].slice(0, 300) });
    return 4;
  } finally {
    if (transport) await transport.close([context]);
  }
}

main().then((code) => process.exit(code), (err) => {
  process.stderr.write(`read_page: unexpected error: ${err && err.stack ? err.stack : err}\n`);
  process.exit(4);
});
