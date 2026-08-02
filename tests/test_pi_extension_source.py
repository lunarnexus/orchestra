from __future__ import annotations

from pathlib import Path


def test_pi_extension_registers_natural_language_dispatch_tool() -> None:
    extension_source = Path("extensions/pi/orchestra/index.ts").read_text(encoding="utf-8")
    asset_source = Path("src/orchestra/assets/pi/orchestra/index.ts").read_text(encoding="utf-8")
    prompts_source = Path("src/orchestra/assets/prompts.yaml").read_text(encoding="utf-8")

    assert extension_source == asset_source
    assert 'name: "orch_dispatch"' in extension_source
    assert "_tool-info" in extension_source
    assert 'const ORCHESTRA_WORKER_ENV = "ORCHESTRA_WORKER"' in extension_source
    assert "function canDispatchOrchestraWorker(): boolean" in extension_source
    assert "return orchestraWorkerBudget() !== 1;" in extension_source
    assert "const registerDispatchTool = canDispatchOrchestraWorker();" in extension_source
    assert "function registerOrchDispatchTool(toolInfo: ToolInfoPayload): void" in extension_source
    assert "async function refreshOrchDispatchToolRegistration(): Promise<void>" in extension_source
    assert "await refreshOrchDispatchToolRegistration();" in extension_source
    assert "timeout: Type.Optional" not in extension_source
    assert "timeout is not accepted by orch_dispatch" in extension_source
    assert 'subcommand === "roles"' in extension_source
    assert 'cachedRoleNames = null;' in extension_source
    assert 'getArgumentCompletions: getOrchArgumentCompletions' in extension_source
    assert 'function tokenizeArgs(input: string): TokenizeArgsResult' in extension_source
    assert 'Malformed quoted string in /orch do arguments' in extension_source
    assert '''if (subcommand === "roles") {
        const result = await runOrchestra(rest.length > 0 ? ["roles", ...rest] : ["roles", "--all"]);
        cachedRoleNames = null;
        await refreshOrchDispatchToolRegistration();
''' in extension_source
    for keyword in ("delegate", "dispatch", "subagent", "sub-agent", "worker"):
        assert keyword in prompts_source


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
        'description: "Orchestra host adapter: /orch help|do|roles|status|stop|doctor|history"'
        in extension_source
    )
    assert "compactReturnMessage" not in extension_source
    assert "format_orchestrator_return" in core_source
    assert "format_progress_notification" in core_source
    assert "format_dispatch_ack" in core_source
    assert "format_command_echo" in core_source
    assert "tool_info" in core_source
    assert "[orchestra: Worker" in core_source
    assert "Request: {run.task_label}" in core_source
    assert "Log: {run.log_path}" in core_source
    assert "{label}: {summary}" in core_source
