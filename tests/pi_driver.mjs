/**
 * Pi delivery-flow test driver.
 *
 * Loads the real extensions/pi/orchestra/index.ts via the installed Pi
 * extension loader, creates a fake ExtensionAPI/runtime, and communicates
 * with the pytest wrapper via stdin/stdout JSON lines.
 *
 * Protocol (stdin commands → stdout JSON-line events):
 *   {"cmd":"session_start","id":"<raw-id>"}
 *   {"cmd":"session_shutdown"}
 *   {"cmd":"dispatch","goal":"<goal>"}
 *   {"cmd":"message_end","text":"<text>"}
 *   {"cmd":"quit"}
 *
 * Emitted events:
 *   {"kind":"ready"}
 *   {"kind":"ack","result":{...}}
 *   {"kind":"followup","message":"...","options":{...}}
 *   {"kind":"notify","message":"..."}
 *   {"kind":"error","message":"..."}
 */

import { pathToFileURL } from "node:url";
import { createRequire } from "node:module";

const PKG = process.env.ORCH_PI_PKG;
const EXT_PATH = process.env.ORCH_EXT_PATH;

if (!PKG || !EXT_PATH) {
  process.stderr.write("ORCH_PI_PKG and ORCH_EXT_PATH env vars are required\n");
  process.exit(1);
}

const { loadExtensions, createExtensionRuntime } = await import(
  pathToFileURL(`${PKG}/dist/core/extensions/loader.js`)
);
const { createEventBus } = await import(
  pathToFileURL(`${PKG}/dist/core/event-bus.js`)
);

// --- Fake runtime ---
const runtime = createExtensionRuntime();

const followups = [];
let compactionRejects = 0;
runtime.sendUserMessage = (msg, opts) => {
  if (compactionRejects > 0) {
    compactionRejects -= 1;
    emit({ kind: "rejected", message: msg });
    return; // simulate rejection during compaction
  }
  followups.push([msg, opts]);
  emit({ kind: "followup", message: msg, options: opts });
};
runtime.getActiveTools = () => [];
runtime.setActiveTools = () => {};
runtime.sendMessage = () => {};
runtime.appendEntry = () => {};

// --- Load extension ---
const eventBus = createEventBus();
const result = await loadExtensions([EXT_PATH], process.cwd(), eventBus, runtime);
if (result.errors.length) {
  process.stderr.write(`LOAD ERRORS: ${JSON.stringify(result.errors)}\n`);
  process.exit(1);
}
const ext = result.extensions[0];
if (!ext) {
  process.stderr.write("No extension loaded\n");
  process.exit(1);
}

// --- Helpers ---
function emit(obj) {
  process.stdout.write(JSON.stringify(obj) + "\n");
}

function makeCtx(sessionId) {
  return {
    ui: {
      notify: (msg) => emit({ kind: "notify", message: msg }),
      setWidget: () => {},
      theme: { bold: (t) => t, fg: (_c, t) => t },
    },
    mode: "tui",
    hasUI: true,
    cwd: process.cwd(),
    sessionManager: {
      getSessionId: () => sessionId,
      buildContextEntries: () => { throw new Error("not available in test"); },
      getBranch: () => { throw new Error("not available in test"); },
    },
    modelRegistry: {},
    model: undefined,
    scopedModels: [],
    isIdle: () => true,
    isProjectTrusted: () => true,
    signal: undefined,
    abort: () => {},
    hasPendingMessages: () => false,
    shutdown: () => { throw new Error("not available in test"); },
    getContextUsage: () => undefined,
    compact: () => {},
    getSystemPrompt: () => "",
  };
}

let currentCtx = null;
let currentRawId = null;

// --- Command loop ---
emit({ kind: "ready" });

let buffer = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {
  buffer += chunk;
  let idx;
  while ((idx = buffer.indexOf("\n")) !== -1) {
    const line = buffer.slice(0, idx).trim();
    buffer = buffer.slice(idx + 1);
    if (!line) continue;
    void handleCommand(line);
  }
});

async function handleCommand(line) {
  let cmd;
  try {
    cmd = JSON.parse(line);
  } catch {
    emit({ kind: "error", message: `invalid JSON: ${line}` });
    return;
  }

  try {
    switch (cmd.cmd) {
      case "session_start": {
        currentRawId = cmd.id;
        currentCtx = makeCtx(cmd.id);
        const handlers = ext.handlers.get("session_start");
        if (!handlers?.length) throw new Error("session_start handler not registered");
        await handlers[0]({ type: "session_start", reason: "startup" }, currentCtx);
        break;
      }
      case "session_shutdown": {
        if (!currentCtx) throw new Error("no active session");
        const handlers = ext.handlers.get("session_shutdown");
        if (!handlers?.length) throw new Error("session_shutdown handler not registered");
        await handlers[0]({ type: "session_shutdown" }, currentCtx);
        currentCtx = null;
        currentRawId = null;
        break;
      }
      case "dispatch": {
        if (!currentCtx) throw new Error("no active session");
        const tool = ext.tools.get("orch_dispatch");
        if (!tool) throw new Error("orch_dispatch tool not registered");
        const res = await tool.definition.execute(
          "tc-1",
          { goal: cmd.goal },
          undefined,
          undefined,
          currentCtx,
        );
        // res is { content: [{type:"text",text:...}], isError?: boolean }
        const text = Array.isArray(res.content)
          ? res.content.map((p) => p.text ?? "").join("")
          : String(res.content ?? "");
        emit({ kind: "ack", result: { text, isError: res.isError ?? false } });
        break;
      }
      case "message_end": {
        const handlers = ext.handlers.get("message_end");
        if (!handlers?.length) throw new Error("message_end handler not registered");
        handlers[0]({
          type: "message_end",
          message: { role: "user", content: cmd.text },
        });
        break;
      }
      case "compaction_reject": {
        compactionRejects = cmd.count ?? 1;
        // Fire session_before_compact to signal compaction is starting.
        const compactHandlers = ext.handlers.get("session_before_compact");
        if (compactHandlers?.length) {
          await compactHandlers[0]({ type: "session_before_compact" }, currentCtx);
        }
        emit({ kind: "ack", result: { text: `compaction_reject set to ${compactionRejects}`, isError: false } });
        break;
      }
      case "compaction_end":
      case "compaction_failed": {
        const eventType = cmd.cmd === "compaction_failed" ? "session_compact_failed" : "session_compact";
        const handlers = ext.handlers.get(eventType);
        if (!handlers?.length) throw new Error(`${eventType} handler not registered`);
        for (const h of handlers) await h({ type: eventType }, currentCtx);
        compactionRejects = 0;
        emit({ kind: "ack", result: { text: `${eventType} fired`, isError: false } });
        break;
      }
      case "delivery_count": {
        emit({ kind: "delivery_count", count: followups.length });
        break;
      }
      case "quit": {
        process.exit(0);
        break;
      }
      default:
        emit({ kind: "error", message: `unknown command: ${cmd.cmd}` });
    }
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    emit({ kind: "error", message: msg });
  }
}
