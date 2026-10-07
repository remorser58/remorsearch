#!/usr/bin/env node
// One JSON request to the bundled driver's loopback serve endpoint.
import http from 'node:http';

import { EXIT, UsageError, isPlainObject } from './util.mjs';

const USAGE = `usage:
  node drivers/web/drive_client.mjs --port N <request> [json]

requests:
  act JSON       send one action (e.g. '{"action":"tap","target":"#submit"}')
  inspect        read form values, validation associations, focus and DOM reading order
  observe        capture the current screen without acting
  screenshot     same as observe; prints JSON containing the PNG path
  snapshot       same as observe
  health         read session status
  note JSON      record a persona note (confusion is required)
  finish [JSON]  finish the run (e.g. '{"success":true}')

exit codes: 0 successful request, 2 usage error, 3 action failed or run unsuccessful,
            4 connection or HTTP error
inspect requires an a11y or screenshot+a11y operator channel.`;

const REQUESTS = {
  health: ['GET', '/health'],
  observe: ['GET', '/snapshot'],
  screenshot: ['GET', '/snapshot'],
  snapshot: ['GET', '/snapshot'],
  inspect: ['GET', '/inspect'],
  act: ['POST', '/act'],
  note: ['POST', '/note'],
  finish: ['POST', '/finish'],
};

function parseArgs(argv) {
  let port;
  const positional = [];
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--port' || arg.startsWith('--port=')) {
      if (port !== undefined) throw new UsageError('--port given twice');
      port = arg === '--port' ? argv[++i] : arg.slice(7);
      if (!/^\d+$/.test(port || '') || Number(port) < 1 || Number(port) > 65535) throw new UsageError('--port must be an integer within 1..65535');
    } else if (arg.startsWith('--')) throw new UsageError(`unknown option ${arg}`);
    else positional.push(arg);
  }
  if (port === undefined) throw new UsageError('--port is required');
  const [name, raw] = positional;
  if (!Object.hasOwn(REQUESTS, name) || positional.length > 2) throw new UsageError('provide one request: act, inspect, observe, screenshot, snapshot, health, note or finish');
  const [method, pathname] = REQUESTS[name];
  if (method === 'GET' && raw !== undefined) throw new UsageError(`${name} takes no JSON body`);
  if (['act', 'note'].includes(name) && raw === undefined) throw new UsageError(`${name} needs a JSON object`);
  let body = null;
  if (method === 'POST') {
    let obj;
    try { obj = raw === undefined ? {} : JSON.parse(raw); }
    catch { throw new UsageError('request body must be valid JSON'); }
    if (!isPlainObject(obj)) throw new UsageError('request body must be a JSON object');
    body = JSON.stringify(obj);
    if (Buffer.byteLength(body) > 64 * 1024) throw new UsageError('request body exceeds 65536 bytes');
  }
  return { port: Number(port), method, pathname, body };
}

function sendRequest({ port, method, pathname, body }) {
  return new Promise((resolve, reject) => {
    const req = http.request({
      hostname: '127.0.0.1', port, method, path: pathname,
      headers: body === null ? {} : { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
    }, (res) => {
      let text = '';
      res.setEncoding('utf8');
      res.on('data', (chunk) => { text += chunk; });
      res.on('error', reject);
      res.on('end', () => {
        let json;
        try { json = JSON.parse(text); }
        catch { reject(new Error(`HTTP ${res.statusCode}: response is not JSON`)); return; }
        if (!isPlainObject(json)) { reject(new Error(`HTTP ${res.statusCode}: response is not a JSON object`)); return; }
        resolve({ status: res.statusCode, json });
      });
    });
    // Finish can include the existing focus walks and a 40-second reflow pass.
    const timer = setTimeout(() => req.destroy(new Error('request timed out after 120 seconds')), 120000);
    req.on('close', () => clearTimeout(timer));
    req.on('error', reject);
    req.end(body);
  });
}

async function main(argv) {
  if (argv.length === 1 && argv[0] === '--help') {
    process.stdout.write(`${USAGE}\n`);
    return EXIT.OK;
  }
  const { status, json } = await sendRequest(parseArgs(argv));
  process.stdout.write(`${JSON.stringify(json)}\n`);
  if (status < 200 || status >= 300) return EXIT.DRIVER;
  if (['error', 'no_target'].includes(json.result)) return EXIT.UNSUCCESSFUL;
  if (Number.isInteger(json.exit_code)) return json.exit_code;
  return EXIT.OK;
}

main(process.argv.slice(2)).then(
  (code) => { process.exitCode = code; },
  (err) => {
    const message = err instanceof UsageError ? err.message : `cannot complete request: ${err.message}`;
    process.stdout.write(`${JSON.stringify({ error: message })}\n`);
    process.exitCode = err instanceof UsageError ? EXIT.USAGE : EXIT.DRIVER;
  },
);
