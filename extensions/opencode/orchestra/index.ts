import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { tool, type Plugin } from "@opencode-ai/plugin";

const FORBIDDEN_IDENTITY_FIELDS = ["session_id", "sessionId", "orchestrator_session_id"] as const;
const ORCHESTRA_DISPATCH_BUDGET_ENV = "ORCHESTRA_DISPATCH_BUDGET";
const TOOL_TIMEOUT_ERROR = "timeout is not accepted by orch_dispatch; configured default_timeout applies.";
const WATCHER_TIMEOUT_MARGIN_SECONDS = 30;
const execFileAsync = promisify(execFile);

type OrchDispatchArgs = {
  goal: string;
  role?: string;
  taskLabel?: string;
};

type OrchStatusAction = "on" | "status" | "history" | "help" | "doctor" | "roles" | "stop";

type OrchStatusArgs = {
  action: OrchStatusAction;
  limit?: number;
  runId?: string;
  role?: string;
  setting?: string;
  value?: string;
};

const SUPPORTED_ROLE_SETTINGS = new Set(["harness", "enabled", "model", "profile", "agent"]);

type ToolInfoPayload = {
  description: string;
  promptSnippet: string;
  promptGuidelines: string[];
  goalDescription: string;
  roleDescription: string;
  taskLabelDescription: string;
  statusDescription: string;
  statusActionDescription: string;
  statusLimitDescription: string;
  statusRunIdDescription: string;
  statusRoleDescription: string;
  statusSettingDescription: string;
  statusValueDescription: string;
};

type OpenCodeToastVariant = "info" | "error";

type OpenCodeToastClient = {
  tui?: {
    showToast?: (payload: {
      body: {
        message: string;
        variant: OpenCodeToastVariant;
      };
    }) => Promise<unknown> | unknown;
  };
};

type OpenCodeSessionPromptPayload = {
  path: {
    id: string;
  };
  body: {
    parts: Array<{
      type: "text";
      text: string;
    }>;
  };
};

type OpenCodeSessionPromptClient = {
  session?: {
    promptAsync?: (payload: OpenCodeSessionPromptPayload) => Promise<unknown> | unknown;
    prompt?: (payload: OpenCodeSessionPromptPayload) => Promise<unknown> | unknown;
  };
};

type OpenCodeDeliveryClient = OpenCodeToastClient & OpenCodeSessionPromptClient;

async function showToast(
  client: OpenCodeToastClient | undefined,
  message: string,
  variant: OpenCodeToastVariant,
): Promise<void> {
  if (!client?.tui?.showToast) {
    return;
  }

  try {
    await client.tui.showToast({ body: { message, variant } });
  } catch {
    return;
  }
}

async function notifyDispatchToast(
  client: OpenCodeToastClient | undefined,
  ownerId: string,
): Promise<void> {
  await showToast(client, `Orchestra dispatch queued for ${ownerId}.`, "info");
}

async function notifyFailureToast(
  client: OpenCodeToastClient | undefined,
  ownerId: string,
  error: unknown,
): Promise<void> {
  const message = error instanceof Error ? error.message : String(error);
  await showToast(client, `Orchestra dispatch failed for ${ownerId}: ${message}`, "error");
}

