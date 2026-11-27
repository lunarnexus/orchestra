// Reusable controlled core `__session` stub for Pi translator tests.
//
// Writes a `python3` shim (a Node script named python3) into a temp bin dir and
// configures the environment so the real extension can be loaded and exercised
// against a controlled core WITHOUT real Python, models, live Pi, or install.
//
// The shim:
//   - `tool-info`            -> prints fixed core tool metadata (one-shot read).
//   - `__session --parent-session <id>` -> a persistent core session runtime:
//       reads newline-framed JSON requests on stdin, records each request frame
//       to the log file, and replies per the scenario in the `replyMap` (keyed by
//       operation), then optionally pushes a `status` frame. It also services
//       core-initiated `native_result` frames so get_parent_context / delivery
//       round-trips can be scripted.
//
// Scenario is provided as a JSON object (via env, file, or returned handle)
// mapping operation name -> one of:
//   { result: <object> }   emit {kind:'reply',id,result}
//   { error:  <string> }   emit {kind:'reply',id,error}
// plus optional keys:
//   statusText:   text pushed as {kind:'status',text} right after tool-info and
//                 after each handled request (exercises native rendering).
//   dispatchDelay: ms to delay the dispatch reply (models an out-of-band ack).
import { mkdtempSync, writeFileSync, rmSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

export const TOOL_INFO = {
  dispatch: { label: 'D', description: 'Submit.', params: { goal: 'g.', additionalContext: 'c.', role: 'r.', taskLabel: 'l.' } },
  status: { label: 'S', description: 'Manage.', params: { action: 'a.', limit: 'n.', runId: 'i.' } },
  command: { description: '/orch' },
  actions: ['status', 'history', 'stop', 'help', 'doctor', 'roles'],
};

const SHIM = `#!${process.execPath}
const fs = require('node:fs');
const args = process.argv.slice(2);
const log = process.env.ORCH_SESSION_LOG || '';
const replyPath = process.env.ORCH_SESSION_REPLY || '';
function record(obj) { if (log) { try { fs.appendFileSync(log, JSON.stringify(obj) + '\\n'); } catch (e) {} } }
function loadScenario() {
  if (!replyPath) return {};
  try { return JSON.parse(fs.readFileSync(replyPath, 'utf8')); } catch (e) { return {}; }
}
function write(obj) { process.stdout.write(JSON.stringify(obj) + '\\n'); }

if (args.includes('tool-info')) {
  process.stdout.write(${JSON.stringify(JSON.stringify(TOOL_INFO))});
  process.exit(0);
}

if (args.includes('__session')) {
  record({ frame: 'session_open', parent_session: args[args.indexOf('--parent-session') + 1] || '' });
  const scen0 = loadScenario();
  if (typeof scen0.statusText === 'string') write({ kind: 'status', text: scen0.statusText });
  let buf = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', (chunk) => {
    buf += chunk;
    let nl;
    while ((nl = buf.indexOf('\\n')) >= 0) {
      const line = buf.slice(0, nl); buf = buf.slice(nl + 1);
      if (!line.trim()) continue;
      let msg; try { msg = JSON.parse(line); } catch (e) { continue; }
      record({ frame: msg.kind, msg });
      if (msg.kind === 'request') {
        const scen = loadScenario();
        const plan = scen[msg.operation];
        // Core-initiated native operations, requested by the controlled core and
        // serviced by the adapter, are recorded as native_result frames.
        if (msg.operation === 'dispatch' && scen.emitContextRequest) {
          write({ kind: 'native_request', id: 'ctx-1', operation: 'get_parent_context', arguments: {} });
        }
        if (msg.operation === 'dispatch' && scen.emitDeliverReport) {
          write({ kind: 'native_request', id: 'deliver-1', operation: 'deliver_report', arguments: { text: scen.emitDeliverReport } });
        }
        const send = () => {
          if (!plan) write({ kind: 'reply', id: msg.id, error: 'operation ' + msg.operation + ' is not scripted' });
          else if (typeof plan.error === 'string') write({ kind: 'reply', id: msg.id, error: plan.error });
          else write({ kind: 'reply', id: msg.id, result: plan.result });
          if (typeof scen.statusText === 'string') write({ kind: 'status', text: scen.statusText });
        };
        if (msg.operation === 'dispatch' && scen.dispatchDelay) setTimeout(send, scen.dispatchDelay);
        else send();
      } else if (msg.kind === 'native_result') {
        // Recorded above; scripted responses observe the delivered context/report.
      }
    }
  });
  process.stdin.on('end', () => process.exit(0));
  return;
}
process.exit(0);
`;

export function makeSessionStub({ reply = {} } = {}) {
  const temp = mkdtempSync(join(tmpdir(), 'orch-session-stub-'));
  const log = join(temp, 'frames.log');
  const replyPath = join(temp, 'scenario.json');
  writeFileSync(log, '');
  writeFileSync(replyPath, JSON.stringify(reply));
  writeFileSync(join(temp, 'python3'), SHIM, { mode: 0o755 });
  process.env.PATH = `${temp}:${process.env.PATH}`;
  process.env.ORCHESTRA_CONFIG = temp;
  process.env.ORCH_SESSION_LOG = log;
  process.env.ORCH_SESSION_REPLY = replyPath;
  return {
    temp,
    setScenario(scenario) {
      writeFileSync(replyPath, JSON.stringify(scenario));
    },
    frames() {
      return readFileSync(log, 'utf8').split('\n').filter((l) => l.length > 0).map((l) => JSON.parse(l));
    },
    requests() {
      return this.frames().filter((f) => f.frame === 'request').map((f) => f.msg);
    },
    request(operation) {
      return this.requests().filter((r) => r.operation === operation).pop();
    },
    nativeResults() {
      return this.frames().filter((f) => f.frame === 'native_result').map((f) => f.msg);
    },
    reset() {
      writeFileSync(log, '');
    },
    cleanup() {
      rmSync(temp, { recursive: true, force: true });
    },
  };
}

// Standard minimal native UI context builder used across translator tests.
export function makeCtx(sessionId, { notes = [], entries = [], widgets = [] } = {}) {
  return {
    hasUI: true,
    sessionManager: {
      getSessionId: () => sessionId,
      buildContextEntries: () => entries,
      getBranch: () => [],
    },
    ui: {
      theme: { fg: (_c, t) => t, bold: (t) => t },
      setWidget: (key, content, options) => widgets.push({ key, content, options }),
      notify: (msg) => notes.push(String(msg)),
    },
  };
}
