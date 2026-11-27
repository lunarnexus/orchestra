import assert from 'node:assert/strict';
import { createJiti } from 'jiti';
import { makeSessionStub, makeCtx } from './helpers/orchestra-session-stub.mjs';

// Native footer-DISPLAY contract for the Pi translator, driven against the
// controlled `__session` core STUB (no real core, models, live Pi, or install).
//
// The running-only role meter is CORE-PRODUCED text: the core pushes
// {kind:'status', text} frames and the adapter renders them verbatim into the
// below-editor widget. These tests prove the DISPLAY/transport contract only —
// they never imply that the stub proves core timing. Actual core→footer
// lifetime visibility (and the worker-exit/backstop distinction) is covered by
// tests/pi-footer-live.test.mjs against the real core.
//
// Covers, per the approved thin-adapter contract:
//   - the running-only meter is core text displayed immediately, the adapter
//     never derives role status (scripted builder -> verifier -> idle pushes);
//   - `/orch status` renders the core reply TEXT, not a structured JSON envelope;
//   - `before_agent_start` is a forwarded native event — it issues NO independent
//     status subprocess/request of the adapter's own;
//   - a session replacement never renders a previous session's core footer;
//   - `session_shutdown` clears the widget and no post-close update/query occurs;
//   - a native `hasUI:false` context is safe (no widget write, no crash).
//
// The obsolete "no periodic status calls ANYWHERE" assertion is NOT reasserted:
// the approved core active-only 10s backstop exists (out of the adapter's
// scope). Here we assert only that the Pi adapter has no own timer that would
// re-render the footer on its own, and that the footer tracks core pushes.

const stub = makeSessionStub();

function scenario(meterText, extra = {}) {
  return { 'initial-mode': { result: { mode: 'on' } }, ...extra, statusText: meterText };
}

function footerOf(widgets) {
  for (let i = widgets.length - 1; i >= 0; i -= 1) {
    if (widgets[i].key === 'orchestra') {
      const c = widgets[i].content;
      return c === undefined ? '' : Array.isArray(c) ? c.join('\n') : String(c);
    }
  }
  return '';
}

