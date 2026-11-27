/**
 * Orchestra 2 Pi host adapter — thin native<->core TRANSLATOR.
 *
 * This adapter owns ONLY native host concerns and a transport to one persistent
 * core session process. Every Orchestra decision — job lifecycle, admission and
 * readiness, mode, delivery timing, report assembly, and all generic wording —
 * lives in the Python core. The adapter holds NO core business state, NO timers,
 * NO report buffer, NO job/lifecycle maps, and NO mode cache.
 *
 * Responsibilities retained here (all Pi-native or transport-only):
 * - Core tool-info fetch before tool registration (one short-lived read).
 * - Native tool/command/entry registration and active-tool on/off.
 * - Native runtime identity capture (normalized `pi:<id>`, never model-supplied).
 * - One persistent `python3 -m orchestra __session` connection started on native
 *   `session_start`, speaking newline-framed JSON over stdio.
 * - Native status rendering and command-entry echo.
 * - Native parent-context capture, performed ONLY when core requests it.
 * - Native delivery via `sendUserMessage`, performed ONLY when core requests it.
 * - Forwarding native availability/agent/compaction/session events to core.
 *
 * Wire contract (frozen): see src/orchestra/session.py.
 *   Pi -> core: {kind:'request',id,operation,arguments},
 *               {kind:'host_event',event,details},
 *               {kind:'native_result',id,accepted,data?,error?}
 *   Core -> Pi: {kind:'reply',id,result} | {kind:'reply',id,error},
 *               {kind:'status',text,mode_text?,native_session_ids?},
 *               {kind:'native_request',id,operation,arguments}
 */
import { spawn, type ChildProcessByStdio } from "node:child_process";
import { createInterface } from "node:readline";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { Readable } from "node:stream";
import { calculateCost, StringEnum, type Api, type Model, type Usage } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

/** The tools a session activates or deactivates as a unit (native active set). */
const ORCHESTRA_TOOLS = ["orch_dispatch", "orch_status"];

/** Reserved nested-dispatch marker shared with the Python core
 * (src/orchestra/dispatch_guard.py). A launched Orchestra child carries "1" so
 * it can never orchestrate. Only an unmarked parent may; a marked, positive,
 * or malformed value disables the whole adapter (fail closed). */
const ORCHESTRA_DISPATCH_BUDGET_ENV = "ORCHESTRA_DISPATCH_BUDGET";

function orchestraCanDispatch(): boolean {
  const raw = process.env[ORCHESTRA_DISPATCH_BUDGET_ENV]?.trim();
  if (!raw) return true;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || !Number.isInteger(parsed)) return false;
  return parsed <= 0;
}

/** A theme surface for the native entry renderer. */
type Theme = { fg(color: string, text: string): string; bold(text: string): string };

/** Minimal native UI/context surface used for rendering. */
interface UiCtx {
  hasUI: boolean;
  /** The live native Pi model handle for this session (captured from the native
   * event/context, never Orchestra config); used for pricing the usage footer. */
  model?: Model<Api>;
  ui: {
    notify(msg: string, level: "info" | "warning" | "error"): void;
    setWidget(key: string, content: string[] | undefined, options?: { placement?: string }): void;
    theme: Theme;
  };
  sessionManager: ParentContextSessionManager;
}

/** Fixed contract returned by `python3 -m orchestra tool-info` (registration only). */
interface ToolInfo {
  dispatch: { label: string; description: string; params: { goal: string; additionalContext: string; role: string; taskLabel: string } };
  status: { label: string; description: string; params: { action: string; limit: string; runId: string } };
  command: { description: string };
  actions: string[];
}

/** Install record written beside the extension by `./orchestra init pi`:
 * this checkout's root and interpreter, so the core session uses this checkout's
 * environment instead of an arbitrary system Python. */
interface InstallRecord {
  root?: string;
  python?: string;
}

function moduleDir(): string {
  try {
    return dirname(fileURLToPath(import.meta.url));
  } catch {
    // Some loaders do not expose import.meta; jiti provides __dirname.
  }
  return typeof __dirname !== "undefined" ? __dirname : process.cwd();
}

function loadInstallRecord(): InstallRecord | null {
  try {
    const parsed: unknown = JSON.parse(readFileSync(join(moduleDir(), "install.json"), "utf8"));
    if (parsed && typeof parsed === "object") {
      const record = parsed as InstallRecord;
      if (typeof record.root === "string" && typeof record.python === "string") return record;
    }
  } catch {
    // No install record; fall back to the environment below.
  }
  return null;
}

const install: InstallRecord | null = loadInstallRecord();
const orchestraPython: string = install?.python ?? "python3";

/** Environment for core invocations: Orchestra 2 config dir, and its src/ on
 * PYTHONPATH so `python3 -m orchestra` resolves this checkout's package. */
function orchestraEnv(): NodeJS.ProcessEnv {
  const configDir = process.env.ORCHESTRA_CONFIG ?? install?.root ?? "";
  const pythonPath = [configDir ? join(configDir, "src") : "", process.env.PYTHONPATH ?? ""]
    .filter((part) => part.length > 0)
    .join(":");
  return {
    ...process.env,
    ...(configDir ? { ORCHESTRA_CONFIG: configDir } : {}),
    ...(pythonPath ? { PYTHONPATH: pythonPath } : {}),
  };
}

