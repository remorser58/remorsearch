#!/usr/bin/env node
// Self-test for drivers/web/ergo_drive.mjs.
//
// Serves fixtures/selftest.html from a local node:http server (127.0.0.1,
// ephemeral port), runs a scripted scenario on galaxy-s24 and desktop-1920,
// drives `serve` over HTTP, checks usage/blocked exits, and asserts the outputs
// against docs/ergonomic-swarm-spec.md (and ergoqa.snapshot.load_run_dir when
// Python and the ergoqa package are available). Prints PASS/FAIL/SKIP lines;
// exits 1 on any FAIL.
//
//   node drivers/web/selftest.mjs [--keep]

import { spawn, spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { CATALOG } from './devices.mjs';
import { openBrowser, validateBrowserWs } from './browser_transport.mjs';
import { loadPlaywright } from './playwright_loader.mjs';
import { capturePage } from './read_capture.mjs';
import { STATE_KEY, armBinaryControl, pageInit, extractSnapshot } from './page_scripts.mjs';
import { WebSession } from './session.mjs';
import { decodePng } from './png.mjs';
import { snapshotReply } from './serve.mjs';
import { normalizeAction, normalizeBuildId, normalizeScenario } from './validate.mjs';
import { writeJsonAtomic } from './util.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '..', '..');
const DRIVER = path.join(HERE, 'ergo_drive.mjs');
const CLIENT = path.join(HERE, 'drive_client.mjs');
const FIXTURE = path.join(HERE, 'fixtures', 'selftest.html');
const KNOWN_ROLES = new Set(['primary', 'destructive', 'critical_message', 'error_message', 'status', 'navigation', 'ad_like', 'hud', 'game_control', 'timed']);
const HEX = /^#[0-9a-f]{6}$/;
const ISO = /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/;

let failures = 0;
let passes = 0;
function check(name, cond, detail) {
  if (cond) {
    passes++;
    console.log(`PASS ${name}`);
  } else {
    failures++;
    console.log(`FAIL ${name}${detail !== undefined ? ` -- ${typeof detail === 'string' ? detail : JSON.stringify(detail)}` : ''}`);
  }
  return !!cond;
}
function skip(name, why) {
  console.log(`SKIP ${name} -- ${why}`);
}

// read_page.mjs fixtures (ux-page-read.v1): an article below the fold with JSON-LD and
// meta tags, redirects, persistent/self-clearing/late checks and a login form.
// Requests count images, check clearing and scrolls to verify stop behavior.
const READ_HITS = { image: 0, cleared: 0, navigations: 0, scrolls: {} };
const LABEL_FIXTURES = ['board-post-comments', 'store-reviews', 'blog-popular-sidebar', 'board-writer-links'];
const READ_PAGES = {
  ...Object.fromEntries(LABEL_FIXTURES.map((name) => [`/read/${name}.html`, fs.readFileSync(path.join(HERE, 'fixtures', `read-${name}.html`), 'utf8')])),
  '/read/structure.html': fs.readFileSync(path.join(HERE, 'fixtures', 'read_structure.html'), 'utf8'),
  '/read/body-chrome.html': '<!doctype html><body class="sidebar">BODY-CHROME-SENTINEL</body>',
  '/read/article.html': `<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>공개 후기 모음</title>
<meta name="description" content="가게 이용 후기"><meta property="og:title" content="후기 모음"><meta name="robots" content="index, follow">
<meta name="tdm-reservation" content="1">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Article","headline":"첫 주문 후기"}</script>
<script type="application/ld+json">{not json</script></head>
<body><h1>첫 주문 후기</h1><img src="/read/img.png" alt="사진"><div style="height:3000px">위쪽 본문</div>
<p id="late">아래쪽 본문</p><script>window.addEventListener('scroll',()=>{if(!document.getElementById('lazy')){const p=document.createElement('p');p.id='lazy';p.textContent='스크롤로 불러온 댓글';document.body.appendChild(p);}});</script></body></html>`,
  '/read/check.html': `<!doctype html><html><head><meta charset="utf-8"><title>Just a moment...</title></head>
<body><div id="cf-please-wait">Checking your browser before accessing the site.</div>
<script>setTimeout(()=>{fetch('/read/cleared');document.title='본문';document.body.innerHTML='<main>확인이 끝난 본문</main>';},1000);</script>
<script async src="/read/delayed.js"></script><div style="height:3000px"></div></body></html>`,
  '/read/persistent.html': `<!doctype html><html><body><div id="browser-check">Checking your browser</div>
<script type="application/ld+json">{"secret":"private page content"}</script><div style="height:3000px"></div>
<script>addEventListener('scroll',()=>fetch('/read/scroll-event?case=persistent'));</script></body></html>`,
  '/read/late-load.html': `<!doctype html><html><body><main>private page content</main><div style="height:3000px"></div>
<script>addEventListener('load',()=>{document.body.insertAdjacentHTML('afterbegin','<div id="browser-check">Checking your browser</div>');});
addEventListener('scroll',()=>fetch('/read/scroll-event?case=late-load'));</script>
<script async src="/read/delayed.js"></script></body></html>`,
  '/read/during-load.html': `<!doctype html><html><body><main>private page content</main><div style="height:3000px"></div>
<script>setTimeout(()=>{document.body.insertAdjacentHTML('afterbegin','<div id="browser-check">Checking your browser</div>');
setTimeout(()=>{fetch('/read/cleared');document.getElementById('browser-check').remove();},250);},200);</script>
<script async src="/read/delayed.js"></script></body></html>`,
  '/read/late-scroll.html': `<!doctype html><html><body><main>private page content</main><div style="height:3000px"></div>
<script>addEventListener('scroll',()=>{fetch('/read/scroll-event?case=late-scroll');
document.body.insertAdjacentHTML('afterbegin','<div id="browser-check" style="position:fixed;left:0;top:0">Checking your browser</div>');});</script></body></html>`,
  '/read/late-human-scroll.html': `<!doctype html><html><body><main>private page content</main><div style="height:3000px"></div>
<script>addEventListener('scroll',()=>{fetch('/read/scroll-event?case=late-human-scroll');
document.body.insertAdjacentHTML('afterbegin','<div class="g-recaptcha" style="position:fixed;left:0;top:0"></div>');});</script></body></html>`,
  '/read/transient-scroll.html': `<!doctype html><html><body><main>private page content</main><div style="height:3000px"></div>
<script>addEventListener('scroll',()=>{fetch('/read/scroll-event?case=transient-scroll');
document.body.insertAdjacentHTML('afterbegin','<div id="browser-check" style="position:fixed;left:0;top:0">Checking your browser</div>');
setTimeout(()=>{fetch('/read/cleared');document.getElementById('browser-check').remove();},250);});</script></body></html>`,
  '/read/captcha.html': `<!doctype html><html><head><meta charset="utf-8"><title>확인</title></head>
<body><div class="g-recaptcha"></div><p>I'm not a robot</p><div style="height:3000px"></div></body></html>`,
  '/read/login.html': `<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>로그인</title></head>
<body><form><input name="id" aria-label="아이디"><input type="password" aria-label="비밀번호"><button>로그인</button></form></body></html>`,
  '/read/storage.html': '<!doctype html><html><body>Connection isolation fixture</body></html>',
  '/task-integrity.html': `<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>과업 값 검사</title></head><body>
<label for="memo">요청사항</label><input id="memo" aria-describedby="memo-help"><p id="memo-help">입력 안내</p><p id="summary">없음</p>
<label><input id="option" type="checkbox">선택</label><input id="masked" type="password"><input id="hidden" type="hidden">
<p class="ambiguous">첫째</p><p class="ambiguous">둘째</p>
<button id="copy" onclick="document.getElementById('summary').innerText=document.getElementById('memo').value">저장</button>
<button id="lose" onclick="document.getElementById('memo').value=''">손실</button>
<button id="reset" onclick="document.getElementById('memo').value=''">초기화</button>
<button id="normalize" onclick="document.getElementById('memo').value=document.getElementById('memo').value.trim().toUpperCase()">정규화</button>
<button id="done" onclick="document.getElementById('summary').innerText=document.getElementById('memo').value;document.getElementById('memo').value=''">완료</button>
<button id="echo" onclick="document.getElementById('memo-help').innerText=document.getElementById('memo').value">설명</button>
<input id="unrelated" value="unrelated-owned-fixture" aria-label="다른 입력">
<label for="choice">선택 유형</label><select id="choice"><option value="CHOICE-PRIVATE-51983">비공개 선택</option></select>
<div style="opacity:0"><input id="transparent" value="stable fixture"></div>
<div id="private-region"></div><input id="secret-field" type="password" value="PASSWORD-PRIVATE-31984">
<button id="echo-PASSWORD-PRIVATE-31984">보호된 식별자</button>
<script>document.getElementById('private-region').attachShadow({mode:'open'}).innerHTML='<label>보호된 입력<input value="SHADOW-PRIVATE-48152"></label><p>SHADOW-PRIVATE-DISPLAY-51984</p>';</script>
</body></html>`,
  '/task-integrity-timing.html': `<!doctype html><html><head><title>Owned capture timing fixture</title></head><body>
<p id="display">retained</p><button id="switch">Trigger owned transition</button>
<div role="dialog" aria-modal="true" id="dialog" hidden><button>Dialog control</button></div>
<script>
const display=document.getElementById('display'); let armed=false;
const unstable=new URLSearchParams(location.search).has('unstable');
Object.defineProperty(display,'innerText',{get(){const value=display.textContent;
  if(unstable&&armed){armed=false;setTimeout(()=>display.textContent='changed',0);}return value;}});
document.getElementById('switch').onclick=()=>{document.getElementById('dialog').hidden=false;
  if(unstable)armed=true;else setTimeout(()=>display.textContent='changed',400);};
</script></body></html>`,
};

function readFixture(pathname, res, req) {
  if (pathname === '/read/delayed.js') {
    const timer = setTimeout(() => {
      res.writeHead(200, { 'Content-Type': 'text/javascript', 'Cache-Control': 'no-store' });
      res.end('// delayed load fixture');
    }, 2000);
    res.on('close', () => clearTimeout(timer));
    return;
  }
  if (pathname === '/read/cleared' || pathname === '/read/scroll-event') {
    if (pathname === '/read/cleared') READ_HITS.cleared += 1;
    else {
      const name = new URL(req.url, 'http://127.0.0.1').searchParams.get('case');
      READ_HITS.scrolls[name] = (READ_HITS.scrolls[name] || 0) + 1;
    }
    res.writeHead(204);
    res.end();
    return;
  }
  READ_HITS.navigations += 1;
  if (pathname === '/read/article.html') READ_HITS.ua = req.headers['user-agent'];
  if (pathname === '/read/redirect') {
    res.writeHead(302, { Location: '/read/article.html' });
    res.end();
    return;
  }
  if (pathname === '/read/img.png') {
    READ_HITS.image += 1;
    res.writeHead(200, { 'Content-Type': 'image/png' });
    res.end(Buffer.alloc(0));
    return;
  }
  const body = READ_PAGES[pathname];
  res.writeHead(body ? 200 : 404, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(body || 'not found');
}

// Fixture files served at /<name> (same origin as the pages, no CORS headers).
const FIXTURE_FILES = Object.fromEntries(['layers.html', 'dialog.html', 'reflow.html', 'reflow2.html', 'reflow2.css', 'reflow_adaptation.html', 'viewport.html', 'focus.html', 'focus2.html', 'feedback_ambient.html', 'native_feedback.html', 'inspect.html', 'painted_state.html', 'typography.html']
  .map((f) => [`/${f}`, f]));

function startFixtureServer() {
  const html = fs.readFileSync(FIXTURE);
  const server = http.createServer((req, res) => {
    const { pathname } = new URL(req.url, 'http://127.0.0.1');
    if (req.method === 'GET' && pathname === '/selftest.html') {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
      res.end(html);
      return;
    }
    if (req.method === 'GET' && (pathname.startsWith('/read/') || pathname === '/task-integrity.html' || pathname === '/task-integrity-timing.html')) {
      readFixture(pathname, res, req);
      return;
    }
    const file = FIXTURE_FILES[pathname];
    if (req.method === 'GET' && file) {
      res.writeHead(200, { 'Content-Type': file.endsWith('.css') ? 'text/css; charset=utf-8' : 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
      res.end(fs.readFileSync(path.join(path.dirname(FIXTURE), file)));
      return;
    }
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    res.end('not found');
  });
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server)));
}

function runDriver(args, { timeoutMs = 120000, onLine, env = process.env, script = DRIVER } = {}) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [script, ...args], { stdio: ['ignore', 'pipe', 'pipe'], env });
    let out = '';
    let err = '';
    const lines = [];
    let buf = '';
    child.stdout.on('data', (d) => {
      out += d;
      buf += d;
      let i;
      while ((i = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, i);
        buf = buf.slice(i + 1);
        try {
          const obj = JSON.parse(line);
          lines.push(obj);
          if (onLine) onLine(obj);
        } catch { /* not JSON */ }
      }
    });
    child.stderr.on('data', (d) => { err += d; });
    const timer = setTimeout(() => child.kill('SIGKILL'), timeoutMs);
    child.on('close', (code) => {
      clearTimeout(timer);
      resolve({ code, out, err, lines });
    });
  });
}

function request(port, method, pathname, { body, headers = {} } = {}) {
  return new Promise((resolve, reject) => {
    const data = body === undefined ? null : (typeof body === 'string' ? body : JSON.stringify(body));
    const req = http.request({
      host: '127.0.0.1',
      port,
      method,
      path: pathname,
      headers: {
        ...(data !== null ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } : {}),
        ...headers,
      },
    }, (res) => {
      let text = '';
      res.on('data', (d) => { text += d; });
      res.on('end', () => {
        let json = null;
        try {
          json = JSON.parse(text);
        } catch { /* keep null */ }
        resolve({ status: res.statusCode, json, text });
      });
    });
    req.on('error', reject);
    if (data !== null) req.write(data);
    req.end();
  });
}

function scenario() {
  return {
    schema_version: 'ergo-scenario.v1',
    scenario_id: 'SC-driver-selftest-01',
    surface: { kind: 'web', url: '{BASE}/selftest.html' },
    task_goal_ko: '카드 번호를 입력하고 결제를 완료한다',
    device_ids: ['galaxy-s24', 'desktop-1920'],
    targets: {
      primary: ['#pay'],
      destructive: ['#delete-all'],
      critical_message: ['#error'],
      game_control: ['hotspot:hs-static'],
      timed: [],
    },
    steps: [
      { action: 'wait', ms: 200 },
      { action: 'tap', target: '#pay' },
      { action: 'type', target: '#card', text: '1234 5678 9012 3456' },
      { action: 'tap', target: 'hotspot:hs-jump' },
      { action: 'tap', target: '#plain-text' },
      { action: 'tap', target: '#start-qte' },
      { action: 'wait', ms: 1400 },
      { action: 'tap', target: '#below' },
      { action: 'tap', target: 'text=결제하기' },
      { action: 'tap', target: '#flash-btn' },
    ],
    timing_windows: [{ id: 'qte-1', selector: '#qte', measure: 'visible_duration', kind: 'qte' }],
    success: { selector_visible: '#done', text_present: '결제 완료', url_contains: 'selftest' },
    hotspots: [{ id: 'hs-static', name: '정적 핫스팟', box: { x: 10, y: 10, w: 40, h: 40 }, roles: ['game_control'] }],
  };
}

function profile(id, deviceId) {
  return {
    schema_version: 'ergo-profile.v1',
    profile_id: id,
    origin: 'manual',
    label_ko: '드라이버 자체 시험',
    attributes: {
      age_band: '30s', handedness: 'right', grip: deviceId.startsWith('desktop') ? 'mouse_right' : 'one_hand_right',
      thumb_length_mm: 62, hand_percentile: 50, device_id: deviceId, orientation: deviceId.startsWith('desktop') ? 'landscape' : 'portrait',
      vision: { acuity: 'normal', presbyopia: false, cvd: 'none', cvd_severity: 0, viewing_distance_mm: 300 },
      motor: { tremor: 'none', touch_sigma_mm: 1.5 },
      context: { mobility: 'seated', lighting: 'indoor', free_hands: 1, interruptions: false },
      cognition: { familiarity: 'first_use', time_pressure: 'low', reading_wpm_ko: 0 },
      reaction_time_ms: 250,
    },
    assumption_fields: ['handedness', 'grip', 'device_id'],
  };
}

function writeJson(file, obj) {
  fs.writeFileSync(file, `${JSON.stringify(obj, null, 2)}\n`);
}

function loadRun(runDir) {
  const run = JSON.parse(fs.readFileSync(path.join(runDir, 'run.json'), 'utf8'));
  check(`${path.basename(runDir)}: browser transport and versions recorded`,
    run.driver.browser_connected === (process.env.REMORSEARCH_BROWSER_WS !== undefined)
    && typeof run.driver.browser_version === 'string' && run.driver.browser_version.length > 0
    && run.driver.playwright_client_version === '1.56.1', run.driver);
  const snaps = new Map();
  for (const s of run.snapshots || []) snaps.set(s.snapshot_id, JSON.parse(fs.readFileSync(path.join(runDir, s.path), 'utf8')));
  return { run, snaps };
}

const byId = (snap, id) => snap.elements.find((e) => e.id === id);
const bySel = (snap, sel) => snap.elements.find((e) => e.selector === sel);
const near = (a, b, tol) => typeof a === 'number' && Math.abs(a - b) <= tol;
function hexNear(hex, want, tol) {
  if (typeof hex !== 'string' || !HEX.test(hex)) return false;
  for (let i = 1; i < 7; i += 2) {
    if (Math.abs(parseInt(hex.slice(i, i + 2), 16) - parseInt(want.slice(i, i + 2), 16)) > tol) return false;
  }
  return true;
}
const inside = (p, b) => p && b && p.x >= b.x && p.x <= b.x + b.w && p.y >= b.y && p.y <= b.y + b.h;

function pythonAvailable() {
  const r = spawnSync('python3', ['-c', 'import ergoqa.snapshot, ergoqa.devices'], { cwd: REPO, encoding: 'utf8' });
  return r.status === 0;
}

function pythonLoadRun(label, runDir) {
  if (!pythonAvailable()) {
    skip(`${label}: ergoqa.snapshot.load_run_dir accepts the run`, 'python3 or ergoqa not importable');
    return;
  }
  const r = spawnSync('python3', ['-c', [
    'import sys',
    'from ergoqa.snapshot import load_run_dir',
    'run, snaps = load_run_dir(sys.argv[1])',
    'print(len(snaps))',
  ].join('\n'), runDir], { cwd: REPO, encoding: 'utf8' });
  check(`${label}: ergoqa.snapshot.load_run_dir accepts the run (schema, hashes, PNG sizes)`, r.status === 0, (r.stderr || '').trim().split('\n').slice(-1)[0]);
}

function checkSnapshotFiles(label, runDir, run, snaps, dev) {
  const ew = Math.round(dev.vw * dev.dpr);
  const eh = Math.round(dev.vh * dev.dpr);
  let shapeOk = true;
  let pngOk = true;
  let elemOk = true;
  let firstBad = null;
  for (const [id, s] of snaps) {
    for (const k of ['schema_version', 'snapshot_id', 'run_id', 'step_index', 'captured_at', 'surface', 'device', 'screenshot', 'elements', 'focus_point', 'console_errors', 'notes']) {
      if (!(k in s)) {
        shapeOk = false;
        firstBad = firstBad || `${id} missing ${k}`;
      }
    }
    if (s.schema_version !== 'ergo-snapshot.v1' || s.snapshot_id !== id || s.run_id !== run.run_id || !ISO.test(s.captured_at) || s.surface.kind !== 'web') {
      shapeOk = false;
      firstBad = firstBad || `${id} header`;
    }
    let expectedHeight = eh;
    const viewport = s.device?.viewport_css;
    let deviceOk = s.device?.id === dev.id && s.device?.dpr === dev.dpr && s.device?.orientation === dev.orientation
      && viewport?.[0] === dev.vw && viewport?.[1] === dev.vh;
    if (s.device?.probe === 'adaptation') {
      const record = (run.adaptation || []).find((r) => r.baseline_snapshot_id === id || r.snapshot_id === id);
      const baseline = record?.baseline_snapshot_id === id;
      const source = snaps.get(record?.source_snapshot_id);
      const kind = baseline ? 'baseline' : record?.kind;
      const condition = record?.condition;
      const short = kind === 'short_height';
      const expectedCssHeight = short ? Math.max(256, Math.floor(dev.vh * 0.5)) : dev.vh;
      const knownCondition = record?.kind === 'short_height'
        ? condition?.height_ratio === 0.5 && condition?.min_height_css === 256
        : record?.kind === 'text_spacing' && condition?.line_height === 1.5 && condition?.paragraph_after === 2
          && condition?.letter_spacing === 0.12 && condition?.word_spacing === 0.16 && condition?.preserve_larger === true;
      deviceOk = !!record && !!source && source.device?.probe !== 'adaptation' && knownCondition
        && s.adaptation?.kind === kind && s.adaptation?.source_snapshot_id === source.snapshot_id
        && JSON.stringify(s.adaptation?.condition) === JSON.stringify(baseline ? null : condition)
        && record.dpr === dev.dpr && record.baseline_viewport_css?.[0] === dev.vw && record.baseline_viewport_css?.[1] === dev.vh
        && record.viewport_css?.[0] === dev.vw && record.viewport_css?.[1] === (record.kind === 'short_height' ? Math.max(256, Math.floor(dev.vh * 0.5)) : dev.vh)
        && s.device.id === dev.id && s.device.orientation === dev.orientation && s.device.dpr === dev.dpr
        && viewport?.[0] === dev.vw && viewport?.[1] === expectedCssHeight;
      expectedHeight = Math.round(expectedCssHeight * dev.dpr);
    }
    if (!deviceOk || (!!s.adaptation && s.device?.probe !== 'adaptation')) {
      shapeOk = false;
      firstBad = firstBad || `${id} device/auxiliary condition`;
    }
    const pngPath = path.join(runDir, s.screenshot.path);
    const buf = fs.existsSync(pngPath) ? fs.readFileSync(pngPath) : null;
    if (!buf || crypto.createHash('sha256').update(buf).digest('hex') !== s.screenshot.sha256
      || buf.readUInt32BE(16) !== ew || buf.readUInt32BE(20) !== expectedHeight || s.screenshot.width_px !== ew || s.screenshot.height_px !== expectedHeight) {
      pngOk = false;
      firstBad = firstBad || `${id} png ${buf ? `${buf.readUInt32BE(16)}x${buf.readUInt32BE(20)}` : 'missing'} want ${ew}x${expectedHeight}`;
    }
    const ids = new Set();
    if (s.elements.length > 400) elemOk = false;
    for (const e of s.elements) {
      const good = typeof e.id === 'string' && !ids.has(e.id) && typeof e.role === 'string' && e.role.length > 0
        && e.box && ['x', 'y', 'w', 'h'].every((k) => Number.isFinite(e.box[k])) && e.box.w >= 0 && e.box.h >= 0
        && typeof e.interactive === 'boolean' && typeof e.visible === 'boolean' && typeof e.enabled === 'boolean' && typeof e.in_viewport === 'boolean'
        && Array.isArray(e.roles) && e.roles.every((r) => KNOWN_ROLES.has(r)) && ['dom', 'manual'].includes(e.source)
        && ['color_fg', 'color_bg', 'border_color'].every((k) => e[k] === null || HEX.test(e[k]))
        && (e.font_size_px === null || e.font_size_px > 0) && (e.font_weight === null || (e.font_weight >= 1 && e.font_weight <= 1000));
      if (!good) {
        elemOk = false;
        firstBad = firstBad || `${id} element ${JSON.stringify(e).slice(0, 200)}`;
      }
      ids.add(e.id);
    }
  }
  check(`${label}: every snapshot has the ergo-snapshot.v1 fields`, shapeOk, firstBad);
  check(`${label}: every PNG matches its sha256 and live or verified auxiliary viewport*dpr`, pngOk, firstBad);
  check(`${label}: every element has typed fields, known roles, hex colours, <= 400 per snapshot`, elemOk, firstBad);
}

