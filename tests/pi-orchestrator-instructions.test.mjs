import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createJiti } from 'jiti';
import { makeSessionStub, makeCtx } from './helpers/orchestra-session-stub.mjs';
import { createLiveCoreHost, makeContext } from './helpers/pi-live-core-host.mjs';

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..');

// Pi-native half of the universal core orchestrator SPSI. Against a controlled
// core stub (no real core, models, live Pi, or install) this proves the
// before_agent_start handler:
//   1. requests core operation 'orchestrator-instructions' with {} arguments
//      and appends the returned instructions to the NATIVE event.systemPrompt,
//      preserving the original prompt text;
//   2. injects per-turn from event.systemPrompt only (no cache): repeated turns
//      with the same base never accumulate or duplicate the instructions;
//   3. leaves the native prompt untouched (no return) on empty instructions
//      (core mode off / no skills);
//   4. relays the actual core error (e.g. missing configured skill) visibly and
//      does NOT silently fall back or inject on failure;
//   5. never issues the request nor injects through a stale native session that
//      no longer owns the connection;
//   6. a flagged Orchestra child early-returns: no before_agent_start hook, so
//      no injection at all.

// A parent harness activation needs an unmarked dispatch budget; a subagent
// session may inherit a marked budget from its launcher, so clear it first.
delete process.env.ORCHESTRA_DISPATCH_BUDGET;

// ---------------------------------------------------------------------------
// CONNECTED (real Python core) half of the orchestrator SPSI. The stub below
// proves the adapter<->transport contract but never runs Python or resolves a
// real SKILL.md. This journey runs the SAME before_agent_start path against the
// real core connection (`python3 -m orchestra __session` over real transport
// frames, only the model is the scripted fake-pi) with a temporary catalog whose
// reserved `orchestrator` role names ONE controlled skill. It proves the real
// core resolves that skill's text into the native system-prompt return that
// preserves the original prompt (appended exactly once), that a repeated turn
// never accumulates or duplicates it, and that a core "off" mode leaves the
// native prompt untouched. The flagged-child no-hook path is already covered by
// the stub block (test 6) and is intentionally not duplicated here.
//
// It runs FIRST so the helper resolves the real interpreter on a clean PATH
// before the stub prepends its shim; teardown restores the ambient PATH.
// ---------------------------------------------------------------------------
async function connectedCoreJourney() {
  const SKILL_TEXT = 'CONNECTED-ORCHESTRATOR-SKILL-MARKER';
  const catalog = [
    'default_role: builder',
    'model_limits:',
    '  "m1":',
    '    concurrency: 3',
    'roles:',
    '  orchestrator:',
    '    skills: [controlledskill]',
    '  builder:',
    '    enabled: manual',
    '    harness_config: pi',
    '    model: "m1"',
    '    env: {}',
    '    skills: []',
    '    dispatch_hint: Build the assigned change and return the result.',
    '    auto_verify: false',
    '',
  ].join('\n');

  const host = createLiveCoreHost({ repoRoot, catalog });
  try {
    // Known skill text fixture under the temp config the real core resolves.
    mkdirSync(join(host.configDir, 'skills', 'controlledskill'), { recursive: true });
    writeFileSync(join(host.configDir, 'skills', 'controlledskill', 'SKILL.md'), SKILL_TEXT);

    const hooks = new Map();
    const tools = new Map();
    const commands = new Map();
    let active = [];
    const pi = {
      on: (name, handler) => hooks.set(name, handler),
      registerTool: (t) => tools.set(t.name, t),
      registerCommand: (name, def) => commands.set(name, def),
      registerEntryRenderer() {},
      appendEntry() {},
      getActiveTools: () => [...active],
      setActiveTools: (list) => { active = [...list]; },
      sendUserMessage() {},
    };
    const jiti = createJiti(import.meta.url);
    const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');
    await activate(pi);
    assert.ok(hooks.has('before_agent_start'), 'before_agent_start registered against the live core');

    const liveCtx = makeContext('instr-live-connected');
    await hooks.get('session_start')({}, liveCtx);
    const fire = () => hooks.get('before_agent_start')(
      { type: 'before_agent_start', messageType: 'user', prompt: 'go', systemPrompt: 'BASE NATIVE PROMPT' },
      liveCtx,
    );

    // 1. the real core resolves the configured skill text into the return.
    const first = await fire();
    assert.ok(first && typeof first.systemPrompt === 'string',
      'the connected core must yield a systemPrompt from the real skill resolver');
    assert.ok(first.systemPrompt.startsWith('BASE NATIVE PROMPT'),
      `the original native prompt must be preserved, got: ${JSON.stringify(first.systemPrompt)}`);
    assert.equal(first.systemPrompt.split(SKILL_TEXT).length - 1, 1,
      'the configured skill text must be injected exactly once by the real core');

    // 2. a repeated turn does not accumulate or duplicate the skill text.
    const second = await fire();
    assert.equal(first.systemPrompt, second.systemPrompt,
      'a repeated identical turn must yield an identical prompt (no accumulation)');
    assert.equal(second.systemPrompt.split(SKILL_TEXT).length - 1, 1,
      'the skill text must never be duplicated across turns');

    // 3. core mode off (a real core state change) leaves the native prompt alone.
    await commands.get('orch').handler('off', liveCtx);
    const off = await fire();
    assert.ok(!off || off.systemPrompt === undefined,
      'a core "off" mode must leave the native prompt untouched');

    // The real core genuinely served the request over the live connection.
    assert.ok(host.requests('orchestrator-instructions').length >= 1,
      'the real core connection received the orchestrator-instructions request');

    await hooks.get('session_shutdown')({}, liveCtx);
    console.log('Pi orchestrator-instructions CONNECTED (real core) journey passed');
  } finally {
    await host.teardown();
  }
}