function normalizePiSessionId(raw: string): string {
  const normalized = (raw ?? "").trim();
  if (!normalized) throw new Error("pi session id is required");
  return `pi:${normalized}`;
}

// -- parent-context capture (Pi-native; performed only when core requests it) --

/** Minimal surface of the Pi session manager used for parent-context capture. */
interface ParentContextSessionManager {
  getSessionId(): string;
  buildContextEntries?: () => unknown[];
  getBranch?: (fromId?: string) => unknown[];
}

function isSessionMessageEntry(value: unknown): value is { type: "message"; message: unknown } {
  if (typeof value !== "object" || value === null) return false;
  const entry = value as { type?: unknown; message?: unknown };
  return entry.type === "message" && typeof entry.message === "object" && entry.message !== null;
}

/** Natural-language text from a message's content: a plain string, or the
 * `text` blocks of a content array. Tool calls, thinking/reasoning, tool
 * results, images, and all metadata are dropped. */
function extractMessageText(content: unknown): string {
  if (typeof content === "string") return content.trim();
  if (Array.isArray(content)) {
    const parts: string[] = [];
    for (const block of content) {
      if (typeof block !== "object" || block === null) continue;
      const part = block as { type?: unknown; text?: unknown };
      if (part.type === "text" && typeof part.text === "string" && part.text.length > 0) {
        parts.push(part.text);
      }
    }
    return parts.join(" ").trim();
  }
  return "";
}

/** Anti-bloat cap for the digest commands section: keep the most-recent
 * this many de-duplicated commands. File paths are kept in full. */
const MAX_DIGEST_COMMANDS = 25;

/** Tool names whose `arguments.path` is recorded as a touched file. */
const FILE_TOOL_NAMES = new Set(["read", "edit", "write"]);

/** Deterministic, no-LLM references digest appended after the chat lines:
 * which file paths the parent read/wrote/edited (labeled with the action verb
 * actually used) and which bash commands it ran (ok vs failed taken only from
 * the joined tool result's `isError`, never from result content). Tool result
 * bodies, file contents, reasoning, schemas, and metadata are never read. */
function renderReferencesDigest(entries: unknown[]): string {
  const failedIds = new Set<string>();
  for (const entry of entries) {
    if (!isSessionMessageEntry(entry)) continue;
    const message = entry.message as { role?: unknown; toolCallId?: unknown; isError?: unknown };
    if (message.role !== "toolResult") continue;
    if (typeof message.toolCallId === "string" && message.toolCallId && message.isError === true) {
      failedIds.add(message.toolCallId);
    }
  }

  const seenPaths = new Set<string>();
  const fileLines: string[] = [];
  const seenCommands = new Set<string>();
  const commandLines: string[] = [];

  for (const entry of entries) {
    if (!isSessionMessageEntry(entry)) continue;
    const message = entry.message as { role?: unknown; content?: unknown };
    if (message.role !== "assistant" || !Array.isArray(message.content)) continue;
    for (const block of message.content) {
      if (typeof block !== "object" || block === null) continue;
      const call = block as { type?: unknown; name?: unknown; arguments?: unknown; id?: unknown };
      if (call.type !== "toolCall" || typeof call.name !== "string") continue;
      const args =
        typeof call.arguments === "object" && call.arguments !== null
          ? (call.arguments as { path?: unknown; command?: unknown })
          : {};
      if (FILE_TOOL_NAMES.has(call.name)) {
        if (typeof args.path === "string" && args.path.length > 0 && !seenPaths.has(args.path)) {
          seenPaths.add(args.path);
          fileLines.push(`  ${args.path} (${call.name})`);
        }
      } else if (call.name === "bash") {
        if (typeof args.command === "string" && args.command.length > 0 && !seenCommands.has(args.command)) {
          seenCommands.add(args.command);
          const failed = typeof call.id === "string" && failedIds.has(call.id);
          commandLines.push(`  ${args.command} -> ${failed ? "failed" : "ok"}`);
        }
      }
    }
  }

  const cappedCommands =
    commandLines.length > MAX_DIGEST_COMMANDS
      ? commandLines.slice(commandLines.length - MAX_DIGEST_COMMANDS)
      : commandLines;

  const out: string[] = [];
  if (fileLines.length > 0) out.push("Files touched:", ...fileLines);
  if (cappedCommands.length > 0) out.push("Commands run:", ...cappedCommands);
  return out.length > 0 ? `${out.join("\n")}\n` : "";
}

/** Chat-only parent context: only `user`/`assistant` conversational text, one
 * role-prefixed line per non-empty message; every other role, tool call, result,
 * reasoning, and metadata is excluded, plus a deterministic references digest of
 * touched files and run commands appended after the chat lines. The digest is
 * appended only when there is chat content and at least one file or command
 * entry, so it never by itself makes an empty capture non-empty. */