function checkScripted(label, runDir, dev, { flash }) {
  const { run, snaps } = loadRun(runDir);
  const sc = scenario();
  check(`${label}: run.json header (schema, ids, driver, device, mode, timestamps)`,
    run.schema_version === 'ergo-run.v1' && run.scenario_id === sc.scenario_id && typeof run.profile_id === 'string'
    && run.driver.name === 'playwright-web' && run.driver.version === '1.56.1' && run.driver.browser === 'chromium'
    && run.device.id === dev.id && run.device.viewport_css[0] === dev.vw && run.device.viewport_css[1] === dev.vh
    && run.device.dpr === dev.dpr && run.device.orientation === dev.orientation && run.mode === 'scripted'
    && ISO.test(run.started_at) && ISO.test(run.ended_at), { driver: run.driver.version, device: run.device });
  check(`${label}: status completed and success true (measured)`, run.status === 'completed' && run.success === true && run.success_basis === 'measured',
    { status: run.status, success: run.success, detail: run.success_detail, warnings: run.warnings });
  check(`${label}: one step record per scenario step`, run.steps.length === sc.steps.length, run.steps.length);
  let stepsOk = true;
  let prevEnd = -1;
  for (const s of run.steps) {
    const keys = ['step_index', 'action', 'target_element_id', 'point', 'before', 'after', 't_start_ms', 't_end_ms', 'feedback_latency_ms', 'result', 'error'];
    if (!keys.every((k) => k in s) || !snaps.has(s.before) || !snaps.has(s.after) || !(s.t_end_ms >= s.t_start_ms) || s.t_start_ms < prevEnd || s.result !== 'ok') {
      stepsOk = false;
    }
    prevEnd = s.t_end_ms;
  }
  check(`${label}: steps have spec fields, existing before/after snapshots, ordered timing, result ok`, stepsOk,
    run.steps.map((s) => [s.step_index, s.result, s.error]));
  checkSnapshotFiles(label, runDir, run, snaps, dev);

  const s0 = snaps.get(run.snapshots[0].snapshot_id);
  check(`${label}: first snapshot is step 0 with focus_point null`, s0.step_index === 0 && s0.focus_point === null);
  const pay = bySel(s0, '#pay');
  check(`${label}: #pay extracted as primary button with geometry, font and colours`,
    pay && pay.roles.join() === 'primary' && pay.interactive && pay.visible && pay.in_viewport && pay.enabled
    && pay.tag === 'button' && pay.role === 'button' && pay.name === '결제하기' && pay.box.x >= 0 && pay.box.x + pay.box.w <= dev.vw
    && near(pay.box.h, 48, 1) && pay.box.w > 100 && pay.font_size_px === 16 && pay.font_weight === 700
    && pay.color_fg === '#ffffff' && pay.color_bg === '#1a73e8', pay);
  const del = bySel(s0, '#delete-all');
  check(`${label}: #delete-all has role destructive and a border colour`, del && del.roles.join() === 'destructive' && del.border_color === '#d93025', del);
  const err0 = bySel(s0, '#error');
  check(`${label}: hidden #error is listed (visible false) with target + data-ergo-role roles`,
    err0 && err0.visible === false && err0.roles.includes('critical_message') && err0.roles.includes('error_message') && err0.role === 'alert', err0);
  check(`${label}: rgba(0,0,0,.5) over white composites to #808080`, hexNear(bySel(s0, '#overlay-label')?.color_bg, '#808080', 1), bySel(s0, '#overlay-label'));
  check(`${label}: gradient background gives color_bg null`, bySel(s0, '#grad') && bySel(s0, '#grad').color_bg === null);
  const faded = bySel(s0, '#faded');
  check(`${label}: opacity .5 disabled button composites to #8db9f4 / #ffffff, enabled false`,
    faded && hexNear(faded.color_bg, '#8db9f4', 2) && faded.color_fg === '#ffffff' && faded.enabled === false, faded);
  check(`${label}: input border colour #c4c4c4 and accessible name from <label>`,
    bySel(s0, '#card')?.border_color === '#c4c4c4' && bySel(s0, '#card')?.name === '카드 번호', bySel(s0, '#card'));
  const jump = byId(s0, 'hs-hs-jump');
  const stat = byId(s0, 'hs-hs-static');
  check(`${label}: page and scenario hotspots become source=manual elements with roles`,
    jump && jump.source === 'manual' && jump.roles.includes('game_control') && jump.selector === 'hotspot:hs-jump'
    && stat && stat.source === 'manual' && stat.roles.includes('game_control'), [jump, stat]);
  check(`${label}: canvas listed as interactive DOM element with unknown (null) background`,
    bySel(s0, '#game')?.interactive === true && bySel(s0, '#game')?.color_bg === null);

  // PNG decoder + geometry: the pixel at #pay's centre is #1a73e8.
  try {
    const img = decodePng(fs.readFileSync(path.join(runDir, s0.screenshot.path)));
    const cx = Math.round((pay.box.x + pay.box.w / 2) * dev.dpr);
    const cy = Math.round((pay.box.y + 6) * dev.dpr);
    const o = (cy * img.width + cx) * img.channels;
    const px = [img.data[o], img.data[o + 1], img.data[o + 2]];
    check(`${label}: decoded screenshot pixel inside #pay is #1a73e8 (box x dpr maps to device px)`,
      Math.abs(px[0] - 0x1a) <= 3 && Math.abs(px[1] - 0x73) <= 3 && Math.abs(px[2] - 0xe8) <= 3, px);
  } catch (err) {
    check(`${label}: decoded screenshot pixel inside #pay is #1a73e8`, false, err.message);
  }

  const [st1, st2, st3, st4, st5, , , st8, st9, st10] = run.steps;
  check(`${label}: wait step has no point and null latency`, st1.point === null && st1.feedback_latency_ms === null);
  const before2 = snaps.get(st2.before);
  const pay2 = bySel(before2, '#pay');
  check(`${label}: tap #pay point is the element centre and target_element_id matches the before snapshot`,
    pay2 && st2.target_element_id === pay2.id && near(st2.point.x, pay2.box.x + pay2.box.w / 2, 0.6) && near(st2.point.y, pay2.box.y + pay2.box.h / 2, 0.6) && st2.target_hit === true,
    { step: st2.point, id: st2.target_element_id, box: pay2 && pay2.box });
  check(`${label}: input kind is ${dev.input}`, st2.input === dev.input, st2.input);
  check(`${label}: feedback latency of the delayed (150 ms) error is measured from a DOM mutation`,
    st2.feedback_source === 'dom_mutation' && st2.feedback_latency_ms >= 120 && st2.feedback_latency_ms <= 1000, [st2.feedback_latency_ms, st2.feedback_source]);
  const after2 = snaps.get(st2.after);
  check(`${label}: #error visible after the tap, focus_point = tap point`,
    bySel(after2, '#error')?.visible === true && after2.focus_point && near(after2.focus_point.x, st2.point.x, 0.2) && near(after2.focus_point.y, st2.point.y, 0.2),
    { error: bySel(after2, '#error'), focus: after2.focus_point });
  check(`${label}: type step focuses #card by pointer and types`, st3.target_element_id === bySel(snaps.get(st3.before), '#card')?.id && /keyboard/.test(st3.input || ''), st3.input);
  const after4 = snaps.get(st4.after);
  check(`${label}: hotspot tap targets hs-hs-jump and reaches the canvas handler`,
    st4.target_element_id === 'hs-hs-jump' && bySel(after4, '#game-log')?.text === '점프 1회', { id: st4.target_element_id, log: bySel(after4, '#game-log')?.text });
  check(`${label}: console.error from the page appears in the after snapshot`,
    after4.console_errors.some((c) => String(c).includes('핫스팟')), after4.console_errors);
  check(`${label}: tap on inert text has feedback_latency_ms null after the 3000 ms window`,
    st5.feedback_latency_ms === null && st5.feedback_window_ms === 3000 && st5.feedback_source === null, [st5.feedback_latency_ms, st5.feedback_window_ms, st5.feedback_source]);
  const tw = run.timing_windows.find((w) => w.id === 'qte-1');
  check(`${label}: timing window measures both visible intervals (~400 ms, ~250 ms) with min/max`,
    tw && tw.intervals_ms.length === 2 && near(tw.intervals_ms[0], 400, 60) && near(tw.intervals_ms[1], 250, 60)
    && tw.visible_ms === Math.min(...tw.intervals_ms) && tw.max_visible_ms === Math.max(...tw.intervals_ms) && tw.text === '지금 누르세요!', tw);
  const pre8 = snaps.get(st8.before);
  check(`${label}: off-screen target is scrolled into view with a pre-action snapshot`,
    st8.auto_scrolled === true && pre8.notes.includes('pre_action_auto_scroll') && pre8.step_index === 8
    && st8.point.y >= 0 && st8.point.y < dev.vh && st8.target_hit === true && bySel(snaps.get(st8.after), '#below-status')?.text === '맨 아래 버튼을 눌렀습니다',
    { auto: st8.auto_scrolled, notes: pre8.notes, point: st8.point });
  check(`${label}: Playwright text= selector resolves to the #pay element id`,
    st9.target_element_id === bySel(snaps.get(st9.before), '#pay')?.id, st9.target_element_id);
  const last = snaps.get(run.steps[run.steps.length - 1].after);
  check(`${label}: success element #done is visible at the end`, bySel(last, '#done')?.visible === true);
  const payA = bySel(last, '#pay')?.a11y;
  const cardA = bySel(last, '#card')?.a11y;
  check(`${label}: controls carry a11y state (name source, focusable, ARIA links)`,
    payA && payA.name_source === 'content' && payA.focusable === true && payA.invalid === false && Array.isArray(payA.described_by)
    && cardA && cardA.name_source === 'label' && cardA.focusable === true, { payA, cardA });
  check(`${label}: off-origin image and WebSocket blocked by the network policy, no console noise`,
    run.driver.network_policy.blocked_requests >= 2
    && ['image', 'websocket'].every((t) => run.driver.network_policy.blocked_sample.some((b) => b.resource_type === t))
    && [...snaps.values()].every((s) => s.console_errors.every((c) => !/ERR_BLOCKED_BY_CLIENT|WebSocket/.test(String(c)))),
    run.driver.network_policy);
  if (flash) {
    const samples = run.flash_samples;
    const burst = samples.filter((s) => s.step_index === st10.step_index);
    const changed = burst.filter((s) => s.changed_fraction > 0.1).length;
    const monotonic = samples.every((s, i) => i === 0 || s.t_ms >= samples[i - 1].t_ms);
    check(`${label}: flash sampling records luminance frames (t_ms, mean_luminance 0..1, frame_index)`,
      run.flash_sampling.enabled && samples.length > 20 && monotonic
      && samples.every((s) => s.mean_luminance >= 0 && s.mean_luminance <= 1 && Number.isInteger(s.frame_index) && s.changed_fraction >= 0 && s.changed_fraction <= 1),
      { n: samples.length, sampling: run.flash_sampling });
    check(`${label}: 10 Hz black/white flicker shows >= 4 frames with >10% changed area`, changed >= 4, burst.map((s) => [s.t_ms, s.mean_luminance, s.changed_fraction]));
    const grid = run.flash_sampling.block_grid;
    const blocks = grid ? grid.cols * grid.rows : 0;
    const gridOk = grid && grid.cols >= 16 && grid.rows >= 8 && blocks <= 820
      && samples.every((s) => Buffer.from(s.block_lum || '', 'base64').length === blocks && Buffer.from(s.block_red || '', 'base64').length === blocks);
    check(`${label}: flash samples carry a block grid (block_lum, block_red: one byte per block)`, gridOk,
      grid && { cols: grid.cols, rows: grid.rows, block_css: grid.block_css, first: samples[0] && Object.keys(samples[0]) });
    const longWait = run.steps.find((s) => s.action?.action === 'wait' && s.action.ms >= 1000);
    const inWait = samples.filter((s) => s.step_index === longWait?.step_index);
    const waitSpan = inWait.length ? inWait[inWait.length - 1].t_ms - inWait[0].t_ms : 0;
    check(`${label}: flash sampling covers a wait step for its duration`, inWait.length >= 10 && waitSpan >= 0.7 * longWait.action.ms,
      { step: longWait?.step_index, n: inWait.length, span: waitSpan });
    const fs = run.flash_sampling;
    check(`${label}: flash_sampling records coverage and capture jitter`,
      fs.sampled_ms > 0 && fs.mean_fps > 0 && fs.max_gap_ms > 0 && Array.isArray(fs.jitter_ms) && fs.jitter_ms[1] > 0 && fs.truncated === null,
      { sampled_ms: fs.sampled_ms, mean_fps: fs.mean_fps, max_gap_ms: fs.max_gap_ms, jitter_ms: fs.jitter_ms, truncated: fs.truncated });
  } else {
    check(`${label}: flash sampling off by default`, run.flash_samples.length === 0 && run.flash_sampling.enabled === false);
  }
  pythonLoadRun(label, runDir);
}

function actionsScenario() {
  return {
    schema_version: 'ergo-scenario.v1',
    scenario_id: 'SC-driver-actions-01',
    surface: { kind: 'web', url: '{BASE}/selftest.html?panel=actions' },
    task_goal_ko: '제스처 입력이 페이지에 실제 이벤트로 도착하는지 확인한다',
    device_ids: ['iphone-15', 'tv-55-1080'],
    targets: {},
    steps: [
      { action: 'scroll', direction: 'down', distance: 300 },
      { action: 'scroll', dy: -300 },
      { action: 'long_press', target: '#lp-target', ms: 700 },
      { action: 'double_tap', target: '#dbl-target' },
      { action: 'drag', target: '#drag-handle', dx: 80, dy: 0 },
      { action: 'swipe', target: '#swipe-area', direction: 'left', distance: 120 },
      { action: 'press', key: 'ArrowRight' },
      { action: 'gamepad', button: 'A', key: 'Enter' },
      { action: 'tap', target: { x: 700, y: 300 } },
    ],
    success: { text_present: ['두 번 눌림', 'ArrowRight Enter'] },
  };
}

function checkActions(label, runDir, dev) {
  const { run, snaps } = loadRun(runDir);
  check(`${label}: device ${dev.id} ${dev.orientation} ${dev.vw}x${dev.vh}, completed, success`,
    run.device.id === dev.id && run.device.orientation === dev.orientation && run.device.viewport_css.join() === `${dev.vw},${dev.vh}`
    && run.status === 'completed' && run.success === true, { device: run.device, status: run.status, success: run.success, steps: run.steps.map((s) => [s.result, s.error]) });
  checkSnapshotFiles(label, runDir, run, snaps, dev);
  const [sc1, sc2, lp, dbl, drag, swipe, press, pad, pt] = run.steps;
  check(`${label}: scroll down/up 300 px measured in scroll_delta (+-6)`,
    near(sc1.scroll_delta?.y, 300, 6) && near(sc2.scroll_delta?.y, -300, 6), [sc1.scroll_delta, sc2.scroll_delta]);
  const pointer = dev.input;
  check(`${label}: pointer actions use ${pointer}, keys use keyboard / gamepad mapping`,
    [sc1, lp, dbl, drag, swipe, pt].every((s) => s.input === pointer) && press.input === 'keyboard' && pad.input === 'keyboard(gamepad-mapping)',
    run.steps.map((s) => s.input));
  if (pointer === 'mouse(fallback)') {
    check(`${label}: pointer fallback is reported in warnings`, run.warnings.some((w) => /no pointer/.test(w)), run.warnings);
  }
  check(`${label}: drag end_point = start + (80, 0)`, drag.end_point && near(drag.end_point.x - drag.point.x, 80, 0.5) && near(drag.end_point.y, drag.point.y, 0.5), [drag.point, drag.end_point]);
  const last = snaps.get(pt.after);
  const log = (sel) => bySel(last, sel)?.text || '';
  const lpMs = Number((log('#lp-log').match(/(\d+)ms/) || [])[1]);
  check(`${label}: long_press held >= 650 ms on the target`, lpMs >= 650 && lpMs <= 1500, log('#lp-log'));
  check(`${label}: double_tap produced a dblclick`, log('#dbl-log') === '두 번 눌림', log('#dbl-log'));
  const dragPx = Number((log('#drag-log').match(/-?\d+/) || [])[0]);
  check(`${label}: drag moved the handle ~80 px`, near(dragPx, 80, 10), log('#drag-log'));
  check(`${label}: swipe left reached the swipe area`, /^왼쪽/.test(log('#swipe-log')), log('#swipe-log'));
  check(`${label}: press and gamepad keys arrived`, log('#key-log') === 'ArrowRight Enter', log('#key-log'));
  check(`${label}: {x,y} target taps that point and becomes the focus_point`,
    pt.point.x === 700 && pt.point.y === 300 && last.focus_point && last.focus_point.x === 700 && last.focus_point.y === 300, [pt.point, last.focus_point]);
  pythonLoadRun(label, runDir);
}

