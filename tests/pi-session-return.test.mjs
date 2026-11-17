import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, copyFileSync, mkdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createJiti } from 'jiti';

// Exercise the real extension and the real Orchestra 2 core CLI end to end:
// real queue database, real state files, real dispatch subprocesses, real
// automatic verifier follow-up. Controlled boundaries only: the host-side
// `python3` is a pass-through stub (env injection + one delayed dispatch for
// the unacked-spawn race) and the `pi` RPC binary is a scripted fake. No live
// Pi sessions, global installs, or models are involved.
const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const temp = mkdtempSync(join(tmpdir(), 'orchestra-session-return-'));
const sessionDir = join(temp, 'pi-sessions');
mkdirSync(sessionDir);
mkdirSync(join(temp, 'state'), { recursive: true });
mkdirSync(join(temp, 'logs'), { recursive: true });

// Resolve the real interpreter BEFORE the stub shadows `python3` on PATH.
const realPython = spawnSync('python3', ['-c', 'import sys;print(sys.executable)'], { encoding: 'utf8' }).stdout.trim();
assert.ok(realPython, 'a real python3 interpreter is required');

// --- controlled boundaries -------------------------------------------------
// Pass-through python3: forwards to the real orchestra module. Delays the
// launch of any dispatch whose goal contains "beta" so its acknowledgement is
// still pending while the other run of the same session completes.
writeFileSync(join(temp, 'python3'), `#!${process.execPath}
const { spawn } = require('node:child_process');
const args = process.argv.slice(2);
const goalIndex = args.indexOf('--goal');
const goal = goalIndex >= 0 ? (args[goalIndex + 1] || '') : '';
const delay = args[0] === 'dispatch' && goal.includes('beta') ? 200 : 0;
const launch = () => {
  const child = spawn(${JSON.stringify(realPython)}, [...args], { stdio: 'inherit', env: process.env });
  child.on('error', (e) => { process.stderr.write(String(e)); process.exit(1); });
  child.on('exit', (c) => process.exit(c ?? 1));
};
if (delay > 0) setTimeout(launch, delay); else launch();
`, { mode: 0o755 });

// Fake pi RPC binary: accepts the prompt, settles after an optional delay,
// and answers get_last_assistant_text from the scenario file. A scenario
// entry with `fail: true` rejects the prompt (hard failure path).
const fakePiPath = join(temp, 'fake-pi');
writeFileSync(fakePiPath, `#!${process.execPath}
const fs = require('node:fs');
const readline = require('node:readline');
const scenario = JSON.parse(fs.readFileSync(process.env.FAKE_PI_SCENARIO, 'utf8'));
function entryFor(prompt) {
  return scenario.find((e) => e.match !== '*' && prompt.includes(e.match)) || scenario.find((e) => e.match === '*');
}
function send(obj) { process.stdout.write(JSON.stringify(obj) + '\\n'); }
let lastPrompt = '';
readline.createInterface({ input: process.stdin }).on('line', (line) => {
  let msg; try { msg = JSON.parse(line); } catch { return; }
  if (msg.type === 'prompt') {
    lastPrompt = String(msg.message ?? '');
    const entry = entryFor(lastPrompt);
    setTimeout(() => {
      if (entry && entry.fail) send({ id: 'prompt-1', type: 'response', success: false, error: 'fake failure' });
      else send({ id: 'prompt-1', type: 'response', success: true });
      send({ type: 'agent_settled', aborted: false });
    }, (entry && entry.delayMs) || 0);
  } else if (msg.type === 'get_last_assistant_text') {
    const entry = entryFor(lastPrompt);
    send({ id: msg.id, type: 'response', command: 'get_last_assistant_text', data: { text: (entry && entry.fail) ? '' : ((entry && entry.text) || 'unscripted answer') } });
  }
});
`, { mode: 0o755 });

