/**
 * Orchestra 2 Pi host adapter (thin).
 *
 * Owns only host-specific concerns; all wording and behavior come from the
 * Orchestra 2 core CLI (`python3 -m orchestra`) with ORCHESTRA_CONFIG set to
 * the Orchestra 2 project root:
 *
 * - `orch_dispatch` tool: submits an assignment and returns the dispatch
 *   acknowledgement; the single session return is delivered later as a steer
 *   user message (guarded against compaction).
 * - `orch_status` tool: read-only management of the current session's work —
 *   status, history, session-owned cancellation, help, diagnostics, and the
 *   role listing.
 * - `/orch help|on|off|doctor|status|history|do|stop` command.
 * - belowEditor footer widget: token/cost, mode, and worker role meter.
 * - Entry renderers for command echoes and Orchestra output; non-UI runs
 *   fall back to stdout/stderr.
 */
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { calculateCost, StringEnum, type Api, type Model, type Usage } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

const PI_MODULE_ARGV = ["-m", "orchestra"];

/** Max bytes of child stderr retained (tail) so a pre-ack dispatch failure can
 * surface its real cause in the tool result. Full stderr is still relayed live;
 * only this bounded tail is held for the tool result. */
const STDERR_TAIL_LIMIT = 4096;

/** The Orchestra tools a session activates or deactivates as a unit. */
const ORCHESTRA_TOOLS = ["orch_dispatch", "orch_status"];

/** Fixed contract returned by `python3 -m orchestra tool-info`. */
interface ToolInfo {
  dispatch: { label: string; description: string; params: { goal: string; additionalContext: string; role: string; taskLabel: string } };
  status: { label: string; description: string; params: { action: string; limit: string; runId: string } };
  command: { description: string };
  actions: string[];
}

/** Install record written beside the extension by `./orchestra init pi`:
 * this checkout's root and dedicated interpreter, so core invocations always
 * use this checkout's project-local environment instead of an arbitrary
 * system Python. */
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

type Theme = { fg(color: string, text: string): string; bold(text: string): string };

interface UiCtx {
  hasUI: boolean;
  ui: {
    notify(msg: string, level: "info" | "warning" | "error"): void;
    setWidget(key: string, content: string[] | undefined, options?: { placement?: string }): void;
    theme: Theme;
  };
  /** Present on real Pi tool/command contexts; capture fails clearly when
   * a caller supplies a context without it. */
  sessionManager?: ParentContextSessionManager;
}

interface AckPayload {
  type?: "ack" | "return" | "event";
  run_id?: string;
  role?: string;
  ack?: string;
  task_label?: string;
  jobs?: Array<{ job_id?: string; sequence?: number; role?: string; worker_session_id?: string }>;
}

/** A dispatch acknowledgement that passed the boundary contract: the required
 * identifiers are present and non-empty, so valid-ack renderers never need a
 * "unknown"/"?" placeholder or a malformed-success fallback. */
interface ValidAck extends AckPayload {
  run_id: string;
  role: string;
  ack: string;
}

interface JobReturnPayload {
  step?: number;
  job_id?: string;
  role?: string;
  status?: string;
  summary?: string;
}

interface ReturnPayload {
  type?: "ack" | "return" | "event";
  run_id?: string;
  category?: string;
  hint?: string;
  note?: string;
  jobs?: JobReturnPayload[];
  stopped?: boolean;
  return?: ReturnPayload | null;
}

interface StatusPayload {
  rendered?: string;
  data?: {
    session_jobs?: Array<{ role?: string; status?: string }>;
  };
}

/** One core status read: rendered text for the display, structured data for
 * the footer, plus whatever core reported on failure. */
interface StatusRead {
  ok: boolean;
  rendered: string;
  payload: StatusPayload | null;
  result: { code: number; stdout: string; stderr: string };
}

interface DispatchParams {
  goal?: string;
  additionalContext?: string;
  role?: string;
  taskLabel?: string;
}

interface StatusParams {
  /** Declared as a string enum schema; the typed inference is opaque. */
  action?: unknown;
  limit?: number;
  runId?: string;
}

/** Minimal surface of the Pi session manager used for parent-context
 * capture; mirrors the documented read-only session access. */
