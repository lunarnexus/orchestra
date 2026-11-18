import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createJiti } from 'jiti';

// Exercise the real extension's parent-context capture + deterministic
// references digest end to end. The only controlled boundary is the core
// `python3` dispatch, which records the exact stdin (the artifact) it receives.
// No live Pi sessions, models, global config, or real core are involved.
const temp = mkdtempSync(join(tmpdir(), 'orchestra-references-digest-'));
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

  const ctx = {
    hasUI: true,
    sessionManager: {
      getSessionId: () => 'references-digest-test',
      buildContextEntries: () => entries,
      getBranch: () => [],
    },
    ui: {
      theme: { fg: (_c, t) => t, bold: (t) => t },
      setWidget() {},
      notify() {},
    },
  };

  const ack = await tools.get('orch_dispatch').execute('probe', { goal: 'investigate', role: 'builder' }, undefined, undefined, ctx);
  assert.equal(ack.isError, false, `dispatch ack failed: ${JSON.stringify(ack)}`);

  const captured = readFileSync(capturePath, 'utf8');

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

  const capCtx = {
    hasUI: true,
    sessionManager: {
      getSessionId: () => 'cap-test',
      buildContextEntries: () => capEntries,
      getBranch: () => [],
    },
    ui: { theme: { fg: (_c, t) => t, bold: (t) => t }, setWidget() {}, notify() {} },
  };

  const capAck = await tools.get('orch_dispatch').execute('cap', { goal: 'cap probe', role: 'builder' }, undefined, undefined, capCtx);
  assert.equal(capAck.isError, false, `cap dispatch ack failed: ${JSON.stringify(capAck)}`);
  const capCapture = readFileSync(capturePath, 'utf8');

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
  rmSync(temp, { recursive: true, force: true });
}