// --- real Orchestra 2 config (real prompts, real catalog semantics) -------
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
    auto_verify: true
  verifier:
    enabled: auto
    harness_config: pi
    model: "m1"
    env: {}
    skills: []
    auto_verify: false
  plain:
    enabled: manual
    harness_config: pi
    model: "m1"
    env: {}
    skills: []
    auto_verify: false
`);

process.env.PATH = `${temp}:${process.env.PATH}`;
process.env.ORCHESTRA_CONFIG = configDir;
process.env.PYTHONPATH = join(repoRoot, 'src');
process.env.PI_CODING_AGENT_SESSION_DIR = sessionDir;
process.env.FAKE_PI_SCENARIO = join(temp, 'scenario.json');

function setScenario(entries) {
  writeFileSync(join(temp, 'scenario.json'), JSON.stringify(entries));
}

async function poll(label, fn, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (fn()) return;
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${label}`);
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
}

function realStatus(sessionId) {
  const result = spawnSync(join(temp, 'python3'), ['-m', 'orchestra', 'status', '--session-id', sessionId, '--mode', 'on'], { encoding: 'utf8' });
  if (result.status !== 0) throw new Error(`status failed: ${result.stderr}`);
  return JSON.parse(result.stdout).data.session_jobs;
}

function steerTextsFor(steers) { return () => steers.join('\n'); }

