import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createJiti } from 'jiti';

// Native usage/cost footer contract for the Pi translator, against a controlled
// `__session` core STUB (no real core, models, live Pi, or install).
//
// The footer's usage/cost is computed FRESH per status push: core supplies only
// opaque native worker session ids (native_session_ids) and a mode chip
// (mode_text); the adapter reads the live Pi JSONL transcripts for exactly those
// ids and prices them with the native current-model handle captured from the
// current context/event — NEVER from a saved worker-id set, a core snapshot
// cache, an mtime cache, or Orchestra config. The running-only meter stays the
// core-pushed text rendered verbatim.
//
// Proves:
//   - total input/output tokens and Pi-AI cost are summed across the supplied
//     cross-session ids and shown beside the core mode chip and verbatim meter;
//   - ids supplied by core are NOT cached: a changed id list updates the footer
//     immediately, and a changed transcript file updates it on the next push
//     (no file/mtime cache);
//   - a controlled status push missing the optional fields leaves only the core
//     text — no fabricated "$0.000"/default snapshot value appears;
//   - the session_shutdown owner guard clears the widget with no stale re-add.

// -- fixtures: a session dir with native worker transcripts -------------------

const sessionDir = mkdtempSync(join(tmpdir(), 'orch-usage-sessions-'));

// Transcripts are named `..._<id>.jsonl`; the id is what core supplies.
const TRANSCRIPTS = {
  'pi_alpha.jsonl': [
    { message: { usage: { input: 1000, output: 200, cacheRead: 50, cacheWrite: 0 } } },
    { message: { usage: { input: 500, output: 200, cacheRead: 0, cacheWrite: 0 } } },
  ],
  'pi_beta.jsonl': [{ message: { usage: { input: 250, output: 50, cacheRead: 0, cacheWrite: 0 } } }],
};
for (const [name, lines] of Object.entries(TRANSCRIPTS)) {
  writeFileSync(join(sessionDir, name), lines.map((o) => JSON.stringify(o)).join('\n'));
}
process.env.PI_CODING_AGENT_SESSION_DIR = sessionDir;

// A priced model handle (per-million-token rates). cacheRead/cacheWrite are 0 so
// cost is input + 2*output, computed here independently of the adapter.
const COST_RATES = { input: 1_000_000, output: 2_000_000, cacheRead: 0, cacheWrite: 0 };
function expectedCost(input, output) {
  return (COST_RATES.input / 1e6) * input + (COST_RATES.output / 1e6) * output;
}
function compact(value) {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
  if (abs >= 1_000) return `${(value / 1_000).toFixed(1).replace(/\.0$/, '')}k`;
  return String(value);
}
function usageSegment(input, output) {
  return `↑${compact(input)} ↓${compact(output)} $${expectedCost(input, output).toFixed(3)}`;
}

// -- controlled core stub (emits full status frames) --------------------------

const temp = mkdtempSync(join(tmpdir(), 'orch-usage-stub-'));
const replyPath = join(temp, 'scenario.json');
writeFileSync(replyPath, JSON.stringify({}));

const SHIM = `#!${process.execPath}
const fs = require('node:fs');
const args = process.argv.slice(2);
const replyPath = process.env.ORCH_USAGE_REPLY || '';
function scen() { try { return JSON.parse(fs.readFileSync(replyPath, 'utf8')); } catch (e) { return {}; } }
function write(obj) { process.stdout.write(JSON.stringify(obj) + '\\n'); }
function push() { const s = scen().status; if (s && typeof s.text === 'string') write({ kind: 'status', ...s }); }
if (args.includes('tool-info')) {
  process.stdout.write(JSON.stringify({
    dispatch: { label: 'D', description: 'Submit.', params: { goal: 'g.', additionalContext: 'c.', role: 'r.', taskLabel: 'l.' } },
    status: { label: 'S', description: 'Manage.', params: { action: 'a.', limit: 'n.', runId: 'i.' } },
    command: { description: '/orch' },
    actions: ['status', 'history', 'stop', 'help', 'doctor', 'roles'],
  }));
  process.exit(0);
}
if (args.includes('__session')) {
  push();
  let buf = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', (chunk) => {
    buf += chunk; let nl;
    while ((nl = buf.indexOf('\\n')) >= 0) {
      const line = buf.slice(0, nl); buf = buf.slice(nl + 1);
      if (!line.trim()) continue;
      let msg; try { msg = JSON.parse(line); } catch (e) { continue; }
      if (msg.kind === 'request') {
        const plan = scen()[msg.operation];
        if (plan && typeof plan.error === 'string') write({ kind: 'reply', id: msg.id, error: plan.error });
        else write({ kind: 'reply', id: msg.id, result: (plan && plan.result) || {} });
        push();
      }
    }
  });
  process.stdin.on('end', () => process.exit(0));
  return;
}
process.exit(0);
`;
writeFileSync(join(temp, 'python3'), SHIM, { mode: 0o755 });
process.env.PATH = `${temp}:${process.env.PATH}`;
process.env.ORCHESTRA_CONFIG = temp;
process.env.ORCH_USAGE_REPLY = replyPath;

const setScenario = (s) => writeFileSync(replyPath, JSON.stringify(s));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// -- minimal native context with a priced model + widget capture --------------