async function toolingTest(base, tmp) {
  const noBrowserEnv = { ...process.env, REMORSEARCH_BROWSER_WS: 'invalid-browser-endpoint' };
  let r = await runDriver(['devices'], { env: noBrowserEnv });
  const rows = r.out.trim().split('\n').slice(1).map((line) => line.trim().split(/\s+/));
  check('devices: lists every ID, CSS viewport, DPR and input without connecting to a browser', r.code === 0 && rows.length === CATALOG.size
    && rows.every(([id, viewport, dpr, input]) => {
      const d = CATALOG.get(id);
      return d && viewport === d.viewport_css.join('x') && Number(dpr) === d.dpr && input === d.input;
    }), r.out);
  const sc = path.join(tmp, 'init.json');
  const url = `${base}/inspect.html`;
  r = await runDriver(['init', '--url', url, '--device', 'desktop-1920', '--task', 'Check required options and retain the order request.', '--out', sc], { env: noBrowserEnv });
  check('init: writes a scenario without connecting to a browser', r.code === 0 && fs.existsSync(sc), r.err);
  if (!fs.existsSync(sc)) return;
  const doc = JSON.parse(fs.readFileSync(sc, 'utf8'));
  let normalized;
  try { normalized = normalizeScenario(doc, { requireSteps: true }); } catch (err) { normalized = { error: err.message }; }
  check('init: all required fields are present and the driver validates the output', !normalized.error && normalized.warnings.length === 0
    && doc.surface.kind === 'web' && doc.surface.url === url && doc.task_goal_ko === 'Check required options and retain the order request.'
    && doc.device_ids[0] === 'desktop-1920' && Array.isArray(doc.steps) && doc.success === null, normalized);
  const buildId = `fixture-source-sha256:${crypto.createHash('sha256').update(fs.readFileSync(path.join(HERE, 'fixtures', 'inspect.html'))).digest('hex')}`;
  const versioned = { ...doc, surface: { ...doc.surface, build_id: buildId }, success: { selector_visible: '#request' } };
  check('build identity: scenario retains an explicit source identifier',
    normalizeScenario(versioned, { requireSteps: true }).scenario.build_id === buildId);
  for (const bad of [null, '', ' ', 'unknown', 'unrecorded', 'x\n', 42]) {
    let rejected = false;
    try { normalizeBuildId(bad); } catch { rejected = true; }
    check(`build identity: rejects ${JSON.stringify(bad)}`, rejected);
  }
  const versionedPath = path.join(tmp, 'versioned.json');
  writeJson(versionedPath, versioned);
  r = await runDriver(['run', '--scenario', versionedPath, '--profile', path.join(tmp, 'p-s24.json'),
    '--build-id', 'different-source', '--out', path.join(tmp, 'conflicting-runs'), '--run-id', 'R-conflict'], { env: noBrowserEnv });
  check('build identity: conflicting operator and scenario identities fail before browser or write',
    r.code === 2 && /conflicts/.test(r.err) && !fs.existsSync(path.join(tmp, 'conflicting-runs')), r.err);
  r = await runDriver(['run', '--scenario', versionedPath, '--profile', path.join(tmp, 'p-s24.json'),
    '--out', path.join(tmp, 'versioned-runs'), '--run-id', 'R-versioned', '--no-focus-walk', '--no-reflow']);
  if (check('build identity: profile-bearing scenario metadata records on a real surface', r.code === 0, r.err)) {
    const recorded = loadRun(path.join(tmp, 'versioned-runs', 'R-versioned'));
    check('build identity: run and every snapshot retain the source identifier and operator provenance',
      recorded.run.surface.build_id === buildId && recorded.run.surface.build_id_basis === 'operator_supplied'
      && recorded.run.surface.build_id_source === 'scenario.surface.build_id'
      && [...recorded.snaps.values()].every((s) => s.surface.build_id === buildId && s.surface.build_id_basis === 'operator_supplied'));
  }
  if (pythonAvailable()) {
    const py = spawnSync('python3', ['-c', 'import json, sys; from ergoqa.snapshot import validate_scenario; errors = validate_scenario(json.load(open(sys.argv[1]))); print(errors); sys.exit(bool(errors))', sc], { cwd: REPO, encoding: 'utf8' });
    check('init: Python scenario validator accepts the output', py.status === 0, `${py.stdout} ${py.stderr}`);
  } else skip('init: Python scenario validator accepts the output', 'python3 or ergoqa not importable');
  const original = fs.readFileSync(sc, 'utf8');
  r = await runDriver(['init', '--url', url, '--device', 'galaxy-s24', '--out', sc]);
  check('init: refuses to overwrite an existing scenario', r.code === 2 && /already exists/.test(r.err) && fs.readFileSync(sc, 'utf8') === original, r.err);
  const defaultSc = path.join(tmp, 'init-default.json');
  r = await runDriver(['init', '--url', url, '--device', 'galaxy-s24', '--out', defaultSc]);
  check('init: optional task has a non-empty default', r.code === 0 && JSON.parse(fs.readFileSync(defaultSc)).task_goal_ko.length > 0, r.err);
  for (const [name, args] of [
    ['missing URL', ['--device', 'galaxy-s24']],
    ['unknown device', ['--url', url, '--device', 'unknown-device']],
    ['invalid URL', ['--url', 'not-a-url', '--device', 'galaxy-s24']],
    ['empty task', ['--url', url, '--device', 'galaxy-s24', '--task', ' ']],
  ]) {
    const output = path.join(tmp, `bad-${name.replaceAll(' ', '-')}.json`);
    r = await runDriver(['init', ...args, '--out', output]);
    check(`init: rejects ${name} before writing`, r.code === 2 && !fs.existsSync(output), r.err);
  }

  const start = async (channel, runId) => {
    const agent = path.join(tmp, `${runId}-agent.json`);
    writeJson(agent, { model_family: 'selftest', input_channel: channel, persona_arm: 'neutral' });
    let resolveReady;
    const readyP = new Promise((resolve) => { resolveReady = resolve; });
    const proc = runDriver(['serve', '--scenario', sc, '--device', 'desktop-1920', '--agent-json', agent, '--out', path.join(tmp, 'runs'),
      '--run-id', runId, '--port', '0', '--no-focus-walk', '--no-reflow', '--idle-timeout-s', '60'], {
      onLine: (line) => { if (line.event === 'ready') resolveReady(line); },
    });
    proc.then(() => resolveReady(null));
    const guard = setTimeout(() => resolveReady(null), 60000);
    const ready = await readyP;
    clearTimeout(guard);
    return { ready, proc };
  };
  const { ready, proc } = await start('screenshot+a11y', 'R-client');
  if (!check('drive_client: serve starts on the form fixture', !!ready && ready.endpoints.includes('GET /inspect'), ready)) {
    console.log((await proc).err);
    return;
  }
  const client = async (name, body, port = ready.port) => {
    const reply = await runDriver(['--port', String(port), name, ...(body === undefined ? [] : [JSON.stringify(body)])], { script: CLIENT });
    return { ...reply, json: reply.lines[0] };
  };
  const act = async (body) => {
    const reply = await client('act', body);
    check(`drive_client: ${body.action} ${body.target || body.key || ''}`, reply.code === 0 && reply.json?.result === 'ok', reply.out || reply.err);
    return reply;
  };
  let state = await client('inspect');
  check('inspect: reads current state and saves private JSON evidence without taking an action', state.code === 0 && state.json?.source === 'dom'
    && state.json.step_index === 0 && fs.existsSync(state.json.inspection) && (fs.statSync(state.json.inspection).mode & 0o777) === 0o600, state.out);
  const firstOrder = state.json?.reading_order.map((f) => f.dom_id) || [];
  check('inspect: visible controls stay in document order even when CSS reverses their visual order', firstOrder.indexOf('reading-first') >= 0
    && firstOrder.indexOf('reading-first') < firstOrder.indexOf('reading-second') && !firstOrder.includes('hidden') && !firstOrder.includes('invisible')
    && !firstOrder.includes('zero-size') && firstOrder.includes('below'), firstOrder);
  check('inspect: includes fields in open shadow roots', state.json?.fields.some((f) => f.dom_id === 'shadow-request' && f.value === 'shadow-value'), state.out);
  for (const alias of ['health', 'observe', 'screenshot', 'snapshot']) {
    r = await client(alias);
    check(`drive_client: ${alias} returns JSON${alias === 'health' ? '' : ' with a screenshot path'}`, r.code === 0 && (alias === 'health'
      ? r.json?.ok && r.json.steps === 0 : r.json?.result === 'ok' && fs.existsSync(r.json.png) && r.json.step_index === 0), r.out);
  }
  await act({ action: 'type', target: '#request', text: 'No peanuts please' });
  await act({ action: 'tap', target: '#submit-associated' });
  state = await client('inspect');
  const part = state.json?.invalid_fields.find((f) => f.dom_id === 'part-group');
  check('inspect: submitting without a required option exposes its feedback and focus', state.code === 0 && state.json.focus.dom_id === 'part-a'
    && part?.aria_invalid === 'true' && part.described_by_text === 'Choose a part.' && part.error_associated === true, state.out);
  await act({ action: 'tap', target: '#part-a' });
  await act({ action: 'tap', target: '#terms' });
  await act({ action: 'tap', target: '#submit-associated' });
  state = await client('inspect');
  const address = state.json?.invalid_fields.find((f) => f.dom_id === 'address');
  check('inspect: failed submit reports focus, aria-invalid, described-by text and associated error', state.code === 0 && state.json.focus.dom_id === 'address'
    && address?.aria_invalid === 'true' && address.error_associated === true && address.described_by_text.includes('Enter an address.')
    && address.error_messages[0]?.id === 'address-error', state.out);
  const fields = new Map(state.json?.fields.map((f) => [f.dom_id, f]));
  check('inspect: reports entered values, checked radios/checkboxes and all selected options', fields.get('request')?.value === 'No peanuts please'
    && fields.get('terms')?.checked === true && fields.get('part-a')?.checked === true && fields.get('part-b')?.checked === false
    && fields.get('sauces')?.selected.map((s) => s.value).join(',') === 'mild,sweet', state.out);
  await act({ action: 'tap', target: '#submit-unassociated' });
  state = await client('inspect');
  const missing = state.json?.fields.find((f) => f.dom_id === 'address');
  check('inspect: exposes unchanged submit-button focus and absent error association', state.code === 0 && state.json.focus.dom_id === 'submit-unassociated'
    && missing?.aria_invalid === null && missing.described_by_text === '' && missing.error_associated === false, state.out);
  await act({ action: 'tap', target: '#keep' });
  state = await client('inspect');
  check('inspect: sees entered value surviving a re-render', state.json?.fields.find((f) => f.dom_id === 'request')?.value === 'No peanuts please', state.out);
  await act({ action: 'tap', target: '#clear' });
  state = await client('inspect');
  check('inspect: sees entered value cleared by the next re-render', state.json?.fields.find((f) => f.dom_id === 'request')?.value === '', state.out);
  await act({ action: 'type', target: '#password', text: 'secret-password-qa' });
  await act({ action: 'type', target: '#card', text: '4242 4242 4242 4242' });
  state = await client('inspect');
  const privateIds = ['password', 'card', 'cvv2', 'holder', 'bank-account', 'reference', 'payment-method', 'private-editor', 'private-child', 'private-nested', 'token'];
  check('inspect: redacts password, card, security code, account, hidden and custom sensitive values', state.code === 0 && privateIds.every((id) => {
    const f = state.json?.fields.find((field) => field.dom_id === id);
    return f?.redacted === true && f.value === null && (!f.selected || f.selected.every((s) => s.value === null && s.text === null));
  }), state.out);
  check('inspect: focus metadata never includes the focused card value', state.json?.focus.dom_id === 'card' && !('value' in state.json.focus), state.json?.focus);
  await act({ action: 'tap', target: '#echo' });
  state = await client('inspect');
  const sensitiveValues = ['secret-password-qa', '4242 4242 4242 4242', '987', 'Private Card Holder', 'BANK-PRIVATE-123', '4111111111111111',
    'private-card-token', 'private-editable-value', 'private-child-value', 'private-nested-value', 'hidden-private-token'];
  const saved = fs.readFileSync(state.json.inspection, 'utf8');
  check('inspect: response and saved evidence redact sensitive values echoed in error text', sensitiveValues.every((v) => !state.out.includes(v) && !saved.includes(v))
    && state.json.fields.find((f) => f.dom_id === 'password').described_by_text.includes('[redacted]'), state.out);
  r = await client('note', { confusion: false, observed: 'The request was cleared after a re-render.' });
  check('drive_client: note records an observation', r.code === 0 && r.json?.ok, r.out);
  r = await client('act', { action: 'evaluate', script: '1' });
  check('drive_client: HTTP errors return JSON and a non-zero exit', r.code === 4 && typeof r.json?.error === 'string', r.out);
  r = await client('act', { action: 'tap', target: '#missing', timeout_ms: 50 });
  check('drive_client: missing target returns JSON and exit 3', r.code === 3 && r.json?.result === 'no_target', r.out);
  r = await client('finish', { success: true });
  check('drive_client: finish writes the original device-only run and returns its exit code', r.code === 0 && fs.existsSync(r.json?.run)
    && JSON.parse(fs.readFileSync(r.json.run)).profile_id === 'no-profile', r.out);
  check('drive_client: serve exits after finish', (await proc).code === 0);

  const screenshot = await start('screenshot', 'R-client-screenshot');
  if (check('inspect: screenshot-only fixture session starts', !!screenshot.ready)) {
    r = await client('inspect', undefined, screenshot.ready.port);
    check('inspect: screenshot-only sessions reject DOM inspection with a clear fix', r.code === 4 && /separate serve session.*a11y/.test(r.json?.error || '')
      && !('fields' in r.json) && !('inspection' in r.json), r.out);
    r = await client('finish', { success: false }, screenshot.ready.port);
    check('drive_client: unsuccessful finish returns JSON and exit 3', r.code === 3 && r.json?.success === false, r.out);
  }
  check('drive_client: unsuccessful serve exits 3', (await screenshot.proc).code === 3);
  for (const [label, args] of [
    ['invalid port', ['--port', '0', 'health']],
    ['invalid request', ['--port', '9477', 'evaluate']],
    ['invalid JSON', ['--port', '9477', 'act', '{']],
    ['non-object JSON', ['--port', '9477', 'act', '[]']],
    ['body on inspect', ['--port', '9477', 'inspect', '{}']],
  ]) {
    r = await runDriver(args, { script: CLIENT });
    check(`drive_client: ${label} is a JSON usage error`, r.code === 2 && typeof r.lines[0]?.error === 'string', r.out);
  }
  r = await client('health');
  check('drive_client: a closed connection returns JSON and exit 4', r.code === 4 && typeof r.json?.error === 'string', r.out);
}

async function serveTest(base, tmp) {
  const label = 'serve galaxy-s24';
  const outDir = path.join(tmp, 'runs');
  let ready = null;
  let resolveReady;
  const readyP = new Promise((r) => { resolveReady = r; });
  writeJson(path.join(tmp, 'agent.json'), { model_family: 'claude', model: 'selftest', input_channel: 'screenshot+a11y', persona_arm: 'neutral' });
  const proc = runDriver(['serve', '--agent-json', path.join(tmp, 'agent.json'), '--scenario', path.join(tmp, 'scenario.json'), '--profile', path.join(tmp, 'p-s24.json'),
    '--out', outDir, '--run-id', 'R-serve', '--base', base, '--port', '0', '--idle-timeout-s', '120'], {
    onLine: (obj) => {
      if (obj.event === 'ready') resolveReady(obj);
    },
  });
  const guard = setTimeout(() => resolveReady(null), 60000);
  ready = await readyP;
  clearTimeout(guard);
  if (!check(`${label}: prints a ready line with a 127.0.0.1 URL and the initial snapshot`,
    ready && /^http:\/\/127\.0\.0\.1:\d+$/.test(ready.url) && fs.existsSync(ready.snapshot) && fs.existsSync(ready.png), ready)) {
    const r = await proc;
    console.log(r.err);
    return;
  }
  const port = ready.port;
  const health = await request(port, 'GET', '/health');
  check(`${label}: GET /health`, health.status === 200 && health.json.ok === true && health.json.run_id === 'R-serve', health.text);
  const snap = await request(port, 'GET', '/snapshot');
  check(`${label}: GET /snapshot writes a new snapshot without acting`,
    snap.status === 200 && snap.json.result === 'ok' && fs.existsSync(snap.json.snapshot) && fs.existsSync(snap.json.png) && snap.json.step_index === 0, snap.text);
  const tap = await request(port, 'POST', '/act', { body: { action: 'tap', target: '#pay' } });
  check(`${label}: POST /act tap returns snapshot/png paths, result ok and a feedback latency`,
    tap.status === 200 && tap.json.result === 'ok' && fs.existsSync(tap.json.snapshot) && fs.existsSync(tap.json.png)
    && typeof tap.json.feedback_latency_ms === 'number' && tap.json.target_element_id, tap.text);
  const cases = [
    ['unknown action is rejected (400)', await request(port, 'POST', '/act', { body: { action: 'evaluate', script: 'alert(1)' } }), 400],
    ['unknown key is rejected (400)', await request(port, 'POST', '/act', { body: { action: 'tap', target: '#pay', js: '1' } }), 400],
    ['non-JSON content type is rejected (415)', await request(port, 'POST', '/act', { body: '{"action":"tap","target":"#pay"}', headers: { 'Content-Type': 'text/plain' } }), 415],
    ['cross-origin Origin is rejected (403)', await request(port, 'POST', '/act', { body: { action: 'tap', target: '#pay' }, headers: { Origin: 'http://evil.example' } }), 403],
    ['foreign Host header is rejected (421)', await request(port, 'GET', '/health', { headers: { Host: `evil.example:${port}` } }), 421],
    ['wrong method is rejected (405)', await request(port, 'GET', '/act'), 405],
    ['unknown endpoint is 404', await request(port, 'GET', '/eval'), 404],
    ['oversized body is rejected (413)', await request(port, 'POST', '/act', { body: JSON.stringify({ action: 'type', text: 'x'.repeat(70000) }) }), 413],
    ['malformed JSON is rejected (400)', await request(port, 'POST', '/act', { body: '{"action":' }), 400],
    ['note without confusion flag is rejected (400)', await request(port, 'POST', '/note', { body: { intent: 'x' } }), 400],
  ];
  for (const [name, res, want] of cases) check(`${label}: ${name}`, res.status === want, `${res.status} ${res.text}`);
  const note = await request(port, 'POST', '/note', { body: { intent: '결제하기', expected: '결제 완료 화면', observed: '카드 번호 오류가 위쪽에 표시됨', confusion: true } });
  check(`${label}: POST /note records a persona note`, note.status === 200 && note.json.ok === true && note.json.step_index === 1, note.text);
  const type = await request(port, 'POST', '/act', { body: { action: 'type', target: '#card', text: '4242 4242' } });
  check(`${label}: POST /act type`, type.status === 200 && type.json.result === 'ok', type.text);
  const miss = await request(port, 'POST', '/act', { body: { action: 'tap', target: '#does-not-exist', timeout_ms: 300 } });
  check(`${label}: missing target returns result no_target (session continues)`, miss.status === 200 && miss.json.result === 'no_target', miss.text);
  const pay = await request(port, 'POST', '/act', { body: { action: 'tap', target: 'text=결제하기' } });
  check(`${label}: POST /act tap text selector`, pay.status === 200 && pay.json.result === 'ok', pay.text);
  const fin = await request(port, 'POST', '/finish', { body: { success: true } });
  check(`${label}: POST /finish writes run.json`, fin.status === 200 && fs.existsSync(fin.json.run) && fin.json.exit_code === 0, fin.text);
  const done = await proc;
  check(`${label}: process exits 0 after /finish`, done.code === 0, `${done.code} ${done.err}`);
  const runDir = path.join(outDir, 'R-serve');
  const { run, snaps } = loadRun(runDir);
  check(`${label}: run.json is interactive, completed, success measured, persona claim kept`,
    run.mode === 'interactive' && run.status === 'completed' && run.success === true && run.success_basis === 'measured' && run.persona_claimed_success === true,
    { mode: run.mode, status: run.status, success: run.success });
  const n0 = run.persona_notes[0];
  check(`${label}: persona_notes carry step_index/intent/expected/observed/confusion (basis judgment)`,
    run.persona_notes.length === 1 && n0.step_index === 1 && n0.intent === '결제하기' && n0.confusion === true && n0.basis === 'judgment', run.persona_notes);
  check(`${label}: a note without anchor is anchored to the acted element (selector and snapshot recorded)`,
    n0.anchor === 'acted' && Array.isArray(n0.anchor_selectors) && n0.anchor_selectors.length === 1 && typeof n0.anchor_snapshot_id === 'string' && typeof n0.screen_key === 'string', n0);
  check(`${label}: the operator record comes from --agent-json`,
    run.agent && run.agent.model_family === 'claude' && run.agent.input_channel === 'screenshot+a11y', run.agent);
  const fake = { jsonPath: '/x/S.json', pngPath: '/x/S.png', id: 'S-1', snap: { step_index: 2, surface: { url: 'u', title: 't' }, elements: [1, 2] } };
  const shot = snapshotReply(fake, { result: 'ok', target_element_id: 'el-1', target_hit: true, feedback_latency_ms: 40, feedback_source: 'dom' }, 'screenshot');
  const both = snapshotReply(fake, { result: 'ok', target_element_id: 'el-1' }, 'screenshot+a11y');
  check(`${label}: screenshot-channel replies carry no snapshot JSON path, element count or DOM grounding flags`,
    shot.png && shot.result === 'ok' && ['snapshot', 'elements', 'target_element_id', 'target_hit', 'feedback_latency_ms', 'feedback_source'].every((k) => !(k in shot))
    && both.snapshot === '/x/S.json' && both.elements === 2 && both.target_element_id === 'el-1', { shot, both });
  check(`${label}: interactive steps recorded including no_target`,
    run.steps.length === 4 && run.steps.map((s) => s.result).join() === 'ok,ok,no_target,ok', run.steps.map((s) => s.result));
  check(`${label}: on-demand snapshot is noted`, [...snaps.values()].some((s) => s.notes.includes('on_demand')));
  checkSnapshotFiles(label, runDir, run, snaps, { id: 'galaxy-s24', orientation: 'portrait', vw: 360, vh: 780, dpr: 3 });
  pythonLoadRun(label, runDir);
}

async function exitCodeTests(base, tmp) {
  const sc = path.join(tmp, 'scenario.json');
  const p = path.join(tmp, 'p-s24.json');
  const out = path.join(tmp, 'runs');
  let r = await runDriver(['run', '--profile', p, '--out', out]);
  check('usage: missing --scenario exits 2', r.code === 2, r.err);
  r = await runDriver(['serve', '--scenario', sc, '--profile', p, '--out', out, '--base', base, '--port', '0']);
  check('usage: serve without an operator record (--agent-json) exits 2', r.code === 2 && /agent-json/.test(r.err), r.err);
  r = await runDriver(['run', '--scenario', sc, '--device', 'nokia-3310', '--out', out, '--base', base]);
  check('usage: unknown device exits 2', r.code === 2 && /unknown device/.test(r.err), r.err);
  r = await runDriver(['run', '--scenario', sc, '--profile', p, '--out', out]);
  check('usage: "{BASE}" without --base exits 2', r.code === 2 && /--base/.test(r.err), r.err);
  const bad = scenario();
  bad.steps = [{ action: 'eval', target: '#pay' }];
  writeJson(path.join(tmp, 'bad.json'), bad);
  r = await runDriver(['run', '--scenario', path.join(tmp, 'bad.json'), '--profile', p, '--out', out, '--base', base]);
  check('usage: unknown scenario action exits 2', r.code === 2 && /action must be one of/.test(r.err), r.err);
  r = await runDriver(['run', '--scenario', sc, '--profile', p, '--out', out, '--base', base, '--run-id', 'R-serve']);
  check('usage: existing non-empty run directory is never overwritten (exit 2)', r.code === 2 && /not empty/.test(r.err), r.err);
  const failing = scenario();
  failing.steps = [{ action: 'tap', target: '#missing', timeout_ms: 300 }, { action: 'tap', target: '#pay' }];
  writeJson(path.join(tmp, 'failing.json'), failing);
  r = await runDriver(['run', '--scenario', path.join(tmp, 'failing.json'), '--profile', p, '--out', out, '--base', base, '--run-id', 'R-failed']);
  const failedRun = r.code === 3 ? loadRun(path.join(out, 'R-failed')).run : null;
  check('run: failed step stops the run with status failed, success false, exit 3',
    failedRun && failedRun.status === 'failed' && failedRun.success === false && failedRun.steps.length === 1 && failedRun.steps[0].result === 'no_target',
    `${r.code} ${r.err}`);
  // A port nothing listens on: the initial navigation fails -> blocked, exit 4, run.json still written.
  const closed = await new Promise((resolve) => {
    const s = http.createServer();
    s.listen(0, '127.0.0.1', () => {
      const { port } = s.address();
      s.close(() => resolve(port));
    });
  });
  r = await runDriver(['run', '--scenario', sc, '--profile', p, '--out', out, '--base', `http://127.0.0.1:${closed}`, '--run-id', 'R-blocked']);
  const blockedRun = fs.existsSync(path.join(out, 'R-blocked', 'run.json')) ? loadRun(path.join(out, 'R-blocked')).run : null;
  check('run: unreachable surface gives status blocked, exit 4, run.json written',
    r.code === 4 && blockedRun && blockedRun.status === 'blocked' && blockedRun.blocked_reasons.length > 0, `${r.code} ${r.err}`);
}

function deviceTableTest() {
  if (!pythonAvailable()) {
    skip('device table mirrors ergoqa.devices', 'python3 or ergoqa not importable');
    return;
  }
  const r = spawnSync('python3', ['-c', [
    'import json',
    'from ergoqa.devices import list_devices',
    'print(json.dumps([{"id": d.id, "form_factor": d.form_factor, "viewport_css": list(d.viewport_css), "dpr": d.dpr, "input": d.input, "playwright_device": d.playwright_device, "has_touch": d.has_touch, "is_mobile": d.is_mobile} for d in list_devices()]))',
  ].join('\n')], { cwd: REPO, encoding: 'utf8' });
  if (r.status !== 0) {
    check('device table mirrors ergoqa.devices', false, r.stderr);
    return;
  }
  const py = JSON.parse(r.stdout);
  const diffs = [];
  for (const d of py) {
    const js = CATALOG.get(d.id);
    if (!js) {
      diffs.push(`${d.id} missing in devices.mjs`);
      continue;
    }
    const touch = js.input === 'touch' || ['phone', 'tablet', 'foldable', 'handheld_console'].includes(js.form_factor);
    const mobile = ['phone', 'tablet', 'foldable'].includes(js.form_factor);
    if (js.form_factor !== d.form_factor || js.viewport_css[0] !== d.viewport_css[0] || js.viewport_css[1] !== d.viewport_css[1]
      || js.dpr !== d.dpr || js.input !== d.input || js.playwright_device !== d.playwright_device || touch !== d.has_touch || mobile !== d.is_mobile) {
      diffs.push(`${d.id}: js ${JSON.stringify(js)} py ${JSON.stringify(d)}`);
    }
  }
  for (const id of CATALOG.keys()) if (!py.some((d) => d.id === id)) diffs.push(`${id} missing in ergoqa.devices`);
  check('device table mirrors ergoqa.devices (ids, viewport, dpr, input, touch/mobile, descriptor)', diffs.length === 0, diffs);
}

async function layersTest(base, tmp) {
  const sc = {
    schema_version: 'ergo-scenario.v1',
    scenario_id: 'SC-driver-layers-01',
    surface: { kind: 'web', url: '{BASE}/layers.html' },
    task_goal_ko: '모달을 연다',
    device_ids: ['galaxy-s24'],
    targets: {},
    steps: [{ action: 'tap', target: '#open-modal' }],
    success: { selector_visible: '#in-modal' },
  };
  writeJson(path.join(tmp, 'layers.json'), sc);
  const outDir = path.join(tmp, 'runs');
  const r = await runDriver(['run', '--scenario', path.join(tmp, 'layers.json'), '--profile', path.join(tmp, 'p-s24.json'),
    '--out', outDir, '--run-id', 'R-layers', '--base', base]);
  if (!check('layers galaxy-s24: exit 0', r.code === 0, `${r.code} ${r.err}`)) return;
  const { run, snaps } = loadRun(path.join(outDir, 'R-layers'));
  const s0 = snaps.get(run.snapshots[0].snapshot_id);
  const s1 = snaps.get(run.steps[0].after);
  const field = bySel(s0, '#wfield');
  check('layers: opaque input on a tinted card reports the card as container_bg (#fffbe6)', field && field.container_bg === '#fffbe6', field);
  const covered = bySel(s0, '#covered-btn');
  check('layers: a button under a translucent cover has occluded_fraction 1 and occluded_by #cover',
    covered && covered.occluded_fraction === 1 && covered.occluded_by === '#cover', covered);
  const hud = bySel(s0, '#hud');
  check('layers: a pointer-events:none HUD over a canvas has unknown (null) occlusion, not "covered by the canvas"',
    hud && hud.occluded_fraction === null && hud.occluded_by === null, hud);
  const cardText = bySel(s0, '#card-text');
  check('layers: text under a transparent stretched link is not treated as covered',
    cardText && cardText.occluded_fraction === 0, cardText);
  const free = bySel(s0, '#behind');
  check('layers: an uncovered button has occluded_fraction 0 and is not inert', free && free.occluded_fraction === 0 && free.inert_by_modal === false, free);
  check('layers: <li> without its own text node is not listed; its button is (20px)',
    !bySel(s0, '#li-owner') && bySel(s0, '#li-btn')?.font_size_px === 20, bySel(s0, '#li-owner'));
  const behind1 = bySel(s1, '#behind');
  const inModal = bySel(s1, '#in-modal');
  check('layers: after showModal() the page behind is inert_by_modal and the dialog content is not',
    behind1 && behind1.inert_by_modal === true && inModal && inModal.inert_by_modal === false, [behind1, inModal]);
}

