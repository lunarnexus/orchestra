import assert from 'node:assert/strict';
import { rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createJiti } from 'jiti';
import { createLiveCoreHost, makeContext, text } from './helpers/pi-live-core-host.mjs';

// Connected session-return consolidation, against the REAL Python core
// (real queue/SQLite, real per-run detached __run workers, real native report
// delivery) with the only controlled boundary being the fake-Pi model binary.
// Covers: an automatic verifier follow-up consolidated into ONE return with
// both answers; a later run that does not repeat earlier delivered results;
// overlapping runs that produce no premature/duplicate report; failure stays
// visible with the child's actual error; and session isolation. The native
// host (fake) is the real delivery recipient, so a delivered report plus the
// persisted terminal end-state are both proven.

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const host = createLiveCoreHost({ repoRoot });

function realStatus(sessionId) {
  return host.activeJobs(sessionId);
}

const hooks = new Map();
const tools = new Map();

try {
  const jiti = createJiti(import.meta.url);
  const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');
  const steers = [];
  const notifications = [];
  await activate({
    on: (name, handler) => hooks.set(name, handler),
    registerTool: (t) => tools.set(t.name, t),
    registerCommand() {}, registerEntryRenderer() {},
    getActiveTools: () => [...tools.keys()],
    setActiveTools() {},
    sendUserMessage: (message) => steers.push(String(message)),
  });
  assert.ok(tools.has('orch_dispatch'), 'orch_dispatch tool must be registered');

  // The owning parent session is normalized to `pi:<raw>` by the adapter from
  // native session_start; durable status queries must use that bound identity.
  const S1 = 'pi:S1', S2 = 'pi:S2', S3 = 'pi:S3';
  host.trackSession(S1); host.trackSession(S2); host.trackSession(S3);
  await hooks.get('session_start')({}, makeContext('S1'));

  // --- journey 1: one run with an automatic verifier follow-up ----------
  host.setScenario([
    { match: 'one task', text: 'one builder answer' },
    { match: 'two task', text: 'two builder answer' },
    { match: '*', text: 'verifier: confirmed' },
  ]);
  const ack1 = await tools.get('orch_dispatch').execute('c1', { goal: 'one task', role: 'builder' }, undefined, undefined, makeContext('S1'));
  assert.equal(ack1.isError, false, `dispatch 1 ack failed: ${JSON.stringify(ack1)}`);
  const ackText1 = text(ack1);
  host.trackRun(ackText1);
  assert.match(ackText1, /builder/i, 'ack must name the role');
  assert.match(ackText1, /poll/i, 'ack must tell the orchestrator not to poll (asserted by concept so rewording is allowed)');
  assert.match(ackText1, /own(s|ed)?\b|delegat/i, 'ack must convey the subagent owns the delegated scope');
  assert.match(ackText1, /edit|independent|verify/i, 'ack must forbid parent edits or independent verification of the delegated scope');
  assert.match(ackText1, /sleep/i, 'ack must forbid sleeping, not only polling');
  assert.match(ackText1, /end (your|the) (response|turn)|your own|independent work|continue/i, 'ack must tell the orchestrator to continue independent work or end its response');

  await host.poll('consolidated S1 return', () => steers.length > 0);
  assert.equal(steers.length, 1, 'exactly one return prompt after all session jobs (builder + verifier) finish');
  const first = steers[0];
  assert.match(first, /one builder answer/, 'actual child response is delivered');
  assert.match(first, /verifier: confirmed/, 'follow-up verifier answer is delivered in the same prompt');
  assert.match(first, /do not duplicate the work/i, 'one applicable hint is included');
  assert.doesNotMatch(first, /Jobs:/, 'redundant Jobs heading is absent');
  assert.doesNotMatch(first, /finished \(/, 'duplicate per-run summary line is absent');
  // Scope-limitation is now an owner-approved core note, present and singular:
  // the report states the runs it covers exactly once.
  assert.match(first, /Runs:/, 'the report lists the run(s) it covers');
  assert.equal(first.match(/This return /g)?.length, 1, 'exactly one scope note is included');
  // Structural separation is a core-owned property: each delivered job renders
  // as its own delimited `#N role [status] job-id` header block, so a builder ->
  // verifier chain is separable without inferring boundaries from prose.
  const stepHeaders = first.match(/^\s*#\d+ /gm) || [];
  assert.ok(
    stepHeaders.length >= 2,
    `each delivered job must render as a separately delimited header (got ${stepHeaders.length})`,
  );
  const stepBlocks = first.split(/^\s*#\d+ /m);
  const builderBlock = stepBlocks.find((b) => b.includes('one builder answer'));
  const verifierBlock = stepBlocks.find((b) => b.includes('verifier: confirmed'));
  assert.ok(builderBlock, 'builder response is delivered inside a header block');
  assert.ok(verifierBlock, 'verifier response is delivered inside a header block');
  assert.notEqual(builderBlock, verifierBlock, 'builder and verifier render in different blocks');
  assert.equal(realStatus(S1).length, 0, 'no session jobs remain running after the return');

  // --- journey 2: a later run must not repeat earlier delivered results --
  const steerCountBefore = steers.length;
  const ack2 = await tools.get('orch_dispatch').execute('c2', { goal: 'two task', role: 'builder' }, undefined, undefined, makeContext('S1'));
  assert.equal(ack2.isError, false);
  host.trackRun(text(ack2));
  await host.poll('second S1 return', () => steers.length > steerCountBefore);
  assert.equal(steers.length, steerCountBefore + 1, 'one return for the second run');
  assert.match(steers[steers.length - 1], /two builder answer/);
  assert.doesNotMatch(steers[steers.length - 1], /one builder answer/, 'earlier delivered results are not repeated');

  // --- journey 3: overlapping runs, one completing early -----------------
  // Overlap is driven by the controlled model boundary (beta answers late), not
  // a transport launch delay: alpha reaches a terminal end-state while beta is
  // still active, and only then does ONE consolidated report go out.
  const ctx2 = makeContext('S2');
  // Bind the adapter's single connection to the S2 native session before
  // dispatching S2 jobs: the ownership guard only honors a tool request from
  // the session that currently owns the core connection.
  await hooks.get('session_start')({}, ctx2);
  host.setScenario([
    { match: 'alpha task', text: 'alpha actual answer' },
    { match: 'beta task', text: 'beta actual answer', delayMs: 900 },
    { match: '*', text: 'verifier: confirmed' },
  ]);
  const s2Baseline = steers.length;
  const ackA = await tools.get('orch_dispatch').execute('c3', { goal: 'alpha task', role: 'plain' }, undefined, undefined, ctx2);
  assert.equal(ackA.isError, false, `alpha ack failed: ${JSON.stringify(ackA)}`);
  const alphaRun = host.trackRun(text(ackA));
  const ackB = await tools.get('orch_dispatch').execute('c4', { goal: 'beta task', role: 'plain' }, undefined, undefined, ctx2);
  assert.equal(ackB.isError, false, `beta ack failed: ${JSON.stringify(ackB)}`);
  const betaRun = host.trackRun(text(ackB));
  // Overlap window: beta is genuinely running while alpha has already reached a
  // terminal end-state. Read the durable queue by run id so the early-completing
  // run is proven drained WHILE a live sibling is still active. (The previous
  // `every(job.status !== 'running')` predicate was trivially true for pending
  // jobs and only became true once every job finished — i.e. after the report
  // had already fired — so it could not observe the overlap it claimed to prove.)
  await host.poll('beta running while alpha drained (overlap window)', () => {
    const jobs = realStatus(S2);
    return jobs.some((j) => j.run_id === betaRun && j.status === 'running')
      && !jobs.some((j) => j.run_id === alphaRun);
  });
  assert.equal(steers.length, s2Baseline,
    'no early wake while a live sibling run is still active');
  assert.doesNotMatch(steers.join('\n'), /alpha actual answer|beta actual answer/, 'neither answer delivered before all runs finish');

  await host.poll('consolidated S2 return', () => steers.some((s) => s.includes('alpha actual answer')));
  const s2Steer = steers.find((s) => s.includes('alpha actual answer'));
  assert.ok(s2Steer, 'one wake after both runs finish');
  assert.match(s2Steer, /beta actual answer/, 'both actual child answers in one prompt');
  assert.equal(steers.filter((s) => s === s2Steer).length, 1, 'single wake, not repeated');
  assert.doesNotMatch(s2Steer, /Jobs:/);
  assert.match(s2Steer, /All jobs succeeded|do not duplicate the work/i);
  // Separation is generic, not verifier-specific: a plain two-job chain (no
  // verifier) also renders as two separately delimited header blocks.
  const s2Headers = s2Steer.match(/^\s*#\d+ /gm) || [];
  assert.ok(s2Headers.length >= 2, 'plain two-job chain renders as delimited blocks');
  const s2Blocks = s2Steer.split(/^\s*#\d+ /m);
  const alphaBlock = s2Blocks.find((b) => b.includes('alpha actual answer'));
  const betaBlock = s2Blocks.find((b) => b.includes('beta actual answer'));
  assert.ok(alphaBlock && betaBlock && alphaBlock !== betaBlock, 'alpha and beta render in different blocks');

  // --- journey 4: other sessions are isolated; failures stay visible ----
  const ctx3 = makeContext('S3');
  // Rebind the connection to the S3 native session for the isolation/failure run.
  await hooks.get('session_start')({}, ctx3);
  host.setScenario([
    { match: 'gamma task', fail: true },
    { match: '*', text: 'verifier: confirmed' },
  ]);
  const s3Baseline = steers.length;
  const ack3 = await tools.get('orch_dispatch').execute('c5', { goal: 'gamma task', role: 'plain' }, undefined, undefined, ctx3);
  assert.equal(ack3.isError, false, 'gamma ack failed');
  host.trackRun(text(ack3));
  await host.poll('S3 failure return', () => steers.some((s) => s.includes('failed')));
  const s3Steer = steers.find((s) => s.includes('failed'));
  assert.match(s3Steer, /failed/, 'failure stays visible');
  assert.match(s3Steer, /prompt rejected: fake failure/, 'actual failure detail from the child is preserved');
  assert.match(s3Steer, /harness or execution error/i, 'failure hint is included');
  assert.doesNotMatch(s3Steer, /one builder answer|alpha actual answer/, 'other sessions are excluded');
  assert.equal(steers.length, s3Baseline + 1, 'failure delivers once');

  // Success proof: every dispatched run reached a persisted terminal end-state.
  await host.waitForCompletedEndState();

  console.log('Pi session-return consolidation passed');
} finally {
  // Shut the core CONNECTION down first (session_shutdown: signals session_end
  // and closes the persistent connection), then stop only this test's own
  // still-active runs. Independent workers are never killed by the shutdown.
  try { hooks.get('session_shutdown')({}, makeContext('S1')); } catch { /* best-effort */ }
  await host.teardown();
  try { rmSync(host.temp, { recursive: true, force: true }); } catch { /* already removed */ }
}
