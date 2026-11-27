import assert from 'node:assert/strict';
import { createJiti } from 'jiti';
import { makeSessionStub, makeCtx } from './helpers/orchestra-session-stub.mjs';

// Translator contract: the adapter captures parent context ONLY when the core
// requests it via a persistent-`__session` native_request `get_parent_context`,
// and returns the chat-only capture as a native_result data.text. There is no
// role/context policy and no made-up/fallback context text in the adapter. The
// controlled core `__session` emits the get_parent_context request when it
// accepts a dispatch; the test asserts the native_result the adapter sends back.
// Controlled boundaries only: no real core, models, live Pi, or install.
const stub = makeSessionStub({
  reply: {
    'initial-mode': { result: { mode: 'on', text: 'Orchestra active.' } },
    dispatch: { result: { text: 'Assignment accepted. Run abcdef0123456789abcdef0123456789.' } },
  },
});
stub.setScenario({
  'initial-mode': { result: { mode: 'on', text: 'Orchestra active.' } },
  dispatch: { result: { text: 'Assignment accepted. Run abcdef0123456789abcdef0123456789.' } },
  emitContextRequest: true,
});

const entries = [
  { type: 'message', message: { role: 'user', content: [{ type: 'text', text: 'Please build the widget.' }] } },
  {
    type: 'message',
    message: {
      role: 'assistant',
      content: [
        { type: 'thinking', thinking: 'THINKING_MARKER hidden reasoning' },
        { type: 'text', text: 'I will inspect the source first.' },
        { type: 'toolCall', id: 't1', name: 'read', arguments: { path: 'TOOLCALL_ARGS_MARKER' } },
      ],
    },
  },
  { type: 'message', message: { role: 'system', content: [{ type: 'text', text: 'SYS_MARKER system prompt' }] } },
  { type: 'message', message: { role: 'toolResult', toolName: 'read', content: [{ type: 'text', text: 'TOOLRESULT_MARKER tool output' }] } },
  { type: 'message', message: { role: 'assistant', content: [{ type: 'toolCall', id: 't2', name: 'bash', arguments: { command: 'ONLYTOOLCALL_MARKER' } }] } },
  { type: 'custom', customType: 'skills', data: { note: 'SKILLS_MARKER injected skill text' } },
  { type: 'message', message: { role: 'user', content: 'A plain string user turn.' } },
];

async function waitFor(label, fn, timeoutMs = 4000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (fn()) return;
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${label}`);
    await new Promise((r) => setTimeout(r, 25));
  }
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
    registerCommand() {},
    registerEntryRenderer() {},
    appendEntry() {},
    getActiveTools: () => [...tools.keys()],
    setActiveTools() {},
    sendUserMessage() {},
  });

  ctx = makeCtx('parent-context-test', { entries });
  // Establish the persistent core `__session` connection for the SAME native id
  // the dispatch will use, before any dispatch.
  await hooks.get('session_start')({}, ctx);

  // Dispatch triggers a core-initiated get_parent_context; the adapter services
  // it from the live native session and replies with a native_result.
  const ack = await tools.get('orch_dispatch').execute('c1', { goal: 'build the widget', role: 'builder' }, undefined, undefined, ctx);
  assert.equal(ack.isError, false, `dispatch ack failed: ${JSON.stringify(ack)}`);

  await waitFor('native_result for get_parent_context', () => stub.nativeResults().length > 0);
  const results = stub.nativeResults();
  const ctxResult = results.find((r) => r.id === 'ctx-1');
  assert.ok(ctxResult, 'adapter answered the core get_parent_context request with a native_result');
  assert.equal(ctxResult.accepted, true, 'capture accepted');
  const captured = ctxResult.data.text;

  const expected = [
    'user: Please build the widget.',
    'assistant: I will inspect the source first.',
    'user: A plain string user turn.',
    '',
    'Files touched:',
    '  TOOLCALL_ARGS_MARKER (read)',
    'Commands run:',
    '  ONLYTOOLCALL_MARKER -> ok',
    '',
  ].join('\n');
  assert.equal(captured, expected, 'chat-only lines then a deterministic files/commands references digest');

  for (const marker of ['THINKING_MARKER', 'SYS_MARKER', 'TOOLRESULT_MARKER', 'SKILLS_MARKER', 'toolCall', 'thinking', 'toolResult', 'role":"system']) {
    assert.ok(!captured.includes(marker), `captured artifact must exclude ${marker}`);
  }
  assert.ok(!/^\s*assistant:\s*$/m.test(captured), 'assistant turn with no text is skipped');

  // The context was captured only in response to the core request — never pushed
  // eagerly on dispatch, and never delivered to a foreign session.
  assert.ok(!stub.requests().some((r) => r.operation === 'dispatch' && JSON.stringify(r).includes('TOOLCALL_ARGS_MARKER')),
    'the adapter never sends captured context inside the dispatch request');

  console.log('Pi parent-context chat-only capture passed');
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
