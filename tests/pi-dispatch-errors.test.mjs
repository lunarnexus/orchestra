import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, copyFileSync, mkdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createJiti } from 'jiti';

// Feedback #2: a pre-ack dispatch failure must surface the ACTUAL cause in the
// orch_dispatch tool result's isError text, not a fixed "see stderr". Covers
// both a pre-ack nonzero exit (child stderr cause) and a launch error (ENOENT,
// which errors without ever closing). Controlled fake subprocess only: no real
// Python core, no live Pi sessions, no models, no global install.
const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const temp = mkdtempSync(join(tmpdir(), 'orchestra-dispatch-errors-'));
const sessionDir = join(temp, 'pi-sessions');
mkdirSync(sessionDir);
mkdirSync(join(temp, 'state'), { recursive: true });
mkdirSync(join(temp, 'logs'), { recursive: true });

// Cause string the child writes last so it survives a bounded tail (the real
// DB traceback ends with the error), plus filler that must be dropped.
const CAUSE = 'sqlite3.OperationalError: unable to open database file';
const FILLER = 'frame filler dropped from head';
// Bound the tool-result text well under the ~116KB the unbuffered stderr would
// produce, proving only a tail is retained.
const STDERR_BOUND = 6000;

// --- controlled fake python3 (no real Python core) -------------------------
// `dispatch` -> writes a huge stderr traceback ending in the real cause, exits
// 1 before any ack. Other core calls (initial-mode, status) stay benign.
const fillerLines = 4000;
writeFileSync(join(temp, 'python3'), [
  `#!${process.execPath}`,
  "const args = process.argv.slice(2);",
  "if (args.includes('tool-info')) {",
  `  process.stdout.write(JSON.stringify(${JSON.stringify({dispatch:{label:"Orchestra Dispatch",description:"Submit.",params:{goal:"goal.",additionalContext:"ctx.",role:"role.",taskLabel:"label."}},status:{label:"Orchestra Status",description:"Manage.",params:{action:"action.",limit:"limit.",runId:"runId."}},command:{description:"/orch"},actions:["status","history","stop","help","doctor","roles"]})}));`,
  "  process.exit(0);",
  "}",
  "if (args.includes('dispatch')) {",
  "  process.stderr.write('Traceback (most recent call last):\\n');",
  `  for (let i = 0; i < ${fillerLines}; i += 1) process.stderr.write(${JSON.stringify(FILLER + ' ')} + i + '\\n');`,
  `  process.stderr.write(${JSON.stringify(CAUSE + '\n')});`,
  "  process.exit(1);",
  "}",
  "if (args.includes('initial-mode')) process.stdout.write('on\\n');",
  "process.exit(0);",
].join('\n'), { mode: 0o755 });

const fakePiPath = join(temp, 'fake-pi');
writeFileSync(fakePiPath, `#!${process.execPath}
process.stdin.resume();
`, { mode: 0o755 });

// --- minimal real config (mode/initial commands only) ----------------------
const configDir = join(temp, 'config');
mkdirSync(configDir);
copyFileSync(join(repoRoot, 'prompts.yaml'), join(configDir, 'prompts.yaml'));
writeFileSync(join(configDir, 'config.yaml'), `state_dir: ${join(temp, 'state')}
log_dir: ${join(temp, 'logs')}
default_timeout: 300
soft_timeout: 240
turn_limit: 60
concurrency:
  global: 6
  per_session: 3
retention_days: 90
default_mode: 'on'
`);
writeFileSync(join(configDir, 'harnesses.yaml'), `pi:
  harness: pi
  command: ["${fakePiPath}"]
`);
writeFileSync(join(configDir, 'agent-catalog.yaml'), `default_role: builder
model_limits:
  "m1":
    concurrency: 3
roles:
  builder:
    enabled: manual
    harness_config: pi
    model: "m1"
    env: {}
    skills: []
    dispatch_hint: Build the requested change.
    auto_verify: false
`);

process.env.PATH = `${temp}:${process.env.PATH}`;
process.env.ORCHESTRA_CONFIG = configDir;
process.env.PYTHONPATH = join(repoRoot, 'src');
process.env.PI_CODING_AGENT_SESSION_DIR = sessionDir;

const text = (result) => (result.content ?? []).map((part) => part.text ?? '').join('\n');

function makeContext(sessionId) {
  return {
    hasUI: true,
    sessionManager: {
      getSessionId: () => sessionId,
      buildContextEntries: () => [],
      getBranch: () => [],
    },
    ui: { theme: { fg: (_c, t) => t, bold: (t) => t }, setWidget() {}, notify() {} },
  };
}

try {
  const jiti = createJiti(import.meta.url);
  const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');
  const tools = new Map();
  await activate({
    on() {},
    registerTool: (tool) => tools.set(tool.name, tool),
    registerCommand() {},
    registerEntryRenderer() {},
    appendEntry() {},
    getActiveTools: () => [],
    setActiveTools() {},
    sendUserMessage() {},
  });
  const dispatch = tools.get('orch_dispatch');
  assert.ok(dispatch, 'orch_dispatch tool must be registered');

  // --- A: pre-ack nonzero exit surfaces the real cause, bounded -----------
  {
    const ctx = makeContext('E1');
    const result = await dispatch.execute('e1', { goal: 'will fail', role: 'builder' }, undefined, undefined, ctx);
    assert.equal(result.isError, true, `pre-ack dispatch must be isError: ${JSON.stringify(result)}`);
    const shown = text(result);
    assert.match(shown, /unable to open database file/, 'the real child stderr cause must appear in the tool result');
    assert.doesNotMatch(shown, /head 0\b/, 'the retained stderr must be a bounded tail (head filler dropped)');
    assert.ok(shown.length < STDERR_BOUND, `tool result text must stay bounded (got ${shown.length} chars)`);
    assert.ok(!/^\s*orchestra dispatch failed \(see stderr\.\)\s*$/.test(shown), 'must not return the bare fixed see-stderr text');
  }

  // --- B: launch error (ENOENT) surfaces cause and settles (no hang) ------
  {
    const emptyBin = join(temp, 'empty-bin');
    mkdirSync(emptyBin);
    const savedPath = process.env.PATH;
    process.env.PATH = emptyBin; // no python3 on PATH -> spawn errors ENOENT
    try {
      const guard = new Promise((_resolve, reject) =>
        setTimeout(() => reject(new Error('HANG: dispatch did not settle on launch error')), 5000));
      const ctx = makeContext('E2');
      const result = await Promise.race([
        dispatch.execute('e2', { goal: 'cannot launch', role: 'builder' }, undefined, undefined, ctx),
        guard,
      ]);
      assert.equal(result.isError, true, `launch error must be isError: ${JSON.stringify(result)}`);
      const shown = text(result);
      assert.match(shown, /failed to launch/i, 'the launch error must be reported as the cause');
      assert.match(shown, /ENOENT|python3/i, 'the actual launch cause (ENOENT/python3) must be present');
      void spawnSync; // keep import referenced without invoking here
    } finally {
      process.env.PATH = savedPath;
    }
  }

  console.log('Pi dispatch error propagation passed');
} finally {
  rmSync(temp, { recursive: true, force: true });
}
