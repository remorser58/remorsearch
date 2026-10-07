// Small shared helpers: errors/exit codes, atomic writes, hashing, clocks.

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

export const EXIT = Object.freeze({ OK: 0, UNSUCCESSFUL: 3, USAGE: 2, DRIVER: 4 });

/** Bad CLI arguments or input files (exit 2). */
export class UsageError extends Error {}

/** Browser/driver failure (exit 4). */
export class DriverFailure extends Error {}

/** Invalid action object (serve: HTTP 400; run: exit 2). */
export class ActionError extends Error {}

export const MAX_JSON_BYTES = 5 * 1024 * 1024;

export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, Math.max(0, ms)));
}

/** Wall-clock epoch in ms with sub-ms resolution (monotonic after start). */
export function epochNow() {
  return performance.timeOrigin + performance.now();
}

export function isoNow(date = new Date()) {
  return date.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

export function round1(n) {
  return n == null || !Number.isFinite(n) ? null : Math.round(n * 10) / 10;
}

export function sha256(buf) {
  return crypto.createHash('sha256').update(buf).digest('hex');
}

/** Write file contents atomically: temp file in the same dir, fsync, rename. */
export function writeFileAtomic(file, data, mode = 0o644) {
  const dir = path.dirname(file);
  const tmp = path.join(dir, `.${path.basename(file)}.${process.pid}.${crypto.randomBytes(4).toString('hex')}.tmp`);
  const fd = fs.openSync(tmp, 'wx', mode);
  try {
    fs.writeSync(fd, data);
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  fs.renameSync(tmp, file);
}

export function writeJsonAtomic(file, obj, mode = 0o644) {
  writeFileAtomic(file, `${JSON.stringify(obj, null, 2)}\n`, mode);
}

export function readJsonFile(file, what) {
  let stat;
  try {
    stat = fs.statSync(file);
  } catch {
    throw new UsageError(`${what}: cannot read ${file}`);
  }
  if (!stat.isFile()) throw new UsageError(`${what}: ${file} is not a regular file`);
  if (stat.size > MAX_JSON_BYTES) throw new UsageError(`${what}: ${file} exceeds ${MAX_JSON_BYTES} bytes`);
  const text = fs.readFileSync(file, 'utf8');
  try {
    return JSON.parse(text);
  } catch (err) {
    throw new UsageError(`${what}: ${file} is not valid JSON (${err.message})`);
  }
}

export function isPlainObject(v) {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

/** Read the IHDR width/height of a PNG buffer. */
export function pngSize(buf) {
  if (buf.length < 24 || buf.readUInt32BE(0) !== 0x89504e47) throw new Error('not a PNG');
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
}

export function truncate(s, n) {
  const str = String(s ?? '');
  return str.length > n ? `${str.slice(0, n - 1)}…` : str;
}
