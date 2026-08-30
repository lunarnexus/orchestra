from __future__ import annotations

from pathlib import Path


def test_pi_extension_registers_natural_language_dispatch_tool() -> None:
    extension_source = Path("extensions/pi/orchestra/index.ts").read_text(encoding="utf-8")
    prompts_source = Path("prompts.yaml").read_text(encoding="utf-8")

    assert (
        extension_source.count('function registerOrchStatusTool(toolInfo: ToolInfoPayload): void {')
        == 1
    )
    assert 'name: "orch_dispatch"' in extension_source
    assert 'name: "orch_status"' in extension_source
    assert "_tool-info" in extension_source
    assert 'function registerOrchStatusTool(toolInfo: ToolInfoPayload): void' in extension_source
    assert 'sanitizeRoleListing(output: string): string' in extension_source
    assert 'filter((line) => !/^\\s*env:\\s+/i.test(line))' not in extension_source
    assert "promptSnippet" not in extension_source
    assert "promptGuidelines" not in extension_source
    assert 'action: Type.Union([' in extension_source
    assert (
        'runId: Type.Optional(Type.String({ description: toolInfo.statusRunIdDescription }))'
        in extension_source
    )
    assert (
        'limit: Type.Optional(Type.String({ description: toolInfo.statusLimitDescription }))'
        in extension_source
    )
    assert (
        'role: Type.Optional(Type.String({ description: toolInfo.statusRoleDescription }))'
        in extension_source
    )
    assert (
        'setting: Type.Optional(Type.String({ description: toolInfo.statusSettingDescription }))'
        in extension_source
    )
    assert (
        'value: Type.Optional(Type.String({ description: toolInfo.statusValueDescription }))'
        in extension_source
    )
    assert 'let currentToolInfo = await loadToolInfo();' in extension_source
    assert 'registerOrchStatusTool(toolInfo);' in extension_source
    assert 'await refreshOrchestraToolRegistrations(currentToolInfo);' in extension_source
    assert 'ctx.sessionManager.getSessionId()' in extension_source
    assert 'normalizePiSessionId(ctx.sessionManager.getSessionId())' in extension_source
    assert '["status", "--session-id", sessionId, "--json"]' in extension_source
    assert '["history", "--session-id", sessionId, "--limit", limitValue]' in extension_source
    assert '["stop", "--session-id", sessionId, "--run-id", runId]' in extension_source
    assert '["help-host"]' in extension_source
    assert '["doctor"]' in extension_source
    assert '["roles", "--all"]' in extension_source
    assert '["_orchestrator-skill"]' in extension_source
    assert 'runId is required for orch_status stop.' in extension_source
    assert (
        'orch_status roles is read-only; use the host /orch roles command to change role settings.'
        in extension_source
    )
    assert '"roles", role, setting, value' not in extension_source
    assert 'sanitizeRoleListing(output: string): string' in extension_source
    assert 'filter((line) => !/^\\s*env:\\s+/i.test(line))' not in extension_source
    assert 'dispatchTimeoutError: string;' in extension_source
    assert 'toolInfo.dispatchTimeoutError' in extension_source
    assert 'timeout is not accepted by orch_dispatch' not in extension_source
    assert 'const ORCHESTRA_DISPATCH_BUDGET_ENV = "ORCHESTRA_DISPATCH_BUDGET"' in extension_source
    assert 'const ORCHESTRA_TURN_BUDGET_ENV = "ORCHESTRA_TURN_BUDGET"' in extension_source
    assert (
        'const ORCHESTRA_SOFT_TIMEOUT_SECONDS_ENV = "ORCHESTRA_SOFT_TIMEOUT_SECONDS"'
        in extension_source
    )
    assert 'pi.on("turn_end"' in extension_source
    assert 'pi.on("tool_call"' in extension_source
    assert 'pi.sendUserMessage(`${prompt}' in extension_source
    assert 'function canDispatchOrchestraWorker(): boolean' in extension_source
    assert 'return orchestraDispatchBudget() !== 1;' in extension_source
    assert 'const registerDispatchTool = canDispatchOrchestraWorker();' in extension_source
    assert 'function registerOrchDispatchTool(toolInfo: ToolInfoPayload): void' in extension_source
    assert (
        'async function refreshOrchestraToolRegistrations('
        'toolInfo?: ToolInfoPayload): Promise<void>'
        in extension_source
    )
    assert 'subcommand === "on"' in extension_source
    assert 'subcommand === "off"' in extension_source
    assert 'subcommand === "roles"' in extension_source
    assert 'cachedRoleNames = null;' in extension_source
    assert 'getArgumentCompletions: getOrchArgumentCompletions' in extension_source
    assert (
        'function parseRoleMetadata(output: string): '
        '{ roles: string[]; harnessConfigs: string[] }'
        in extension_source
    )
    assert 'const result = await runOrchestra(["_role-metadata"]);' in extension_source
    assert 'function parseDispatchPayload(output: string): DispatchPayload {' in extension_source
    assert (
        'const result = await runOrchestra(["status", "--session-id", sessionId, "--json"]);'
        in extension_source
    )
    assert '"--json",' in extension_source
    assert '{ token: "harness ", description: "Set selected harness config" }' in extension_source
    assert (
        '{ token: "profile ", description: "Set harness profile when supported" }'
        in extension_source
    )
    assert (
        '{ token: "agent ", description: "Set harness agent when supported" }'
        in extension_source
    )
    assert 'parsed.tokens[2] === "harness"' in extension_source
    assert 'parsed.tokens[2] === "enabled"' in extension_source
    assert 'function tokenizeArgs(input: string): TokenizeArgsResult' in extension_source
    assert 'Malformed quoted string in /orch do arguments' in extension_source
    assert 'filter((line) => !/^\\s*env:\\s+/i.test(line))' not in extension_source
    status_block = extension_source[
        extension_source.index(
            'function registerOrchStatusTool(toolInfo: ToolInfoPayload): void {'
        ) : extension_source.index(
            'function registerOrchDispatchTool(toolInfo: ToolInfoPayload): void {'
        )
    ]
    assert 'goal: Type.String(' not in status_block
    assert 'taskLabel: Type.Optional' not in status_block
    for keyword in ("delegate", "dispatch", "subagent", "sub-agent"):
        assert keyword in prompts_source
    assert "worker" not in prompts_source


