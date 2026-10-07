// Load the playwright package: normal module resolution, NODE_PATH entries, then the
// cloud container's /opt/node22 install as a last resort (shared by the drivers).

import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';

import { DriverFailure } from './util.mjs';

export function loadPlaywright() {
  const req = createRequire(import.meta.url);
  const attempts = [];
  const tryLoad = (spec, how) => {
    try {
      const resolved = req.resolve(spec);
      return { mod: req(resolved), path: resolved, how };
    } catch (err) {
      attempts.push(`${how}: ${String(err.message).split('\n')[0]}`);
      return null;
    }
  };
  let r = tryLoad('playwright', 'module resolution');
  for (const dir of (process.env.NODE_PATH || '').split(path.delimiter).filter(Boolean)) {
    r = r || tryLoad(path.join(dir, 'playwright'), `NODE_PATH ${dir}`);
  }
  r = r || tryLoad('/opt/node22/lib/node_modules/playwright', '/opt/node22 fallback');
  if (!r) throw new DriverFailure(`cannot load the playwright package (${attempts.join('; ')})`);
  let version = null;
  for (let dir = path.dirname(r.path); dir !== path.dirname(dir); dir = path.dirname(dir)) {
    const pkg = path.join(dir, 'package.json');
    if (fs.existsSync(pkg)) {
      try {
        const meta = JSON.parse(fs.readFileSync(pkg, 'utf8'));
        if (meta.name === 'playwright') {
          version = meta.version;
          break;
        }
      } catch { /* keep looking */ }
    }
  }
  return { pw: r.mod, info: { version, path: path.dirname(r.path), resolved_by: r.how } };
}
