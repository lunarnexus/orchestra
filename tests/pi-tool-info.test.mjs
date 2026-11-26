import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createJiti } from 'jiti';

// Prove that the extension awaits core tool-info metadata before tool
// registration, consumes its descriptions/labels/actions, and fails visibly
// (no incomplete/fallback tools) when metadata is missing or malformed.
// Controlled subprocess boundary only — no real Python core, no models.
const temp = mkdtempSync(join(tmpdir(), 'orchestra-tool-info-'));

// The frozen contract that the fixed `tool-info` CLI must return.
const TOOL_INFO = {
  dispatch: {
    label: "Orchestra Dispatch",
    description: "Submit an assignment to Orchestra subagents.",
    params: {
      goal: "Assignment text: goal, scope, boundaries, stop condition.",
      additionalContext: "Extra context for parent-context roles.",
      role: "Configured role name.",
      taskLabel: "Short optional display label.",
    },
  },
  status: {
    label: "Orchestra Status",
    description: "Manage the current session Orchestra work.",
    params: {
      action: "Management action to perform.",
      limit: "history only: how many completed runs to list.",
      runId: "stop only: the run id from a dispatch acknowledgement.",
    },
  },
  command: { description: "Orchestra: /orch help|on|off|doctor|status|history|do|stop" },
  actions: ["status", "history", "stop", "help", "doctor", "roles"],
};

function writeStub(dir, script) {
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, 'python3'), script, { mode: 0o755 });
}

// --- A: valid tool-info ---
writeStub(join(temp, 'valid'), `#!${process.execPath}
const args = process.argv.slice(2);
if (args.includes('tool-info')) {
  process.stdout.write(JSON.stringify(${JSON.stringify(TOOL_INFO)}));
} else if (args.includes('initial-mode')) {
  process.stdout.write('on');
} else if (args.includes('status')) {
  process.stdout.write(JSON.stringify({ data: { session_jobs: [] } }));
}
process.exit(0);
`);

// --- B: tool-info nonzero exit ---
writeStub(join(temp, 'fail'), `#!${process.execPath}
const args = process.argv.slice(2);
if (args.includes('tool-info')) {
  process.stderr.write('ModuleNotFoundError: No module named orchestra');
  process.exit(1);
}
process.exit(0);
`);

// --- C: malformed JSON ---
writeStub(join(temp, 'malformed'), `#!${process.execPath}
const args = process.argv.slice(2);
if (args.includes('tool-info')) {
  process.stdout.write('not json at all {{{');
}
process.exit(0);
`);

// --- D: missing required field (no actions) ---
const partial = { ...TOOL_INFO };
delete partial.actions;
writeStub(join(temp, 'partial'), `#!${process.execPath}
const args = process.argv.slice(2);
if (args.includes('tool-info')) {
  process.stdout.write(JSON.stringify(${JSON.stringify(partial)}));
}
process.exit(0);
`);

// --- E: empty PATH (launch failure) ---
const emptyBin = join(temp, 'empty-bin');
mkdirSync(emptyBin, { recursive: true });

// --- F: a required dispatch param is an empty string ---
const emptyParam = JSON.parse(JSON.stringify(TOOL_INFO));
emptyParam.dispatch.params.goal = '';
writeStub(join(temp, 'empty-param'), `#!${process.execPath}
const args = process.argv.slice(2);
if (args.includes('tool-info')) {
  process.stdout.write(JSON.stringify(${JSON.stringify(emptyParam)}));
}
process.exit(0);
`);

// --- G: a top-level status label is an empty string ---
const emptyLabel = JSON.parse(JSON.stringify(TOOL_INFO));
emptyLabel.status.label = '';
writeStub(join(temp, 'empty-label'), `#!${process.execPath}
const args = process.argv.slice(2);
if (args.includes('tool-info')) {
  process.stdout.write(JSON.stringify(${JSON.stringify(emptyLabel)}));
}
process.exit(0);
`);

process.env.ORCHESTRA_CONFIG = temp;