async function focusTest(base, tmp) {
  const sc = {
    schema_version: 'ergo-scenario.v1',
    scenario_id: 'SC-driver-focus-01',
    surface: { kind: 'web', url: '{BASE}/focus.html' },
    task_goal_ko: '포커스 표시를 본다',
    device_ids: ['desktop-1920'],
    targets: {},
    steps: [{ action: 'type', target: '#pw', text: 'hunter2secret' }, { action: 'click', target: '#open-step2' },
      { action: 'click', target: '#fv' }, { action: 'click', target: '#js-ring' }, { action: 'click', target: '#save' },
      { action: 'click', target: '#note' }, { action: 'click', target: '#submit' }, { action: 'click', target: '#menu-btn' },
      { action: 'click', target: '#chat-btn' }, { action: 'wait', ms: 100 }],
    success: { url_contains: 'focus' },
  };
  writeJson(path.join(tmp, 'focus.json'), sc);
  const outDir = path.join(tmp, 'runs');
  const t0 = Date.now();
  const r = await runDriver(['run', '--scenario', path.join(tmp, 'focus.json'), '--device', 'desktop-1920',
    '--out', outDir, '--run-id', 'R-focus', '--base', base]);
  if (!check('focus desktop-1920: exit 0', r.code === 0, `${r.code} ${r.err}`)) return;
  const { run } = loadRun(path.join(outDir, 'R-focus'));
  const walks = run.focus_walks || [];
  const load = walks.find((w) => w.phase === 'load');
  const end = walks.find((w) => w.phase === 'end');
  check('focus: walks recorded after the run (end state, then the initial screen in a fresh context)',
    walks.map((w) => w.phase).join() === 'end,load' && load.snapshot_id === run.snapshots[0].snapshot_id && run.steps[0].t_start_ms < 3000,
    walks.map((w) => [w.phase, w.snapshot_id, w.ended, w.stops.length]));
  const stop = (sel) => load?.stops.find((s) => s.selector === sel);
  check('focus: the walk starts at the top even with an autofocused field in the middle', load?.stops[0]?.selector === '#under',
    load?.stops.slice(0, 3).map((s) => s.selector));
  check('focus: default and custom rings change pixels; outline:none changes none',
    stop('#plain')?.indicator_px > 50 && stop('#ring')?.indicator_px > 50 && stop('#nofocus')?.indicator_px === 0,
    ['#plain', '#ring', '#nofocus'].map((k) => [k, stop(k)?.indicator_px]));
  check("focus: a neighbour's ring does not count as the next element's indicator", stop('#adj1')?.indicator_px > 20 && stop('#adj2')?.indicator_px === 0,
    [stop('#adj1')?.indicator_px, stop('#adj2')?.indicator_px]);
  check('focus: the walk enters a same-origin iframe and continues after it',
    load?.stops.some((s) => s.frame === 'iframe') && !!stop('#after-frame'), load?.stops.map((s) => [s.selector, s.frame]));
  check('focus: an element behind the fixed bar is fully obscured by it', stop('#under')?.obscured_fraction === 1 && stop('#under')?.obscured_by === '#bar',
    stop('#under'));
  check('focus: a field inside a fixed dialog under its floating label is not obscured', stop('#dlg-in')?.obscured_fraction === 0, stop('#dlg-in'));
  check('focus: below the fold with smooth scrolling the element is measured in view', stop('#deep')?.in_viewport === true && stop('#deep')?.indicator_px === 0,
    stop('#deep'));
  check('focus: an indicator drawn away from the element is found in the viewport (ACT oj04fd)',
    stop('#far')?.indicator_px < 4 && stop('#far')?.indicator_any_px > 50, stop('#far'));
  check('focus: an animation inside an element without an indicator is not an indicator',
    stop('#anim')?.indicator_px < 4 && (stop('#anim')?.indicator_any_px === null || stop('#anim')?.indicator_any_px < 4), stop('#anim'));
  check('focus: a non-modal absolute dialog fully covers the element under it (author layer)',
    stop('#adlg-under')?.obscured_fraction === 1 && stop('#adlg-under')?.obscured_user_opened === false, stop('#adlg-under'));
  check('focus: layers opened by the user are closed on the fresh load', stop('#menu-under')?.obscured_fraction === 0, stop('#menu-under'));
  const endStop = (sel) => end?.stops.find((s) => s.selector === sel);
  check('focus: a user-opened menu that closes on Escape without moving focus reveals the element (2.4.11 note)',
    endStop('#menu-under')?.obscured_user_opened === true && endStop('#menu-under')?.escape_reveals === true, endStop('#menu-under'));
  check('focus: a user-opened chat that stays on Escape keeps the element covered',
    endStop('#chat-under')?.obscured_fraction === 1 && endStop('#chat-under')?.obscured_user_opened === true && endStop('#chat-under')?.escape_reveals === false,
    endStop('#chat-under'));
  const probe = (sel) => run.steps.find((s) => s.action.target === sel)?.focus_probe;
  check('focus probe: before a click on a mid-task screen, a control without an indicator changes no pixels',
    probe('#save')?.focus_visible === true && probe('#save')?.indicator_px === 0 && (probe('#save')?.indicator_any_px ?? 0) < 4
      && !walks.some((w) => w.stops.some((s) => s.selector === '#save')), probe('#save'));
  check('focus probe: :focus-visible rings and rings a script draws after a key press show after mouse clicks',
    probe('#fv')?.indicator_px > 50 && probe('#js-ring')?.indicator_px > 20 && probe('#menu-btn')?.indicator_px > 50,
    ['#fv', '#js-ring', '#menu-btn'].map((k) => [k, probe(k)?.focus_visible, probe(k)?.indicator_px]));
  check('focus probe: text fields are skipped; a click while a text field has focus is probed after blurring it; every probe names its screen',
    probe('#note')?.skipped === 'text_entry' && probe('#submit')?.after_field === true && probe('#submit')?.indicator_px > 50
    && probe('#open-step2')?.after_field === true && probe('#open-step2')?.indicator_px > 50
    && ['#fv', '#save', '#menu-btn'].every((k) => probe(k)?.snapshot_id && probe(k)?.selector === k), [probe('#note'), probe('#submit'), probe('#save')?.snapshot_id]);
  const names = walks.flatMap((w) => w.stops.map((s) => s.name)).join('|');
  check('focus: stop names never contain a typed value', !names.includes('hunter2') && stop('#pw')?.name === '비밀번호', names);
  check('focus: the walk does not disturb the run (steps ok, success measured)', run.status === 'completed' && run.success === true,
    { status: run.status, success: run.success, ms: Date.now() - t0 });
  const touch = loadRun(path.join(outDir, 'R-layers')).run;
  check('focus: no walk and no focus probe on touch devices by default', Array.isArray(touch.focus_walks) && touch.focus_walks.length === 0
    && touch.steps.every((s) => !s.focus_probe), touch.focus_walks);
}

async function focusProbeTest(base, tmp) {
  const click = (target) => ({ action: 'click', target });
  const sc = {
    schema_version: 'ergo-scenario.v1', scenario_id: 'SC-driver-focus-02', surface: { kind: 'web', url: '{BASE}/focus2.html' },
    task_goal_ko: '메뉴와 대화상자를 쓴다', device_ids: ['desktop-1920'], targets: {},
    steps: [click('#tick-btn'), click('#menu2-btn'), click('#mi-2'), click('#fb'), click('#card-img'), click('#fake-radio'), click('#cb-l'),
      click('#disc-btn'), click('#disc-btn'), click('#mui-btn'), click('#mui-close'), click('#late-btn'), click('#late-close'), click('#wi-btn'), click('#pair-a'), click('#pair-b'),
      click('#card2-img'), click('#dock-btn'), click('#dock-close'), click('#pulse-btn'), { action: 'type', target: '#ac', text: '충전' }, click('#ac-go'),
      { action: 'type', target: '#fill', text: '5' }, click('#fill-btn'), click('#dead-btn')],
    success: { url_contains: 'focus2' },
  };
  writeJson(path.join(tmp, 'focus2.json'), sc);
  const outDir = path.join(tmp, 'runs');
  const r = await runDriver(['run', '--scenario', path.join(tmp, 'focus2.json'), '--device', 'desktop-1920', '--out', outDir, '--run-id', 'R-focus2',
    '--base', base, '--no-reflow', '--feedback-timeout-ms', '1000']);
  if (!check('focus2 desktop-1920: exit 0', r.code === 0, `${r.code} ${r.err}`)) return;
  const { run, snaps } = loadRun(path.join(outDir, 'R-focus2'));
  const step = (sel, nth = 0) => run.steps.filter((s) => s.action.target === sel)[nth];
  check('focus probe: a ticking counter inside a control without an indicator is not an indicator',
    step('#tick-btn')?.focus_probe?.indicator_px < 4, step('#tick-btn')?.focus_probe);
  check('focus probe: skipped inside a menu that manages its own focus; the click still lands',
    step('#mi-2')?.focus_probe?.skipped === 'managed_focus' && step('#mi-2')?.target_hit === true && run.steps.every((s) => !s.focus_probe?.disturbed),
    [step('#mi-2')?.focus_probe, step('#mi-2')?.target_hit]);
  const ctl = (sel) => step(sel)?.target_control;
  check('click targets: a button in a shadow root is a control; a card image is covered by its link; a hidden input is no control',
    ctl('#fb')?.control === true && ctl('#card-img')?.control === false && ctl('#card-img')?.card_control === true
      && ctl('#fake-radio')?.control === false && ctl('#fake-radio')?.contains_control === false,
    { fb: ctl('#fb'), card: ctl('#card-img'), fake: ctl('#fake-radio') });
  check('feedback: toggling a custom checkbox whose look never changes is not feedback (input events of checkboxes are not counted)',
    step('#cb-l')?.feedback_source === null, [step('#cb-l')?.feedback_source, step('#cb-l')?.feedback_latency_ms]);
  const after = (sel, nth = 0) => snaps.get(step(sel, nth)?.after) || {};
  const disc = (after('#disc-btn').layers || []).find((l) => l.dom_id === 'disc');
  check('layers: a panel the next Tab reaches follows focus', !!disc && disc.follows_focus === true && disc.contains_focus === false, after('#disc-btn').layers);
  const paper = (after('#mui-btn').layers || []).find((l) => l.dom_id === 'mui-paper');
  check('layers: focus on the fixed overlay root around a dialog counts as inside it',
    !!paper && paper.contains_focus === true && paper.overlay_root === '#mui-root', after('#mui-btn').layers);
  const late = (after('#late-btn').layers || []).find((l) => l.dom_id === 'late-dlg');
  check('layers: a dialog that takes focus after its entrance transition is listed on the step (focus_late_layers)',
    !!late && late.contains_focus === false && (step('#late-btn')?.focus_late_layers || []).includes(late.selector),
    { layer: late, late: step('#late-btn')?.focus_late_layers });
  check('focus probe: a click while a text field has focus is probed after the field is blurred',
    step('#late-close')?.focus_probe?.after_field === true && step('#late-close')?.target_hit === true, step('#late-close')?.focus_probe);
  check('focus probe: a ring hidden in "mouse" modality by a script that ignores modifier keys is seen (non-modifier key)',
    step('#wi-btn')?.focus_probe?.indicator_px > 50, step('#wi-btn')?.focus_probe);
  check("focus probe: the previous control's ring is masked without masking the target in the same small group",
    step('#pair-b')?.focus_probe?.masked_prev === true && step('#pair-b')?.focus_probe?.indicator_px > 50, step('#pair-b')?.focus_probe);
  check('click targets: a card whose only controls are side actions is not covered by them',
    ctl('#card2-img')?.control === false && ctl('#card2-img')?.card_control === false && ctl('#card2-img')?.contains_control === false, ctl('#card2-img'));
  const drawer = (after('#dock-btn').layers || []).find((l) => l.dom_id === 'dock-drawer');
  check('layers: focus left on the menu button in the same fixed bar is not inside the drawer it opened',
    !!drawer && drawer.contains_focus === false && !(step('#dock-btn')?.focus_late_layers || []).length, { drawer, late: step('#dock-btn')?.focus_late_layers });
  check('focus probe: a container that held focus (the dialog root) is not masked over the target inside it',
    step('#mui-close')?.focus_probe?.masked_prev === false && step('#mui-close')?.focus_probe?.indicator_px > 50, step('#mui-close')?.focus_probe);
  check('focus probe: a control whose background keeps pulsing is inconclusive, not a missing indicator',
    step('#pulse-btn')?.focus_probe?.indicator_px === null && step('#pulse-btn')?.focus_probe?.inconclusive === 'animated', step('#pulse-btn')?.focus_probe);
  check('focus probe: after typing in a field with suggestions, the next click is not probed',
    step('#ac-go')?.focus_probe?.skipped === 'field_focused', step('#ac-go')?.focus_probe);
  check('focus probe: focus is not given back to an ordinary previous control (blurred instead)',
    step('#pair-b')?.focus_probe?.restored === 'blur', step('#pair-b')?.focus_probe);
  check('feedback: a script filling the focused field (value property) is feedback, although the field is masked for its caret',
    step('#fill-btn')?.feedback_source === 'dom_mutation' && step('#fill-btn')?.feedback_latency_ms < 300, [step('#fill-btn')?.feedback_source, step('#fill-btn')?.feedback_latency_ms]);
  check("feedback: a probed click on a button that does nothing has no feedback (the root's modality marker is not a response)",
    step('#dead-btn')?.focus_probe && !step('#dead-btn').focus_probe.skipped && step('#dead-btn')?.feedback_source === null,
    [step('#dead-btn')?.focus_probe?.skipped, step('#dead-btn')?.feedback_source, step('#dead-btn')?.feedback_latency_ms]);
  check('focus2: every step ok', run.steps.every((s) => s.result === 'ok'), run.steps.map((s) => [s.action.target, s.result, s.error]));
  await feedbackReversalTest(base, tmp);
}

async function feedbackReversalTest(base, tmp) {
  const { pw, info } = loadPlaywright();
  const transport = await openBrowser(pw, info);
  let context;
  try {
    context = await transport.browser.newContext({ viewport: { width: 1920, height: 1080 } });
    await context.addInitScript(pageInit, { key: STATE_KEY });
    for (const [target, phases, response] of [
      ['#dead', [200, 300, 380], false],
      ['#same-label', [200, 300, 380], false],
      ['#paint-label', [100, 200, 300, 380], true],
    ]) {
      const page = await context.newPage();
      await page.goto(`${base}/feedback_ambient.html`);
      const { scenario } = normalizeScenario({ schema_version: 'ergo-scenario.v1', scenario_id: 'SC-feedback-reversal',
        surface: { kind: 'web', url: `${base}/feedback_ambient.html` }, task_goal_ko: '반응을 본다',
        device_ids: ['desktop-1920'], targets: {}, steps: [], success: { url_contains: 'feedback_ambient' } }, { requireSteps: false });
      const session = new WebSession({ pw, pwInfo: info, scenario, runDir: tmp, runId: 'R-reversal',
        options: { visualFeedback: true, feedbackTimeoutMs: 500, settleMs: 0, flashSampleMs: 0 } });
      session.page = page;
      session.cdp = await context.newCDPSession(page);
      session.dev = { contextOptions: { hasTouch: false }, base: { input: 'mouse' } };
      session.vw = 1920;
      session.vh = 1080;
      let captures = 0;
      // Only animation time is controlled. Input dispatch, CDP screenshots,
      // pixel comparison, motion masks and DOM/input feedback remain the real code.
      session.captureFrame = async () => {
        const phase = phases[Math.min(captures++, phases.length - 1)];
        await page.evaluate((t) => {
          const a = document.getElementById('pulse').getAnimations()[0];
          a.pause();
          a.currentTime = t;
        }, phase);
        return WebSession.prototype.captureFrame.call(session);
      };
      const point = await page.locator(target).evaluate((n) => {
        const r = n.getBoundingClientRect();
        return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
      });
      const step = { step_index: 0 };
      await session.performInput({ action: 'click' }, { point }, step);
      check(`feedback reversal: ${target} ${response ? 'keeps real CSS-only feedback outside ambient motion' : 'has no response when equal pre-input colors alias the pulse'}`,
        response ? step.feedback_source === 'visual_change' && step.feedback_dom_ms === null
          && step.feedback_visual_ambient === false && step.feedback_visual_moving_px > 0
          : step.feedback_source === null, step);
      await session.cdp.detach();
      await page.close();
    }
  } finally { await transport.close([context]); }
}

// Native binary-control activation evidence (feedback_native_state): a small
// checkbox/radio whose state change paints too little for the downsampled
// visual diff is acknowledged by its boolean change plus the trusted
// input/change event of the same control — recorded separately from the
// DOM/visual feedback sources, never as a claim of visible paint.
async function nativeFeedbackTest(base, tmp) {
  const outDir = path.join(tmp, 'native-runs');
  const click = (target) => ({ action: 'click', target });
  const sc = {
    schema_version: 'ergo-scenario.v1', scenario_id: 'SC-driver-native-feedback',
    surface: { kind: 'web', url: '{BASE}/native_feedback.html' }, task_goal_ko: '체크박스와 라디오를 켠다',
    device_ids: ['desktop-1920'], targets: {},
    steps: [click('#small'), click('#for-label'), click('#nest-label'), click('#big'), click('#r1-label'),
      click('#r2-label'), click('#dis-label'), click('#noop'), click('#aria-cb'), click('#aria-dead'),
      click('#focus-btn'), click('#delayed-label'), click('#slow-label'), click('#restore-label'),
      click('#sensitive-label'), click('#private-label')],
    success: { url_contains: 'native_feedback' },
  };
  writeJson(path.join(tmp, 'native.json'), sc);
  const r = await runDriver(['run', '--scenario', path.join(tmp, 'native.json'), '--device', 'desktop-1920',
    '--out', outDir, '--run-id', 'R-native', '--base', base, '--no-reflow', '--no-focus-walk', '--feedback-timeout-ms', '1500']);
  if (!check('native feedback desktop-1920: exit 0', r.code === 0, `${r.code} ${r.err}`)) return;
  const { run } = loadRun(path.join(outDir, 'R-native'));
  const step = (sel) => run.steps.find((s) => s.action.target === sel);
  const ack = (sel) => step(sel)?.feedback_native_state;
  check('native feedback: every step ok', run.steps.every((s) => s.result === 'ok'),
    run.steps.map((s) => [s.action.target, s.result, s.error]));
  const changedAck = (sel, via, type, domId) => {
    const a = ack(sel);
    return !!a && a.source === 'native_state_change' && a.changed === true && a.before === false && a.after === true
      && a.via === via && a.type === type && a.dom_id === domId && ['input', 'change'].includes(a.event)
      && typeof a.latency_ms === 'number' && a.latency_ms >= 0 && a.latency_ms < 400;
  };
  check('native feedback: 13x13 checkbox toggled by direct input records the same control with a trusted event time',
    changedAck('#small', 'direct', 'checkbox', 'small'), ack('#small'));
  check('native feedback: a 20x20 explicit for= label toggles the same control it names',
    changedAck('#for-label', 'label_for', 'checkbox', 'for-cb'), ack('#for-label'));
  check('native feedback: a 20x20 nested label toggles the control it wraps',
    changedAck('#nest-label', 'nested_label', 'checkbox', 'nest-cb'), ack('#nest-label'));
  check('native feedback: the 48x48 checkbox keeps its downsampled visual feedback path',
    changedAck('#big', 'direct', 'checkbox', 'big') && step('#big').feedback_source === 'visual_change',
    { ack: ack('#big'), src: step('#big')?.feedback_source, ms: step('#big')?.feedback_latency_ms });
  check('native feedback: clicking the selected radio again leaves the boolean unchanged (no native change)',
    ack('#r1-label') && ack('#r1-label').changed === false && ack('#r1-label').after === true
      && ack('#r1-label').event === null && ack('#r1-label').latency_ms === null, ack('#r1-label'));
  check('native feedback: switching radio through its label is a state change of the radio',
    changedAck('#r2-label', 'label_for', 'radio', 'r2'), ack('#r2-label'));
  check('native feedback: a disabled checkbox in its label changes nothing',
    ack('#dis-label') && ack('#dis-label').changed === false && ack('#dis-label').event === null, ack('#dis-label'));
  check('native feedback: no-op, custom ARIA (with or without handler) and focus-only clicks create no native state evidence',
    ack('#noop') === undefined && ack('#aria-cb') === undefined && ack('#aria-dead') === undefined
      && ack('#focus-btn') === undefined, [ack('#noop'), ack('#aria-cb'), ack('#aria-dead'), ack('#focus-btn')]);
  check('native feedback: the custom ARIA toggle stays DOM (semantic) evidence and the focus-only click stays visual',
    step('#aria-cb').feedback_source === 'dom_mutation' && step('#aria-dead').feedback_source === null
      && step('#focus-btn').feedback_source === 'visual_change',
    [step('#aria-cb')?.feedback_source, step('#aria-dead')?.feedback_source, step('#focus-btn')?.feedback_source]);
  const delayed = step('#delayed-label');
  check('native feedback: instant state acknowledgment and the ~650 ms indicator commit keep separate honest times',
    delayed.feedback_native_state.changed === true && delayed.feedback_native_state.latency_ms < 400
      && delayed.feedback_source === 'dom_mutation' && delayed.feedback_latency_ms >= 600,
    { ack: delayed.feedback_native_state, src: delayed.feedback_source, ms: delayed.feedback_latency_ms });
  const slow = step('#slow-label');
  check('native feedback: a ~1200 ms deferred activation is recorded as a slow acknowledgment, never a timely one',
    slow.feedback_native_state && slow.feedback_native_state.changed === true
      && slow.feedback_native_state.latency_ms >= 1000 && slow.feedback_native_state.latency_ms <= 1500
      && slow.feedback_source === null,
    { ack: slow.feedback_native_state, src: slow.feedback_source });
  const restore = step('#restore-label');
  check('native feedback: a restored state does not lend its trusted event timestamp to a later programmatic change',
    restore.feedback_native_state && restore.feedback_native_state.changed === true
      && restore.feedback_native_state.event === null && restore.feedback_native_state.latency_ms === null,
    restore.feedback_native_state);
  check('native feedback: a protected (data-sensitive) control behind a harmless label records no native evidence at all',
    step('#sensitive-label').feedback_native_state === undefined,
    step('#sensitive-label').feedback_native_state);
  check('native feedback: an explicitly private control/label records no native evidence',
    ack('#private-label') === undefined, ack('#private-label'));
  check('native feedback: small-control state changes never masquerade as DOM/visual feedback sources',
    ['#small', '#for-label', '#nest-label'].every((sel) => ['visual_change', null].includes(step(sel).feedback_source)),
    ['#small', '#for-label', '#nest-label'].map((sel) => step(sel).feedback_source));
  check('native feedback: run telemetry documents the state acknowledgment source and its limits',
    typeof run.driver.feedback.state_acknowledgment === 'string'
      && run.driver.feedback.state_acknowledgment.startsWith('native_state_change:'), run.driver.feedback);
  const keys = new Set(run.steps.flatMap((s) => (s.feedback_native_state ? Object.keys(s.feedback_native_state) : [])));
  check('native feedback: the acknowledgment carries only bounded, value-free metadata',
    [...keys].every((k) => ['source', 'via', 'type', 'dom_id', 'before', 'after', 'changed', 'event', 'latency_ms', 'stable'].includes(k)),
    [...keys]);
  const python = process.env.ERGOQA_PYTHON || 'python3';
  const loaded = spawnSync(python, ['-c', 'from ergoqa.snapshot import load_run_dir; import sys; load_run_dir(sys.argv[1])', path.join(outDir, 'R-native')],
    { encoding: 'utf8', env: { ...process.env, PYTHONPATH: REPO } });
  check('native feedback: a run with the new field passes the native capture loader', loaded.status === 0, loaded.stderr);
  await nativeCorrectionTest(base, tmp);
}

