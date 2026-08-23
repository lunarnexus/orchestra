from __future__ import annotations

from pathlib import Path


def test_opencode_plugin_registers_orch_dispatch_tool() -> None:
    source = Path("extensions/opencode/orchestra/index.ts").read_text(encoding="utf-8")

    assert 'import { tool, type Plugin } from "@opencode-ai/plugin";' in source
    assert 'export const OrchestraPlugin: Plugin = async ({ client }) => {' in source
    assert 'const orchStatusTool = tool({' in source
    assert 'action: tool.schema' in source
    assert '.enum(["on", "status", "history", "help", "doctor", "roles", "stop"])' in source
    assert (
        'runId: tool.schema.string().optional().describe(toolInfo.statusRunIdDescription),'
        in source
    )
    assert 'orch_status: orchStatusTool,' in source
    assert 'tool: {' in source
    assert 'orch_dispatch: tool({' in source
    assert 'const toolInfo = await loadToolInfo();' in source
    assert 'description: toolInfo.description,' in source
    assert 'goal: tool.schema.string().describe(toolInfo.goalDescription),' in source
    assert 'role: tool.schema.string().optional().describe(toolInfo.roleDescription),' in source
    assert (
        'taskLabel: tool.schema.string().optional().describe(toolInfo.taskLabelDescription),'
        in source
    )
    assert 'description: toolInfo.statusDescription,' in source
    assert (
        'action: tool.schema.enum(["on", "status", "history", "help", "doctor", "roles", "stop"])'
        in source
    )


def test_opencode_plugin_routes_orch_status_actions_and_role_settings() -> None:
    source = Path("extensions/opencode/orchestra/index.ts").read_text(encoding="utf-8")

    assert 'type OrchStatusArgs = {' in source
    assert 'runId?: string;' in source
    assert (
        'const SUPPORTED_ROLE_SETTINGS = new Set(["harness", "enabled", "model", "profile", '
        '"agent"]);' in source
    )
    assert 'if (args.action === "on") {' in source
    assert '["orchestra", "_orchestrator-skill"]' in source
    assert '["orchestra", "status", "--session-id", ownerId]' in source
    assert 'normalizeOrchStatusLimit(args.limit)' in source
    assert (
        '["orchestra", "history", "--session-id", ownerId, "--limit", '
        'normalizeOrchStatusLimit(args.limit)]' in source
    )
    assert '["orchestra", "help-opencode"]' in source
    assert '["orchestra", "doctor"]' in source
    assert '["orchestra", "roles", "--all"]' in source
    assert '["orchestra", "roles", role, setting, value]' not in source
    assert '["orchestra", "stop", "--session-id", ownerId, "--run-id", runId]' in source
    assert (
        'orch_status roles is read-only; use the host /orch roles command to change role settings.'
        in source
    )
    assert 'Unsupported role setting' not in source
    assert 'context.sessionID is required for orch_status status/history/stop.' in source
    assert 'runId is required for orch_status stop.' in source
    assert 'limit is only accepted for orch_status history.' not in source
    assert 'role, setting, and value are only accepted for orch_status roles.' not in source


def test_opencode_plugin_ignores_irrelevant_orch_status_optional_fields() -> None:
    source = Path("extensions/opencode/orchestra/index.ts").read_text(encoding="utf-8")

    validate_pos = source.index("function validateOrchStatusArgs(")
    roles_return_pos = source.index('if (action !== "roles") {', validate_pos)
    roles_validation_pos = source.index(
        'orch_status roles is read-only; use the host /orch roles command to change role settings.',
        validate_pos,
    )
    history_command_pos = source.index('if (args.action === "history") {')
    limit_normalize_pos = source.index("normalizeOrchStatusLimit(args.limit)", history_command_pos)

    assert roles_return_pos < roles_validation_pos
    assert history_command_pos < limit_normalize_pos
    assert "limit is only accepted for orch_status history." not in source
    assert "role, setting, and value are only accepted for orch_status roles." not in source


