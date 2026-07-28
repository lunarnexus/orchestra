from __future__ import annotations

from pathlib import Path


def test_pi_extension_registers_natural_language_dispatch_tool() -> None:
    source = Path("extensions/pi/orchestra/index.ts").read_text(encoding="utf-8")

    assert 'name: "orch_dispatch"' in source
    for keyword in ("delegate", "dispatch", "subagent", "sub-agent", "worker"):
        assert keyword in source
    assert "availableRoles" in source
    assert "Omit role to use the default worker role" in source


def test_clean_return_templates_live_in_core_not_extension() -> None:
    extension_source = Path("extensions/pi/orchestra/index.ts").read_text(encoding="utf-8")
    core_source = Path("src/orchestra/app.py").read_text(encoding="utf-8")

    assert "_dispatch-ack" in extension_source
    assert "_progress-message" in extension_source
    assert "compactReturnMessage" not in extension_source
    assert "format_orchestrator_return" in core_source
    assert "format_progress_notification" in core_source
    assert "format_dispatch_ack" in core_source
    assert "[orchestra: Worker" in core_source
    assert "Request: {run.task_label}" in core_source
    assert "Log: {run.log_path}" in core_source
    assert "{label}: {summary}" in core_source
