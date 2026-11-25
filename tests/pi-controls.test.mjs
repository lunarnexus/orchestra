import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, copyFileSync, mkdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createJiti } from 'jiti';

// Exercise the real extension's management surface against the real Orchestra 2
// core CLI and SQLite queue: one read-only `orch_status` tool (status, history,
// stop, help, doctor, roles), run/job identifiers in the dispatch
// acknowledgement, session-owned cancellation, session isolation, and on/off
// tool activation. Controlled boundaries only: the host-side `python3` is a
// pass-through stub and the `pi` RPC binary is a scripted fake. No live Pi
// sessions, global installs, or models are involved.
const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const temp = mkdtempSync(join(tmpdir(), 'orchestra-controls-'));
const sessionDir = join(temp, 'pi-sessions');
mkdirSync(sessionDir);
mkdirSync(join(temp, 'state'), { recursive: true });
mkdirSync(join(temp, 'logs'), { recursive: true });

// Resolve the real interpreter BEFORE the stub shadows `python3` on PATH.
const realPython = spawnSync('python3', ['-c', 'import sys;print(sys.executable)'], { encoding: 'utf8' }).stdout.trim();
assert.ok(realPython, 'a real python3 interpreter is required');

// --- controlled boundaries -------------------------------------------------
// Pass-through python3: forwards to the real orchestra module unchanged.
writeFileSync(join(temp, 'python3'), `#!${process.execPath}
const { spawn } = require('node:child_process');
const child = spawn(${JSON.stringify(realPython)}, process.argv.slice(2), { stdio: 'inherit', env: process.env });
child.on('error', (e) => { process.stderr.write(String(e)); process.exit(1); });
child.on('exit', (c) => process.exit(c ?? 1));
`, { mode: 0o755 });

