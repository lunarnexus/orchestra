import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createJiti } from 'jiti';

// Thin Pi-adapter boundary contract. A single controllable fake `python3` is
// driven through environment variables so each scenario can script the exact
// core ack line / command output the adapter receives, and record the argv the
// adapter forwarded. Proves the adapter-side contract the diff review flagged:
//   - malformed dispatch acknowledgements are rejected once, BEFORE tracking:
//     no success notification and no run tracking (no delivered return).
//   - a supplied taskLabel is forwarded literally (empty and untrimmed values
//     included); only an absent label omits the flag.
//   - core command failures relay stderr, then stdout, else the exit code — no
//     generic status/history/stop substitutions; an invalid action surfaces the
//     real core argparse cause, not an adapter "Unknown orchestra action".
//   - a session-return with no assembled return is a protocol error, not a
//     generic/empty outcome.
//   - the slash parser strips only paired double quotes; a literal trailing
//     apostrophe (O'Connor') is preserved.
// Controlled boundaries only: no real core, no models, no live Pi, no install.
const temp = mkdtempSync(join(tmpdir(), 'orchestra-adapter-contract-'));
const argvPath = join(temp, 'argv.log');
writeFileSync(argvPath, '');

const TOOL_INFO = {
  dispatch: { label: 'D', description: 'Submit.', params: { goal: 'g.', additionalContext: 'c.', role: 'r.', taskLabel: 'l.' } },
  status: { label: 'S', description: 'Manage.', params: { action: 'a.', limit: 'n.', runId: 'i.' } },
  command: { description: '/orch' },
  actions: ['status', 'history', 'stop', 'help', 'doctor', 'roles'],
};

// The ack used when a scenario does not override ORCH_ACK: a fully valid ack.
const VALID_ACK = { type: 'ack', run_id: 'a'.repeat(32), role: 'plain', ack: 'Accepted.', jobs: [{ job_id: 'a:1', worker_session_id: 'w1' }] };

writeFileSync(join(temp, 'python3'), `#!${process.execPath}\n` + [
  `const fs = require('node:fs');`,
  `const args = process.argv.slice(2);`,
  `const ARGV = process.env.ORCH_ARGV;`,
  `if (ARGV) { try { fs.appendFileSync(ARGV, JSON.stringify(args) + '\\n'); } catch (e) {} }`,
  `if (args.includes('tool-info')) { process.stdout.write(${JSON.stringify(JSON.stringify(TOOL_INFO))}); process.exit(0); }`,
  `if (args.includes('initial-mode')) { process.stdout.write('on'); process.exit(0); }`,
  `if (args.includes('dispatch')) {`,
  `  const ack = process.env.ORCH_ACK || ${JSON.stringify(JSON.stringify(VALID_ACK))};`,
  `  process.stdout.write(ack + '\\n');`,
  `  if (process.env.ORCH_RETURN) process.stdout.write(process.env.ORCH_RETURN + '\\n');`,
  `  process.exit(0);`,
  `}`,
  `{`,
  `  const code = parseInt(process.env.ORCH_CMD_CODE || '0', 10) || 0;`,
  `  if (process.env.ORCH_CMD_STDERR) process.stderr.write(process.env.ORCH_CMD_STDERR);`,
  `  if (process.env.ORCH_CMD_STDOUT) process.stdout.write(process.env.ORCH_CMD_STDOUT);`,
  `  process.exit(code);`,
  `}`,
].join('\n'), { mode: 0o755 });

process.env.PATH = `${temp}:${process.env.PATH}`;
process.env.ORCHESTRA_CONFIG = temp;

function mkCtx(sessionId, notes) {
  return {
    hasUI: true,
    sessionManager: { getSessionId: () => sessionId, buildContextEntries: () => [], getBranch: () => [] },
    ui: {
      theme: { fg: (_c, t) => t, bold: (t) => t },
      setWidget() {},
      notify: (msg) => { if (notes) notes.push(String(msg)); },
    },
  };
}