function renderParentContextArtifact(entries: unknown[]): string {
  const lines: string[] = [];
  for (const entry of entries) {
    if (!isSessionMessageEntry(entry)) continue;
    const message = entry.message as { role?: unknown; content?: unknown };
    if (message.role !== "user" && message.role !== "assistant") continue;
    const text = extractMessageText(message.content);
    if (!text) continue;
    lines.push(`${message.role}: ${text}`);
  }
  if (lines.length === 0) return "";
  const chat = `${lines.join("\n")}\n`;
  const digest = renderReferencesDigest(entries);
  if (!digest) return chat;
  return `${chat}\n${digest}`;
}

/** Capture the native Pi session context as chat-only text. The capture reads
 * the live session entries (falling back to the branch when the current command
 * is not yet recorded in the compacted context); a fresh/empty session yields an
 * empty string, which is returned unchanged so core decides what to do with it.
 * There is no made-up or fallback context text. */
function captureParentContextText(sessionManager: ParentContextSessionManager): string {
  if (typeof sessionManager.buildContextEntries !== "function") {
    throw new Error("Pi session manager does not expose buildContextEntries()");
  }
  let text = renderParentContextArtifact(sessionManager.buildContextEntries());
  if (!text && typeof sessionManager.getBranch === "function") {
    text = renderParentContextArtifact(sessionManager.getBranch());
  }
  return text;
}

// -- native Pi transcript usage read (computed fresh per status push) -------

interface UsageSummary {
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
}

function parseJsonLine<T>(line: string): T | null {
  try {
    const value: unknown = JSON.parse(line);
    return typeof value === "object" && value !== null ? (value as T) : null;
  } catch {
    return null;
  }
}

function compactTokens(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (abs >= 1_000) return `${(value / 1_000).toFixed(1).replace(/\.0$/, "")}k`;
  return String(value);
}

/** Worker session id embedded in a transcript file name: `..._<id>.jsonl`. */
function sessionTranscriptId(fileName: string): string {
  const base = fileName.split("/").pop() ?? fileName;
  const withoutExt = base.replace(/\.jsonl$/, "");
  return withoutExt.slice(withoutExt.indexOf("_") + 1);
}

/** Sum token usage across the given native Pi worker session transcripts. The
 * ids are opaque native worker session ids supplied by core in the current
 * status push; nothing is cached, so every status request re-reads the live
 * transcripts. An absent/unreadable transcript contributes nothing. */
function readWorkerUsage(workerSessionIds: readonly string[]): UsageSummary {
  const total: UsageSummary = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 };
  if (workerSessionIds.length === 0) return total;
  const wanted = new Set(workerSessionIds);
  const agentDir = process.env.PI_CODING_AGENT_DIR ?? join(process.env.HOME ?? "~", ".pi", "agent");
  const sessionRoot = process.env.PI_CODING_AGENT_SESSION_DIR ?? join(agentDir, "sessions");
  let files: string[] = [];
  try {
    files = readdirSync(sessionRoot, { recursive: true }) as string[];
  } catch {
    return total;
  }
  for (const name of files) {
    if (!wanted.has(sessionTranscriptId(name))) continue;
    try {
      for (const line of readFileSync(join(sessionRoot, name), "utf8").split("\n")) {
        if (!line.trim()) continue;
        const entry = parseJsonLine<{ message?: { usage?: Partial<Usage> } }>(line);
        const usage = entry?.message?.usage;
        if (!usage) continue;
        total.input += usage.input ?? 0;
        total.output += usage.output ?? 0;
        total.cacheRead += usage.cacheRead ?? 0;
        total.cacheWrite += usage.cacheWrite ?? 0;
      }
    } catch {
      // A missing or unreadable transcript contributes nothing.
    }
  }
  return total;
}

/** Render the usage/cost segment from a native Pi model handle (captured from
 * the live native context, never Orchestra config) and a freshly-read usage
 * summary. No model handle means cost 0 (the token counts are still real). */
function usageText(usage: UsageSummary, model: Model<Api> | undefined, theme: Theme): string {
  const cost = model
    ? calculateCost(model, {
        input: usage.input,
        output: usage.output,
        cacheRead: usage.cacheRead,
        cacheWrite: usage.cacheWrite,
        totalTokens: usage.input + usage.output + usage.cacheRead + usage.cacheWrite,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
      } satisfies Usage).total
    : 0;
  return theme.fg("dim", `↑${compactTokens(usage.input)} ↓${compactTokens(usage.output)} $${cost.toFixed(3)}`);
}

// -- one-shot core read used ONLY for registration metadata -----------------

