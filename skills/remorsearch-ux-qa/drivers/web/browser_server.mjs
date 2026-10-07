#!/usr/bin/env node
// Start outside a command sandbox; the drivers connect through loopback only.
import crypto from 'node:crypto';
import { loadPlaywright } from './playwright_loader.mjs';

const USAGE = 'usage: node browser_server.mjs [--port 0..65535]\nStarts a headless Chromium Playwright server on 127.0.0.1 until SIGINT or SIGTERM.';

async function main() {
  const args = process.argv.slice(2);
  if (args.length === 1 && ['--help', '-h'].includes(args[0])) {
    process.stdout.write(`${USAGE}\n`);
    return 0;
  }
  let port = 0;
  if (args.length) {
    if (args.length !== 2 || args[0] !== '--port' || !/^\d+$/.test(args[1])
      || Number(args[1]) > 65535) {
      process.stderr.write(`browser_server: invalid arguments\n${USAGE}\n`);
      return 2;
    }
    port = Number(args[1]);
  }
  const { pw } = loadPlaywright();
  const server = await pw.chromium.launchServer({
    headless: true, host: '127.0.0.1', port, wsPath: crypto.randomBytes(24).toString('hex'),
  });
  await new Promise((resolve) => {
    let closing = false;
    const stop = async () => {
      if (closing) return;
      closing = true;
      await server.close().catch(() => {});
      resolve();
    };
    process.once('SIGINT', stop);
    process.once('SIGTERM', stop);
    server.once('close', resolve);
    process.stdout.write(`export REMORSEARCH_BROWSER_WS=${server.wsEndpoint()}\n`);
  });
  return 0;
}

main().then((code) => { process.exitCode = code; }, (err) => {
  process.stderr.write(`browser_server: ${err.message}\n`);
  process.exitCode = 4;
});