interface ParentContextSessionManager {
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
  // Map each tool call id to whether its joined result reported isError.
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

/** Chat-only parent context: only `user`/`assistant` conversational text,
 * one role-prefixed line per non-empty message; every other role, tool call,
 * result, reasoning, and metadata is excluded, plus a deterministic references
 * digest of touched files and run commands appended after the chat lines. The
 * digest is appended only when there is chat content and at least one file or
 * command entry, so it never by itself makes an empty capture non-empty. The
 * core run artifact is the only persisted copy. */
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

function renderDispatchRequestFallback(params: DispatchParams): string {
  const lines: string[] = [];
  const goal = (params.goal ?? "").trim();
  if (goal) lines.push(`goal: ${goal}`);
  const role = (params.role ?? "").trim();
  if (role) lines.push(`role: ${role}`);
  return lines.length > 0 ? `${lines.join("\n")}\n` : "";
}

/** Capture the native Pi session context for parent-context roles. Fresh
 * sessions fall back to the dispatch request itself; an empty capture is a
 * hard error so core never receives a fake successful capture. */
function captureParentContextText(sessionManager: ParentContextSessionManager, params: DispatchParams): string {
  if (typeof sessionManager.buildContextEntries !== "function") {
    throw new Error("Pi session manager does not expose buildContextEntries()");
  }
  let text = renderParentContextArtifact(sessionManager.buildContextEntries());
  if (!text && typeof sessionManager.getBranch === "function") {
    // The current command may not be recorded in the compacted context yet.
    text = renderParentContextArtifact(sessionManager.getBranch());
  }
  if (!text) {
    // Fresh sessions have no recorded messages; capture the dispatch request itself.
    text = renderDispatchRequestFallback(params);
  }
  if (!text) throw new Error("parent context capture produced no session content");
  return text;
}

interface UsageSummary {
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
}

function normalizePiSessionId(raw: string): string {
  const normalized = raw.trim();
  if (!normalized) throw new Error("pi session id is required");
  return `pi:${normalized}`;
}

/** Environment for core CLI calls: Orchestra 2 config dir, and its src/ on
 * PYTHONPATH so `python3 -m orchestra` resolves the Orchestra 2 package. */
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

/** Load the core tool-info metadata. Throws on launch failure, nonzero exit,
 * malformed JSON, or missing required fields — activation never registers
 * incomplete/fallback tools. */
async function loadToolInfo(): Promise<ToolInfo> {
  const result = await runOrchestra(["tool-info"]);
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
  // Validate the fixed contract with small fixed checks (no validation
  // framework): every required label/description/param is a NON-EMPTY string
  // and actions is a non-empty array of non-empty strings. An empty string
  // counts as missing.
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

function runOrchestra(args: string[], input?: string): Promise<{ code: number; stdout: string; stderr: string }> {
  return new Promise((resolve) => {
    const child = spawn(orchestraPython, [...PI_MODULE_ARGV, ...args], {
      env: orchestraEnv(),
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk: string) => {
      stderr += chunk;
    });
    child.on("error", (error: Error) => {
      resolve({ code: 1, stdout: "", stderr: error.message });
    });
    child.on("close", (code: number | null) => {
      resolve({ code: code ?? 0, stdout: stdout.trim(), stderr: stderr.trim() });
    });
    child.stdin.on("error", () => {
      // Ignore EPIPE when the child exits before consuming all input.
    });
    child.stdin.end(input ?? "");
  });
}

/** Spawn a long-running core dispatch; `onLine` receives each stdout JSONL
 * line. `onClose(code, reason)` fires exactly once when the dispatch settles:
 * `reason` is a bounded diagnostic (the launch error, else the stderr tail) so a
 * pre-ack failure can be surfaced. A failed launch errors without ever closing,
 * so the terminal is guarded to avoid a double-complete or a never-settle. */
function spawnDispatch(
  args: string[],
  input: string,
  onLine: (line: string) => void,
  onClose: (code: number | null, reason: string) => void,
): void {
  const child = spawn(orchestraPython, [...PI_MODULE_ARGV, ...args], {
    env: orchestraEnv(),
    stdio: ["pipe", "pipe", "pipe"],
  });
  child.stdin.on("error", () => {
    // Ignore EPIPE when the child exits before consuming all input.
  });
  child.stdin.end(input);
  createInterface({ input: child.stdout }).on("line", onLine);
  // Relay the child's stderr live for diagnostics, and retain a bounded tail of
  // it so the launch/exit cause can be surfaced in the tool result.
  let stderrTail = "";
  createInterface({ input: child.stderr }).on("line", (line: string) => {
    process.stderr.write(`${line}\n`);
    stderrTail = (stderrTail + line + "\n").slice(-STDERR_TAIL_LIMIT);
  });
  let settled = false;
  let launchError = "";
  const finish = (code: number | null): void => {
    if (settled) return;
    settled = true;
    onClose(code, launchError || stderrTail.trim());
  };
  child.on("error", (error: Error) => {
    launchError = `orchestra dispatch failed to launch: ${error.message}`;
    process.stderr.write(`${launchError}\n`);
    finish(null);
  });
  child.on("close", (code: number | null) => finish(code));
}

/** Relay a core command failure: prefer stderr, then stdout, and report only
 * the actual transport exit code when the child produced no diagnostic text.
 * Never substitutes an operation-specific message for the real cause. */
function transportFailure(result: { code: number; stdout: string; stderr: string }): string {
  const detail = result.stderr.trim() || result.stdout.trim();
  return detail || `orchestra command failed with exit code ${result.code}.`;
}

/** Validate the first acknowledgement JSONL line against the core contract.
 * Returns null when valid, else a short cause string. Required: type "ack",
 * non-empty run_id/role/ack, and a jobs array whose entries carry job ids. */
function ackError(payload: ReturnPayload & AckPayload): string | null {
  if (payload.type !== "ack") return 'malformed acknowledgement: type is not "ack"';
  if (typeof payload.run_id !== "string" || payload.run_id.trim().length === 0) return "malformed acknowledgement: no run id";
  if (typeof payload.role !== "string" || payload.role.trim().length === 0) return "malformed acknowledgement: no role";
  if (typeof payload.ack !== "string" || payload.ack.trim().length === 0) return "malformed acknowledgement: no acknowledgement text";
  if (!Array.isArray(payload.jobs)) return "malformed acknowledgement: jobs must be an array";
  for (const job of payload.jobs) {
    // A jobs entry may be malformed (null or a non-object) from untrusted core
    // output; guard before dereferencing job_id so a malformed entry is a
    // visible protocol failure, not a TypeError thrown inside the async data
    // callback.
    if (typeof job !== "object" || job === null) return "malformed acknowledgement: a job entry is not an object";
    if (typeof job.job_id !== "string" || job.job_id.trim().length === 0) return "malformed acknowledgement: a job has no job id";
  }
  return null;
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

/** Sum token usage across the given workers' native Pi session transcripts. */
function readWorkerUsage(workerSessionIds: ReadonlySet<string>): UsageSummary {
  const total: UsageSummary = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 };
  const agentDir = process.env.PI_CODING_AGENT_DIR ?? join(process.env.HOME ?? "~", ".pi", "agent");
  const sessionRoot = process.env.PI_CODING_AGENT_SESSION_DIR ?? join(agentDir, "sessions");
  let files: string[] = [];
  try {
    files = readdirSync(sessionRoot, { recursive: true }) as string[];
  } catch {
    return total;
  }
  for (const name of files) {
    if (!workerSessionIds.has(sessionTranscriptId(name))) continue;
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

/** Worker session id embedded in a transcript file name: `..._<id>.jsonl`. */
function sessionTranscriptId(fileName: string): string {
  const base = fileName.split("/").pop() ?? fileName;
  const withoutExt = base.replace(/\.jsonl$/, "");
  return withoutExt.slice(withoutExt.indexOf("_") + 1);
}

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

function renderRoleMeter(theme: Theme, roleCounts: Array<{ role: string; count: number }>): string | undefined {
  if (roleCounts.length === 0) return undefined;
  return roleCounts
    .slice()
    .sort((left, right) => left.role.localeCompare(right.role))
    .map(({ role, count }) => {
      const activeLength = Math.min(Math.max(count, 0), role.length);
      const active = activeLength > 0 ? theme.bold(role.slice(0, activeLength).toUpperCase()) : "";
      const inactive = activeLength < role.length ? theme.fg("dim", role.slice(activeLength).toLowerCase()) : "";
      return `${active}${inactive}`;
    })
    .join(" ");
}

/** One consolidated session return: one delimited step block per delivered
 * job (the per-job boundary and step label come from core), each carrying
 * that job's actual child response verbatim, then one applicable hint. No
 * "Jobs:" heading, no internal scope-limitation note, no per-run summary
 * prose. The plugin only renders the core-supplied per-job structure. */
function formatSessionReturn(payload: ReturnPayload): string {
  const jobs = payload.jobs ?? [];
  const lines: string[] = [`Orchestra return (${payload.category ?? "unknown"}):`];
  jobs.forEach((job, index) => {
    const step = job.step ?? index + 1;
    lines.push("", `Step ${step} \u2014 ${job.role ?? "worker"} [${job.status ?? "?"}]`, (job.summary ?? "").trim());
  });
  if (payload.hint?.trim()) lines.push("", payload.hint.trim());
  return lines.join("\n");
}

export default async function orchestraExtension(pi: ExtensionAPI) {
  const toolInfo = await loadToolInfo();
  let currentSessionId: string | null = null;
  let mode: string | null = null;
  let model: Model<Api> | undefined;
  const workerSessionIds = new Set<string>();
  const pendingReturns = new Map<string, string[]>();
  const compacting = new Set<string>();
  // Session-wide return consolidation: run ids acked and awaiting their
  // return, run ids returned and awaiting the one consolidated delivery, and
  // live dispatch subprocesses whose acknowledgement has not arrived yet.
  const pendingRuns = new Map<string, Set<string>>();
  const completedRuns = new Map<string, string[]>();
  const liveSpawns = new Map<string, number>();
  const deliveryChains = new Map<string, Promise<void>>();
  // Footer refresh is event-driven: the core dispatch stream publishes one
  // lifecycle event per job transition, and each event refreshes the role
  // meter. Overlapping refreshes are coalesced into at most one in-flight
  // status round-trip plus one queued follow-up, so a burst of events cannot
  // spawn a request storm. No periodic polling remains.
  let footerRefreshInFlight = false;
  let footerRefreshQueued = false;

  function scheduleFooterRefresh(ctx: UiCtx): void {
    if (footerRefreshInFlight) {
      footerRefreshQueued = true;
      return;
    }
    footerRefreshInFlight = true;
    void (async () => {
      do {
        footerRefreshQueued = false;
        await refreshFooter(ctx);
      } while (footerRefreshQueued);
      footerRefreshInFlight = false;
    })();
  }

  function emitOutput(ctx: UiCtx, text: string, level: "info" | "warning" | "error" = "info"): void {
    if (ctx.hasUI) {
      ctx.ui.notify(text, level);
      return;
    }
    process.stdout.write(text.endsWith("\n") ? text : `${text}\n`);
  }

  function emitEntryOutput(ctx: { hasUI: boolean }, text: string): void {
    if (ctx.hasUI) {
      pi.appendEntry("orchestra-output", { text });
      return;
    }
    process.stdout.write(text.endsWith("\n") ? text : `${text}\n`);
  }

  function setToolsActive(enabled: boolean): void {
    const active = pi.getActiveTools();
    const withoutOrchestra = active.filter((name) => !ORCHESTRA_TOOLS.includes(name));
    pi.setActiveTools(enabled ? [...withoutOrchestra, ...ORCHESTRA_TOOLS] : withoutOrchestra);
  }

  /** One core status read. Its `rendered` text serves the human-facing display
   * and its structured data serves the footer, so a single subprocess covers
   * both and no refresh ever spends two reads. */
  async function readStatus(sessionId: string): Promise<StatusRead> {
    const result = await runOrchestra(["status", "--session-id", sessionId, "--mode", mode ?? "on"]);
    if (result.code !== 0) {
      return { ok: false, rendered: "", payload: null, result };
    }
    const payload = parseJsonLine<StatusPayload>(result.stdout);
    return {
      ok: true,
      rendered: payload?.rendered ?? result.stdout,
      payload,
      result,
    };
  }

  function applyFooter(ctx: UiCtx, sessionId: string, payload: StatusPayload | null): void {
    // A response for a session that is no longer the active one is discarded,
    // so a switched or shut-down session never receives a stale footer.
    if (!payload?.data || currentSessionId !== sessionId) return;
    const roleCounts = Object.entries(
      (payload.data.session_jobs ?? []).reduce<Record<string, number>>((counts, job) => {
        if (job.status === "running" && job.role) counts[job.role] = (counts[job.role] ?? 0) + 1;
        return counts;
      }, {}),
    ).map(([role, count]) => ({ role, count }));
    const theme = ctx.ui.theme;
    const parts = [usageText(readWorkerUsage(workerSessionIds), model, theme)];
    if (mode) parts.push(theme.fg("dim", `(Orchestra:${mode})`));
    const meter = renderRoleMeter(theme, roleCounts);
    if (meter) parts.push(meter);
    ctx.ui.setWidget("orchestra", parts.join(" ").split("\n"), { placement: "belowEditor" });
  }

  async function refreshFooter(ctx: UiCtx, sessionId: string | null = currentSessionId): Promise<void> {
    if (!sessionId) return;
    const status = await readStatus(sessionId);
    applyFooter(ctx, sessionId, status.payload);
  }

  function deliverReturn(sessionId: string, message: string): void {
    if (compacting.has(sessionId)) {
      pendingReturns.set(sessionId, [...(pendingReturns.get(sessionId) ?? []), message]);
      return;
    }
    pi.sendUserMessage(message, { deliverAs: "steer" });
  }

  /** Deliver one consolidated session return once every outstanding job of
   * the originating session is terminal: no dispatch subprocess is still
   * spawning/unacked, and no acked run is still executing (follow-ups stay
   * inside their run, so a run's return line implies they finished). Calls
   * are serialized per session; the gate is live process/run state, never a
   * timeout. Core blocks loudly on any outstanding session job and its
   * error text is surfaced unchanged. */
  function deliverWhenReady(sessionId: string, ctx: UiCtx): void {
    const previous = deliveryChains.get(sessionId) ?? Promise.resolve();
    const next = previous.then(() => deliverIfReady(sessionId, ctx));
    deliveryChains.set(sessionId, next.catch(() => {}));
  }

  async function deliverIfReady(sessionId: string, ctx: UiCtx): Promise<void> {
    for (;;) {
      if ((liveSpawns.get(sessionId) ?? 0) > 0) return;
      if ((pendingRuns.get(sessionId)?.size ?? 0) > 0) return;
      const runIds = completedRuns.get(sessionId) ?? [];
      if (runIds.length === 0) return;
      const args = ["session-return", "--session-id", sessionId];
      for (const runId of runIds) args.push("--run-id", runId);
      const result = await runOrchestra(args);
      if (result.code !== 0) {
        emitOutput(ctx, result.stderr || result.stdout || "orchestra session return failed.", "error");
        return;
      }
      const payload = parseJsonLine<ReturnPayload>(result.stdout);
      if (!payload?.return) {
        emitOutput(ctx, "orchestra session-return produced malformed protocol output: no assembled return.", "error");
        return;
      }
      completedRuns.delete(sessionId);
      deliverReturn(sessionId, formatSessionReturn(payload.return));
    }
  }

  pi.on("session_before_compact", async () => {
    if (currentSessionId) compacting.add(currentSessionId);
  });

  function finishCompaction(): void {
    const sessionId = currentSessionId;
    if (!sessionId) return;
    compacting.delete(sessionId);
    const pending = pendingReturns.get(sessionId);
    if (!pending?.length) return;
    pendingReturns.delete(sessionId);
    for (const message of pending) {
      pi.sendUserMessage(message, { deliverAs: "steer" });
    }
  }

  pi.on("session_compact", finishCompaction);
  pi.on("session_compact_failed", finishCompaction);

  /** Spawn the core dispatch; the first stdout JSONL line (the ack) resolves
   * `onAck`; the second (the return) is delivered to the session as a steer. */
  function dispatchWorker(sessionId: string, params: DispatchParams, ctx: UiCtx, onAck: (ack: ValidAck | null, reason?: string) => void): void {
    let goal = params.goal?.trim() ?? "";
    // Additional context is assignment data carried in the goal text; it is
    // never a substitute for the native session history piped on stdin.
    const additionalContext = params.additionalContext?.trim();
    if (goal && additionalContext) {
      goal = `${goal}\n\nAdditional context:\n${additionalContext}`;
    }
    // Native Pi session context: core persists it only for roles that opt
    // in via their catalog parent_context setting; other roles ignore it.
    let parentContextInput: string;
    try {
      parentContextInput = captureParentContextText(ctx.sessionManager ?? {}, params);
    } catch (error) {
      const message = (error as { message?: string }).message ?? String(error);
      onAck(null, `parent context capture failed: ${message}`);
      emitOutput(ctx, `orchestra: parent context capture failed: ${message}`, "error");
      return;
    }
    const args = ["dispatch", "--session-id", sessionId, "--goal", goal];
    const role = params.role?.trim();
    if (role) args.push("--role", role);
    // The task label is forwarded literally: a supplied value is passed exactly
    // as given (including an empty string); only an absent value omits the flag.
    if (params.taskLabel !== undefined) args.push("--task-label", params.taskLabel);
    liveSpawns.set(sessionId, (liveSpawns.get(sessionId) ?? 0) + 1);
    let ackResolved = false;
    let sawAck = false;
    let sawReturn = false;
    let ackedRunId = "";
    spawnDispatch(
      args,
      parentContextInput,
      (line) => {
        const payload = parseJsonLine<ReturnPayload & AckPayload>(line);
        if (!payload) return;
        if (payload.type === "event") {
          // A generic mid-run lifecycle transition for this dispatch. It is
          // neither the ack nor the return; refresh the role meter only while
          // this dispatch's own session is still the active one, so a
          // switched or shut-down session never receives a stale update.
          if (sessionId === currentSessionId) scheduleFooterRefresh(ctx);
          return;
        }
        if (!ackResolved) {
          ackResolved = true;
          const invalid = ackError(payload);
          if (invalid) {
            // A malformed first acknowledgement is rejected once with its cause:
            // no run tracking, no success notification, and no fallback ack.
            liveSpawns.set(sessionId, Math.max((liveSpawns.get(sessionId) ?? 1) - 1, 0));
            onAck(null, invalid);
            return;
          }
          sawAck = true;
          ackedRunId = payload.run_id ?? "";
          liveSpawns.set(sessionId, (liveSpawns.get(sessionId) ?? 1) - 1);
          const pending = pendingRuns.get(sessionId) ?? new Set<string>();
          pending.add(ackedRunId);
          pendingRuns.set(sessionId, pending);
          for (const job of payload.jobs ?? []) {
            if (job.worker_session_id) workerSessionIds.add(job.worker_session_id);
          }
          onAck(payload as unknown as ValidAck);
          emitOutput(ctx, `orchestra: run ${payload.run_id} dispatched (${payload.role}).`, "info");
          scheduleFooterRefresh(ctx);
          return;
        }
        if (!sawAck) {
          // The acknowledgement was rejected as malformed; ignore any later line
          // so it cannot masquerade as a successful return.
          return;
        }
        sawReturn = true;
        const runId = payload.run_id ?? ackedRunId;
        pendingRuns.get(sessionId)?.delete(runId);
        emitOutput(ctx, `orchestra: run ${runId} returned.`, "info");
        if (payload.stopped) {
          // Cancellation is reported immediately; a stopped run may leave
          // pending jobs, so it is excluded from the consolidated return.
          deliverReturn(sessionId, `Orchestra run ${runId} was stopped before completion.`);
        } else {
          completedRuns.set(sessionId, [...(completedRuns.get(sessionId) ?? []), runId]);
        }
        if (sessionId === currentSessionId) scheduleFooterRefresh(ctx);
        deliverWhenReady(sessionId, ctx);
      },
      (code, reason) => {
        if (!ackResolved) {
          liveSpawns.set(sessionId, Math.max((liveSpawns.get(sessionId) ?? 1) - 1, 0));
          onAck(null, reason);
        } else if (sawAck && !sawReturn) {
          // The dispatch CLI died after acknowledging: report the run as
          // drained; core blocks loudly if any of its jobs is still
          // outstanding, and that error is surfaced unchanged.
          pendingRuns.get(sessionId)?.delete(ackedRunId);
          deliverWhenReady(sessionId, ctx);
        }
        if (sessionId === currentSessionId) scheduleFooterRefresh(ctx);
        // A launch error already reported its cause via `reason`; only a real
        // nonzero child exit code needs this extra diagnostic line.
        if (code !== null && code !== 0) process.stderr.write(`orchestra dispatch exited with code ${code}\n`);
      },
    );
  }

  pi.registerEntryRenderer<{ text?: string }>("orchestra-command", (entry) => {
    return new Text(entry.data?.text ?? "/orch", 0, 0);
  });

  pi.registerEntryRenderer<{ text?: string }>("orchestra-output", (entry, _options, theme) => {
    return new Text(theme.fg("toolOutput", entry.data?.text ?? ""), 0, 0);
  });

  function toolResult(text: string, isError = false) {
    return { content: [{ type: "text" as const, text }], isError, details: undefined };
  }

  /** Failure text for a pre-ack dispatch: the captured launch/stderr cause when
   * available, else a clear fallback. Never mixes a child cause into a success. */
  function dispatchFailureText(reason?: string): string {
    const detail = (reason ?? "").trim();
    return detail ? `orchestra dispatch failed: ${detail}` : "orchestra dispatch failed with no diagnostic output.";
  }

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
    async execute(_toolCallId, params: DispatchParams, _signal, _onUpdate, ctx) {
      const sessionId = normalizePiSessionId(ctx.sessionManager.getSessionId());
      const { ack, reason } = await new Promise<{ ack: ValidAck | null; reason?: string }>((resolve) => {
        dispatchWorker(sessionId, params, ctx as UiCtx, (a, r) => resolve({ ack: a, reason: r }));
      });
      if (ack === null) {
        return toolResult(dispatchFailureText(reason), true);
      }
      // The acknowledgement already passed the boundary contract, so run id,
      // role, and ack text are present and non-empty; no placeholder fallback.
      // The identifiers the caller needs to follow up: the run id for
      // `orch_status stop`, plus every job id the run contains.
      const jobLabels = (ack.jobs ?? [])
        .map((job) => (job.job_id ? `${job.job_id}${job.role ? ` (${job.role})` : ""}` : ""))
        .filter((label) => label.length > 0)
        .join(", ");
      const identifiers = [`Run ${ack.run_id}.`, jobLabels ? `Jobs: ${jobLabels}.` : ""]
        .filter((part) => part.length > 0)
        .join(" ");
      const label = ack.task_label !== undefined ? `Label: ${ack.task_label}.` : "";
      const ackText = [`${ack.ack.trim()} Role: ${ack.role}.`, identifiers, label]
        .filter((part) => part.length > 0)
        .join(" ");
      return { content: [{ type: "text", text: ackText }], isError: false, details: undefined };
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
    async execute(_toolCallId, params: StatusParams, _signal, _onUpdate, ctx) {
      const sessionId = normalizePiSessionId(ctx.sessionManager.getSessionId());
      const ui = ctx as UiCtx;
      const action = typeof params.action === "string" ? params.action : "";
      if (action === "status") {
        const status = await readStatus(sessionId);
        if (!status.ok) return toolResult(transportFailure(status.result), true);
        applyFooter(ui, sessionId, status.payload);
        return toolResult(status.rendered);
      }
      if (action === "history") {
        const limit = params.limit;
        const args = ["history", "--session-id", sessionId];
        if (limit !== undefined) args.push("--limit", String(limit));
        const result = await runOrchestra(args);
        if (result.code !== 0) return toolResult(transportFailure(result), true);
        return toolResult(result.stdout);
      }
      if (action === "stop") {
        const args = ["stop", "--session-id", sessionId];
        if (params.runId !== undefined) args.push("--run-id", params.runId.trim());
        const result = await runOrchestra(args);
        const status = await readStatus(sessionId);
        applyFooter(ui, sessionId, status.payload);
        if (result.code !== 0) return toolResult(transportFailure(result), true);
        return toolResult(result.stdout);
      }
      const passthrough = await runOrchestra([action]);
      if (passthrough.code !== 0) return toolResult(transportFailure(passthrough), true);
      return toolResult(passthrough.stdout);
    },
  });

  pi.registerCommand("orch", {
    description: toolInfo.command.description,
    handler: async (args, ctx) => {
      const trimmed = args.trim();
      const sessionId = normalizePiSessionId(ctx.sessionManager.getSessionId());
      const [subcommand, ...rest] = trimmed.split(/\s+/);
      const emit = (text: string) => {
        pi.appendEntry("orchestra-command", { text: trimmed ? `/orch ${trimmed}` : "/orch" });
        emitEntryOutput(ctx, text);
      };

      if (!subcommand || subcommand === "help") {
        const result = await runOrchestra(["help"]);
        emit(result.stdout || result.stderr);
        return;
      }

      if (subcommand === "on" || subcommand === "off") {
        mode = subcommand;
        setToolsActive(subcommand === "on");
        emitOutput(ctx, `Orchestra ${subcommand}.`, "info");
        await refreshFooter(ctx);
        return;
      }

      if (subcommand === "doctor") {
        const result = await runOrchestra(["doctor"]);
        emit(result.stdout || result.stderr);
        return;
      }

      if (subcommand === "status") {
        const status = await readStatus(sessionId);
        emit(status.ok ? status.rendered : transportFailure(status.result));
        if (status.ok) applyFooter(ctx, sessionId, status.payload);
        return;
      }

      if (subcommand === "history") {
        const args = ["history", "--session-id", sessionId];
        if (rest[0]) args.push("--limit", rest[0]);
        const result = await runOrchestra(args);
        emit(result.stdout || result.stderr);
        return;
      }

      if (subcommand === "stop") {
        const runId = rest[0];
        if (!runId) {
          emitOutput(ctx, "Usage: /orch stop <run-id>", "warning");
          return;
        }
        const result = await runOrchestra(["stop", "--session-id", sessionId, "--run-id", runId]);
        emit(result.stdout || result.stderr);
        await refreshFooter(ctx);
        return;
      }

      if (subcommand === "do") {
        const tokens = rest.join(" ").match(/(?:[^\s"]+|"[^"]*")+/g) ?? [];
        // Strip only the paired double quotes the tokenizer above groups on;
        // never strip an arbitrary leading/trailing apostrophe from a literal
        // token (e.g. O'Connor' must keep its trailing apostrophe).
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
          emitOutput(ctx, "Usage: /orch do [--role ROLE] [--task-label LABEL] <goal>", "warning");
          return;
        }
        dispatchWorker(sessionId, { goal, role, taskLabel }, ctx, (ack, reason) => {
          if (ack) {
            const label = ack.task_label !== undefined ? ` Label: ${ack.task_label}.` : "";
            emitOutput(ctx, `${ack.ack.trim()} Role: ${ack.role}. Run: ${ack.run_id}.${label}`, "info");
          } else {
            emitOutput(ctx, dispatchFailureText(reason), "error");
          }
        });
        return;
      }

      const result = await runOrchestra(["help"]);
      emitOutput(ctx, `Unknown /orch subcommand: ${subcommand}\n\n${result.stdout || result.stderr}`, "warning");
    },
  });

  pi.on("before_agent_start", async (_event, ctx) => {
    // One status read per agent-run start, from the session identity in the
    // runtime context: the same response refreshes the footer, so persisted
    // state that changed without a lifecycle event is reflected before the
    // run proceeds. No timer, polling loop, or watcher is involved, and a
    // response for a session that has since been switched is discarded.
    let sessionId: string;
    try {
      sessionId = normalizePiSessionId(ctx.sessionManager.getSessionId());
    } catch {
      return;
    }
    await refreshFooter(ctx as UiCtx, sessionId);
  });

  pi.on("session_start", async (_event, ctx) => {
    try {
      currentSessionId = normalizePiSessionId(ctx.sessionManager.getSessionId());
    } catch {
      currentSessionId = null;
      return;
    }
    compacting.delete(currentSessionId);
    pendingReturns.delete(currentSessionId);
    pendingRuns.delete(currentSessionId);
    completedRuns.delete(currentSessionId);
    liveSpawns.delete(currentSessionId);
    deliveryChains.delete(currentSessionId);
    workerSessionIds.clear();
    model = ctx.model;
    mode = null;
    try {
      const result = await runOrchestra(["initial-mode"]);
      mode = result.code === 0 && result.stdout.trim() ? result.stdout.trim() : null;
    } catch {
      mode = null;
    }
    setToolsActive(mode !== "off");
    await refreshFooter(ctx);
  });

  pi.on("session_shutdown", async (_event, ctx) => {
    ctx.ui.setWidget("orchestra", undefined, { placement: "belowEditor" });
    if (currentSessionId) {
      compacting.delete(currentSessionId);
      pendingReturns.delete(currentSessionId);
      pendingRuns.delete(currentSessionId);
      completedRuns.delete(currentSessionId);
      liveSpawns.delete(currentSessionId);
      deliveryChains.delete(currentSessionId);
    }
    currentSessionId = null;
    mode = null;
    workerSessionIds.clear();
  });
}