function runToolInfo(): Promise<{ code: number; stdout: string; stderr: string }> {
  return new Promise((resolve) => {
    const child = spawn(orchestraPython, ["-m", "orchestra", "tool-info"], {
      env: orchestraEnv(),
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => (stdout += chunk));
    child.stderr.on("data", (chunk: string) => (stderr += chunk));
    child.on("error", (error: Error) => resolve({ code: 1, stdout: "", stderr: error.message }));
    child.on("close", (code: number | null) => resolve({ code: code ?? 0, stdout: stdout.trim(), stderr: stderr.trim() }));
    child.stdin.on("error", () => {
      /* ignore EPIPE */
    });
    child.stdin.end("");
  });
}

/** Load the core tool-info metadata. Throws on launch failure, nonzero exit,
 * malformed JSON, or a missing/empty required field — activation never registers
 * incomplete or fallback tools. */
async function loadToolInfo(): Promise<ToolInfo> {
  const result = await runToolInfo();
  if (result.code !== 0) {
    throw new Error(`tool-info failed (exit ${result.code}): ${result.stderr || result.stdout || "no output"}`);
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(result.stdout);
  } catch {
    throw new Error(`tool-info returned malformed JSON: ${result.stdout.slice(0, 200)}`);
  }
  if (typeof parsed !== "object" || parsed === null) {
    throw new Error("tool-info returned non-object JSON");
  }
  const info = parsed as Record<string, unknown>;
  const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;
  const requireText = (obj: Record<string, unknown>, key: string, path: string): void => {
    const value = obj[key];
    if (typeof value !== "string" || value.trim().length === 0) {
      throw new Error(`tool-info.${path}.${key} must be a non-empty string`);
    }
  };
  for (const key of ["dispatch", "status", "command", "actions"] as const) {
    if (!(key in info)) throw new Error(`tool-info missing required field: ${key}`);
  }
  if (!isObj(info.dispatch)) throw new Error("tool-info.dispatch must be an object");
  requireText(info.dispatch, "label", "dispatch");
  requireText(info.dispatch, "description", "dispatch");
  if (!isObj(info.dispatch.params)) throw new Error("tool-info.dispatch.params must be an object");
  for (const key of ["goal", "additionalContext", "role", "taskLabel"] as const) {
    requireText(info.dispatch.params, key, "dispatch.params");
  }
  if (!isObj(info.status)) throw new Error("tool-info.status must be an object");
  requireText(info.status, "label", "status");
  requireText(info.status, "description", "status");
  if (!isObj(info.status.params)) throw new Error("tool-info.status.params must be an object");
  for (const key of ["action", "limit", "runId"] as const) {
    requireText(info.status.params, key, "status.params");
  }
  if (!isObj(info.command)) throw new Error("tool-info.command must be an object");
  requireText(info.command, "description", "command");
  if (
    !Array.isArray(info.actions) ||
    info.actions.length === 0 ||
    !info.actions.every((a: unknown) => typeof a === "string" && a.trim().length > 0)
  ) {
    throw new Error("tool-info.actions must be a non-empty array of non-empty strings");
  }
  return info as unknown as ToolInfo;
}

// -- one framed JSON connection to the core session runtime -----------------

interface Reply {
  result?: unknown;
  error?: string;
}

/** A core-produced status push. `text` is the running-only meter shown verbatim;
 * `mode_text` is the core mode chip (e.g. "(Orchestra:on)"); `native_session_ids`
 * are the opaque native worker session ids whose live Pi transcripts the adapter
 * reads fresh to render usage/cost. Optional fields (e.g. in a controlled test
 * stub) may be absent, in which case only the core text is shown. */
interface CoreStatus {
  text: string;
  mode_text?: string;
  native_session_ids?: string[];
}

type StatusHandler = (status: CoreStatus) => void;
type NativeRequest = { id: string | number; operation: string; arguments: Record<string, unknown> };
type NativeRequestHandler = (request: NativeRequest) => void;

/** A single persistent connection to one core session process. Transport only:
 * it holds a child handle and pending-request promises keyed by request id.
 * It interprets NO Orchestra state. Closing stops the connection and rejects any
 * in-flight request (a disconnect never leaves a request hanging); it never
 * touches independently-launched core execution, which lives in its own process
 * group and outlives this connection. */
class CoreSessionConnection {
  readonly parentSession: string;
  private readonly proc: ChildProcessByStdio<import("node:stream").Writable, Readable, Readable>;
  private readonly pending = new Map<string, { resolve: (r: Reply) => void; reject: (e: Error) => void }>();
  private seq = 0;
  private closed = false;
  private readonly onStatus: StatusHandler;
  private readonly onNativeRequest: NativeRequestHandler;

  constructor(
    parentSession: string,
    handlers: { onStatus: StatusHandler; onNativeRequest: NativeRequestHandler },
  ) {
    this.parentSession = parentSession;
    this.onStatus = handlers.onStatus;
    this.onNativeRequest = handlers.onNativeRequest;
    this.proc = spawn(
      orchestraPython,
      ["-m", "orchestra", "__session", "--parent-session", parentSession],
      { env: orchestraEnv(), stdio: ["pipe", "pipe", "pipe"] },
    ) as ChildProcessByStdio<import("node:stream").Writable, Readable, Readable>;

    this.proc.stdin.on("error", () => {
      /* ignore EPIPE on a child that already exited */
    });
    this.proc.stderr.setEncoding("utf8");
    this.proc.stderr.on("data", (chunk: string) => process.stderr.write(chunk));
    createInterface({ input: this.proc.stdout }).on("line", (line) => this.onLine(line));
    this.proc.on("error", (error: Error) => this.teardown(new Error(`orchestra session connection failed: ${error.message}`)));
    this.proc.on("close", () => this.teardown(new Error("orchestra session connection closed")));
  }

  get isClosed(): boolean {
    return this.closed;
  }

  /** Send one request and resolve with its correlated reply frame (which may
   * arrive out-of-band, e.g. the dispatch acknowledgement emitted on a core
   * admission thread). Rejects if the connection closes before the reply. */
  request(operation: string, args: Record<string, unknown>): Promise<Reply> {
    if (this.closed) return Promise.reject(new Error("orchestra session connection is closed"));
    const id = `req-${(this.seq += 1)}`;
    return new Promise<Reply>((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.write({ kind: "request", id, operation, arguments: args });
    });
  }

  /** Fire-and-forget a native host event (no response expected). */
  hostEvent(event: string, details: Record<string, unknown> = {}): void {
    if (this.closed) return;
    this.write({ kind: "host_event", event, details });
  }

  /** Respond to a core-initiated native_request. */
  nativeResult(id: string | number, accepted: boolean, extra: { data?: unknown; error?: string } = {}): void {
    if (this.closed) return;
    this.write({ kind: "native_result", id, accepted, ...extra });
  }

  /** Close the connection: stop the read loop and reject any in-flight request.
   * Never kills an execution process group (independent workers outlive this). */
  close(): void {
    if (this.closed) {
      this.rejectPending(new Error("orchestra session connection closed"));
      return;
    }
    this.proc.stdin.end();
    this.proc.kill("SIGTERM");
    this.teardown(new Error("orchestra session connection closed"));
  }

  private teardown(error: Error): void {
    this.closed = true;
    this.rejectPending(error);
  }

  private rejectPending(error: Error): void {
    for (const [, entry] of this.pending) entry.reject(error);
    this.pending.clear();
  }

  private write(message: Record<string, unknown>): void {
    if (this.closed || !this.proc.stdin.writable) return;
    this.proc.stdin.write(`${JSON.stringify(message)}\n`);
  }

  private onLine(line: string): void {
    // Frames that land after close are ignored: a dead connection must never
    // render, answer, or resolve anything into a replacement session.
    if (this.closed) return;
    if (!line.trim()) return;
    let message: unknown;
    try {
      message = JSON.parse(line);
    } catch {
      process.stderr.write("orchestra core sent a malformed (non-JSON) frame; ignoring it\n");
      return;
    }
    if (typeof message !== "object" || message === null) {
      process.stderr.write("orchestra core sent a malformed (non-object) frame; ignoring it\n");
      return;
    }
    const frame = message as { kind?: unknown; id?: unknown; text?: unknown; mode_text?: unknown; native_session_ids?: unknown; operation?: unknown; arguments?: unknown; result?: unknown; error?: unknown };
    if (frame.kind === "reply") {
      const id = typeof frame.id === "string" ? frame.id : null;
      if (id === null) {
        process.stderr.write("orchestra core sent a reply without a request id\n");
        return;
      }
      const entry = this.pending.get(id);
      if (!entry) {
        process.stderr.write(`orchestra core sent a reply for unknown request id ${id}\n`);
        return;
      }
      this.pending.delete(id);
      const hasError = frame.error !== undefined && frame.error !== null;
      const hasResult = frame.result !== undefined && frame.result !== null;
      if (hasError !== hasResult) {
        if (hasError) {
          if (typeof frame.error === "string") entry.reject(new CoreCommandError(frame.error));
          else entry.reject(new CoreCommandError("orchestra core reply carries a malformed error: expected a string."));
        } else {
          entry.resolve({ result: frame.result });
        }
      } else {
        entry.reject(
          new CoreCommandError(`orchestra core reply ${id} violates the reply contract: exactly one of result or error is required.`),
        );
      }
      return;
    }
    if (frame.kind === "status") {
      if (typeof frame.text === "string") {
        const ids = Array.isArray(frame.native_session_ids)
          ? frame.native_session_ids.filter((v): v is string => typeof v === "string")
          : undefined;
        this.onStatus({
          text: frame.text,
          mode_text: typeof frame.mode_text === "string" ? frame.mode_text : undefined,
          native_session_ids: ids,
        });
      }
      return;
    }
    if (frame.kind === "native_request") {
      const id = typeof frame.id === "string" || typeof frame.id === "number" ? frame.id : null;
      const operation = typeof frame.operation === "string" ? frame.operation : "";
      const args = typeof frame.arguments === "object" && frame.arguments !== null ? (frame.arguments as Record<string, unknown>) : {};
      if (id !== null && operation) this.onNativeRequest({ id, operation, arguments: args });
      return;
    }
    // Unknown frame kinds cannot be acted on, but they are never silent.
    process.stderr.write(`orchestra core sent an unknown frame kind (${String(frame.kind)})\n`);
  }
}

/** A core command/reply error carrying the real core cause verbatim (never
 * replaced with a generic success or operation-description fallback). */
class CoreCommandError extends Error {}

// -- the extension factory ---------------------------------------------------

export default async function orchestraExtension(pi: ExtensionAPI) {
  // A marked Orchestra child (a launched subagent) must never orchestrate: no
  // tool registration, no /orch to re-enable, and no core session/coordinator
  // spawn. This is the thin native mirror of the core-owned no-nesting policy
  // (src/orchestra/dispatch_guard.py); the core independently rejects any
  // dispatch that reaches it from a marked process.
  if (!orchestraCanDispatch()) return;

  // Await the core-owned tool metadata BEFORE registering tools. A failure here
  // aborts activation with the real cause; no incomplete/fallback tools register.
  const toolInfo = await loadToolInfo();

  // Transport + native handles ONLY (no Orchestra lifecycle state). Each
  // connection is bound at creation to its own native owner context; there is
  // no mutable "current native" a stale session context could overwrite, so a
  // replaced session's callbacks and tool contexts can never control or be
  // delivered through the live connection.
  let conn: CoreSessionConnection | null = null;

  function setToolsActive(enabled: boolean): void {
    const active = pi.getActiveTools();
    const withoutOrchestra = active.filter((name) => !ORCHESTRA_TOOLS.includes(name));
    pi.setActiveTools(enabled ? [...withoutOrchestra, ...ORCHESTRA_TOOLS] : withoutOrchestra);
  }

  function emitOutput(ctx: UiCtx, text: string, level: "info" | "warning" | "error" = "info"): void {
    if (ctx.hasUI) {
      ctx.ui.notify(text, level);
      return;
    }
    process.stdout.write(text.endsWith("\n") ? text : `${text}\n`);
  }

  function emitEntryOutput(ctx: UiCtx, text: string): void {
    if (ctx.hasUI) {
      pi.appendEntry("orchestra-output", { text });
      return;
    }
    process.stdout.write(text.endsWith("\n") ? text : `${text}\n`);
  }

  function toolResult(text: string, isError = false) {
    return { content: [{ type: "text" as const, text }], isError, details: undefined };
  }

  /** Map a core error (or transport error) to a tool/command error string —
   * the real cause, never a generic fallback. */
  function errorText(error: unknown): string {
    const message = error instanceof Error ? error.message : String(error);
    return message || "orchestra command failed.";
  }

  /** True only when `ctx` is the native session that owns `connection` (its
   * runtime session id matches the identity captured at that connection's
   * session_start). A tool/command context from a stale or foreign native
   * session can therefore never issue work through the live connection. */
  function ownsConnection(ctx: unknown, connection: CoreSessionConnection): boolean {
    const manager = (ctx as { sessionManager?: { getSessionId?: unknown } } | null | undefined)?.sessionManager;
    if (!manager || typeof manager.getSessionId !== "function") return false;
    try {
      return normalizePiSessionId(String((manager.getSessionId as () => unknown)())) === connection.parentSession;
    } catch {
      return false;
    }
  }

  /** The mode field must be exactly "on" or "off"; anything else is a protocol
   * error surfaced visibly, never coerced into enabled/disabled. */
  function modeEnabled(value: unknown, source: string): boolean {
    if (value === "on") return true;
    if (value === "off") return false;
    throw new CoreCommandError(`${source} returned a malformed mode (expected "on" or "off").`);
  }

  // -- native-request handling (bound to one connection and its owner) -------

  async function handleNativeRequest(connection: CoreSessionConnection, owner: UiCtx, request: NativeRequest): Promise<void> {
    if (connection.isClosed) return;
    if (request.operation === "get_parent_context") {
      try {
        const text = captureParentContextText(owner.sessionManager);
        connection.nativeResult(request.id, true, { data: { text } });
      } catch (error) {
        connection.nativeResult(request.id, false, { error: errorText(error) });
      }
      return;
    }
    if (request.operation === "deliver_report") {
      const text = (request.arguments as { text?: unknown }).text;
      if (typeof text !== "string") {
        connection.nativeResult(request.id, false, { error: "deliver_report requires a text argument" });
        return;
      }
      try {
        // Native acceptance = the host queued/started the message, NOT that the
        // model consumed the report or completed a turn.
        pi.sendUserMessage(text, { deliverAs: "steer" });
        connection.nativeResult(request.id, true);
      } catch (error) {
        connection.nativeResult(request.id, false, { error: errorText(error) });
      }
      return;
    }
    connection.nativeResult(request.id, false, { error: `unsupported native operation: ${request.operation}` });
  }

  /** Forward a native event to core (no-op when not connected). */
  function forward(event: string, details: Record<string, unknown> = {}): void {
    conn?.hostEvent(event, details);
  }

  function closeConnection(): void {
    if (conn) {
      conn.close();
      conn = null;
    }
  }

  // -- registration (uses only core-owned metadata; no adapter literals) -----

  pi.registerEntryRenderer<{ text?: string }>("orchestra-command", (entry) => new Text(entry.data?.text ?? "/orch", 0, 0));
  pi.registerEntryRenderer<{ text?: string }>("orchestra-output", (entry, _options, theme) => new Text(theme.fg("toolOutput", entry.data?.text ?? ""), 0, 0));

  pi.registerTool({
    name: "orch_dispatch",
    label: toolInfo.dispatch.label,
    description: toolInfo.dispatch.description,
    parameters: Type.Object({
      goal: Type.String({ description: toolInfo.dispatch.params.goal }),
      additionalContext: Type.Optional(Type.String({ description: toolInfo.dispatch.params.additionalContext })),
      role: Type.Optional(Type.String({ description: toolInfo.dispatch.params.role })),
      taskLabel: Type.Optional(Type.String({ description: toolInfo.dispatch.params.taskLabel })),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const typed = params as { goal: string; additionalContext?: string; role?: string; taskLabel?: string };
      const connection = conn;
      if (!connection || connection.isClosed) {
        return toolResult("orchestra is not connected to its core session for this native session.", true);
      }
      if (!ownsConnection(ctx, connection)) {
        return toolResult("orchestra ignored a tool request from a native session that no longer owns its core connection.", true);
      }
      // Forward the public dispatch fields verbatim; core validates semantics and
      // returns the complete core-owned acknowledgement text (which must carry the
      // IDs). The adapter does not reassemble a generic report or fabricate IDs.
      const args: Record<string, unknown> = { goal: typed.goal };
      if (typed.role !== undefined) args.role = typed.role;
      if (typed.taskLabel !== undefined) args.taskLabel = typed.taskLabel;
      if (typed.additionalContext !== undefined) args.additionalContext = typed.additionalContext;
      try {
        const reply = await connection.request("dispatch", args);
        return toolResult(resultText(reply));
      } catch (error) {
        return toolResult(errorText(error), true);
      }
    },
  });

  pi.registerTool({
    name: "orch_status",
    label: toolInfo.status.label,
    description: toolInfo.status.description,
    parameters: Type.Object({
      action: StringEnum(toolInfo.actions as [string, ...string[]], { description: toolInfo.status.params.action }),
      limit: Type.Optional(Type.Number({ description: toolInfo.status.params.limit })),
      runId: Type.Optional(Type.String({ description: toolInfo.status.params.runId })),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const typed = params as { action?: string; limit?: number; runId?: string };
      const connection = conn;
      const action = typeof typed.action === "string" ? typed.action : "";
      if (!connection || connection.isClosed) {
        return toolResult("orchestra is not connected to its core session for this native session.", true);
      }
      if (!ownsConnection(ctx, connection)) {
        return toolResult("orchestra ignored a tool request from a native session that no longer owns its core connection.", true);
      }
      if (!action) {
        return toolResult("orch_status requires an action.", true);
      }
      // The action is the core operation name; the whole params object is the
      // argument object. Core reads only the fields it uses (runId, limit) and
      // ignores unknown arguments. No adapter-side action semantics.
      try {
        const reply = await connection.request(action, typed as Record<string, unknown>);
        return toolResult(resultText(reply));
      } catch (error) {
        return toolResult(errorText(error), true);
      }
    },
  });

  pi.registerCommand("orch", {
    description: toolInfo.command.description,
    handler: async (rawArgs, ctx) => {
      const ui = ctx as unknown as UiCtx;
      const trimmed = rawArgs.trim();
      const [subcommand, ...rest] = trimmed.split(/\s+/);
      const emit = (text: string) => {
        pi.appendEntry("orchestra-command", { text: trimmed ? `/orch ${trimmed}` : "/orch" });
        emitEntryOutput(ui, text);
      };

      const connection = conn;
      if (!connection || connection.isClosed || !ownsConnection(ctx, connection)) {
        emitOutput(ui, "orchestra is not connected to its core session for this native session.", "error");
        return;
      }

      const run = async (operation: string, args: Record<string, unknown>) => {
        try {
          const reply = await connection.request(operation, args);
          const text = resultText(reply);
          if (operation === "mode") {
            const mode = (reply.result as { mode?: unknown } | undefined)?.mode;
            setToolsActive(modeEnabled(mode, "mode"));
          }
          emit(text);
        } catch (error) {
          emit(errorText(error));
        }
      };

      if (!subcommand || subcommand === "help") {
        await run("help", {});
        return;
      }
      if (subcommand === "on" || subcommand === "off") {
        // Core owns the mode; the reply's mode drives the native active-tool set.
        await run("mode", { mode: subcommand });
        return;
      }
      if (subcommand === "doctor") {
        await run("doctor", {});
        return;
      }
      if (subcommand === "status") {
        await run("status", {});
        return;
      }
      if (subcommand === "history") {
        const args: Record<string, unknown> = {};
        if (rest[0]) args.limit = Number(rest[0]);
        await run("history", args);
        return;
      }
      if (subcommand === "stop") {
        const runId = rest[0];
        if (!runId) {
          emitOutput(ui, "Usage: /orch stop <run-id>", "warning");
          return;
        }
        await run("stop", { runId });
        return;
      }
      if (subcommand === "do") {
        const tokens = rest.join(" ").match(/(?:[^\s"]+|"[^"]*")+/g) ?? [];
        // Strip only the paired double quotes the tokenizer grouped on; never
        // strip an arbitrary leading/trailing apostrophe from a literal token.
        const unquote = (tok: string): string =>
          tok.length >= 2 && tok.startsWith('"') && tok.endsWith('"') ? tok.slice(1, -1) : tok;
        let role: string | undefined;
        let taskLabel: string | undefined;
        const goalParts: string[] = [];
        for (let i = 0; i < tokens.length; i += 1) {
          const token = tokens[i];
          if (token === "--role" && tokens[i + 1]) {
            role = unquote(tokens[i + 1]);
            i += 1;
          } else if (token === "--task-label" && tokens[i + 1]) {
            taskLabel = unquote(tokens[i + 1]);
            i += 1;
          } else {
            goalParts.push(unquote(token));
          }
        }
        const goal = goalParts.join(" ").trim();
        if (!goal) {
          emitOutput(ui, "Usage: /orch do [--role ROLE] [--task-label LABEL] <goal>", "warning");
          return;
        }
        const args: Record<string, unknown> = { goal };
        if (role !== undefined) args.role = role;
        if (taskLabel !== undefined) args.taskLabel = taskLabel;
        await run("dispatch", args);
        return;
      }
      // Unknown subcommands are forwarded to core, which rejects them visibly
      // as unhandled operations. The adapter never answers "unknown" with a
      // local help screen or a success-shaped response.
      await run(subcommand, {});
    },
  });

  // -- lifecycle: one persistent connection per attached native session ------

  pi.on("session_start", async (_event, ctx) => {
    let parentSession: string;
    try {
      parentSession = normalizePiSessionId(ctx.sessionManager.getSessionId());
    } catch {
      return;
    }
    // Replace any existing connection before binding a new native session.
    closeConnection();
    // This connection's native owner is frozen at its session_start context.
    // Rendering and native requests are bound to THIS owner and THIS connection,
    // so a late frame from a replaced connection can neither render into nor
    // answer through the replacement session.
    const owner = ctx as unknown as UiCtx;
    // Capture the live native model handle for THIS session's footer pricing.
    // It is a native Pi handle from the current context/event, never Orchestra
    // config, and is bound to this connection so a replaced session re-prices
    // with its own model.
    const model = owner.model;
    const connection = new CoreSessionConnection(parentSession, {
      onStatus: (status) => {
        if (conn !== connection || connection.isClosed) return;
        if (!owner.hasUI) return;
        // Computed fresh per push: usage is read live from the native transcripts
        // for the ids core supplied in THIS status frame; nothing is cached.
        const theme = owner.ui.theme;
        const ids = status.native_session_ids ?? [];
        const parts: string[] = [];
        if (ids.length > 0) parts.push(usageText(readWorkerUsage(ids), model, theme));
        if (status.mode_text) parts.push(status.mode_text);
        parts.push(status.text);
        owner.ui.setWidget("orchestra", parts.join(" ").split("\n"), { placement: "belowEditor" });
      },
      onNativeRequest: (request) => {
        if (conn !== connection) return;
        void handleNativeRequest(connection, owner, request);
      },
    });
    conn = connection;
    // Announce the native session start to the (just-started) core runtime.
    connection.hostEvent("session_start");

    // Apply the core-owned initial mode to the native active-tool set (transient;
    // the mode is not cached in the adapter). A failure exposes its real cause
    // and leaves the tools disabled — there is no fallback-on.
    try {
      const reply = await connection.request("initial-mode", {});
      const mode = (reply.result as { mode?: unknown } | undefined)?.mode;
      setToolsActive(modeEnabled(mode, "initial-mode"));
    } catch (error) {
      setToolsActive(false);
      emitOutput(owner, `orchestra could not determine its initial mode; tools stay disabled: ${errorText(error)}`, "error");
    }
  });

  // Forward documented native availability/agent/compaction/session facts. Core
  // decides the Orchestra consequences; the adapter interprets none.
  pi.on("before_agent_start", () => forward("before_agent_start"));
  pi.on("agent_start", () => forward("agent_start"));
  pi.on("agent_settled", () => forward("available"));
  pi.on("session_before_compact", () => forward("compaction_start"));
  pi.on("session_compact", () => forward("compaction_end"));
  pi.on("session_compact_failed", () => forward("compaction_end"));
  pi.on("session_before_switch", () => forward("session_switch"));
  pi.on("session_before_fork", () => forward("session_switch"));

  pi.on("session_shutdown", (_event, ctx) => {
    const owner = ctx as unknown as UiCtx;
    if (owner.hasUI) owner.ui.setWidget("orchestra", undefined, { placement: "belowEditor" });
    // Signal the native session end, then stop the connection (never a worker
    // kill: independent execution keeps its own process group and outlives this).
    forward("session_end");
    closeConnection();
  });
}

/** Map a core reply's result to the displayed text. A reply whose result is not
 * core-owned text (a string, or an object carrying a string `text`) is a
 * protocol error surfaced visibly — never an empty success. */
function resultText(reply: { result?: unknown }): string {
  const result = reply.result;
  if (typeof result === "string") return result;
  if (result && typeof result === "object" && typeof (result as { text?: unknown }).text === "string") {
    return (result as { text: string }).text;
  }
  throw new CoreCommandError("orchestra core reply is malformed: result.text is missing.");
}
