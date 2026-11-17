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
import { calculateCost, type Api, type Model, type Usage } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

const PI_MODULE_ARGV = ["-m", "orchestra"];

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
}

interface AckPayload {
  run_id?: string;
  role?: string;
  ack?: string;
  jobs?: Array<{ worker_session_id?: string }>;
}

interface JobReturnPayload {
  role?: string;
  status?: string;
  summary?: string;
}

interface ReturnPayload {
  run_id?: string;
  category?: string;
  hint?: string;
  note?: string;
  jobs?: JobReturnPayload[];
  stopped?: boolean;
  return?: ReturnPayload | null;
}

interface StatusPayload {
  data?: {
    session_jobs?: Array<{ role?: string }>;
  };
}

interface DispatchParams {
  goal?: string;
  additionalContext?: string;
  role?: string;
  taskLabel?: string;
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

/** Spawn a long-running core dispatch; `onLine` receives each stdout JSONL line. */
function spawnDispatch(
  args: string[],
  input: string,
  onLine: (line: string) => void,
  onClose: (code: number | null) => void,
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
  createInterface({ input: child.stderr }).on("line", (line: string) => process.stderr.write(`${line}\n`));
  child.on("error", (error: Error) => process.stderr.write(`orchestra dispatch failed to launch: ${error.message}\n`));
  child.on("close", onClose);
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

function formatReturnMessage(payload: ReturnPayload): string {
  const lines: string[] = [];
  const runId = payload.run_id ?? "(unknown run)";
  if (payload.stopped) {
    lines.push(`Orchestra run ${runId} was stopped before completion.`);
  } else {
    lines.push(`Orchestra run ${runId} finished (${payload.category ?? "unknown"}).`);
  }
  if (payload.hint?.trim()) lines.push("", payload.hint.trim());
  const jobs = payload.jobs ?? [];
  if (jobs.length > 0) {
    lines.push("", "Jobs:");
    for (const job of jobs) {
      lines.push(`- ${job.role ?? "worker"} [${job.status ?? "?"}]: ${(job.summary ?? "").trim()}`);
    }
  }
  if (payload.note?.trim()) lines.push("", payload.note.trim());
  return lines.join("\n");
}

export default async function orchestraExtension(pi: ExtensionAPI) {
  let currentSessionId: string | null = null;
  let mode: string | null = null;
  let model: Model<Api> | undefined;
  const workerSessionIds = new Set<string>();
  const pendingReturns = new Map<string, string[]>();
  const compacting = new Set<string>();

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
    const withoutOrchestra = active.filter((name) => name !== "orch_dispatch");
    pi.setActiveTools(enabled ? [...withoutOrchestra, "orch_dispatch"] : withoutOrchestra);
  }

  async function refreshFooter(ctx: UiCtx): Promise<void> {
    if (!currentSessionId) return;
    const result = await runOrchestra(["status", "--session-id", currentSessionId]);
    if (result.code !== 0) return;
    const payload = parseJsonLine<StatusPayload>(result.stdout);
    if (!payload?.data) return;
    const roleCounts = Object.entries(
      (payload.data.session_jobs ?? []).reduce<Record<string, number>>((counts, job) => {
        if (job.role) counts[job.role] = (counts[job.role] ?? 0) + 1;
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

  function deliverReturn(sessionId: string, message: string): void {
    if (compacting.has(sessionId)) {
      pendingReturns.set(sessionId, [...(pendingReturns.get(sessionId) ?? []), message]);
      return;
    }
    pi.sendUserMessage(message, { deliverAs: "steer" });
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
  function dispatchWorker(sessionId: string, params: DispatchParams, ctx: UiCtx, onAck: (ack: AckPayload | null) => void): void {
    const goal = (params.taskLabel?.trim() ? `[${params.taskLabel.trim()}] ` : "") + (params.goal?.trim() ?? "");
    const args = ["dispatch", "--session-id", sessionId, "--goal", goal];
    const role = params.role?.trim();
    if (role) args.push("--role", role);
    let sawAck = false;
    spawnDispatch(
      args,
      params.additionalContext?.trim() ?? "",
      (line) => {
        const payload = parseJsonLine<ReturnPayload & AckPayload>(line);
        if (!payload) return;
        if (!sawAck) {
          sawAck = true;
          for (const job of payload.jobs ?? []) {
            if (job.worker_session_id) workerSessionIds.add(job.worker_session_id);
          }
          onAck(payload);
          emitOutput(ctx, `orchestra: run ${payload.run_id ?? ""} dispatched (${payload.role ?? "default role"}).`, "info");
          void refreshFooter(ctx);
          return;
        }
        emitOutput(ctx, `orchestra: run ${payload.run_id ?? ""} returned.`, "info");
        deliverReturn(sessionId, formatReturnMessage(payload.return ?? payload));
        void refreshFooter(ctx);
      },
      (code) => {
        if (!sawAck) onAck(null);
        if (code !== 0) process.stderr.write(`orchestra dispatch exited with code ${code}\n`);
      },
    );
  }

  pi.registerEntryRenderer<{ text?: string }>("orchestra-command", (entry) => {
    return new Text(entry.data?.text ?? "/orch", 0, 0);
  });

  pi.registerEntryRenderer<{ text?: string }>("orchestra-output", (entry, _options, theme) => {
    return new Text(theme.fg("toolOutput", entry.data?.text ?? ""), 0, 0);
  });

  pi.registerTool({
    name: "orch_dispatch",
    label: "Orchestra Dispatch",
    description:
      "Submit an assignment to Orchestra. Provide a goal (assignment text with scope, boundaries, stop condition, and expected return); role, additional context, and a short task label are optional. Returns the dispatch acknowledgement; execution continues in the background and one consolidated return is delivered to this session when all dispatched jobs finish. Do not poll.",
    parameters: Type.Object({
      goal: Type.String({ description: "Assignment text: goal, scope, boundaries, stop condition, expected return, and relevant prior evidence." }),
      additionalContext: Type.Optional(Type.String({ description: "Extra context piped to the dispatcher as parent context for roles configured to receive it." })),
      role: Type.Optional(Type.String({ description: "Configured role name; omitted uses the configured default role." })),
      taskLabel: Type.Optional(Type.String({ description: "Short display label prefixed to the goal." })),
    }),
    async execute(_toolCallId, params: DispatchParams, _signal, _onUpdate, ctx) {
      const goal = params.goal?.trim() ?? "";
      if (!goal) {
        return { content: [{ type: "text", text: "Usage: provide a worker goal." }], isError: true, details: undefined };
      }
      const sessionId = normalizePiSessionId(ctx.sessionManager.getSessionId());
      const ack = await new Promise<AckPayload | null>((resolve) => {
        dispatchWorker(sessionId, params, ctx as UiCtx, resolve);
      });
      if (ack === null) {
        return { content: [{ type: "text", text: "orchestra dispatch failed (see stderr)." }], isError: true, details: undefined };
      }
      return { content: [{ type: "text", text: ack.ack ?? "Assignment accepted." }], isError: false, details: undefined };
    },
  });

  pi.registerCommand("orch", {
    description: "Orchestra: /orch help|on|off|doctor|status|history|do|stop",
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
        const result = await runOrchestra(["status", "--session-id", sessionId]);
        emit(result.stdout || result.stderr);
        await refreshFooter(ctx);
        return;
      }

      if (subcommand === "history") {
        const result = await runOrchestra(["history", "--session-id", sessionId, "--limit", rest[0] ?? "10"]);
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
        let role: string | undefined;
        let taskLabel: string | undefined;
        const goalParts: string[] = [];
        for (let i = 0; i < tokens.length; i += 1) {
          const token = tokens[i];
          if (token === "--role" && tokens[i + 1]) {
            role = tokens[i + 1];
            i += 1;
          } else if (token === "--task-label" && tokens[i + 1]) {
            taskLabel = tokens[i + 1];
            i += 1;
          } else {
            goalParts.push(token.replace(/^"|"$/g, ""));
          }
        }
        const goal = goalParts.join(" ").trim();
        if (!goal) {
          emitOutput(ctx, "Usage: /orch do [--role ROLE] [--task-label LABEL] <goal>", "warning");
          return;
        }
        dispatchWorker(sessionId, { goal, role, taskLabel }, ctx, (ack) => {
          emitOutput(ctx, ack?.ack ?? "orchestra dispatch failed (see stderr).", ack ? "info" : "error");
        });
        return;
      }

      const result = await runOrchestra(["help"]);
      emitOutput(ctx, `Unknown /orch subcommand: ${subcommand}\n\n${result.stdout || result.stderr}`, "warning");
    },
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
    }
    currentSessionId = null;
    mode = null;
    workerSessionIds.clear();
  });
}
