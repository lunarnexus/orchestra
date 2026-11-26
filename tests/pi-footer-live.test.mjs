import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, readFileSync, appendFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createJiti } from 'jiti';

// Prove the event-driven footer: a child job that starts AFTER the dispatch
// ack (an auto-verify verifier that begins when the builder finishes) becomes
// visible in the belowEditor role meter DURING the run, driven ONLY by typed
// lifecycle event lines on the dispatch stdout stream — never a periodic poll.
// The real extension is driven; only the Python and host boundaries are
// controlled by a fake python3. No live pi, model, global config, or real core.
//
// The fake dispatch forwards event lines that the test enqueues, so the
// extension's status-query count is fully under test control: a flat count
// between events proves the removed 2s timer is really gone.
const temp = mkdtempSync(join(tmpdir(), 'orchestra-footer-live-'));
const dataPath = join(temp, 'status.json');       // mutable status served to `status`
const eventsPath = join(temp, 'events.jsonl');     // events the test enqueues for dispatch to forward
const pidPath = join(temp, 'dispatch.pid');
const counterPath = join(temp, 'status.count');
try {
  writeFileSync(join(temp, 'python3'), `#!${process.execPath}\n` + [
    `const fs = require('node:fs');`,
    `const C = ${JSON.stringify(counterPath)};`,
    `const EV = ${JSON.stringify(eventsPath)};`,
    `const args = process.argv.slice(2);`,
    `const sub = args[2];`,
    `if (args.includes('tool-info')) {`,
    `  process.stdout.write(JSON.stringify({dispatch:{label:"Orchestra Dispatch",description:"Submit.",params:{goal:"Assignment text.",additionalContext:"Extra context.",role:"Role name.",taskLabel:"Short label."}},status:{label:"Orchestra Status",description:"Manage.",params:{action:"Action.",limit:"Limit.",runId:"Run ID."}},command:{description:"/orch"},actions:["status","history","stop","help","doctor","roles"]}));`,
    `  process.exit(0);`,
    `}`,
    `if (sub === 'initial-mode') { console.log('on'); process.exit(0); }`,
    `if (sub === 'status') {`,
    `  let n = 0; try { n = parseInt(fs.readFileSync(C, 'utf8'), 10) || 0; } catch {}`,
    `  fs.writeFileSync(C, String(n + 1));`,
    `  console.log(fs.readFileSync(${JSON.stringify(dataPath)}, 'utf8')); process.exit(0);`,
    `}`,
    `if (sub === 'dispatch') {`,
    `  fs.writeFileSync(${JSON.stringify(pidPath)}, String(process.pid));`,
    `  console.log(JSON.stringify({ type: 'ack', run_id: 'footer-live-run', role: 'builder', ack: 'Assignment accepted.', jobs: [{ job_id: 'footer-live-run:1', worker_session_id: 'w1' }] }));`,
    // Forward test-enqueued lifecycle event lines as they appear (test-side
    // polling, not the extension). Never emits a return, so nothing here lets
    // a late return line mask whether the meter updated live.
    `  let sent = 0;`,
    `  setInterval(() => {`,
    `    let lines = [];`,
    `    try { lines = fs.readFileSync(EV, 'utf8').split('\\n').filter(Boolean); } catch {}`,
    `    while (sent < lines.length) { console.log(lines[sent]); sent += 1; }`,
    `  }, 40);`,
    `  process.stdin.resume();`,
    `}`,
  ].join('\n'), { mode: 0o755 });

  process.env.PATH = `${temp}:${process.env.PATH}`;
  process.env.ORCHESTRA_CONFIG = temp;
  process.env.PI_CODING_AGENT_SESSION_DIR = temp; // no worker transcripts
  writeFileSync(eventsPath, '');

  const jiti = createJiti(import.meta.url);
  const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');

  const hooks = new Map();
  const tools = new Map();
  let footer = '';
  await activate({
    on: (name, handler) => hooks.set(name, handler),
    registerTool: (t) => tools.set(t.name, t),
    registerCommand() {}, registerEntryRenderer() {},
    getActiveTools: () => [...tools.keys()],
    setActiveTools() {},
  });
  assert.ok(tools.has('orch_dispatch'), 'orch_dispatch tool must be registered');

  const ctx = {
    hasUI: true,
    sessionManager: {
      getSessionId: () => 'pi:footer-live',
      buildContextEntries: () => [],
      getBranch: () => [],
    },
    ui: {
      theme: { fg: (_c, t) => t, bold: (t) => t },
      setWidget: (_name, value) => { footer = (value ?? []).join('\n'); },
      notify() {},
    },
  };

  function pollCount() {
    try { return parseInt(readFileSync(counterPath, 'utf8'), 10) || 0; } catch { return 0; }
  }
  async function waitFor(label, fn, timeoutMs = 8000) {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      if (fn()) return;
      if (Date.now() > deadline) throw new Error(`timed out waiting for ${label}`);
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
  }
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  function enqueueEvent(jobId, status) {
    appendFileSync(eventsPath, JSON.stringify({
      type: 'event', session_id: 'pi:footer-live', run_id: 'footer-live-run', job_id: jobId, status,
    }) + '\n');
  }

  // Step 1: session_start with the builder running -> footer shows builder.
  writeFileSync(dataPath, JSON.stringify({ data: { session_jobs: [{ role: 'builder', status: 'running' }] } }));
  await hooks.get('session_start')({}, ctx);
  assert.match(footer, /builder/i, 'builder running appears after session_start');
  assert.doesNotMatch(footer, /verifier/i, 'verifier not active yet');

  // Step 2: dispatch ack leaves the run live (the fake never emits a return).
  const ack = await tools.get('orch_dispatch').execute('c1', { goal: 'build it', role: 'builder' }, undefined, undefined, ctx);
  assert.equal(ack.isError, false, `dispatch ack failed: ${JSON.stringify(ack)}`);
  await waitFor('ack footer refresh round-trip', () => pollCount() >= 2);
  assert.match(footer, /builder/i, 'footer still shows the running builder right after the ack');
  assert.doesNotMatch(footer, /verifier/i, 'verifier has not started yet at ack time');

  // Step 3: the builder finished and the auto-verify verifier is now running.
  // The verifier must become visible BEFORE any return, driven by a lifecycle
  // event line — there is no session_start/ack/return and no periodic poll to
  // trigger the refresh.
  writeFileSync(dataPath, JSON.stringify({ data: { session_jobs: [{ role: 'verifier', status: 'running' }] } }));
  enqueueEvent('footer-live-run:2', 'running');

  let sawVerifierLive = false;
  try {
    await waitFor('event-driven verifier in footer', () => /verifier/i.test(footer), 6000);
    sawVerifierLive = true;
  } catch {
    sawVerifierLive = false;
  }
  assert.ok(sawVerifierLive, 'follow-up verifier must appear in the footer during the live run, before any return, via lifecycle events');
  assert.doesNotMatch(footer, /builder/i, 'completed builder is no longer counted as running');

  // Step 4: no request storm. With the periodic timer removed, status is
  // queried only when an event arrives. Across a window longer than the old
  // 2s poll, with NO new events enqueued, the status count must not grow.
  const idleCount = pollCount();
  await sleep(2600);
  assert.equal(pollCount(), idleCount, 'no periodic status polling may occur between lifecycle events');

  // Step 5: a subsequent event still drives a refresh (the flat idle window
  // was not a dead channel).
  writeFileSync(dataPath, JSON.stringify({ data: { session_jobs: [{ role: 'builder', status: 'running' }] } }));
  enqueueEvent('footer-live-run:3', 'running');
  await waitFor('second event-driven refresh', () => pollCount() > idleCount && /builder/i.test(footer), 6000);

  // Step 6: session ownership / shutdown. After shutdown there is no active
  // session, so further events must NOT refresh the footer or query status.
  await hooks.get('session_shutdown')({}, ctx);
  const afterShutdown = pollCount();
  enqueueEvent('footer-live-run:4', 'running');
  await sleep(500);
  assert.equal(pollCount(), afterShutdown, 'events after shutdown must not query status for a non-current session');

  console.log('Pi event-driven live-run footer refresh passed');
} finally {
  try { process.kill(parseInt(readFileSync(pidPath, 'utf8'), 10)); } catch {}
  rmSync(temp, { recursive: true, force: true });
}
