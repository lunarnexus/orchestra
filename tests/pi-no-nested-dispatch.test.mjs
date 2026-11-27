import assert from 'node:assert/strict';
import { existsSync, mkdirSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createJiti } from 'jiti';

// No-nested-dispatch regression (adapter layer). A marked Orchestra child
// (subagent) MUST NOT register Orchestra tools, MUST NOT expose /orch to
// re-enable them, and MUST NOT spawn the core session/coordinator. The marker
// is the reserved ORCHESTRA_DISPATCH_BUDGET; a marked, positive, or malformed
// value disables, and only an unmarked/zero parent activates. Controlled
// subprocess boundary only — no real Python core, no models.
const temp = mkdtempSync(join(tmpdir(), 'orchestra-nonested-'));

const TOOL_INFO = {
  dispatch: { label: 'D', description: 'Dispatch.', params: { goal: 'g', additionalContext: 'a', role: 'r', taskLabel: 't' } },
  status: { label: 'S', description: 'Status.', params: { action: 'act', limit: 'l', runId: 'rid' } },
  command: { description: '/orch ...' },
  actions: ['status', 'history', 'stop', 'help', 'doctor'],
};

// python3 stub: records EVERY invocation so we can prove the adapter spawned
// nothing (not even the short tool-info read) when the child is marked.
const spawnLog = join(temp, 'spawn.log');
const validBin = join(temp, 'valid-bin');
mkdirSync(validBin, { recursive: true });
writeFileSync(
  join(validBin, 'python3'),
  `#!${process.execPath}
const fs = require('node:fs');
fs.appendFileSync(${JSON.stringify(spawnLog)}, process.argv.slice(2).join(' ') + '\\n');
const args = process.argv.slice(2);
if (args.includes('tool-info')) process.stdout.write(${JSON.stringify(JSON.stringify(TOOL_INFO))});
process.exit(0);
`,
  { mode: 0o755 },
);
process.env.PATH = validBin;
process.env.ORCHESTRA_CONFIG = temp;

function fakePi(rec) {
  return {
    on: (name, handler) => rec.handlers.set(name, handler),
    registerTool: (t) => rec.tools.set(t.name, t),
    registerCommand: (name, def) => rec.commands.set(name, def),
    registerEntryRenderer() {},
    appendEntry() {},
    getActiveTools: () => [],
    setActiveTools() {},
    sendUserMessage() {},
  };
}

function newRec() {
  return { tools: new Map(), commands: new Map(), handlers: new Map() };
}

try {
  const jiti = createJiti(import.meta.url);
  const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');

  // --- Positive control: unmarked parent registers tools + command ---------
  {
    delete process.env.ORCHESTRA_DISPATCH_BUDGET;
    rmSync(spawnLog, { force: true });
    const rec = newRec();
    await activate(fakePi(rec));
    assert.ok(rec.tools.has('orch_dispatch'), 'unmarked parent registers orch_dispatch');
    assert.ok(rec.tools.has('orch_status'), 'unmarked parent registers orch_status');
    assert.ok(rec.commands.has('orch'), 'unmarked parent registers /orch');
    assert.ok(rec.handlers.has('session_start'), 'unmarked parent wires session_start (core spawn path)');
  }

  // --- Every marked / non-parent value disables the whole adapter ----------
  for (const marker of ['1', '2', '99', 'banana']) {
    process.env.ORCHESTRA_DISPATCH_BUDGET = marker;
    rmSync(spawnLog, { force: true });
    const rec = newRec();
    await activate(fakePi(rec));
    assert.equal(rec.tools.size, 0, `${marker}: no Orchestra tools registered in a marked child`);
    assert.equal(rec.commands.size, 0, `${marker}: no /orch command to re-enable in a marked child`);
    assert.ok(!rec.handlers.has('session_start'), `${marker}: no session_start core-spawn handler in a marked child`);
    // Decisive: the adapter spawned nothing at all (not even the tool-info read),
    // so no needless Orchestra core/coordinator can start in the child.
    assert.ok(!existsSync(spawnLog), `${marker}: no core/tool-info subprocess spawned in a marked child`);
  }
  delete process.env.ORCHESTRA_DISPATCH_BUDGET;

  console.log('Pi no-nested-dispatch adapter guard passed');
} finally {
  rmSync(temp, { recursive: true, force: true });
}
