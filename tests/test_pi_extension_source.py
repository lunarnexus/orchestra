from __future__ import annotations

from pathlib import Path


def test_pi_extension_registers_natural_language_dispatch_tool() -> None:
    extension_source = Path("extensions/pi/orchestra/index.ts").read_text(encoding="utf-8")
    asset_source = Path("src/orchestra/assets/pi/orchestra/index.ts").read_text(encoding="utf-8")
    prompts_source = Path("src/orchestra/assets/prompts.yaml").read_text(encoding="utf-8")

    assert extension_source == asset_source
    assert (
        extension_source.count('function registerOrchStatusTool(toolInfo: ToolInfoPayload): void {')
        == 1
    )
    assert (
        asset_source.count('function registerOrchStatusTool(toolInfo: ToolInfoPayload): void {')
        == 1
    )
    assert 'name: "orch_dispatch"' in extension_source
    assert 'name: "orch_status"' in extension_source
    assert "_tool-info" in extension_source
    assert 'function registerOrchStatusTool(toolInfo: ToolInfoPayload): void' in extension_source
    assert 'sanitizeRoleListing(output: string): string' in extension_source
    assert 'filter((line) => !/^\\s*env:\\s+/i.test(line))' not in extension_source
    assert (
        'promptGuidelines: [...toolInfo.promptGuidelines, toolInfo.statusActionDescription],'
        in extension_source
    )
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
    assert 'const toolInfo = await loadToolInfo();' in extension_source
    assert 'registerOrchStatusTool(toolInfo);' in extension_source
    assert 'await refreshOrchDispatchToolRegistration(toolInfo);' in extension_source
    assert 'ctx.sessionManager.getSessionId()' in extension_source
    assert 'normalizePiSessionId(ctx.sessionManager.getSessionId())' in extension_source
    assert '["status", "--session-id", sessionId]' in extension_source
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
    assert 'timeout is not accepted by orch_dispatch' in extension_source
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
        'async function refreshOrchDispatchToolRegistration('
        'toolInfo?: ToolInfoPayload): Promise<void>'
        in extension_source
    )
    assert 'subcommand === "on"' in extension_source
    assert 'subcommand === "roles"' in extension_source
    assert 'cachedRoleNames = null;' in extension_source
    assert 'getArgumentCompletions: getOrchArgumentCompletions' in extension_source
    assert (
        'function parseRoleMetadata(output: string): '
        '{ roles: string[]; harnessConfigs: string[] }'
        in extension_source
    )
    assert 'const result = await runOrchestra(["_role-metadata"]);' in extension_source
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


def test_clean_return_templates_live_in_core_not_extension() -> None:
    extension_source = Path("extensions/pi/orchestra/index.ts").read_text(encoding="utf-8")
    core_source = Path("src/orchestra/app.py").read_text(encoding="utf-8")

    assert "_dispatch-ack" in extension_source
    assert "_progress-message" in extension_source
    assert "_command-echo" in extension_source
    assert "const roleMatch = /^role:" in extension_source
    assert '["_dispatch-ack", "--run-id", runId, "--role", role]' in extension_source
    assert 'command.push("--role", role)' in extension_source
    assert "help-host" in extension_source
    assert 'rest.length > 0 ? ["roles", ...rest] : ["roles", "--all"]' in extension_source
    assert (
        'description: "Orchestra host adapter: /orch help|on|do|roles|status|stop|doctor|history"'
        in extension_source
    )
    assert (
        'pi.sendUserMessage(message, { deliverAs: "followUp", triggerTurn: true });'
        in extension_source
    )
    assert "compactReturnMessage" not in extension_source
    assert "format_orchestrator_return" in core_source
    assert "format_progress_notification" in core_source
    assert "format_dispatch_ack" in core_source
    assert "format_command_echo" in core_source
    assert "tool_info" in core_source
    assert "[orchestra: {run.role}" in core_source
    assert "Request: {run.task_label}" in core_source
    assert "Log: {run.log_path}" in core_source
    assert "{label}: {summary}" in core_source
