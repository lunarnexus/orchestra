import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { rmSync, readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createJiti } from 'jiti';
import { createLiveCoreHost, makeContext, text } from './helpers/pi-live-core-host.mjs';

// Item: dispatcher-death recovery, against the REAL Python core session runtime
// (real queue/SQLite, real detached per-run `__run` dispatcher workers, real
// native report delivery). The ONLY controlled boundary is the fake-Pi model and
// a holding model fault. This preserves the BEHAVIOR the obsolete raw-ack test
// asserted — a dispatcher that dies after the native tool ack, while its own
// execution is still running, must be reconciled by the still-live `__session`
// core observer and deliver the actual failure to the originating idle session
// exactly once — but no longer drives or asserts the raw dispatch-ack wire
// protocol. Recovery here is core-observer-driven (proc.wait on the dead worker
// wakes evaluate -> reconcile_abandoned), never a host status call.
//
// Owner-scoped by construction: the dispatcher we SIGKILL is identified ONLY as
// the psutil parent of THIS run's registered child_pgid whose own argv carries
// this run id, so only this test's worker can ever be signaled.

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const host = createLiveCoreHost({ repoRoot });

function alive(pid) {
  if (!pid) return false;
  try { process.kill(pid, 0); return true; } catch (e) { return e.code === 'EPERM'; }
}

function persistedJobStatus(jobId) {
  if (!existsSync(host.queueDb)) return null;
  const out = spawnSync(host.realPython, [
    '-c',
    'import sqlite3,sys; r=sqlite3.connect(sys.argv[1]).execute("select status from jobs where job_id=?", (sys.argv[2],)).fetchone(); print(r[0] if r else "")',
    host.queueDb, jobId,
  ], { encoding: 'utf8' });
  return out.status === 0 ? out.stdout.trim() : '';
}

