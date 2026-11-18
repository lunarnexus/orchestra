import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createJiti } from 'jiti';

// Exercise the real extension's parent-context capture end to end. The only
// controlled boundary is the core `python3` dispatch, which records the exact
// stdin it receives (the parent-context artifact the plugin sends to core).
// No live Pi sessions, models, global config, or real core are involved.
const temp = mkdtempSync(join(tmpdir(), 'orchestra-parent-context-'));
const capturePath = join(temp, 'captured-stdin.txt');
try {
  // python3 stub: for `dispatch`, dump stdin to the capture file and print an
  // ack line; for `status`, return an empty job list; otherwise exit 0.
  writeFileSync(join(temp, 'python3'), `#!${process.execPath}
const fs = require('node:fs');
const args = process.argv.slice(2);
const cmd = args[2];
let input = '';
process.stdin.on('data', (d) => { input += d; });
process.stdin.on('end', () => {
  if (cmd === 'dispatch') {
    fs.writeFileSync(${JSON.stringify(capturePath)}, input);
    process.stdout.write(JSON.stringify({ run_id: 'test-run', role: 'builder', ack: 'Assignment accepted.', jobs: [] }) + '\\n');
    process.exit(0);
  }
  if (cmd === 'status') {
    process.stdout.write(JSON.stringify({ data: { session_jobs: [] } }) + '\\n');
  }
  process.exit(0);
});
`, { mode: 0o755 });

  process.env.PATH = `${temp}:${process.env.PATH}`;
  process.env.ORCHESTRA_CONFIG = temp;

  const jiti = createJiti(import.meta.url);
  const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');

  const tools = new Map();
  activate({
    on() {},
    registerTool: (t) => tools.set(t.name, t),
    registerCommand() {}, registerEntryRenderer() {},
    getActiveTools: () => [...tools.keys()],
    setActiveTools() {},
    sendUserMessage() {},
  });
  assert.ok(tools.has('orch_dispatch'), 'orch_dispatch tool must be registered');

  // A realistic mix of session context entries: user text, an assistant turn
  // mixing text + thinking + a tool call, a system message, a toolResult
  // message, an assistant turn with only a tool call, and a user message with
  // string content. Only the user/assistant natural-language text survives.
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

  const ctx = {
    hasUI: true,
    sessionManager: {
      getSessionId: () => 'parent-context-test',
      buildContextEntries: () => entries,
      getBranch: () => [],
    },
    ui: {
      theme: { fg: (_c, t) => t, bold: (t) => t },
      setWidget() {},
      notify() {},
    },
  };

  const ack = await tools.get('orch_dispatch').execute('c1', { goal: 'build the widget', role: 'builder' }, undefined, undefined, ctx);
  assert.equal(ack.isError, false, `dispatch ack failed: ${JSON.stringify(ack)}`);

  const captured = readFileSync(capturePath, 'utf8');
  const expected = [
    'user: Please build the widget.',
    'assistant: I will inspect the source first.',
    'user: A plain string user turn.',
    '',
  ].join('\n');
  assert.equal(captured, expected, 'artifact keeps ONLY user/assistant natural-language text, one role-prefixed line per non-empty message, trailing newline');

  for (const marker of ['THINKING_MARKER', 'TOOLCALL_ARGS_MARKER', 'ONLYTOOLCALL_MARKER', 'SYS_MARKER', 'TOOLRESULT_MARKER', 'SKILLS_MARKER', 'toolCall', 'thinking', 'toolResult', 'role":"system']) {
    assert.ok(!captured.includes(marker), `captured artifact must exclude ${marker}`);
  }
  assert.ok(!/ONLYTOOLCALL_MARKER|^\s*assistant:\s*$/m.test(captured), 'assistant turn with no text is skipped');

  console.log('Pi parent-context chat-only capture passed');
} finally {
  rmSync(temp, { recursive: true, force: true });
}