try {
  const jiti = createJiti(import.meta.url);
  const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');
  const hooks = new Map();
  const tools = new Map();
  const steers = [];
  const notifications = [];
  activate({
    on: (name, handler) => hooks.set(name, handler),
    registerTool: (t) => tools.set(t.name, t),
    registerCommand() {}, registerEntryRenderer() {},
    getActiveTools: () => [...tools.keys()],
    setActiveTools() {},
    sendUserMessage: (message) => steers.push(String(message)),
  });
  assert.ok(tools.has('orch_dispatch'), 'orch_dispatch tool must be registered');

  function makeContext(sessionId) {
    return {
      hasUI: true,
      sessionManager: {
        getSessionId: () => sessionId,
        // Fresh sessions: parent-context capture falls back to the request.
        buildContextEntries: () => [],
        getBranch: () => [],
      },
      ui: {
        theme: { fg: (_c, t) => t, bold: (t) => t },
        setWidget() {},
        notify: (msg) => notifications.push(msg),
      },
    };
  }

  await hooks.get('session_start')({}, makeContext('pi:S1'));

  // --- journey 1: one run with an automatic verifier follow-up ----------
  setScenario([
    { match: 'one task', text: 'one builder answer' },
    { match: 'two task', text: 'two builder answer' },
    { match: '*', text: 'verifier: confirmed' },
  ]);
  const ack1 = await tools.get('orch_dispatch').execute('c1', { goal: 'one task', role: 'builder' }, undefined, undefined, makeContext('pi:S1'));
  assert.equal(ack1.isError, false, `dispatch 1 ack failed: ${JSON.stringify(ack1)}`);
  const ackText1 = ack1.content[0].text;
  assert.match(ackText1, /builder/i, 'ack must name the role');
  assert.match(ackText1, /do not poll/i, 'ack must tell the orchestrator not to poll');

  await poll('consolidated S1 return', () => steers.length > 0);
  assert.equal(steers.length, 1, 'exactly one return prompt after all session jobs (builder + verifier) finish');
  const first = steers[0];
  assert.match(first, /one builder answer/, 'actual child response is delivered');
  assert.match(first, /verifier: confirmed/, 'follow-up verifier answer is delivered in the same prompt');
  assert.match(first, /do not duplicate the work/i, 'one applicable hint is included');
  assert.doesNotMatch(first, /Jobs:/, 'redundant Jobs heading is removed');
  assert.doesNotMatch(first, /covers one run|unlisted runs/i, 'internal scope-limitation prose is removed');
  assert.doesNotMatch(first, /finished \(/, 'duplicate per-run summary line is removed');
  assert.equal(realStatus('pi:S1').length, 0, 'no session jobs remain running after the return');

  // --- journey 2: a later run must not repeat earlier delivered results --
  const steerCountBefore = steers.length;
  const ack2 = await tools.get('orch_dispatch').execute('c2', { goal: 'two task', role: 'builder' }, undefined, undefined, makeContext('pi:S1'));
  assert.equal(ack2.isError, false);
  await poll('second S1 return', () => steers.length > steerCountBefore);
  assert.equal(steers.length, steerCountBefore + 1, 'one return for the second run');
  assert.match(steers[steers.length - 1], /two builder answer/);
  assert.doesNotMatch(steers[steers.length - 1], /one builder answer/, 'earlier delivered results are not repeated');


  // --- journey 3: overlapping runs, one completing early ----------------
  const ctx2 = makeContext('pi:S2');
  setScenario([
    { match: 'alpha task', text: 'alpha actual answer' },
    { match: 'beta task', text: 'beta actual answer', delayMs: 800 },
    { match: '*', text: 'verifier: confirmed' },
  ]);
  const s2Baseline = steers.length;
  const ackA = await tools.get('orch_dispatch').execute('c3', { goal: 'alpha task', role: 'plain' }, undefined, undefined, ctx2);
  assert.equal(ackA.isError, false, 'alpha ack failed');
  // The stub python3 delays beta's *launch*, so alpha can fully finish while
  // beta's dispatch subprocess has not even printed its acknowledgement.
  const ackB = await tools.get('orch_dispatch').execute('c4', { goal: 'beta task', role: 'plain' }, undefined, undefined, ctx2);
  assert.equal(ackB.isError, false, 'beta ack failed');
  // Alpha is terminal (no running session jobs) while beta is still pending.
  await poll('alpha run terminal', () => realStatus('pi:S2').every((job) => job.status !== 'running'));
  // Give the extension time to process alpha's return line.
  await new Promise((resolve) => setTimeout(resolve, 500));
  assert.equal(steers.length, s2Baseline, 'no early wake while a live pending dispatch exists');
  assert.doesNotMatch(steers.join('\n'), /alpha actual answer|beta actual answer/, 'neither answer delivered before all runs finish');

  await poll('consolidated S2 return', () => steers.some((s) => s.includes('alpha actual answer')));
  const s2Steer = steers.find((s) => s.includes('alpha actual answer'));
  assert.ok(s2Steer, 'one wake after both runs finish');
  assert.match(s2Steer, /beta actual answer/, 'both actual child answers in one prompt');
  assert.equal(steers.filter((s) => s === s2Steer).length, 1, 'single wake, not repeated');
  assert.doesNotMatch(s2Steer, /Jobs:/);
  assert.match(s2Steer, /All jobs succeeded|do not duplicate the work/i);

  // --- journey 4: other sessions are isolated; failures stay visible ----
  const ctx3 = makeContext('pi:S3');
  setScenario([
    { match: 'gamma task', fail: true },
    { match: '*', text: 'verifier: confirmed' },
  ]);
  const s3Baseline = steers.length;
  const ack3 = await tools.get('orch_dispatch').execute('c5', { goal: 'gamma task', role: 'plain' }, undefined, undefined, ctx3);
  assert.equal(ack3.isError, false, 'gamma ack failed');
  await poll('S3 failure return', () => steers.some((s) => s.includes('failed')));
  const s3Steer = steers.find((s) => s.includes('failed'));
  assert.match(s3Steer, /failed/, 'failure stays visible');
  assert.match(s3Steer, /prompt rejected: fake failure/, 'actual failure detail from the child is preserved');
  assert.match(s3Steer, /harness or execution error/i, 'failure hint is included');
  assert.doesNotMatch(s3Steer, /one builder answer|alpha actual answer/, 'other sessions are excluded');
  assert.equal(steers.length, s3Baseline + 1, 'failure delivers once');

  console.log('Pi session-return consolidation passed');
} finally {
  rmSync(temp, { recursive: true, force: true });
}
