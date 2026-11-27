import assert from 'node:assert/strict';
import { createJiti } from 'jiti';
import { makeSessionStub, makeCtx } from './helpers/orchestra-session-stub.mjs';

// Thin Pi-adapter translator contract over the persistent core `__session`.
// Raw dispatch-ack JSON (run_id/jobs/role/ack policy) is now produced and
// validated inside core and never crosses this boundary; the adapter only turns
// correlated reply frames into tool results and answers core-initiated native
// requests. Asserted here, at the boundary the adapter actually owns:
//   - a reply whose result is not core-owned text (missing/non-string result, or
//     a reply frame carrying neither result nor error) is a visible protocol
//     error — never an accepted tool success and never a fallback substitution;
//   - core error replies are relayed verbatim (history/status/stop and an
//     invalid action), with no generic adapter substitutions;
//   - dispatch forwards the public fields as exact request wire values: a padded
//     or empty taskLabel is forwarded literally, only an absent label/role is
//     omitted;
//   - the slash parser strips only paired double quotes; a literal trailing
//     apostrophe (O'Connor') is preserved;
//   - a core-initiated deliver_report with string text steers the host, while
//     one WITHOUT a string text is rejected and delivers no steer (a missing
//     report is a protocol rejection, not a silent success).
// Controlled core `__session` stub only: no real Python core, models, live Pi,
// or install.
const NATIVE = 'adapter-contract';
const stub = makeSessionStub({ reply: {} });

const scenario = (extra) => ({
  'initial-mode': { result: { mode: 'on', text: 'Orchestra active.' } },
  dispatch: { result: { text: 'Assignment accepted. Run abcdef0123456789abcdef0123456789.' } },
  ...extra,
});
stub.setScenario(scenario());