try {
  const jiti = createJiti(import.meta.url);
  const { default: activate } = await jiti.import('../extensions/pi/orchestra/index.ts');

  // --- A: valid metadata -> tools registered with core text ---
  {
    process.env.PATH = join(temp, 'valid');
    const tools = new Map();
    const commands = new Map();
    await activate({
      on() {},
      registerTool: (t) => tools.set(t.name, t),
      registerCommand: (name, def) => commands.set(name, def),
      registerEntryRenderer() {},
      appendEntry() {},
      getActiveTools: () => [],
      setActiveTools() {},
      sendUserMessage() {},
    });
    assert.ok(tools.has('orch_dispatch'), 'valid metadata registers orch_dispatch');
    assert.ok(tools.has('orch_status'), 'valid metadata registers orch_status');
    // Descriptions come from core, not adapter literals.
    assert.equal(tools.get('orch_dispatch').description, TOOL_INFO.dispatch.description);
    assert.equal(tools.get('orch_status').description, TOOL_INFO.status.description);
    // Labels come from core.
    assert.equal(tools.get('orch_dispatch').label, TOOL_INFO.dispatch.label);
    assert.equal(tools.get('orch_status').label, TOOL_INFO.status.label);
    // Parameter descriptions from core.
    const dispatchParams = tools.get('orch_dispatch').parameters;
    assert.equal(dispatchParams.properties.goal.description, TOOL_INFO.dispatch.params.goal);
    assert.equal(dispatchParams.properties.role.description, TOOL_INFO.dispatch.params.role);
    assert.equal(dispatchParams.properties.taskLabel.description, TOOL_INFO.dispatch.params.taskLabel);
    // Status actions come from core actions array, not adapter enum.
    const statusTool = tools.get('orch_status');
    const actionProp = statusTool.parameters.properties.action;
    assert.ok(actionProp, 'action parameter exists');
    // Verify the enum matches core actions.
    const actionEnum = actionProp.enum ?? actionProp.anyOf?.[0]?.enum;
    assert.ok(actionEnum, 'action parameter must expose an enum from core actions');
    assert.deepEqual([...actionEnum].sort(), [...TOOL_INFO.actions].sort());
    // Command description from core.
    const cmd = commands.get('orch');
    assert.ok(cmd, '/orch command registered');
    assert.equal(cmd.description, TOOL_INFO.command.description);
  }

  // --- B: nonzero tool-info exit -> abort, register nothing ---
  {
    process.env.PATH = join(temp, 'fail');
    const tools = new Map();
    let threw = false;
    try {
      await activate({
        on() {},
        registerTool: (t) => tools.set(t.name, t),
        registerCommand() {},
        registerEntryRenderer() {},
        appendEntry() {},
        getActiveTools: () => [],
        setActiveTools() {},
        sendUserMessage() {},
      });
    } catch (e) {
      threw = true;
      assert.match(String(e), /tool-info/i, 'error mentions tool-info');
    }
    assert.ok(threw, 'activation must throw when tool-info fails');
    assert.equal(tools.size, 0, 'no tools registered when tool-info fails');
  }

  // --- C: malformed JSON -> abort ---
  {
    process.env.PATH = join(temp, 'malformed');
    const tools = new Map();
    let threw = false;
    try {
      await activate({
        on() {},
        registerTool: (t) => tools.set(t.name, t),
        registerCommand() {},
        registerEntryRenderer() {},
        appendEntry() {},
        getActiveTools: () => [],
        setActiveTools() {},
        sendUserMessage() {},
      });
    } catch (e) {
      threw = true;
      assert.match(String(e), /tool-info|malformed/i, 'error mentions cause');
    }
    assert.ok(threw, 'malformed tool-info JSON must throw');
    assert.equal(tools.size, 0, 'no tools on malformed metadata');
  }

  // --- D: missing required field -> abort ---
  {
    process.env.PATH = join(temp, 'partial');
    const tools = new Map();
    let threw = false;
    try {
      await activate({
        on() {},
        registerTool: (t) => tools.set(t.name, t),
        registerCommand() {},
        registerEntryRenderer() {},
        appendEntry() {},
        getActiveTools: () => [],
        setActiveTools() {},
        sendUserMessage() {},
      });
    } catch (e) {
      threw = true;
      assert.match(String(e), /tool-info|missing|actions/i, 'error mentions cause');
    }
    assert.ok(threw, 'incomplete tool-info must throw');
    assert.equal(tools.size, 0, 'no tools on incomplete metadata');
  }

  // --- E: launch failure (no python3) -> abort ---
  {
    process.env.PATH = emptyBin;
    const tools = new Map();
    let threw = false;
    try {
      await activate({
        on() {},
        registerTool: (t) => tools.set(t.name, t),
        registerCommand() {},
        registerEntryRenderer() {},
        appendEntry() {},
        getActiveTools: () => [],
        setActiveTools() {},
        sendUserMessage() {},
      });
    } catch (e) {
      threw = true;
      assert.match(String(e), /tool-info|ENOENT|python/i, 'error mentions cause');
    }
    assert.ok(threw, 'launch failure must throw');
    assert.equal(tools.size, 0, 'no tools on launch failure');
  }

  // --- F/G: an empty required text field aborts activation (no fallback) ---
  for (const [dir, re] of [['empty-param', /non-empty|goal|params/i], ['empty-label', /non-empty|label/i]]) {
    process.env.PATH = join(temp, dir);
    const tools = new Map();
    let threw = false;
    try {
      await activate({
        on() {},
        registerTool: (t) => tools.set(t.name, t),
        registerCommand() {}, registerEntryRenderer() {}, appendEntry() {},
        getActiveTools: () => [], setActiveTools() {}, sendUserMessage() {},
      });
    } catch (e) {
      threw = true;
      assert.match(String(e), re, `${dir} error mentions the empty-field cause`);
    }
    assert.ok(threw, `${dir}: empty required text field must throw`);
    assert.equal(tools.size, 0, `${dir}: no tools on empty required field`);
  }

  console.log('Pi tool-info contract passed');
} finally {
  rmSync(temp, { recursive: true, force: true });
}
