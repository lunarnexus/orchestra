import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createJiti } from 'jiti';
import { createLiveCoreHost, makeContext, text } from './helpers/pi-live-core-host.mjs';

// Admission/gating regression, against the REAL Python core session runtime.
// The obsolete version asserted a transport-protocol contract by feeding a
// scripted python3 stub that emitted raw malformed "ack"/"return" lines. That
// raw-ack protocol is no longer authoritative: the real core owns admission,
// readiness, and delivery timing. (Transport-protocol malformed coverage lives
// in the separate adapter-contract test.) True pre-queue launch failures are
// already proven by the Python test_session_execution and are not re-created
// here as a duplicate Node fixture.
//
// What this proves with the real runtime: a concurrent run B whose OPT-IN native
// parent-context capture is held open keeps core's dispatch admission open, so
// the session never becomes ready and NO report is delivered even after a plain
// run A of the SAME session reaches a persisted terminal end-state. Releasing
// B as a native capture rejection (the real core admission-failure path) yields
// an error reply on B, and then A's report is delivered automatically — exactly
// once, with no extra prompt or status trigger.

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..');

// `ctx` opts into parent_context so B drives a REAL native get_parent_context
// capture; `plain` does not, so A is unaffected by the hold.
const CATALOG = `default_role: builder
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
    dispatch_hint: Build the requested change and return the concrete edits and checks.
    auto_verify: true
  plain:
    enabled: manual
    harness_config: pi
    model: "m1"
    env: {}
    skills: []
    dispatch_hint: Do the assigned work and return a concise result.
    auto_verify: false
  ctx:
    enabled: manual
    harness_config: pi
    model: "m1"
    env: {}
    skills: []
    parent_context: true
    dispatch_hint: Do the assigned work and return a concise result.
    auto_verify: false
`;

const host = createLiveCoreHost({ repoRoot, catalog: CATALOG });

// Read A's terminal state directly from SQLite so the test never issues a
// status call that could itself advance or trigger delivery.
function jobStatus(jobId) {
  const out = spawnSync(host.realPython, [
    '-c',
    'import sqlite3,sys; r=sqlite3.connect(sys.argv[1]).execute("select status from jobs where job_id=?", (sys.argv[2],)).fetchone(); print(r[0] if r else "")',
    host.queueDb, jobId,
  ], { encoding: 'utf8' });
  return out.status === 0 ? out.stdout.trim() : '';
}

const TERMINAL = new Set(['succeeded', 'done', 'failed', 'skipped']);

const hooks = new Map();
const tools = new Map();

try {
  const jiti = createJiti(import.meta.url);
  const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');
  const steers = [];
  await activate({
    on: (name, handler) => hooks.set(name, handler),
    registerTool: (t) => tools.set(t.name, t),
    registerCommand() {}, registerEntryRenderer() {},
    getActiveTools: () => [...tools.keys()], setActiveTools() {},
    sendUserMessage: (message) => steers.push(String(message)),
  });
  assert.ok(tools.has('orch_dispatch'), 'orch_dispatch must be registered');

  host.setScenario([
    { match: 'ALPHA', text: 'alpha actual answer' },
    { match: 'BLOCKER', text: 'blocker must never run' },
    { match: '*', text: 'generic answer' },
  ]);

  const SA = 'pi:SA';
  host.trackSession(SA);
  const ctxA = makeContext('SA');
  await hooks.get('session_start')({}, ctxA);

  // Hold the native capture boundary BEFORE starting B so core never receives
  // the host's get_parent_context answer and B's admission stays open.
  host.holdNativeContext(true);

  // Start B (opt-in native context). Its dispatch request is answered only once
  // the capture is resolved, so the promise stays in flight while held.
  const bPromise = tools.get('orch_dispatch').execute('call-b', { goal: 'BLOCKER blocker task', role: 'ctx' }, undefined, undefined, ctxA);

  // B is genuinely in admission: core emitted a get_parent_context capture the
  // host never answered. This is the real core "open admission" condition.
  await host.poll('core opened native context capture for B', () => host.heldNativeContextIds().length > 0, 30000);

  // A plain same-session run proceeds normally and finishes.
  const ackA = await tools.get('orch_dispatch').execute('call-a', { goal: 'ALPHA alpha task', role: 'plain' }, undefined, undefined, ctxA);
  assert.equal(ackA.isError, false, `A dispatch must ack: ${JSON.stringify(ackA)}`);
  const runA = host.trackRun(text(ackA));
  assert.ok(runA, 'A run id parsed from real core ack');

  // A reaches a persisted terminal end-state while B's admission is still open,
  // yet NOTHING is delivered: the open admission keeps the session non-ready.
  await host.poll('A run terminal in durable queue', () => TERMINAL.has(jobStatus(`${runA}:1`)), 30000);
  await new Promise((r) => setTimeout(r, 400));
  assert.equal(steers.length, 0, 'no report while B admission is open, even with A already terminal');

  // Release B as a native capture rejection (the real core admission-failure
  // path: a rejected capture fails the submission loudly, never a fake capture).
  const released = host.releaseNativeContextWithFailure();
  assert.equal(released.length, 1, 'exactly one held native capture released');

  // B surfaces as an error reply on its own dispatch call.
  const bResult = await bPromise;
  assert.equal(bResult.isError, true, 'a failed native capture must be an error reply on B');
  assert.match(text(bResult), /rejected|get_parent_context/i, 'the error relays the native capture failure cause');

  // With B's admission now closed, A's report is delivered automatically, once.
  await host.poll('A report delivered automatically after admission closes', () => steers.some((s) => s.includes('alpha actual answer')), 30000);
  const aSteer = steers.find((s) => s.includes('alpha actual answer'));
  assert.ok(aSteer, 'A report is delivered');
  assert.equal(steers.length, 1, 'A report delivered exactly once, with no extra prompt/status trigger');
  assert.equal(steers.filter((s) => s.includes('alpha actual answer')).length, 1, 'A report is not duplicated');

  // B produced no run at all (capture failed before any durable job row), so no
  // second/failure report exists and B's work never ran.
  assert.equal(host.historyRuns(SA).length, 1, 'only A became a run; B never queued');
  assert.ok(!steers.some((s) => s.includes('blocker must never run')), 'B never ran and is never reported');

  console.log('Pi session admission (real core) passed');
} finally {
  // Close the owning core connection first, then stop ONLY this test's own
  // still-active runs (bounded), drain, and remove the temp dir. The controlled
  // hold marker is removed with the temp dir; no broad kill, no live host.
  try { hooks.get('session_shutdown')({}, makeContext('SA')); } catch { /* best-effort */ }
  await host.teardown();
  try { rmSync(host.temp, { recursive: true, force: true }); } catch { /* already removed */ }
}
