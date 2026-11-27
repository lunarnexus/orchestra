// Reusable "live core host" fixture for connected Pi integration tests.
//
// Unlike the controlled `__session` STUB (orchestra-session-stub.mjs, which
// never runs Python or touches SQLite), this fixture runs the REAL Python core:
//   - a persistent `python3 -m orchestra __session` connection backed by the
//     real queue/SQLite (dispatch, status, history, stop, roles, mode),
//   - a real dispatcher worker (`__run`) per accepted run in its own process
//     group, and
//   - the real native parent-context capture and report-delivery round-trips.
//
// The only controlled boundary is the model: the `pi` RPC binary is a scripted
// fake (`fake-pi`). Transport frames are real, so queue effects, run/job ids,
// session status, cancellation, fan-out, and delivered reports are genuine —
// not a stub that merely claims success.
//
// To keep the connection observable without weakening it, the `python3` shim
// proxies the `__session` stdin/stdout through the REAL core and tees every
// newline-framed JSON line in both directions to a frames log. Requests,
// replies, status pushes, and core-initiated native_request/native_result
// frames can therefore be inspected by the test while the real runtime runs.
//
// No live Pi session, global install, or live model is ever involved.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import {
  mkdtempSync,
  writeFileSync,
  copyFileSync,
  mkdirSync,
  readFileSync,
  rmSync,
  existsSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const DEFAULT_CATALOG = `default_role: builder
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
  verifier:
    enabled: auto
    harness_config: pi
    model: "m1"
    env: {}
    skills: []
    dispatch_hint: Verify the assigned work and return your verdict with supporting evidence.
    auto_verify: false
  plain:
    enabled: manual
    harness_config: pi
    model: "m1"
    env: {}
    skills: []
    dispatch_hint: Do the assigned work and return a concise result.
    auto_verify: false
`;

// The python3 shim. `__session` proxies the real core and tees frames; other
// one-shot reads (used only by test helpers to read durable queue state) pass
// through to the real interpreter; `tool-info` is served by the real core.
function shimSource({ realPython, framesLog, holdFlag, releaseFile, heldFile }) {
  return `#!${process.execPath}
const fs = require('node:fs');
const { spawn, spawnSync } = require('node:child_process');
const args = process.argv.slice(2);
const real = ${JSON.stringify(realPython)};
const framesLog = ${JSON.stringify(framesLog)};
const holdFlag = ${JSON.stringify(holdFlag)};
const releaseFile = ${JSON.stringify(releaseFile)};
const heldFile = ${JSON.stringify(heldFile)};
function tee(dir, line) {
  if (!framesLog || !line.trim()) return;
  let frame; try { frame = JSON.parse(line); } catch (e) { frame = line; }
  try { fs.appendFileSync(framesLog, JSON.stringify({ dir, frame }) + '\\n'); } catch (e) {}
}
if (args.includes('tool-info')) {
  const r = spawnSync(real, args, { encoding: 'utf8', env: process.env });
  process.stdout.write(r.stdout || '');
  if (r.stderr) process.stderr.write(r.stderr);
  process.exit(r.status ?? 0);
}
if (args.includes('__session')) {
  const child = spawn(real, args, { stdio: ['pipe', 'pipe', 'pipe'], env: process.env });
  // Newline-framed pass-through both ways. Every complete JSONL frame is
  // forwarded byte-for-byte (frame + newline) and teed. The ONLY divergence is
  // a controlled host fault: while a hold marker exists, a core-initiated
  // get_parent_context native_request is withheld from the host (the adapter
  // is never asked, so core blocks keeping its admission open) and its id is
  // recorded. A release marker then has its frames written back to core stdin.
  let inBuf = '';
  process.stdin.on('data', (chunk) => {
    child.stdin.write(chunk);
    inBuf += chunk.toString('utf8');
    let nl;
    while ((nl = inBuf.indexOf('\\n')) >= 0) {
      tee('in', inBuf.slice(0, nl)); inBuf = inBuf.slice(nl + 1);
    }
  });
  process.stdin.on('end', () => { try { child.stdin.end(); } catch (e) {} });
  process.stdin.on('error', () => {});
  const heldIds = [];
  function persistHeld() { try { fs.writeFileSync(heldFile, heldIds.join('\\n')); } catch (e) {} }
  let outBuf = '';
  child.stdout.on('data', (chunk) => {
    outBuf += chunk.toString('utf8');
    let nl;
    while ((nl = outBuf.indexOf('\\n')) >= 0) {
      const line = outBuf.slice(0, nl); outBuf = outBuf.slice(nl + 1);
      tee('out', line);
      let f = null; try { f = JSON.parse(line); } catch (e) {}
      if (f && f.kind === 'native_request' && f.operation === 'get_parent_context'
          && holdFlag && fs.existsSync(holdFlag)) {
        heldIds.push(f.id); persistHeld();
        continue; // controlled fault: withhold the capture request from the host
      }
      process.stdout.write(line + '\\n');
    }
  });
  const injector = setInterval(() => {
    if (heldIds.length === 0 || !releaseFile || !fs.existsSync(releaseFile)) return;
    let data = '';
    try { data = fs.readFileSync(releaseFile, 'utf8'); } catch (e) { return; }
    for (const l of data.split('\\n')) {
      if (l.trim()) { try { child.stdin.write(l.endsWith('\\n') ? l : l + '\\n'); } catch (e) {} }
    }
    heldIds.length = 0; persistHeld();
    try { fs.rmSync(releaseFile, { force: true }); } catch (e) {}
  }, 50);
  if (injector.unref) injector.unref();
  child.stderr.on('data', (c) => process.stderr.write(c));
  child.on('error', (e) => { process.stderr.write(String(e)); process.exit(1); });
  child.on('exit', (c) => { if (inBuf.trim()) tee('in', inBuf); if (outBuf.trim()) tee('out', outBuf); process.exit(c ?? 0); });
  process.on('SIGTERM', () => { try { child.kill('SIGTERM'); } catch (e) {} });
  return;
}
const p = spawn(real, args, { stdio: 'inherit', env: process.env });
p.on('error', (e) => { process.stderr.write(String(e)); process.exit(1); });
p.on('exit', (c) => process.exit(c ?? 1));
`;
}

