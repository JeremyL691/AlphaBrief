#!/usr/bin/env node
'use strict';

// Deterministic AlphaBrief Electron packaging contract (M17-W03).
//
// Builds a reproducible local package from the frozen source files
// into dist/, writes a versioned SHA-256 checksum manifest, and
// refuses to embed secrets, account data, databases, logs, or
// observation artifacts. A second build from the same frozen source
// produces identical normalized contents and an identical manifest.
//
// Usage:
//   node scripts/package.js [--out <dir>]   build the package
//   node scripts/package.js check           verify an existing build

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const VERSION = require('../package.json').version || '0.0.0';

// Frozen source files that form the package (never node_modules).
const SOURCE_FILES = [
  'main.js',
  'preload.js',
  'error-overlay.html',
  'package.json',
];

// Content that must never be embedded (AC-M17-W03-01).
const FORBIDDEN_PATTERNS = [
  /BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY/,
  /api[_-]?key\s*[:=]\s*\S+/i,
  /Bearer\s+\S+/i,
  /account[_-]?id\s*[:=]\s*\S+/i,
  /account-\d{8,}/i,
  /\.duckdb\b/,
  /observation[_-]?manifest/i,
  /\.ndjson\b/,
];

function normalize(content, name) {
  // package.json is written in a stable minimal form so the build is
  // independent of devDependency drift.
  if (name === 'package.json') {
    const parsed = JSON.parse(content);
    return JSON.stringify(
      {
        name: parsed.name,
        version: parsed.version,
        private: true,
        main: parsed.main,
      },
      null,
      2,
    ) + '\n';
  }
  return content;
}

function sha256(text) {
  return crypto.createHash('sha256').update(text, 'utf8').digest('hex');
}

function scanForbidden(text) {
  const hits = [];
  for (const pattern of FORBIDDEN_PATTERNS) {
    if (pattern.test(text)) {
      hits.push(pattern.toString());
    }
  }
  return hits;
}

function buildPackage(outDir) {
  const target = path.resolve(outDir, `alphabrief-desktop-${VERSION}`);
  fs.mkdirSync(target, { recursive: true });
  const manifest = {};
  for (const name of SOURCE_FILES) {
    const raw = fs.readFileSync(path.join(ROOT, name), 'utf8');
    const content = normalize(raw, name);
    const hits = scanForbidden(content);
    if (hits.length > 0) {
      throw new Error(
        `refusing to package ${name}: forbidden content ${hits.join(', ')}`,
      );
    }
    fs.writeFileSync(path.join(target, name), content, 'utf8');
    manifest[name] = sha256(content);
  }
  const manifestPath = path.join(target, 'CHECKSUMS.sha256');
  fs.writeFileSync(
    manifestPath,
    Object.keys(manifest)
      .sort()
      .map((name) => `${manifest[name]}  ${name}`)
      .join('\n') + '\n',
    'utf8',
  );
  return { target, manifest };
}

function verifyPackage(target) {
  const manifestPath = path.join(target, 'CHECKSUMS.sha256');
  if (!fs.existsSync(manifestPath)) {
    throw new Error(`missing checksum manifest in ${target}`);
  }
  const lines = fs.readFileSync(manifestPath, 'utf8').trim().split('\n');
  for (const line of lines) {
    const [expected, name] = line.split(/\s+/, 2);
    const actual = sha256(fs.readFileSync(path.join(target, name), 'utf8'));
    if (actual !== expected) {
      throw new Error(`checksum mismatch for ${name}`);
    }
  }
  return true;
}

function main() {
  const args = process.argv.slice(2);
  if (args[0] === 'selftest') {
    // Unit-level proof that the scanner refuses forbidden content.
    const bad = 'token = super-secret-value\naccount-12345678\n';
    const hits = scanForbidden(bad);
    if (hits.length === 0) {
      console.error('selftest failed: forbidden content not detected');
      process.exit(1);
    }
    const clean = 'const HEALTH_URL = `http://localhost:8765/health`;';
    if (scanForbidden(clean).length > 0) {
      console.error('selftest failed: clean content flagged');
      process.exit(1);
    }
    console.log('selftest passed');
    process.exit(0);
  }
  if (args[0] === 'check') {
    const dist = path.join(ROOT, 'dist');
    if (!fs.existsSync(dist)) {
      console.error('no build present; run `npm run package` first');
      process.exit(1);
    }
    const targets = fs
      .readdirSync(dist)
      .filter((name) => name.startsWith('alphabrief-desktop-'));
    if (targets.length === 0) {
      console.error('no packaged artifact found in dist/');
      process.exit(1);
    }
    for (const name of targets) {
      verifyPackage(path.join(dist, name));
    }
    console.log(`verified ${targets.length} packaged artifact(s)`);
    process.exit(0);
  }

  const outIndex = args.indexOf('--out');
  const outDir = outIndex >= 0 ? args[outIndex + 1] : path.join(ROOT, 'dist');
  const { target } = buildPackage(outDir);
  console.log(`packaged ${path.relative(ROOT, target)}`);
  process.exit(0);
}

main();