def test_pi_extension_footer_includes_session_mode() -> None:
    extension_source = Path("extensions/pi/orchestra/index.ts").read_text(encoding="utf-8")

    # The extension tracks the last known main session mode locally.
    assert 'type MainSessionMode = "off" | "on" | "orchestrator";' in extension_source
    assert "let mainSessionMode: MainSessionMode | null = null;" in extension_source

    # Footer composes a labeled dimmed mode with the existing role/active-run text.
    footer_start = extension_source.index("function renderOrchestraFooterStatus(")
    footer_end = extension_source.index("function setOrchestraWorkerStatus(", footer_start)
    footer_body = extension_source[footer_start:footer_end]
    assert 'if (!mode || mode === "off") return undefined;' in footer_body
    assert 'theme.fg("dim", `Orchestra:${mode}`)' in footer_body
    assert (
        "status && status.activeCount > 0 ? renderOrchestraWorkerStatus(theme, "
        "status.roleCounts) : undefined"
        in footer_body
    )
    # The existing role renderer is preserved.
    assert (
        "function renderOrchestraWorkerStatus(theme: OrchestraFooterTheme, "
        "roleCounts: ActiveRoleCount[]): string | undefined {"
        in extension_source
    )

    # Session start resets the tracked mode and initializes it from core tool info.
    start_idx = extension_source.index('pi.on("session_start"')
    shutdown_idx = extension_source.index('pi.on("session_shutdown"', start_idx)
    init_block = extension_source[start_idx:shutdown_idx]
    assert "mainSessionMode = null;" in init_block
    assert 'mainSessionMode === "orchestrator"' in init_block

    # Session shutdown clears the tracked mode.
    register_idx = extension_source.index("const registerDispatchTool")
    shutdown_block = extension_source[shutdown_idx:register_idx]
    assert "mainSessionMode = null;" in shutdown_block

    # Orchestrator activation tracks the mode when core confirms it.
    inject_start = extension_source.index(
        "async function injectOrchestratorSkill(sessionId: string)"
    )
    on_idx = extension_source.index("async function handleOrchOn(", inject_start)
    inject_body = extension_source[inject_start:on_idx]
    assert 'mainSessionMode = "orchestrator";' in inject_body

    # /orch off and first /orch on track the mode when core confirms it.
    handler_end = extension_source.index("async function getOrchArgumentCompletions(", on_idx)
    handlers_block = extension_source[on_idx:handler_end]
    assert 'mainSessionMode = "on";' in handlers_block
    assert 'mainSessionMode = "off";' in handlers_block

    # The /orch command paths render the tracked mode through setStatus("orchestra", ...).
    assert "setOrchestraWorkerStatus(ctx, null, mainSessionMode);" in extension_source
    assert (
        "await refreshOrchestraWorkerStatus(currentSessionId, (status) => "
        "setOrchestraWorkerStatus(ctx, status, mainSessionMode), { fresh: true });"
        in extension_source
    )