// The scripted fake-pi model binary. Entries: {match, text?, delayMs?, fail?}.
const FAKE_PI = `#!${process.execPath}
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
    // Controlled model fault: a holding harness never responds or settles, so
    // its job stays running past a dispatcher's death for recovery to observe.
    if (entry && entry.hold) return;
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
`;

export function createLiveCoreHost({
  repoRoot,
  prefix = 'orchestra-live-core-',
  catalog = DEFAULT_CATALOG,
  promptsYaml,
  delegationGuidance,
} = {}) {
  assert.ok(repoRoot, 'repoRoot is required');
  const temp = mkdtempSync(join(tmpdir(), prefix));
  const sessionDir = join(temp, 'pi-sessions');
  mkdirSync(sessionDir);
  mkdirSync(join(temp, 'state'), { recursive: true });
  mkdirSync(join(temp, 'logs'), { recursive: true });

  // Resolve the real interpreter BEFORE the shim shadows `python3` on PATH.
  const realPython = spawnSync('python3', ['-c', 'import sys;print(sys.executable)'], { encoding: 'utf8' }).stdout.trim();
  assert.ok(realPython, 'a real python3 interpreter is required');

  const configDir = join(temp, 'config');
  mkdirSync(configDir);
  copyFileSync(promptsYaml ?? join(repoRoot, 'prompts.yaml'), join(configDir, 'prompts.yaml'));
  const tempPrompts = join(configDir, 'prompts.yaml');

  // Optionally override ONE prompts.yaml value (e.g. delegation_guidance) with
  // distinctive controlled text, via the project's real Python YAML dependency,
  // proving a supplied behavior prompt flows through the real loader without
  // ever mutating the repo file or pinning default prose.
  if (delegationGuidance) {
    const r = spawnSync(realPython, [
      '-c',
      'import sys, yaml; p = sys.argv[1]; d = yaml.safe_load(open(p)) or {}; ' +
      'd["delegation_guidance"] = sys.argv[2]; ' +
      'yaml.safe_dump(d, open(p, "w"), default_flow_style=False, sort_keys=False)',
      tempPrompts,
      delegationGuidance,
    ], { encoding: 'utf8' });
    assert.equal(r.status, 0, `prompts.yaml override must succeed: ${r.stderr}`);
  }

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
  const fakePiPath = join(temp, 'fake-pi');
  writeFileSync(fakePiPath, FAKE_PI, { mode: 0o755 });
  writeFileSync(join(configDir, 'harnesses.yaml'), `pi:
  harness: pi
  command: ["${fakePiPath}"]
`);
  writeFileSync(join(configDir, 'agent-catalog.yaml'), catalog);

  const framesLog = join(temp, 'frames.log');
  writeFileSync(framesLog, '');
  const holdFlag = join(temp, 'hold-native-context.flag');
  const releaseFile = join(temp, 'release-native-context.jsonl');
  const heldFile = join(temp, 'held-native-context.ids');
  writeFileSync(join(temp, 'python3'), shimSource({ realPython, framesLog, holdFlag, releaseFile, heldFile }), { mode: 0o755 });

  // Save the ambient PATH so a test can prepend an override bin dir and restore.
  const ambientPath = process.env.PATH;
  process.env.PATH = `${temp}:${process.env.PATH}`;
  process.env.ORCHESTRA_CONFIG = configDir;
  process.env.PYTHONPATH = join(repoRoot, 'src');
  process.env.PI_CODING_AGENT_SESSION_DIR = sessionDir;
  process.env.FAKE_PI_SCENARIO = join(temp, 'scenario.json');
  writeFileSync(join(temp, 'scenario.json'), JSON.stringify([{ match: '*', text: 'live core answer' }]));

  const ownRunIds = new Set();
  const ownSessions = new Set();

  const host = {
    temp,
    realPython,
    configDir,
    framesLog,
    ambientPath,
    queueDb: join(temp, 'state', 'queue.db'),
    holdFlag,
    releaseFile,
    heldFile,

    setScenario(entries) {
      writeFileSync(join(temp, 'scenario.json'), JSON.stringify(entries));
    },

    // Track this test's own runs/sessions for safe, bounded teardown.
    trackRun(text) {
      const m = String(text).match(/\b[0-9a-f]{32}\b/);
      if (m) ownRunIds.add(m[0]);
      return m ? m[0] : null;
    },
    trackSession(sessionId) {
      ownSessions.add(sessionId);
      return sessionId;
    },

    // ---- connection frame inspection (from the tee log) ----
    frames() {
      if (!existsSync(framesLog)) return [];
      return readFileSync(framesLog, 'utf8')
        .split('\n')
        .filter((l) => l.length > 0)
        .map((l) => JSON.parse(l));
    },
    requests(operation) {
      const reqs = host.frames().filter((f) => f.dir === 'in' && f.frame.kind === 'request').map((f) => f.frame);
      return operation ? reqs.filter((r) => r.operation === operation) : reqs;
    },
    request(operation) {
      return host.requests(operation).pop();
    },
    nativeRequests(operation) {
      const nreqs = host.frames().filter((f) => f.dir === 'out' && f.frame.kind === 'native_request').map((f) => f.frame);
      return operation ? nreqs.filter((r) => r.operation === operation) : nreqs;
    },
    nativeResults() {
      return host.frames().filter((f) => f.dir === 'in' && f.frame.kind === 'native_result').map((f) => f.frame);
    },
    resetFrames() {
      writeFileSync(framesLog, '');
    },

    // ---- durable queue reads (through the real CLI, never the transport) ----
    statusPayload(sessionId) {
      const r = spawnSync(realPython, ['-m', 'orchestra', 'status', '--session-id', sessionId, '--mode', 'on'], { encoding: 'utf8', env: process.env, timeout: 15000 });
      if (r.status !== 0) throw new Error(`status failed: ${r.stderr}`);
      return JSON.parse(r.stdout).data;
    },
    activeJobs(sessionId) {
      try {
        return host.statusPayload(sessionId).session_jobs ?? [];
      } catch {
        return [];
      }
    },
    historyRuns(sessionId) {
      const r = spawnSync(realPython, ['-m', 'orchestra', 'history', '--session-id', sessionId], { encoding: 'utf8', env: process.env, timeout: 15000 });
      try {
        return (JSON.parse(r.stdout).runs ?? []).map((x) => x.run_id);
      } catch {
        return [];
      }
    },

    // ---- read-only durable execution identity (never a recovery trigger) ----
    // The registered child_pgid is the harness process group the dispatcher
    // launched with its own session. Read directly from SQLite so the test never
    // issues a status/session-return call that could itself reconcile.
    jobChildPgid(runId) {
      if (!existsSync(host.queueDb)) return null;
      const out = spawnSync(realPython, [
        '-c',
        'import sqlite3,sys; r=sqlite3.connect(sys.argv[1]).execute('
        + '"select child_pgid from jobs where run_id=? and child_pgid is not null limit 1", (sys.argv[2],)).fetchone();'
        + 'print(r[0] if r else "")',
        host.queueDb, runId,
      ], { encoding: 'utf8' });
      const v = out.status === 0 ? out.stdout.trim() : '';
      return v ? parseInt(v, 10) : null;
    },

    // The test-owned dispatcher (`__run` worker) is the PARENT of the registered
    // harness group, uniquely identified by the run id in its own argv. This is
    // owner-scoped: only this run's worker can be returned, never a foreign one.
    dispatcherPid(runId) {
      const pgid = host.jobChildPgid(runId);
      if (!pgid) return null;
      const out = spawnSync(realPython, [
        '-c',
        'import sys,psutil;'
        + 'child=psutil.Process(int(sys.argv[1]));'
        + 'parent=child.parent();'
        + 'cl=" ".join(parent.cmdline());'
        + 'print(parent.pid if sys.argv[2] in cl and "__run" in cl else "")',
        String(pgid), runId,
      ], { encoding: 'utf8', timeout: 8000 });
      const v = out.status === 0 ? out.stdout.trim() : '';
      return v ? parseInt(v, 10) : null;
    },

    // ---- controlled native parent-context hold (host fault) ----
    // While held, core's get_parent_context capture is never answered, so the
    // dispatch admission stays open and the session never becomes ready.
    holdNativeContext(on) {
      if (on) writeFileSync(holdFlag, '1');
      else { try { rmSync(holdFlag, { force: true }); } catch (e) {} }
    },
    heldNativeContextIds() {
      if (!existsSync(heldFile)) return [];
      return readFileSync(heldFile, 'utf8').split('\n').map((s) => s.trim()).filter(Boolean);
    },
    // Release a held capture as a rejection — the real core path for a native
    // capture failure (a rejected capture fails the submission loudly, never a
    // fake capture). Builds one accepted:false native_result per held id.
    releaseNativeContextWithFailure() {
      const ids = host.heldNativeContextIds();
      const lines = ids.map((id) => JSON.stringify({
        kind: 'native_result', id, accepted: false, error: 'test-controlled native capture failure',
      }));
      writeFileSync(releaseFile, lines.join('\n') + (lines.length ? '\n' : ''));
      host.holdNativeContext(false);
      return ids;
    },
  };

  host.poll = async function poll(label, fn, timeoutMs = 20000) {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      if (fn()) return;
      if (Date.now() > deadline) throw new Error(`timed out waiting for ${label}`);
      await new Promise((r) => setTimeout(r, 100));
    }
  };

  // ---- success proof: every tracked run reaches a persisted terminal end ----
  host.waitForCompletedEndState = async function waitForCompletedEndState(timeoutMs = 40000) {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const done = new Set();
      for (const s of ownSessions) for (const id of host.historyRuns(s)) done.add(id);
      if ([...ownRunIds].every((id) => done.has(id))) return;
      if (Date.now() > deadline) {
        throw new Error(`timed out waiting for dispatched runs to reach a persisted completed end-state (seen=${done.size}/${ownRunIds.size})`);
      }
      await new Promise((r) => setTimeout(r, 200));
    }
  };

  // ---- bounded, owner-scoped teardown ----
  // Stop ONLY this test's own runs, wait bounded for them to drain, THEN remove
  // the temp dir. Never removes SQLite state while a run is still active.
  host.teardown = async function teardown() {
    for (const s of ownSessions) {
      const activeIds = new Set(host.activeJobs(s).map((j) => j.run_id).filter(Boolean));
      for (const runId of ownRunIds) {
        if (!activeIds.has(runId)) continue;
        try {
          spawnSync(realPython, ['-m', 'orchestra', 'stop', '--session-id', s, '--run-id', runId], { encoding: 'utf8', env: process.env, timeout: 8000 });
        } catch { /* best-effort, bounded */ }
      }
    }
    // Wait bounded until none of our own runs remain active in any owned session.
    const deadline = Date.now() + 20000;
    for (;;) {
      let anyActive = false;
      for (const s of ownSessions) {
        const active = new Set(host.activeJobs(s).map((j) => j.run_id).filter(Boolean));
        if ([...ownRunIds].some((id) => active.has(id))) anyActive = true;
      }
      if (!anyActive) break;
      if (Date.now() > deadline) break; // bounded: never hang cleanup
      await new Promise((r) => setTimeout(r, 200));
    }
    for (let i = 0; i < 20; i += 1) {
      try { rmSync(temp, { recursive: true, force: true }); break; } catch { await new Promise((r) => setTimeout(r, 200)); }
    }
    // Restore ambient PATH so a leaked failure cannot poison later tests.
    process.env.PATH = ambientPath;
  };

  return host;
}

// Standard minimal native UI context for the connected tests. `contextEntries`
// feed the host-side native parent-context capture; `notes`/`widgets`/`footers`
// collect native notifications/widgets so the test can observe renders.
export function makeContext(sessionId, { contextEntries = [], notes = [], widgets = [], footers = [] } = {}) {
  return {
    hasUI: true,
    sessionManager: {
      getSessionId: () => sessionId,
      buildContextEntries: () => contextEntries,
      getBranch: () => [],
    },
    ui: {
      theme: { fg: (_c, t) => t, bold: (t) => t },
      setWidget: (key, content, options) => { widgets.push({ key, content, options }); if (Array.isArray(content)) footers.push(content.join('\n')); else footers.push(''); },
      notify: (msg) => notes.push(String(msg)),
    },
  };
}

export const text = (result) => (result.content ?? []).map((part) => part.text ?? '').join('\n');
