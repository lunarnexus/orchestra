import { execFile, spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { promisify } from "node:util";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { Type } from "typebox";

const execFileAsync = promisify(execFile);
const TOOL_TIMEOUT_ERROR = "timeout is not accepted by orch_dispatch; configured default_timeout applies.";
const ORCHESTRA_WORKER_ENV = "ORCHESTRA_WORKER";

interface OrchestraFooterTheme {
  bold(text: string): string;
  fg(color: string, text: string): string;
}

interface ActiveRoleCount {
  role: string;
  count: number;
}

interface ActiveSessionStatus {
  activeCount: number;
  roleCounts: ActiveRoleCount[];
  runIds: string[];
}

function renderOrchestraWorkerStatus(theme: OrchestraFooterTheme, roleCounts: ActiveRoleCount[]): string | undefined {
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

function setOrchestraWorkerStatus(
  ctx: { ui: { setStatus: (key: string, msg: string | undefined) => void; theme: OrchestraFooterTheme } },
  status: ActiveSessionStatus | null,
): void {
  ctx.ui.setStatus(
    "orchestra",
    status && status.activeCount > 0 ? renderOrchestraWorkerStatus(ctx.ui.theme, status.roleCounts) : undefined,
  );
}

function orchestraWorkerBudget(): number {
  const raw = process.env[ORCHESTRA_WORKER_ENV]?.trim();
  if (!raw) return 0;
  const parsed = Number(raw);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : 1;
}

function canDispatchOrchestraWorker(): boolean {
  return orchestraWorkerBudget() !== 1;
}

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

interface TokenizeArgsResult {
  tokens: string[];
  trailingSpace: boolean;
  error: string | null;
}

interface ParsedDoArgs {
  role: string | null;
  timeout: string | null;
  taskLabel: string | null;
  goal: string;
  error: string | null;
}

function tokenizeArgs(input: string): TokenizeArgsResult {
  const tokens: string[] = [];
  let current = "";
  let quote: '"' | "'" | null = null;
  let escaping = false;

  for (const char of input) {
    if (escaping) {
      current += char;
      escaping = false;
      continue;
    }

    if (char === "\\") {
      escaping = true;
      continue;
    }

    if (quote) {
      if (char === quote) {
        quote = null;
      } else {
        current += char;
      }
      continue;
    }

    if (char === '"' || char === "'") {
      quote = char;
      continue;
    }

    if (/\s/.test(char)) {
      if (current) {
        tokens.push(current);
        current = "";
      }
      continue;
    }

    current += char;
  }

  if (escaping) {
    current += "\\";
  }
  if (quote) {
    return { tokens: [], trailingSpace: /\s$/.test(input), error: "Malformed quoted string in /orch do arguments" };
  }
  if (current) {
    tokens.push(current);
  }

  return {
    tokens,
    trailingSpace: /\s$/.test(input),
    error: null,
  };
}

function parseDoArgs(args: string): ParsedDoArgs {
  const tokenized = tokenizeArgs(args);
  if (tokenized.error) {
    return {
      role: null,
      timeout: null,
      taskLabel: null,
      goal: "",
      error: tokenized.error,
    };
  }

  let role: string | null = null;
  let timeout: string | null = null;
  let taskLabel: string | null = null;
  const goalParts: string[] = [];

  for (let i = 0; i < tokenized.tokens.length; i += 1) {
    const token = tokenized.tokens[i];
    if (token === "--role" && tokenized.tokens[i + 1]) {
      role = tokenized.tokens[i + 1];
      i += 1;
      continue;
    }
    if (token === "--timeout" && tokenized.tokens[i + 1]) {
      timeout = tokenized.tokens[i + 1];
      i += 1;
      continue;
    }
    if (token === "--task-label" && tokenized.tokens[i + 1]) {
      taskLabel = tokenized.tokens[i + 1];
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
    error: null,
  };
}

function extractField(output: string, field: string): string | null {
  for (const line of output.split(/\r?\n/)) {
    const match = new RegExp(`^${field}:\\s+(.+)$`).exec(line.trim());
    if (match) return match[1].trim();
  }
  return null;
}

function extractRunId(output: string): string | null {
  return extractField(output, "run_id");
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
    roleDescription: "(Optional) specific role; omit for default.",
    taskLabelDescription: "Optional short request label.",
  };
}

function parseRoleNames(output: string): string[] {
  const roles = new Set<string>();
  for (const line of output.split(/\r?\n/)) {
    const match = /^\s+[D✓✗]\s+(\S+)/.exec(line);
    if (match) roles.add(match[1]);
  }
  return [...roles];
}

function parseActiveSessionStatus(output: string): ActiveSessionStatus {
  const runIds = new Set<string>();
  const roleCounts = new Map<string, number>();

  for (const line of output.split(/\r?\n/)) {
    const match = /^-\s+(\S+)\s+\[[^\]]+\]\s+(\S+)\s+::/.exec(line.trim());
    if (!match) continue;
    const [, runId, role] = match;
    runIds.add(runId);
    roleCounts.set(role, (roleCounts.get(role) ?? 0) + 1);
  }

  return {
    activeCount: runIds.size,
    roleCounts: [...roleCounts.entries()].map(([role, count]) => ({ role, count })),
    runIds: [...runIds],
  };
}

function replaceCurrentToken(rawPrefix: string, currentToken: string, replacement: string): string {
  return rawPrefix.slice(0, rawPrefix.length - currentToken.length) + replacement;
}

function appendCompletion(rawPrefix: string, suffix: string): string {
  return `${rawPrefix}${suffix}`;
}

function buildCompletionItem(value: string, label: string, description?: string): { value: string; label: string; description?: string } {
  return description ? { value, label, description } : { value, label };
}

function filterStaticCompletions(
  rawPrefix: string,
  currentToken: string,
  suggestions: Array<{ token: string; description?: string }>,
): Array<{ value: string; label: string; description?: string }> | null {
  const items = suggestions
    .filter((suggestion) => suggestion.token.startsWith(currentToken))
    .map((suggestion) => buildCompletionItem(
      replaceCurrentToken(rawPrefix, currentToken, suggestion.token),
      suggestion.token.trim(),
      suggestion.description,
    ));
  return items.length > 0 ? items : null;
}

function doArgumentContext(tokens: string[]): { expecting: "role" | "timeout" | "taskLabel" | null; goalStarted: boolean } {
  let expecting: "role" | "timeout" | "taskLabel" | null = null;
  let goalStarted = false;

  for (const token of tokens) {
    if (expecting) {
      expecting = null;
      continue;
    }
    if (token === "--role") {
      expecting = "role";
      continue;
    }
    if (token === "--timeout") {
      expecting = "timeout";
      continue;
    }
    if (token === "--task-label") {
      expecting = "taskLabel";
      continue;
    }
    goalStarted = true;
  }

  return { expecting, goalStarted };
}

export default async function orchestraExtension(pi: ExtensionAPI) {
  let currentSessionId: string | null = null;
  const reportWatchers = new Map<string, Set<ChildProcessWithoutNullStreams>>();
  const awaitRunWatchers = new Map<string, Set<ChildProcessWithoutNullStreams>>();
  const sessionRuns = new Map<string, Set<string>>();
  const sessionCompletedRuns = new Map<string, Set<string>>();
  const sessionGenerations = new Map<string, number>();
  const sessionRefreshRequests = new Map<string, number>();
  let cachedRoleNames: { expiresAt: number; roles: string[] } | null = null;
  let cachedActiveStatus: { expiresAt: number; sessionId: string; status: ActiveSessionStatus } | null = null;

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

  function parseAwaitRunOutput(output: string): { status: string | null; role: string | null; blocker: string | null; activeRemaining: number | null } {
    let status: string | null = null;
    let role: string | null = null;
    let blocker: string | null = null;
    let activeRemaining: number | null = null;
    for (const line of output.split(/\r?\n/)) {
      const trimmed = line.trim();
      const statusMatch = /^status:\s+(.+)$/.exec(trimmed);
      if (statusMatch) status = statusMatch[1].trim();
      const roleMatch = /^role:\s+(.+)$/.exec(trimmed);
      if (roleMatch) role = roleMatch[1].trim();
      const blockerMatch = /^blocker:\s+(.+)$/.exec(trimmed);
      if (blockerMatch) blocker = blockerMatch[1].trim();
      const activeMatch = /^active_runs_remaining:\s+(\d+)$/.exec(trimmed);
      if (activeMatch) activeRemaining = Number(activeMatch[1]);
    }
    return { status, role, blocker, activeRemaining };
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

  function ensureSessionGeneration(sessionId: string): number {
    const generation = sessionGenerations.get(sessionId) ?? 1;
    sessionGenerations.set(sessionId, generation);
    return generation;
  }

  function bumpSessionGeneration(sessionId: string): number {
    const generation = ensureSessionGeneration(sessionId) + 1;
    sessionGenerations.set(sessionId, generation);
    return generation;
  }

  function isCurrentSessionGeneration(sessionId: string, generation: number): boolean {
    return sessionGenerations.get(sessionId) === generation;
  }

  function nextRefreshRequestId(sessionId: string): number {
    const requestId = (sessionRefreshRequests.get(sessionId) ?? 0) + 1;
    sessionRefreshRequests.set(sessionId, requestId);
    return requestId;
  }

  function isCurrentRefreshRequest(sessionId: string, generation: number, requestId: number): boolean {
    return isCurrentSessionGeneration(sessionId, generation) && sessionRefreshRequests.get(sessionId) === requestId;
  }

  function stopWatcherSet(
    watcherMap: Map<string, Set<ChildProcessWithoutNullStreams>>,
    sessionId: string,
  ): void {
    const watchers = watcherMap.get(sessionId);
    if (!watchers) return;
    for (const watcher of watchers) {
      try {
        watcher.kill("SIGTERM");
      } catch {
        // ignore shutdown races
      }
    }
    watcherMap.delete(sessionId);
  }

  function stopSessionWatchers(sessionId: string | null): void {
    if (!sessionId) return;
    stopWatcherSet(awaitRunWatchers, sessionId);
    stopWatcherSet(reportWatchers, sessionId);
    sessionRefreshRequests.delete(sessionId);
    sessionRuns.delete(sessionId);
    sessionCompletedRuns.delete(sessionId);
  }

  function watchRunProgress(
    sessionId: string,
    runId: string,
    notifier: ProgressNotifier,
    updateStatus?: (status: ActiveSessionStatus | null) => void,
  ): void {
    const sessionGeneration = ensureSessionGeneration(sessionId);
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

    const watchers = awaitRunWatchers.get(sessionId) ?? new Set<ChildProcessWithoutNullStreams>();
    watchers.add(child);
    awaitRunWatchers.set(sessionId, watchers);

    let stdout = "";
    let refreshedFailureStatus = false;
    const refreshFailureStatus = (): void => {
      if (refreshedFailureStatus) return;
      refreshedFailureStatus = true;
      void refreshOrchestraWorkerStatus(sessionId, updateStatus, { fresh: true, expectedGeneration: sessionGeneration });
    };

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });

    child.on("error", () => {
      refreshFailureStatus();
    });

    child.on("close", (code) => {
      watchers.delete(child);
      if (watchers.size === 0) awaitRunWatchers.delete(sessionId);

      if (code !== 0) {
        refreshFailureStatus();
        return;
      }
      if (!isCurrentSessionGeneration(sessionId, sessionGeneration)) return;
      const completed = sessionCompletedRuns.get(sessionId) ?? new Set<string>();
      completed.add(runId);
      sessionCompletedRuns.set(sessionId, completed);
      const { status, role, blocker, activeRemaining } = parseAwaitRunOutput(stdout);
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
      void runOrchestra(command).then(async (result) => {
        if (!isCurrentSessionGeneration(sessionId, sessionGeneration)) return;
        const roleText = role ? ` ${role}` : "";
        const blockerText = blocker ? ` :: ${blocker}` : "";
        notifier.notify(result.stdout || `orchestra:${roleText} ${runId} returned ${status ?? "done"} (${completed.size}/${total})${blockerText}`);
        const activeCount = await refreshOrchestraWorkerStatus(sessionId, updateStatus, { fresh: true, expectedGeneration: sessionGeneration });
        if (activeCount === 0 && isCurrentSessionGeneration(sessionId, sessionGeneration)) {
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
    updateStatus?: (status: ActiveSessionStatus | null) => void,
  ): Promise<DispatchResult> {
    const goal = params.goal?.trim() ?? "";
    if (!goal) return { code: 1, runId: null, output: "Usage: provide a worker goal." };

    const command = [
      "do",
      "--session-id",
      sessionId,
      "--goal",
      goal,
    ];
    const requestedRole = params.role?.trim();
    if (requestedRole) {
      command.push("--role", requestedRole);
    }
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
      watchRunProgress(sessionId, runId, notifier, updateStatus);
      watchSessionReport(sessionId, runId);
      const role = extractField(result.stdout, "role") || requestedRole || "worker";
      const ack = await runOrchestra(["_dispatch-ack", "--run-id", runId, "--role", role]);
      await refreshOrchestraWorkerStatus(sessionId, updateStatus, { fresh: true });
      return { code: 0, runId, output: ack.stdout || `orchestra dispatched: ${role} ${runId}` };
    }
    return { code: result.code, runId: null, output: result.stdout || result.stderr };
  }

  function watchSessionReport(sessionId: string, runId: string): void {
    if (reportWatchers.has(sessionId)) return;

    const sessionGeneration = ensureSessionGeneration(sessionId);
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
      if (!isCurrentSessionGeneration(sessionId, sessionGeneration)) return;

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
    bumpSessionGeneration(currentSessionId);
    await refreshOrchestraWorkerStatus(currentSessionId, (status) => setOrchestraWorkerStatus(ctx, status), { fresh: true });
  });

  pi.on("session_shutdown", async (_event, ctx) => {
    if (currentSessionId) {
      bumpSessionGeneration(currentSessionId);
    }
    setOrchestraWorkerStatus(ctx, null);
    stopSessionWatchers(currentSessionId);
    currentSessionId = null;
  });

  const registerDispatchTool = canDispatchOrchestraWorker();

  async function getRoleNames(): Promise<string[]> {
    const now = Date.now();
    if (cachedRoleNames && cachedRoleNames.expiresAt > now) {
      return cachedRoleNames.roles;
    }
    const result = await runOrchestra(["roles", "--all"]);
    const roles = result.code === 0 ? parseRoleNames(result.stdout) : [];
    cachedRoleNames = { expiresAt: now + 5_000, roles };
    return roles;
  }

  async function getActiveSessionStatus(sessionId: string): Promise<ActiveSessionStatus> {
    const now = Date.now();
    if (
      cachedActiveStatus
      && cachedActiveStatus.sessionId === sessionId
      && cachedActiveStatus.expiresAt > now
    ) {
      return cachedActiveStatus.status;
    }
    const result = await runOrchestra(["status", "--session-id", sessionId]);
    const status = result.code === 0 ? parseActiveSessionStatus(result.stdout) : { activeCount: 0, roleCounts: [], runIds: [] };
    cachedActiveStatus = { expiresAt: now + 2_000, sessionId, status };
    return status;
  }

  async function getActiveRunIds(sessionId: string): Promise<string[]> {
    return (await getActiveSessionStatus(sessionId)).runIds;
  }

  async function refreshOrchestraWorkerStatus(
    sessionId: string,
    updateStatus?: (status: ActiveSessionStatus | null) => void,
    options?: { fresh?: boolean; expectedGeneration?: number },
  ): Promise<number | null> {
    const sessionGeneration = options?.expectedGeneration ?? ensureSessionGeneration(sessionId);
    if (options?.expectedGeneration !== undefined && !isCurrentSessionGeneration(sessionId, sessionGeneration)) {
      return null;
    }
    const requestId = nextRefreshRequestId(sessionId);
    try {
      if (options?.fresh) cachedActiveStatus = null;
      const activeStatus = await getActiveSessionStatus(sessionId);
      if (!isCurrentRefreshRequest(sessionId, sessionGeneration, requestId)) return null;
      updateStatus?.(activeStatus);
      return activeStatus.activeCount;
    } catch {
      if (!isCurrentRefreshRequest(sessionId, sessionGeneration, requestId)) return null;
      updateStatus?.(null);
      return null;
    }
  }

  async function injectOrchestratorSkill(_sessionId: string): Promise<{ code: number; output: string }> {
    const result = await runOrchestra(["_orchestrator-skill"]);
    const message = result.stdout.trim();
    if (result.code !== 0 || !message) {
      return {
        code: result.code || 1,
        output: result.stderr || message || "Failed to load Orchestra main-session skill.",
      };
    }
    pi.sendUserMessage(message, { deliverAs: "followUp", triggerTurn: true });
    return { code: 0, output: "Orchestra orchestrator skill refreshed for this session." };
  }

  async function getOrchArgumentCompletions(argumentPrefix: string): Promise<Array<{ value: string; label: string; description?: string }> | null> {
    const parsed = tokenizeArgs(argumentPrefix);
    if (parsed.error) return null;

    const subcommands = [
      { token: "help", description: "Show Orchestra help" },
      { token: "on", description: "Load the orchestra orchestrator skill" },
      { token: "doctor", description: "Check Orchestra setup" },
      { token: "do ", description: "Dispatch a subagent" },
      { token: "roles ", description: "Show or update configured roles" },
      { token: "status", description: "Show active workers for this session" },
      { token: "stop ", description: "Stop an active worker." },
      { token: "history ", description: "Show recent results for this session" },
    ];

    if (parsed.tokens.length === 0) {
      return subcommands.map((item) => buildCompletionItem(item.token, item.token.trim(), item.description));
    }

    if (parsed.tokens.length === 1 && !parsed.trailingSpace) {
      return filterStaticCompletions(argumentPrefix, parsed.tokens[0], subcommands);
    }

    const subcommand = parsed.tokens[0];

    if (subcommand === "history") {
      const historyLimits = ["10", "20", "50"];
      if (parsed.tokens.length === 1 && parsed.trailingSpace) {
        return historyLimits.map((limit) => buildCompletionItem(appendCompletion(argumentPrefix, limit), limit));
      }
      if (parsed.tokens.length === 2 && !parsed.trailingSpace) {
        return historyLimits
          .filter((limit) => limit.startsWith(parsed.tokens[1]))
          .map((limit) => buildCompletionItem(replaceCurrentToken(argumentPrefix, parsed.tokens[1], limit), limit));
      }
      return null;
    }

    if (subcommand === "stop") {
      if (!currentSessionId) return null;
      const runIds = await getActiveRunIds(currentSessionId);
      if (parsed.tokens.length === 1 && parsed.trailingSpace) {
        return runIds.map((runId) => buildCompletionItem(appendCompletion(argumentPrefix, runId), runId));
      }
      if (parsed.tokens.length === 2 && !parsed.trailingSpace) {
        return runIds
          .filter((runId) => runId.startsWith(parsed.tokens[1]))
          .map((runId) => buildCompletionItem(replaceCurrentToken(argumentPrefix, parsed.tokens[1], runId), runId));
      }
      return null;
    }

    if (subcommand === "roles") {
      const roleNames = await getRoleNames();
      const roleSettings = [
        { token: "enabled ", description: "Enable or disable a role" },
        { token: "model ", description: "Set a role model" },
      ];
      const boolValues = ["true", "false"];

      if (parsed.tokens.length === 1 && parsed.trailingSpace) {
        return roleNames.map((roleName) => buildCompletionItem(appendCompletion(argumentPrefix, roleName), roleName));
      }
      if (parsed.tokens.length === 2 && !parsed.trailingSpace) {
        return roleNames
          .filter((roleName) => roleName.startsWith(parsed.tokens[1]))
          .map((roleName) => buildCompletionItem(replaceCurrentToken(argumentPrefix, parsed.tokens[1], roleName), roleName));
      }
      if (parsed.tokens.length === 2 && parsed.trailingSpace) {
        return roleSettings.map((setting) => buildCompletionItem(appendCompletion(argumentPrefix, setting.token), setting.token.trim(), setting.description));
      }
      if (parsed.tokens.length === 3 && !parsed.trailingSpace) {
        return filterStaticCompletions(argumentPrefix, parsed.tokens[2], roleSettings);
      }
      if (parsed.tokens.length === 3 && parsed.trailingSpace && parsed.tokens[2] === "enabled") {
        return boolValues.map((value) => buildCompletionItem(appendCompletion(argumentPrefix, value), value));
      }
      if (parsed.tokens.length === 4 && !parsed.trailingSpace && parsed.tokens[2] === "enabled") {
        return boolValues
          .filter((value) => value.startsWith(parsed.tokens[3]))
          .map((value) => buildCompletionItem(replaceCurrentToken(argumentPrefix, parsed.tokens[3], value), value));
      }
      return null;
    }

    if (subcommand === "do") {
      const roleNames = await getRoleNames();
      const doFlags = [
        { token: "--role ", description: "Select a configured role" },
        { token: "--timeout ", description: "Set timeout in seconds" },
        { token: "--task-label ", description: "Set a short task label" },
      ];
      const timeoutValues = ["60", "120", "300", "600"];
      const doTokens = parsed.tokens.slice(1);
      const beforeCurrentTokens = parsed.trailingSpace ? doTokens : doTokens.slice(0, -1);
      const currentToken = parsed.trailingSpace ? "" : (doTokens.at(-1) ?? "");
      const context = doArgumentContext(beforeCurrentTokens);

      if (context.expecting === "role") {
        if (parsed.trailingSpace) {
          return roleNames.map((roleName) => buildCompletionItem(appendCompletion(argumentPrefix, roleName), roleName));
        }
        return roleNames
          .filter((roleName) => roleName.startsWith(currentToken))
          .map((roleName) => buildCompletionItem(replaceCurrentToken(argumentPrefix, currentToken, roleName), roleName));
      }

      if (context.expecting === "timeout") {
        if (parsed.trailingSpace) {
          return timeoutValues.map((value) => buildCompletionItem(appendCompletion(argumentPrefix, value), value));
        }
        return timeoutValues
          .filter((value) => value.startsWith(currentToken))
          .map((value) => buildCompletionItem(replaceCurrentToken(argumentPrefix, currentToken, value), value));
      }

      if (context.expecting === "taskLabel") {
        return null;
      }

      if (context.goalStarted) {
        return null;
      }

      if (parsed.trailingSpace) {
        return doFlags.map((flag) => buildCompletionItem(appendCompletion(argumentPrefix, flag.token), flag.token.trim(), flag.description));
      }

      if (currentToken.startsWith("--")) {
        return filterStaticCompletions(argumentPrefix, currentToken, doFlags);
      }
    }

    return null;
  }

  function registerOrchDispatchTool(toolInfo: ToolInfoPayload): void {
    pi.registerTool({
      name: "orch_dispatch",
      label: "Orchestra Dispatch",
      description: toolInfo.description,
      promptSnippet: toolInfo.promptSnippet,
      promptGuidelines: toolInfo.promptGuidelines,
      parameters: Type.Object({
        goal: Type.String({ description: toolInfo.goalDescription }),
        role: Type.Optional(Type.String({ description: toolInfo.roleDescription })),
        taskLabel: Type.Optional(Type.String({ description: toolInfo.taskLabelDescription })),
      }),
      async execute(_toolCallId, params: DispatchParams, _signal, _onUpdate, ctx) {
        if (params.timeout !== undefined) {
          return {
            content: [{ type: "text", text: TOOL_TIMEOUT_ERROR }],
            isError: true,
          };
        }
        const runtimeSessionId = normalizePiSessionId(ctx.sessionManager.getSessionId());
        const result = await dispatchWorker(runtimeSessionId, params, progressNotifier(ctx), (status) => setOrchestraWorkerStatus(ctx, status));
        return {
          content: [{ type: "text", text: result.output }],
          isError: result.code !== 0,
        };
      },
    });
  }

  async function refreshOrchDispatchToolRegistration(): Promise<void> {
    if (!registerDispatchTool) return;
    registerOrchDispatchTool(await loadToolInfo());
  }

  await refreshOrchDispatchToolRegistration();

  pi.registerCommand("orch", {
    description: "Orchestra host adapter: /orch help|on|do|roles|status|stop|doctor|history",
    getArgumentCompletions: getOrchArgumentCompletions,
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

      if (subcommand === "on") {
        const result = await injectOrchestratorSkill(runtimeSessionId);
        emitOutput(ctx, result.output, result.code === 0 ? "info" : "error");
        return;
      }

      if (subcommand === "doctor") {
        const result = await runOrchestra(["doctor"]);
        emitEntryOutput(ctx, result.stdout || result.stderr);
        return;
      }

      if (subcommand === "roles") {
        const result = await runOrchestra(rest.length > 0 ? ["roles", ...rest] : ["roles", "--all"]);
        cachedRoleNames = null;
        await refreshOrchDispatchToolRegistration();
        emitEntryOutput(ctx, result.stdout || result.stderr);
        return;
      }

      if (subcommand === "status") {
        const result = await runOrchestra(["status", "--session-id", runtimeSessionId]);
        emitEntryOutput(ctx, result.stdout || result.stderr);
        if (result.code === 0) {
          const status = parseActiveSessionStatus(result.stdout);
          cachedActiveStatus = { expiresAt: Date.now() + 2_000, sessionId: runtimeSessionId, status };
          setOrchestraWorkerStatus(ctx, status);
        }
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
        await refreshOrchestraWorkerStatus(runtimeSessionId, (status) => setOrchestraWorkerStatus(ctx, status), { fresh: true });
        return;
      }

      if (subcommand === "do") {
        const parsed = parseDoArgs(rest.join(" "));
        if (parsed.error) {
          emitOutput(ctx, parsed.error, "warning");
          return;
        }
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
          (status) => setOrchestraWorkerStatus(ctx, status),
        );
        emitOutput(ctx, result.output, result.code === 0 ? "info" : "error");
        return;
      }

      emitOutput(ctx, `Unknown /orch subcommand: ${subcommand}\n\n${await hostHelp()}`, "warning");
    },
  });
}
