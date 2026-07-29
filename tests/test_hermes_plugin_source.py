from __future__ import annotations

import ast
import builtins
import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from tests.helpers import wait_for_condition

PLUGIN_PATH = Path("extensions/hermes/orchestra/__init__.py")
MANIFEST_PATH = Path("extensions/hermes/orchestra/plugin.yaml")


def load_plugin() -> ModuleType:
    spec = importlib.util.spec_from_file_location("orchestra_hermes_plugin", PLUGIN_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeHermesPluginContext:
    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []
        self.commands: list[dict[str, Any]] = []
        self.hooks: list[tuple[str, Any]] = []
        self.injected: list[tuple[str, str]] = []
        self.notifications: list[str] = []
        self.inject_success = True

    def register_tool(self, **kwargs: Any) -> None:
        self.tools.append(kwargs)

    def register_command(self, name: str, **kwargs: Any) -> None:
        self.commands.append({"name": name, **kwargs})

    def register_hook(self, name: str, handler: Any) -> None:
        self.hooks.append((name, handler))

    def inject_message(self, content: str, role: str = "user") -> bool:
        self.injected.append((content, role))
        return self.inject_success

    def notify(self, message: str) -> None:
        self.notifications.append(message)


class InjectOnlyContext:
    def __init__(self) -> None:
        self.injected: list[tuple[str, str]] = []

    def inject_message(self, content: str, role: str = "user") -> bool:
        self.injected.append((content, role))
        return True


def completed(
    args: list[str],
    stdout: str = "",
    stderr: str = "",
    code: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=args, returncode=code, stdout=stdout, stderr=stderr)


def test_hermes_plugin_source_does_not_import_orchestra_package() -> None:
    tree = ast.parse(PLUGIN_PATH.read_text(encoding="utf-8"))

    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_from_roots = {
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert "orchestra" not in imported_roots | imported_from_roots


def test_hermes_plugin_import_does_not_import_orchestra_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "orchestra" or name.startswith("orchestra."):
            raise AssertionError(f"plugin imported Orchestra package: {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    load_plugin()


def test_hermes_plugin_registers_dispatch_tool_without_session_id_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    monkeypatch.setattr(plugin, "_run_orchestra", lambda args: completed(args, code=1))
    ctx = FakeHermesPluginContext()

    plugin.register(ctx)

    assert [tool["name"] for tool in ctx.tools] == ["orch_dispatch"]
    schema = ctx.tools[0]["schema"]
    assert set(schema["parameters"]["properties"]) == {"goal", "role", "timeout", "taskLabel"}
    assert schema["parameters"]["properties"]["timeout"]["type"] == "integer"
    assert schema["parameters"]["properties"]["timeout"]["minimum"] == 1
    assert "session_id" not in json.dumps(schema)
    assert ctx.commands[0]["name"] == "orch"
    assert ctx.commands[0]["handler"]("") == ""
    assert ctx.hooks == []


def test_hermes_plugin_manifest_declares_tool_and_fail_closed_command() -> None:
    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["name"] == "orchestra"
    assert manifest["provides_tools"] == ["orch_dispatch"]
    assert manifest["provides_commands"] == ["orch"]


def test_hermes_plugin_uses_dynamic_tool_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    plugin = load_plugin()
    payload = {
        "description": "dynamic description",
        "goalDescription": "dynamic goal",
        "roleDescription": "dynamic role",
        "timeoutDescription": "dynamic timeout",
        "taskLabelDescription": "dynamic label",
    }
    monkeypatch.setattr(plugin, "_run_orchestra", lambda args: completed(args, json.dumps(payload)))
    ctx = FakeHermesPluginContext()

    plugin.register(ctx)

    schema = ctx.tools[0]["schema"]
    assert schema["description"] == "dynamic description"
    assert schema["parameters"]["properties"]["goal"]["description"] == "dynamic goal"
    assert schema["parameters"]["properties"]["taskLabel"]["description"] == "dynamic label"


def test_orch_slash_session_scoped_commands_fail_closed_without_trusted_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_tool-info":
            return completed(args, code=1)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext()
    plugin.register(ctx)
    calls.clear()

    for raw_args in [
        "do --role reviewer session_id attacker ship it",
        "status session_id attacker",
        "history 7 session_id attacker",
        "stop run-1 session_id attacker",
    ]:
        output = ctx.commands[0]["handler"](raw_args)
        assert "trusted runtime session context" in output

    assert calls == []


def test_orch_slash_doctor_help_are_sessionless_safe_wrappers_and_scoped_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return completed(args, "ok\n")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)

    assert plugin._orch_command("help") == "ok\n"
    assert plugin._orch_command("doctor") == "ok\n"
    assert "trusted runtime session context" in plugin._orch_command("status")
    assert "trusted runtime session context" in plugin._orch_command("history 7")
    assert "trusted runtime session context" in plugin._orch_command("stop run-1")

    assert calls == [
        ["help-host"],
        ["doctor"],
    ]


def test_orch_slash_fails_closed_without_hook_session_context() -> None:
    plugin = load_plugin()

    output = plugin._orch_command("status")

    assert "trusted runtime session context" in output


def test_hermes_plugin_source_does_not_trust_global_or_private_slash_session() -> None:
    source = PLUGIN_PATH.read_text(encoding="utf-8")

    assert "_CURRENT_SESSION_ID" not in source
    assert "on_session_start" not in source
    assert "on_session_reset" not in source
    assert "on_session_finalize" not in source
    assert "_cli_ref" not in source


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"session_id": ""}, {"session_id": "   "}, {"session_id": None}],
)
def test_orch_dispatch_rejects_missing_trusted_session_id(kwargs: dict[str, Any]) -> None:
    plugin = load_plugin()

    payload = json.loads(plugin.orch_dispatch({"goal": "do work"}, **kwargs))

    assert "error" in payload
    assert "session_id" in payload["error"]


