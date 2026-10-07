#!/usr/bin/env node
// ergoqa live web driver (docs/ergonomic-swarm-spec.md section 10).
//
//   node drivers/web/ergo_drive.mjs run   --scenario sc.json --profile p.json --out runs/ [--run-id R-x]
//   node drivers/web/ergo_drive.mjs serve --scenario sc.json --profile p.json --agent-json agent.json --out runs/ --port 9477
//
// Exit codes: 0 completed and success; 3 run written but not successful
// (success false/unknown, or a scripted step failed); 2 usage/input error;
// 4 driver/browser failure or blocked run.

import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

import { CATALOG, DeviceError, deviceFromJson, resolveDevice } from './devices.mjs';
import { WebSession, ensureRunDir } from './session.mjs';
import { startServer } from './serve.mjs';
import { normalizeBuildId, normalizeProfile, normalizeScenario } from './validate.mjs';
import { loadPlaywright } from './playwright_loader.mjs';
import { DriverFailure, EXIT, UsageError, readJsonFile } from './util.mjs';

const USAGE = `usage:
  node drivers/web/ergo_drive.mjs devices
  node drivers/web/ergo_drive.mjs init --url URL --device ID [--task TEXT] --out SC.json
  node drivers/web/ergo_drive.mjs run   --scenario SC.json (--profile P.json | --device ID) --out RUNS_DIR [options]
  node drivers/web/ergo_drive.mjs serve --scenario SC.json (--profile P.json | --device ID) --agent-json AGENT.json --out RUNS_DIR [--port 9477] [options]

options:
  --run-id ID              run directory name (default R-<scenario>-<profile>-<utc>-<rand>)
  --base URL               replaces "{BASE}" in scenario urls, e.g. http://127.0.0.1:8765
  --build-id ID            operator-supplied product commit/version/deploy or source identity
  --device ID              override the profile's attributes.device_id (${[...CATALOG.keys()].join(', ')})
  --device-json FILE       device object (ergoqa Device.to_dict) instead of the built-in table
  --orientation O          override the profile's orientation (portrait|landscape)
  --flash-sample-ms N      after each step, sample viewport luminance for N ms (0 = off)
  --feedback-timeout-ms N  max wait for first feedback after an input (default 3000)
  --settle-ms N            wait after feedback before the after-snapshot (default 300)
  --allow-origin ORIGIN    extra origin the page may load from (repeatable; default: scenario origin only)
  --continue-on-error      scripted run: keep going after a failed step
  --no-auto-scroll         do not scroll targets into view (step fails with no_target instead)
  --focus-walk / --no-focus-walk  Tab through the page at load (separate context) and at the end,
                           recording focus indicators and covered focus (default: on for mouse/keyboard devices)
  --no-reflow                   skip the 320 CSS px reflow pass (static copies of the screens, scripts off)
  --no-visual-feedback     only DOM mutations/navigation count as feedback
  --timeout-s N            scripted run time limit (default 900)
  --idle-timeout-s N       serve: finish as blocked after N s without requests (default 900)
  --agent TEXT             who operates the run (free text), stored in run.json agent
  --agent-json FILE        operator record {model_family, input_channel, model, persona_arm, seed, ...};
                           required by serve (input_channel "screenshot" keeps DOM data out of the replies)
  --locale L / --timezone Z  browser locale and timezone (default ko-KR, Asia/Seoul)
  --headed                 show the browser window (needs a display)

exit codes: 0 completed+success, 3 not successful, 2 usage/input error, 4 driver failure/blocked`;

const INPUT_CHANNELS = new Set(['screenshot', 'a11y', 'screenshot+a11y']);
const PERSONA_ARMS = new Set(['neutral', 'cognition', 'full', 'full+view']);