async function poll(label, fn, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (fn()) return;
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${label}`);
    await new Promise((r) => setTimeout(r, 25));
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const text = (result) => (result.content ?? []).map((p) => p.text ?? '').join('\n');

const hooks = new Map();
const tools = new Map();
const commands = new Map();
let entries = [];
let active = [];
const steers = [];

try {
  const jiti = createJiti(import.meta.url);
  const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');
  await activate({
    on: (name, handler) => hooks.set(name, handler),
    registerTool: (t) => { tools.set(t.name, t); active.push(t.name); },
    registerCommand: (name, def) => commands.set(name, def),
    registerEntryRenderer() {},
    appendEntry: (type, data) => entries.push({ type, data }),
    getActiveTools: () => [...active],
    setActiveTools: (list) => { active = [...list]; },
    sendUserMessage: (m) => steers.push(String(m)),
  });
  assert.ok(tools.has('orch_dispatch') && tools.has('orch_status'), 'orch tools registered');
  assert.ok(hooks.has('session_start') && hooks.has('before_agent_start') && hooks.has('session_shutdown'),
    'lifecycle hooks registered');

  const outputText = () => entries.filter((e) => e.type === 'orchestra-output').map((e) => e.data?.text ?? '').join('\n');
  function orch(statusArgs, ctx) { return commands.get('orch').handler(statusArgs, ctx); }
  // Drive one fresh core status push by issuing a handled request; the stub
  // emits its scripted statusText after each handled request frame. The push is
  // a separate frame that lands just after the reply, so wait for the widget.
  async function pushMeter(ctx, widgets, meterText) {
    stub.setScenario(scenario(meterText, { status: { result: { text: 'STATUS_TEXT' } } }));
    entries = [];
    await orch('status', ctx);
    await poll(`footer updated to: ${meterText}`, () => footerOf(widgets) === meterText);
  }

  // --- running-only meter is core text, displayed verbatim, never derived ----
  const wA = [];
  const ctx1b = makeCtx('display-b', { widgets: wA });
  stub.setScenario(scenario('Orchestra: running builder×1'));
  await hooks.get('session_start')({}, ctx1b);
  assert.equal(footerOf(wA), 'Orchestra: running builder×1',
    'the core-pushed running-only meter is rendered verbatim into the widget');

  // A novel token proves the adapter COPIES core text instead of deriving it:
  // no adapter-side role logic could invent "zeta-role×7".
  await pushMeter(ctx1b, wA, 'Orchestra: running zeta-role×7');
  assert.equal(footerOf(wA), 'Orchestra: running zeta-role×7',
    'the footer copies whatever the core pushes; the adapter does not derive role status');

  // --- scripted builder -> verifier -> idle transitions (controlled pushes) --
  await pushMeter(ctx1b, wA, 'Orchestra: running builder×1');
  assert.match(footerOf(wA), /builder/, 'builder phase of the scripted transition');
  assert.doesNotMatch(footerOf(wA), /verifier/, 'running-only meter lists only running roles');
  await pushMeter(ctx1b, wA, 'Orchestra: running verifier×1');
  assert.match(footerOf(wA), /verifier/, 'verifier phase is shown after the core pushes it');
  assert.doesNotMatch(footerOf(wA), /builder/, 'the previous running role is gone, not merged');
  await pushMeter(ctx1b, wA, 'Orchestra: no running jobs');
  assert.equal(footerOf(wA), 'Orchestra: no running jobs', 'idle meter clears the roles');

  // --- /orch status renders core reply text, not a structured JSON envelope ---
  stub.setScenario(scenario('Orchestra: running builder×1', {
    status: { result: { text: 'Orchestra: on\n\nThis session:\n  #1     builder     running   run deadbeef\n' } },
  }));
  entries = [];
  await orch('status', ctx1b);
  const shown = outputText();
  assert.match(shown, /This session:/, 'the detailed core status reply text is displayed');
  assert.ok(!shown.trimStart().startsWith('{'), 'no raw JSON is shown for /orch status');
  assert.doesNotMatch(shown, /"session_jobs"/, 'the structured status envelope stays out of user output');

  // --- command errors surface the real core cause ----------------------------
  stub.setScenario({ 'initial-mode': { result: { mode: 'on' } }, status: { error: 'status boundary exploded' } });
  entries = [];
  await orch('status', ctx1b);
  assert.match(outputText(), /status boundary exploded/, 'a failing status surfaces the core error verbatim');

  // --- before_agent_start is a forwarded native event, not a status subprocess
  stub.reset();
  const requestsBefore = stub.requests().length;
  const statusReqsBefore = stub.requests().filter((r) => r.operation === 'status').length;
  await hooks.get('before_agent_start')({ messageType: 'user', prompt: 'next turn' }, ctx1b);
  await poll('host_event frame forwarded to core',
    () => stub.frames().some((f) => f.frame === 'host_event' && f.msg.event === 'before_agent_start'));
  assert.equal(stub.requests().length, requestsBefore,
    'before_agent_start forwards the event without issuing any new core request');
  assert.equal(stub.requests().filter((r) => r.operation === 'status').length, statusReqsBefore,
    'the agent-start event triggers no independent status subprocess of the adapter');

  // --- the adapter has no own timer that re-renders the footer on its own -----
  await pushMeter(ctx1b, wA, 'Orchestra: running builder×1');
  const rendered = footerOf(wA);
  await sleep(300); // well under the core 10s backstop; no new core request
  assert.equal(footerOf(wA), rendered,
    'the adapter does not self-update the footer (no Pi-side timer); it only follows core pushes');

  // --- session replacement never renders the previous session's footer --------
  const wB = [];
  const ctx2 = makeCtx('display-next', { widgets: wB });
  stub.setScenario(scenario('Orchestra: running verifier×1'));
  await hooks.get('session_start')({}, ctx2); // replaces ctx1b's connection
  assert.equal(footerOf(wB), 'Orchestra: running verifier×1',
    'the replaced-to session shows its own core footer');
  assert.equal(footerOf(wA), 'Orchestra: running builder×1',
    'the replaced-away session widget is untouched (stale old-core footer never re-applied)');

  // --- shutdown clears the widget and no post-close update/query happens ------
  await hooks.get('session_shutdown')({}, ctx2);
  assert.equal(footerOf(wB), '', 'session_shutdown clears the below-editor widget');
  const closedRequests = stub.requests().length;
  await hooks.get('before_agent_start')({ messageType: 'user', prompt: 'after' }, ctx2); // must be a no-op
  const stopResult = await orch('status', ctx2); // not-connected path
  await poll('shutdown cleared connection', () => stub.requests().length === closedRequests);
  assert.equal(stub.requests().length, closedRequests, 'no status query is issued after the connection closed');
  void stopResult;

  // --- hasUI:false is safe: no widget write, no crash -------------------------
  let widgetTouched = false;
  const ctxNoUI = {
    hasUI: false,
    sessionManager: { getSessionId: () => 'no-ui', buildContextEntries: () => [], getBranch: () => [] },
    ui: {
      theme: { fg: (_c, t) => t, bold: (t) => t },
      setWidget: () => { widgetTouched = true; },
      notify: () => {},
    },
  };
  stub.setScenario(scenario('Orchestra: running builder×1', { status: { result: { text: 'STATUS_TEXT' } } }));
  await hooks.get('session_start')({}, ctxNoUI);
  entries = [];
  await orch('status', ctxNoUI); // emits to stdout, never a widget
  assert.ok(!widgetTouched, 'a hasUI:false native context must never receive a widget write');
  await hooks.get('session_shutdown')({}, ctxNoUI); // release the open connection

  console.log('Pi footer native-display contract passed');
} finally {
  stub.cleanup();
}
