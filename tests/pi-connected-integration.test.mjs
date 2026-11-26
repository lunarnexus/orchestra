import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, copyFileSync, mkdirSync, readFileSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createJiti } from 'jiti';

// Slice C: connected integration. The real Pi extension is connected to the
// real Python core (no tool-info interception). The only controlled boundaries
// are the model harness (fake pi binary) and a thin argv/stdin recorder so the
// test can prove what argv the adapter forwarded and what parent-context
// payload it captured. Covers:
//   - real `tool-info` metadata visible in registered tools before the first
//     agent call, including the configured delegation_guidance from
//     prompts.yaml.
//   - taskLabel via the orch_dispatch tool AND `/orch do --task-label`,
//     including labels containing spaces.
//   - unlabeled dispatch still produces a valid ack with no label rendered.
//   - taskLabel never leaks into parent context or goal.
//   - omitted history limit means no `--limit` flag in the adapter's argv.
//   - malformed acknowledgements fail visibly without fallback substitutions.
//   - malformed tool-info metadata registers no tools and surfaces its cause.
// No live Pi sessions, global installs, or live models.

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const temp = mkdtempSync(join(tmpdir(), 'orchestra-connected-'));
const sessionDir = join(temp, 'pi-sessions');
mkdirSync(sessionDir);
mkdirSync(join(temp, 'state'), { recursive: true });
mkdirSync(join(temp, 'logs'), { recursive: true });

const realPython = spawnSync('python3', ['-c', 'import sys;print(sys.executable)'], { encoding: 'utf8' }).stdout.trim();
assert.ok(realPython, 'a real python3 interpreter is required');

// --- argv/stdin recorder --------------------------------------------------
// Records every dispatch / status / history invocation to the argv log, and
// tees stdin for `dispatch` to the parent-context log, then forwards the call
// to the real Python core unchanged (preserving stdio for ack lines).
const argvLog = join(temp, 'argv.log');
const parentCtxLog = join(temp, 'parent-ctx.log');
writeFileSync(argvLog, '');
writeFileSync(parentCtxLog, '');

writeFileSync(join(temp, 'python3'), `#!${process.execPath}
const fs = require('node:fs');
const { spawn } = require('node:child_process');
const argvLog = ${JSON.stringify(argvLog)};
const parentCtxLog = ${JSON.stringify(parentCtxLog)};
const real = ${JSON.stringify(realPython)};
const args = process.argv.slice(2);
fs.appendFileSync(argvLog, JSON.stringify(args) + '\\n');
let input = '';
process.stdin.on('data', (d) => { input += d; });
process.stdin.on('end', () => {
  if (args.includes('dispatch') && input.length > 0) {
    fs.appendFileSync(parentCtxLog, JSON.stringify({ args, stdin: input }) + '\\n');
  }
  const child = spawn(real, args, { stdio: ['pipe', 'inherit', 'inherit'], env: process.env });
  child.stdin.end(input);
  child.on('error', (e) => { process.stderr.write(String(e)); process.exit(1); });
  child.on('exit', (c) => process.exit(c ?? 1));
});
`, { mode: 0o755 });

// Fake pi harness binary: same pattern as pi-controls.
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
      send({ id: 'p1', type: 'response', success: true });
      send({ type: 'agent_settled', aborted: false });
    }, (entry && entry.delayMs) || 0);
  } else if (msg.type === 'get_last_assistant_text') {
    const entry = entryFor(lastPrompt);
    send({ id: msg.id, type: 'response', command: 'get_last_assistant_text', data: { text: (entry && entry.text) || 'unscripted answer' } });
  }
});
`, { mode: 0o755 });

// --- real config with real prompts.yaml -----------------------------------
const configDir = join(temp, 'config');
mkdirSync(configDir);
// Copy the real prompts.yaml into the temp config, then override ONLY the
// delegation_guidance value with distinctive controlled test text using the
// project's existing Python YAML dependency (via spawnSync of the real
// interpreter). This proves a supplied behavior prompt flows through the real
// loader into core metadata and Pi registration, without pinning default prose
// (PLAN test1) and without ever mutating the repo's prompts.yaml.
const TEST_DELEGATION = 'ZZTEST-CONTROLLED-DELEGATION-PHRASE delegate-every-slice-now';
const tempPrompts = join(configDir, 'prompts.yaml');
copyFileSync(join(repoRoot, 'prompts.yaml'), tempPrompts);
const overrideYaml = spawnSync(
  realPython,
  [
    '-c',
    'import sys, yaml; p = sys.argv[1]; d = yaml.safe_load(open(p)) or {}; ' +
    'd["delegation_guidance"] = sys.argv[2]; ' +
    'yaml.safe_dump(d, open(p, "w"), default_flow_style=False, sort_keys=False)',
    tempPrompts,
    TEST_DELEGATION,
  ],
  { encoding: 'utf8' },
);
assert.equal(overrideYaml.status, 0, `temp prompts.yaml override must succeed: ${overrideYaml.stderr}`);
assert.ok(readFileSync(tempPrompts, 'utf8').includes(TEST_DELEGATION), 'temp prompts.yaml carries the controlled delegation text');
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
`);

