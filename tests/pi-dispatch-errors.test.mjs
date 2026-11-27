import assert from 'node:assert/strict';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createJiti } from 'jiti';
import { makeSessionStub, makeCtx } from './helpers/orchestra-session-stub.mjs';

// Translator-boundary error propagation over the persistent core `__session`.
// The raw dispatch-subprocess stderr tailing that used to live in the adapter is
// now produced inside core and arrives as a correlated error reply; the adapter
// must relay that ACTUAL cause verbatim, never a fixed "see stderr". A launch
// failure of the `__session` runtime must also surface its real cause and settle
// (no hang). Controlled core stub + empty PATH only: no real Python core, live
// Pi sessions, models, or global install.
const stub = makeSessionStub({ reply: {} });

// A realistic core-produced dispatch failure cause. Bounded stderr-tail selection
// is now core-producer behaviour, not a translator assertion: the translator's
// contract is that whatever cause core returns is relayed unchanged.
const CAUSE = 'sqlite3.OperationalError: unable to open database file';

const scenario = (extra) => ({
  'initial-mode': { result: { mode: 'on', text: 'Orchestra active.' } },
  ...extra,
});

const text = (result) => (result.content ?? []).map((p) => p.text ?? '').join('\n');

const hooks = new Map();
const tools = new Map();
let ctx;

try {
  const jiti = createJiti(import.meta.url);
  const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');
  await activate({
    on: (name, handler) => hooks.set(name, handler),
    registerTool: (t) => tools.set(t.name, t),
    registerCommand() {},
    registerEntryRenderer() {},
    appendEntry() {},
    getActiveTools: () => [...tools.keys()],
    setActiveTools() {},
    sendUserMessage() {},
  });
  const dispatch = tools.get('orch_dispatch');
  assert.ok(dispatch, 'orch_dispatch tool must be registered');

  // --- A: a core dispatch error is relayed verbatim as the tool result cause --
  {
    stub.setScenario(scenario({ dispatch: { error: CAUSE } }));
    ctx = makeCtx('dispatch-error-relay');
    await hooks.get('session_start')({}, ctx);
    const r = await dispatch.execute('e1', { goal: 'will fail', role: 'builder' }, undefined, undefined, ctx);
    assert.equal(r.isError, true, `a core dispatch error must be isError: ${JSON.stringify(r)}`);
    const shown = text(r);
    assert.equal(shown, CAUSE, 'the actual core error is relayed verbatim as the tool result');
    assert.match(shown, /unable to open database file/, 'the real core cause appears in the tool result');
    assert.ok(!/see stderr/i.test(shown), 'the bare fixed "see stderr" text is never returned');
  }

  // --- B: a launch error surfaces its real cause and settles (no hang) --------
  {
    // Close the connected session, then point PATH at an empty dir so the next
    // `__session` spawn errors ENOENT before any reply can arrive. The initial
    // mode request must reject with the launch cause, visibly, and settle.
    hooks.get('session_shutdown')({}, ctx);
    const emptyBin = mkdtempSync(join(tmpdir(), 'orch-empty-bin-'));
    const savedPath = process.env.PATH;
    process.env.PATH = emptyBin;
    try {
      const notes = [];
      const launchCtx = makeCtx('dispatch-launch-error', { notes });
      const guard = new Promise((_resolve, reject) =>
        setTimeout(() => reject(new Error('HANG: the launch-error path did not settle')), 5000));
      await Promise.race([hooks.get('session_start')({}, launchCtx), guard]);
      const surfaced = notes.join('\n');
      assert.match(surfaced, /ENOENT/, 'the actual launch cause (ENOENT) is surfaced');
      assert.match(surfaced, /python3/, 'the launch cause names the missing python3 runtime');
      assert.ok(!/Assignment accepted|active/i.test(surfaced), 'a launch failure never reports success');
    } finally {
      process.env.PATH = savedPath;
    }
  }

  console.log('Pi dispatch error propagation passed');
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
