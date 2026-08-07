from __future__ import annotations

from pathlib import Path


def test_opencode_plugin_registers_orch_dispatch_tool() -> None:
    source = Path("extensions/opencode/orchestra/index.ts").read_text(encoding="utf-8")

    assert 'import { tool, type Plugin } from "@opencode-ai/plugin";' in source
    assert 'export const OrchestraPlugin: Plugin = async ({ client }) => {' in source
    assert 'tool: {' in source
    assert 'orch_dispatch: tool({' in source
    assert 'description: "Orchestra dispatch tool for OpenCode."' in source
    assert 'goal: tool.schema.string()' in source


def test_opencode_plugin_executes_with_session_identity_guardrails() -> None:
    source = Path("extensions/opencode/orchestra/index.ts").read_text(encoding="utf-8")

    assert 'async execute(args, context)' in source
    assert 'const rawSessionID = context.sessionID?.trim();' in source
    assert 'if (!rawSessionID) {' in source
    assert 'context.sessionID is required for orch_dispatch.' in source
    assert 'function normalizeOpenCodeOwnerId(sessionID: string): string {' in source
    assert 'return `opencode:${normalizedSessionID}`;' in source
    assert 'let ownerId = "opencode:unknown";' in source
    assert 'ownerId = normalizeOpenCodeOwnerId(rawSessionID);' in source
    assert 'const FORBIDDEN_IDENTITY_FIELDS = [' in source
    assert '"session_id"' in source
    assert '"sessionId"' in source
    assert '"orchestrator_session_id"' in source
    assert 'timeout is not accepted by orch_dispatch; configured default_timeout applies.' in source
    assert 'Object.prototype.hasOwnProperty.call(args, "timeout")' in source
    assert 'owner_id: ownerId,' in source
    assert 'role: tool.schema.string().optional()' in source
    assert 'taskLabel: tool.schema.string().optional()' in source


def test_opencode_plugin_builds_tokenized_orchestra_do_argv() -> None:
    source = Path("extensions/opencode/orchestra/index.ts").read_text(encoding="utf-8")

    assert 'type OrchDispatchArgs = {' in source
    assert (
        'function buildOrchestraDoCommand(ownerId: string, args: OrchDispatchArgs): string[] {'
        in source
    )
    assert (
        'const command = ["orchestra", "do", "--session-id", ownerId, "--goal", args.goal.trim()];'
        in source
    )
    assert 'command.push("--role", role);' in source
    assert 'command.push("--task-label", taskLabel);' in source
    assert 'command.join(" ")' not in source
    assert 'shell: true' not in source
    assert 'spawn(' not in source


def test_opencode_plugin_executes_tokenized_dispatch_with_execfile_and_wires_delivery() -> None:
    source = Path("extensions/opencode/orchestra/index.ts").read_text(encoding="utf-8")

    assert 'import { execFile } from "node:child_process";' in source
    assert 'const execFileAsync = promisify(execFile);' in source
    assert (
        'function runOrchestra(command: string[]): Promise<SessionReportRunnerResult> {'
        in source
    )
    assert 'const [file, ...args] = command;' in source
    assert 'await execFileAsync(file, args, { encoding: "utf8" });' in source
    assert 'const result = await runOrchestra(command);' in source
    assert 'if (result.returncode !== 0) {' in source
    assert 'stderr: string;' in source
    assert 'const timeoutSeconds = extractDispatchTimeoutSeconds(result.stdout);' in source
    assert 'const runId = extractRunId(result.stdout);' in source
    assert 'await notifyDispatchToast(client, ownerId);' in source
    queue_call = (
        'queueSessionReportDelivery(client, rawSessionID, ownerId, runId, '
        'timeoutSeconds, runOrchestra);'
    )
    assert queue_call in source
    assert 'timeout_seconds: timeoutSeconds,' in source
    assert 'command.join(" ")' not in source
    assert 'shell: true' not in source
    assert 'spawn(' not in source

    execute_pos = source.index('async execute(args, context) {')
    timeout_pos = source.index(
        'const timeoutSeconds = extractDispatchTimeoutSeconds(result.stdout);',
        execute_pos,
    )
    run_id_pos = source.index('const runId = extractRunId(result.stdout);', execute_pos)
    queue_pos = source.index(queue_call, execute_pos)
    return_pos = source.index('return JSON.stringify({', execute_pos)

    assert timeout_pos < run_id_pos < queue_pos < return_pos