// Correction cases that need the live session object: the page-clock offset
// conversion, the armed-watch cleanup on a failed action, and the opted-out
// region skip. Only the failure and the clock are injected; the arm, read,
// dispatch and privacy paths are the real driver code.
async function nativeCorrectionTest(base, tmp) {
  const { pw, info } = loadPlaywright();
  const transport = await openBrowser(pw, info);
  let context;
  try {
    context = await transport.browser.newContext({ viewport: { width: 1920, height: 1080 } });
    await context.addInitScript(pageInit, { key: STATE_KEY });
    const { scenario } = normalizeScenario({ schema_version: 'ergo-scenario.v1', scenario_id: 'SC-native-correction',
      surface: { kind: 'web', url: `${base}/native_feedback.html` }, task_goal_ko: '수정 사항을 확인한다',
      device_ids: ['desktop-1920'], targets: {}, steps: [], success: { url_contains: 'native_feedback' } }, { requireSteps: false });
    const mkSession = async (page) => {
      const session = new WebSession({ pw, pwInfo: info, scenario, runDir: tmp, runId: 'R-native-fix',
        options: { visualFeedback: false, feedbackTimeoutMs: 500, settleMs: 0, flashSampleMs: 0 } });
      session.page = page;
      session.cdp = await context.newCDPSession(page);
      session.dev = { contextOptions: { hasTouch: false }, base: { input: 'mouse' } };
      session.vw = 1920;
      session.vh = 1080;
      return session;
    };
    const pointOf = (page, selector) => page.locator(selector).evaluate((n) => {
      const r = n.getBoundingClientRect();
      return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
    });
    const watchLeft = (page) => page.evaluate((key) => !!window[Symbol.for(key)].binaryWatch, STATE_KEY);

    // Page clock 500 ms ahead of Node: after recalibration the same immediate
    // activation must measure small, not ~500 ms (offset sign and reuse).
    for (const offset of [500, -500]) {
      const page = await context.newPage();
      await page.goto(`${base}/native_feedback.html`);
      const session = await mkSession(page);
      await session.calibrate();
      await page.evaluate((offset) => {
        const orig = performance.now.bind(performance);
        performance.now = () => orig() + offset;
      }, offset);
      await session.calibrate();
      const step = { step_index: 0 };
      await session.performInput({ action: 'click' }, { point: await pointOf(page, '#small') }, step);
      check(`native correction: a ${offset} ms page-clock offset is absorbed by the existing calibration (immediate activation stays immediate)`,
        step.feedback_native_state && step.feedback_native_state.changed === true
          && step.feedback_native_state.latency_ms < 100,
        step.feedback_native_state);
      check(`native correction: the ${offset} ms offset case leaves no watch behind`, await watchLeft(page) === false);
      await session.cdp.detach();
      await page.close();
    }
    // A probe that fails after arming must not leave the watch and listeners armed.
    {
      const page = await context.newPage();
      await page.goto(`${base}/native_feedback.html`);
      const session = await mkSession(page);
      await session.calibrate();
      session.probeFrames = () => { throw new Error('owned injected probe failure'); };
      const step = { step_index: 0 };
      let threw = null;
      try {
        await session.performInput({ action: 'click' }, { point: await pointOf(page, '#small') }, step);
      } catch (err) {
        threw = err;
      }
      check('native correction: a failing probe after arming fails the step', threw && /owned injected probe failure/.test(threw.message), threw && threw.message);
      check('native correction: the failed step disposes the armed watch and its listeners', await watchLeft(page) === false);
      await session.cdp.detach();
      await page.close();
    }
    // readNativeBinary contains transport errors: finally still clears a watch
    // when the read itself fails before its page-side disposal runs.
    {
      const page = await context.newPage();
      await page.goto(`${base}/native_feedback.html`);
      const session = await mkSession(page);
      await session.calibrate();
      const evaluate = page.evaluate.bind(page);
      page.evaluate = (fn, args) => fn.name === 'readBinaryControl'
        ? Promise.reject(new Error('owned injected read failure')) : evaluate(fn, args);
      const step = { step_index: 0 };
      await session.performInput({ action: 'click' }, { point: await pointOf(page, '#small') }, step);
      check('native correction: a failed native read records no acknowledgment', step.feedback_native_state === undefined);
      check('native correction: a failed native read leaves no watch behind', await watchLeft(page) === false);
      await session.cdp.detach();
      await page.close();
    }
    // An opted-out region covers the control: no native evidence is recorded.
    {
      const page = await context.newPage();
      await page.goto(`${base}/native_feedback.html`);
      const session = await mkSession(page);
      await session.calibrate();
      session.rememberPrivateAction({ action: 'type', target: '#opted-region', redact: true });
      const step = { step_index: 0 };
      await session.performInput({ action: 'click' }, { point: await pointOf(page, '#region-label') }, step);
      check('native correction: a control inside an opted-out region records no native evidence (no id, no boolean)',
        step.feedback_native_state === undefined, step.feedback_native_state);
      check('native correction: the skipped control leaves no watch behind', await watchLeft(page) === false);
      await session.cdp.detach();
      await page.close();
    }
    // Replacing a watch with a non-control/protected target disposes it even
    // though the next arm returns no descriptor. Flat-tree privacy also covers
    // opted-out and explicit private ancestors of controls in open shadow DOM.
    {
      const page = await context.newPage();
      await page.goto(`${base}/native_feedback.html`);
      for (const selector of ['#noop', '#sensitive-label']) {
        await page.locator('#small').evaluate(armBinaryControl, { key: STATE_KEY });
        const previous = await page.evaluateHandle((key) => window[Symbol.for(key)].binaryWatch, STATE_KEY);
        await page.locator(selector).evaluate(armBinaryControl, { key: STATE_KEY });
        check(`native correction: replacing a watch with ${selector} clears state and listeners`,
          await watchLeft(page) === false && await previous.evaluate((w) => w.closed && w.timers.size === 0));
        await previous.dispose();
      }
      await page.evaluate(() => {
        const host = document.createElement('div');
        host.id = 'owned-shadow-region';
        host.attachShadow({ mode: 'open' }).innerHTML = '<label id="owned-shadow-label"><input type="checkbox" id="owned-shadow-cb">Owned</label>';
        document.body.append(host);
      });
      for (const attribute of ['data-private', 'data-sensitive']) {
        await page.locator('#owned-shadow-region').evaluate((n, attribute) => n.setAttribute(attribute, ''), attribute);
        const armed = await page.locator('#owned-shadow-label').evaluate(armBinaryControl, { key: STATE_KEY });
        check(`native correction: a ${attribute} shadow ancestor protects the control state`, armed?.protected === true && await watchLeft(page) === false);
        await page.locator('#owned-shadow-region').evaluate((n, attribute) => n.removeAttribute(attribute), attribute);
      }
      const opted = await page.locator('#owned-shadow-label').evaluate(armBinaryControl, {
        key: STATE_KEY, redactSelectors: ['#owned-shadow-region'],
      });
      check('native correction: an opted-out shadow ancestor protects the control state', opted?.protected === true && await watchLeft(page) === false);
      await page.close();
    }
  } finally { await transport.close([context]); }
}

async function viewportTest(base, tmp) {
  const outDir = path.join(tmp, 'runs');
  const scenario = (id, query, device, success) => ({
    schema_version: 'ergo-scenario.v1', scenario_id: id, surface: { kind: 'web', url: `{BASE}/viewport.html${query}` },
    task_goal_ko: '다음을 누른다', device_ids: [device], targets: {}, steps: [{ action: 'tap', target: '#go' }, { action: 'wait', ms: 200 }], success,
  });
  // A scrolled page: the captured frames must show the scrolled screen.
  writeJson(path.join(tmp, 'vp-scroll.json'), scenario('SC-driver-vp-01', '', 'galaxy-s24', { url_contains: 'viewport' }));
  let r = await runDriver(['run', '--scenario', path.join(tmp, 'vp-scroll.json'), '--device', 'galaxy-s24', '--out', outDir, '--run-id', 'R-vp-scroll',
    '--base', base, '--no-reflow']);
  if (check('viewport galaxy-s24 (scrolled): exit 0', r.code === 0, `${r.code} ${r.err}`)) {
    const st = loadRun(path.join(outDir, 'R-vp-scroll')).run.steps[0];
    check('viewport: canvas-only feedback after a scroll is seen in the frames (frames show the scrolled screen, not the document top)',
      st.target_hit === true && st.feedback_source === 'visual_change', { hit: st.target_hit, src: st.feedback_source, visual: st.feedback_visual_ms });
  }
  // A swipe on an inner scroll box while frames are captured for visual feedback.
  writeJson(path.join(tmp, 'vp-inner.json'), {
    ...scenario('SC-driver-vp-03', '', 'galaxy-s24', { url_contains: 'viewport' }),
    steps: [{ action: 'swipe', target: '#inner', direction: 'up', distance: 150 }, { action: 'wait', ms: 400 }],
  });
  r = await runDriver(['run', '--scenario', path.join(tmp, 'vp-inner.json'), '--device', 'galaxy-s24', '--out', outDir, '--run-id', 'R-vp-inner',
    '--base', base, '--no-reflow']);
  if (check('viewport galaxy-s24 (inner scroll box): exit 0', r.code === 0, `${r.code} ${r.err}`)) {
    const { run } = loadRun(path.join(outDir, 'R-vp-inner'));
    const last = JSON.parse(fs.readFileSync(path.join(outDir, 'R-vp-inner', run.snapshots[run.snapshots.length - 1].path), 'utf8'));
    const pos = Number((last.elements.find((e) => e.dom_id === 'inner-pos') || {}).text);
    check('viewport: a swipe scrolls an inner scroll box while frames are captured (no downscaling clip during gestures)', pos > 50, pos);
  }
  // Keys in a focused empty field: the caret blinks, which is not feedback; a typed
  // character is (an input event).
  writeJson(path.join(tmp, 'vp-caret.json'), {
    ...scenario('SC-driver-vp-04', '', 'desktop-1920', { url_contains: 'viewport' }),
    device_ids: ['desktop-1920'],
    steps: [{ action: 'click', target: '#field' }, { action: 'press', key: 'Backspace' }, { action: 'press', key: 'Backspace' },
      { action: 'press', key: 'Backspace' }, { action: 'type', target: '#field', text: 'a' }],
  });
  r = await runDriver(['run', '--scenario', path.join(tmp, 'vp-caret.json'), '--device', 'desktop-1920', '--out', outDir, '--run-id', 'R-vp-caret',
    '--base', base, '--no-reflow', '--no-focus-walk']);
  if (check('viewport desktop-1920 (caret): exit 0', r.code === 0, `${r.code} ${r.err}`)) {
    const st = loadRun(path.join(outDir, 'R-vp-caret')).run.steps;
    const keys = st.filter((s) => s.action.action === 'press');
    const typed = st.find((s) => s.action.action === 'type');
    check('viewport: Backspace in an empty focused field has no feedback (the blinking caret is masked)',
      keys.every((s) => s.feedback_source === null), keys.map((s) => [s.feedback_source, s.feedback_latency_ms]));
    check('viewport: a typed character is feedback at once (input event)', typed && typed.feedback_latency_ms !== null && typed.feedback_latency_ms < 300,
      typed && [typed.feedback_source, typed.feedback_latency_ms]);
  }
  // Content wider than the phone: the screen pans inside a wider layout viewport.
  writeJson(path.join(tmp, 'vp-wide.json'), scenario('SC-driver-vp-02', '?wide', 'galaxy-s24', { text_present: '눌림' }));
  r = await runDriver(['run', '--scenario', path.join(tmp, 'vp-wide.json'), '--device', 'galaxy-s24', '--out', outDir, '--run-id', 'R-vp-wide',
    '--base', base, '--no-reflow']);
  if (check('viewport galaxy-s24 (wider than the screen): exit 0', r.code === 0, `${r.code} ${r.err}`)) {
    const { run } = loadRun(path.join(outDir, 'R-vp-wide'));
    const st = run.steps[0];
    const snaps = run.snapshots.map((s) => JSON.parse(fs.readFileSync(path.join(outDir, 'R-vp-wide', s.path), 'utf8')));
    const boxes = snaps.map((sn) => sn.elements.find((e) => e.dom_id === 'go')).filter(Boolean);
    check('viewport: a tap after scrolling a page wider than the screen lands (success, target hit)', run.success === true && st.target_hit === true,
      { success: run.success, hit: st.target_hit, point: st.point });
    check('viewport: boxes are screen coordinates (the tapped button is inside the 360x780 screen in the snapshots around the tap)',
      boxes.length >= 2 && boxes.slice(1).every((b) => b.in_viewport === true && b.box.y >= 0 && b.box.y + b.box.h <= 780), boxes.map((b) => [b.box, b.in_viewport]));
  }
}

async function reflowTest(base, tmp) {
  const sc = {
    schema_version: 'ergo-scenario.v1', scenario_id: 'SC-driver-reflow-01', surface: { kind: 'web', url: '{BASE}/reflow.html' },
    task_goal_ko: '다음 화면으로 간다', device_ids: ['galaxy-s24'], targets: {},
    steps: [{ action: 'tap', target: '#next' }, { action: 'wait', ms: 100 }], success: { url_contains: 'reflow' },
  };
  writeJson(path.join(tmp, 'reflow.json'), sc);
  const outDir = path.join(tmp, 'runs');
  const r = await runDriver(['run', '--scenario', path.join(tmp, 'reflow.json'), '--device', 'galaxy-s24', '--out', outDir, '--run-id', 'R-reflow', '--base', base]);
  if (!check('reflow galaxy-s24: exit 0', r.code === 0, `${r.code} ${r.err}`)) return;
  const { run } = loadRun(path.join(outDir, 'R-reflow'));
  const recs = (run.reflow || []).filter((x) => !x.error);
  const offenders = recs.flatMap((x) => x.offenders.map((o) => o.dom_id));
  check('reflow: every distinct screen is re-rendered at 320 px (two screens here)', recs.length >= 2 && recs.every((x) => x.width === 320),
    run.reflow);
  check('reflow: fixed-width boxes stick out on both screens', offenders.includes('fixed-box') && offenders.includes('wide-note'), offenders);
  check('reflow: a table, a self-scrolling chip row and fluid text are exempt',
    !offenders.includes('fee-table') && !offenders.includes('chips') && !offenders.includes('fluid') && !offenders.some((o) => o === null), offenders);
  check('reflow: the run itself is not resized (steps ok, success)', run.status === 'completed' && run.success === true, { status: run.status });
  const lost = recs.flatMap((x) => (x.lost || []).map((o) => o.dom_id));
  check('reflow: text visible at the device width but cut at 320 px is lost; a carousel slide hidden at both is not',
    lost.includes('bar-timer') && !lost.includes('slide-2') && !lost.includes('bar-title'), recs.map((x) => x.lost));
  check('reflow: text in a 90vh overflow:hidden shell is not lost because of a shorter viewport alone', !lost.includes('shell-note')
    && recs.every((x) => x.lost_height === 780), recs.map((x) => x.lost_height));
  const first = JSON.parse(fs.readFileSync(path.join(outDir, 'R-reflow', run.snapshots[0].path), 'utf8'));
  const chip = first.elements.find((e) => e.dom_id === 'chip-t');
  check('LY-01 data: text cut by a clipping ancestor records the ancestor', !!chip && chip.clipped && chip.clipped.x === true && chip.clipped.by === '#chip-l',
    chip && chip.clipped);
}

async function reflowCopyTest(base, tmp) {
  const sc = {
    schema_version: 'ergo-scenario.v1', scenario_id: 'SC-driver-reflow-02', surface: { kind: 'web', url: '{BASE}/reflow2.html' },
    task_goal_ko: '패널을 연다', device_ids: ['galaxy-s24'], targets: {},
    steps: [{ action: 'wait', ms: 250 }, { action: 'wait', ms: 250 }, { action: 'tap', target: '#open-panel' }, { action: 'wait', ms: 100 }],
    success: { selector_visible: '#panel' },
  };
  writeJson(path.join(tmp, 'reflow2.json'), sc);
  const outDir = path.join(tmp, 'runs');
  const r = await runDriver(['run', '--scenario', path.join(tmp, 'reflow2.json'), '--device', 'galaxy-s24', '--out', outDir, '--run-id', 'R-reflow2', '--base', base]);
  if (!check('reflow copy galaxy-s24: exit 0', r.code === 0, `${r.code} ${r.err}`)) return;
  const { run } = loadRun(path.join(outDir, 'R-reflow2'));
  const recs = run.reflow || [];
  check('reflow copy: a ticking counter does not make new screens; the newest copy of a screen is kept',
    recs.length === 2 && recs.every((x) => !x.error && !x.styles_lost) && recs[0].snapshot_id !== run.snapshots[0].snapshot_id,
    recs.map((x) => [x.snapshot_id, x.error, x.styles_lost]));
  const offenders = recs.flatMap((x) => (x.offenders || []).map((o) => o.dom_id));
  check('reflow copy: CSSOM-inserted, adopted, shadow-root and crossorigin same-origin styles reach the copy',
    ['cssom-box', 'adopted-box', 'shadow-wide', 'link-box'].every((id) => offenders.includes(id)) && !offenders.includes('hero'), offenders);
  check('reflow copy: off-canvas, inert and noscript content does not stick out',
    !offenders.includes('cart') && !offenders.includes('inert-wide') && !offenders.includes('ns-wide'), offenders);
  const buy = recs.flatMap((x) => x.offenders || []).find((o) => o.dom_id === 'buy-now');
  check('reflow copy: a button pushed past the edge inside a fixed bar is an offender (fixed)', !!buy && buy.fixed === true, buy);
  const lost = recs.flatMap((x) => (x.lost || []).map((o) => o.dom_id));
  check('reflow copy: an off-canvas fixed menu below a breakpoint is neither lost nor an offender; a carousel slide is not lost',
    !lost.includes('side-a1') && !offenders.includes('side-nav') && !offenders.includes('side-a1') && !lost.includes('promo-2'), { lost, offenders });
  check('reflow copy: links in a list collapsed below a breakpoint (with or without a toggle) are not lost',
    !lost.includes('gnb-a1') && !lost.includes('foot-a1'), recs.map((x) => x.lost));
}

async function adaptationTest(base, tmp) {
  const { pw, info } = loadPlaywright();
  const { scenario } = normalizeScenario({ schema_version: 'ergo-scenario.v1', scenario_id: 'SC-adaptation',
    surface: { kind: 'web', url: `${base}/reflow_adaptation.html` }, targets: {},
    steps: [{ action: 'type', target: '#private-note', text: 'TYPED-PRIVATE-SENTINEL-8fb2', redact: true }],
    success: { selector_visible: '#ordinary-label' } }, { requireSteps: true });
  const dir = path.join(tmp, 'runs', 'R-adaptation');
  fs.mkdirSync(dir, { recursive: true });
  const session = new WebSession({ pw, pwInfo: info, scenario, runDir: dir, runId: 'R-adaptation', profileId: 'EP-S24',
    deviceRequest: { id: 'galaxy-s24' }, mode: 'scripted', warnings: [],
    options: { headed: false, settleMs: 0, feedbackTimeoutMs: 0, focusWalk: false, visualFeedback: false,
      locale: 'ko-KR', timezoneId: 'Asia/Seoul', buildId: 'owned-adaptation-v1', buildIdSource: 'fixture' } });
  session.redactSelectors.add('#spacing-safe');
  try {
    await session.start();
    const first = JSON.parse(fs.readFileSync(path.join(dir, `${session.lastSnapshotId}.json`), 'utf8'));
    check('adaptation privacy: prefilled textarea value is absent from its exported accessible label',
      first.elements.find((e) => e.selector === '#private-note')?.a11y.visible_label === ''
      && !JSON.stringify(first).includes('PREFILLED-PRIVATE-SENTINEL-7f4c'));
    check('adaptation privacy: ordinary button label survives', first.elements.find((e) => e.selector === '#ordinary-label')?.a11y.visible_label === '정상 버튼 이름');
    await session.act(scenario.steps[0]);
    await session.page.locator('#private-note').focus();
    await session.page.evaluate(() => window.scrollTo(0, 80));
    const state = () => session.page.evaluate(() => ({ width: innerWidth, height: innerHeight, scroll: scrollY, focus: document.activeElement.id, value: document.querySelector('#private-note').value }));
    const before = await state();
    check('adaptation privacy: serialized copies omit prefilled and typed sentinel', session.reflowScreens.every((s) => !s.html.includes('PREFILLED-PRIVATE-SENTINEL-7f4c') && !s.html.includes('TYPED-PRIVATE-SENTINEL-8fb2')));
    await session.adaptationPass();
    check('adaptation: live viewport, input, focus and scroll stay unchanged', JSON.stringify(before) === JSON.stringify(await state()));
    await session.reflowPass();
    await session.finish();
    const run = JSON.parse(fs.readFileSync(path.join(dir, 'run.json'), 'utf8'));
    const spacing = run.adaptation.find((r) => r.kind === 'text_spacing');
    const short = run.adaptation.find((r) => r.kind === 'short_height');
    check('adaptation: conditions keep source CSS mapping and have both capture anchors', [spacing, short].every((r) => r.status === 'measured' && r.applied && r.evaluable
      && r.dpr === 3 && r.baseline_snapshot_id && r.snapshot_id && r.baseline_viewport_css.join() === '360,780'), run.adaptation);
    check('adaptation spacing: fixed element box stays same but Range content is lost', spacing?.lost.some((x) => x.selector === '#spacing-cut'
      && x.before.box.h === x.after.box.h && x.before.visible_fraction >= .999 && x.after.visible_fraction < .999), spacing);
    const larger = spacing?.overrides.find((x) => x.selector === '#already-large');
    check('adaptation spacing: larger authored settings are never reduced', !!larger
      && ['line_height', 'paragraph_after', 'letter_spacing', 'word_spacing'].every((key) => larger.after[key] >= larger.before[key]), larger);
    check('adaptation short height: fixed toolbar CTA is clipped and remains eligible', short?.viewport_css.join() === '360,390'
      && short.lost.some((x) => x.selector === '#fixed-cta' && x.kind === 'control'), short);
    check('adaptation: growing text, long scrollable lines and document/container controls remain reachable', run.adaptation.every((r) => !r.lost.some((x) => ['#spacing-safe', '#spacing-scrollword', '#document-cta', '#scroll-cta', '#carousel-hidden'].includes(x.selector))));
    check('adaptation privacy: all saved records omit field sentinels', fs.readdirSync(dir).filter((n) => n.endsWith('.json')).every((n) => {
      const text = fs.readFileSync(path.join(dir, n), 'utf8');
      return !text.includes('PREFILLED-PRIVATE-SENTINEL-7f4c') && !text.includes('TYPED-PRIVATE-SENTINEL-8fb2');
    }));
    const python = process.env.ERGOQA_PYTHON || 'python3';
    const result = spawnSync(python, ['-c', 'from ergoqa.snapshot import load_run_dir; import sys; load_run_dir(sys.argv[1])', dir],
      { encoding: 'utf8', env: { ...process.env, PYTHONPATH: REPO } });
    check('adaptation: loader verifies auxiliary PNG hashes and conditions', result.status === 0, result.stderr);
    const changedCopies = run.adaptation.flatMap((r) => [r.baseline_snapshot_id, r.snapshot_id]).filter(Boolean)
      .map((id) => JSON.parse(fs.readFileSync(path.join(dir, `${id}.json`), 'utf8')));
    check('adaptation typography privacy: protected fields have no derived body metrics in copied captures',
      changedCopies.length > 0 && changedCopies.every((s) => ['#private-note', '#spacing-safe'].every((selector) => {
        const metric = s.elements.find((e) => e.selector === selector)?.font_metrics;
        return metric?.status === 'unavailable' && metric.body_height_px === null && Object.keys(metric.probes || {}).length === 0;
      })));
  } finally {
    if (session.browserTransport) await session.browserTransport.close([session.context]);
  }
  const cleanScenario = { schema_version: 'ergo-scenario.v1', scenario_id: 'SC-adaptation-clean',
    surface: { kind: 'web', url: `${base}/reflow_adaptation.html?clean` }, targets: {},
    steps: [{ action: 'type', target: '#private-note', text: 'TYPED-PRIVATE-SENTINEL-8fb2', redact: true }],
    success: { selector_visible: '#ordinary-label' } };
  writeJson(path.join(tmp, 'adaptation-clean.json'), cleanScenario);
  const clean = await runDriver(['run', '--scenario', path.join(tmp, 'adaptation-clean.json'), '--device', 'galaxy-s24',
    '--out', path.join(tmp, 'runs'), '--run-id', 'R-adaptation-clean', '--no-focus-walk']);
  const cleanRun = clean.code === 0 ? loadRun(path.join(tmp, 'runs', 'R-adaptation-clean')).run : null;
  check('adaptation: responsive clean variant has measured conditions and no new losses', cleanRun?.adaptation.length === 2
    && cleanRun.adaptation.every((r) => r.status === 'measured' && r.lost.length === 0), cleanRun?.adaptation ?? clean.err);
  cleanScenario.surface.url = `${base}/reflow_adaptation.html?disappear`;
  writeJson(path.join(tmp, 'adaptation-disappear.json'), cleanScenario);
  const disappeared = await runDriver(['run', '--scenario', path.join(tmp, 'adaptation-disappear.json'), '--device', 'galaxy-s24',
    '--out', path.join(tmp, 'runs'), '--run-id', 'R-adaptation-disappear', '--no-focus-walk']);
  const disappearRun = disappeared.code === 0 ? loadRun(path.join(tmp, 'runs', 'R-adaptation-disappear')).run : null;
  check('adaptation: a newly hidden control requires alternate-access review', disappearRun?.adaptation.some((r) => r.kind === 'short_height'
    && r.status === 'unevaluable' && !r.evaluable && r.gaps.includes('content_disappeared_unverified')), disappearRun?.adaptation ?? disappeared.err);
}