// Fake pi RPC binary: accepts the prompt, settles after an optional delay, and
// answers get_last_assistant_text from the scenario file.
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
      send({ id: 'prompt-1', type: 'response', success: true });
      send({ type: 'agent_settled', aborted: false });
    }, (entry && entry.delayMs) || 0);
  } else if (msg.type === 'get_last_assistant_text') {
    const entry = entryFor(lastPrompt);
    send({ id: msg.id, type: 'response', command: 'get_last_assistant_text', data: { text: (entry && entry.text) || 'unscripted answer' } });
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
const catalogPath = join(configDir, 'agent-catalog.yaml');
writeFileSync(catalogPath, `default_role: builder
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

/** Structured core status for a session, read through the real CLI. */
function statusPayload(sessionId) {
  const result = spawnSync(join(temp, 'python3'), ['-m', 'orchestra', 'status', '--session-id', sessionId, '--mode', 'on'], { encoding: 'utf8' });
  if (result.status !== 0) throw new Error(`status failed: ${result.stderr}`);
  return JSON.parse(result.stdout).data;
}

function activeJobs(sessionId) {
  return statusPayload(sessionId).session_jobs;
}

const HOST = 'pi:';
const text = (result) => (result.content ?? []).map((part) => part.text ?? '').join('\n');

try {
  const jiti = createJiti(import.meta.url);
  const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');
  const hooks = new Map();
  const tools = new Map();
  const commands = new Map();
  const steers = [];
  const entries = [];
  let active = [];
  let footer = '';
  activate({
    on: (name, handler) => hooks.set(name, handler),
    registerTool: (tool) => tools.set(tool.name, tool),
    registerCommand: (name, definition) => commands.set(name, definition),
    registerEntryRenderer() {},
    appendEntry: (type, data) => entries.push({ type, data }),
    getActiveTools: () => [...active],
    setActiveTools: (value) => { active = [...value]; },
    sendUserMessage: (message) => steers.push(String(message)),
  });
  assert.ok(tools.has('orch_dispatch'), 'orch_dispatch tool must be registered');
  assert.ok(tools.has('orch_status'), 'orch_status management tool must be registered');

  // The model-facing management tool stays read-only: no mutation parameters.
  const statusTool = tools.get('orch_status');
  const properties = statusTool.parameters?.properties ?? {};
  for (const banned of ['setting', 'value', 'mode', 'role']) {
    assert.ok(!(banned in properties), `orch_status must stay read-only: no ${banned} parameter`);
  }

  function makeContext(sessionId) {
    return {
      hasUI: true,
      sessionManager: {
        getSessionId: () => sessionId,
        buildContextEntries: () => [],
        getBranch: () => [],
      },
      ui: { theme: { fg: (_c, t) => t, bold: (t) => t }, setWidget: (_n, value) => { footer = value ? value.join('\n') : ''; }, notify() {} },
    };
  }

  const ctx1 = makeContext('C1');
  await hooks.get('session_start')({}, ctx1);
  assert.ok(active.includes('orch_dispatch'), 'session start activates orch_dispatch');
  assert.ok(active.includes('orch_status'), 'session start activates orch_status');

  // --- 1: the dispatch acknowledgement exposes run and job identifiers ----
  setScenario([{ match: 'slow one', text: 'slow one answer', delayMs: 2500 }, { match: '*', text: 'unused' }]);
  const ack1 = await tools.get('orch_dispatch').execute('c1', { goal: 'slow one', role: 'plain' }, undefined, undefined, ctx1);
  assert.equal(ack1.isError, false, `dispatch ack failed: ${JSON.stringify(ack1)}`);
  const ackText = text(ack1);
  const runIds = ackText.match(/\b[0-9a-f]{32}\b/g) ?? [];
  assert.ok(runIds.length > 0, `dispatch acknowledgement must expose the run id (got: ${ackText})`);
  const runId = runIds[0];
  assert.ok(ackText.includes(`${runId}:1`), 'dispatch acknowledgement must expose the job id');
  // Lifecycle-driven footer refresh stays intact: the dispatch stream's own
  // transitions update the role meter without any manual status command.
  await poll('footer shows the dispatched role', () => /plain/i.test(footer));

  // --- 2: the status action is readable session status, not raw JSON ------
  const statusResult = await statusTool.execute('c2', { action: 'status' }, undefined, undefined, ctx1);
  assert.equal(statusResult.isError, false, `status action failed: ${JSON.stringify(statusResult)}`);
  const statusText = text(statusResult);
  assert.ok(!statusText.trimStart().startsWith('{'), 'status must be readable text, not a raw JSON envelope');
  assert.match(statusText, /this session/i, 'status names the current session');
  assert.match(statusText, /plain/, 'the running job role appears in status');

  // --- 3: owned cancellation reaches a persisted terminal state -----------
  const stopResult = await statusTool.execute('c3', { action: 'stop', runId }, undefined, undefined, ctx1);
  assert.equal(stopResult.isError, false, `owned stop must succeed: ${JSON.stringify(stopResult)}`);
  assert.match(text(stopResult), /stopped/i, 'stop reports the outcome');
  await poll('stopped run terminal', () => activeJobs(HOST + 'C1').length === 0);
  const afterStop = statusPayload(HOST + 'C1').last_completed;
  assert.equal(afterStop?.run_id, runId, 'the stopped run is the last completed run');
  assert.equal(afterStop?.failed, 1, 'cancellation is persisted as a failed job');
  assert.equal(afterStop?.succeeded, 0, 'a stopped run records no success');
  await poll('footer clears after the stopped run drains', () => !/plain/i.test(footer));

  // --- 4: another session cannot cancel this session's run ----------------
  setScenario([{ match: 'slow two', text: 'slow two answer', delayMs: 2500 }, { match: '*', text: 'unused' }]);
  const ack2 = await tools.get('orch_dispatch').execute('c4', { goal: 'slow two', role: 'plain' }, undefined, undefined, ctx1);
  assert.equal(ack2.isError, false, `second dispatch ack failed: ${JSON.stringify(ack2)}`);
  const runId2 = (text(ack2).match(/\b[0-9a-f]{32}\b/g) ?? [])[0];
  assert.ok(runId2, 'the second acknowledgement exposes its run id');
  const foreign = await statusTool.execute('c5', { action: 'stop', runId: runId2 }, undefined, undefined, makeContext('C9'));
  assert.equal(foreign.isError, true, 'a foreign session must not cancel another session run');
  assert.match(text(foreign), /own/i, 'the rejection explains session ownership');
  // The un-cancelled run keeps running and finishes honestly.
  await poll('un-cancelled run terminal', () => activeJobs(HOST + 'C1').length === 0);
  const afterForeign = statusPayload(HOST + 'C1').last_completed;
  assert.equal(afterForeign?.run_id, runId2, 'the untouched run is the last completed run');
  assert.equal(afterForeign?.succeeded, 1, 'the un-cancelled run still succeeds');

  // --- 5: history honours a positive limit --------------------------------
  const history = await statusTool.execute('c6', { action: 'history', limit: 1 }, undefined, undefined, ctx1);
  assert.equal(history.isError, false, `history action failed: ${JSON.stringify(history)}`);
  const historyText = text(history);
  assert.ok(historyText.includes(runId2), 'history lists the newest completed run');
  assert.ok(!historyText.includes(runId), 'history respects the requested limit');
  const badLimit = await statusTool.execute('c7', { action: 'history', limit: 0 }, undefined, undefined, ctx1);
  assert.equal(badLimit.isError, true, 'history limit must be a positive integer');
  const badStop = await statusTool.execute('c8', { action: 'stop' }, undefined, undefined, ctx1);
  assert.equal(badStop.isError, true, 'stop requires a run id');

  // --- 6: read-only role listing ------------------------------------------
  const catalogBefore = readFileSync(catalogPath, 'utf8');
  const roles = await statusTool.execute('c9', { action: 'roles' }, undefined, undefined, ctx1);
  assert.equal(roles.isError, false, `roles action failed: ${JSON.stringify(roles)}`);
  const rolesText = text(roles);
  for (const role of ['builder', 'verifier', 'plain']) {
    assert.ok(rolesText.includes(role), `role listing includes ${role}`);
  }
  assert.match(rolesText, /default/i, 'role listing reports the default role');
  assert.equal(readFileSync(catalogPath, 'utf8'), catalogBefore, 'role listing never mutates the catalog');

  // --- 7: help and diagnostics through the same tool ----------------------
  const help = await statusTool.execute('c10', { action: 'help' }, undefined, undefined, ctx1);
  assert.equal(help.isError, false, `help action failed: ${JSON.stringify(help)}`);
  assert.match(text(help), /dispatch/i, 'help describes the operations');
  const doctor = await statusTool.execute('c11', { action: 'doctor' }, undefined, undefined, ctx1);
  assert.equal(doctor.isError, false, `doctor action failed: ${JSON.stringify(doctor)}`);
  assert.match(text(doctor), /doctor: all checks passed/, 'doctor reports the real core diagnostics');

  // --- 8: /orch on|off activation covers both tools -----------------------
  const command = commands.get('orch');
  assert.ok(command, 'the /orch command must be registered');
  await command.handler('off', ctx1);
  assert.ok(!active.includes('orch_dispatch') && !active.includes('orch_status'), '/orch off deactivates both tools');
  await command.handler('on', ctx1);
  assert.ok(active.includes('orch_dispatch') && active.includes('orch_status'), '/orch on activates both tools');

  // --- 9: /orch status renders readable text, not the JSON envelope -------
  entries.length = 0;
  await command.handler('status', ctx1);
  const shown = entries.filter((entry) => entry.type === 'orchestra-output').map((entry) => entry.data?.text ?? '').join('\n');
  assert.ok(shown.length > 0, '/orch status must produce output');
  assert.ok(!shown.trimStart().startsWith('{'), '/orch status must render readable text, not raw JSON');
  assert.match(shown, /this session/i, 'the rendered core status is what the user sees');
  assert.doesNotMatch(shown, /"session_jobs"/, 'structured status fields stay out of user output');

  // Nothing dispatched here may leak a return into another session.
  await poll('session returns delivered', () => steers.length >= 2);

  console.log('Pi connected controls passed');
} finally {
  rmSync(temp, { recursive: true, force: true });
}