def test_opencode_plugin_uses_sparse_toasts_for_dispatch_and_failure() -> None:
    source = Path("extensions/opencode/orchestra/index.ts").read_text(encoding="utf-8")

    assert 'async function showToast(' in source
    assert 'if (!client?.tui?.showToast) {' in source
    assert 'await client.tui.showToast({ body: { message, variant } });' in source
    assert 'async function notifyDispatchToast(' in source
    assert 'async function notifyFailureToast(' in source
    assert 'await notifyDispatchToast(client, ownerId);' in source
    assert 'await notifyFailureToast(client, ownerId, error);' in source
    assert 'context.client' not in source
    assert 'notifyCompletionToast' not in source
    assert 'variant: "success"' not in source


def test_opencode_plugin_requires_timeout_seconds_and_uses_margin_for_report_watcher() -> None:
    source = Path("extensions/opencode/orchestra/index.ts").read_text(encoding="utf-8")

    assert 'const WATCHER_TIMEOUT_MARGIN_SECONDS = 30;' in source
    assert 'function extractDispatchTimeoutSeconds(output: string): number {' in source
    assert 'const timeoutText = extractField(output, "timeout_seconds");' in source
    assert 'throw new Error("orchestra do output did not include timeout_seconds.");' in source
    assert 'throw new Error("orchestra do timeout_seconds must be a positive integer.");' in source
    watcher_timeout = (
        'const watcherTimeoutSeconds = timeoutSeconds + '
        'WATCHER_TIMEOUT_MARGIN_SECONDS;'
    )
    assert watcher_timeout in source
    retrieve_call = (
        'const envelope = await retrieveSessionReport(ownerId, runId, '
        'watcherTimeoutSeconds, runner);'
    )
    assert retrieve_call in source
    assert 'REPORT_WATCHER_TIMEOUT_SECONDS' not in source
    assert 'REPORT_WATCHER_ATTEMPTS' not in source


def test_opencode_plugin_contains_report_watcher_and_retrieval_state() -> None:
    source = Path("extensions/opencode/orchestra/index.ts").read_text(encoding="utf-8")

    assert 'type SessionReportEnvelope = {' in source
    assert 'const deliveredSessionReportRunIds = new Set<string>();' in source
    assert 'const pendingSessionReports = new Map<string, SessionReportEnvelope>();' in source
    assert 'function buildAwaitSessionReportCommand(' in source
    assert '"_await-session-report"' in source
    assert '"--json"' in source
    parse_session_report = (
        'function parseSessionReportEnvelope(stdout: string): '
        'SessionReportEnvelope | null {'
    )
    assert parse_session_report in source
    assert 'JSON.parse(stdout)' in source
    assert 'function retrieveSessionReport(' in source
    assert 'function watchSessionReport(' in source
    assert 'function rememberSessionReport(' in source
    assert 'function getPendingSessionReport(' in source
    assert 'function queueSessionReportDelivery(' in source


def test_opencode_plugin_prompts_final_reports_through_the_owning_session() -> None:
    source = Path("extensions/opencode/orchestra/index.ts").read_text(encoding="utf-8")

    assert 'function hasDeliveredSessionReport(' in source
    assert 'function markSessionReportDelivered(' in source
    assert 'function releaseSessionReport(' in source
    assert 'function buildMarkSessionReportDeliveredCommand(' in source
    assert 'function buildReleaseSessionReportCommand(' in source
    assert 'client.session.prompt({' in source
    assert 'path: { id: rawSessionID },' in source
    assert 'body: { parts: [{ type: "text", text: envelope.report }] },' in source
    assert 'buildMarkSessionReportDeliveredCommand(ownerId, envelope.runIds)' in source
    assert 'markSessionReportDelivered(ownerId, envelope.runIds);' in source
    assert 'buildReleaseSessionReportCommand(ownerId, envelope.runIds)' in source
    release_result_call = (
        'const releaseResult = await runOrchestra('
        'buildReleaseSessionReportCommand(ownerId, envelope.runIds));'
    )
    assert release_result_call in source
    assert 'if (releaseResult.returncode !== 0) {' in source
    assert 'releaseSessionReport(ownerId);' in source
    assert 'sessionID: ownerId,' not in source
    assert 'noReply: true' not in source


