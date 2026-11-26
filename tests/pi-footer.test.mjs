import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createJiti } from 'jiti';

// Exercise the real extension callback. Only its Python/host boundaries are
// controlled; no live Pi sessions, global settings, or models are involved.
// Covers the running-only role meter, readable `/orch status` rendering from
// one core status response, and the event-free footer refresh that runs once
// per agent start without any timer, watcher, or stale cross-session update.
const temp = mkdtempSync(join(tmpdir(), 'orchestra-footer-'));
const statusPath = join(temp, 'status.json');
const delayPath = join(temp, 'delay');
const callsPath = join(temp, 'status-calls.log');
const failPath = join(temp, 'fail');

// Controlled core boundary: prints the scripted status payload, optionally
// delayed (to hold a response in flight across a session switch), optionally
// failing, and records every status invocation.
writeFileSync(join(temp, 'python3'), `#!${process.execPath}
const fs = require('node:fs');
const argv = process.argv.join(' ');
if (argv.includes('tool-info')) {
  process.stdout.write(JSON.stringify({dispatch:{label:"Orchestra Dispatch",description:"Submit.",params:{goal:"Assignment text.",additionalContext:"Extra context.",role:"Role name.",taskLabel:"Short label."}},status:{label:"Orchestra Status",description:"Manage.",params:{action:"Action.",limit:"Limit.",runId:"Run ID."}},command:{description:"/orch help|on|off|doctor|status|history|do|stop"},actions:["status","history","stop","help","doctor","roles"]}));
  process.exit(0);
}
if (argv.includes('initial-mode')) { console.log('on'); process.exit(0); }
fs.appendFileSync(${JSON.stringify(callsPath)}, 'status\\n');
if (fs.existsSync(${JSON.stringify(failPath)})) {
  process.stderr.write(fs.readFileSync(${JSON.stringify(failPath)}, 'utf8'));
  process.exit(3);
}
const delay = fs.existsSync(${JSON.stringify(delayPath)})
  ? Number(fs.readFileSync(${JSON.stringify(delayPath)}, 'utf8'))
  : 0;
const payload = fs.readFileSync(${JSON.stringify(statusPath)}, 'utf8');
setTimeout(() => console.log(payload), delay);
`, { mode: 0o755 });
writeFileSync(statusPath, JSON.stringify({ rendered: 'Orchestra: on\n', data: { session_jobs: [] } }));
writeFileSync(callsPath, '');

process.env.PATH = `${temp}:${process.env.PATH}`;
process.env.ORCHESTRA_CONFIG = temp;

function writeStatus(payload) {
  writeFileSync(statusPath, JSON.stringify(payload));
}

function statusCalls() {
  return readFileSync(callsPath, 'utf8').split('\n').filter(Boolean).length;
}

