import assert from 'node:assert/strict';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createJiti } from 'jiti';
import { createLiveCoreHost, makeContext, text } from './helpers/pi-live-core-host.mjs';

// ACTUAL core<->footer LIFETIME visibility against the REAL Python core (real
// queue/SQLite, real detached __run worker, real transport frames). Only the
// model (fake-Pi) is controlled. This is the counterpart to the controlled
// session-stub display test (pi-footer.test.mjs): the stub proves the adapter's
// display/transport contract, but it CANNOT prove core timing — this file does.
//
// The running-only meter is core-produced: every evaluate() pass emits a
// {kind:'status', text} frame (render_running_meter) and the adapter renders it
// verbatim. An evaluate pass is woken by a host event, by dispatch acceptance,
// by native results, by the core-owned worker-progress observer reading lifecycle
// transitions over an inherited notification pipe, by the worker-exit reaper, or
// by the 10s active-work backstop. The Pi adapter has no timer and derives no
// status.
//
// Progress bridge: __run passes lifecycle events (started, succeeded, failed,
// skipped) through an inherited one-way notification pipe to the connection.
// The observer reads each trigger and calls request_evaluation(), which wakes
// the SAME shared evaluator. The evaluator re-reads the authoritative queue and
// pushes the current running-only meter. This means a builder→verifier running
// transition is observable from the real execution lifecycle, NOT only via a
// manual host event or the 10s backstop.
//
// This test proves: builder running → verifier running (auto_verify) → idle →
// exactly one native report delivery, all observed via the progress bridge
// without any agent_start/status/prompt/host-event wake, within the 10s
// backstop window.

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const host = createLiveCoreHost({ repoRoot });
const S = 'pi:footer-live';
host.trackSession(S);

const hooks = new Map();
const tools = new Map();
const steers = [];

function statusPushes() {
  return host.frames()
    .filter((f) => f.dir === 'out' && f.frame && f.frame.kind === 'status')
    .map((f) => f.frame.text);
}
const lastPush = () => { const p = statusPushes(); return p[p.length - 1]; };

function statusFrames() {
  return host.frames()
    .filter((f) => f.dir === 'out' && f.frame && f.frame.kind === 'status')
    .map((f) => f.frame);
}
const lastFrame = () => { const f = statusFrames(); return f[f.length - 1]; };

// The rendered widget now prepends the native usage segment (only when core
// supplies worker ids) and the core mode chip before the VERBATIM core meter
// text. Whole-widget equality to the bare core text is therefore no longer the
// contract: assert the core meter text survives verbatim as the contiguous
// suffix, and that the core-supplied mode chip is actually rendered. Native
// usage is a separate native segment and is never treated as core state.
function renderedVerbatim(footer, frame) {
  assert.ok(
    typeof footer === 'string' && footer.endsWith(frame.text),
    `core meter text must render verbatim as the contiguous suffix (footer=${JSON.stringify(footer)}, core=${JSON.stringify(frame.text)})`,
  );
  if (frame.mode_text) {
    assert.ok(
      footer.includes(frame.mode_text),
      `core mode chip must actually render in the widget (footer=${JSON.stringify(footer)}, chip=${JSON.stringify(frame.mode_text)})`,
    );
  }
}