/** Machine-readable operator record (LAT-02): corroboration is computed from model family and channel. */
function readAgentJson(file) {
  const a = readJsonFile(file, 'agent JSON');
  if (!a || typeof a !== 'object' || Array.isArray(a)) throw new UsageError('--agent-json must contain an object');
  if (typeof a.model_family !== 'string' || !a.model_family) throw new UsageError('--agent-json: model_family is required (e.g. "claude")');
  if (!INPUT_CHANNELS.has(a.input_channel)) throw new UsageError(`--agent-json: input_channel must be one of ${[...INPUT_CHANNELS].join(', ')}`);
  if (a.persona_arm !== undefined && !PERSONA_ARMS.has(a.persona_arm)) throw new UsageError(`--agent-json: persona_arm must be one of ${[...PERSONA_ARMS].join(', ')}`);
  const keep = ['description', 'model', 'model_family', 'model_version', 'effort', 'temperature', 'seed', 'input_channel', 'persona_arm', 'prompt_sha256', 'max_steps'];
  const out = {};
  for (const k of keep) if (a[k] !== undefined) out[k] = typeof a[k] === 'string' ? a[k].slice(0, 200) : a[k];
  return out;
}

const VALUE_FLAGS = new Set([
  'scenario', 'profile', 'out', 'run-id', 'base', 'build-id', 'port', 'flash-sample-ms', 'device', 'device-json', 'orientation',
  'allow-origin', 'feedback-timeout-ms', 'settle-ms', 'timeout-s', 'idle-timeout-s', 'locale', 'timezone', 'agent', 'agent-json', 'url', 'task',
]);
const BOOL_FLAGS = new Set(['headed', 'continue-on-error', 'no-auto-scroll', 'no-visual-feedback', 'focus-walk', 'no-focus-walk', 'no-reflow', 'help']);

function parseArgs(argv) {
  const out = { command: null, flags: {}, allowOrigins: [] };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (!arg.startsWith('--')) {
      if (out.command) throw new UsageError(`unexpected argument ${JSON.stringify(arg)}`);
      out.command = arg;
      continue;
    }
    let name = arg.slice(2);
    let value;
    const eq = name.indexOf('=');
    if (eq >= 0) {
      value = name.slice(eq + 1);
      name = name.slice(0, eq);
    }
    if (BOOL_FLAGS.has(name)) {
      if (value !== undefined) throw new UsageError(`--${name} takes no value`);
      out.flags[name] = true;
    } else if (VALUE_FLAGS.has(name)) {
      if (value === undefined) {
        value = argv[++i];
        if (value === undefined) throw new UsageError(`--${name} needs a value`);
      }
      if (name === 'allow-origin') out.allowOrigins.push(value);
      else if (name in out.flags) throw new UsageError(`--${name} given twice`);
      else out.flags[name] = value;
    } else {
      throw new UsageError(`unknown option --${name}`);
    }
  }
  return out;
}

function intFlag(flags, name, def, min, max) {
  if (flags[name] === undefined) return def;
  const v = Number(flags[name]);
  if (!Number.isInteger(v) || v < min || v > max) throw new UsageError(`--${name} must be an integer within ${min}..${max}`);
  return v;
}