def test_pi_extension_budget_texts_come_from_loaded_tool_info() -> None:
    extension_source = Path("extensions/pi/orchestra/index.ts").read_text(encoding="utf-8")

    # The loaded _tool-info payload owns both budget texts.
    assert "budgetTriggerLabel: string;" in extension_source
    assert "softTimeoutBlockReason: string;" in extension_source

    # Injection appends the core-owned trigger label; env override and steer delivery are kept.
    assert (
        'pi.sendUserMessage(`${prompt}\\n\\n${currentToolInfo.budgetTriggerLabel}: ${reason}`, '
        '{ deliverAs: "steer" });'
        in extension_source
    )
    assert '"Budget trigger"' not in extension_source

    # Soft-timeout blocking uses the core-owned block reason.
    assert (
        'return { block: true, reason: currentToolInfo.softTimeoutBlockReason };'
        in extension_source
    )
    assert '"Orchestra soft timeout reached; return budget handoff"' not in extension_source


def test_clean_return_templates_live_in_core_not_extension() -> None:
    extension_source = Path("extensions/pi/orchestra/index.ts").read_text(encoding="utf-8")
    core_reports_source = Path("src/orchestra/reports.py").read_text(encoding="utf-8")
    core_host_text_source = Path("src/orchestra/host_text.py").read_text(encoding="utf-8")

    assert "_dispatch-ack" in extension_source
    assert "_progress-message" in extension_source
    assert "_command-echo" in extension_source
    assert 'function parseDispatchPayload(output: string): DispatchPayload {' in extension_source
    assert (
        'function parseProgressNotification(output: string): { message: string | null } {'
        in extension_source
    )
    assert '["_dispatch-ack", "--run-id", runId, "--role", role]' in extension_source
    assert 'command.push("--role", role)' in extension_source
    assert (
        'const dispatch = result.code === 0 ? parseDispatchPayload(result.stdout) : null;'
        in extension_source
    )
    assert "help-host" in extension_source
    assert 'rest.length > 0 ? ["roles", ...rest] : ["roles", "--all"]' in extension_source
    adapter_description = (
        'description: "Orchestra host adapter: '
        '/orch help|on|off|do|roles|status|stop|doctor|history"'
    )
    assert adapter_description in extension_source
    assert (
        'pi.sendUserMessage(message, { deliverAs: "followUp", triggerTurn: true });'
        in extension_source
    )
    assert (
        'pi.setActiveTools(enabled ? [...withoutOrchestra, ...orchestraTools] : withoutOrchestra);'
        in extension_source
    )
    assert 'Run "/orch on" again to load the orchestrator skill.' in extension_source
    assert (
        'Orchestra tools hidden for this session. Run /orch on to enable them again.'
        in extension_source
    )
    assert "compactReturnMessage" not in extension_source
    assert "format_orchestrator_return" in core_reports_source
    assert "clean_result_summary" in core_reports_source
    assert "[orchestra: {run.role}" in core_reports_source
    assert "Request: {run.task_label}" not in core_reports_source
    assert "log: {run.log_path}" in core_reports_source
    assert "summary: {_format_run_summary(run)}" in core_reports_source
    assert "format_progress_notification" in core_host_text_source
    assert "format_dispatch_ack" in core_host_text_source
    assert "format_command_echo" in core_host_text_source
    assert "tool_info" not in core_host_text_source
    assert "tool_info_payload" in Path("src/orchestra/host_commands.py").read_text(
        encoding="utf-8"
    )