function persistedEvidence(runId, needle) {
  const file = join(host.temp, 'state', 'artifacts', `${runId}.jsonl`);
  if (!existsSync(file)) return false;
  return readFileSync(file, 'utf8').includes(needle);
}

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
    { match: 'WEDGE', hold: true },
    { match: 'slow', text: 'slow actual answer', delayMs: 1200 },
    { match: 'foreign', text: 'foreign session answer' },
    { match: '*', text: 'generic answer' },
  ]);

  // --- journey 1: a foreign session completes normally, isolated from wedged ---
  host.trackSession('pi:FOREIGN');
  await hooks.get('session_start')({}, makeContext('FOREIGN'));
  const foreignAck = await tools.get('orch_dispatch').execute('f1', { goal: 'foreign task', role: 'plain' }, undefined, undefined, makeContext('FOREIGN'));
  assert.equal(foreignAck.isError, false, 'foreign dispatch acked');
  host.trackRun(text(foreignAck));
  await host.poll('foreign session return', () => steers.some((s) => s.includes('foreign session answer')));
  const foreignBaseline = steers.length;

  // --- journey 2: wedged dispatcher dies after ack; idle origin recovers -----
  host.trackSession('pi:S1');
  await hooks.get('session_start')({}, makeContext('S1'));
  const wedgedAck = await tools.get('orch_dispatch').execute('w1', { goal: 'WEDGE this run', role: 'plain' }, undefined, undefined, makeContext('S1'));
  assert.equal(wedgedAck.isError, false, 'wedged dispatch acked');
  const runId = host.trackRun(text(wedgedAck));
  assert.ok(runId, 'run id parsed from ack');
  const jobId = `${runId}:1`;

  // Prove the dispatcher is ALIVE and its execution is registered + running
  // BEFORE injecting death, so this exercises the post-ack loss path — not a
  // pre-launch failure (which test_session_execution already proves in Python).
  await host.poll('wedged execution registered', () => host.jobChildPgid(runId) !== null, 30000);
  const harnessPgid = host.jobChildPgid(runId);
  assert.ok(alive(harnessPgid), 'registered harness group alive before the kill');
  await host.poll('test-owned dispatcher identified', () => alive(host.dispatcherPid(runId)), 30000);
  const dispatcherPid = host.dispatcherPid(runId);
  assert.ok(dispatcherPid && dispatcherPid !== harnessPgid, 'dispatcher pid distinct from harness pgid');

  // Inject death into ONLY the test-owned dispatcher (external SIGKILL, like the
  // bench's self-matching pkill). No prompt, no status call, no direct
  // reconciliation is issued by this test.
  process.kill(dispatcherPid, 'SIGKILL');
  await host.poll('dispatcher death', () => !alive(dispatcherPid), 10000);

  // The only new event is the dead worker's process exit, observed by the
  // still-live core connection. Recovery must deliver the failure to the
  // originating session automatically — no status/return call was issued.
  await host.poll('failure delivered to originating session', () => steers.slice(foreignBaseline).some((s) => s.includes('failed')), 40000);
  const wedgedSteer = steers.slice(foreignBaseline).find((s) => s.includes('failed'));
  assert.ok(wedgedSteer, 'a failure report reached the session');
  assert.match(wedgedSteer, /dispatcher loss|abandoned/i, 'the report names dispatcher loss, not a normal job failure');
  assert.doesNotMatch(wedgedSteer, /foreign session answer/, 'the originating report excludes foreign session content');
  assert.equal(steers.length, foreignBaseline + 1, 'the wedged failure delivers exactly once');

  // Recovery TERMINATES the surviving owned execution, not merely marks it failed.
  await host.poll('surviving owned execution terminated by recovery', () => !alive(harnessPgid), 40000);

  // Persisted terminal failure + durable loss evidence (read directly; never a
  // status subprocess that could itself be the recovery trigger).
  await host.poll('persisted failed status', () => persistedJobStatus(jobId) === 'failed', 15000);
  assert.ok(
    persistedEvidence(runId, 'dispatcher loss') || persistedEvidence(runId, 'abandoned'),
    'durable dispatcher-loss reason recorded in artifacts',
  );

  // --- journey 3: concurrent same-session accepted run gates the report -------
  host.trackSession('pi:Sg');
  const gctx = makeContext('Sg');
  await hooks.get('session_start')({}, gctx);
  const gBase = steers.length;
  const gAck1 = await tools.get('orch_dispatch').execute('g1', { goal: 'WEDGE gate run', role: 'plain' }, undefined, undefined, gctx);
  assert.equal(gAck1.isError, false, 'gate wedged acked');
  const gRunId = host.trackRun(text(gAck1));
  // A second, still-executing run of the SAME session must hold the return.
  const gAck2 = await tools.get('orch_dispatch').execute('g2', { goal: 'slow gate run', role: 'plain' }, undefined, undefined, gctx);
  assert.equal(gAck2.isError, false, 'gate slow acked');
  host.trackRun(text(gAck2));

  await host.poll('gate execution registered', () => host.jobChildPgid(gRunId) !== null, 30000);
  await host.poll('gate dispatcher identified', () => alive(host.dispatcherPid(gRunId)), 30000);
  const gDispatcher = host.dispatcherPid(gRunId);
  process.kill(gDispatcher, 'SIGKILL');
  await host.poll('gate dispatcher death', () => !alive(gDispatcher), 10000);

  // After death, while the slow run is still executing, NOTHING may be delivered
  // for the gate session (the live concurrent run keeps the session non-ready).
  await new Promise((r) => setTimeout(r, 800));
  assert.equal(steers.length, gBase, 'no premature return while a live same-session run is still outstanding');

  // Once the slow run drains, the gate opens and the wedged failure returns with
  // it, in exactly one consolidated report.
  await host.poll('gate return after slow run drains', () => steers.length > gBase, 40000);
  const gateSteer = steers.slice(gBase).join('\n');
  assert.match(gateSteer, /failed/i, 'wedged failure delivered once the gate opens');
  assert.match(gateSteer, /slow actual answer/, 'the concurrently running result returns together');
  assert.equal(steers.length, gBase + 1, 'the consolidated gate return fires exactly once');

  console.log('Pi dispatcher-death recovery (real core) passed');
} finally {
  // Close the owning core connection first (session_shutdown), then let the
  // helper stop ONLY this test's own still-active runs (the held harness groups
  // are terminated through real core stop/reconcile), wait bounded to drain,
  // and remove the temp dir. No broad kill, no live host.
  for (const s of ['FOREIGN', 'S1', 'Sg']) {
    try { hooks.get('session_shutdown')({}, makeContext(s)); } catch { /* best-effort */ }
  }
  await host.teardown();
  try { rmSync(host.temp, { recursive: true, force: true }); } catch { /* already removed */ }
}
