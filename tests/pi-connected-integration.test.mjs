import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { writeFileSync, mkdirSync, rmSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createJiti } from 'jiti';
import { createLiveCoreHost, makeContext, text } from './helpers/pi-live-core-host.mjs';

// Connected integration, migrated onto the shared live-core-host fixture: the
// real Pi extension talks to the REAL Python core over one persistent
// `__session` connection (real queue/SQLite, real detached per-run workers, real
// native parent-context capture and report delivery). The only controlled
// boundary is the fake-Pi model binary. Where the legacy script recorded one
// subprocess argv, this version observes WIRE request arguments and the real
// core effect, never a source-string or argv expectation. Covers:
//   - real `tool-info` metadata in registered tools BEFORE the first agent call,
//     carrying the configured delegation_guidance from prompts.yaml.
//   - taskLabel via the orch_dispatch tool AND `/orch do --task-label`, including
//     labels with spaces; the core dispatch text echoes the label value and IDs.
//   - unlabeled dispatch omits the label field and renders no label line.
//   - taskLabel never leaks into the wire goal field or the native parent-context
//     capture (a real get_parent_context round-trip).
//   - omitted history limit omits the limit on the wire; an explicit limit is
//     forwarded as a wire argument.
//   - blank goal (with/without context), non-positive/fractional limit, and a
//     stop with no run id all relay the REAL core error as isError (no adapter
//     pre-check, no bogus acceptance).
//   - a malformed core reply is a protocol error, never a fabricated success
//     (small independent controlled boundary block).
//   - malformed tool-info registers no tools and surfaces its cause.
// No live Pi sessions, global installs, or live models. The foreign-core
// ownership rejection journey is covered by pi-controls.test.mjs (2 connections)
// and is NOT duplicated here.

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..');

// Distinctive controlled delegation guidance, injected via the real Python YAML
// loader into the temp prompts.yaml — never the repo file — proving a supplied
// behavior prompt reaches core tool-info -> Pi registration without pinning
// default prose.
const TEST_DELEGATION = 'ZZTEST-CONTROLLED-DELEGATION-PHRASE delegate-every-slice-now';

// A controlled catalog: `plain` is a single manual job; `ctx` enables
// parent_context so a dispatch drives a REAL get_parent_context native round-trip
// (used to prove the task label never leaks into the captured native context).
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

// A distinctive marker only present in the parent-context capture, so the test
// can confirm a real native round-trip happened and that the task label did not
// ride along with it.
const CTX_MARKER = 'PARENT-CONTEXT-MARKER-DO-NOT-INJECT-LABEL';

const host = createLiveCoreHost({ repoRoot, catalog: CATALOG, delegationGuidance: TEST_DELEGATION });

// The adapter normalizes a native session id "CONN1" to owning session "pi:CONN1".
const CONN = 'pi:CONN1';

const hooks = new Map();
const tools = new Map();