process.env.PATH = `${temp}:${process.env.PATH}`;
process.env.ORCHESTRA_CONFIG = configDir;
process.env.PYTHONPATH = join(repoRoot, 'src');
process.env.PI_CODING_AGENT_SESSION_DIR = sessionDir;
process.env.FAKE_PI_SCENARIO = join(temp, 'scenario.json');

// --- owner-scoped process/run teardown ------------------------------------
// This process-based test dispatches REAL runs to the real core under session
// CONN1. If an assertion fails mid-flight, its own dispatched subprocesses/runs
// would otherwise be left active while the temp dir is deleted. We track ONLY
// this test's own run ids (owner-scoped) and, in the finally block, stop those
// specific runs with the real core before removing the temp dir. No global
// kill, no live host. Bounded so teardown can never hang.
const CONN_SESSION = 'pi:CONN1';
const ownRunIds = new Set();
function extractRunId(t) {
  const m = String(t).match(/\b[0-9a-f]{32}\b/);
  if (m) ownRunIds.add(m[0]);
  return m ? m[0] : null;
}
// Invoke the real core directly (the recorded fake python3 is only on PATH for
// the adapter; teardown uses the real interpreter explicitly, bounded).
function coreCli(args, timeoutMs = 15000) {
  return spawnSync(realPython, ['-m', 'orchestra', ...args], {
    encoding: 'utf8',
    env: process.env,
    timeout: timeoutMs,
  });
}
function completedRunIds() {
  const r = coreCli(['history', '--session-id', CONN_SESSION]);
  const ids = new Set();
  try {
    const data = JSON.parse(r.stdout);
    for (const run of data.runs ?? []) {
      if (run.run_id) ids.add(run.run_id);
    }
  } catch { /* not parseable yet */ }
  return ids;
}
// Success-path proof: every dispatched run reaches a PERSISTED completed
// (terminal) end-state in the real core. Bounded so it can never hang.
async function waitForCompletedEndState(timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const done = completedRunIds();
    if ([...ownRunIds].every((id) => done.has(id))) return;
    if (Date.now() > deadline) {
      throw new Error(`timed out waiting for dispatched runs to reach a persisted completed end-state (seen=${done.size}/${ownRunIds.size})`);
    }
    await new Promise((r) => setTimeout(r, 200));
  }
}
// Bounded, owner-scoped teardown: stop ONLY this test's own runs still active
// in its own session, then wait (bounded) for them to leave the active set,
// i.e. reach a persisted terminal end-state in the real core. No global kill.
async function teardownOwnRuns() {
  const activeRunIds = () => {
    const r = coreCli(['status', '--session-id', CONN_SESSION, '--mode', 'on']);
    const ids = new Set();
    try {
      const data = JSON.parse(r.stdout);
      for (const job of data.data?.session_jobs ?? []) if (job.run_id) ids.add(job.run_id);
    } catch { /* not parseable yet */ }
    return ids;
  };
  for (const runId of ownRunIds) {
    try {
      coreCli(['stop', '--session-id', CONN_SESSION, '--run-id', runId], 8000);
    } catch { /* best-effort, bounded */ }
  }
  const deadline = Date.now() + 20000;
  for (;;) {
    const active = activeRunIds();
    if (![...ownRunIds].some((id) => active.has(id))) return;
    if (Date.now() > deadline) return; // bounded: never hang cleanup
    await new Promise((r) => setTimeout(r, 200));
  }
}

