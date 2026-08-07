import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { tool, type Plugin } from "@opencode-ai/plugin";

const FORBIDDEN_IDENTITY_FIELDS = ["session_id", "sessionId", "orchestrator_session_id"] as const;
const TOOL_TIMEOUT_ERROR = "timeout is not accepted by orch_dispatch; configured default_timeout applies.";
const WATCHER_TIMEOUT_MARGIN_SECONDS = 30;
const execFileAsync = promisify(execFile);

type OrchDispatchArgs = {
  goal: string;
  role?: string;
  taskLabel?: string;
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

type OpenCodeSessionPromptClient = {
  session?: {
    prompt?: (payload: {
      path: {
        id: string;
      };
      body: {
        parts: Array<{
          type: "text";
          text: string;
        }>;
      };
    }) => Promise<unknown> | unknown;
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

async function runOrchestra(command: string[]): Promise<SessionReportRunnerResult> {
  const [file, ...args] = command;

  try {
    const { stdout, stderr } = await execFileAsync(file, args, { encoding: "utf8" });
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

async function promptSessionReport(
  client: OpenCodeDeliveryClient | undefined,
  rawSessionID: string,
  ownerId: string,
  envelope: SessionReportEnvelope,
): Promise<boolean> {
  if (!client?.session?.prompt) {
    return false;
  }

  if (!claimSessionReportDelivery(ownerId, envelope.runIds)) {
    return false;
  }

  try {
    await client.session.prompt({
      path: { id: rawSessionID },
      body: { parts: [{ type: "text", text: envelope.report }] },
    });
    const markResult = await runOrchestra(buildMarkSessionReportDeliveredCommand(ownerId, envelope.runIds));
    if (markResult.returncode !== 0) {
      throw new Error(markResult.stderr || "failed to mark Orchestra report delivered.");
    }
    markSessionReportDelivered(ownerId, envelope.runIds);
    releaseSessionReportDeliveryClaim(ownerId, envelope.runIds);
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
      return false;
    }
    releaseSessionReport(ownerId);
    releaseSessionReportDeliveryClaim(ownerId, envelope.runIds);
    return false;
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

  await promptSessionReport(client, rawSessionID, ownerId, envelope);
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

export const OrchestraPlugin: Plugin = async ({ client }) => {
  return {
    tool: {
      orch_dispatch: tool({
        description: "Orchestra dispatch tool for OpenCode.",
        args: {
          goal: tool.schema.string().describe("Task goal for the Orchestra worker."),
          role: tool.schema.string().optional().describe("Optional worker role; omit to use the default."),
          taskLabel: tool.schema.string().optional().describe("Optional task label to include with the dispatch."),
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
            const command = buildOrchestraDoCommand(ownerId, {
              goal: args.goal,
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
            if (runId) {
              queueSessionReportDelivery(client, rawSessionID, ownerId, runId, timeoutSeconds, runOrchestra);
            }

            return JSON.stringify({
              ok: true,
              owner_id: ownerId,
              run_id: runId,
              timeout_seconds: timeoutSeconds,
              ack: result.stdout.trim(),
            });
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