@pytest.mark.parametrize("identity_arg", ["session_id", "identity", "orchestrator_session_id"])
def test_orch_dispatch_rejects_model_supplied_identity_args(identity_arg: str) -> None:
    plugin = load_plugin()

    payload = json.loads(
        plugin.orch_dispatch({"goal": "do work", identity_arg: "attacker"}, session_id="trusted")
    )

    assert payload == {
        "error": "identity arguments are not accepted; Hermes runtime session_id is used instead"
    }


@pytest.mark.parametrize("timeout", [1.5, "42", 0, -1, True])
def test_orch_dispatch_rejects_non_positive_integer_timeout(
    monkeypatch: pytest.MonkeyPatch,
    timeout: object,
) -> None:
    plugin = load_plugin()

    def fake_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)

    payload = json.loads(
        plugin.orch_dispatch({"goal": "do work", "timeout": timeout}, session_id="trusted")
    )

    assert payload == {"error": "timeout must be a positive integer"}


def test_orch_dispatch_builds_cli_args_from_trusted_kwargs_and_returns_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "do":
            return completed(args, "run_id: abc123\nstatus: queued\n")
        if args[0] == "_dispatch-ack":
            return completed(args, "orchestra dispatched: reviewer abc123\n")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)

    output = plugin.orch_dispatch(
        {
            "goal": "ship focused task",
            "role": "reviewer",
            "timeout": 42,
            "taskLabel": "review-task",
        },
        session_id="trusted-session",
    )

    assert calls == [
        [
            "do",
            "--session-id",
            "hermes:trusted-session",
            "--role",
            "reviewer",
            "--goal",
            "ship focused task",
            "--timeout",
            "42",
            "--task-label",
            "review-task",
        ],
        ["_dispatch-ack", "--run-id", "abc123", "--role", "reviewer"],
    ]
    assert output == "orchestra dispatched: reviewer abc123"


def test_orch_dispatch_requires_run_id_before_ack(monkeypatch: pytest.MonkeyPatch) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return completed(args, "status: queued\n")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)

    payload = json.loads(plugin.orch_dispatch({"goal": "do work"}, session_id="trusted"))

    assert calls == [
        ["do", "--session-id", "hermes:trusted", "--role", "worker", "--goal", "do work"]
    ]
    assert payload == {"error": "orchestra dispatch did not return a run_id"}