function setScenario(entries) {
  writeFileSync(join(temp, 'scenario.json'), JSON.stringify(entries));
}
setScenario([{ match: '*', text: 'connected answer' }]);

function recordedArgv() {
  return readFileSync(argvLog, 'utf8').split('\n').filter((l) => l.length > 0).map((l) => JSON.parse(l));
}
function recordedDispatchStdin() {
  if (!existsSync(parentCtxLog)) return [];
  return readFileSync(parentCtxLog, 'utf8').split('\n').filter((l) => l.length > 0).map((l) => JSON.parse(l));
}

async function poll(label, fn, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (fn()) return;
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${label}`);
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
}

const text = (result) => (result.content ?? []).map((part) => part.text ?? '').join('\n');

function makeContext(sessionId, opts = {}) {
  return {
    hasUI: true,
    sessionManager: {
      getSessionId: () => sessionId,
      buildContextEntries: () => opts.contextEntries ?? [],
      getBranch: () => opts.branch ?? [],
    },
    ui: {
      theme: { fg: (_c, t) => t, bold: (t) => t },
      setWidget() {},
      notify: (msg) => { notifs.push(String(msg)); },
    },
  };
}

const notifs = [];

try {
  const jiti = createJiti(import.meta.url);
  const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');
  const hooks = new Map();
  const tools = new Map();
  const commands = new Map();
  const entries = [];
  const steers = [];
  let active = [];

  await activate({
    on: (name, handler) => hooks.set(name, handler),
    registerTool: (tool) => tools.set(tool.name, tool),
    registerCommand: (name, def) => commands.set(name, def),
    registerEntryRenderer() {},
    appendEntry: (type, data) => entries.push({ type, data }),
    getActiveTools: () => [...active],
    setActiveTools: (v) => { active = [...v]; },
    sendUserMessage: (msg) => steers.push(String(msg)),
  });

  // ---- 1: real tool-info metadata reaches registered tools BEFORE first agent
  assert.ok(tools.has('orch_dispatch'), 'orch_dispatch registered');
  assert.ok(tools.has('orch_status'), 'orch_status registered');

  // The controlled delegation_guidance is set in the temp config's prompts.yaml
  // (the real loader reads it via ORCHESTRA_CONFIG). Prove the distinctive test
  // phrase — NOT any default prose — reaches the registered dispatch description
  // BEFORE any agent run is started or any child dispatched. This is the real
  // prompt loader -> core tool-info -> Pi registration path with no stubbing.
  const desc = tools.get('orch_dispatch').description;
  assert.ok(desc.includes(TEST_DELEGATION), 'registered orch_dispatch description includes the controlled delegation text from the loaded prompts.yaml');
  assert.ok(!desc.includes('Delegate by default.'), 'registered description does not pin default delegation prose');

  // Status tool actions reflect core actions array, not an adapter enum.
  const statusActionProp = tools.get('orch_status').parameters.properties.action;
  const actionEnum = statusActionProp.enum ?? statusActionProp.anyOf?.[0]?.enum;
  assert.ok(actionEnum, 'action parameter exposes enum from core actions');
  assert.deepEqual([...actionEnum].sort(), ['doctor', 'help', 'history', 'roles', 'status', 'stop']);

  // /orch command description from core.
  const cmd = commands.get('orch');
  assert.ok(cmd, '/orch command registered');
  assert.ok(typeof cmd.description === 'string' && cmd.description.length > 0, 'command description present');

  // ---- 2: tool dispatch with taskLabel containing spaces, label echoed in ack
  const ctx1 = makeContext('CONN1');
  await hooks.get('session_start')({}, ctx1);
  assert.ok(active.includes('orch_dispatch'), 'session_start activates orch_dispatch');

  const dispatch = tools.get('orch_dispatch');
  const ackA = await dispatch.execute('t1', {
    goal: 'connected goal alpha',
    role: 'plain',
    taskLabel: 'alpha label with spaces',
  }, undefined, undefined, ctx1);
  assert.equal(ackA.isError, false, `labeled tool dispatch must succeed: ${JSON.stringify(ackA)}`);
  const ackAText = text(ackA);
  assert.match(ackAText, /alpha label with spaces/, 'tool-dispatch ack renders the supplied taskLabel verbatim (with spaces)');
  // Ack contains a real run id (32 hex chars), not the run label or goal.
  assert.match(ackAText, /\b[0-9a-f]{32}\b/, 'tool-dispatch ack contains a real run id from core');
  // No generic fallback substitutions.
  assert.ok(!/default role/i.test(ackAText), 'no "default role" substitution in tool ack');
  extractRunId(ackAText);

  // Wait for the run to settle so its parent-context file is flushed.
  await poll('first dispatch recorded stdin written', () => recordedDispatchStdin().length >= 1);

  // ---- 3: /orch do --task-label with quoted spaces -> live ack includes label
  notifs.length = 0;
  await cmd.handler('do --role plain --task-label "slash label with spaces" connected slash goal', ctx1);
  // Wait for the slash dispatch ack to be emitted via ui.notify.
  let slashOutput = '';
  await poll('slash dispatch ack emitted', () => {
    slashOutput = notifs.join('\n');
    return slashOutput.length > 0;
  });
  assert.match(slashOutput, /slash label with spaces/, '/orch do ack renders the slash-supplied taskLabel verbatim (with spaces)');
  assert.match(slashOutput, /Run:\s+[0-9a-f]{32}/i, '/orch do ack contains a real run id from core');
  extractRunId(slashOutput);

  // ---- 4: unlabeled dispatch still works and produces NO label text
  const ackB = await dispatch.execute('t2', { goal: 'unlabeled goal', role: 'plain' }, undefined, undefined, ctx1);
  assert.equal(ackB.isError, false, `unlabeled tool dispatch must succeed: ${JSON.stringify(ackB)}`);
  const ackBText = text(ackB);
  assert.ok(!/Label:/i.test(ackBText), `unlabeled ack must not render any "Label:" line (got: ${ackBText})`);
  assert.match(ackBText, /\b[0-9a-f]{32}\b/, 'unlabeled ack still contains a real run id');
  // No fabricated label.
  assert.ok(!/task_label/i.test(ackBText), 'unlabeled ack contains no fabricated task_label field');
  extractRunId(ackBText);

  // ---- 5: task label never appears in parent-context stdin or goal field
  await poll('third dispatch recorded stdin', () => recordedDispatchStdin().length >= 3);
  const captures = recordedDispatchStdin();
  // Find the capture corresponding to the labeled tool dispatch.
  const labeledCapture = captures.find((c) => c.args.includes('alpha label with spaces'));
  assert.ok(labeledCapture, 'labeled tool dispatch recorded its core stdin payload');
  // The task label value must NOT appear in the parent-context artifact body.
  assert.ok(!labeledCapture.stdin.includes('alpha label with spaces'),
    'taskLabel value must NOT leak into the parent-context stdin payload sent to core');
  // The goal must appear unchanged (no label prefix).
  assert.ok(labeledCapture.stdin.includes('connected goal alpha'), 'goal preserved in core argv/stdin');
  // No "task_label:" injection marker anywhere in the captured artifact.
  assert.ok(!/^task_label:/m.test(labeledCapture.stdin), 'no "task_label:" line injected into parent-context fallback');
  // Also check slash label doesn't appear in its own parent-context.
  const slashCapture = captures.find((c) => c.args.includes('slash label with spaces'));
  assert.ok(slashCapture, 'slash labeled dispatch recorded its core stdin payload');
  assert.ok(!slashCapture.stdin.includes('slash label with spaces'),
    'slash taskLabel value must NOT leak into parent-context stdin payload');

  // ---- 6: omitted history limit produces no `--limit` argv
  writeFileSync(argvLog, ''); // truncate to isolate this check
  const historyNoLimit = await tools.get('orch_status').execute('t3', { action: 'history' }, undefined, undefined, ctx1);
  assert.equal(historyNoLimit.isError, false, 'history without limit succeeds');
  const historyCall = recordedArgv().find((a) => a.includes('history'));
  assert.ok(historyCall, 'history call recorded');
  assert.ok(!historyCall.includes('--limit'), `adapter must omit --limit when no limit supplied (got argv: ${JSON.stringify(historyCall)})`);

  // Explicit limit IS forwarded.
  writeFileSync(argvLog, '');
  await tools.get('orch_status').execute('t4', { action: 'history', limit: 3 }, undefined, undefined, ctx1);
  const historyWithLimit = recordedArgv().find((a) => a.includes('history'));
  assert.ok(historyWithLimit, 'limited history call recorded');
  const limitIdx = historyWithLimit.indexOf('--limit');
  assert.ok(limitIdx >= 0 && historyWithLimit[limitIdx + 1] === '3', 'explicit limit forwarded as --limit 3');

  // ---- 7: malformed dispatch ack (controlled boundary) -> visible failure
  {
    const malTemp = join(temp, 'malformed-dispatch-bin');
    mkdirSync(malTemp);
    // python3 stub: real tool-info via real python, but dispatch returns a JSON
    // line missing role and ack — the validation in orch_dispatch.execute must
    // fail visibly, never substitute "default role" / "Assignment accepted.".
    writeFileSync(join(malTemp, 'python3'), `#!${process.execPath}
const { spawnSync } = require('node:child_process');
const args = process.argv.slice(2);
if (args.includes('tool-info')) {
  const r = spawnSync(${JSON.stringify(realPython)}, args, { encoding: 'utf8', env: process.env });
  process.stdout.write(r.stdout);
  process.exit(r.status ?? 0);
}
if (args.includes('dispatch')) {
  // Malformed ack: no role, no ack text.
  process.stdout.write(JSON.stringify({ type: 'ack', run_id: 'abc123', jobs: [] }) + '\\n');
  process.exit(0);
}
if (args.includes('initial-mode')) { process.stdout.write('on\\n'); process.exit(0); }
const r = spawnSync(${JSON.stringify(realPython)}, args, { encoding: 'utf8', env: process.env });
process.stdout.write(r.stdout);
process.stderr.write(r.stderr);
process.exit(r.status ?? 0);
`, { mode: 0o755 });

    const savedPath = process.env.PATH;
    process.env.PATH = `${malTemp}:${savedPath}`;
    try {
      const jiti2 = createJiti(import.meta.url);
      const { default: activate2 } = await jiti2.import('../extensions/pi/orchestra/index.ts');
      const tools2 = new Map();
      await activate2({
        on() {},
        registerTool: (t) => tools2.set(t.name, t),
        registerCommand() {},
        registerEntryRenderer() {},
        appendEntry() {},
        getActiveTools: () => [],
        setActiveTools() {},
        sendUserMessage() {},
      });
      const ctx2 = makeContext('MAL1');
      const r = await tools2.get('orch_dispatch').execute('m1', { goal: 'will fail malformed ack', role: 'plain' }, undefined, undefined, ctx2);
      assert.equal(r.isError, true, 'malformed ack (missing role/ack) must surface as isError');
      const shown = text(r);
      // No "default role" or "Assignment accepted." substitution.
      assert.ok(!/default role/i.test(shown), 'malformed ack must not substitute "default role"');
      assert.ok(!/Assignment accepted\./i.test(shown), 'malformed ack must not substitute "Assignment accepted."');
      assert.match(shown, /no (role|acknowledgement)/i, 'malformed ack surfaces the missing-field cause');
    } finally {
      process.env.PATH = savedPath;
    }
  }

  // ---- 8: malformed tool-info JSON registers no tools, surfaces real cause
  {
    const badInfoTemp = join(temp, 'bad-tool-info-bin');
    mkdirSync(badInfoTemp);
    writeFileSync(join(badInfoTemp, 'python3'), `#!${process.execPath}
const args = process.argv.slice(2);
if (args.includes('tool-info')) {
  process.stdout.write('not json {{{');
  process.exit(0);
}
process.exit(0);
`, { mode: 0o755 });
    const savedPath = process.env.PATH;
    process.env.PATH = `${badInfoTemp}:${savedPath}`;
    try {
      const jiti3 = createJiti(import.meta.url);
      const { default: activate3 } = await jiti3.import('../extensions/pi/orchestra/index.ts');
      const tools3 = new Map();
      let threw = false;
      try {
        await activate3({
          on() {},
          registerTool: (t) => tools3.set(t.name, t),
          registerCommand() {},
          registerEntryRenderer() {},
          appendEntry() {},
          getActiveTools: () => [],
          setActiveTools() {},
          sendUserMessage() {},
        });
      } catch (e) {
        threw = true;
        assert.match(String(e), /tool-info|malformed/i, 'malformed tool-info throws with cause');
      }
      assert.ok(threw, 'malformed tool-info must throw');
      assert.equal(tools3.size, 0, 'malformed tool-info registers no tools');
    } finally {
      process.env.PATH = savedPath;
    }
  }

  // ---- 9: removed Pi duplicate semantic checks now relay REAL core validation.
  // Refactor-verification (not fabricated RED): the adapter no longer runs its
  // own blank-goal / limit / run-id pre-checks, so the ACTUAL core error text,
  // an isError tool result, and NO accepted run/job must surface. These inputs
  // were never valid; the change only removed a duplicate adapter-layer
  // rejection that used to mask the core cause.

  // 9a: blank goal alone -> core "non-empty goal" error, isError, no run accepted.
  {
    const blank = await tools.get('orch_dispatch').execute('t9a', { goal: '   ', role: 'plain' }, undefined, undefined, ctx1);
    assert.equal(blank.isError, true, 'blank goal must be an isError tool result');
    const blankText = text(blank);
    assert.match(blankText, /non-empty goal/i, 'blank goal relays the real core goal error');
    assert.ok(!/\b[0-9a-f]{32}\b/.test(blankText), 'blank goal must not report an accepted run id');
    assert.ok(!/Assignment accepted\./i.test(blankText), 'blank goal must not fake an acknowledgement');
  }

  // 9b: blank goal WITH additionalContext -> the context append must NOT rescue
  // an empty primary goal (the append is now guarded by a non-empty goal), so
  // core still rejects at the empty goal.
  {
    const blankCtx = await tools.get('orch_dispatch').execute('t9b', {
      goal: '',
      additionalContext: 'context that must not substitute for a goal',
      role: 'plain',
    }, undefined, undefined, ctx1);
    assert.equal(blankCtx.isError, true, 'blank goal + context must be an isError tool result');
    const btext = text(blankCtx);
    assert.match(btext, /non-empty goal/i, 'blank goal + context still relays the real core goal error');
    assert.ok(!/\b[0-9a-f]{32}\b/.test(btext), 'blank goal + context must not report an accepted run id');
    assert.ok(!/Assignment accepted\./i.test(btext), 'blank goal + context must not fake an acknowledgement');
  }

  // 9c: history limit 0 / -1 / fractional -> real core positivity/type errors.
  for (const bad of [
    { limit: 0, re: /positive integer/i },
    { limit: -1, re: /positive integer/i },
    { limit: 2.5, re: /invalid int value/i },
  ]) {
    const badHistory = await tools.get('orch_status').execute(`t9c-${bad.limit}`, { action: 'history', limit: bad.limit }, undefined, undefined, ctx1);
    assert.equal(badHistory.isError, true, `history limit ${bad.limit} must be an isError tool result`);
    assert.match(text(badHistory), bad.re, `history limit ${bad.limit} relays the real core limit error`);
  }

  // 9d: stop with a missing runId -> real core missing-argument error.
  {
    const stopNoId = await tools.get('orch_status').execute('t9d', { action: 'stop' }, undefined, undefined, ctx1);
    assert.equal(stopNoId.isError, true, 'stop without runId must be an isError tool result');
    assert.match(text(stopNoId), /required.*--run-id|--run-id.*required/i, 'stop relays the real core missing-run-id error');
  }

  // ---- success proof: delivery + persisted terminal end-state --------------
  // Every run this test dispatched under its own session must be DELIVERED to
  // real core execution (active) before cleanup. The finally block then drives
  // these same own runs to a persisted terminal end-state via the real core.
  await waitForCompletedEndState();

  console.log('Pi connected integration passed');
} finally {
  // Owner-scoped teardown: stop ONLY this test's own dispatched runs that are
  // still active (e.g. an ack assertion threw mid-flight), then wait bounded
  // for them to reach a persisted terminal end-state in the real core before
  // removing the temp dir. No global kill, no live host, no other session's runs.
  await teardownOwnRuns();
  // The real Python supervisor may briefly hold files; retry cleanup.
  for (let i = 0; i < 20; i += 1) {
    try { rmSync(temp, { recursive: true, force: true }); break; } catch { await new Promise((r) => setTimeout(r, 200)); }
  }
}