async function dialogTest(base, tmp) {
  const sc = {
    schema_version: 'ergo-scenario.v1', scenario_id: 'SC-driver-dialog-01', surface: { kind: 'web', url: '{BASE}/dialog.html' },
    task_goal_ko: '주소를 찾고 본인 확인을 한다', device_ids: ['desktop-1920'], targets: {},
    steps: [{ action: 'click', target: '#open-bad' }, { action: 'click', target: '#close-bad' }, { action: 'click', target: '#open-good' },
      { action: 'click', target: '#close-good' }, { action: 'click', target: '#chip-hot' }, { action: 'click', target: '#chip-ok-t' }],
    success: { url_contains: 'dialog' },
  };
  writeJson(path.join(tmp, 'dialog.json'), sc);
  const outDir = path.join(tmp, 'runs');
  const r = await runDriver(['run', '--scenario', path.join(tmp, 'dialog.json'), '--device', 'desktop-1920', '--out', outDir, '--run-id', 'R-dialog',
    '--base', base, '--no-focus-walk', '--no-reflow']);
  if (!check('dialog desktop-1920: exit 0', r.code === 0, `${r.code} ${r.err}`)) return;
  const loaded = loadRun(path.join(outDir, 'R-dialog'));
  const snaps = [...loaded.snaps.values()];
  const layersAt = (i) => (snaps[i] && snaps[i].layers) || [];
  check('layers: the first screen has no layer (a small toast is not one)', layersAt(0).length === 0, layersAt(0));
  const bad = layersAt(1).find((l) => l.dom_id === 'sheet');
  check('layers: a fixed painted sheet over the screen is a layer, and focus stayed outside it',
    !!bad && bad.kind === 'sheet' && bad.contains_focus === false && snaps[1].focus && snaps[1].focus.dom_id === 'open-bad', { layers: layersAt(1), focus: snaps[1].focus });
  const good = layersAt(3).find((l) => l.dom_id === 'dlg');
  check('layers: a modal dialog that takes focus is recorded with focus inside', !!good && good.kind === 'modal' && good.contains_focus === true,
    { layers: layersAt(3), focus: snaps[3] && snaps[3].focus });
  check('focus record never carries a field value', !JSON.stringify(snaps.map((x) => x.focus)).includes('value'), snaps.map((x) => x.focus));
  const ctl = (sel) => (loaded.run.steps.find((st) => st.action && st.action.target === sel) || {}).target_control;
  check('clicks record what they landed on: a role-less div is not a control; text inside a button is',
    ctl('#chip-hot') && ctl('#chip-hot').control === false && ctl('#chip-hot').contains_control === false && ctl('#chip-hot').ancestor_ids.includes('chips')
    && ctl('#chip-ok-t') && ctl('#chip-ok-t').control === true && ctl('#open-bad').control === true,
    { hot: ctl('#chip-hot'), ok: ctl('#chip-ok-t') });
}

function runReader(args, { reader = path.join(HERE, 'read_page.mjs'), env = process.env } = {}) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [reader, ...args], { stdio: ['ignore', 'pipe', 'pipe'], env });
    let out = '';
    let err = '';
    child.stdout.on('data', (d) => { out += d; });
    child.stderr.on('data', (d) => { err += d; });
    const timer = setTimeout(() => child.kill('SIGKILL'), 90000);
    child.on('close', (code) => {
      clearTimeout(timer);
      const line = out.trim().split('\n').filter(Boolean).map((l) => {
        try {
          return JSON.parse(l);
        } catch {
          return null;
        }
      }).filter(Boolean).pop() || null;
      resolve({ code, line, err });
    });
  });
}

const PAGE_READ_KEYS = new Set(['schema_version', 'url', 'final_url', 'status', 'redirects', 'title', 'lang', 'text', 'json_ld', 'meta', 'challenge',
  'login_form', 'context', 'waited_ms', 'scrolls', 'blocked_types', 'device_id', 'driver_version', 'browser_connected', 'browser_version',
  'playwright_client_version', 'started_at', 'finished_at']);
const PAGE_READ_REQUIRED = ['schema_version', 'url', 'final_url', 'status', 'text', 'context', 'started_at', 'finished_at'];

function pageReadShape(doc) {
  const extra = Object.keys(doc).filter((k) => !PAGE_READ_KEYS.has(k));
  const missing = PAGE_READ_REQUIRED.filter((k) => !(k in doc));
  const metaExtra = Object.keys(doc.meta || {}).filter((k) => !['description', 'og', 'robots', 'tdm_reservation'].includes(k));
  return [...extra.map((k) => `extra ${k}`), ...missing.map((k) => `missing ${k}`), ...metaExtra.map((k) => `meta extra ${k}`)];
}

async function readPageTest(base, tmp) {
  const out = (name) => path.join(tmp, `read-${name}.json`);
  const load = (name) => JSON.parse(fs.readFileSync(out(name), 'utf8'));
  let r = await runReader([`${base}/read/article.html`, '--allow-local', '--out', out('article'), '--device', 'galaxy-s24']);
  if (check('read_page article: exit 0 with a document', r.code === 0 && fs.existsSync(out('article')), `${r.code} ${r.err}`)) {
    const d = load('article');
    check('read_page: document has only ux-page-read.v1 fields', pageReadShape(d).length === 0 && d.schema_version === 'ux-page-read.v1'
      && d.context === 'anonymous', pageReadShape(d));
    const markers = JSON.parse(fs.readFileSync(path.join(REPO, 'uxresearch', 'data', 'markers.json'), 'utf8'));
    check('read_page: the driver version records the markers version without adding schema fields',
      d.driver_version === `read_page/2; markers/${markers.version}`, d.driver_version);
    check('read_page: browser transport and versions recorded',
      d.browser_connected === (process.env.REMORSEARCH_BROWSER_WS !== undefined) && d.browser_version.length > 0
      && d.playwright_client_version === '1.56.1', d);
    check('read_page: unscrubbed capture is private (mode 0600)', (fs.statSync(out('article')).mode & 0o777) === 0o600);
    fs.chmodSync(out('article'), 0o644);
    r = await runReader([`${base}/read/article.html`, '--allow-local', '--out', out('article'), '--scrolls', '0']);
    check('read_page: replacing a public capture makes it private (mode 0600)', r.code === 0
      && (fs.statSync(out('article')).mode & 0o777) === 0o600);
    // The first capture is retained for its scrolling/content assertions below.
    check('read_page: scrolling reaches text below the fold and loads scroll-triggered content',
      d.text.includes('아래쪽 본문') && d.text.includes('스크롤로 불러온 댓글') && d.scrolls >= 1, { scrolls: d.scrolls, chars: d.text.length });
    check('read_page: JSON-LD kept (parsed, and raw when invalid), meta tags read',
      d.json_ld.length === 2 && d.json_ld[0].headline === '첫 주문 후기' && typeof d.json_ld[1] === 'string'
      && d.meta.description === '가게 이용 후기' && d.meta.og['og:title'] === '후기 모음' && d.meta.robots === 'index, follow' && d.meta.tdm_reservation === '1',
      { json_ld: d.json_ld, meta: d.meta });
    check('read_page: images, media and fonts are blocked (no image request reached the server)',
      READ_HITS.image === 0 && d.blocked_types.join() === 'image,media,font', READ_HITS);
    check('read_page: the browser keeps its own identity (no emulated phone user agent)', /Chrome/.test(READ_HITS.ua || '')
      && !/Android|iPhone/.test(READ_HITS.ua || '') && d.device_id === 'galaxy-s24' && d.status === 200 && d.lang === 'ko' && d.login_form === false && d.challenge.interactive === false, { ua: READ_HITS.ua, challenge: d.challenge });
  }
  r = await runReader([`${base}/read/redirect`, '--allow-local', '--out', out('redirect')]);
  if (check('read_page redirect: exit 0', r.code === 0, `${r.code} ${r.err}`)) {
    const d = load('redirect');
    check('read_page: redirects recorded, final_url is the target', d.redirects.length === 1 && d.redirects[0].status === 302
      && d.final_url.endsWith('/read/article.html') && d.url.endsWith('/read/redirect'), { redirects: d.redirects, final: d.final_url });
  }
  for (const [name, file, interactive, scrolls, marker] of [
    ['persistent', 'persistent', false, 0, 'browser-check'],
    ['self-clearing', 'check', false, 0, 'cf-please-wait'],
    ['after load', 'late-load', false, 0, 'browser-check'],
    ['during load before it clears', 'during-load', false, 0, 'browser-check'],
    ['after scroll', 'late-scroll', false, 1, 'browser-check'],
    ['human after scroll', 'late-human-scroll', true, 1, 'g-recaptcha'],
    ['self-clearing after scroll', 'transient-scroll', false, 1, 'browser-check'],
  ]) {
    r = await runReader([`${base}/read/${file}.html`, '--allow-local', '--out', out(file), '--max-wait-ms', '15000']);
    if (check(`read_page ${name} check: exit 3 with a document`, r.code === 3 && fs.existsSync(out(file)), `${r.code} ${r.err}`)) {
      const d = load(file);
      check(`read_page ${name} check: markers recorded, no wait, no further scroll or page content`,
        d.challenge.interactive === interactive && d.challenge.markers.some((m) => m.includes(marker))
        && d.waited_ms === 0 && d.scrolls === scrolls && d.text === '' && d.json_ld.length === 0
        && d.title === '' && pageReadShape(d).length === 0 && (READ_HITS.scrolls[file] || 0) <= scrolls, d);
      check(`read_page ${name} check: stopped capture is private (mode 0600)`, (fs.statSync(out(file)).mode & 0o777) === 0o600);
    }
  }
  check('read_page: self-clearing checks stop before their clearing timers fire', READ_HITS.cleared === 0, READ_HITS);
  r = await runReader([`${base}/read/captcha.html`, '--allow-local', '--out', out('captcha')]);
  if (check('read_page human check: exit 3 (stopped) with a document', r.code === 3 && fs.existsSync(out('captcha')), `${r.code} ${r.err}`)) {
    const d = load('captcha');
    check('read_page: the interactive check is reported, not solved, and the page is not scrolled',
      d.challenge.interactive === true && d.challenge.markers.some((m) => m.includes('g-recaptcha')) && d.scrolls === 0
      && d.waited_ms === 0 && d.text === '' && d.json_ld.length === 0, d.challenge);
  }
  r = await runReader([`${base}/read/login.html`, '--allow-local', '--out', out('login')]);
  check('read_page: a password field is reported (exit 0; the reader decides whether the page is gated)',
    r.code === 0 && load('login').login_form === true, `${r.code} ${r.err}`);
  r = await runReader([`${base}/read/article.html`]);
  check('read_page: local and private addresses are refused without --allow-local (exit 2)', r.code === 2 && /refused/.test(r.err), `${r.code} ${r.err}`);
  r = await runReader(['file:///etc/passwd']);
  check('read_page: only http and https are read (exit 2)', r.code === 2, `${r.code} ${r.err}`);
  r = await runReader(['http://127.0.0.1:9/', '--allow-local', '--out', out('down'), '--timeout-s', '5']);
  check('read_page: an unreachable host is unread (exit 4, no document)', r.code === 4 && !fs.existsSync(out('down')) && r.line && r.line.exit === 4,
    `${r.code} ${JSON.stringify(r.line)}`);
  const installed = path.join(tmp, 'reader-with-invalid-markers');
  const driverDir = path.join(installed, 'drivers', 'web');
  const markerDir = path.join(installed, 'uxresearch', 'data');
  fs.mkdirSync(driverDir, { recursive: true });
  fs.mkdirSync(markerDir, { recursive: true });
  for (const file of ['read_page.mjs', 'read_capture.mjs', 'devices.mjs', 'browser_transport.mjs', 'playwright_loader.mjs', 'util.mjs']) {
    fs.copyFileSync(path.join(HERE, file), path.join(driverDir, file));
  }
  for (const [name, data] of [['missing', null], ['corrupt JSON', '{broken'], ['corrupt structure', '{}']]) {
    const markerFile = path.join(markerDir, 'markers.json');
    if (data !== null) fs.writeFileSync(markerFile, data);
    const before = READ_HITS.navigations;
    r = await runReader([`${base}/read/article.html`, '--allow-local', '--out', out(name)], { reader: path.join(driverDir, 'read_page.mjs') });
    check(`read_page: ${name} markers fail closed before browser loading or navigation (exit 4)`,
      r.code === 4 && r.line?.reason === 'invalid_markers' && /cannot read or parse challenge markers/.test(r.line.detail)
      && !fs.existsSync(out(name)) && READ_HITS.navigations === before, r);
  }
  const markers = JSON.parse(fs.readFileSync(path.join(REPO, 'uxresearch', 'data', 'markers.json'), 'utf8'));
  for (const key of ['chrome_idents', 'author_idents', 'item_idents', 'keep_in_author_idents']) {
    for (const bad of ['missing', 'empty', 'invalid']) {
      const m = structuredClone(markers);
      if (bad === 'missing') delete m[key];
      else m[key] = bad === 'empty' ? [] : { tokens: ['valid', 3] };
      fs.writeFileSync(path.join(markerDir, 'markers.json'), JSON.stringify(m));
      const before = READ_HITS.navigations;
      const name = `${key}-${bad}`;
      r = await runReader([`${base}/read/article.html`, '--allow-local', '--out', out(name)], { reader: path.join(driverDir, 'read_page.mjs') });
      check(`read_page: ${bad} ${key} fail closed before browser loading or navigation`,
        r.code === 4 && r.line?.reason === 'invalid_markers' && r.line.detail.includes(key)
        && !fs.existsSync(out(name)) && READ_HITS.navigations === before, r);
    }
  }
  const names = ['빛나는고슴도치', '잠자는수달', '지나가는사슴', '초코칩다람쥐', '가을하늘펭귄', '북극여우님', '이끼낀돌',
    '반짝반짝돌멩이', '홍길동', 'kim_s', '별빛여우', '이슬나그네'];
  for (const [name, count, kept, dropped, boundaries] of [
    ['board-post-comments', 4, ['BOARD-BODY-SENTINEL', 'COMMENT-ONE-SENTINEL', 'COMMENT-TWO-SENTINEL', 'COMMENT-THREE-SENTINEL',
      '2026.09.27 21:20', '2026.09.28 07:55'], ['POPULAR-SENTINEL', 'RELATED-SENTINEL', '인기 글', '댓글 3', '테스트 갤러리', '로그인'], 3],
    ['store-reviews', 2, ['REVIEW-ONE-SENTINEL', 'REVIEW-TWO-SENTINEL', '2026-09-18', '2026-09-20', '별점 5', '별점 2'], ['리뷰를 쓰려면'], 2],
    ['blog-popular-sidebar', 2, ['BLOG-BODY-SENTINEL', 'COMMENT-SENTINEL', '2026.09.25'], ['SIDEBAR-SENTINEL', 'SIDEBAR-TWO-SENTINEL', '인기 포스트'], 1],
    ['board-writer-links', 4, ['WRITER-ROW-BODY-SENTINEL', 'NAME-CHILD-BODY-SENTINEL', 'STRONG-CHILD-BODY-SENTINEL', 'TIME-CHILD-BODY-SENTINEL',
      '2026.09.28 08:12', '조회 12', '2026-09-01', '추천 3', '3시간 전', '9월 1일', '★★★★☆'], ['테스트 게시판', '로그인'], 3],
  ]) {
    r = await runReader([`${base}/read/${name}.html`, '--allow-local', '--out', out(name), '--scrolls', '0']);
    if (!check(`read_page ${name}: exit 0`, r.code === 0, r)) continue;
    const d = load(name), text = d.text;
    check(`read_page ${name}: names and chrome absent, one placeholder per label, bodies/dates/ratings and item boundaries retained`,
      [...names, ...dropped].every((s) => !text.includes(s)) && kept.every((s) => text.includes(s))
      && text.split('[author]').length - 1 === count && text.split('\n---\n').length - 1 >= boundaries, text);
    if (name === 'store-reviews') check('read_page: a boundary separates the two review bodies',
      text.split('REVIEW-ONE-SENTINEL')[1].split('REVIEW-TWO-SENTINEL')[0].includes('\n---\n'), text);
  }
  r = await runReader([`${base}/read/structure.html`, '--allow-local', '--out', out('structure'), '--scrolls', '0']);
  if (check('read_page structure: exit 0', r.code === 0, r)) {
    const text = load('structure').text;
    check('read_page: author wrappers keep bodies while nested member/profile links and data/rel/itemprop labels lose names',
      ['WRAPPER-BODY-SENTINEL', 'NO-LABEL-ONE', 'NO-LABEL-TWO', 'WHOLE-TOKEN-SENTINEL', '2026년 9월 1일', '2 days ago',
        'Sep 1, 2026', '12,000 views', 'rating 4/5', '★★★★☆', 'KEEP-TIME-SENTINEL', '２０２６-０９-０１'].every((s) => text.includes(s))
      && ['민들레연필', '초록지우개', '황금방울새', '프로필작가', '블로그작가', '채널작가', '시간옆이름', '자리이름', '숨은이름',
        'CHROME-WIDGET', 'PRIVATE-FORM-SENTINEL'].every((s) => !text.includes(s))
      && text.split('[author]').length - 1 === 11 && text.split('\n---\n').length - 1 === 2, text);
  }
  r = await runReader([`${base}/read/body-chrome.html`, '--allow-local', '--out', out('body-chrome'), '--scrolls', '0']);
  check('read_page: chrome marking on the body itself drops all body text', r.code === 0 && load('body-chrome').text === '', r);
  const { pw, info } = loadPlaywright();
  const transport = await openBrowser(pw, info);
  let context;
  try {
    context = await transport.browser.newContext();
    const page = await context.newPage();
    await page.goto(`${base}/read/structure.html`);
    const before = await page.evaluate(() => {
      window.__captureMutations = 0;
      new MutationObserver((list) => { window.__captureMutations += list.length; }).observe(document.body,
        { subtree: true, childList: true, attributes: true, characterData: true });
      return document.body.outerHTML;
    });
    await page.evaluate(capturePage, { blocks: 10, chars: 1_000_000, structure: { chrome: markers.chrome_idents,
      author: markers.author_idents.tokens, item: markers.item_idents.tokens, keep: markers.keep_in_author_idents.tokens,
      overrides: [], profilePatterns: [] } });
    const after = await page.evaluate(() => ({ html: document.body.outerHTML, mutations: window.__captureMutations }));
    check('read_page: the structure pass changes only a detached clone (live DOM identical, no mutations)',
      before === after.html && after.mutations === 0, after.mutations);
  } finally { await transport.close([context]); }
  r = await runReader([`${base}/read/article.html`, '--allow-local', '--out', out('invalid-endpoint')],
    { env: { ...process.env, REMORSEARCH_BROWSER_WS: 'wss://127.0.0.1:39123/refused' } });
  check('read_page: invalid REMORSEARCH_BROWSER_WS fails with a clear error and no capture',
    r.code === 4 && /REMORSEARCH_BROWSER_WS/.test(r.line?.detail || '') && !fs.existsSync(out('invalid-endpoint')), r);
  const ordinary = path.join(tmp, 'ordinary-output.json');
  writeJsonAtomic(ordinary, { ordinary: true });
  check('atomic writer: other callers retain their ordinary file mode', (fs.statSync(ordinary).mode & 0o777) === (0o644 & ~process.umask()));
}