def test_opencode_command_template_routes_through_tools() -> None:
    command_source = Path("extensions/opencode/orchestra/commands/orch.md").read_text(
        encoding="utf-8"
    )

    assert (
        "Call exactly one Orchestra tool for this command, "
        "then return the tool output to the user:"
    ) in command_source
    assert 'orch_status({ action: "on" })' in command_source
    assert 'orch_dispatch({ goal, role?, taskLabel? })' in command_source
    assert "/orch stop" not in command_source


def test_opencode_plugin_reuses_core_tool_info_and_dispatch_budget_guard() -> None:
    source = Path("extensions/opencode/orchestra/index.ts").read_text(encoding="utf-8")

    assert 'const ORCHESTRA_DISPATCH_BUDGET_ENV = "ORCHESTRA_DISPATCH_BUDGET";' in source
    assert 'function orchestraDispatchBudget(): number {' in source
    assert 'function canDispatchOrchestraWorker(): boolean {' in source
    assert 'return orchestraDispatchBudget() !== 1;' in source
    assert 'async function loadToolInfo(): Promise<ToolInfoPayload> {' in source
    assert 'const result = await runOrchestra(["orchestra", "_tool-info"]);' in source
    assert (
        'throw new Error("failed to load orch_dispatch and orch_status metadata from '
        'orchestra _tool-info");' in source
    )
    assert 'const orchStatusTool = tool({' in source
    assert 'if (!canDispatchOrchestraWorker()) {' in source
    assert 'disposePluginRuntimeState(runtimeState);' in source
    assert 'const toolInfo = await loadToolInfo();' in source
    assert 'description: toolInfo.description,' in source
    assert 'goal: tool.schema.string().describe(toolInfo.goalDescription),' in source
    assert 'role: tool.schema.string().optional().describe(toolInfo.roleDescription),' in source
    assert (
        'taskLabel: tool.schema.string().optional().describe(toolInfo.taskLabelDescription),'
        in source
    )
    assert 'promptSnippet: "Use Orchestra tools to delegate work."' not in source


def test_opencode_plugin_forwards_orchestra_config_and_catalog_to_cli_calls() -> None:
    source = Path("extensions/opencode/orchestra/index.ts").read_text(encoding="utf-8")

    assert 'function orchestraBaseArgs(): string[] {' in source
    assert 'if (process.env.ORCHESTRA_CONFIG) {' in source
    assert 'args.push("--config", process.env.ORCHESTRA_CONFIG);' in source
    assert 'if (process.env.ORCHESTRA_AGENT_CATALOG) {' in source
    assert 'args.push("--agent-catalog", process.env.ORCHESTRA_AGENT_CATALOG);' in source
    assert 'execFileAsync(file, [...orchestraBaseArgs(), ...args], { encoding: "utf8" });' in source


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
    assert 'dispatchTimeoutError: string;' in source
    assert 'throw new Error(toolInfo.dispatchTimeoutError);' in source
    assert (
        "timeout is not accepted by orch_dispatch; configured default_timeout applies."
        not in source
    )
    assert 'Object.prototype.hasOwnProperty.call(args, "timeout")' in source
    assert 'const goal = args.goal.trim();' in source
    assert 'if (!goal) {' in source
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
    assert (
        'await execFileAsync(file, [...orchestraBaseArgs(), ...args], { '
        'encoding: "utf8" });'
        in source
    )
    assert 'const result = await runOrchestra(command);' in source
    assert 'if (result.returncode !== 0) {' in source
    assert 'stderr: string;' in source
    assert 'const dispatch = parseDispatchPayload(result.stdout);' in source
    assert 'const timeoutSeconds = dispatch.timeout_seconds;' in source
    assert 'const runId = typeof dispatch.run_id === "string" ? dispatch.run_id : null;' in source
    assert 'await notifyDispatchToast(client, ownerId);' in source
    queue_call = (
        'queueSessionReportDelivery(client, rawSessionID, ownerId, runId, '
        'timeoutSeconds, runOrchestra, runtimeState);'
    )
    ack_call = (
        'const ack = await runOrchestra(["orchestra", "_dispatch-ack", '
        '"--run-id", runId, "--role", role]);'
    )
    assert queue_call in source
    assert ack_call in source
    assert 'timeout_seconds: timeoutSeconds,' not in source
    assert 'return ack.stdout.trim();' in source
    assert 'throw new Error(ack.stderr || "orchestra dispatch ack failed.");' in source
    assert '`orchestra dispatched: ${role} ${runId}`' not in source
    assert 'command.join(" ")' not in source
    assert 'shell: true' not in source
    assert 'spawn(' not in source

    execute_pos = source.index('async execute(args, context) {')
    timeout_pos = source.index(
        'const timeoutSeconds = dispatch.timeout_seconds;',
        execute_pos,
    )
    run_id_pos = source.index(
        'const runId = typeof dispatch.run_id === "string" ? dispatch.run_id : null;',
        execute_pos,
    )
    queue_pos = source.index(queue_call, execute_pos)
    ack_pos = source.index(ack_call, execute_pos)
    return_pos = source.index('return ack.stdout.trim();', execute_pos)

    assert timeout_pos < run_id_pos < queue_pos < ack_pos < return_pos