try {
  const jiti = createJiti(import.meta.url);
  const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');
  await activate({
    on: (name, handler) => hooks.set(name, handler),
    registerTool: (t) => tools.set(t.name, t),
    registerCommand() {}, registerEntryRenderer() {}, appendEntry() {},
    getActiveTools: () => [...tools.keys()],
    setActiveTools() {},
    sendUserMessage: (m) => steers.push(String(m)),
  });
  assert.ok(tools.has('orch_dispatch'), 'orch_dispatch must be registered');

  const footers = [];
  const liveCtx = makeContext('footer-live', { footers });
  // A widget rendered from a given core frame: verbatim core-text suffix and,
  // when present, the core mode chip actually shown.
  const footerRendered = (frame) => footers.some(
    (f) => typeof f === 'string' && f.endsWith(frame.text)
      && (!frame.mode_text || f.includes(frame.mode_text)),
  );

  // --- session_start: a genuine core push renders the idle meter verbatim -----
  await hooks.get('session_start')({}, liveCtx);
  await host.poll('initial idle meter pushed by the real core',
    () => statusPushes().some((t) => t === 'Orchestra: no running jobs'));
  assert.equal(lastPush(), 'Orchestra: no running jobs',
    'the real core pushes the running-only idle meter for an empty session');
  renderedVerbatim(footers[footers.length - 1], lastFrame());

  // --- progress bridge: builder→verifier lifecycle observed without any -----
  // manual host-event wake. Builder has auto_verify=true (default catalog), so
  // Submit creates a dependent verifier job. Delays chosen so the full
  // builder→verifier→idle lifecycle completes well before the 10s backstop.
  host.setScenario([
    { match: 'build the meter', text: 'builder done', delayMs: 2000 },
    { match: 'Verify', text: 'verifier confirmed', delayMs: 1000 },
    { match: '*', text: 'live core answer' },
  ]);
  const t0 = Date.now();
  const ack = await tools.get('orch_dispatch').execute('c1',
    { goal: 'build the meter', role: 'builder' }, undefined, undefined, liveCtx);
  assert.equal(ack.isError, false, `dispatch ack failed: ${JSON.stringify(ack)}`);
  const runId = host.trackRun(text(ack));
  assert.ok(runId, 'dispatch acknowledgement contains a trackable run id');

  // ---- observe builder running via the progress bridge (NO agent_start) ----
  // The __run worker writes a "started" lifecycle event per job transition to
  // the inherited notification pipe; the connection observer calls
  // request_evaluation() which wakes the shared evaluator. The evaluator
  // re-reads the durable queue and pushes the running-only meter.
  await host.poll('builder running meter pushed via progress bridge',
    () => statusPushes().some((t) => /running builder/i.test(t)), 8000);
  const tBuilderRunning = Date.now();

  // Durable queue confirms builder is genuinely running at this observation.
  const activeAtBuilder = host.activeJobs(S);
  assert.ok(activeAtBuilder.some((j) => j.role === 'builder' && j.status === 'running'),
    'builder job is running in the durable queue when the builder meter was observed');
  assert.ok(activeAtBuilder.some((j) => j.role === 'verifier' && j.status === 'pending'),
    'auto_verify verifier is pending in the durable queue while builder runs');

  // The footer renders the builder-running core text verbatim (with its chip).
  const builderFrame = statusFrames().find((fr) => /running builder/i.test(fr.text));
  assert.ok(builderFrame, 'builder-running meter is a genuine core push');
  assert.ok(footerRendered(builderFrame),
    'builder-running core text rendered verbatim (with its mode chip) in the adapter');

  // ---- observe verifier running via the progress bridge (NO agent_start) ---
  // After builder succeeds, the dispatcher claims the dependent verifier job.
  // The "started" event fires and wakes the same evaluator: the running meter
  // now names verifier, NOT builder (builder is terminal → excluded).
  const idxAfterBuilder = statusPushes().findIndex((t) => /running builder/i.test(t));
  await host.poll('verifier running meter pushed via progress bridge',
    () => statusPushes().slice(idxAfterBuilder + 1).some((t) => /running verifier/i.test(t)), 8000);
  const tVerifierRunning = Date.now();

  // Durable queue confirms verifier running, builder terminal.
  const activeAtVerifier = host.activeJobs(S);
  assert.ok(activeAtVerifier.some((j) => j.role === 'verifier' && j.status === 'running'),
    'verifier job is running in the durable queue when the verifier meter was observed');
  assert.ok(!activeAtVerifier.some((j) => j.role === 'builder' && j.status === 'running'),
    'builder is no longer running in the durable queue during verifier');

  // The verifier push names verifier and NOT builder.
  const verifierPush = statusPushes().slice(idxAfterBuilder + 1).find((t) => /running verifier/i.test(t));
  assert.ok(verifierPush, 'verifier-running meter is a distinct push');
  assert.match(verifierPush, /running verifier/i);
  assert.doesNotMatch(verifierPush, /builder/i,
    'completed builder is absent from the running meter during verifier');
  const verifierFrame = statusFrames().slice(idxAfterBuilder + 1).find((fr) => /running verifier/i.test(fr.text));
  assert.ok(verifierFrame && footerRendered(verifierFrame),
    'verifier-running core text rendered verbatim (with its mode chip) in the adapter');

  // ---- still active overall during verifier ----
  // The run has not reached a reported end-state yet: the session still has
  // active (running) jobs and no delivery has been made.
  const deliverReqsDuringVerifier = host.nativeRequests('deliver_report').length;
  assert.equal(deliverReqsDuringVerifier, 0,
    'no report delivery request during verifier phase — run is still active');

  // ---- idle meter after verifier completes (progress bridge drives this) ----
  const idxAfterVerifier = statusPushes().findIndex((t) => /running verifier/i.test(t));
  await host.poll('idle meter pushed after verifier via progress bridge',
    () => statusPushes().slice(idxAfterVerifier + 1).some((t) => t === 'Orchestra: no running jobs'),
    8000);
  const tIdle = Date.now();

  // Footer displays the idle push verbatim.
  assert.equal(lastPush(), 'Orchestra: no running jobs',
    'idle meter after all jobs terminal — the genuine execution-lifecycle footer update');
  renderedVerbatim(footers[footers.length - 1], lastFrame());

  // Active jobs drained.
  const activeAtIdle = host.activeJobs(S);
  assert.equal(activeAtIdle.length, 0,
    'no active jobs remain in the durable queue at idle');

  // ---- timing: all transitions observed well before the 10s backstop ----
  // The progress bridge fires within milliseconds of actual queue transitions.
  // Proving observation within 10s of dispatch shows the bridge — not the
  // backstop timer — drove these events.
  const totalMs = tIdle - t0;
  assert.ok(totalMs < 10000,
    `builder→verifier→idle lifecycle completed in ${totalMs}ms, well under the 10s backstop`);

  // ---- exactly one native report delivery with real content ----
  await host.poll('report delivery requested via native round-trip',
    () => host.nativeRequests('deliver_report').length >= 1, 10000);
  const deliverReqs = host.nativeRequests('deliver_report');
  assert.equal(deliverReqs.length, 1,
    'exactly one deliver_report native_request — no duplicate delivery');
  const reportReq = deliverReqs[0];
  const reportText = reportReq.arguments?.text;
  assert.ok(typeof reportText === 'string' && reportText.length > 20,
    'the delivered report carries real assembled content, not a stub');

  // The Pi adapter routed the report through sendUserMessage → steers.
  await host.poll('report steer received', () => steers.length >= 1, 5000);
  assert.equal(steers.length, 1,
    'exactly one native receipt (steer) — the report delivery was accepted once');
  assert.ok(steers[0].length > 20,
    'the steer carries the real report body, not a unit stub');

  // ---- run reaches persisted terminal end-state ----
  await host.waitForCompletedEndState(15000);

  console.log('Pi live-core footer lifetime visibility passed');
} finally {
  if (hooks.has('session_shutdown')) hooks.get('session_shutdown')({}, makeContext('footer-live'));
  await host.teardown();
}
