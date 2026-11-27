import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, readFileSync, rmSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createJiti } from 'jiti';

// Native-connection ownership regressions for the Pi translator, against a
// controlled self-contained `__session` core stub (no real core, models, live
// Pi, or install). Proves:
//   1. initial-mode failure exposes its real cause and keeps the tools
//      DISABLED (no fallback-on);
//   2. a tool request from a stale native session cannot control the live
//      core connection (rejected visibly; the core never sees the request),
//      while the owning session's identical request still succeeds;
//   3. a late core frame (deliver_report + reply) emitted after its
//      connection was closed by a session replacement is ignored: it never
//      steers the replacement session and never answers through it, while the
//      in-flight request is rejected visibly.
const temp = mkdtempSync(join(tmpdir(), 'orch-native-conn-'));
const logDir = join(temp, 'frames');
mkdirSync(logDir, { recursive: true });
const scenPath = join(temp, 'scenario.json');
writeFileSync(scenPath, JSON.stringify({}));

const TOOL_INFO = {
  dispatch: { label: 'D', description: 'Submit.', params: { goal: 'g.', additionalContext: 'c.', role: 'r.', taskLabel: 'l.' } },
  status: { label: 'S', description: 'Manage.', params: { action: 'a.', limit: 'n.', runId: 'i.' } },
  command: { description: '/orch' },
  actions: ['status', 'history', 'stop', 'help', 'doctor', 'roles'],
};

// Self-contained controlled core: one-shot tool-info; a persistent `__session`
// runtime scripted by the scenario file (re-read per request). Frames each
// session process RECEIVED and the late-emit marker are logged per parent
// session so assertions can prove what the core actually saw. On SIGTERM the
// shim keeps its scheduled late emit alive (deterministically simulating a
// core frame already in flight when the adapter closes the connection).
writeFileSync(join(temp, 'python3'), `#!${process.execPath}
const fs = require('node:fs');
const args = process.argv.slice(2);
const scenPath = process.env.ORCH_NC_SCENARIO || '';
const logDir = process.env.ORCH_NC_LOG || '';
function loadScenario() { try { return JSON.parse(fs.readFileSync(scenPath, 'utf8')); } catch (e) { return {}; } }
function safe(s) { return String(s).replace(/[^a-zA-Z0-9_-]/g, '_'); }
function record(parent, obj) { if (!logDir) return; try { fs.appendFileSync(logDir + '/frames-' + safe(parent) + '.log', JSON.stringify(obj) + '\\n'); } catch (e) {} }
if (args.includes('tool-info')) { process.stdout.write(${JSON.stringify(JSON.stringify(TOOL_INFO))}); process.exit(0); }
if (args.includes('__session')) {
  const parent = args[args.indexOf('--parent-session') + 1] || '';
  record(parent, { frame: 'session_open' });
  let flushTimer = null;
  process.on('SIGTERM', () => { if (!flushTimer) process.exit(0); });
  const w = (obj) => process.stdout.write(JSON.stringify(obj) + '\\n');
  let buf = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', (chunk) => {
    buf += chunk;
    let nl;
    while ((nl = buf.indexOf('\\n')) >= 0) {
      const line = buf.slice(0, nl); buf = buf.slice(nl + 1);
      if (!line.trim()) continue;
      let msg; try { msg = JSON.parse(line); } catch (e) { continue; }
      record(parent, { frame: 'request', msg });
      if (msg.kind !== 'request') continue;
      const scen = loadScenario();
      if (msg.operation === 'initial-mode') {
        if (typeof scen.initialModeError === 'string') w({ kind: 'reply', id: msg.id, error: scen.initialModeError });
        else w({ kind: 'reply', id: msg.id, result: { mode: scen.mode || 'on', text: scen.mode || 'on' } });
        continue;
      }
      if (msg.operation === 'dispatch') {
        if (scen.lateDeliverMs) {
          flushTimer = setTimeout(() => {
            record(parent, { frame: 'late_emit' });
            w({ kind: 'native_request', id: 'late-1', operation: 'deliver_report', arguments: { text: scen.lateReport || 'LATE' } });
            w({ kind: 'reply', id: msg.id, result: { text: 'late reply' } });
            process.exit(0);
          }, scen.lateDeliverMs);
        } else {
          w({ kind: 'reply', id: msg.id, result: { text: 'ACK ' + msg.id } });
        }
        continue;
      }
      w({ kind: 'reply', id: msg.id, error: 'operation ' + msg.operation + ' is not scripted' });
    }
  });
  process.stdin.on('end', () => { if (!flushTimer) process.exit(0); });
  return;
}
process.exit(0);
`, { mode: 0o755 });

process.env.PATH = `${temp}:${process.env.PATH}`;
process.env.ORCHESTRA_CONFIG = temp;
process.env.ORCH_NC_SCENARIO = scenPath;
process.env.ORCH_NC_LOG = logDir;