try {
  const jiti = createJiti(import.meta.url);
  const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');
  const commands = new Map();
  const steers = [];
  const entries = [];
  let active = [];
  await activate({
    on: (name, handler) => hooks.set(name, handler),
    registerTool: (tool) => tools.set(tool.name, tool),
    registerCommand: (name, definition) => commands.set(name, definition),
    registerEntryRenderer() {},
    appendEntry: (type, data) => entries.push({ type, data }),
    getActiveTools: () => [...active],
    setActiveTools: (value) => { active = [...value]; },
    sendUserMessage: (message) => steers.push(String(message)),
  });

  // The slash-command output the adapter appends as `orchestra-output` entries.
  const shownOutput = () =>
    entries.filter((e) => e.type === 'orchestra-output').map((e) => e.data?.text ?? '').join('\n');

  // ---- 1: real tool-info metadata reaches registered tools BEFORE first agent --
  assert.ok(tools.has('orch_dispatch'), 'orch_dispatch registered');
  assert.ok(tools.has('orch_status'), 'orch_status registered');

  // The controlled delegation_guidance — NOT any default prose — reaches the
  // registered dispatch description before any run is started, through the real
  // prompt loader -> core tool-info -> Pi registration path with no stubbing.
  const desc = tools.get('orch_dispatch').description;
  assert.ok(desc.includes(TEST_DELEGATION), 'registered orch_dispatch description includes the controlled delegation text loaded from prompts.yaml');
  assert.ok(!desc.includes('Delegate by default.'), 'registered description does not pin default delegation prose');

  // Status tool action enum is the core actions array, not an adapter enum.
  const statusActionProp = tools.get('orch_status').parameters.properties.action;
  const actionEnum = statusActionProp.enum ?? statusActionProp.anyOf?.[0]?.enum;
  assert.ok(actionEnum, 'action parameter exposes enum from core actions');
  assert.deepEqual([...actionEnum].sort(), ['doctor', 'help', 'history', 'roles', 'status', 'stop']);

  // /orch command description comes from core.
  const cmd = commands.get('orch');
  assert.ok(cmd, '/orch command registered');
  assert.ok(typeof cmd.description === 'string' && cmd.description.length > 0, 'command description present');

  // ---- 2: tool dispatch with taskLabel containing spaces -------------------
  // Bound this session's owner and start the connection. contextEntries carry a
  // distinctive marker so the native parent-context capture is observable.
  const ctx1 = makeContext('CONN1', {
    contextEntries: [{ type: 'message', message: { role: 'user', content: [{ type: 'text', text: CTX_MARKER }] } }],
  });
  host.trackSession(CONN);
  await hooks.get('session_start')({}, ctx1);
  assert.ok(active.includes('orch_dispatch'), 'session_start activates orch_dispatch');

  // A `ctx` role (parent_context true) so this dispatch also drives a real
  // get_parent_context capture, while the taskLabel is supplied with spaces.
  const ackA = await tools.get('orch_dispatch').execute('t1', {
    goal: 'connected goal alpha',
    role: 'ctx',
    taskLabel: 'alpha label with spaces',
  }, undefined, undefined, ctx1);
  assert.equal(ackA.isError, false, `labeled tool dispatch must succeed: ${JSON.stringify(ackA)}`);
  const ackAText = text(ackA);
  const runIdA = host.trackRun(ackAText);
  // The core final dispatch text includes the IDs and the supplied label value.
  assert.ok(runIdA && ackAText.includes(runIdA), 'core dispatch text includes the real run id');
  assert.ok(ackAText.includes(`${runIdA}:1`), 'core dispatch text includes the job id');
  assert.match(ackAText, /alpha label with spaces/, 'core dispatch text echoes the supplied taskLabel value verbatim (with spaces)');
  // The core-owned session-workload snapshot is present (concept only; wording not pinned).
  assert.match(ackAText, /running|pending/i, 'core dispatch text renders a session-workload snapshot');
  assert.ok(!/default role/i.test(ackAText), 'no "default role" substitution in a successful ack');

  // WIRE REQUEST ARGUMENTS replace the old argv assertions: the taskLabel travels
  // as its own field, the goal stays literal (no label prefix/leak).
  const dispatchesA = host.requests('dispatch');
  const wireA = dispatchesA[dispatchesA.length - 1];
  assert.ok(wireA, 'labeled dispatch reached the core over the connection');
  assert.equal(wireA.arguments.taskLabel, 'alpha label with spaces', 'taskLabel with spaces is forwarded as a wire argument field');
  assert.equal(wireA.arguments.goal, 'connected goal alpha', 'goal wire argument is forwarded unchanged');
  assert.ok(!wireA.arguments.goal.includes('alpha label with spaces'), 'taskLabel must NOT be folded into the goal wire argument');

  // ---- 3: native parent-context capture never carries the task label -------
  // The real core requested get_parent_context (proves a live native round-trip);
  // the adapter captured the parent context from contextEntries. The captured
  // text must include the marker and must NOT contain the task label.
  await host.poll('get_parent_context native capture answered', () =>
    host.nativeResults().some((fr) => fr.data && typeof fr.data.text === 'string' && fr.data.text.includes(CTX_MARKER)), 8000);
  const captures = host.nativeResults().filter((fr) => fr.data && typeof fr.data.text === 'string');
  const labeledCapture = captures.find((fr) => fr.data.text.includes(CTX_MARKER));
  assert.ok(labeledCapture, 'native parent-context capture returned the session marker text');
  assert.ok(!labeledCapture.data.text.includes('alpha label with spaces'), 'taskLabel must NOT leak into the native parent-context capture');

  // ---- 4: /orch do --task-label with quoted spaces -------------------------
  entries.length = 0;
  await cmd.handler('do --role plain --task-label "slash label with spaces" connected slash goal', ctx1);
  let slashOut = '';
  await host.poll('slash dispatch ack emitted', () => {
    slashOut = shownOutput();
    return slashOut.length > 0;
  });
  assert.match(slashOut, /slash label with spaces/, '/orch do ack renders the slash-supplied taskLabel value verbatim (with spaces)');
  assert.match(slashOut, /\b[0-9a-f]{32}\b/, '/orch do ack contains a real run id from core');
  host.trackRun(slashOut);
  // WIRE: the slash dispatch forwards the unquoted label as its own field and the
  // goal literal with no label token.
  const wireSlash = host.requests('dispatch')[host.requests('dispatch').length - 1];
  assert.equal(wireSlash.arguments.taskLabel, 'slash label with spaces', '/orch do forwards the unquoted taskLabel as a wire argument');
  assert.equal(wireSlash.arguments.goal, 'connected slash goal', '/orch do builds the goal literal from the remaining tokens');
  assert.ok(!wireSlash.arguments.goal.includes('slash label with spaces'), '/orch do goal must NOT include the label token');

  // ---- 5: unlabeled dispatch omits the label field entirely ----------------
  const ackB = await tools.get('orch_dispatch').execute('t2', { goal: 'unlabeled goal', role: 'plain' }, undefined, undefined, ctx1);
  assert.equal(ackB.isError, false, `unlabeled tool dispatch must succeed: ${JSON.stringify(ackB)}`);
  const ackBText = text(ackB);
  host.trackRun(ackBText);
  assert.ok(!/label/i.test(ackBText), `unlabeled ack must render no label line (got: ${ackBText})`);
  assert.match(ackBText, /\b[0-9a-f]{32}\b/, 'unlabeled ack still contains a real run id');
  // WIRE: no taskLabel key is sent when the label is omitted.
  const wireB = host.requests('dispatch')[host.requests('dispatch').length - 1];
  assert.ok(!('taskLabel' in wireB.arguments), `omitted label must not appear as a wire argument (got: ${JSON.stringify(wireB.arguments)})`);

  // ---- 6: history limit default vs explicit (wire arguments) ---------------
  const historyNoLimit = await tools.get('orch_status').execute('t3', { action: 'history' }, undefined, undefined, ctx1);
  assert.equal(historyNoLimit.isError, false, 'history without limit succeeds');
  const histReq = host.requests('history')[host.requests('history').length - 1];
  assert.ok(histReq, 'history request reached core over the connection');
  assert.ok(!('limit' in histReq.arguments), `adapter must omit the limit wire argument when none supplied (got: ${JSON.stringify(histReq.arguments)})`);

  const historyLimited = await tools.get('orch_status').execute('t4', { action: 'history', limit: 3 }, undefined, undefined, ctx1);
  assert.equal(historyLimited.isError, false, 'history with limit succeeds');
  const histReq2 = host.requests('history')[host.requests('history').length - 1];
  assert.equal(histReq2.arguments.limit, 3, 'explicit limit is forwarded as a wire argument');

  // ---- 7: removed adapter pre-checks now relay REAL core validation --------
  // The adapter no longer pre-validates; the actual core reply is the observed
  // effect (isError + the core's own message), and NO accepted run id appears.

  // 7a: blank goal -> real core goal error, isError, no accepted run id.
  {
    const blank = await tools.get('orch_dispatch').execute('t7a', { goal: '   ', role: 'plain' }, undefined, undefined, ctx1);
    assert.equal(blank.isError, true, 'blank goal must be an isError tool result');
    const t = text(blank);
    assert.match(t, /non-empty goal/i, 'blank goal relays the real core goal error');
    assert.ok(!/\b[0-9a-f]{32}\b/.test(t), 'blank goal must not report an accepted run id');
  }

  // 7b: blank goal WITH additionalContext -> context must not rescue an empty goal.
  {
    const blankCtx = await tools.get('orch_dispatch').execute('t7b', {
      goal: '',
      additionalContext: 'context that must not substitute for a goal',
      role: 'plain',
    }, undefined, undefined, ctx1);
    assert.equal(blankCtx.isError, true, 'blank goal + context must be an isError tool result');
    const t = text(blankCtx);
    assert.match(t, /non-empty goal/i, 'blank goal + context still relays the real core goal error');
    assert.ok(!/\b[0-9a-f]{32}\b/.test(t), 'blank goal + context must not report an accepted run id');
  }

  // 7c: non-positive / fractional limit -> real core positivity/type errors.
  for (const bad of [
    { limit: 0, re: /positive integer/i },
    { limit: -1, re: /positive integer/i },
    { limit: 2.5, re: /integer/i },
  ]) {
    const badHistory = await tools.get('orch_status').execute(`t7c-${bad.limit}`, { action: 'history', limit: bad.limit }, undefined, undefined, ctx1);
    assert.equal(badHistory.isError, true, `history limit ${bad.limit} must be an isError tool result`);
    assert.match(text(badHistory), bad.re, `history limit ${bad.limit} relays the real core limit error`);
  }

  // 7d: stop with a missing run id -> real core missing-argument error.
  {
    const stopNoId = await tools.get('orch_status').execute('t7d', { action: 'stop' }, undefined, undefined, ctx1);
    assert.equal(stopNoId.isError, true, 'stop without runId must be an isError tool result');
    assert.match(text(stopNoId), /runId|run id/i, 'stop relays the real core missing-run-id error');
  }

  // ---- 8: malformed core reply -> protocol error, no bogus acceptance ------
  // Small independent controlled boundary: a `__session` responder that answers
  // tool-info and initial-mode honestly but replies to a dispatch with a result
  // carrying NO text. The adapter must surface resultText's protocol error and
  // never fabricate an acknowledgement or a run id.
  {
    const malBin = join(host.temp, 'malformed-reply-bin');
    mkdirSync(malBin);
    writeFileSync(join(malBin, 'python3'), `#!${process.execPath}
const { spawn, spawnSync } = require('node:child_process');
const readline = require('node:readline');
const args = process.argv.slice(2);
const real = ${JSON.stringify(host.realPython)};
if (args.includes('tool-info')) {
  const r = spawnSync(real, args, { encoding: 'utf8', env: process.env });
  process.stdout.write(r.stdout || '');
  if (r.stderr) process.stderr.write(r.stderr);
  process.exit(r.status ?? 0);
}
if (args.includes('__session')) {
  const send = (o) => process.stdout.write(JSON.stringify(o) + '\\n');
  readline.createInterface({ input: process.stdin }).on('line', (line) => {
    let f; try { f = JSON.parse(line); } catch { return; }
    if (f.kind !== 'request') return;
    if (f.operation === 'initial-mode') return send({ kind: 'reply', id: f.id, result: { mode: 'on' } });
    if (f.operation === 'dispatch') return send({ kind: 'reply', id: f.id, result: { status: 'accepted' } }); // no text
    return send({ kind: 'reply', id: f.id, result: { text: 'ok' } });
  }).on('close', () => process.exit(0));
  return;
}
const r = spawnSync(real, args, { encoding: 'utf8', env: process.env });
process.stdout.write(r.stdout || '');
if (r.stderr) process.stderr.write(r.stderr);
process.exit(r.status ?? 0);
`, { mode: 0o755 });

    const savedPath = process.env.PATH;
    process.env.PATH = `${malBin}:${savedPath}`;
    const malHooks = new Map();
    try {
      const jitiMal = createJiti(import.meta.url);
      const { default: activateMal } = await jitiMal.import('../extensions/pi/orchestra/index.ts');
      const malTools = new Map();
      await activateMal({
        on: (name, handler) => malHooks.set(name, handler),
        registerTool: (t) => malTools.set(t.name, t),
        registerCommand() {}, registerEntryRenderer() {},
        appendEntry() {},
        getActiveTools: () => [], setActiveTools() {}, sendUserMessage() {},
      });
      const malCtx = makeContext('MAL1');
      await malHooks.get('session_start')({}, malCtx);
      const r = await malTools.get('orch_dispatch').execute('m1', { goal: 'will fail malformed reply', role: 'plain' }, undefined, undefined, malCtx);
      assert.equal(r.isError, true, 'a malformed core reply (no result.text) must surface as isError');
      const shown = text(r);
      assert.match(shown, /malformed|protocol/i, 'a malformed reply is surfaced as a protocol error');
      assert.ok(!/Assignment accepted\./i.test(shown), 'a malformed reply must not fabricate an acknowledgement');
      assert.ok(!/\b[0-9a-f]{12,}\b/.test(shown), 'a malformed reply must not report a bogus run id');
      try { malHooks.get('session_shutdown')({}, malCtx); } catch { /* best-effort close */ }
    } finally {
      process.env.PATH = savedPath;
    }
  }

  // ---- 9: malformed tool-info JSON registers no tools, surfaces real cause -
  {
    const badInfoBin = join(host.temp, 'bad-tool-info-bin');
    mkdirSync(badInfoBin);
    writeFileSync(join(badInfoBin, 'python3'), `#!${process.execPath}
const args = process.argv.slice(2);
if (args.includes('tool-info')) { process.stdout.write('not json {{{'); process.exit(0); }
process.exit(0);
`, { mode: 0o755 });
    const savedPath = process.env.PATH;
    process.env.PATH = `${badInfoBin}:${savedPath}`;
    try {
      const jitiBad = createJiti(import.meta.url);
      const { default: activateBad } = await jitiBad.import('../extensions/pi/orchestra/index.ts');
      const badTools = new Map();
      let threw = false;
      try {
        await activateBad({
          on() {}, registerTool: (t) => badTools.set(t.name, t),
          registerCommand() {}, registerEntryRenderer() {}, appendEntry() {},
          getActiveTools: () => [], setActiveTools() {}, sendUserMessage() {},
        });
      } catch (e) {
        threw = true;
        assert.match(String(e), /tool-info|malformed/i, 'malformed tool-info throws with its real cause');
      }
      assert.ok(threw, 'malformed tool-info must throw');
      assert.equal(badTools.size, 0, 'malformed tool-info registers no tools');
    } finally {
      process.env.PATH = savedPath;
    }
  }

  // ---- success proof: every dispatched run reaches a persisted terminal end --
  await host.waitForCompletedEndState();

  console.log('Pi connected integration passed');
} finally {
  // Close the owning core connection first (session_shutdown: signals session_end
  // and closes the persistent connection), then stop ONLY this test's own still
  // active runs, wait bounded for them to drain, and remove the temp dir. No
  // global kill, no live host; independent workers are never killed by shutdown.
  try { hooks.get('session_shutdown')({}, makeContext('CONN1')); } catch { /* best-effort */ }
  await host.teardown();
  try { rmSync(host.temp, { recursive: true, force: true }); } catch { /* already removed */ }
}