function connectClient(url) {
  const child = spawn(process.execPath, [path.join(HERE, 'fixtures', 'connect_client.mjs'), url],
    { stdio: ['ignore', 'ignore', 'pipe', 'ipc'] });
  let err = '';
  let sequence = 0;
  const pending = new Map();
  let readyResolve;
  let readyReject;
  const ready = new Promise((resolve, reject) => { readyResolve = resolve; readyReject = reject; });
  const timer = setTimeout(() => { readyReject(new Error(`client ready timed out: ${err}`)); child.kill('SIGKILL'); }, 15000);
  child.stderr.on('data', (data) => { err += data; });
  child.on('message', (message) => {
    if (message.event === 'ready') {
      clearTimeout(timer);
      readyResolve(message);
      return;
    }
    const request = pending.get(message.id);
    if (!request) return;
    pending.delete(message.id);
    clearTimeout(request.timer);
    if (message.error) request.reject(new Error(message.error));
    else request.resolve(message.result);
  });
  const exited = new Promise((resolve) => child.once('exit', (code, signal) => {
    clearTimeout(timer);
    readyReject(new Error(`client exited: ${code} ${signal} ${err}`));
    for (const request of pending.values()) { clearTimeout(request.timer); request.reject(new Error(`client exited: ${err}`)); }
    pending.clear();
    resolve({ code, signal });
  }));
  return {
    child, ready, exited,
    request(op, value) {
      return new Promise((resolve, reject) => {
        const id = ++sequence;
        const requestTimer = setTimeout(() => { pending.delete(id); reject(new Error(`client ${op} timed out: ${err}`)); }, 10000);
        pending.set(id, { resolve, reject, timer: requestTimer });
        child.send({ id, op, value });
      });
    },
  };
}

async function connectTest(base, tmp) {
  for (const url of ['ws://127.0.0.1:39123/path', 'ws://localhost:1234/path', 'ws://[::1]:1234/path']) {
    check(`browser connection: accepts ${url}`, validateBrowserWs(url) === url);
  }
  for (const url of ['', 'not a URL', 'http://127.0.0.1/path', 'wss://127.0.0.1/path', 'ws://example.com/path',
    'ws://127.0.0.2/path', 'ws://localhost.example.com/path', 'ws://127.0.0.1.example.com/path', 'ws://0.0.0.0/path',
    'ws://[::ffff:127.0.0.1]/path', 'ws://user:secret@localhost/path', 'ws://localhost/path#fragment']) {
    let error = null;
    try { validateBrowserWs(url); } catch (err) { error = err; }
    check(`browser connection: refuses ${url || 'an empty endpoint'} with the variable named`, /REMORSEARCH_BROWSER_WS/.test(error?.message || ''));
  }
  const refused = await runDriver(['run', '--scenario', path.join(tmp, 'scenario.json'), '--profile', path.join(tmp, 'p-desk.json'),
    '--out', path.join(tmp, 'runs'), '--run-id', 'R-invalid-connection', '--base', base],
    { env: { ...process.env, REMORSEARCH_BROWSER_WS: 'ws://example.com/refused' } });
  const refusedRun = JSON.parse(fs.readFileSync(path.join(tmp, 'runs', 'R-invalid-connection', 'run.json'), 'utf8'));
  check('live driver: invalid REMORSEARCH_BROWSER_WS blocks the run before opening a page',
    refused.code === 4 && refusedRun.status === 'blocked' && refusedRun.snapshots.length === 0
    && refusedRun.blocked_reasons.some((r) => /REMORSEARCH_BROWSER_WS/.test(r)), refusedRun.blocked_reasons);
  if (process.env.REMORSEARCH_BROWSER_WS === undefined) {
    skip('shared browser clients and version handshake', 'set REMORSEARCH_BROWSER_WS to a loopback launchServer endpoint');
    return;
  }
  const { pw, info } = loadPlaywright();
  let mismatch = null;
  try {
    const incompatible = { chromium: { connect: (url, options) => pw.chromium.connect(url,
      { ...options, headers: { 'User-Agent': 'Playwright/0.0.0' } }) } };
    const unexpected = await openBrowser(incompatible, { ...info, version: '0.0.0' }, { timeout: 5000 });
    await unexpected.close();
  } catch (err) { mismatch = err; }
  check('browser connection: protocol rejects a mismatched client with both versions and the variable named',
    /REMORSEARCH_BROWSER_WS: Playwright client\/server version mismatch \(client 0\.0\.0, server 1\.56\)/.test(mismatch?.message || ''), mismatch?.message);

  const clients = [];
  const start = () => { const client = connectClient(`${base}/read/storage.html`); clients.push(client); return client; };
  const empty = (s) => s.cookies.length === 0 && s.storage.local === null && s.storage.session === null;
  const owned = (s, value) => s.cookies.length === 1 && s.cookies[0].join() === `owner,${value}`
    && s.storage.local === value && s.storage.session === value;
  try {
    const a = start();
    const b = start();
    const [ar, br] = await Promise.all([a.ready, b.ready]);
    check('browser connection: two simultaneous clients open pages in fresh anonymous contexts',
      ar.connected && br.connected && empty(ar.initial) && empty(br.initial)
      && ar.browser_version === br.browser_version && ar.playwright_client_version === '1.56.1', { ar, br });
    await a.request('seed', 'first-client');
    check('browser connection: cookies, local storage and session storage do not leak to the second client', empty(await b.request('probe')));
    await b.request('seed', 'second-client');
    check('browser connection: both clients retain separate cookies and storage',
      owned(await a.request('probe'), 'first-client') && owned(await b.request('probe'), 'second-client'));
    await a.request('close');
    const exit = await a.exited;
    check('browser connection: a client exiting early leaves the other client and server working',
      exit.code === 0 && owned(await b.request('navigate'), 'second-client'));
    const c = start();
    check('browser connection: a later client starts fresh after another client disconnects', empty((await c.ready).initial));
    c.child.kill('SIGKILL');
    await c.exited;
    check('browser connection: abrupt client exit also leaves the other client working', owned(await b.request('navigate'), 'second-client'));
    await b.request('close');
    check('browser connection: surviving client closes its context and disconnects normally', (await b.exited).code === 0);
  } finally {
    for (const client of clients) if (client.child.exitCode === null && client.child.signalCode === null) client.child.kill('SIGKILL');
    await Promise.all(clients.map((client) => client.exited));
  }
}

async function taskIntegrityTest(base, tmp) {
  const outDir = path.join(tmp, 'integrity-runs');
  const sentinel = 'RQ-PRIVATE-SENTINEL-67291';
  const input = { action: 'type', target: '#memo', text: sentinel, redact: true, delay_ms: 0 };
  const tap = (target) => ({ action: 'tap', target });
  const criterion = (id, selector, property, expected, after_step) => ({ id, selector, property, expected,
    ...(after_step === undefined ? {} : { after_step }), severity: 'P2', consequence: '명시한 요청사항이 해당 단계에 유지되어야 합니다.' });
  const ref = (id, selector, property, from_step, after_step) => {
    const result = criterion(id, selector, property, '', after_step);
    delete result.expected;
    return { ...result, from_step };
  };
  const scenarioFor = (id, steps, checks) => ({ schema_version: 'ergo-scenario.v1', scenario_id: id,
    surface: { kind: 'web', url: `${base}/task-integrity.html` }, task_goal_ko: '요청사항과 선택을 확인합니다', device_ids: ['galaxy-s24'],
    targets: {}, steps, success: { selector_visible: '#summary', task_checks: checks } });
  const runCase = async (id, sc, exit) => {
    const file = path.join(tmp, `${id}.json`);
    writeJson(file, sc);
    const r = await runDriver(['run', '--scenario', file, '--device', 'galaxy-s24', '--out', outDir, '--run-id', id,
      '--no-focus-walk', '--no-reflow', '--no-visual-feedback', '--feedback-timeout-ms', '0', '--settle-ms', '0']);
    check(`task integrity ${id}: real process exit ${exit}`, r.code === exit, { code: r.code, err: r.err });
    const run = loadRun(path.join(outDir, id)).run;
    const criteria = run.success_detail.criteria.filter((c) => c.kind === 'task_check');
    check(`task integrity ${id}: no expected or actual values in results`, criteria.every((c) => !('value' in c) && !('actual' in c) && !('expected' in c)));
    return { run, criteria, out: r.out + r.err, dir: path.join(outDir, id) };
  };
  const privateCheck = ref('retained', '#memo', 'value', 1, 1);
  for (const [name, mutate] of [
    ['duplicate id', (s) => s.success.task_checks.push({ ...privateCheck })],
    ['duplicate checkpoint', (s) => s.success.task_checks.push({ ...privateCheck, id: 'another' })],
    ['unreachable checkpoint', (s) => s.success.task_checks[0].after_step = 9],
    ['future input reference', (s) => s.success.task_checks[0].from_step = 2],
    ['wrong property type', (s) => s.success.task_checks[0] = criterion('bad', '#option', 'checked', 'true')],
    ['credential predicate', (s) => s.success.task_checks[0].selector = 'input[value="private"]'],
    ['whitespace value predicate', (s) => s.success.task_checks[0].selector = 'input[ value="private"]'],
    ['escaped attribute predicate', (s) => s.success.task_checks[0].selector = 'input[v\\61lue="private"]'],
    ['unknown criterion key', (s) => s.success.task_checks[0].guess = true],
    ['promotion without source selector', (s) => { delete s.steps[0].target; delete s.steps[0].redact; s.success.task_checks[0].redact = true; }],
  ]) {
    const sc = scenarioFor('invalid', [{ ...input }], [{ ...privateCheck }]);
    mutate(sc);
    let rejected = false;
    try { normalizeScenario(sc, { requireSteps: true }); } catch { rejected = true; }
    check(`task integrity validation: ${name} rejected`, rejected);
  }
  let invalidRedact = false;
  try { normalizeAction({ action: 'type', text: sentinel, redact: true }, { strict: true }); } catch { invalidRedact = true; }
  check('task integrity validation: redacted typing requires explicit selector', invalidRedact);
  for (const target of ['css=#memo', 'role=textbox[name="Request"]', '#memo:not(']) {
    if (target === '#memo:not(') continue; // Browser syntax validation is exercised before dispatch below.
    let rejected = false;
    try { normalizeAction({ action: 'type', text: sentinel, target, redact: true }, { strict: true }); } catch { rejected = true; }
    check('task integrity validation: redaction rejects non-CSS selector engines', rejected);
  }
  const promoted = normalizeScenario(scenarioFor('promoted', [{ ...input, redact: false }], [
    ref('early-copy', '#summary', 'text', 1, 1), { ...ref('late-copy', '#memo', 'value', 1), redact: true }]), { requireSteps: true }).scenario;
  check('task integrity validation: source redaction propagates to every reference regardless of order', promoted.steps[0].redact
    && promoted.success.task_checks.every((c) => c.redact));
  const hiddenRegion = await runCase('R-integrity-private-region', scenarioFor('private-region', [{ action: 'snapshot' }],
    [{ ...criterion('region-check', '#private-region', 'text', ''), redact: true }]), 0);
  const regionRecords = fs.readdirSync(hiddenRegion.dir).filter((name) => name.endsWith('.json'))
    .map((name) => fs.readFileSync(path.join(hiddenRegion.dir, name), 'utf8')).join('');
  check('task integrity capture: opted host omits private shadow text from saved snapshots', !regionRecords.includes('SHADOW-PRIVATE-DISPLAY-51984')
    && !regionRecords.includes('SHADOW-PRIVATE-48152'));
  const timingScenario = scenarioFor('capture-timing', [tap('#switch')], [criterion('timed-retention', '#display', 'text', 'retained', 1)]);
  delete timingScenario.success.selector_visible;
  timingScenario.surface.url = `${base}/task-integrity-timing.html`;
  const timed = await runCase('R-integrity-delayed-focus', timingScenario, 0);
  const timedSnapshot = JSON.parse(fs.readFileSync(path.join(timed.dir, `${timed.criteria[0].snapshot_id}.json`), 'utf8'));
  check('task integrity capture: delayed modal state check matches the captured state before focus wait', timed.criteria[0].result === 'pass'
    && timedSnapshot.elements.some((el) => el.selector === '#display' && el.text === 'retained'));
  timingScenario.surface.url += '?unstable=1';
  const unstable = await runCase('R-integrity-unstable-capture', timingScenario, 3);
  check('task integrity capture: state changed across PNG is unevaluable', unstable.run.status === 'completed' && unstable.run.success === null
    && unstable.criteria[0].result === 'unevaluable' && unstable.criteria[0].reason === 'capture_state_changed');
  const retained = await runCase('R-integrity-retained', scenarioFor('retained', [input, tap('#option'), tap('#copy')],
    [privateCheck, criterion('selected', '#option', 'checked', true, 2), { ...ref('final', '#summary', 'text', 1), redact: true }]), 0);
  check('task integrity: value/checkbox/final all measured with capture anchors', retained.run.status === 'completed'
    && retained.run.success === true && retained.criteria.every((c) => c.result === 'pass' && c.snapshot_id && c.element_id), retained.criteria);
  const lost = await runCase('R-integrity-lost', scenarioFor('lost', [input, tap('#lose'), input, tap('#copy')],
    [ref('early-loss', '#memo', 'value', 1, 2), ref('restored', '#memo', 'value', 1, 3), { ...ref('final', '#summary', 'text', 1), redact: true }]), 3);
  check('task integrity: restored value cannot erase earlier failure', lost.run.status === 'completed' && lost.run.success === false
    && lost.criteria.map((c) => c.result).join() === 'fail,pass,pass', lost.criteria);
  const reset = await runCase('R-integrity-reset', scenarioFor('reset', [input, tap('#reset')], [criterion('intentional-reset', '#memo', 'value', '')]), 0);
  check('task integrity: explicitly expected empty reset passes', reset.run.success === true);
  const shortPrivate = await runCase('R-integrity-short-private', scenarioFor('short-private', [
    { action: 'type', target: '#memo', text: 'a', redact: true, delay_ms: 0 }], [ref('short-private', '#memo', 'value', 1)]), 0);
  check('task integrity privacy: short private input preserves schema and collector identity', shortPrivate.run.schema_version === 'ergo-run.v1'
    && shortPrivate.run.driver.name === 'playwright-web' && shortPrivate.run.steps[0].action.text === '[redacted]');
  const python = process.env.ERGOQA_PYTHON || 'python3';
  const loaded = spawnSync(python, ['-c', 'from ergoqa.snapshot import load_run_dir; import sys; load_run_dir(sys.argv[1])', shortPrivate.dir],
    { encoding: 'utf8', env: { ...process.env, PYTHONPATH: REPO } });
  check('task integrity privacy: a single-character private source roundtrips the native capture loader', loaded.status === 0, loaded.stderr);
  const normalized = await runCase('R-integrity-normalized', scenarioFor('normalized', [
    { action: 'type', target: '#memo', text: '  safe memo  ', delay_ms: 0 }, tap('#normalize'), tap('#done')],
    [criterion('normalized', '#memo', 'value', 'SAFE MEMO', 2), criterion('cleanup', '#memo', 'value', ''), criterion('submitted', '#summary', 'text', 'SAFE MEMO')]), 0);
  check('task integrity: normalization and successful cleanup are authored explicitly', normalized.criteria.every((c) => c.result === 'pass'));
  check('task integrity: unrelated synthetic input remains recorded', normalized.run.steps[0].action.text === '  safe memo  ');
  const unknown = await runCase('R-integrity-unknown', scenarioFor('unknown', [input], [
    criterion('missing', '#absent', 'value', ''), criterion('ambiguous', '.ambiguous', 'text', ''),
    criterion('password', '#masked', 'value', ''), criterion('hidden', '#hidden', 'value', ''), criterion('transparent', '#transparent', 'value', 'stable fixture')]), 3);
  check('task integrity: missing/ambiguous/credential/hidden targets do not pass', unknown.run.status === 'completed' && unknown.run.success === null
    && unknown.criteria.every((c) => c.result === 'unevaluable' && c.passed === null), unknown.criteria);
  const failed = await runCase('R-integrity-technical-failure', scenarioFor('technical-failure', [
    { action: 'tap', target: '#absent', timeout_ms: 50 }, input], [ref('unvisited', '#memo', 'value', 2, 2)]), 3);
  check('task integrity: true action failure has failed execution and unvisited check', failed.run.status === 'failed' && failed.run.success === false
    && failed.criteria[0].reason === 'checkpoint_unvisited', failed.criteria);
  for (const test of [retained, lost, reset, unknown, failed]) {
    const records = fs.readdirSync(test.dir).filter((name) => name.endsWith('.json')).map((name) => fs.readFileSync(path.join(test.dir, name), 'utf8')).join('');
    check('task integrity privacy: sentinel absent from results, snapshots and errors', !records.includes(sentinel) && !test.out.includes(sentinel));
  }
  const interactiveFile = path.join(tmp, 'integrity-interactive.json');
  writeJson(interactiveFile, scenarioFor('interactive', [input, tap('#lose'), tap('#copy'), input],
    [ref('preserve', '#memo', 'value', 1, 2), ref('authored-input', '#memo', 'value', 4, 4), ref('unvisited', '#memo', 'value', 1, 7),
      { ...criterion('private-choice', '#choice', 'value', 'CHOICE-PRIVATE-51983', 1), redact: true },
      { ...criterion('private-shadow', '#private-region', 'text', '', 1), redact: true }]));
  const agent = path.join(tmp, 'integrity-agent.json');
  writeJson(agent, { model_family: 'selftest', input_channel: 'screenshot+a11y' });
  let readyResolve;
  const readyPromise = new Promise((resolve) => { readyResolve = resolve; });
  const proc = runDriver(['serve', '--scenario', interactiveFile, '--device', 'galaxy-s24', '--agent-json', agent,
    '--out', outDir, '--run-id', 'R-integrity-interactive', '--port', '0', '--no-focus-walk', '--no-reflow',
    '--no-visual-feedback', '--feedback-timeout-ms', '0', '--settle-ms', '0'], { onLine: (line) => { if (line.event === 'ready') readyResolve(line); } });
  const ready = await readyPromise;
  await request(ready.port, 'POST', '/act', { body: input });
  const inspectedPrivate = await request(ready.port, 'GET', '/inspect');
  check('task integrity inspection: opted field value is masked before reply and saved I artifact',
    inspectedPrivate.json.fields.find((field) => field.selector === '#memo')?.value === null
    && inspectedPrivate.json.fields.find((field) => field.selector === '#choice')?.selected.every((option) => option.value === null && option.text === null)
    && !inspectedPrivate.text.includes(sentinel) && !fs.readFileSync(inspectedPrivate.json.inspection, 'utf8').includes(sentinel));
  check('task integrity inspection: sensitive identifier echoes and opted shadow descendants stay private',
    !inspectedPrivate.text.includes('PASSWORD-PRIVATE-31984') && !inspectedPrivate.text.includes('SHADOW-PRIVATE-48152')
    && !fs.readFileSync(inspectedPrivate.json.inspection, 'utf8').includes('SHADOW-PRIVATE-48152'));
  await request(ready.port, 'POST', '/act', { body: tap('#lose') });
  await request(ready.port, 'POST', '/act', { body: tap('#copy') });
  await request(ready.port, 'POST', '/act', { body: { action: 'type', target: '#memo', text: 'another owned synthetic input', delay_ms: 0 } });
  await request(ready.port, 'POST', '/act', { body: tap('#normalize') });
  await request(ready.port, 'POST', '/act', { body: tap('#echo') });
  const normalizedInspection = await request(ready.port, 'GET', '/inspect');
  check('task integrity inspection: normalized value and ARIA echo masked, unrelated field preserved',
    !normalizedInspection.text.includes('ANOTHER OWNED SYNTHETIC INPUT')
    && !fs.readFileSync(normalizedInspection.json.inspection, 'utf8').includes('ANOTHER OWNED SYNTHETIC INPUT')
    && normalizedInspection.json.fields.find((field) => field.selector === '#memo')?.value === null
    && normalizedInspection.json.fields.find((field) => field.selector === '#unrelated')?.value === 'unrelated-owned-fixture');
  const finish = await request(ready.port, 'POST', '/finish', { body: { success: true } });
  const done = await proc;
  const interactive = loadRun(path.join(outDir, 'R-integrity-interactive')).run;
  check('task integrity interactive: shared checks override persona success, record loss and unvisited step', finish.json.exit_code === 3
    && done.code === 3 && interactive.status === 'completed' && interactive.success === false && interactive.persona_claimed_success === true
    && interactive.success_detail.criteria.some((c) => c.id === 'unvisited' && c.result === 'unevaluable'));
  check('task integrity interactive: changed authored source is an unevaluable execution mismatch',
    interactive.success_detail.criteria.some((c) => c.id === 'authored-input' && c.result === 'unevaluable' && c.reason === 'source_input_mismatch'));
  check('task integrity interactive: an authored private source protects changed input without a repeated flag',
    interactive.steps[3].action.text === '[redacted]' && !JSON.stringify(interactive).includes('another owned synthetic input'));
}

