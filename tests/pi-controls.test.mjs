import assert from 'node:assert/strict';
import { rmSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createJiti } from 'jiti';
import { createLiveCoreHost, makeContext, text } from './helpers/pi-live-core-host.mjs';

// Exercise the real extension's management surface against the REAL Orchestra 2
// core runtime and SQLite queue: the read-only `orch_status` tool (status,
// history, stop, help, doctor, roles), run/job identifiers in the dispatch
// acknowledgement, session-owned cancellation, foreign-session rejection, the
// configured default/role listing, and /orch on|off tool activation. The only
// controlled boundary is the fake-Pi model binary; dispatch/status/stop/history
// travel over the persistent `__session` connection to the real core. No live
// Pi sessions, global installs, or models.

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const host = createLiveCoreHost({ repoRoot });
const realCatalogPath = join(host.configDir, 'agent-catalog.yaml');

const HOST = 'pi:'; // adapter normalizes native id "C1" -> owning session "pi:C1"

const hooks = new Map();
const tools = new Map();

try {
  const jiti = createJiti(import.meta.url);
  const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');
  const commands = new Map();
  const steers = [];
  const entries = [];
  let active = [];
  let footer = '';
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
  assert.ok(tools.has('orch_dispatch'), 'orch_dispatch tool must be registered');
  assert.ok(tools.has('orch_status'), 'orch_status management tool must be registered');

  // The model-facing management tool stays read-only: no mutation parameters.
  const statusTool = tools.get('orch_status');
  const properties = statusTool.parameters?.properties ?? {};
  for (const banned of ['setting', 'value', 'mode', 'role']) {
    assert.ok(!(banned in properties), `orch_status must stay read-only: no ${banned} parameter`);
  }

  const footers = [];
  host.trackSession(HOST + 'C1');
  const ctx1 = makeContext('C1', { footers });
  await hooks.get('session_start')({}, ctx1);
  assert.ok(active.includes('orch_dispatch'), 'session start activates orch_dispatch');
  assert.ok(active.includes('orch_status'), 'session start activates orch_status');
  const footerText = () => footers[footers.length - 1] ?? '';

  // --- 1: the dispatch acknowledgement exposes run and job identifiers ----
  // The model turn is deliberately longer than the whole test: the ONLY way
  // this run reaches a terminal state is the owned stop, so the cancellation
  // below is a real cancellation of a live run, not a short completion racing
  // the stop.
  host.setScenario([{ match: 'slow one', text: 'slow one answer', delayMs: 20000 }, { match: '*', text: 'unused' }]);
  const ack1 = await tools.get('orch_dispatch').execute('c1', { goal: 'slow one', role: 'plain' }, undefined, undefined, ctx1);
  assert.equal(ack1.isError, false, `dispatch ack failed: ${JSON.stringify(ack1)}`);
  const ackText = text(ack1);
  const runIds = ackText.match(/\b[0-9a-f]{32}\b/g) ?? [];
  assert.ok(runIds.length > 0, `dispatch acknowledgement must expose the run id (got: ${ackText})`);
  const runId = runIds[0];
  host.trackRun(runId);
  assert.ok(ackText.includes(`${runId}:1`), 'dispatch acknowledgement must expose the job id');
  // Lifecycle-driven footer refresh, in the new core-owned model: the running
  // role meter is a status frame the CORE pushes (the adapter never derives
  // job truth). Claim -> running happens in the independent worker process, so
  // the meter refreshes when the same evaluator is woken by a native lifecycle
  // event (the adapter forwards `agent_start` on every model turn) — never by a
  // manual status tool call. Wait for the job to be durably running, forward the
  // native event, and assert the pushed meter names the running role.
  await host.poll('job durably running', () =>
    host.activeJobs(HOST + 'C1').some((j) => j.role === 'plain' && j.status === 'running'), 8000);
  hooks.get('agent_start')({}, ctx1);
  await host.poll('core-pushed footer meter shows the running role', () => /running.*plain|plain.*×/i.test(footerText()));

  // --- 2: the status action is readable session status, not raw JSON ------
  const statusResult = await statusTool.execute('c2', { action: 'status' }, undefined, undefined, ctx1);
  assert.equal(statusResult.isError, false, `status action failed: ${JSON.stringify(statusResult)}`);
  const statusText = text(statusResult);
  assert.ok(!statusText.trimStart().startsWith('{'), 'status must be readable text, not a raw JSON envelope');
  assert.match(statusText, /this session/i, 'status names the current session');
  assert.match(statusText, /plain/, 'the running job role appears in status');

  // --- 3: owned cancellation reaches a persisted terminal state -----------
  // Record the real cancellation overlap: the run is still durably RUNNING at
  // the instant the stop is issued, so the stop injects into live execution
  // rather than a run that already finished.
  assert.ok(
    host.activeJobs(HOST + 'C1').some((j) => j.run_id === runId && j.status === 'running'),
    'the owned run is actually running when the stop is issued (real cancellation overlap)',
  );
  const stopResult = await statusTool.execute('c3', { action: 'stop', runId }, undefined, undefined, ctx1);
  assert.equal(stopResult.isError, false, `owned stop must succeed: ${JSON.stringify(stopResult)}`);
  assert.match(text(stopResult), /stopped/i, 'stop reports the outcome');
  await host.poll('stopped run terminal', () => host.activeJobs(HOST + 'C1').length === 0);
  const afterStop = host.statusPayload(HOST + 'C1').last_completed;
  assert.equal(afterStop?.run_id, runId, 'the stopped run is the last completed run');
  assert.equal(afterStop?.failed, 1, 'cancellation is persisted as a failed job');
  assert.equal(afterStop?.succeeded, 0, 'a stopped run records no success');
  await host.poll('footer clears after the stopped run drains', () => !/plain/i.test(footerText()));

  // --- 4: another session cannot cancel this session's run ----------------
  // Foreign-CORE rejection (not the adapter's stale-context guard, which the
  // source owner tests independently): the core connection is bound to its
  // parent_session at session_start, so a genuine foreign attempt needs a
  // SECOND activation whose connection is bound to native C9. The stop then
  // travels to the core as pi:C9 and the core rejects the foreign run; C1's
  // independent worker keeps running (start_new_session) and finishes honestly.
  host.setScenario([{ match: 'slow two', text: 'slow two answer', delayMs: 9000 }, { match: '*', text: 'unused' }]);
  const ack2 = await tools.get('orch_dispatch').execute('c4', { goal: 'slow two', role: 'plain' }, undefined, undefined, ctx1);
  assert.equal(ack2.isError, false, `second dispatch ack failed: ${JSON.stringify(ack2)}`);
  const runId2 = (text(ack2).match(/\b[0-9a-f]{32}\b/g) ?? [])[0];
  assert.ok(runId2, 'the second acknowledgement exposes its run id');
  host.trackRun(runId2);
  await host.poll('second job durably running', () =>
    host.activeJobs(HOST + 'C1').some((j) => j.run_id === runId2 && j.role === 'plain' && j.status === 'running'), 8000);
  // Second activation: a new core connection bound to pi:C9 replaces the C1
  // connection; the independent run worker outlives the replaced connection.
  const ctx9 = makeContext('C9');
  host.trackSession(HOST + 'C9');
  await hooks.get('session_start')({}, ctx9);
  const foreign = await statusTool.execute('c5', { action: 'stop', runId: runId2 }, undefined, undefined, ctx9);
  assert.equal(foreign.isError, true, 'a foreign session must not cancel another session run');
  // Core ownership rejection (not the adapter's stale-context guard): the stop
  // reached the core as pi:C9 and the core refused another session's run.
  assert.match(text(foreign), /not owned by session/i, 'the core rejects the foreign run by ownership');
  // Re-bind C1 (closes the C9 connection) so the remaining C1-owned sections
  // keep working; the un-cancelled C1 run is untouched and finishes honestly.
  await hooks.get('session_start')({}, ctx1);
  hooks.get('agent_start')({}, ctx1);
  await host.poll('un-cancelled run terminal', () => host.activeJobs(HOST + 'C1').length === 0);
  const afterForeign = host.statusPayload(HOST + 'C1').last_completed;
  assert.equal(afterForeign?.run_id, runId2, 'the untouched run is the last completed run');
  assert.equal(afterForeign?.succeeded, 1, 'the un-cancelled run still succeeds');

  // --- 5: history honours a positive limit --------------------------------
  const history = await statusTool.execute('c6', { action: 'history', limit: 1 }, undefined, undefined, ctx1);
  assert.equal(history.isError, false, `history action failed: ${JSON.stringify(history)}`);
  const historyText = text(history);
  assert.ok(historyText.includes(runId2), 'history lists the newest completed run');
  assert.ok(!historyText.includes(runId), 'history respects the requested limit');
  const badLimit = await statusTool.execute('c7', { action: 'history', limit: 0 }, undefined, undefined, ctx1);
  assert.equal(badLimit.isError, true, 'history limit must be a positive integer');
  const badStop = await statusTool.execute('c8', { action: 'stop' }, undefined, undefined, ctx1);
  assert.equal(badStop.isError, true, 'stop requires a run id');

  // --- 6: read-only role listing ------------------------------------------
  const catalogBefore = readFileSync(realCatalogPath, 'utf8');
  const roles = await statusTool.execute('c9', { action: 'roles' }, undefined, undefined, ctx1);
  assert.equal(roles.isError, false, `roles action failed: ${JSON.stringify(roles)}`);
  const rolesText = text(roles);
  for (const role of ['builder', 'verifier', 'plain']) {
    assert.ok(rolesText.includes(role), `role listing includes ${role}`);
  }
  assert.match(rolesText, /default/i, 'role listing reports the default role');
  assert.equal(readFileSync(realCatalogPath, 'utf8'), catalogBefore, 'role listing never mutates the catalog');

  // --- 7: help and diagnostics through the same tool ----------------------
  const help = await statusTool.execute('c10', { action: 'help' }, undefined, undefined, ctx1);
  assert.equal(help.isError, false, `help action failed: ${JSON.stringify(help)}`);
  assert.match(text(help), /dispatch/i, 'help describes the operations');
  const doctor = await statusTool.execute('c11', { action: 'doctor' }, undefined, undefined, ctx1);
  assert.equal(doctor.isError, false, `doctor action failed: ${JSON.stringify(doctor)}`);
  // The tool-path doctor surfaces the per-check core report (the "all checks
  // passed" summary is a CLI-command-only line, never emitted over the
  // connection). Assert the real checks are present and none report a problem.
  const doctorText = text(doctor);
  assert.match(doctorText, /Orchestra doctor/, 'doctor names the core diagnostics report');
  assert.match(doctorText, /config: ok/, 'doctor reports the loaded core config');
  assert.doesNotMatch(doctorText, /problem:/i, 'doctor reports no problems');

  // --- 8: /orch on|off activation covers both tools -----------------------
  const command = commands.get('orch');
  assert.ok(command, 'the /orch command must be registered');
  await command.handler('off', ctx1);
  assert.ok(!active.includes('orch_dispatch') && !active.includes('orch_status'), '/orch off deactivates both tools');
  await command.handler('on', ctx1);
  assert.ok(active.includes('orch_dispatch') && active.includes('orch_status'), '/orch on activates both tools');

  // --- 9: /orch status renders readable text, not the JSON envelope -------
  entries.length = 0;
  await command.handler('status', ctx1);
  const shown = entries.filter((entry) => entry.type === 'orchestra-output').map((entry) => entry.data?.text ?? '').join('\n');
  assert.ok(shown.length > 0, '/orch status must produce output');
  assert.ok(!shown.trimStart().startsWith('{'), '/orch status must render readable text, not raw JSON');
  assert.match(shown, /this session/i, 'the rendered core status is what the user sees');
  assert.doesNotMatch(shown, /"session_jobs"/, 'structured status fields stay out of user output');

  // Every report that returns is addressed to the owning session (pi:C1): the
  // cancelled run produced exactly the durable failed return shown, and no
  // return ever leaked to the foreign session (pi:C9).
  await host.poll('a return is delivered to the owning session', () => steers.length >= 1);
  for (const steer of steers) {
    assert.match(steer, /\(pi:C1\)/, 'every return is addressed to the owning pi:C1 session');
    assert.doesNotMatch(steer, /pi:C9/, 'no return leaks to the foreign pi:C9 session');
  }

  console.log('Pi connected controls passed');
} finally {
  try { hooks.get('session_shutdown')({}, makeContext('C1')); } catch { /* best-effort: close the core connection first */ }
  await host.teardown();
  try { rmSync(host.temp, { recursive: true, force: true }); } catch { /* already removed */ }
}