function setScenario(scenario) { writeFileSync(scenPath, JSON.stringify(scenario)); }
function frames(parent) {
  try {
    return readFileSync(join(logDir, `frames-${parent.replace(/[^a-zA-Z0-9_-]/g, '_')}.log`), 'utf8')
      .split('\n').filter((l) => l.length > 0).map((l) => JSON.parse(l));
  } catch { return []; }
}
// The adapter opens the core with the normalized identity `pi:<id>`; the shim
// sanitizes that to the log-file suffix.
const fk = (id) => `pi_${id}`;
function operations(parent) {
  return frames(parent).filter((f) => f.frame === 'request').map((f) => f.msg.operation);
}
async function waitFor(label, fn, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (fn()) return;
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${label}`);
    await new Promise((r) => setTimeout(r, 25));
  }
}
const text = (result) => (result.content ?? []).map((p) => p.text ?? '').join('\n');

function makeCtx(sessionId, notes) {
  return {
    hasUI: true,
    sessionManager: { getSessionId: () => sessionId, buildContextEntries: () => [], getBranch: () => [] },
    ui: {
      theme: { fg: (_c, t) => t, bold: (t) => t },
      setWidget() {},
      notify: (m) => notes.push(String(m)),
    },
  };
}

const hooks = new Map();
const tools = new Map();
const steers = [];
let active = [];

try {
  const jiti = createJiti(import.meta.url);
  const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');
  await activate({
    on: (name, handler) => hooks.set(name, handler),
    registerTool: (t) => { tools.set(t.name, t); active.push(t.name); },
    registerCommand() {},
    registerEntryRenderer() {},
    appendEntry() {},
    getActiveTools: () => [...active],
    setActiveTools: (list) => { active = [...list]; },
    sendUserMessage: (m) => steers.push(String(m)),
  });
  assert.ok(tools.has('orch_dispatch') && tools.has('orch_status'), 'orchestra tools registered');

  async function startSession(ctx) {
    await hooks.get('session_start')({}, ctx);
  }
  function endSession(ctx) {
    if (hooks.has('session_shutdown')) hooks.get('session_shutdown')({}, ctx);
  }

  // -- 1. initial-mode failure: cause exposed, tools stay disabled ------------
  {
    setScenario({ initialModeError: 'mode config exploded in core' });
    const notes = [];
    const ctx = makeCtx('mode-fail', notes);
    try {
      await startSession(ctx);
      assert.ok(notes.some((n) => n.includes('mode config exploded in core')),
        `initial-mode failure must expose the core cause, got: ${JSON.stringify(notes)}`);
      assert.ok(!active.includes('orch_dispatch') && !active.includes('orch_status'),
        'initial-mode failure must keep the orchestra tools disabled (no fallback-on)');
    } finally {
      endSession(ctx);
    }
  }

  // -- 2. stale-session tool request cannot control the live connection -------
  {
    setScenario({ mode: 'on' });
    const stale = makeCtx('owner-stale', []);
    const live = makeCtx('owner-live', []);
    try {
      await startSession(stale);
      await startSession(live); // replaces the stale session's connection
      const staleResult = await tools.get('orch_dispatch').execute('c1', { goal: 'stale goal' }, undefined, undefined, stale);
      assert.equal(staleResult.isError, true, 'a stale-session tool request must be an error');
      assert.ok(!operations(fk('owner-stale')).includes('dispatch') && !operations(fk('owner-live')).includes('dispatch'),
        'the rejected stale request must never reach the core');
      const liveResult = await tools.get('orch_dispatch').execute('c2', { goal: 'live goal' }, undefined, undefined, live);
      assert.equal(liveResult.isError, false, `the owning session must still dispatch: ${text(liveResult)}`);
      assert.match(text(liveResult), /^ACK /, 'core ack text is returned verbatim to the owning session');
      assert.ok(operations(fk('owner-live')).includes('dispatch'), 'owning dispatch reached its own core');
    } finally {
      endSession(live);
    }
  }

  // -- 3. late frame after close must not deliver into the replacement --------
  {
    const LATE_REPORT = 'LATE_REPORT_MUST_NOT_DELIVER';
    setScenario({ mode: 'on', lateDeliverMs: 400, lateReport: LATE_REPORT });
    const old = makeCtx('late-core', []);
    const replacement = makeCtx('replacement', []);
    try {
      await startSession(old);
      const inflight = tools.get('orch_dispatch').execute('c1', { goal: 'late' }, undefined, undefined, old);
      await waitFor('core received the dispatch', () => operations(fk('late-core')).includes('dispatch'));
      await startSession(replacement); // closes the old connection mid-request
      const result = await inflight;
      assert.equal(result.isError, true, 'an in-flight request is rejected visibly when its connection closes');
      await waitFor('late frame emitted by the core', () => frames(fk('late-core')).some((f) => f.frame === 'late_emit'));
      await new Promise((r) => setTimeout(r, 300)); // grace for any racing delivery
      assert.ok(!steers.some((s) => s.includes(LATE_REPORT)),
        'a late core frame from a closed connection must never deliver into the replacement session');
      assert.ok(!frames(fk('replacement')).some((f) => f.frame === 'request' && f.msg.kind === 'native_result'),
        'a late core frame must never be answered through the replacement connection');
    } finally {
      endSession(replacement);
    }
  }

  console.log('Pi native-connection ownership regressions passed');
} finally {
  rmSync(temp, { recursive: true, force: true });
}