def test_opencode_plugin_fails_when_dispatch_ack_fails() -> None:
    source = Path("extensions/opencode/orchestra/index.ts").read_text(encoding="utf-8")

    ack_call = (
        'const ack = await runOrchestra(["orchestra", "_dispatch-ack", '
        '"--run-id", runId, "--role", role]);'
    )

    assert ack_call in source
    assert 'if (ack.returncode !== 0 || !ack.stdout.trim()) {' in source
    assert 'throw new Error(ack.stderr || "orchestra dispatch ack failed.");' in source
    assert '`orchestra dispatched: ${role} ${runId}`' not in source


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
    assert 'type DispatchPayload = {' in source
    assert 'function parseDispatchPayload(output: string): DispatchPayload {' in source
    assert 'const timeoutSeconds = dispatch.timeout_seconds;' in source
    assert 'if (!runId || typeof timeoutSeconds !== "number") {' in source
    assert (
        'return dispatch.message?.trim() || result.stdout.trim() || result.stderr.trim();'
        in source
    )
    watcher_timeout = (
        'const watcherTimeoutSeconds = timeoutSeconds + '
        'WATCHER_TIMEOUT_MARGIN_SECONDS;'
    )
    assert watcher_timeout in source
    retrieve_call = (
        'const envelope = await retrieveSessionReport(ownerId, runId, '
        'watcherTimeoutSeconds, runner, runtimeState);'
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
    assert 'function getSessionPrompt(' in source
    assert 'const session = client?.session;' in source
    assert 'return session.prompt.bind(session);' in source
    assert 'return session.promptAsync.bind(session);' in source
    assert 'await sessionPrompt({' in source
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


def test_opencode_plugin_prefers_prompt_and_cleans_up_report_delivery_claims() -> None:
    source = Path("extensions/opencode/orchestra/index.ts").read_text(encoding="utf-8")

    assert (
        'prompt?: (payload: OpenCodeSessionPromptPayload) => '
        'Promise<unknown> | unknown;'
        in source
    )
    assert 'function getSessionPrompt(' in source
    assert 'const session = client?.session;' in source
    assert 'return session.prompt.bind(session);' in source
    assert 'return session.promptAsync.bind(session);' in source
    assert 'if (!sessionPrompt) {' in source
    assert 'await sessionPrompt({' in source
    assert 'let preserveClaim = false;' in source
    assert 'finally {' in source
    assert 'if (!preserveClaim) {' in source
    assert 'releaseSessionReportDeliveryClaim(ownerId, envelope.runIds);' in source
    assert (
        'if (!(await promptSessionReport(client, rawSessionID, ownerId, envelope, runtimeState))) {'
        in source
    )

    prompt_pos = source.index('async function promptSessionReport(')
    session_prompt_pos = source.index('function getSessionPrompt(')
    finally_pos = source.index('finally {', prompt_pos)
    release_claim_pos = source.index(
        'releaseSessionReportDeliveryClaim(ownerId, envelope.runIds);',
        finally_pos,
    )
    deliver_pos = source.index('async function deliverSessionReport(')
    deliver_null_pos = source.index(
        (
            'if (!(await promptSessionReport(client, rawSessionID, ownerId, '
            'envelope, runtimeState))) {'
        ),
        deliver_pos,
    )

    assert session_prompt_pos < prompt_pos < finally_pos < release_claim_pos
    assert deliver_pos < deliver_null_pos


def test_opencode_plugin_releases_pending_report_when_session_prompt_is_unavailable() -> None:
    source = Path("extensions/opencode/orchestra/index.ts").read_text(encoding="utf-8")

    prompt_pos = source.index('async function promptSessionReport(')
    no_prompt_pos = source.index('if (!sessionPrompt) {', prompt_pos)
    claim_pos = source.index(
        'if (!claimSessionReportDelivery(ownerId, envelope.runIds)) {',
        prompt_pos,
    )
    release_pos = source.index('releaseSessionReport(ownerId);', no_prompt_pos)

    assert 'if (!sessionPrompt) {' in source
    assert 'releaseSessionReport(ownerId);' in source
    assert no_prompt_pos < release_pos < claim_pos

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
    assert 'finally {' in source

    claim_pos = source.index('if (!claimSessionReportDelivery(ownerId, envelope.runIds)) {')
    prompt_pos = source.index('await sessionPrompt({')
    mark_pos = source.index('markSessionReportDelivered(ownerId, envelope.runIds);')
    release_claim_pos = source.index('releaseSessionReportDeliveryClaim(ownerId, envelope.runIds);')

    assert claim_pos < prompt_pos < mark_pos < release_claim_pos


def test_opencode_plugin_queues_report_delivery_in_background() -> None:
    source = Path("extensions/opencode/orchestra/index.ts").read_text(encoding="utf-8")

    assert 'function queueSessionReportDelivery(' in source
    background_delivery = (
        'void deliverSessionReport(client, rawSessionID, ownerId, runId, '
        'timeoutSeconds, runner, runtimeState).catch('
    )
    assert background_delivery in source

    execute_pos = source.index('async execute(args, context) {')
    queue_call = (
        'queueSessionReportDelivery(client, rawSessionID, ownerId, runId, '
        'timeoutSeconds, runOrchestra, runtimeState);'
    )
    queue_pos = source.index(queue_call, execute_pos)
    return_pos = source.index('return ack.stdout.trim();', execute_pos)

    assert queue_pos < return_pos


def test_opencode_plugin_queues_progress_notifications_in_background() -> None:
    source = Path("extensions/opencode/orchestra/index.ts").read_text(encoding="utf-8")

    assert 'const sessionRuns = new Map<string, Set<string>>();' in source
    assert 'const sessionCompletedRuns = new Map<string, Set<string>>();' in source
    assert 'function trackSessionRun(' in source
    assert 'function buildAwaitRunCommand(' in source
    assert '"_await-run"' in source
    assert 'function buildProgressMessageCommand(' in source
    assert '"_progress-message"' in source
    assert 'async function notifyProgressToast(' in source
    assert 'function queueRunProgressNotification(' in source
    assert (
        'void deliverRunProgressNotification(client, ownerId, runId, '
        'timeoutSeconds, runner, runtimeState).catch('
    ) in source

    deliver_pos = source.index('async function deliverRunProgressNotification(')
    watcher_timeout_pos = source.index(
        'const watcherTimeoutSeconds = timeoutSeconds + WATCHER_TIMEOUT_MARGIN_SECONDS;',
        deliver_pos,
    )
    await_run_pos = source.index(
        'const awaitRunResult = await runner(buildAwaitRunCommand('
        'ownerId, runId, watcherTimeoutSeconds));',
        deliver_pos,
    )
    progress_pos = source.index(
        'const progressResult = await runner(',
        deliver_pos,
    )
    toast_pos = source.index(
        'await notifyProgressToast(client, progressResult.stdout.trim() ||',
        deliver_pos,
    )

    execute_pos = source.index('async execute(args, context) {')
    run_id_pos = source.index(
        'const runId = typeof dispatch.run_id === "string" ? dispatch.run_id : null;',
        execute_pos,
    )
    track_pos = source.index('trackSessionRun(ownerId, runId);', execute_pos)
    progress_queue_pos = source.index(
        (
            'queueRunProgressNotification(client, ownerId, runId, timeoutSeconds, '
            'runOrchestra, runtimeState);'
        ),
        execute_pos,
    )
    report_queue_pos = source.index(
        'queueSessionReportDelivery(client, rawSessionID, ownerId, runId, '
        'timeoutSeconds, runOrchestra, runtimeState);',
        execute_pos,
    )
    ack_pos = source.index(
        'const ack = await runOrchestra(["orchestra", "_dispatch-ack", '
        '"--run-id", runId, "--role", role]);',
        execute_pos,
    )

    assert run_id_pos < track_pos < progress_queue_pos < report_queue_pos < ack_pos
    assert deliver_pos < watcher_timeout_pos < await_run_pos < progress_pos < toast_pos


def test_opencode_plugin_cleans_up_progress_state_when_await_run_fails() -> None:
    source = Path("extensions/opencode/orchestra/index.ts").read_text(encoding="utf-8")

    deliver_pos = source.index('async function deliverRunProgressNotification(')
    try_pos = source.index('try {', deliver_pos)
    failure_pos = source.index('if (awaitRunResult.returncode !== 0) {', deliver_pos)
    finally_pos = source.index('finally {', deliver_pos)
    cleanup_guard_pos = source.index('if (!markedCompleted) {', deliver_pos)
    cleanup_pos = source.index('releaseSessionProgressRun(ownerId, runId);', deliver_pos)
    release_all_pos = source.index('releaseSessionProgressRuns(ownerId);', deliver_pos)

    assert 'function releaseSessionProgressRun(ownerId: string, runId: string): void {' in source
    assert 'let markedCompleted = false;' in source
    assert (
        deliver_pos < try_pos < failure_pos < finally_pos < cleanup_guard_pos
        < cleanup_pos < release_all_pos
    )


def test_opencode_plugin_delivers_final_reports_only_after_retrieval_succeeds() -> None:
    source = Path("extensions/opencode/orchestra/index.ts").read_text(encoding="utf-8")

    deliver_pos = source.index('async function deliverSessionReport(')
    watch_pos = source.index(
        (
            'const envelope = await watchSessionReport(ownerId, runId, timeoutSeconds, '
            'runner, runtimeState);'
        ),
        deliver_pos,
    )
    prompt_call_pos = source.index(
        (
            'if (!(await promptSessionReport(client, rawSessionID, ownerId, '
            'envelope, runtimeState))) {'
        ),
        deliver_pos,
    )
    prompt_pos = source.index('await sessionPrompt({')
    mark_command_pos = source.index(
        'buildMarkSessionReportDeliveredCommand(ownerId, envelope.runIds)'
    )
    mark_pos = source.index('markSessionReportDelivered(ownerId, envelope.runIds);')
    release_command_pos = source.index(
        'buildReleaseSessionReportCommand(ownerId, envelope.runIds)'
    )
    release_pos = source.index('releaseSessionReport(ownerId);', release_command_pos)

    assert watch_pos < prompt_call_pos
    assert prompt_pos < mark_command_pos < mark_pos
    assert prompt_pos < release_command_pos < release_pos


def test_opencode_plugin_exposes_dispose_cleanup_and_gates_late_watchers() -> None:
    source = Path("extensions/opencode/orchestra/index.ts").read_text(encoding="utf-8")

    assert 'type OpenCodePluginRuntimeState = {' in source
    assert 'function createPluginRuntimeState(): OpenCodePluginRuntimeState {' in source
    assert 'function clearPluginRuntimeState(): void {' in source
    assert 'deliveredSessionReportRunIds.clear();' in source
    assert 'pendingSessionReports.clear();' in source
    assert 'inflightSessionReportDeliveries.clear();' in source
    assert 'sessionRuns.clear();' in source
    assert 'sessionCompletedRuns.clear();' in source
    assert (
        'function disposePluginRuntimeState(runtimeState: OpenCodePluginRuntimeState): void {'
        in source
    )
    assert 'runtimeState.disposed = true;' in source
    assert 'const runtimeState = createPluginRuntimeState();' in source
    assert 'dispose: () => {' in source
    assert 'disposePluginRuntimeState(runtimeState);' in source
    assert 'if (isPluginRuntimeStateDisposed(runtimeState)) {' in source
    assert 'return null;' in source
    assert 'return;' in source