async function poll(label, fn, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (fn()) return;
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${label}`);
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
}

try {
  const jiti = createJiti(import.meta.url);
  const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');
  const hooks = new Map();
  const commands = new Map();
  const entries = [];
  let tools = [];
  let footer;
  await activate({
    on: (name, handler) => hooks.set(name, handler),
    registerTool() {},
    registerCommand: (name, definition) => commands.set(name, definition),
    registerEntryRenderer() {},
    appendEntry: (type, data) => entries.push({ type, data }),
    getActiveTools: () => tools,
    setActiveTools: (value) => { tools = value; },
  });
  function makeContext(sessionId) {
    return {
      hasUI: true,
      sessionManager: { getSessionId: () => sessionId },
      ui: {
        theme: { fg: (_color, text) => text, bold: (text) => text },
        setWidget: (_name, value) => { footer = value ? value.join('\n') : undefined; },
        notify: () => {},
      },
    };
  }
  const ctx1 = makeContext('isolated-footer-test');
  const ctx2 = makeContext('isolated-footer-other');

  async function refresh(jobs) {
    writeStatus({ rendered: 'Orchestra: on\n', data: { session_jobs: jobs } });
    await hooks.get('session_start')({}, ctx1);
    return footer;
  }

  // --- running-only role meter -------------------------------------------
  let text = await refresh([
    { role: 'builder', status: 'running' },
    { role: 'verifier', status: 'pending' },
  ]);
  assert.match(text, /builder/i);
  assert.doesNotMatch(text, /verifier/i, 'pending verifier must not appear active');
  text = await refresh([{ role: 'verifier', status: 'running' }]);
  assert.match(text, /verifier/i, 'verifier appears after it starts');
  text = await refresh([{ role: 'builder', status: 'pending' }]);
  assert.doesNotMatch(text, /builder/i, 'pending work is not running work');

  // --- /orch status renders the core response, one call serves both -------
  writeStatus({
    rendered: 'Orchestra: on\n\nThis session:\n  #1     builder     running   run deadbeef\n',
    data: { session_jobs: [{ role: 'builder', status: 'running' }] },
  });
  const beforeStatus = statusCalls();
  entries.length = 0;
  await commands.get('orch').handler('status', ctx1);
  const shown = entries.filter((entry) => entry.type === 'orchestra-output').map((entry) => entry.data?.text ?? '').join('\n');
  assert.match(shown, /This session:/, 'the rendered core status text is displayed');
  assert.doesNotMatch(shown, /"session_jobs"/, 'the structured status envelope stays out of user output');
  assert.ok(!shown.trimStart().startsWith('{'), 'no raw JSON is shown for /orch status');
  assert.equal(statusCalls() - beforeStatus, 1, 'one core status call serves both the display and the footer');
  assert.match(footer, /builder/i, 'the footer is updated from the same status response');

  // --- command errors are surfaced ----------------------------------------
  writeFileSync(failPath, 'status boundary exploded');
  entries.length = 0;
  await commands.get('orch').handler('status', ctx1);
  const errorShown = entries.filter((entry) => entry.type === 'orchestra-output').map((entry) => entry.data?.text ?? '').join('\n');
  assert.match(errorShown, /status boundary exploded/, 'a failing status command surfaces core stderr');
  rmSync(failPath, { force: true });

  // --- event-free refresh: persisted state changed with no lifecycle event -
  writeStatus({ rendered: 'Orchestra: on\n', data: { session_jobs: [{ role: 'builder', status: 'running' }] } });
  await hooks.get('session_start')({}, ctx1);
  assert.match(footer, /builder/i, 'the running role is shown before the state change');
  writeStatus({ rendered: 'Orchestra: on\n', data: { session_jobs: [] } });
  assert.match(footer, /builder/i, 'nothing has refreshed the footer since the state changed');
  const beforeStart = statusCalls();
  await hooks.get('before_agent_start')({ messageType: 'user', prompt: 'next turn' }, ctx1);
  assert.equal(statusCalls() - beforeStart, 1, 'exactly one status refresh per agent run start');
  assert.doesNotMatch(footer, /builder/i, 'stale running counts clear at the next agent run start');

  // --- a switched session never receives a stale refresh ------------------
  writeStatus({ rendered: 'Orchestra: on\n', data: { session_jobs: [{ role: 'verifier', status: 'running' }] } });
  await hooks.get('session_start')({}, ctx1);
  assert.match(footer, /verifier/i, 'session one shows its running verifier');
  writeFileSync(delayPath, '600');
  writeStatus({ rendered: 'Orchestra: on\n', data: { session_jobs: [{ role: 'builder', status: 'running' }] } });
  const beforeSwitch = statusCalls();
  const inFlight = hooks.get('before_agent_start')({ messageType: 'user', prompt: 'switch away' }, ctx1);
  await poll('status read started before the session switch', () => statusCalls() > beforeSwitch);
  rmSync(delayPath, { force: true });
  writeStatus({ rendered: 'Orchestra: on\n', data: { session_jobs: [] } });
  await hooks.get('session_start')({}, ctx2);
  assert.doesNotMatch(footer, /builder|verifier/i, 'the switched-to session shows its own empty state');
  await inFlight;
  assert.doesNotMatch(footer, /builder/i, 'a response for the session that was switched away from is discarded');

  console.log('Pi footer running-only regression passed');
} finally {
  rmSync(temp, { recursive: true, force: true });
}