await connectedCoreJourney();

const stub = makeSessionStub({
  reply: {
    'initial-mode': { result: { mode: 'on', text: 'on' } },
    'orchestrator-instructions': { result: { instructions: 'CORE SPSI MARKER' } },
  },
});

function makeHarness() {
  const hooks = new Map();
  let active = [];
  const pi = {
    on: (name, handler) => hooks.set(name, handler),
    registerTool: (t) => { active.push(t.name); },
    registerCommand() {},
    registerEntryRenderer() {},
    appendEntry() {},
    getActiveTools: () => [...active],
    setActiveTools: (list) => { active = [...list]; },
    sendUserMessage() {},
  };
  return { hooks, pi };
}

function beforeAgent(hooks, ctx, systemPrompt) {
  return hooks.get('before_agent_start')(
    { type: 'before_agent_start', messageType: 'user', prompt: 'do the thing', systemPrompt },
    ctx,
  );
}

const countOccurrences = (haystack, needle) => haystack.split(needle).length - 1;

try {
  const jiti = createJiti(import.meta.url);
  const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');
  const { hooks, pi } = makeHarness();
  await activate(pi);
  assert.ok(hooks.has('before_agent_start'), 'before_agent_start handler registered');

  // -- 1. explicit core instructions appended to the preserved native prompt --
  {
    stub.reset();
    const notes = [];
    const ctx = makeCtx('instr-own', { notes });
    await hooks.get('session_start')({}, ctx);
    const result = await beforeAgent(hooks, ctx, 'BASE NATIVE PROMPT');
    assert.ok(result && typeof result.systemPrompt === 'string', 'instructions must yield a systemPrompt');
    assert.ok(result.systemPrompt.startsWith('BASE NATIVE PROMPT'),
      `the original native prompt must be preserved, got: ${JSON.stringify(result.systemPrompt)}`);
    assert.ok(result.systemPrompt.includes('CORE SPSI MARKER'),
      'explicit core instructions must be injected');
    const req = stub.request('orchestrator-instructions');
    assert.ok(req, "core must receive the 'orchestrator-instructions' request");
    assert.deepEqual(req.arguments, {}, 'the request arguments must be exactly {}');
    // No persistent user/SPSI message: only systemPrompt is returned.
    assert.ok(!('message' in result), 'must not inject a persistent message, only the system prompt');
  }

  // -- 2. per-turn, no accumulation/duplicate (event.systemPrompt only) -------
  {
    stub.reset();
    const ctx = makeCtx('instr-perturn', {});
    await hooks.get('session_start')({}, ctx);
    const first = await beforeAgent(hooks, ctx, 'BASE NATIVE PROMPT');
    const second = await beforeAgent(hooks, ctx, 'BASE NATIVE PROMPT');
    assert.equal(first.systemPrompt, second.systemPrompt,
      'repeated turns with the same base must yield an identical prompt (no accumulation)');
    assert.equal(countOccurrences(second.systemPrompt, 'CORE SPSI MARKER'), 1,
      'instructions must appear exactly once, never duplicated by caching');
  }

  // -- 3. empty instructions (mode off / no skills) preserve native prompt ----
  {
    stub.setScenario({
      'initial-mode': { result: { mode: 'on', text: 'on' } },
      'orchestrator-instructions': { result: { instructions: '' } },
    });
    stub.reset();
    const ctx = makeCtx('instr-empty', {});
    await hooks.get('session_start')({}, ctx);
    const result = await beforeAgent(hooks, ctx, 'BASE NATIVE PROMPT');
    assert.ok(!result || result.systemPrompt === undefined,
      'empty instructions must leave the native prompt untouched (no forced prompt)');
  }

  // -- 4. core error relayed visibly, no silent fallback / no injection -------
  {
    stub.setScenario({
      'initial-mode': { result: { mode: 'on', text: 'on' } },
      'orchestrator-instructions': { error: 'missing configured skill: orch-orchestrator' },
    });
    stub.reset();
    const notes = [];
    const ctx = makeCtx('instr-error', { notes });
    await hooks.get('session_start')({}, ctx);
    const result = await beforeAgent(hooks, ctx, 'BASE NATIVE PROMPT');
    assert.ok(!result || result.systemPrompt === undefined,
      'a core error must not inject a system prompt');
    assert.ok(notes.some((n) => n.includes('missing configured skill: orch-orchestrator')),
      `the actual core error must be relayed visibly, got: ${JSON.stringify(notes)}`);
  }

  // -- 5. stale native session cannot request or inject -----------------------
  {
    stub.setScenario({
      'initial-mode': { result: { mode: 'on', text: 'on' } },
      'orchestrator-instructions': { result: { instructions: 'CORE SPSI MARKER' } },
    });
    stub.reset();
    const stale = makeCtx('instr-stale', {});
    const live = makeCtx('instr-live', {});
    await hooks.get('session_start')({}, stale);
    await hooks.get('session_start')({}, live); // replaces the stale connection
    const staleResult = await beforeAgent(hooks, stale, 'BASE NATIVE PROMPT');
    assert.ok(!staleResult || staleResult.systemPrompt === undefined,
      'a stale session must not inject instructions');
    const liveResult = await beforeAgent(hooks, live, 'BASE NATIVE PROMPT');
    assert.ok(liveResult && liveResult.systemPrompt.includes('CORE SPSI MARKER'),
      'the owning session must still inject instructions');
    await hooks.get('session_shutdown')({}, live); // release the open core connection
  }

  console.log('Pi orchestrator-instructions (core SPSI) regressions passed');
} finally {
  // -- 6. flagged child: no before_agent_start hook (no injection) ------------
  process.env.ORCHESTRA_DISPATCH_BUDGET = '1';
  try {
    const jiti = createJiti(import.meta.url);
    const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');
    const { hooks: childHooks, pi } = makeHarness();
    await activate(pi);
    assert.equal(childHooks.size, 0,
      `a flagged child must register no hooks (no injection), got: ${[...childHooks.keys()]}`);
  } finally {
    delete process.env.ORCHESTRA_DISPATCH_BUDGET;
    stub.cleanup();
  }
}