function makeCtx(sessionId) {
  const widgets = [];
  const ctx = {
    hasUI: true,
    model: { id: 'priced-test-model', cost: { ...COST_RATES } },
    sessionManager: {
      getSessionId: () => sessionId,
      buildContextEntries: () => [],
      getBranch: () => [],
    },
    ui: {
      theme: { fg: (_c, t) => t, bold: (t) => t },
      setWidget: (key, content, options) => widgets.push({ key, content, options }),
      notify: () => {},
    },
  };
  return {
    ctx,
    widgets,
    footer: () => {
      for (let i = widgets.length - 1; i >= 0; i -= 1) {
        if (widgets[i].key === 'orchestra') {
          const c = widgets[i].content;
          return c === undefined ? '' : Array.isArray(c) ? c.join('\n') : String(c);
        }
      }
      return '';
    },
    touched: () => widgets.filter((w) => w.key === 'orchestra').length,
  };
}

async function poll(label, fn, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (fn()) return;
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${label}`);
    await sleep(25);
  }
}

const hooks = new Map();

try {
  const jiti = createJiti(import.meta.url);
  const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');
  await activate({
    on: (name, handler) => hooks.set(name, handler),
    registerTool() {},
    registerCommand() {},
    registerEntryRenderer() {},
    appendEntry() {},
    getActiveTools: () => [],
    setActiveTools: () => {},
    sendUserMessage: () => {},
  });

  // --- usage summed across supplied cross-session ids + mode chip + verbatim --
  const inAB = 1750; // alpha(1500) + beta(250)
  const outAB = 450; // alpha(400) + beta(50)
  setScenario({
    'initial-mode': { result: { mode: 'on' } },
    status: { text: 'Orchestra: running builder×1', mode_text: '(Orchestra:on)', native_session_ids: ['alpha', 'beta'] },
  });
  const h = makeCtx('usage-session');
  await hooks.get('session_start')({}, h.ctx);
  const expectedAB = `${usageSegment(inAB, outAB)} (Orchestra:on) Orchestra: running builder×1`;
  await poll(`footer = ${expectedAB}`, () => h.footer() === expectedAB);
  assert.equal(h.footer(), expectedAB, 'usage totals both supplied cross-session ids, beside the core mode chip and verbatim meter');
  assert.ok(!/session_jobs|snapshot|default/.test(h.footer()), 'no structured/default snapshot value leaks into the footer');

  // --- ids are NOT cached: a changed id list updates immediately --------------
  const inA = 1500, outA = 400; // alpha only
  setScenario({
    'initial-mode': { result: { mode: 'on' } },
    status: { text: 'Orchestra: running builder×1', mode_text: '(Orchestra:on)', native_session_ids: ['alpha'] },
  });
  const h2 = makeCtx('usage-session-2');
  await hooks.get('session_start')({}, h2.ctx);
  const expectedA = `${usageSegment(inA, outA)} (Orchestra:on) Orchestra: running builder×1`;
  await poll(`footer = ${expectedA}`, () => h2.footer() === expectedA);
  assert.equal(h2.footer(), expectedA, 'a new core id list (alpha only) is reflected immediately — the prior beta id is not cached');

  // --- no file/mtime cache: editing a transcript updates the NEXT push --------
  writeFileSync(join(sessionDir, 'pi_beta.jsonl'), JSON.stringify({ message: { usage: { input: 50, output: 5, cacheRead: 0, cacheWrite: 0 } } }));
  const h3 = makeCtx('usage-session-3');
  setScenario({
    'initial-mode': { result: { mode: 'on' } },
    status: { text: 'Orchestra: idle', mode_text: '(Orchestra:on)', native_session_ids: ['beta'] },
  });
  await hooks.get('session_start')({}, h3.ctx);
  const expectedBetaEdited = `${usageSegment(50, 5)} (Orchestra:on) Orchestra: idle`;
  await poll(`footer = ${expectedBetaEdited}`, () => h3.footer() === expectedBetaEdited);
  assert.equal(h3.footer(), expectedBetaEdited, 'the freshly-written transcript value is read (no mtime/file cache)');

  // --- missing optional fields leave ONLY the core text (no $0.000 default) ---
  const h4 = makeCtx('usage-session-4');
  setScenario({ 'initial-mode': { result: { mode: 'on' } }, status: { text: 'Orchestra: running verifier×1' } });
  await hooks.get('session_start')({}, h4.ctx);
  await poll('text-only footer', () => h4.footer() === 'Orchestra: running verifier×1');
  assert.equal(h4.footer(), 'Orchestra: running verifier×1', 'a controlled stub push without mode_text/ids shows only the core text — no fabricated $0.000/default segment');

  // --- shutdown owner guard clears the widget and never re-adds ---------------
  const beforeClose = h3.touched();
  await hooks.get('session_shutdown')({}, h3.ctx);
  assert.equal(h3.footer(), '', 'session_shutdown clears the below-editor widget');
  // A late native fact for the closed session must not re-render a stale footer.
  await hooks.get('agent_settled')({}, h3.ctx);
  await sleep(120);
  assert.equal(h3.footer(), '', 'no stale footer re-appears after the owner context closed');
  assert.ok(beforeClose > 0, 'at least one footer render occurred before shutdown (guard exercised)');

  console.log('Pi native usage/cost footer contract passed');
} finally {
  rmSync(temp, { recursive: true, force: true });
  rmSync(sessionDir, { recursive: true, force: true });
}