async function notifyProgressToast(
  client: OpenCodeToastClient | undefined,
  message: string,
): Promise<void> {
  await showToast(client, message, "info");
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

function orchestraDispatchBudget(): number {
  const raw = process.env[ORCHESTRA_DISPATCH_BUDGET_ENV]?.trim();
  if (!raw) return 0;
  const parsed = Number(raw);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : 1;
}

function canDispatchOrchestraWorker(): boolean {
  return orchestraDispatchBudget() !== 1;
}

async function loadToolInfo(): Promise<ToolInfoPayload> {
  const result = await runOrchestra(["orchestra", "_tool-info"]);
  if (result.returncode === 0 && result.stdout.trim()) {
    return JSON.parse(result.stdout) as ToolInfoPayload;
  }

  return {
    description: "Delegate or dispatch a focused task to an Orchestra worker/subagent.",
    promptSnippet: "Dispatch focused work to Orchestra workers/subagents.",
    promptGuidelines: ["Use orch_dispatch for narrow delegated worker tasks."],
    goalDescription: "Focused worker request/task to delegate.",
    roleDescription: "(Optional) specific role; omit for default.",
    taskLabelDescription: "Optional short request label.",
    statusDescription: "Inspect or control Orchestra host-session state from OpenCode.",
    statusActionDescription: "OpenCode /orch action.",
    statusLimitDescription: "Positive history limit; defaults to 10.",
    statusRunIdDescription: "Required run id for stop.",
    statusRoleDescription: "Role to update when using action roles.",
    statusSettingDescription: "Role setting to update when using action roles.",
    statusValueDescription: "Role setting value to update when using action roles.",
  };
}

function normalizeOpenCodeOwnerId(sessionID: string): string {
  const normalizedSessionID = sessionID.trim();
  if (!normalizedSessionID) {
    throw new Error("context.sessionID is required for orch_dispatch.");
  }
  return `opencode:${normalizedSessionID}`;
}

function rejectOrchDispatchOverrides(args: Record<string, unknown>): void {
  for (const field of FORBIDDEN_IDENTITY_FIELDS) {
    if (Object.prototype.hasOwnProperty.call(args, field)) {
      throw new Error(`${field} is not accepted by orch_dispatch; context.sessionID is the only identity source.`);
    }
  }

  if (Object.prototype.hasOwnProperty.call(args, "timeout")) {
    throw new Error(TOOL_TIMEOUT_ERROR);
  }
}

function buildOrchestraDoCommand(ownerId: string, args: OrchDispatchArgs): string[] {
  const command = ["orchestra", "do", "--session-id", ownerId, "--goal", args.goal.trim()];
  const role = args.role?.trim();
  if (role) {
    command.push("--role", role);
  }
  const taskLabel = args.taskLabel?.trim();
  if (taskLabel) {
    command.push("--task-label", taskLabel);
  }
  return command;
}

function normalizeOrchStatusText(value: string | undefined): string | null {
  const normalized = value?.trim();
  return normalized ? normalized : null;
}

function normalizeOrchStatusLimit(limit: number | undefined): string {
  if (limit === undefined) {
    return "10";
  }
  if (!Number.isInteger(limit) || limit <= 0) {
    throw new Error("limit must be a positive integer.");
  }
  return String(limit);
}

function normalizeOrchStatusRoleFields(args: OrchStatusArgs): {
  role: string | null;
  setting: string | null;
  value: string | null;
} {
  return {
    role: normalizeOrchStatusText(args.role),
    setting: normalizeOrchStatusText(args.setting),
    value: normalizeOrchStatusText(args.value),
  };
}

function validateOrchStatusArgs(action: OrchStatusAction, args: OrchStatusArgs): void {
  const { role, setting, value } = normalizeOrchStatusRoleFields(args);
  const hasRoleChangeArgs = Boolean(role || setting || value);

  if (action !== "roles") {
    return;
  }

  if (hasRoleChangeArgs) {
    throw new Error("orch_status roles is read-only; use the host /orch roles command to change role settings.");
  }
}

function buildOrchStatusCommand(ownerId: string | null, args: OrchStatusArgs): string[] {
  validateOrchStatusArgs(args.action, args);

  if (args.action === "on") {
    return ["orchestra", "_orchestrator-skill"];
  }

  if (args.action === "status") {
    if (!ownerId) {
      throw new Error("context.sessionID is required for orch_status status/history/stop.");
    }
    return ["orchestra", "status", "--session-id", ownerId];
  }

  if (args.action === "history") {
    if (!ownerId) {
      throw new Error("context.sessionID is required for orch_status status/history/stop.");
    }
    return ["orchestra", "history", "--session-id", ownerId, "--limit", normalizeOrchStatusLimit(args.limit)];
  }

  if (args.action === "help") {
    return ["orchestra", "help-opencode"];
  }

  if (args.action === "doctor") {
    return ["orchestra", "doctor"];
  }

  if (args.action === "stop") {
    if (!ownerId) {
      throw new Error("context.sessionID is required for orch_status status/history/stop.");
    }
    const runId = normalizeOrchStatusText(args.runId);
    if (!runId) {
      throw new Error("runId is required for orch_status stop.");
    }
    return ["orchestra", "stop", "--session-id", ownerId, "--run-id", runId];
  }

  if (args.action === "roles") {
    return ["orchestra", "roles", "--all"];
  }

  return ["orchestra", "roles", "--all"];
}

type SessionReportEnvelope = {
  runIds: string[];
  report: string;
};

type SessionReportRunnerResult = {
  returncode: number;
  stdout: string;
  stderr: string;
};

type SessionReportRunner = (
  command: string[],
) => Promise<SessionReportRunnerResult> | SessionReportRunnerResult;

const deliveredSessionReportRunIds = new Set<string>();
const pendingSessionReports = new Map<string, SessionReportEnvelope>();
const inflightSessionReportDeliveries = new Set<string>();
const sessionRuns = new Map<string, Set<string>>();
const sessionCompletedRuns = new Map<string, Set<string>>();

async function runOrchestra(command: string[]): Promise<SessionReportRunnerResult> {
  const [file, ...args] = command;

  try {
    const { stdout, stderr } = await execFileAsync(file, [...orchestraBaseArgs(), ...args], { encoding: "utf8" });
    return { returncode: 0, stdout: stdout.trim(), stderr: stderr.trim() };
  } catch (error) {
    const err = error as { code?: number; stdout?: string; stderr?: string; message: string };
    return {
      returncode: err.code ?? 1,
      stdout: (err.stdout ?? "").trim(),
      stderr: (err.stderr ?? err.message).trim(),
    };
  }
}

function buildAwaitSessionReportCommand(
  ownerId: string,
  runId: string,
  timeoutSeconds: number,
): string[] {
  return [
    "orchestra",
    "_await-session-report",
    "--session-id",
    ownerId,
    "--run-id",
    runId,
    "--timeout",
    String(timeoutSeconds),
    "--json",
  ];
}

function buildMarkSessionReportDeliveredCommand(ownerId: string, runIds: string[]): string[] {
  const command = ["orchestra", "_mark-session-report-delivered", "--session-id", ownerId];
  for (const runId of runIds) {
    command.push("--run-id", runId);
  }
  return command;
}

function buildReleaseSessionReportCommand(ownerId: string, runIds: string[]): string[] {
  const command = ["orchestra", "_release-session-report", "--session-id", ownerId];
  for (const runId of runIds) {
    command.push("--run-id", runId);
  }
  return command;
}

function parseSessionReportEnvelope(stdout: string): SessionReportEnvelope | null {
  try {
    const payload = JSON.parse(stdout) as { runIds?: unknown; report?: unknown };
    if (!Array.isArray(payload.runIds) || typeof payload.report !== "string") {
      return null;
    }

    const runIds = payload.runIds.filter(
      (runId): runId is string => typeof runId === "string" && runId.trim().length > 0,
    );
    const report = payload.report.trim();
    if (!runIds.length || !report) {
      return null;
    }

    return { runIds, report };
  } catch {
    return null;
  }
}

function extractField(output: string, field: string): string | null {
  for (const line of output.split(/\r?\n/)) {
    const match = new RegExp(`^${field}:\\s+(.+)$`).exec(line.trim());
    if (match) {
      return match[1].trim();
    }
  }
  return null;
}

function extractDispatchTimeoutSeconds(output: string): number {
  const timeoutText = extractField(output, "timeout_seconds");
  if (!timeoutText) {
    throw new Error("orchestra do output did not include timeout_seconds.");
  }
  if (!/^\d+$/.test(timeoutText)) {
    throw new Error("orchestra do timeout_seconds must be a positive integer.");
  }

  const timeoutSeconds = Number.parseInt(timeoutText, 10);
  if (timeoutSeconds <= 0) {
    throw new Error("orchestra do timeout_seconds must be a positive integer.");
  }
  return timeoutSeconds;
}

function extractRunId(output: string): string | null {
  try {
    const payload = JSON.parse(output) as { run_id?: unknown; runId?: unknown };
    if (typeof payload.run_id === "string" && payload.run_id.trim()) {
      return payload.run_id.trim();
    }
    if (typeof payload.runId === "string" && payload.runId.trim()) {
      return payload.runId.trim();
    }
  } catch {
    // fall through to line-based parsing
  }

  const dispatchedMatch = /^orchestra dispatched:\s+(\S+)$/m.exec(output);
  if (dispatchedMatch) {
    return dispatchedMatch[1];
  }

  return extractField(output, "run_id") ?? extractField(output, "runId");
}

function hasDeliveredSessionReport(runIds: string[]): boolean {
  return runIds.length > 0 && runIds.every((runId) => deliveredSessionReportRunIds.has(runId));
}

function getSessionReportDeliveryKey(ownerId: string, runIds: string[]): string {
  return JSON.stringify([ownerId, runIds.slice().sort()]);
}

function claimSessionReportDelivery(ownerId: string, runIds: string[]): boolean {
  if (hasDeliveredSessionReport(runIds)) {
    return false;
  }

  const deliveryKey = getSessionReportDeliveryKey(ownerId, runIds);
  if (inflightSessionReportDeliveries.has(deliveryKey)) {
    return false;
  }

  inflightSessionReportDeliveries.add(deliveryKey);
  return true;
}

function releaseSessionReportDeliveryClaim(ownerId: string, runIds: string[]): void {
  inflightSessionReportDeliveries.delete(getSessionReportDeliveryKey(ownerId, runIds));
}

function rememberSessionReport(ownerId: string, envelope: SessionReportEnvelope): SessionReportEnvelope {
  pendingSessionReports.set(ownerId, envelope);
  return envelope;
}

function getPendingSessionReport(ownerId: string): SessionReportEnvelope | null {
  return pendingSessionReports.get(ownerId) ?? null;
}

function markSessionReportDelivered(ownerId: string, runIds: string[]): void {
  pendingSessionReports.delete(ownerId);
  for (const runId of runIds) {
    deliveredSessionReportRunIds.add(runId);
  }
}

function releaseSessionReport(ownerId: string): void {
  pendingSessionReports.delete(ownerId);
}

function getSessionPrompt(
  client: OpenCodeDeliveryClient | undefined,
): ((payload: OpenCodeSessionPromptPayload) => Promise<unknown> | unknown) | null {
  const session = client?.session;
  if (!session) {
    return null;
  }
  if (session.prompt) {
    return session.prompt.bind(session);
  }
  if (session.promptAsync) {
    return session.promptAsync.bind(session);
  }
  return null;
}

async function promptSessionReport(
  client: OpenCodeDeliveryClient | undefined,
  rawSessionID: string,
  ownerId: string,
  envelope: SessionReportEnvelope,
): Promise<boolean> {
  const sessionPrompt = getSessionPrompt(client);
  if (!sessionPrompt) {
    releaseSessionReport(ownerId);
    return false;
  }

  if (!claimSessionReportDelivery(ownerId, envelope.runIds)) {
    return false;
  }

  let preserveClaim = false;
  try {
    await sessionPrompt({
      path: { id: rawSessionID },
      body: { parts: [{ type: "text", text: envelope.report }] },
    });
    const markResult = await runOrchestra(buildMarkSessionReportDeliveredCommand(ownerId, envelope.runIds));
    if (markResult.returncode !== 0) {
      throw new Error(markResult.stderr || "failed to mark Orchestra report delivered.");
    }
    markSessionReportDelivered(ownerId, envelope.runIds);
    return true;
  } catch (error) {
    console.error("Orchestra report delivery failed:", error);
    await notifyFailureToast(client, ownerId, error);
    const releaseResult = await runOrchestra(buildReleaseSessionReportCommand(ownerId, envelope.runIds));
    if (releaseResult.returncode !== 0) {
      console.error("Orchestra report release after failure failed:", releaseResult.stderr);
      await notifyFailureToast(
        client,
        ownerId,
        releaseResult.stderr || "failed to release Orchestra report delivery.",
      );
      preserveClaim = true;
      return false;
    }
    releaseSessionReport(ownerId);
    return false;
  } finally {
    if (!preserveClaim) {
      releaseSessionReportDeliveryClaim(ownerId, envelope.runIds);
    }
  }
}

async function deliverSessionReport(
  client: OpenCodeDeliveryClient | undefined,
  rawSessionID: string,
  ownerId: string,
  runId: string,
  timeoutSeconds: number,
  runner: SessionReportRunner,
): Promise<SessionReportEnvelope | null> {
  const envelope = await watchSessionReport(ownerId, runId, timeoutSeconds, runner);
  if (!envelope) {
    return null;
  }

  if (!(await promptSessionReport(client, rawSessionID, ownerId, envelope))) {
    return null;
  }

  return envelope;
}

function queueSessionReportDelivery(
  client: OpenCodeDeliveryClient | undefined,
  rawSessionID: string,
  ownerId: string,
  runId: string,
  timeoutSeconds: number,
  runner: SessionReportRunner,
): void {
  void deliverSessionReport(client, rawSessionID, ownerId, runId, timeoutSeconds, runner).catch(
    async (error) => {
      console.error("Orchestra report delivery failed:", error);
      await notifyFailureToast(client, ownerId, error);
    },
  );
}

async function retrieveSessionReport(
  ownerId: string,
  runId: string,
  timeoutSeconds: number,
  runner: SessionReportRunner,
): Promise<SessionReportEnvelope | null> {
  const result = await runner(buildAwaitSessionReportCommand(ownerId, runId, timeoutSeconds));
  if (result.returncode !== 0) {
    return null;
  }

  const envelope = parseSessionReportEnvelope(result.stdout);
  if (!envelope || hasDeliveredSessionReport(envelope.runIds)) {
    return null;
  }

  return rememberSessionReport(ownerId, envelope);
}

async function watchSessionReport(
  ownerId: string,
  runId: string,
  timeoutSeconds: number,
  runner: SessionReportRunner,
): Promise<SessionReportEnvelope | null> {
  const watcherTimeoutSeconds = timeoutSeconds + WATCHER_TIMEOUT_MARGIN_SECONDS;
  const envelope = await retrieveSessionReport(ownerId, runId, watcherTimeoutSeconds, runner);
  return envelope ?? getPendingSessionReport(ownerId);
}

function trackSessionRun(ownerId: string, runId: string): void {
  const runs = sessionRuns.get(ownerId) ?? new Set<string>();
  runs.add(runId);
  sessionRuns.set(ownerId, runs);
}

function markSessionRunCompleted(ownerId: string, runId: string): number {
  const completed = sessionCompletedRuns.get(ownerId) ?? new Set<string>();
  completed.add(runId);
  sessionCompletedRuns.set(ownerId, completed);
  return completed.size;
}

function releaseSessionProgressRuns(ownerId: string): void {
  const runs = sessionRuns.get(ownerId);
  const completed = sessionCompletedRuns.get(ownerId);
  if (!runs || !completed || runs.size !== completed.size) {
    return;
  }
  sessionRuns.delete(ownerId);
  sessionCompletedRuns.delete(ownerId);
}

function releaseSessionProgressRun(ownerId: string, runId: string): void {
  const runs = sessionRuns.get(ownerId);
  if (runs) {
    runs.delete(runId);
    if (runs.size === 0) {
      sessionRuns.delete(ownerId);
    }
  }

  const completed = sessionCompletedRuns.get(ownerId);
  if (completed) {
    completed.delete(runId);
    if (completed.size === 0) {
      sessionCompletedRuns.delete(ownerId);
    }
  }
}

function parseAwaitRunOutput(output: string): {
  status: string | null;
  role: string | null;
  blocker: string | null;
  activeRemaining: number | null;
} {
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

function buildAwaitRunCommand(ownerId: string, runId: string, timeoutSeconds: number): string[] {
  return [
    "orchestra",
    "_await-run",
    "--session-id",
    ownerId,
    "--run-id",
    runId,
    "--timeout",
    String(timeoutSeconds),
  ];
}

function buildProgressMessageCommand(
  completedCount: number,
  totalCount: number,
  runId: string,
  status: string,
  role: string | null,
): string[] {
  const command = [
    "orchestra",
    "_progress-message",
    "--completed",
    String(completedCount),
    "--total",
    String(totalCount),
    "--run-id",
    runId,
    "--status",
    status,
  ];
  if (role) {
    command.push("--role", role);
  }
  return command;
}

async function deliverRunProgressNotification(
  client: OpenCodeToastClient | undefined,
  ownerId: string,
  runId: string,
  timeoutSeconds: number,
  runner: SessionReportRunner,
): Promise<void> {
  const watcherTimeoutSeconds = timeoutSeconds + WATCHER_TIMEOUT_MARGIN_SECONDS;
  let markedCompleted = false;

  try {
    const awaitRunResult = await runner(buildAwaitRunCommand(ownerId, runId, watcherTimeoutSeconds));
    if (awaitRunResult.returncode !== 0) {
      throw new Error(awaitRunResult.stderr || "orchestra await-run failed.");
    }

    const { status, role, blocker, activeRemaining } = parseAwaitRunOutput(awaitRunResult.stdout);
    const completedCount = markSessionRunCompleted(ownerId, runId);
    markedCompleted = true;
    const totalCount = sessionRuns.get(ownerId)?.size ?? completedCount + (activeRemaining ?? 0);
    const progressResult = await runner(
      buildProgressMessageCommand(completedCount, totalCount, runId, status ?? "done", role),
    );
    if (progressResult.returncode !== 0) {
      throw new Error(progressResult.stderr || "failed to format Orchestra progress message.");
    }

    const fallbackMessage = `orchestra:${role ? ` ${role}` : ""} ${runId} returned ${status ?? "done"} (${completedCount}/${totalCount})${blocker ? ` :: ${blocker}` : ""}`;
    await notifyProgressToast(client, progressResult.stdout.trim() || fallbackMessage);
  } finally {
    if (!markedCompleted) {
      releaseSessionProgressRun(ownerId, runId);
    }
    releaseSessionProgressRuns(ownerId);
  }
}

function queueRunProgressNotification(
  client: OpenCodeToastClient | undefined,
  ownerId: string,
  runId: string,
  timeoutSeconds: number,
  runner: SessionReportRunner,
): void {
  void deliverRunProgressNotification(client, ownerId, runId, timeoutSeconds, runner).catch(
    async (error) => {
      console.error("Orchestra progress delivery failed:", error);
    },
  );
}

export const OrchestraPlugin: Plugin = async ({ client }) => {
  const toolInfo = await loadToolInfo();
  const orchStatusTool = tool({
    description: toolInfo.statusDescription,
    args: {
      action: tool.schema.enum(["on", "status", "history", "help", "doctor", "roles", "stop"]).describe(toolInfo.statusActionDescription),
      limit: tool.schema
        .number()
        .int()
        .positive()
        .optional()
        .describe(toolInfo.statusLimitDescription),
      runId: tool.schema.string().optional().describe(toolInfo.statusRunIdDescription),
      role: tool.schema.string().optional().describe(toolInfo.statusRoleDescription),
      setting: tool.schema.string().optional().describe(toolInfo.statusSettingDescription),
      value: tool.schema.string().optional().describe(toolInfo.statusValueDescription),
    },
    async execute(args, context) {
      const statusArgs = args as OrchStatusArgs;
      const rawSessionID = context.sessionID?.trim();
      let ownerId: string | null = null;

      if (statusArgs.action === "status" || statusArgs.action === "history" || statusArgs.action === "stop") {
        if (!rawSessionID) {
          throw new Error("context.sessionID is required for orch_status status/history/stop.");
        }
        ownerId = normalizeOpenCodeOwnerId(rawSessionID);
      }

      const command = buildOrchStatusCommand(ownerId, statusArgs);
      const result = await runOrchestra(command);
      const output = result.stdout.trim() || result.stderr.trim();
      if (result.returncode !== 0) {
        throw new Error(output || `orch_status ${statusArgs.action} failed.`);
      }
      if (!output) {
        throw new Error(`orch_status ${statusArgs.action} returned no output.`);
      }
      return output;
    },
  });

  if (!canDispatchOrchestraWorker()) {
    return { tool: { orch_status: orchStatusTool } };
  }

  return {
    tool: {
      orch_status: orchStatusTool,
      orch_dispatch: tool({
        description: toolInfo.description,
        args: {
          goal: tool.schema.string().describe(toolInfo.goalDescription),
          role: tool.schema.string().optional().describe(toolInfo.roleDescription),
          taskLabel: tool.schema.string().optional().describe(toolInfo.taskLabelDescription),
        },
        async execute(args, context) {
          let ownerId = "opencode:unknown";

          try {
            const rawSessionID = context.sessionID?.trim();
            if (!rawSessionID) {
              throw new Error("context.sessionID is required for orch_dispatch.");
            }

            ownerId = normalizeOpenCodeOwnerId(rawSessionID);
            rejectOrchDispatchOverrides(args as Record<string, unknown>);

            const goal = args.goal.trim();
            if (!goal) {
              throw new Error("Usage: provide a worker goal.");
            }

            const command = buildOrchestraDoCommand(ownerId, {
              goal,
              role: args.role,
              taskLabel: args.taskLabel,
            });
            const result = await runOrchestra(command);
            if (result.returncode !== 0) {
              throw new Error(result.stderr || "orchestra dispatch failed.");
            }

            const timeoutSeconds = extractDispatchTimeoutSeconds(result.stdout);
            const runId = extractRunId(result.stdout);
            await notifyDispatchToast(client, ownerId);
            if (!runId) {
              return result.stdout.trim() || result.stderr.trim();
            }

            trackSessionRun(ownerId, runId);
            queueRunProgressNotification(client, ownerId, runId, timeoutSeconds, runOrchestra);
            queueSessionReportDelivery(client, rawSessionID, ownerId, runId, timeoutSeconds, runOrchestra);
            const role = extractField(result.stdout, "role") || args.role?.trim() || "worker";
            const ack = await runOrchestra(["orchestra", "_dispatch-ack", "--run-id", runId, "--role", role]);
            return ack.stdout.trim() || result.stdout.trim() || `orchestra dispatched: ${role} ${runId}`;
          } catch (error) {
            await notifyFailureToast(client, ownerId, error);
            throw error;
          }
        },
      }),
    },
  };
};

export default OrchestraPlugin;