const text = (result) => (result.content ?? []).map((p) => p.text ?? '').join('\n');
function lastDispatchArgv() {
  const lines = readFileSync(argvPath, 'utf8').split('\n').filter((l) => l.length > 0).map((l) => JSON.parse(l));
  return [...lines].reverse().find((a) => a.includes('dispatch')) ?? [];
}
async function waitFor(label, fn, timeoutMs = 4000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (fn()) return;
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${label}`);
    await new Promise((r) => setTimeout(r, 25));
  }
}

try {
  const jiti = createJiti(import.meta.url);
  const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');
  const tools = new Map();
  const commands = new Map();
  const steers = [];
  await activate({
    on() {},
    registerTool: (t) => tools.set(t.name, t),
    registerCommand: (name, def) => commands.set(name, def),
    registerEntryRenderer() {},
    appendEntry() {},
    getActiveTools: () => [...tools.keys()],
    setActiveTools() {},
    sendUserMessage: (m) => steers.push(String(m)),
  });
  const dispatch = tools.get('orch_dispatch');
  const status = tools.get('orch_status');
  const command = commands.get('orch');
  assert.ok(dispatch && status && command, 'tools and command registered');

  // ---- 2: malformed acknowledgements are rejected once, before tracking ----
  const badAcks = [
    ['missing type', { run_id: 'r', role: 'plain', ack: 'ok', jobs: [] }],
    ['wrong type', { type: 'return', run_id: 'r', role: 'plain', ack: 'ok', jobs: [] }],
    ['empty run id', { type: 'ack', run_id: '', role: 'plain', ack: 'ok', jobs: [] }],
    ['empty role', { type: 'ack', run_id: 'r', role: '', ack: 'ok', jobs: [] }],
    ['empty ack text', { type: 'ack', run_id: 'r', role: 'plain', ack: '', jobs: [] }],
    ['jobs not array', { type: 'ack', run_id: 'r', role: 'plain', ack: 'ok', jobs: 'nope' }],
    ['null job entry', { type: 'ack', run_id: 'r', role: 'plain', ack: 'ok', jobs: [null] }],
    ['non-object job entry', { type: 'ack', run_id: 'r', role: 'plain', ack: 'ok', jobs: [42] }],
    ['job without id', { type: 'ack', run_id: 'r', role: 'plain', ack: 'ok', jobs: [{ worker_session_id: 'w' }] }],
  ];
  for (let i = 0; i < badAcks.length; i += 1) {
    const [label, ack] = badAcks[i];
    process.env.ORCH_ACK = JSON.stringify(ack);
    delete process.env.ORCH_RETURN;
    const notes = [];
    const before = steers.length;
    const r = await dispatch.execute(`m${i}`, { goal: 'x', role: 'plain' }, undefined, undefined, mkCtx(`MAL-${i}`, notes));
    assert.equal(r.isError, true, `${label}: malformed ack must be isError`);
    assert.match(text(r), /malformed acknowledgement/, `${label}: surfaces the malformed-ack cause`);
    assert.ok(!/default role|Assignment accepted/i.test(text(r)), `${label}: no fallback substitution`);
    assert.ok(!notes.some((n) => /dispatched/i.test(n)), `${label}: no success notification`);
    assert.equal(steers.length, before, `${label}: malformed ack not tracked, no return delivered`);
  }
  delete process.env.ORCH_ACK;

  // ---- 3: taskLabel forwarded literally; absent label omitted --------------
  writeFileSync(argvPath, '');
  process.env.ORCH_ARGV = argvPath;

  await dispatch.execute('p1', { goal: 'g', role: 'plain', taskLabel: '  pad label  ' }, undefined, undefined, mkCtx('P1', []));
  let argv = lastDispatchArgv();
  let ti = argv.indexOf('--task-label');
  assert.ok(ti >= 0 && argv[ti + 1] === '  pad label  ', `untrimmed label forwarded literally (got ${JSON.stringify(argv[ti + 1])})`);

  await dispatch.execute('p2', { goal: 'g', role: 'plain', taskLabel: '' }, undefined, undefined, mkCtx('P2', []));
  argv = lastDispatchArgv();
  ti = argv.indexOf('--task-label');
  assert.ok(ti >= 0 && argv[ti + 1] === '', `empty label still forwarded (--task-label "")`);

  await dispatch.execute('p3', { goal: 'g' }, undefined, undefined, mkCtx('P3', []));
  argv = lastDispatchArgv();
  assert.ok(!argv.includes('--task-label'), 'absent label omits --task-label');
  assert.ok(!argv.includes('--role'), 'absent role omits --role');

  // ---- 6: slash parser strips only paired double quotes --------------------
  writeFileSync(argvPath, '');
  command.handler(`do --task-label "a b" goal O'Connor'`, mkCtx('U1', []));
  await waitFor('slash dispatch', () => lastDispatchArgv().includes('--task-label'));
  argv = lastDispatchArgv();
  ti = argv.indexOf('--task-label');
  assert.equal(argv[ti + 1], 'a b', 'paired double quotes stripped from --task-label');
  const gi = argv.indexOf('--goal');
  assert.equal(argv[gi + 1], `goal O'Connor'`, `literal trailing apostrophe preserved in goal (got ${JSON.stringify(argv[gi + 1])})`);

  writeFileSync(argvPath, '');
  command.handler(`do "O'Connor' only" more`, mkCtx('U2', []));
  await waitFor('slash dispatch 2', () => lastDispatchArgv().length > 0);
  argv = lastDispatchArgv();
  const gi2 = argv.indexOf('--goal');
  assert.equal(argv[gi2 + 1], `O'Connor' only more`, `double-quoted token keeps an inner/trailing apostrophe when unquoted`);

  // ---- 4: core failure relay (stderr > stdout > exit code) -----------------
  process.env.ORCH_CMD_CODE = '2';
  process.env.ORCH_CMD_STDERR = 'argparse: history rejected';
  process.env.ORCH_CMD_STDOUT = 'ignored stdout';
  let h = await status.execute('h1', { action: 'history' }, undefined, undefined, mkCtx('H1', []));
  assert.equal(h.isError, true, 'history failure is isError');
  assert.equal(text(h), 'argparse: history rejected', 'history relays stderr with priority');
  assert.ok(!/orchestra history failed/i.test(text(h)), 'no generic history substitution');

  delete process.env.ORCH_CMD_STDERR;
  process.env.ORCH_CMD_CODE = '1';
  process.env.ORCH_CMD_STDOUT = 'only stdout detail';
  h = await status.execute('h2', { action: 'history' }, undefined, undefined, mkCtx('H2', []));
  assert.equal(text(h), 'only stdout detail', 'history falls back to stdout when no stderr');

  delete process.env.ORCH_CMD_STDOUT;
  process.env.ORCH_CMD_CODE = '7';
  h = await status.execute('h3', { action: 'history' }, undefined, undefined, mkCtx('H3', []));
  assert.equal(text(h), 'orchestra command failed with exit code 7.', 'exit-code-only when no output detail');

  // status action relays the real cause, not "orchestra status failed:".
  process.env.ORCH_CMD_CODE = '1';
  process.env.ORCH_CMD_STDERR = 'status: sqlite3 unable to open';
  const sFail = await status.execute('s1', { action: 'status' }, undefined, undefined, mkCtx('S1', []));
  assert.equal(sFail.isError, true, 'status failure is isError');
  assert.match(text(sFail), /sqlite3 unable to open/, 'status relays the real core cause');
  assert.ok(!/orchestra status failed/i.test(text(sFail)), 'no "orchestra status failed" substitution');

  // stop relays the real cause.
  process.env.ORCH_CMD_CODE = '2';
  process.env.ORCH_CMD_STDERR = 'stop: run not owned by this session';
  const stopFail = await status.execute('t1', { action: 'stop', runId: 'deadbeef' }, undefined, undefined, mkCtx('T1', []));
  assert.match(text(stopFail), /not owned by this session/, 'stop relays the real core cause');
  assert.ok(!/orchestra stop failed/i.test(text(stopFail)), 'no "orchestra stop failed" substitution');

  // An invalid action relays the core argparse cause, not an adapter duplicate.
  process.env.ORCH_CMD_CODE = '2';
  process.env.ORCH_CMD_STDERR = "usage: orchestra [-h] ... invalid choice: 'bogus'";
  const badAction = await status.execute('a1', { action: 'bogus' }, undefined, undefined, mkCtx('A1', []));
  assert.equal(badAction.isError, true, 'invalid action is isError');
  assert.match(text(badAction), /invalid choice/, 'invalid action relays the core argparse cause');
  assert.ok(!/Unknown orchestra action/i.test(text(badAction)), 'no adapter "Unknown orchestra action" duplicate');

  // ---- 5: no assembled return is a protocol error, not a generic outcome ---
  delete process.env.ORCH_CMD_STDERR;
  process.env.ORCH_CMD_STDOUT = '{}'; // session-return succeeds but has no "return" field
  process.env.ORCH_CMD_CODE = '0';
  process.env.ORCH_RETURN = JSON.stringify({ type: 'return', run_id: 'a'.repeat(32) });
  const notes5 = [];
  const steerBefore = steers.length;
  const ack5 = await dispatch.execute('r1', { goal: 'g', role: 'plain' }, undefined, undefined, mkCtx('R1', notes5));
  assert.equal(ack5.isError, false, 'a valid ack is still accepted');
  await waitFor('protocol-error notification', () => notes5.some((n) => /protocol|malformed/i.test(n)));
  assert.ok(notes5.some((n) => /protocol|malformed/i.test(n)), 'protocol error surfaced');
  assert.equal(steers.length, steerBefore, 'no successful/empty return is delivered for malformed output');

  console.log('Pi adapter boundary contract passed');
} finally {
  rmSync(temp, { recursive: true, force: true });
}