def test_registered_orch_dispatch_watches_injects_and_marks_report_delivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_tool-info":
            return completed(args, code=1)
        if args[0] == "do":
            return completed(args, "run_id: abc123\nstatus: queued\n")
        if args[0] == "_dispatch-ack":
            return completed(args, "orchestra dispatched: worker abc123\n")
        if args[0] == "_await-run":
            return completed(args, "status: done\nrole: worker\nactive_runs_remaining: 0\n")
        if args[0] == "_progress-message":
            return completed(args, "orchestra:worker abc123 returned done (1/1)\n")
        if args[0] == "_await-session-report":
            return completed(
                args,
                json.dumps({"runIds": ["abc123"], "report": "worker done"}),
            )
        if args[0] == "_mark-session-report-delivered":
            return completed(args)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext()
    plugin.register(ctx)

    output = ctx.tools[0]["handler"]({"goal": "do work"}, session_id="trusted")

    assert output == "orchestra dispatched: worker abc123"
    assert wait_for_condition(
        lambda: ctx.notifications == ["orchestra:worker abc123 returned done (1/1)"]
    )
    assert wait_for_condition(lambda: ctx.injected == [("worker done", "user")])
    assert [
        "_await-session-report",
        "--session-id",
        "hermes:trusted",
        "--run-id",
        "abc123",
        "--json",
    ] in calls
    assert [
        "_await-run",
        "--session-id",
        "hermes:trusted",
        "--run-id",
        "abc123",
    ] in calls
    assert [
        "_progress-message",
        "--completed",
        "1",
        "--total",
        "1",
        "--run-id",
        "abc123",
        "--status",
        "done",
        "--role",
        "worker",
    ] in calls
    assert [
        "_mark-session-report-delivered",
        "--session-id",
        "hermes:trusted",
        "--run-id",
        "abc123",
    ] in calls


def test_progress_without_notification_api_skips_inject_fallback_but_final_report_injects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "do":
            return completed(args, "run_id: abc123\nstatus: queued\n")
        if args[0] == "_dispatch-ack":
            return completed(args, "orchestra dispatched: worker abc123\n")
        if args[0] == "_await-session-report":
            return completed(
                args,
                json.dumps({"runIds": ["abc123"], "report": "worker done"}),
            )
        if args[0] == "_mark-session-report-delivered":
            return completed(args)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = InjectOnlyContext()

    output = plugin._dispatch_orchestra_run(
        {"goal": "do work"},
        "hermes:trusted",
        ctx=ctx,
    )

    assert output == "orchestra dispatched: worker abc123"
    assert wait_for_condition(lambda: ctx.injected == [("worker done", "user")])
    assert not any(args[0] == "_await-run" for args in calls)
    assert not any(args[0] == "_progress-message" for args in calls)
    assert [
        "_await-session-report",
        "--session-id",
        "hermes:trusted",
        "--run-id",
        "abc123",
        "--json",
    ] in calls


def test_session_report_injection_failure_releases_without_marking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_release-session-report":
            return completed(args)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext()
    ctx.inject_success = False

    plugin._handle_session_report_result(
        ctx,
        "hermes:trusted",
        completed(
            ["_await-session-report"],
            json.dumps({"runIds": ["abc123"], "report": "worker done"}),
        ),
    )

    assert ctx.injected == [("worker done", "user")]
    assert calls == [
        [
            "_release-session-report",
            "--session-id",
            "hermes:trusted",
            "--run-id",
            "abc123",
        ]
    ]


def test_session_report_mark_failure_releases_for_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_mark-session-report-delivered":
            return completed(args, stderr="mark failed", code=1)
        if args[0] == "_release-session-report":
            return completed(args)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext()

    plugin._handle_session_report_result(
        ctx,
        "hermes:trusted",
        completed(
            ["_await-session-report"],
            json.dumps({"runIds": ["abc123"], "report": "worker done"}),
        ),
    )

    assert ctx.injected == [("worker done", "user")]
    assert calls == [
        [
            "_mark-session-report-delivered",
            "--session-id",
            "hermes:trusted",
            "--run-id",
            "abc123",
        ],
        [
            "_release-session-report",
            "--session-id",
            "hermes:trusted",
            "--run-id",
            "abc123",
        ],
    ]


def test_session_report_malformed_json_releases_fallback_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str]) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_release-session-report":
            return completed(args)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)

    plugin._handle_session_report_result(
        FakeHermesPluginContext(),
        "hermes:trusted",
        completed(["_await-session-report"], "{not json"),
        ["abc123"],
    )

    assert calls == [
        [
            "_release-session-report",
            "--session-id",
            "hermes:trusted",
            "--run-id",
            "abc123",
        ]
    ]


def test_run_orchestra_uses_bounded_subprocess_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    plugin = load_plugin()
    calls: list[dict[str, Any]] = []

    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"args": args, **kwargs})
        return completed(args)

    monkeypatch.setattr(plugin.subprocess, "run", fake_run)

    result = plugin._run_orchestra(["_tool-info"])

    assert result.returncode == 0
    assert calls == [
        {
            "args": ["orchestra", "_tool-info"],
            "check": False,
            "capture_output": True,
            "text": True,
            "timeout": plugin._SUBPROCESS_TIMEOUT_SECONDS,
        }
    ]