function slug(s, n) {
  return String(s).replace(/[^A-Za-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, n) || 'x';
}

function defaultRunId(scenarioId, profileId) {
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z');
  return `R-${slug(scenarioId, 32)}-${slug(profileId, 24)}-${stamp}-${crypto.randomBytes(2).toString('hex')}`;
}

function emit(obj) {
  process.stdout.write(`${JSON.stringify(obj)}\n`);
}

function checkCommandFlags(args, allowed) {
  for (const flag of Object.keys(args.flags)) {
    if (!allowed.includes(flag)) throw new UsageError(`--${flag} is not supported by ${args.command}`);
  }
  if (args.allowOrigins.length) throw new UsageError(`--allow-origin is not supported by ${args.command}`);
}

function initScenario(args) {
  checkCommandFlags(args, ['url', 'device', 'task', 'out', 'build-id']);
  const f = args.flags;
  for (const flag of ['url', 'device', 'out']) if (!f[flag]) throw new UsageError(`--${flag} is required by init`);
  if (!CATALOG.has(f.device)) throw new UsageError(`unknown device ${JSON.stringify(f.device)}; use the devices command to list IDs`);
  if (f.task !== undefined && !f.task.trim()) throw new UsageError('--task must be non-empty');
  const scenario = {
    schema_version: 'ergo-scenario.v1',
    scenario_id: `SC-${slug(path.basename(f.out, path.extname(f.out)), 64)}`,
    surface: { kind: 'web', url: f.url, ...(f['build-id'] !== undefined ? { build_id: normalizeBuildId(f['build-id'], '--build-id') } : {}) },
    task_goal_ko: f.task || 'Complete the task and check that entered values are preserved.',
    device_ids: [f.device],
    steps: [],
    success: null,
  };
  normalizeScenario(scenario, { requireSteps: true });
  const out = path.resolve(f.out);
  fs.mkdirSync(path.dirname(out), { recursive: true });
  try {
    fs.writeFileSync(out, `${JSON.stringify(scenario, null, 2)}\n`, { flag: 'wx' });
  } catch (err) {
    throw new UsageError(err.code === 'EEXIST' ? `scenario ${out} already exists; choose a new --out path` : `cannot write scenario ${out}: ${err.message}`);
  }
  emit({ scenario: out, device_id: f.device });
}

async function main(argv) {
  const args = parseArgs(argv);
  if (args.flags.help || !args.command) {
    process.stdout.write(`${USAGE}\n`);
    return args.flags.help ? EXIT.OK : EXIT.USAGE;
  }
  if (args.command === 'devices') {
    checkCommandFlags(args, []);
    process.stdout.write('id                     viewport (CSS px)  dpr    input\n');
    for (const d of CATALOG.values()) process.stdout.write(`${d.id.padEnd(22)} ${`${d.viewport_css[0]}x${d.viewport_css[1]}`.padEnd(18)} ${String(d.dpr).padEnd(6)} ${d.input}\n`);
    return EXIT.OK;
  }
  if (args.command === 'init') {
    initScenario(args);
    return EXIT.OK;
  }
  if (args.command !== 'run' && args.command !== 'serve') throw new UsageError(`unknown command ${JSON.stringify(args.command)} (use devices, init, run or serve)`);
  const f = args.flags;
  for (const flag of ['url', 'task']) if (f[flag] !== undefined) throw new UsageError(`--${flag} is supported only by init`);
  if (!f.scenario) throw new UsageError('--scenario is required');
  if (!f.out) throw new UsageError('--out is required');
  if (!f.profile && !f.device && !f['device-json']) throw new UsageError('--profile or --device is required');
  // Every interactive session names its operator: the channel decides what the replies
  // may carry, and corroboration counts operators by model family and channel.
  if (args.command === 'serve' && !f['agent-json']) {
    throw new UsageError('serve needs --agent-json FILE (operator record with model_family and input_channel; "screenshot" keeps DOM data out of the replies)');
  }
  let base = null;
  if (f.base) {
    let u;
    try {
      u = new URL(f.base);
    } catch {
      throw new UsageError(`--base is not a URL: ${f.base}`);
    }
    if (u.protocol !== 'http:' && u.protocol !== 'https:') throw new UsageError('--base must be an http(s) URL');
    base = f.base.replace(/\/+$/, '');
  }
  const allowOrigins = args.allowOrigins.map((o) => {
    let u;
    try {
      u = new URL(o);
    } catch {
      throw new UsageError(`--allow-origin is not a URL: ${o}`);
    }
    if (u.protocol !== 'http:' && u.protocol !== 'https:') throw new UsageError('--allow-origin must be an http(s) origin');
    return u.origin;
  });
  const options = {
    flashSampleMs: intFlag(f, 'flash-sample-ms', 0, 0, 10000),
    feedbackTimeoutMs: intFlag(f, 'feedback-timeout-ms', 3000, 0, 10000),
    settleMs: intFlag(f, 'settle-ms', 300, 0, 10000),
    autoScroll: !f['no-auto-scroll'],
    // Keyboard focus walk (default: pointer/keyboard devices only).
    focusWalk: f['focus-walk'] ? true : f['no-focus-walk'] ? false : null,
    reflow: f['no-reflow'] ? false : null,
    visualFeedback: !f['no-visual-feedback'],
    headed: !!f.headed,
    allowOrigins,
    locale: f.locale || 'ko-KR',
    timezoneId: f.timezone || 'Asia/Seoul',
    // Who operated the run (e.g. "claude-opus-5-5 max, screenshot channel"); recorded so
    // agent-layer results can be attributed and compared across models.
    agent: typeof f.agent === 'string' ? f.agent.slice(0, 200) : null,
    agentInfo: f['agent-json'] ? readAgentJson(f['agent-json']) : null,
  };
  if (!/^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$/.test(options.locale)) throw new UsageError('--locale must look like ko-KR');
  if (!/^[A-Za-z_]+(\/[A-Za-z0-9_+-]+)*$/.test(options.timezoneId)) throw new UsageError('--timezone must be an IANA zone like Asia/Seoul');
  const timeoutS = intFlag(f, 'timeout-s', 900, 1, 86400);
  const idleTimeoutS = intFlag(f, 'idle-timeout-s', 900, 1, 86400);
  const port = intFlag(f, 'port', 9477, 0, 65535);
  if (f.orientation && !['portrait', 'landscape'].includes(f.orientation)) throw new UsageError('--orientation must be portrait or landscape');

  const { scenario, warnings } = normalizeScenario(readJsonFile(f.scenario, 'scenario'), { base, requireSteps: args.command === 'run' });
  const buildId = f['build-id'] === undefined ? scenario.build_id : normalizeBuildId(f['build-id'], '--build-id');
  if (scenario.build_id && buildId !== scenario.build_id) throw new UsageError('--build-id conflicts with scenario.surface.build_id');
  options.buildId = buildId;
  options.buildIdSource = buildId ? (f['build-id'] === undefined ? 'scenario.surface.build_id' : '--build-id') : null;
  const profile = f.profile ? normalizeProfile(readJsonFile(f.profile, 'profile')) : null;
  let device = null;
  if (f['device-json']) {
    try {
      device = deviceFromJson(readJsonFile(f['device-json'], 'device JSON'));
    } catch (err) {
      if (err instanceof DeviceError) throw new UsageError(err.message);
      throw err;
    }
  }
  const deviceId = device ? device.id : (f.device || (profile && profile.device_id));
  if (!deviceId) throw new UsageError('no device: the profile has no attributes.device_id and no --device was given');
  const orientation = f.orientation || (profile && profile.orientation) || null;
  let early;
  try {
    early = resolveDevice({ id: deviceId, device, orientation });
  } catch (err) {
    if (err instanceof DeviceError) throw new UsageError(err.message);
    throw err;
  }
  if (scenario.device_ids.length && !scenario.device_ids.includes(deviceId)) {
    warnings.push(`device ${deviceId} is not listed in scenario.device_ids (${scenario.device_ids.join(', ')})`);
  }
  const profileId = profile ? profile.profile_id : 'no-profile';
  const runId = f['run-id'] || defaultRunId(scenario.scenario_id, profileId);
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(runId)) throw new UsageError('--run-id must match [A-Za-z0-9][A-Za-z0-9._-]{0,127}');
  const { pw, info } = loadPlaywright();
  const runDir = path.resolve(f.out, runId);
  const dirProblem = ensureRunDir(runDir);
  if (dirProblem) throw new UsageError(dirProblem);

  if (info.version !== '1.56.1') warnings.push(`playwright ${info.version} found; this driver was tested with 1.56.1`);
  const session = new WebSession({
    pw,
    pwInfo: info,
    scenario,
    deviceRequest: { id: deviceId, device, orientation, fallbackDevice: early.snapshotDevice },
    profileId,
    runId,
    runDir,
    mode: args.command === 'run' ? 'scripted' : 'interactive',
    options,
    warnings,
  });

  const onSignal = (sig) => {
    session.finish({ reason: `interrupted by ${sig}` })
      .then((r) => emit({ event: 'finished', run: r.runPath, status: r.status, success: r.success, exit_code: EXIT.DRIVER }))
      .catch(() => {})
      .finally(() => process.exit(EXIT.DRIVER));
  };
  process.once('SIGINT', onSignal);
  process.once('SIGTERM', onSignal);

  try {
    await session.start();
  } catch (err) {
    const r = await session.finish({ reason: err.message });
    emit({ event: 'finished', run: r.runPath, status: r.status, success: r.success, exit_code: EXIT.DRIVER, error: err.message });
    return EXIT.DRIVER;
  }

  if (args.command === 'run') {
    const deadline = Date.now() + timeoutS * 1000;
    // Hard stop if a single step hangs past the limit: still write a blocked run.json.
    const watchdog = setTimeout(() => {
      session.finish({ reason: `run timeout (${timeoutS}s) while a step was running` })
        .then((r) => emit({ event: 'finished', run: r.runPath, status: r.status, success: r.success, exit_code: EXIT.DRIVER }))
        .catch(() => {})
        .finally(() => process.exit(EXIT.DRIVER));
    }, timeoutS * 1000 + 30000);
    watchdog.unref();
    let failure = null;
    if (!session.blockReasons.length) {
      for (const action of scenario.steps) {
        if (Date.now() > deadline) {
          failure = `run timeout (${timeoutS}s) before step ${session.steps.length + 1}`;
          break;
        }
        try {
          const { step } = await session.act(action);
          if (step.result !== 'ok' && !f['continue-on-error']) break;
        } catch (err) {
          failure = err.message;
          break;
        }
        if (session.crashed) break;
      }
    }
    const r = await session.finish(failure ? { reason: failure } : {});
    emit({
      event: 'finished', run: r.runPath, run_dir: runDir, status: r.status, success: r.success,
      steps: r.run.steps.length, snapshots: r.run.snapshots.length, exit_code: r.exitCode,
    });
    return r.exitCode;
  }

  if (session.blockReasons.length) {
    const r = await session.finish({});
    emit({ event: 'finished', run: r.runPath, status: r.status, success: r.success, exit_code: r.exitCode, error: session.blockReasons.join('; ') });
    return r.exitCode;
  }
  return new Promise((resolve) => {
    startServer({
      session,
      port,
      idleTimeoutS,
      onReady: (actualPort) => emit({
        event: 'ready',
        url: `http://127.0.0.1:${actualPort}`,
        port: actualPort,
        run_id: runId,
        run_dir: runDir,
        // A screenshot-channel operator gets no snapshot JSON path (serve.mjs DOM_REPLY_KEYS).
        ...(session.opts?.agentInfo?.input_channel === 'screenshot' ? {} : { snapshot: path.join(runDir, `${session.lastSnapshotId}.json`) }),
        png: path.join(runDir, `${session.lastSnapshotId}.png`),
        endpoints: ['GET /health', 'GET /snapshot', 'GET /inspect', 'POST /act', 'POST /note', 'POST /finish'],
      }),
      onDone: (r, err) => {
        if (err) {
          process.stderr.write(`ergo_drive: HTTP server error: ${err.message}\n`);
          session.finish({ reason: `HTTP server error: ${err.message}` }).finally(() => resolve(EXIT.DRIVER));
          return;
        }
        emit({ event: 'finished', run: r.runPath, status: r.status, success: r.success, exit_code: r.exitCode });
        resolve(r.exitCode);
      },
    });
  });
}

main(process.argv.slice(2)).then(
  (code) => process.exit(code),
  (err) => {
    if (err instanceof UsageError) {
      process.stderr.write(`ergo_drive: ${err.message}\n`);
      process.exit(EXIT.USAGE);
    }
    process.stderr.write(`ergo_drive: ${err instanceof DriverFailure ? '' : 'unexpected error: '}${err && err.stack ? err.stack : err}\n`);
    process.exit(EXIT.DRIVER);
  },
);