const text = (result) => (result.content ?? []).map((p) => p.text ?? '').join('\n');
async function waitFor(label, fn, timeoutMs = 4000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (fn()) return;
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${label}`);
    await new Promise((r) => setTimeout(r, 25));
  }
}

const hooks = new Map();
const tools = new Map();
const commands = new Map();
const steers = [];
let ctx;

try {
  const jiti = createJiti(import.meta.url);
  const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');
  await activate({
    on: (name, handler) => hooks.set(name, handler),
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

  // Establish the persistent core `__session` connection for the SAME native id
  // every tool/command below uses, so the adapter owns the live connection.
  ctx = makeCtx(NATIVE);
  await hooks.get('session_start')({}, ctx);

  // ---- transport: a reply without a core-owned result.text is never success --
  // These are reply-frame malformations AT THIS BOUNDARY (not the raw ack JSON
  // schema, which is core-internal): the adapter must reject each visibly, with
  // no fallback text and no delivered report/steer.
  const badResults = [
    ['empty result object', { result: {} }],
    ['non-string scalar result', { result: 42 }],
    ['nested object without text', { result: { status: 'ok' } }],
  ];
  for (let i = 0; i < badResults.length; i += 1) {
    const [label, frame] = badResults[i];
    stub.setScenario(scenario({ dispatch: frame }));
    const before = steers.length;
    const r = await dispatch.execute(`m${i}`, { goal: 'x', role: 'builder' }, undefined, undefined, ctx);
    assert.equal(r.isError, true, `${label}: malformed result.text must be isError`);
    assert.match(text(r), /result\.text is missing/, `${label}: surfaces the malformed result.text cause`);
    assert.ok(!/default role|Assignment accepted/i.test(text(r)), `${label}: no fallback substitution`);
    assert.equal(steers.length, before, `${label}: a malformed result delivers no report/steer`);
  }

  // A reply frame carrying neither result nor error is a reply-contract
  // violation surfaced as its actual protocol cause, not an empty success.
  {
    stub.setScenario(scenario({ dispatch: { contractViolation: true } }));
    const r = await dispatch.execute('nc', { goal: 'x', role: 'builder' }, undefined, undefined, ctx);
    assert.equal(r.isError, true, 'a reply with neither result nor error is isError');
    assert.match(text(r), /reply contract|result or error/i, 'the reply-contract violation is surfaced');
  }

  // ---- core errors relay the actual cause, no generic substitute -------------
  const relayCases = [
    { op: 'history', args: { action: 'history' }, error: 'argparse error: --limit must be >= 0', absent: /orchestra history failed/i },
    { op: 'status', args: { action: 'status' }, error: 'status: sqlite3.OperationalError: unable to open database file', absent: /orchestra status failed/i },
    { op: 'stop', args: { action: 'stop', runId: 'deadbeef' }, error: 'stop: run not owned by this session', absent: /orchestra stop failed/i },
  ];
  for (const c of relayCases) {
    stub.setScenario(scenario({ [c.op]: { error: c.error } }));
    const r = await status.execute('relay', c.args, undefined, undefined, ctx);
    assert.equal(r.isError, true, `${c.op} failure is isError`);
    assert.equal(text(r), c.error, `${c.op} relays the actual core cause verbatim`);
    assert.ok(!c.absent.test(text(r)), `${c.op} is not replaced with a generic adapter message`);
  }

  // An invalid action is forwarded to core; the real argparse cause is relayed,
  // never an adapter-side "Unknown orchestra action" duplicate.
  {
    stub.setScenario(scenario({ bogus: { error: "usage: orchestra [-h] {status,history,stop,help,doctor,roles}: invalid choice: 'bogus'" } }));
    const badAction = await status.execute('a1', { action: 'bogus' }, undefined, undefined, ctx);
    assert.equal(badAction.isError, true, 'an invalid action is isError');
    assert.match(text(badAction), /invalid choice/, 'an invalid action relays the core argparse cause');
    assert.ok(!/Unknown orchestra action/i.test(text(badAction)), 'no adapter "Unknown orchestra action" duplicate');
  }

  // ---- dispatch forwards public fields as exact request wire values ----------
  // Raw CLI argv forwarding (`--task-label ...`) is now a core-producer concern;
  // the translator contract is that the request arguments carry the values
  // exactly: padded/empty labels literal, only an absent label/role omitted.
  stub.setScenario(scenario());

  await dispatch.execute('p1', { goal: 'g', role: 'builder', taskLabel: '  pad label  ' }, undefined, undefined, ctx);
  let args = stub.request('dispatch').arguments;
  assert.equal(args.taskLabel, '  pad label  ', 'untrimmed label forwarded literally');
  assert.equal(args.goal, 'g', 'goal forwarded');
  assert.equal(args.role, 'builder', 'role forwarded');

  await dispatch.execute('p2', { goal: 'g', role: 'builder', taskLabel: '' }, undefined, undefined, ctx);
  args = stub.request('dispatch').arguments;
  assert.ok('taskLabel' in args, 'an empty label keeps the taskLabel key present');
  assert.equal(args.taskLabel, '', 'an empty label is forwarded as an empty string');

  await dispatch.execute('p3', { goal: 'g' }, undefined, undefined, ctx);
  args = stub.request('dispatch').arguments;
  assert.ok(!('taskLabel' in args), 'an absent label omits taskLabel');
  assert.ok(!('role' in args), 'an absent role omits role');

  // ---- slash parser: strip only paired double quotes; keep literal apostrophe --
  stub.setScenario(scenario());
  await command.handler(`do --task-label "a b" goal O'Connor'`, ctx);
  args = stub.request('dispatch').arguments;
  assert.equal(args.taskLabel, 'a b', 'paired double quotes stripped from --task-label');
  assert.equal(args.goal, `goal O'Connor'`, `literal trailing apostrophe preserved in the goal`);

  await command.handler(`do "O'Connor' only" more`, ctx);
  args = stub.request('dispatch').arguments;
  assert.equal(args.goal, `O'Connor' only more`, `a double-quoted token keeps an inner/trailing apostrophe when unquoted`);

  // ---- deliver_report: string text steers; missing text rejected, no steer ----
  stub.setScenario(scenario({ emitDeliverReport: 'REPORT BODY delivered' }));
  let before = steers.length;
  const okAck = await dispatch.execute('d-ok', { goal: 'x', role: 'builder' }, undefined, undefined, ctx);
  assert.equal(okAck.isError, false, 'a valid dispatch ack is accepted');
  await waitFor('accepted deliver_report', () => stub.nativeResults().some((r) => r.id === 'deliver-1' && r.accepted === true));
  assert.equal(steers.length, before + 1, 'a deliver_report with string text is steered to the host');
  assert.equal(steers[steers.length - 1], 'REPORT BODY delivered', 'the delivered report text is the host steer');

  // A non-string text reaches the same guard as a missing one: it is rejected
  // with the missing-text cause and delivers no steer (never a silent success).
  stub.setScenario(scenario({ emitDeliverReport: 404 }));
  before = steers.length;
  await dispatch.execute('d-bad', { goal: 'x', role: 'builder' }, undefined, undefined, ctx);
  await waitFor('rejected deliver_report', () => stub.nativeResults().some((r) => r.id === 'deliver-1' && r.accepted === false));
  const rejected = stub.nativeResults().filter((r) => r.id === 'deliver-1').pop();
  assert.match(String(rejected.error), /text argument/, 'a deliver_report without string text is rejected with the missing-text cause');
  assert.equal(steers.length, before, 'a rejected deliver_report delivers no steer');

  console.log('Pi adapter boundary contract passed');
} finally {
  // Always shut the persistent connection down (kills the core `__session`
  // subprocess) before removing the temp owner dir, so the Node process exits
  // whether or not an assertion threw.
  try {
    if (hooks.has('session_shutdown') && ctx) hooks.get('session_shutdown')({}, ctx);
  } finally {
    stub.cleanup();
  }
}
