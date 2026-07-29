import { execFile, spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { promisify } from "node:util";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

const execFileAsync = promisify(execFile);

function normalizePiSessionId(raw: string): string {
  const normalized = raw.trim();
  if (!normalized) throw new Error("pi session id is required");
  return `pi:${normalized}`;
}

function emitOutput(ctx: { hasUI: boolean; ui: { notify: (msg: string, level: "info" | "warning" | "error") => void } }, output: string, level: "info" | "warning" | "error" = "info"): void {
  if (ctx.hasUI) {
    ctx.ui.notify(output, level);
    return;
  }
  process.stdout.write(output.endsWith("\n") ? output : `${output}\n`);
}

function orchestraBaseArgs(): string[] {
  const args: string[] = [];
  if (process.env.ORCHESTRA_CONFIG) {
    args.push("--config", process.env.ORCHESTRA_CONFIG);
  }
  if (process.env.ORCHESTRA_AGENT_CATALOG) {
    args.push("--agent-catalog", process.env.ORCHESTRA_AGENT_CATALOG);
  }
  return args;
}

async function runOrchestra(args: string[]): Promise<{ code: number; stdout: string; stderr: string }> {
  try {
    const { stdout, stderr } = await execFileAsync("orchestra", [...orchestraBaseArgs(), ...args], { encoding: "utf8" });
    return { code: 0, stdout: stdout.trim(), stderr: stderr.trim() };
  } catch (error) {
    const err = error as { code?: number; stdout?: string; stderr?: string; message: string };
    return {
      code: err.code ?? 1,
      stdout: (err.stdout ?? "").trim(),
      stderr: (err.stderr ?? err.message).trim(),
    };
  }
}

function parseDoArgs(args: string): { role: string; timeout: string | null; taskLabel: string | null; goal: string } {
  const parts = args.trim().split(/\s+/).filter(Boolean);
  let role = "worker";
  let timeout: string | null = null;
  let taskLabel: string | null = null;
  const goalParts: string[] = [];

  for (let i = 0; i < parts.length; i += 1) {
    const token = parts[i];
    if (token === "--role" && parts[i + 1]) {
      role = parts[i + 1];
      i += 1;
      continue;
    }
    if (token === "--timeout" && parts[i + 1]) {
      timeout = parts[i + 1];
      i += 1;
      continue;
    }
    if (token === "--task-label" && parts[i + 1]) {
      taskLabel = parts[i + 1];
      i += 1;
      continue;
    }
    goalParts.push(token);
  }

  return {
    role,
    timeout,
    taskLabel,
    goal: goalParts.join(" ").trim(),
  };
}

function extractRunId(output: string): string | null {
  for (const line of output.split(/\r?\n/)) {
    const match = /^run_id:\s+(.+)$/.exec(line.trim());
    if (match) return match[1].trim();
  }
  return null;
}

interface OrchestraCommandEntry {
  text: string;
}

interface OrchestraOutputEntry {
  text: string;
}

interface DispatchParams {
  goal?: string;
  role?: string;
  timeout?: number;
  taskLabel?: string;
}

interface DispatchResult {
  code: number;
  runId: string | null;
  output: string;
}

interface ProgressNotifier {
  notify(message: string): void;
}

interface ToolInfoPayload {
  description: string;
  promptSnippet: string;
  promptGuidelines: string[];
  goalDescription: string;
  roleDescription: string;
  timeoutDescription: string;
  taskLabelDescription: string;
}

async function hostHelp(): Promise<string> {
  const result = await runOrchestra(["help-host"]);
  return result.stdout || result.stderr;
}

async function commandEchoText(trimmed: string): Promise<string> {
  const result = await runOrchestra(["_command-echo", trimmed]);
  return result.stdout || (trimmed ? `/orch ${trimmed}` : "/orch");
}

async function loadToolInfo(): Promise<ToolInfoPayload> {
  const result = await runOrchestra(["_tool-info"]);
  if (result.code === 0 && result.stdout.trim()) {
    return JSON.parse(result.stdout) as ToolInfoPayload;
  }
  return {
    description: "Delegate or dispatch a focused task to an Orchestra worker/subagent.",
    promptSnippet: "Dispatch focused work to Orchestra workers/subagents.",
    promptGuidelines: ["Use orch_dispatch for narrow delegated worker tasks."],
    goalDescription: "Focused worker request/task to delegate.",
    roleDescription: "Optional exact configured role. Omit for default worker role.",
    timeoutDescription: "Optional timeout in seconds.",
    taskLabelDescription: "Optional short request label.",
  };
}

export default async function orchestraExtension(pi: ExtensionAPI) {
  let currentSessionId: string | null = null;
  const reportWatchers = new Map<string, Set<ChildProcessWithoutNullStreams>>();
  const sessionRuns = new Map<string, Set<string>>();
  const sessionCompletedRuns = new Map<string, Set<string>>();

  pi.registerEntryRenderer<OrchestraCommandEntry>("orchestra-command", (entry) => {
    const text = entry.data?.text ?? "/orch";
    return new Text(text, 0, 0);
  });

  pi.registerEntryRenderer<OrchestraOutputEntry>("orchestra-output", (entry, _context, theme) => {
    const text = entry.data?.text ?? "";
    return new Text(theme.fg("toolOutput", text), 0, 0);
  });

  function emitEntryOutput(ctx: { hasUI: boolean }, text: string): void {
    if (ctx.hasUI) {
      pi.appendEntry<OrchestraOutputEntry>("orchestra-output", { text });
      return;
    }
    process.stdout.write(text.endsWith("\n") ? text : `${text}\n`);
  }

  function parseAwaitRunOutput(output: string): { status: string | null; role: string | null; activeRemaining: number | null } {
    let status: string | null = null;
    let role: string | null = null;
    let activeRemaining: number | null = null;
    for (const line of output.split(/\r?\n/)) {
      const trimmed = line.trim();
      const statusMatch = /^status:\s+(.+)$/.exec(trimmed);
      if (statusMatch) status = statusMatch[1].trim();
      const roleMatch = /^role:\s+(.+)$/.exec(trimmed);
      if (roleMatch) role = roleMatch[1].trim();
      const activeMatch = /^active_runs_remaining:\s+(\d+)$/.exec(trimmed);
      if (activeMatch) activeRemaining = Number(activeMatch[1]);
    }
    return { status, role, activeRemaining };
  }

  function progressNotifier(ctx: { hasUI: boolean; ui: { notify: (msg: string, level: "info" | "warning" | "error") => void } }): ProgressNotifier {
    if (!ctx.hasUI) {
      return { notify: (message: string) => process.stderr.write(`${message}\n`) };
    }
    const notify = ctx.ui.notify.bind(ctx.ui);
    return { notify: (message: string) => notify(message, "info") };
  }

  function trackRun(sessionId: string, runId: string): void {
    const runs = sessionRuns.get(sessionId) ?? new Set<string>();
    runs.add(runId);
    sessionRuns.set(sessionId, runs);
    if (!sessionCompletedRuns.has(sessionId)) sessionCompletedRuns.set(sessionId, new Set<string>());
  }

  function stopSessionWatchers(sessionId: string | null): void {
    if (!sessionId) return;
    const watchers = reportWatchers.get(sessionId);
    if (!watchers) return;
    for (const watcher of watchers) {
      try {
        watcher.kill("SIGTERM");
      } catch {
        // ignore shutdown races
      }
    }
    reportWatchers.delete(sessionId);
    sessionRuns.delete(sessionId);
    sessionCompletedRuns.delete(sessionId);
  }

  function watchRunProgress(sessionId: string, runId: string, notifier: ProgressNotifier): void {
    const child = spawn(
      "orchestra",
      [
        ...orchestraBaseArgs(),
        "_await-run",
        "--session-id",
        sessionId,
        "--run-id",
        runId,
      ],
      { stdio: ["ignore", "pipe", "pipe"] },
    );

    let stdout = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });

    child.on("close", (code) => {
      if (code !== 0) return;
      const completed = sessionCompletedRuns.get(sessionId) ?? new Set<string>();
      completed.add(runId);
      sessionCompletedRuns.set(sessionId, completed);
      const { status, role, activeRemaining } = parseAwaitRunOutput(stdout);
      const total = sessionRuns.get(sessionId)?.size ?? completed.size + (activeRemaining ?? 0);
      const command = [
        "_progress-message",
        "--completed",
        String(completed.size),
        "--total",
        String(total),
        "--run-id",
        runId,
        "--status",
        status ?? "done",
      ];
      if (role) command.push("--role", role);
      void runOrchestra(command).then((result) => {
        const roleText = role ? ` ${role}` : "";
        notifier.notify(result.stdout || `orchestra:${roleText} ${runId} returned ${status ?? "done"} (${completed.size}/${total})`);
        if (activeRemaining === 0) {
          sessionRuns.delete(sessionId);
          sessionCompletedRuns.delete(sessionId);
        }
      });
    });
  }

  async function dispatchWorker(
    sessionId: string,
    params: DispatchParams,
    notifier: ProgressNotifier,
  ): Promise<DispatchResult> {
    const goal = params.goal?.trim() ?? "";
    if (!goal) return { code: 1, runId: null, output: "Usage: provide a worker goal." };

    const command = [
      "do",
      "--session-id",
      sessionId,
      "--role",
      params.role?.trim() || "worker",
      "--goal",
      goal,
    ];
    if (params.timeout !== undefined) {
      command.push("--timeout", String(params.timeout));
    }
    if (params.taskLabel?.trim()) {
      command.push("--task-label", params.taskLabel.trim());
    }

    const result = await runOrchestra(command);
    const runId = result.code === 0 ? extractRunId(result.stdout) : null;
    if (runId) {
      trackRun(sessionId, runId);
      watchRunProgress(sessionId, runId, notifier);
      watchSessionReport(sessionId, runId);
      const role = params.role?.trim() || "worker";
      const ack = await runOrchestra(["_dispatch-ack", "--run-id", runId, "--role", role]);
      return { code: 0, runId, output: ack.stdout || `orchestra dispatched: ${role} ${runId}` };
    }
    return { code: result.code, runId: null, output: result.stdout || result.stderr };
  }

  function watchSessionReport(sessionId: string, runId: string): void {
    if (reportWatchers.has(sessionId)) return;

    const child = spawn(
      "orchestra",
      [
        ...orchestraBaseArgs(),
        "_await-session-report",
        "--session-id",
        sessionId,
        "--run-id",
        runId,
        "--json",
      ],
      {
        stdio: ["ignore", "pipe", "pipe"],
      },
    );

    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });

    const watchers = reportWatchers.get(sessionId) ?? new Set<ChildProcessWithoutNullStreams>();
    watchers.add(child);
    reportWatchers.set(sessionId, watchers);

    child.on("close", (code) => {
      watchers.delete(child);
      if (watchers.size === 0) reportWatchers.delete(sessionId);

      const rawReport = stdout.trim();
      if (code === 0 && rawReport) {
        let runIds: string[] = [];
        try {
          const payload = JSON.parse(rawReport) as { runIds?: string[]; report?: string };
          runIds = payload.runIds ?? [];
          const message = payload.report?.trim() ?? "";
          if (!message) return;
          pi.sendUserMessage(message, { deliverAs: "followUp", triggerTurn: true });
          if (runIds.length > 0) {
            void runOrchestra([
              "_mark-session-report-delivered",
              "--session-id",
              sessionId,
              ...runIds.flatMap((id) => ["--run-id", id]),
            ]);
          }
        } catch (error) {
          if (runIds.length > 0) {
            void runOrchestra([
              "_release-session-report",
              "--session-id",
              sessionId,
              ...runIds.flatMap((id) => ["--run-id", id]),
            ]);
          }
          const err = error as { message?: string };
          process.stderr.write(`orchestra auto-return reinjection failed: ${err.message ?? String(error)}\n`);
        }
        return;
      }

      const errorText = stderr.trim();
      if (code && errorText) {
        process.stderr.write(`orchestra auto-return watcher failed: ${errorText}\n`);
      }
    });
  }

  pi.on("session_start", async (_event, ctx) => {
    currentSessionId = normalizePiSessionId(ctx.sessionManager.getSessionId());
  });

  pi.on("session_shutdown", async () => {
    stopSessionWatchers(currentSessionId);
    currentSessionId = null;
  });

  const toolInfo = await loadToolInfo();

  pi.registerTool({
    name: "orch_dispatch",
    label: "Orchestra Dispatch",
    description: toolInfo.description,
    promptSnippet: toolInfo.promptSnippet,
    promptGuidelines: toolInfo.promptGuidelines,
    parameters: Type.Object({
      goal: Type.String({ description: toolInfo.goalDescription }),
      role: Type.Optional(Type.String({ description: toolInfo.roleDescription })),
      timeout: Type.Optional(Type.Number({ description: toolInfo.timeoutDescription })),
      taskLabel: Type.Optional(Type.String({ description: toolInfo.taskLabelDescription })),
    }),
    async execute(_toolCallId, params: DispatchParams, _signal, _onUpdate, ctx) {
      const runtimeSessionId = normalizePiSessionId(ctx.sessionManager.getSessionId());
      const result = await dispatchWorker(runtimeSessionId, params, progressNotifier(ctx));
      return {
        content: [{ type: "text", text: result.output }],
        isError: result.code !== 0,
      };
    },
  });

  pi.registerCommand("orch", {
    description: "Orchestra host adapter: /orch do|status|stop|doctor|history",
    handler: async (args, ctx) => {
      const trimmed = args.trim();
      pi.appendEntry<OrchestraCommandEntry>("orchestra-command", {
        text: await commandEchoText(trimmed),
      });
      if (!trimmed) {
        emitEntryOutput(ctx, await hostHelp());
        return;
      }

      const [subcommand, ...rest] = trimmed.split(/\s+/);
      const runtimeSessionId = normalizePiSessionId(ctx.sessionManager.getSessionId());

      if (subcommand === "help") {
        emitEntryOutput(ctx, await hostHelp());
        return;
      }

      if (subcommand === "doctor") {
        const result = await runOrchestra(["doctor"]);
        emitEntryOutput(ctx, result.stdout || result.stderr);
        return;
      }

      if (subcommand === "status") {
        const result = await runOrchestra(["status", "--session-id", runtimeSessionId]);
        emitEntryOutput(ctx, result.stdout || result.stderr);
        return;
      }

      if (subcommand === "history") {
        const limit = rest[0] ?? "10";
        const result = await runOrchestra([
          "history",
          "--session-id",
          runtimeSessionId,
          "--limit",
          limit,
        ]);
        emitEntryOutput(ctx, result.stdout || result.stderr);
        return;
      }

      if (subcommand === "stop") {
        const runId = rest[0];
        if (!runId) {
          emitOutput(ctx, "Usage: /orch stop <run-id>", "warning");
          return;
        }
        const result = await runOrchestra([
          "stop",
          "--session-id",
          runtimeSessionId,
          "--run-id",
          runId,
        ]);
        emitEntryOutput(ctx, result.stdout || result.stderr);
        return;
      }

      if (subcommand === "do") {
        const parsed = parseDoArgs(rest.join(" "));
        if (!parsed.goal) {
          emitOutput(ctx, "Usage: /orch do [--role ROLE] [--timeout SEC] [--task-label LABEL] <goal>", "warning");
          return;
        }
        const result = await dispatchWorker(
          runtimeSessionId,
          {
            goal: parsed.goal,
            role: parsed.role,
            timeout: parsed.timeout === null ? undefined : Number(parsed.timeout),
            taskLabel: parsed.taskLabel ?? undefined,
          },
          progressNotifier(ctx),
        );
        emitOutput(ctx, result.output, result.code === 0 ? "info" : "error");
        return;
      }

      emitOutput(ctx, `Unknown /orch subcommand: ${subcommand}\n\n${await hostHelp()}`, "warning");
    },
  });
}
