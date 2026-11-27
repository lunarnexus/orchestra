import assert from 'node:assert/strict';
import { createJiti } from 'jiti';
import { makeSessionStub, makeCtx } from './helpers/orchestra-session-stub.mjs';

// Exercise the real extension's parent-context capture + deterministic
// references digest end to end. The only controlled boundary is the core
// `__session` runtime, which requests get_parent_context on an accepted
// dispatch; the adapter answers with a native_result whose data.text is the
// captured chat-only + references digest the test asserts. No live Pi sessions,
// models, global config, or real core are involved.
const stub = makeSessionStub({
  reply: {
    'initial-mode': { result: { mode: 'on', text: 'Orchestra active.' } },
    dispatch: { result: { text: 'Assignment accepted. Run test-run.' } },
  },
});
stub.setScenario({
  'initial-mode': { result: { mode: 'on', text: 'Orchestra active.' } },
  dispatch: { result: { text: 'Assignment accepted. Run test-run.' } },
  emitContextRequest: true,
});

async function waitFor(label, fn, timeoutMs = 4000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (fn()) return;
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${label}`);
    await new Promise((r) => setTimeout(r, 25));
  }
}

function capturedDigest() {
  // The adapter answers each core get_parent_context with a native_result whose
  // data.text is the chat-only + references digest. Use the most recent one.
  const result = stub.nativeResults().filter((r) => r.id === 'ctx-1').pop();
  assert.ok(result, 'adapter answered the core get_parent_context request with a native_result');
  return result.data.text;
}

const hooks = new Map();
let ctx;
try {
  const jiti = createJiti(import.meta.url);
  const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');

  const tools = new Map();
  await activate({
    on: (name, handler) => hooks.set(name, handler),
    registerTool: (t) => tools.set(t.name, t),
    registerCommand() {}, registerEntryRenderer() {},
    appendEntry() {},
    getActiveTools: () => [...tools.keys()],
    setActiveTools() {},
    sendUserMessage() {},
  });
  assert.ok(tools.has('orch_dispatch'), 'orch_dispatch tool must be registered');

  // A realistic parent-context mix: a user turn, an assistant turn that mixes
  // conversational text with read/bash/write tool calls, the matching tool
  // results, a distractor tool whose result body carries a unique marker, a
  // system message, an orphan toolResult, and a duplicate read of /a.py.
  const entries = [
    { type: 'message', message: { role: 'user', content: [{ type: 'text', text: 'Investigate the bug.' }] } },
    {
      type: 'message',
      message: {
        role: 'assistant',
        content: [
          { type: 'text', text: 'Reading the file.' },
          { type: 'toolCall', id: 'c1', name: 'read', arguments: { path: '/a.py' } },
          { type: 'toolCall', id: 'c2', name: 'bash', arguments: { command: 'pytest -q' } },
          { type: 'toolCall', id: 'c3', name: 'write', arguments: { path: '/a.py' } },
        ],
      },
    },
    { type: 'message', message: { role: 'toolResult', toolCallId: 'c1', toolName: 'read', isError: false, content: [{ type: 'text', text: 'FILEBODY result body must never appear' }] } },
    { type: 'message', message: { role: 'toolResult', toolCallId: 'c2', toolName: 'bash', isError: true, content: [{ type: 'text', text: 'CMDBODY result body must never appear' }] } },
    { type: 'message', message: { role: 'toolResult', toolCallId: 'c3', toolName: 'write', isError: false, content: [{ type: 'text', text: 'WRITEBODY result body must never appear' }] } },
    // Distractor: a tool call whose RESULT body contains a unique marker.
    { type: 'message', message: { role: 'assistant', content: [{ type: 'toolCall', id: 'd1', name: 'codex-research', arguments: { search_query: [{ q: 'DistractQuery' }] } }] } },
    { type: 'message', message: { role: 'toolResult', toolCallId: 'd1', toolName: 'codex-research', isError: false, content: [{ type: 'text', text: 'UNIQUE_MARKER leaked result body' }] } },
    // System message and an orphan tool result with its own unique marker.
    { type: 'message', message: { role: 'system', content: [{ type: 'text', text: 'SYS_PROMPT system text' }] } },
    { type: 'message', message: { role: 'toolResult', toolCallId: 'c9', toolName: 'other', isError: false, content: [{ type: 'text', text: 'UNIQUE_TOOLTEXT orphan result body' }] } },
    // Second read of /a.py must collapse into the single existing entry.
    { type: 'message', message: { role: 'assistant', content: [{ type: 'toolCall', id: 'c4', name: 'read', arguments: { path: '/a.py' } }] } },
    { type: 'message', message: { role: 'toolResult', toolCallId: 'c4', toolName: 'read', isError: false, content: [{ type: 'text', text: 'SECOND_READ_BODY result body' }] } },
  ];

  // Establish the persistent core `__session` connection for the SAME native id
  // the dispatch uses, before dispatching.
  ctx = makeCtx('references-digest-test', { entries });
  await hooks.get('session_start')({}, ctx);

  const ack = await tools.get('orch_dispatch').execute('probe', { goal: 'investigate', role: 'builder' }, undefined, undefined, ctx);
  assert.equal(ack.isError, false, `dispatch ack failed: ${JSON.stringify(ack)}`);
  await waitFor('native_result for get_parent_context', () => stub.nativeResults().some((r) => r.id === 'ctx-1'));
  const captured = capturedDigest();

  // Existing chat-only lines stay unchanged.
  assert.ok(captured.includes('user: Investigate the bug.\n'), 'chat line for user turn preserved');
  assert.ok(captured.includes('assistant: Reading the file.\n'), 'chat line for assistant text preserved');

  // Digest: file paths section, /a.py exactly once (covering read + write).
  assert.ok(captured.includes('Files touched:'), 'Files touched section present');
  assert.ok(captured.includes('  /a.py (read)'), 'path labeled with first-used action verb');
  const pathHits = captured.split('/a.py').length - 1;
  assert.equal(pathHits, 1, `/a.py must appear exactly once, found ${pathHits}`);

  // Digest: commands section, bash status from joined toolResult.isError.
  assert.ok(captured.includes('Commands run:'), 'Commands run section present');
  assert.ok(captured.includes('  pytest -q -> failed'), 'bash command status derived from isError=true');

  // Nothing from result bodies / distractors / system / reasoning leaks.
  for (const marker of ['UNIQUE_MARKER', 'UNIQUE_TOOLTEXT', 'FILEBODY', 'CMDBODY', 'WRITEBODY', 'SECOND_READ_BODY', 'SYS_PROMPT', 'DistractQuery', 'toolCall', 'toolResult', 'role":"system']) {
    assert.ok(!captured.includes(marker), `artifact must exclude ${marker}`);
  }

  console.log('Pi references digest passed');

  // --- Cap regression: more unique commands than MAX_DIGEST_COMMANDS (25) ---
  // Only the most-recent 25 de-duplicated commands are kept; the oldest drop.
  const capEntries = [
    { type: 'message', message: { role: 'user', content: [{ type: 'text', text: 'Cap probe.' }] } },
  ];
  const capBlocks = [];
  for (let i = 1; i <= 30; i += 1) {
    capBlocks.push({ type: 'toolCall', id: `cmdid-${i}`, name: 'bash', arguments: { command: `cmd-${String(i).padStart(2, '0')} run` } });
  }
  capEntries.push({ type: 'message', message: { role: 'assistant', content: capBlocks } });

  // Re-attach the persistent connection for the cap native id before dispatch.
  const capCtx = makeCtx('cap-test', { entries: capEntries });
  await hooks.get('session_start')({}, capCtx);

  const capBefore = stub.nativeResults().filter((r) => r.id === 'ctx-1').length;
  const capAck = await tools.get('orch_dispatch').execute('cap', { goal: 'cap probe', role: 'builder' }, undefined, undefined, capCtx);
  assert.equal(capAck.isError, false, `cap dispatch ack failed: ${JSON.stringify(capAck)}`);
  await waitFor('cap native_result for get_parent_context', () => stub.nativeResults().filter((r) => r.id === 'ctx-1').length > capBefore);
  const capCapture = capturedDigest();

  assert.ok(!capCapture.includes('Files touched:'), 'no Files touched section when no file tools ran');
  const keptCount = capCapture.split('run -> ok').length - 1;
  assert.equal(keptCount, 25, `exactly 25 commands kept, found ${keptCount}`);
  // Oldest five dropped; the most-recent 25 (cmd-06..cmd-30) retained.
  for (let i = 1; i <= 5; i += 1) {
    const gone = `  cmd-${String(i).padStart(2, '0')} run -> `;
    assert.ok(!capCapture.includes(gone), `oldest command ${gone.trim()} must be capped out`);
  }
  for (let i = 6; i <= 30; i += 1) {
    const kept = `  cmd-${String(i).padStart(2, '0')} run -> ok`;
    assert.ok(capCapture.includes(kept), `most-recent command ${kept.trim()} must be retained`);
  }

  console.log('Pi references digest cap (most-recent 25) passed');
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
