import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createJiti } from 'jiti';

// Exercise the real extension callback. Only its Python/host boundaries are
// controlled; no live Pi sessions, global settings, or models are involved.
const temp = mkdtempSync(join(tmpdir(), 'orchestra-footer-'));
try {
  const dataPath = join(temp, 'status.json');
  writeFileSync(join(temp, 'python3'), `#!${process.execPath}\n` +
    `const fs = require('node:fs');\n` +
    `console.log(process.argv.includes('initial-mode') ? 'on' : fs.readFileSync(${JSON.stringify(dataPath)}, 'utf8'));\n`, { mode: 0o755 });
  process.env.PATH = `${temp}:${process.env.PATH}`;
  process.env.ORCHESTRA_CONFIG = temp;
  const jiti = createJiti(import.meta.url);
  const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');
  const hooks = new Map();
  let tools = [];
  let footer;
  activate({
    on: (name, handler) => hooks.set(name, handler),
    registerTool() {}, registerCommand() {}, registerEntryRenderer() {},
    getActiveTools: () => tools,
    setActiveTools: value => { tools = value; },
  });
  const ctx = {
    hasUI: true,
    sessionManager: { getSessionId: () => 'isolated-footer-test' },
    ui: {
      theme: { fg: (_color, text) => text, bold: text => text },
      setWidget: (_name, value) => { footer = value.join('\n'); },
    },
  };
  async function refresh(jobs) {
    writeFileSync(dataPath, JSON.stringify({ data: { session_jobs: jobs } }));
    await hooks.get('session_start')({}, ctx);
    return footer;
  }
  let text = await refresh([
    { role: 'builder', status: 'running' },
    { role: 'verifier', status: 'pending' },
  ]);
  assert.match(text, /builder/i);
  assert.doesNotMatch(text, /verifier/i, 'pending verifier must not appear active');
  text = await refresh([{ role: 'verifier', status: 'running' }]);
  assert.match(text, /verifier/i, 'verifier appears after it starts');
  text = await refresh([{ role: 'builder', status: 'pending' }]);
  assert.doesNotMatch(text, /builder/i, 'pending work is not running work');
  console.log('Pi footer running-only regression passed');
} finally {
  rmSync(temp, { recursive: true, force: true });
}