async function paintedStateTest(base, tmp) {
  const { pw, info } = loadPlaywright();
  const transport = await openBrowser(pw, info, { endpoint: undefined });
  const context = await transport.browser.newContext({ viewport: { width: 1100, height: 1000 }, deviceScaleFactor: 1 });
  try {
    const page = await context.newPage();
    const captures = [];
    for (const suffix of ['', '?unused-pale']) {
      await page.goto(`${base}/painted_state.html${suffix}`);
      const ex = await page.evaluate(extractSnapshot, { key: STATE_KEY, cap: 400, knownRoles: [...KNOWN_ROLES] });
      const png = await page.screenshot({ path: path.join(tmp, `painted${suffix ? '-pale' : ''}.png`) });
      captures.push({ ...ex, png_sha256: crypto.createHash('sha256').update(png).digest('hex') });
    }
    writeJson(path.join(tmp, 'painted-captures.json'), captures);
    check('paint: unused CSS foreground produces identical rendered pixels', captures[0].png_sha256 === captures[1].png_sha256);
    const item = (id) => captures[0].elements.find((e) => e.selector === `#${id}`);
    const parts = (id) => item(id)?.paint?.parts || [];
    check('paint: an empty switch has no foreground glyph channel', item('unused')?.paint && !parts('unused').some((p) => p.kind === 'text'));
    check('paint: changing unused foreground does not change measured parts', JSON.stringify(item('unused')?.paint?.parts)
      === JSON.stringify(captures[1].elements.find((e) => e.selector === '#unused')?.paint?.parts) && !!item('unused')?.paint);
    check('paint: pale track and thumb are measured separately from the dark label',
      parts('child-pale').some((p) => p.key === 'self/0:fill' && p.color === '#eeeeee' && p.background === '#ffffff')
      && parts('child-pale').some((p) => p.key === 'self/0/0:fill' && p.color === '#dddddd' && p.background === '#eeeeee'), parts('child-pale'));
    check('paint: SVG fill is rendered paint, not the parent foreground', parts('svg-red').some((p) => p.color === '#d32f2f' && p.kind === 'graphic')
      && parts('svg-green').some((p) => p.color === '#388e3c' && p.kind === 'graphic'), parts('svg-red'));
    check('paint: SVG stroke records its real colour and uniform adjacent background', parts('stroke-red').some((p) => p.key.endsWith(':stroke') && p.color === '#d32f2f' && p.background === '#ffffff'), parts('stroke-red'));
    check('paint: alpha fills are composited against their actual solid layer', parts('alpha').some((p) => p.color === '#808080' && p.background === '#ffffff')
      && parts('alpha').some((p) => p.color === '#bfbfbf' && p.background === '#808080'), parts('alpha'));
    check('paint: unsupported gradient and browser native paint remain explicit gaps', item('gradient')?.paint?.gaps.includes('unknown_background')
      && item('native')?.paint?.gaps.includes('native_appearance'));
    check('paint: caps are bounded and unverified', parts('capped').length <= 16 && item('capped')?.paint?.gaps.includes('part_cap'));
    check('paint: nested controls do not supply their paint to another owner', !parts('nested').some((p) => p.key.startsWith('self/0')));
    check('paint: decorative and transparent graphics supply no state channels', item('decorative')?.paint?.decorative === true
      && parts('transparent').length === 0);
    check('paint: covered and clipped state parts supply no red/green channel', ['covered-red', 'covered-green', 'clip-red', 'clip-green']
      .every((id) => parts(id).every((p) => !['#d32f2f', '#388e3c'].includes(p.color))));
    check('paint: a styled native text field retains its known CSS border', parts('native-styled').some((p) => p.key === 'self:border' && p.color === '#eeeeee')
      && item('native-styled')?.paint?.gaps.length === 0, item('native-styled'));
    check('paint: rendered child icon-font glyphs retain their own foreground', parts('glyph-dark').some((p) => p.kind === 'text' && p.color === '#111111')
      && parts('glyph-pale').some((p) => p.kind === 'text' && p.color === '#eeeeee'));
    await page.goto(`${base}/painted_state.html`);
    const beforeSvg = await page.locator('#svg-pale').screenshot();
    await page.locator('#svg-pale rect').evaluate((n) => { n.style.backgroundColor = '#111'; });
    const afterSvg = await page.locator('#svg-pale').screenshot();
    const exSvg = await page.evaluate(extractSnapshot, { key: STATE_KEY, cap: 400, knownRoles: [...KNOWN_ROLES] });
    const pale = exSvg.elements.find((e) => e.selector === '#svg-pale');
    check('paint: unused SVG shape CSS background is pixel and measurement invariant', beforeSvg.equals(afterSvg)
      && JSON.stringify(pale?.paint?.parts) === JSON.stringify(parts('svg-pale')), pale?.paint);
    writeJson(path.join(tmp, 'painted-svg-background.json'), exSvg);
    const beforeAttribute = await page.screenshot();
    const beforeGeometry = exSvg.elements.find((e) => e.selector === '#svg-green')?.paint;
    await page.locator('#svg-green rect').evaluate((n) => { n.setAttribute('d', 'UNUSED-PRIVATE-SHAPE'); });
    const afterAttribute = await page.screenshot();
    const exAttribute = await page.evaluate(extractSnapshot, { key: STATE_KEY, cap: 400, knownRoles: [...KNOWN_ROLES] });
    check('paint: unused SVG geometry attributes cannot invent a shape cue', beforeAttribute.equals(afterAttribute)
      && JSON.stringify(beforeGeometry) === JSON.stringify(exAttribute.elements.find((e) => e.selector === '#svg-green')?.paint));
    check('paint: unused SVG attributes never enter measured metadata', !JSON.stringify(exAttribute).includes('UNUSED-PRIVATE-SHAPE'));
    writeJson(path.join(tmp, 'painted-svg-attribute.json'), exAttribute);
    await page.locator('#svg-pale svg').evaluate((svg) => {
      svg.innerHTML = '<path fill="#eee" d="M2 2 H26 V26 H2 Z"/>';
    });
    const pathPaint = await page.evaluate(extractSnapshot, { key: STATE_KEY, cap: 400, knownRoles: [...KNOWN_ROLES] });
    check('paint: a bounded valid SVG path retains solid painted evidence', pathPaint.elements.find((e) => e.selector === '#svg-pale')?.paint?.parts.some((p) => p.shape?.startsWith('path|')));
    await page.locator('#svg-pale path').evaluate((n) => { n.setAttribute('d', 'M2 2 H26 V26 H2 Z L'); });
    const invalidPath = await page.evaluate(extractSnapshot, { key: STATE_KEY, cap: 400, knownRoles: [...KNOWN_ROLES] });
    check('paint: malformed SVG path geometry is unverified', invalidPath.elements.find((e) => e.selector === '#svg-pale')?.paint?.gaps.includes('unsupported_svg'));
  } finally {
    await transport.close([context]);
  }
}

async function gazeGeometryTest(tmp) {
  const { pw, info } = loadPlaywright();
  const transport = await openBrowser(pw, info, { endpoint: undefined });
  const context = await transport.browser.newContext({ viewport: { width: 360, height: 780 }, deviceScaleFactor: 1 });
  try {
    const page = await context.newPage();
    await page.setContent(`<!doctype html><style>
      body { margin:0 } button { box-sizing:border-box; width:180px; height:48px }
      #tiny { position:absolute; top:100px; left:10px; height:2px; overflow:hidden }
      #partial { position:absolute; top:200px; left:10px; height:24px; overflow:hidden }
      #clear { position:absolute; top:300px; left:10px }
      #outside { position:absolute; top:900px; left:10px }
      #scroll { position:absolute; top:400px; left:10px; height:24px; overflow:auto }
      #viewport { position:absolute; top:-24px; left:200px }
      </style><div id=tiny><button id=clipped data-ergo-role=primary>Continue</button></div>
      <div id=partial><button id=half>Half</button></div><button id=clear>Clear</button>
      <button id=outside>Offscreen</button><div id=scroll><button id=scrolled>Scroll</button></div>
      <button id=viewport>Viewport</button>`);
    const ex = await page.evaluate(extractSnapshot, { key: STATE_KEY, cap: 400, knownRoles: [...KNOWN_ROLES] });
    writeJson(path.join(tmp, 'gaze-geometry-capture.json'), ex);
    await page.screenshot({ path: path.join(tmp, 'gaze-geometry.png') });
    const item = (id) => ex.elements.find((e) => e.selector === `#${id}`);
    check('gaze geometry: tiny ancestor retains raw 48 px but visible height is 2 px',
      item('clipped')?.box.h === 48 && item('clipped')?.visible_box?.h === 2
      && item('clipped')?.visible_geometry === 'ancestor_clipped', item('clipped'));
    check('gaze geometry: partial ancestor and scroll clipping are explicit',
      ['half', 'scrolled'].every((id) => item(id)?.visible_box?.h === 24 && item(id)?.visible_geometry === 'ancestor_clipped'));
    check('gaze geometry: unclipped control keeps its exact rectangle',
      JSON.stringify(item('clear')?.visible_box) === JSON.stringify(item('clear')?.box)
      && item('clear')?.visible_geometry === 'measured');
    check('gaze geometry: offscreen control has no visible rectangle',
      item('outside')?.in_viewport === false && item('outside')?.visible_box === null && item('outside')?.visible_geometry === 'empty');
    check('gaze geometry: viewport intersection excludes hidden half',
      item('viewport')?.visible_box?.h === 24 && item('viewport')?.visible_box?.y === 0);
    const png = await page.screenshot();
    await page.evaluate(() => {
      const button = document.querySelector('#clear');
      for (let i = 0; i < 20; i++) { const wrapper = document.createElement('div'); button.parentNode.insertBefore(wrapper, button); wrapper.append(button); }
    });
    const wrapped = await page.evaluate(extractSnapshot, { key: STATE_KEY, cap: 400, knownRoles: [...KNOWN_ROLES] });
    writeJson(path.join(tmp, 'gaze-geometry-wrapped.json'), wrapped);
    const clear = wrapped.elements.find((e) => e.selector === '#clear');
    check('gaze geometry: plain wrappers preserve pixels and visible rectangle',
      png.equals(await page.screenshot()) && JSON.stringify(clear?.visible_box) === JSON.stringify(item('clear')?.visible_box));
    await page.evaluate(() => {
      const fixture = document.createElement('div');
      fixture.innerHTML = '<button id="rotate-transform" style="transform:rotate(45deg)">Rotation</button>'
        + '<button id="rotate-individual" style="rotate:45deg">Rotation</button>'
        + '<div style="rotate:45deg"><button id="rotate-ancestor">Rotation</button></div>';
      document.body.append(fixture);
    });
    const rotations = await page.evaluate(extractSnapshot, { key: STATE_KEY, cap: 400, knownRoles: [...KNOWN_ROLES] });
    writeJson(path.join(tmp, 'gaze-rotation-capture.json'), rotations);
    check('gaze geometry: equivalent rotations and rotated ancestors remain unsupported',
      ['#rotate-transform', '#rotate-individual', '#rotate-ancestor'].every((selector) => {
        const target = rotations.elements.find((e) => e.selector === selector);
        return target?.visible_geometry === 'unsupported' && target?.visible_box === null;
      }) && rotations.elements.find((e) => e.selector === '#clear')?.visible_geometry === 'measured');
  } finally {
    await context.close();
    await transport.close();
  }
}

async function typographyTest(base, tmp) {
  const { pw, info } = loadPlaywright();
  const transport = await openBrowser(pw, info, { endpoint: undefined });
  const context = await transport.browser.newContext({ viewport: { width: 1100, height: 1000 }, deviceScaleFactor: 1 });
  try {
    const page = await context.newPage();
    await page.goto(`${base}/typography.html`);
    await page.evaluate(() => document.fonts.ready);
    const capture = () => page.evaluate(extractSnapshot, { key: STATE_KEY, cap: 400, knownRoles: [...KNOWN_ROLES] });
    const ex = await capture();
    const item = (id) => ex.elements.find((e) => e.selector === `#${id}`);
    const metric = (id) => item(id)?.font_metrics;
    writeJson(path.join(tmp, 'typography-capture.json'), ex);
    await page.screenshot({ path: path.join(tmp, 'typography.png') });
    const nativeHeights = await page.evaluate(() => {
      const canvas = document.createElement('canvas').getContext('2d');
      return Object.fromEntries(['arial', 'courier', 'arial16', 'courier16', 'above'].map((id) => {
        const node = document.getElementById(id);
        const cs = getComputedStyle(node);
        canvas.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
        canvas.textBaseline = 'alphabetic';
        const metric = canvas.measureText(node.textContent);
        return [id, metric.actualBoundingBoxAscent + metric.actualBoundingBoxDescent];
      }));
    });
    check('typography: equal CSS em records native glyph heights including shared platform fallbacks',
      item('arial16')?.font_size_px === 16 && item('courier16')?.font_size_px === 16
      && metric('arial16')?.status === 'matched_font' && metric('courier16')?.status === 'matched_font'
      && ['arial16', 'courier16'].every((id) => nativeHeights[id] > 0 && metric(id).body_height_px === nativeHeights[id]));
    check('typography: both named font requests match actual platform Canvas bounds',
      item('arial')?.font_size_px === 22 && item('courier')?.font_size_px === 22
      && ['arial', 'courier'].every((id) => nativeHeights[id] > 0 && metric(id)?.body_height_px === nativeHeights[id]), [metric('arial'), metric('courier')]);
    check('typography: displayed body uses actual text, not a fixed Hg probe',
      metric('xonly')?.body_height_px === metric('xonly')?.probes?.x_height_px
      && metric('xonly').body_height_px < metric('xonly').probes.body_Hg_px);
    check('typography: actual small and large bodies straddle the 18px PC floor',
      metric('arial16')?.body_height_px < 18 && metric('above')?.body_height_px > 18);
    check('typography: mixed fonts and transformed or vertical text remain unavailable',
      ['mixed', 'transformed', 'zoomed', 'vertical', 'pseudo'].every((id) => metric(id)?.status === 'unavailable'
        && metric(id)?.body_height_px === null && metric(id)?.probes === null), ['mixed', 'transformed', 'zoomed', 'vertical', 'pseudo'].map(metric));
    check('typography: individual descendant transforms remain unavailable', ['child-scale', 'child-rotate', 'child-translate']
      .every((id) => metric(id)?.status === 'unavailable' && metric(id)?.body_height_px === null));
    check('typography: sensitive ancestors and subtrees contribute no numeric text fingerprint', ['sensitive', 'private-descendant', 'private-subtree']
      .every((id) => metric(id)?.status === 'unavailable' && metric(id)?.probes === null && metric(id)?.limitations.includes('private_control')));
    check('typography: private controls have no font text measurements or leaked values',
      ['input', 'textarea', 'select', 'private'].every((id) => metric(id)?.status === 'unavailable' && metric(id)?.limitations.includes('private_control'))
      && ['INPUT-PRIVATE-93485', 'TEXTAREA-PRIVATE-19458', 'SELECT-PRIVATE-94752'].every((value) => !JSON.stringify(ex).includes(value)));
    check('typography: raster and font fallback limits accompany matched Canvas data',
      metric('arial')?.method === 'canvas-textmetrics-v1' && metric('arial')?.unit === 'css_px'
      && metric('arial')?.limitations.join() === 'dom_ink_unmeasured,font_fallback_unverified');
    const secret = 'TYPOGRAPHY-OWNED-PRIVATE-54283';
    await page.locator('#echo').evaluate((n, value) => { n.textContent = value; }, secret);
    const { scenario: privateScenario } = normalizeScenario({ schema_version: 'ergo-scenario.v1', scenario_id: 'SC-typography-private',
      surface: { kind: 'web', url: `${base}/typography.html` }, task_goal_ko: '보호된 글자를 확인합니다', device_ids: ['desktop-1920'],
      targets: {}, steps: [{ action: 'type', target: '#input', text: secret, redact: true }], success: { url_contains: 'typography' } },
      { requireSteps: true });
    const session = new WebSession({ pw, pwInfo: info, runDir: tmp, runId: 'R-typography-private', options: {}, scenario: privateScenario });
    session.page = page;
    session.redactSelectors.add('#opted');
    const protectedCapture = session.redactRecord(await session.extract());
    writeJson(path.join(tmp, 'typography-protected-capture.json'), protectedCapture);
    check('typography: session redaction applies before font measurement including private echoes', ['#opted', '#echo']
      .every((selector) => protectedCapture.elements.find((e) => e.selector === selector)?.font_metrics?.status === 'unavailable')
      && !JSON.stringify(protectedCapture).includes(secret));
    await page.evaluate(() => { Object.defineProperty(document.fonts, 'check', { value: () => false }); });
    const unloaded = await capture();
    writeJson(path.join(tmp, 'typography-font-unavailable.json'), unloaded);
    check('typography: unavailable font produces no body metric', unloaded.elements.find((e) => e.selector === '#arial')?.font_metrics?.limitations.includes('font_not_loaded'));
    await page.goto(`${base}/typography.html`);
    await page.evaluate(() => { HTMLCanvasElement.prototype.getContext = () => null; });
    const noCanvas = await capture();
    writeJson(path.join(tmp, 'typography-canvas-unavailable.json'), noCanvas);
    check('typography: unavailable Canvas remains an explicit gap', noCanvas.elements.find((e) => e.selector === '#arial')?.font_metrics?.limitations.includes('canvas_unavailable'));
    const py = process.env.ERGOQA_PYTHON;
    if (py) {
      const r = spawnSync(py, ['-c', [
        'import json, sys',
        'from ergoqa import checks',
        'from ergoqa.devices import get_device',
        'from ergoqa.snapshot import validate_font_metrics',
        'capture = json.load(open(sys.argv[1]))',
        'items = capture["elements"]',
        'for item in items:',
        '    if "font_metrics" in item: assert not validate_font_metrics(item["font_metrics"]), item["selector"]',
        'device = get_device("desktop-1920")',
        'profile = {"profile_id": "EP-font-check", "attributes": {"age_band": "30s", "vision": {}}}',
        'def evaluate(elements):',
        '    snapshot = {"surface": {"kind": "web"}, "device": {"viewport_css": list(device.viewport_css)}, "elements": elements}',
        '    context = checks.Context(run={"run_id": "R-font-check"}, snapshot=snapshot, previous=None, step=None, profile=profile, device=device, scenario=None)',
        '    return [o for o in checks.check_text_size(context) if o.model and o.model.startswith("xag-101")]',
        'before = evaluate([{k: v for k, v in item.items() if k != "font_metrics"} for item in items])',
        'after = evaluate(items)',
        'by_id = {o.element_ids[0]: o for o in after}',
        'rows = {item["selector"]: by_id[item["id"]] for item in items if item["id"] in by_id}',
        'for item in items:',
        '    if item["font_metrics"]["status"] != "matched_font" or item["selector"] not in rows: continue',
        '    row = rows[item["selector"]]',
        '    assert row.measurement["value"] == item["font_metrics"]["body_height_px"]',
        '    assert row.passed == (row.measurement["value"] >= row.measurement["threshold"])',
        '    assert row.severity == (None if row.passed else "P2")',
        'assert not rows["#arial16"].passed and rows["#above"].passed',
        'for selector in ("#mixed", "#transformed", "#zoomed", "#vertical", "#pseudo", "#private"):',
        '    assert rows[selector].extra["verdict"] == "inconclusive" and rows[selector].severity is None',
        'assert all(o.extra["verdict"] == "inconclusive" for o in before)',
        'print(json.dumps({"before": [o.to_dict(i) for i, o in enumerate(before)], "after": [o.to_dict(i) for i, o in enumerate(after)]}, ensure_ascii=False, indent=2))',
      ].join('\n'), path.join(tmp, 'typography-capture.json')], { cwd: REPO, encoding: 'utf8', env: { ...process.env, PYTHONPATH: REPO } });
      fs.writeFileSync(path.join(tmp, 'typography-analysis.json'), r.stdout || '');
      check('typography: captured fonts drive typed XAG estimates and preserve unknown controls', r.status === 0, r.stderr || r.stdout);
    } else skip('typography: Python captured-font analysis', 'ERGOQA_PYTHON not configured');
  } finally {
    await context.close();
    await transport.close();
  }
}

async function main() {
  const keep = process.argv.includes('--keep');
  // --only a,b: run just these groups (scripted, actions, layers, focus, focus2, feedback, native-feedback,
  // read, reflow, reflow-copy, viewport, dialog, serve, tooling, exit, connect) while iterating on one part.
  const oi = process.argv.indexOf('--only');
  const only = oi > 0 && process.argv[oi + 1] ? new Set(process.argv[oi + 1].split(',')) : null;
  const want = (g) => !only || only.has(g);
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ergo-web-selftest-'));
  const server = await startFixtureServer();
  const base = `http://127.0.0.1:${server.address().port}`;
  console.log(`# fixture ${base}/selftest.html, outputs in ${tmp}`);
  try {
    writeJson(path.join(tmp, 'scenario.json'), scenario());
    writeJson(path.join(tmp, 'p-s24.json'), profile('EP-S24', 'galaxy-s24'));
    writeJson(path.join(tmp, 'p-desk.json'), profile('EP-DESK', 'desktop-1920'));
    deviceTableTest();
    if (want('connect')) await connectTest(base, tmp);
    if (want('integrity')) await taskIntegrityTest(base, tmp);
    if (want('painted')) await paintedStateTest(base, tmp);
    if (want('gaze')) await gazeGeometryTest(tmp);
    if (want('typography')) await typographyTest(base, tmp);

    const outDir = path.join(tmp, 'runs');
    let r = null;
    if (want('scripted')) {
    r = await runDriver(['run', '--scenario', path.join(tmp, 'scenario.json'), '--profile', path.join(tmp, 'p-s24.json'),
      '--out', outDir, '--run-id', 'R-s24', '--base', base,
      '--build-id', `fixture-source-sha256:${crypto.createHash('sha256').update(fs.readFileSync(path.join(HERE, 'fixtures', 'selftest.html'))).digest('hex')}`]);
    const fin = r.lines.find((l) => l.event === 'finished');
    if (check('run galaxy-s24: exit 0 with a finished line', r.code === 0 && fin && fin.status === 'completed' && fin.success === true, `${r.code} ${r.err}`)) {
      checkScripted('run galaxy-s24', path.join(outDir, 'R-s24'), {
        id: 'galaxy-s24', vw: 360, vh: 780, dpr: 3, orientation: 'portrait', input: 'touch',
      }, { flash: false });
      const recorded = loadRun(path.join(outDir, 'R-s24'));
      check('build identity: CLI value survives in run and every capture with operator provenance',
        recorded.run.surface.build_id.startsWith('fixture-source-sha256:') && recorded.run.surface.build_id_source === '--build-id'
        && recorded.run.surface.build_id_basis === 'operator_supplied'
        && [...recorded.snaps.values()].every((s) => s.surface.build_id === recorded.run.surface.build_id
          && s.surface.build_id_basis === 'operator_supplied'));
    }

    r = await runDriver(['run', '--scenario', path.join(tmp, 'scenario.json'), '--profile', path.join(tmp, 'p-desk.json'),
      '--out', outDir, '--run-id', 'R-desk', '--base', base, '--flash-sample-ms', '700']);
    const fin2 = r.lines.find((l) => l.event === 'finished');
    if (check('run desktop-1920 (--flash-sample-ms 700): exit 0 with a finished line', r.code === 0 && fin2 && fin2.success === true, `${r.code} ${r.err}`)) {
      checkScripted('run desktop-1920', path.join(outDir, 'R-desk'), {
        id: 'desktop-1920', vw: 1920, vh: 1080, dpr: 1, orientation: 'landscape', input: 'mouse',
      }, { flash: true });
    }
    }

    writeJson(path.join(tmp, 'actions.json'), actionsScenario());
    for (const [devArgs, dev] of [
      [['--device', 'iphone-15', '--orientation', 'landscape'], { id: 'iphone-15', vw: 852, vh: 393, dpr: 3, orientation: 'landscape', input: 'touch' }],
      [['--device', 'tv-55-1080'], { id: 'tv-55-1080', vw: 1920, vh: 1080, dpr: 1, orientation: 'landscape', input: 'mouse(fallback)' }],
    ]) {
      if (!want('actions')) break;
      const runId = `R-actions-${dev.id}`;
      r = await runDriver(['run', '--scenario', path.join(tmp, 'actions.json'), ...devArgs, '--out', outDir, '--run-id', runId,
        '--base', base, '--feedback-timeout-ms', '1000']);
      if (check(`actions ${dev.id}: exit 0`, r.code === 0, `${r.code} ${r.err} ${r.out}`)) {
        checkActions(`actions ${dev.id}`, path.join(outDir, runId), dev);
      }
    }

    if (want('layers') || want('focus')) await layersTest(base, tmp); // focus reads the layers run (touch: no probe)
    if (want('focus')) await focusTest(base, tmp);
    if (want('focus2')) await focusProbeTest(base, tmp);
    if (want('feedback') && !want('focus2')) await feedbackReversalTest(base, tmp);
    if (want('native-feedback')) await nativeFeedbackTest(base, tmp);
    if (want('read')) await readPageTest(base, tmp);
    if (want('reflow')) await reflowTest(base, tmp);
    if (want('reflow-copy')) await reflowCopyTest(base, tmp);
    if (want('adaptation')) await adaptationTest(base, tmp);
    if (want('viewport')) await viewportTest(base, tmp);
    if (want('dialog')) await dialogTest(base, tmp);
    if (want('serve')) await serveTest(base, tmp);
    if (want('tooling')) await toolingTest(base, tmp);
    if (want('exit')) await exitCodeTests(base, tmp);
  } finally {
    server.close();
  }
  console.log(`# ${passes} passed, ${failures} failed`);
  if (!keep && failures === 0) fs.rmSync(tmp, { recursive: true, force: true });
  else console.log(`# outputs kept in ${tmp}`);
  process.exit(failures ? 1 : 0);
}

main().catch((err) => {
  console.log(`FAIL selftest crashed -- ${err && err.stack ? err.stack : err}`);
  process.exit(1);
});