def test_opencode_plugin_claims_each_report_once_before_prompting() -> None:
    source = Path("extensions/opencode/orchestra/index.ts").read_text(encoding="utf-8")

    assert 'const inflightSessionReportDeliveries = new Set<string>();' in source
    assert (
        'function getSessionReportDeliveryKey(ownerId: string, runIds: string[]): string {'
        in source
    )
    assert 'JSON.stringify([ownerId, runIds.slice().sort()])' in source
    assert 'function claimSessionReportDelivery(' in source
    assert 'if (inflightSessionReportDeliveries.has(deliveryKey)) {' in source
    assert 'inflightSessionReportDeliveries.add(deliveryKey);' in source
    assert 'function releaseSessionReportDeliveryClaim(' in source
    assert 'if (!claimSessionReportDelivery(ownerId, envelope.runIds)) {' in source
    assert 'releaseSessionReportDeliveryClaim(ownerId, envelope.runIds);' in source
    assert 'finally {' not in source

    claim_pos = source.index('if (!claimSessionReportDelivery(ownerId, envelope.runIds)) {')
    prompt_pos = source.index('await client.session.prompt({')
    mark_pos = source.index('markSessionReportDelivered(ownerId, envelope.runIds);')
    release_claim_pos = source.index('releaseSessionReportDeliveryClaim(ownerId, envelope.runIds);')

    assert claim_pos < prompt_pos < mark_pos < release_claim_pos


def test_opencode_plugin_queues_report_delivery_in_background() -> None:
    source = Path("extensions/opencode/orchestra/index.ts").read_text(encoding="utf-8")

    assert 'function queueSessionReportDelivery(' in source
    background_delivery = (
        'void deliverSessionReport(client, rawSessionID, ownerId, runId, '
        'timeoutSeconds, runner).catch('
    )
    assert background_delivery in source

    execute_pos = source.index('async execute(args, context) {')
    queue_call = (
        'queueSessionReportDelivery(client, rawSessionID, ownerId, runId, '
        'timeoutSeconds, runOrchestra);'
    )
    queue_pos = source.index(queue_call, execute_pos)
    return_pos = source.index('return JSON.stringify({', execute_pos)

    assert queue_pos < return_pos


def test_opencode_plugin_delivers_final_reports_only_after_retrieval_succeeds() -> None:
    source = Path("extensions/opencode/orchestra/index.ts").read_text(encoding="utf-8")

    deliver_pos = source.index('async function deliverSessionReport(')
    watch_pos = source.index(
        'const envelope = await watchSessionReport(ownerId, runId, timeoutSeconds, runner);',
        deliver_pos,
    )
    prompt_call_pos = source.index(
        'await promptSessionReport(client, rawSessionID, ownerId, envelope);',
        deliver_pos,
    )
    prompt_pos = source.index('await client.session.prompt({')
    mark_command_pos = source.index(
        'buildMarkSessionReportDeliveredCommand(ownerId, envelope.runIds)'
    )
    mark_pos = source.index('markSessionReportDelivered(ownerId, envelope.runIds);')
    release_command_pos = source.index(
        'buildReleaseSessionReportCommand(ownerId, envelope.runIds)'
    )
    release_pos = source.index('releaseSessionReport(ownerId);')

    assert watch_pos < prompt_call_pos
    assert prompt_pos < mark_command_pos < mark_pos
    assert prompt_pos < release_command_pos < release_pos
