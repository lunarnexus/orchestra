from __future__ import annotations

import ast
import builtins
import importlib.util
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace
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
    def __init__(self, session_id: str | None = None, *, agent_running: bool = False) -> None:
        self.tools: list[dict[str, Any]] = []
        self.commands: list[dict[str, Any]] = []
        self.hooks: list[tuple[str, Any]] = []
        self.injected: list[tuple[str, str]] = []
        self.steered: list[str] = []
        self.inject_success = True
        self.steer_success = True
        self.pending_input: queue.Queue[str] = queue.Queue()

        def steer(content: str) -> bool:
            self.steered.append(content)
            return self.steer_success

        self._manager = SimpleNamespace(
            _cli_ref=SimpleNamespace(
                session_id=session_id,
                agent=SimpleNamespace(steer=steer),
                _agent_running=agent_running,
                _pending_input=self.pending_input,
            )
        )

    def register_tool(self, **kwargs: Any) -> None:
        self.tools.append(kwargs)

    def register_command(self, name: str, **kwargs: Any) -> None:
        self.commands.append({"name": name, **kwargs})

    def register_hook(self, name: str, handler: Any) -> None:
        self.hooks.append((name, handler))

    def inject_message(self, content: str, role: str = "user") -> bool:
        self.injected.append((content, role))
        return self.inject_success


class InjectOnlyContext:
    def __init__(self) -> None:
        self.injected: list[tuple[str, str]] = []

    def inject_message(self, content: str, role: str = "user") -> bool:
        self.injected.append((content, role))
        return True


class NoInjectHermesPluginContext:
    def __init__(self, session_id: str | None = None) -> None:
        self.tools: list[dict[str, Any]] = []
        self.commands: list[dict[str, Any]] = []
        self.hooks: list[tuple[str, Any]] = []
        self.injected: list[tuple[str, str]] = []
        self._manager = SimpleNamespace(
            _cli_ref=SimpleNamespace(
                session_id=session_id,
                agent=SimpleNamespace(steer=lambda content: True),
                _agent_running=False,
            )
        )

    def register_tool(self, **kwargs: Any) -> None:
        self.tools.append(kwargs)

    def register_command(self, name: str, **kwargs: Any) -> None:
        self.commands.append({"name": name, **kwargs})

    def register_hook(self, name: str, handler: Any) -> None:
        self.hooks.append((name, handler))


class RegistrationOnlyContext:
    def __init__(self) -> None:
        self.tools: list[dict[str, Any]] = []
        self.commands: list[dict[str, Any]] = []

    def register_tool(self, **kwargs: Any) -> None:
        self.tools.append(kwargs)

    def register_command(self, name: str, **kwargs: Any) -> None:
        self.commands.append({"name": name, **kwargs})


def completed(
    args: list[str],
    stdout: str = "",
    stderr: str = "",
    code: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=args, returncode=code, stdout=stdout, stderr=stderr)


def make_tool_info_payload() -> dict[str, Any]:
    return {
        "description": "dynamic description",
        "promptSnippet": "dynamic prompt snippet",
        "promptGuidelines": ["guideline one", "guideline two"],
        "goalDescription": "dynamic goal",
        "roleDescription": "dynamic role",
        "taskLabelDescription": "dynamic label",
        "statusDescription": "dynamic status",
        "statusActionDescription": "dynamic action",
        "statusLimitDescription": "dynamic limit",
        "statusRunIdDescription": "dynamic run id",
        "statusRoleDescription": "dynamic status role",
        "statusSettingDescription": "dynamic status setting",
        "statusValueDescription": "dynamic status value",
        "dispatchTimeoutError": "dynamic timeout error",
        "budgetTriggerLabel": "dynamic budget trigger label",
        "softTimeoutBlockReason": "dynamic soft timeout block reason",
        "toolsEnabledByDefault": True,
        "mainSessionMode": "on",
    }


def test_hermes_tool_info_loads_only_from_dynamic_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    plugin = load_plugin()
    payload = {"description": "dynamic", "goalDescription": "goal", "statusDescription": "status"}
    monkeypatch.setattr(plugin, "_run_orchestra", lambda args: completed(args, json.dumps(payload)))

    assert plugin._load_tool_info() == payload


@pytest.fixture(autouse=True)
def _clear_orchestra_dispatch_budget_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORCHESTRA_DISPATCH_BUDGET", raising=False)


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

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if args[0] == "_tool-info":
            return completed(args, json.dumps(make_tool_info_payload()))
        return completed(args)

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext()

    plugin.register(ctx)

    assert [tool["name"] for tool in ctx.tools] == ["orch_dispatch", "orch_status"]
    schema = ctx.tools[0]["schema"]
    assert set(schema["parameters"]["properties"]) == {"goal", "role", "taskLabel"}
    assert "timeout" not in schema["parameters"]["properties"]
    assert "session_id" not in json.dumps(schema)
    assert ctx.commands[0]["name"] == "orch"
    assert "/orch on" in ctx.commands[0]["description"]
    assert "on" in ctx.commands[0]["args_hint"]
    assert "do" in ctx.commands[0]["args_hint"]
    assert "--role" in ctx.commands[0]["args_hint"]
    assert "--timeout" in ctx.commands[0]["args_hint"]
    assert "--task-label" in ctx.commands[0]["args_hint"]
    assert "status" in ctx.commands[0]["args_hint"]
    assert "history" in ctx.commands[0]["args_hint"]
    assert "stop" in ctx.commands[0]["args_hint"]
    assert "doctor" in ctx.commands[0]["args_hint"]
    assert "roles" in ctx.commands[0]["args_hint"]
    assert ctx.commands[0]["handler"]("") == ""
    assert [name for name, _ in ctx.hooks] == [
        "on_session_finalize",
        "on_session_reset",
        "on_session_start",
        "pre_tool_call",
        "pre_llm_call",
    ]


@pytest.mark.parametrize("budget", [None, "0", "2", "3"])
def test_hermes_plugin_registers_orch_status_tool_with_tool_info_metadata(
    monkeypatch: pytest.MonkeyPatch,
    budget: str | None,
) -> None:
    plugin = load_plugin()
    if budget is not None:
        monkeypatch.setenv("ORCHESTRA_DISPATCH_BUDGET", budget)

    payload = {
        "description": "dynamic description",
        "promptSnippet": "dynamic prompt snippet",
        "promptGuidelines": ["guideline one", "guideline two"],
        "goalDescription": "dynamic goal",
        "roleDescription": "dynamic role",
        "taskLabelDescription": "dynamic label",
        "statusDescription": "dynamic status",
        "statusActionDescription": "dynamic action",
        "statusLimitDescription": "dynamic limit",
        "statusRunIdDescription": "dynamic run id",
        "statusRoleDescription": "dynamic status role",
        "statusSettingDescription": "dynamic status setting",
        "statusValueDescription": "dynamic status value",
        "dispatchTimeoutError": "dynamic timeout error",
        "budgetTriggerLabel": "Budget trigger",
        "softTimeoutBlockReason": "Orchestra soft timeout reached; return budget handoff",
    }
    monkeypatch.setattr(plugin, "_run_orchestra", lambda args: completed(args, json.dumps(payload)))
    ctx = FakeHermesPluginContext()

    plugin.register(ctx)

    expected_tools = ["orch_status"] if budget == "1" else ["orch_dispatch", "orch_status"]
    assert [tool["name"] for tool in ctx.tools] == expected_tools
    status_tool = next(tool for tool in ctx.tools if tool["name"] == "orch_status")
    schema = status_tool["schema"]
    assert schema["name"] == "orch_status"
    assert schema["description"] == "dynamic status"
    assert set(schema["parameters"]["properties"]) == {
        "action",
        "limit",
        "runId",
        "role",
        "setting",
        "value",
    }
    assert schema["parameters"]["properties"]["action"]["description"] == "dynamic action"
    assert schema["parameters"]["properties"]["limit"]["description"] == "dynamic limit"
    assert schema["parameters"]["properties"]["runId"]["description"] == "dynamic run id"
    assert schema["parameters"]["properties"]["role"]["description"] == "dynamic status role"
    assert schema["parameters"]["properties"]["setting"]["description"] == "dynamic status setting"
    assert schema["parameters"]["properties"]["value"]["description"] == "dynamic status value"
    assert schema["parameters"]["required"] == ["action"]
    assert "session_id" not in json.dumps(schema)


def test_hermes_plugin_session_cleanup_hooks_clear_matching_report_watcher_state() -> None:
    plugin = load_plugin()
    ctx = FakeHermesPluginContext(session_id="runtime")
    plugin._REPORT_WATCHERS.clear()
    plugin._REPORT_WATCHERS.update({"hermes:runtime", "hermes:other"})

    plugin.register(ctx)
    hooks = dict(ctx.hooks)
    assert "on_session_end" not in hooks
    cleanup = hooks["on_session_finalize"]

    cleanup(session_id="runtime")
    assert plugin._REPORT_WATCHERS == {"hermes:other"}

    cleanup()
    cleanup(session_id=None)
    cleanup(session_id="")
    cleanup(session_id=object())
    assert plugin._REPORT_WATCHERS == {"hermes:other"}


@pytest.mark.parametrize("action", ["status", "history", "stop", "roles", "on"])
def test_hermes_orch_status_routes_session_actions_and_keeps_roles_read_only(
    action: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    tool_info_payload = make_tool_info_payload()

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_tool-info":
            return completed(args, json.dumps(tool_info_payload))
        if args[0] == "status":
            return completed(args, "status output\n")
        if args[0] == "history":
            return completed(args, "history output\n")
        if args[0] == "stop":
            return completed(args, "stop output\n")
        if args[0] == "doctor":
            return completed(args, "doctor output\n")
        if args[0] == "help-host":
            return completed(args, "help output\n")
        if args[0] == "roles":
            return completed(
                args,
                "Configured roles\nDefault: builder\n\n"
                "  D  builder [pi]\n"
                "      env: SECRET=hidden\n"
                "  ✓  reviewer [hermes]\n"
                "      model: gpt\n",
            )
        if args[0] == "_session-mode":
            return completed(args)
        if args[0] == "_orchestrator-skill":
            return completed(args, "orchestrator skill payload\n")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext(session_id="runtime")
    plugin.register(ctx)
    handler = next(tool["handler"] for tool in ctx.tools if tool["name"] == "orch_status")

    assert handler({"action": "status"}, session_id="runtime") == "status output\n"
    assert handler({"action": "history", "limit": 7}, session_id="runtime") == "history output\n"
    assert handler({"action": "doctor"}) == "doctor output\n"
    assert handler({"action": "help"}) == "help output\n"
    assert handler(
        {"action": "roles", "role": "reviewer", "setting": "enabled", "value": "false"}
    ) == (
        "Configured roles\nDefault: builder\n\n  D  builder [pi]\n"
        "      env: SECRET=hidden\n  ✓  reviewer [hermes]\n"
        "      model: gpt"
    )
    assert handler({"action": "on"}, session_id="runtime") == (
        "Hermes /orch on succeeded: orchestrator skill injected"
    )
    assert handler({"action": "stop", "runId": "run-1"}, session_id="runtime") == (
        "stop output\n"
    )

    assert calls == [
        ["_tool-info", "--session-id", "hermes:runtime"],
        ["_tool-info"],
        ["status", "--session-id", "hermes:runtime"],
        ["history", "--session-id", "hermes:runtime", "--limit", "7"],
        ["doctor"],
        ["help-host"],
        ["roles", "--all"],
        ["_orchestrator-skill"],
        ["_session-mode", "set", "--session-id", "hermes:runtime", "--mode", "orchestrator"],
        ["stop", "--session-id", "hermes:runtime", "--run-id", "run-1"],
    ]
    assert ctx.injected == [("orchestrator skill payload", "user")]


@pytest.mark.parametrize("action", ["status", "history", "stop", "on"])
def test_hermes_orch_status_rejects_model_supplied_identity_args(
    action: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_tool-info":
            return completed(args, json.dumps(make_tool_info_payload()))
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext(session_id="runtime")
    plugin.register(ctx)
    handler = next(tool["handler"] for tool in ctx.tools if tool["name"] == "orch_status")

    output = handler({"action": action, "session_id": "attacker"}, session_id="runtime")

    assert "identity arguments are not accepted" in output
    assert calls == [
        ["_tool-info", "--session-id", "hermes:runtime"],
        ["_tool-info"],
    ]


def test_hermes_orch_status_requires_run_id_for_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_tool-info":
            return completed(args, json.dumps(make_tool_info_payload()))
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext(session_id="runtime")
    plugin.register(ctx)
    handler = next(tool["handler"] for tool in ctx.tools if tool["name"] == "orch_status")

    output = handler({"action": "stop"}, session_id="runtime")

    assert "runId is required" in output
    assert calls == [
        ["_tool-info", "--session-id", "hermes:runtime"],
        ["_tool-info"],
    ]


def test_hermes_plugin_session_report_watcher_suppresses_late_delivery_after_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []
    started = threading.Event()
    release = threading.Event()
    done = threading.Event()

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_await-session-report":
            started.set()
            assert release.wait(5)
            return completed(
                args,
                json.dumps({"runIds": ["abc123"], "report": "worker done"}),
            )
        raise AssertionError(f"unexpected command: {args}")

    original_watch = plugin._watch_session_report

    def wrapped_watch(*args: Any, **kwargs: Any) -> None:
        try:
            original_watch(*args, **kwargs)
        finally:
            done.set()

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    monkeypatch.setattr(plugin, "_watch_session_report", wrapped_watch)
    ctx = FakeHermesPluginContext(session_id="runtime")

    plugin._start_session_report_watcher(ctx, "hermes:runtime", "abc123", 35)
    assert started.wait(5)

    plugin._on_session_cleanup(session_id="runtime")
    release.set()

    assert wait_for_condition(lambda: done.is_set())
    assert calls == [
        [
            "_await-session-report",
            "--session-id",
            "hermes:runtime",
            "--run-id",
            "abc123",
            "--timeout",
            "35",
            "--json",
        ]
    ]
    assert ctx.injected == []
    assert ctx.steered == []


@pytest.mark.parametrize(
    ("budget", "registered_tools"),
    [
        (None, ["orch_dispatch", "orch_status"]),
        ("0", ["orch_dispatch", "orch_status"]),
        ("1", ["orch_status"]),
        ("2", ["orch_dispatch", "orch_status"]),
        ("3", ["orch_dispatch", "orch_status"]),
    ],
)
def test_hermes_plugin_gates_dispatch_tool_by_nested_dispatch_depth(
    monkeypatch: pytest.MonkeyPatch,
    budget: str | None,
    registered_tools: list[str],
) -> None:
    plugin = load_plugin()
    if budget is not None:
        monkeypatch.setenv("ORCHESTRA_DISPATCH_BUDGET", budget)
    monkeypatch.setattr(
        plugin, "_run_orchestra", lambda args: completed(args, json.dumps(make_tool_info_payload()))
    )
    ctx = FakeHermesPluginContext()

    plugin.register(ctx)

    assert [tool["name"] for tool in ctx.tools] == registered_tools
    assert [command["name"] for command in ctx.commands] == ["orch"]


@pytest.mark.parametrize(
    ("env_name", "raw_budget", "expected"),
    [
        ("ORCHESTRA_TURN_BUDGET", None, 0),
        ("ORCHESTRA_TURN_BUDGET", "0", 0),
        ("ORCHESTRA_TURN_BUDGET", "-1", 1),
        ("ORCHESTRA_SOFT_TIMEOUT_SECONDS", "   ", 0),
        ("ORCHESTRA_SOFT_TIMEOUT_SECONDS", "3", 3),
        ("ORCHESTRA_SOFT_TIMEOUT_SECONDS", "bogus", 1),
    ],
)
def test_parse_budget_env_matches_pi_rules(
    monkeypatch: pytest.MonkeyPatch,
    env_name: str,
    raw_budget: str | None,
    expected: int,
) -> None:
    plugin = load_plugin()
    monkeypatch.delenv(env_name, raising=False)
    if raw_budget is not None:
        monkeypatch.setenv(env_name, raw_budget)

    assert plugin._parse_budget_env(env_name) == expected


def test_hermes_plugin_pre_tool_call_blocks_after_soft_timeout_and_injects_prompt_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    clock = {"value": 100.0}
    monkeypatch.setattr(plugin.time, "monotonic", lambda: clock["value"])
    monkeypatch.setenv("ORCHESTRA_SOFT_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("ORCHESTRA_BUDGET_EXCEEDED_PROMPT", "Budget handoff")
    ctx = FakeHermesPluginContext(session_id="runtime-a")

    plugin.register(ctx)
    pre_tool_call = dict(ctx.hooks)["pre_tool_call"]
    clock["value"] = 102.0

    expected = {
        "action": "block",
        "message": "Orchestra soft timeout reached; return budget handoff",
    }
    assert pre_tool_call() == expected
    assert pre_tool_call() == expected
    assert ctx.injected == [("Budget handoff\n\nBudget trigger: soft_timeout", "user")]


def test_hermes_plugin_pre_tool_call_blocks_without_budget_prompt_without_injection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    clock = {"value": 100.0}
    monkeypatch.setattr(plugin.time, "monotonic", lambda: clock["value"])
    monkeypatch.setenv("ORCHESTRA_SOFT_TIMEOUT_SECONDS", "1")
    monkeypatch.delenv("ORCHESTRA_BUDGET_EXCEEDED_PROMPT", raising=False)
    ctx = FakeHermesPluginContext(session_id="runtime-a")

    plugin.register(ctx)
    pre_tool_call = dict(ctx.hooks)["pre_tool_call"]
    clock["value"] = 102.0

    assert pre_tool_call() == {
        "action": "block",
        "message": "Orchestra soft timeout reached; return budget handoff",
    }
    assert ctx.injected == []


def test_hermes_plugin_budget_texts_come_from_dynamic_tool_info_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    clock = {"value": 100.0}
    monkeypatch.setattr(plugin.time, "monotonic", lambda: clock["value"])
    monkeypatch.setenv("ORCHESTRA_SOFT_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("ORCHESTRA_BUDGET_EXCEEDED_PROMPT", "Budget handoff")
    payload = make_tool_info_payload()
    monkeypatch.setattr(
        plugin, "_run_orchestra", lambda args: completed(args, json.dumps(payload))
    )
    ctx = FakeHermesPluginContext(session_id="runtime-a")

    plugin.register(ctx)
    pre_tool_call = dict(ctx.hooks)["pre_tool_call"]
    clock["value"] = 102.0

    assert pre_tool_call() == {
        "action": "block",
        "message": payload["softTimeoutBlockReason"],
    }
    assert ctx.injected == [
        (f"Budget handoff\n\n{payload['budgetTriggerLabel']}: soft_timeout", "user")
    ]


def test_hermes_plugin_pre_llm_call_decrements_turn_budget_and_injects_prompt_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    monkeypatch.setenv("ORCHESTRA_TURN_BUDGET", "2")
    monkeypatch.setenv("ORCHESTRA_BUDGET_EXCEEDED_PROMPT", "Budget handoff")
    ctx = FakeHermesPluginContext(session_id="runtime-a")

    plugin.register(ctx)
    pre_llm_call = dict(ctx.hooks)["pre_llm_call"]

    assert pre_llm_call() is None
    assert os.environ["ORCHESTRA_TURN_BUDGET"] == "2"
    assert pre_llm_call() is None
    assert os.environ["ORCHESTRA_TURN_BUDGET"] == "2"
    assert ctx.injected == [("Budget handoff\n\nBudget trigger: turn_limit", "user")]


def test_hermes_plugin_pre_llm_call_falls_back_to_context_when_injection_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    monkeypatch.setenv("ORCHESTRA_TURN_BUDGET", "1")
    monkeypatch.setenv("ORCHESTRA_BUDGET_EXCEEDED_PROMPT", "Budget handoff")
    ctx = NoInjectHermesPluginContext(session_id="runtime-a")

    plugin.register(ctx)
    pre_llm_call = dict(ctx.hooks)["pre_llm_call"]

    assert pre_llm_call() == {"context": "Budget handoff\n\nBudget trigger: turn_limit"}
    assert pre_llm_call() is None
    assert os.environ["ORCHESTRA_TURN_BUDGET"] == "1"
    assert ctx.injected == []


def test_hermes_plugin_session_start_resets_only_requested_budget_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    monkeypatch.setenv("ORCHESTRA_TURN_BUDGET", "1")
    monkeypatch.setenv("ORCHESTRA_BUDGET_EXCEEDED_PROMPT", "Budget handoff")
    ctx = FakeHermesPluginContext()

    plugin.register(ctx)
    hooks = dict(ctx.hooks)
    pre_llm_call = hooks["pre_llm_call"]
    on_session_start = hooks["on_session_start"]

    assert pre_llm_call(session_id="runtime-a") is None
    assert pre_llm_call(session_id="runtime-b") is None
    assert ctx.injected == [
        ("Budget handoff\n\nBudget trigger: turn_limit", "user"),
        ("Budget handoff\n\nBudget trigger: turn_limit", "user"),
    ]

    on_session_start(session_id="runtime-a")

    assert pre_llm_call(session_id="runtime-b") is None
    assert pre_llm_call(session_id="runtime-a") is None
    assert ctx.injected == [
        ("Budget handoff\n\nBudget trigger: turn_limit", "user"),
        ("Budget handoff\n\nBudget trigger: turn_limit", "user"),
        ("Budget handoff\n\nBudget trigger: turn_limit", "user"),
    ]


def test_hermes_register_disables_dispatch_when_core_session_mode_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    payload = make_tool_info_payload()
    payload["mainSessionMode"] = "off"

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(args))
        if args[0] == "_tool-info":
            return completed(args, json.dumps(payload))
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext(session_id="runtime-a")

    plugin.register(ctx)

    assert ["_tool-info", "--session-id", "hermes:runtime-a"] in calls
    assert plugin._orch_dispatch_is_disabled("hermes:runtime-a")


def test_hermes_on_session_start_disables_dispatch_when_core_session_mode_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    payload = make_tool_info_payload()
    payload["mainSessionMode"] = "off"

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(args))
        if args[0] == "_tool-info":
            return completed(args, json.dumps(payload))
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext()

    plugin.register(ctx)
    on_session_start = dict(ctx.hooks)["on_session_start"]

    assert not plugin._orch_dispatch_is_disabled("hermes:runtime-b")
    on_session_start(session_id="runtime-b")

    assert ["_tool-info", "--session-id", "hermes:runtime-b"] in calls
    assert plugin._orch_dispatch_is_disabled("hermes:runtime-b")


@pytest.mark.parametrize("mode", ["on", "orchestrator"])
def test_hermes_session_start_keeps_dispatch_enabled_for_non_off_modes(
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    payload = make_tool_info_payload()
    payload["mainSessionMode"] = mode

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(args))
        if args[0] == "_tool-info":
            return completed(args, json.dumps(payload))
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext(session_id="runtime-a")

    plugin.register(ctx)
    on_session_start = dict(ctx.hooks)["on_session_start"]
    on_session_start()

    assert ["_tool-info", "--session-id", "hermes:runtime-a"] in calls
    assert not plugin._orch_dispatch_is_disabled("hermes:runtime-a")


def test_hermes_register_falls_back_to_enabled_when_core_tool_info_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if args[0] == "_tool-info" and "--session-id" in args:
            return completed(args, stderr="core unavailable", code=1)
        if args[0] == "_tool-info":
            return completed(args, json.dumps(make_tool_info_payload()))
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext(session_id="runtime-a")

    plugin.register(ctx)

    assert not plugin._orch_dispatch_is_disabled("hermes:runtime-a")


def test_hermes_register_falls_back_to_enabled_when_core_call_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if args[0] == "_tool-info" and "--session-id" in args:
            raise RuntimeError("core call exploded")
        if args[0] == "_tool-info":
            return completed(args, json.dumps(make_tool_info_payload()))
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext(session_id="runtime-a")

    plugin.register(ctx)

    assert not plugin._orch_dispatch_is_disabled("hermes:runtime-a")


def test_hermes_plugin_session_cleanup_clears_only_requested_budget_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    monkeypatch.setenv("ORCHESTRA_TURN_BUDGET", "1")
    monkeypatch.setenv("ORCHESTRA_BUDGET_EXCEEDED_PROMPT", "Budget handoff")
    ctx = FakeHermesPluginContext()

    plugin.register(ctx)
    pre_llm_call = dict(ctx.hooks)["pre_llm_call"]

    assert pre_llm_call(session_id="runtime-a") is None
    assert pre_llm_call(session_id="runtime-b") is None

    plugin._on_session_cleanup(session_id="runtime-a")

    assert pre_llm_call(session_id="runtime-b") is None
    assert pre_llm_call(session_id="runtime-a") is None
    assert ctx.injected == [
        ("Budget handoff\n\nBudget trigger: turn_limit", "user"),
        ("Budget handoff\n\nBudget trigger: turn_limit", "user"),
        ("Budget handoff\n\nBudget trigger: turn_limit", "user"),
    ]


def test_hermes_plugin_budget_hooks_fail_closed_without_trusted_session_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    clock = {"value": 100.0}
    monkeypatch.setattr(plugin.time, "monotonic", lambda: clock["value"])
    monkeypatch.setenv("ORCHESTRA_TURN_BUDGET", "1")
    monkeypatch.setenv("ORCHESTRA_SOFT_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("ORCHESTRA_BUDGET_EXCEEDED_PROMPT", "Budget handoff")
    ctx = FakeHermesPluginContext()

    plugin.register(ctx)
    hooks = dict(ctx.hooks)
    pre_llm_call = hooks["pre_llm_call"]
    pre_tool_call = hooks["pre_tool_call"]
    clock["value"] = 102.0

    assert pre_llm_call() is None
    assert pre_tool_call() is None
    assert ctx.injected == []


def test_hermes_plugin_manifest_declares_tool_and_fail_closed_command() -> None:
    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["name"] == "orchestra"
    assert manifest["provides_tools"] == ["orch_dispatch", "orch_status"]
    assert manifest["provides_commands"] == ["orch"]


def test_hermes_plugin_uses_dynamic_tool_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    plugin = load_plugin()
    payload = {
        "description": "dynamic description",
        "promptSnippet": "dynamic prompt snippet",
        "promptGuidelines": ["guideline one"],
        "goalDescription": "dynamic goal",
        "roleDescription": "dynamic role",
        "taskLabelDescription": "dynamic label",
        "statusDescription": "dynamic status",
        "statusActionDescription": "dynamic action",
        "statusLimitDescription": "dynamic limit",
        "statusRunIdDescription": "dynamic run id",
        "statusRoleDescription": "dynamic status role",
        "statusSettingDescription": "dynamic status setting",
        "statusValueDescription": "dynamic status value",
        "dispatchTimeoutError": "dynamic timeout error",
        "budgetTriggerLabel": "Budget trigger",
        "softTimeoutBlockReason": "Orchestra soft timeout reached; return budget handoff",
    }
    monkeypatch.setattr(plugin, "_run_orchestra", lambda args: completed(args, json.dumps(payload)))
    ctx = FakeHermesPluginContext()

    plugin.register(ctx)

    schema = ctx.tools[0]["schema"]
    assert schema["description"] == "dynamic description"
    assert schema["parameters"]["properties"]["goal"]["description"] == "dynamic goal"
    assert schema["parameters"]["properties"]["taskLabel"]["description"] == "dynamic label"


def test_orch_slash_session_scoped_commands_fail_closed_without_runtime_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_tool-info":
            return completed(args, json.dumps(make_tool_info_payload()))
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
        "on session_id attacker",
    ]:
        output = ctx.commands[0]["handler"](raw_args)
        assert "runtime session context" in output

    assert calls == []


def test_orch_slash_on_injects_orchestrator_skill_into_current_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_tool-info":
            return completed(args, json.dumps(make_tool_info_payload()))
        if args[0] == "_session-mode":
            return completed(args)
        if args[0] == "_orchestrator-skill":
            return completed(args, "orchestrator skill payload\n")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext(session_id="cli-session")
    plugin.register(ctx)
    calls.clear()

    output = ctx.commands[0]["handler"]("on")

    assert output == "Hermes /orch on succeeded: orchestrator skill injected"
    assert calls == [
        ["_orchestrator-skill"],
        ["_session-mode", "set", "--session-id", "hermes:cli-session", "--mode", "orchestrator"],
    ]
    assert ctx.injected == [("orchestrator skill payload", "user")]


def test_orch_slash_on_is_idempotent_per_session_and_cleared_on_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_tool-info":
            return completed(args, json.dumps(make_tool_info_payload()))
        if args[0] == "_session-mode":
            return completed(args)
        if args[0] == "_orchestrator-skill":
            return completed(args, "orchestrator skill payload\n")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext(session_id="cli-session")
    plugin.register(ctx)
    calls.clear()
    handler = ctx.commands[0]["handler"]

    assert handler("on") == "Hermes /orch on succeeded: orchestrator skill injected"
    assert handler("on") == "Hermes /orch on already active for this session"
    plugin._on_session_cleanup(session_id="cli-session")
    assert handler("on") == "Hermes /orch on succeeded: orchestrator skill injected"

    mode_call = [
        "_session-mode",
        "set",
        "--session-id",
        "hermes:cli-session",
        "--mode",
        "orchestrator",
    ]
    assert calls == [
        ["_orchestrator-skill"],
        mode_call,
        ["_orchestrator-skill"],
        mode_call,
    ]
    assert ctx.injected == [
        ("orchestrator skill payload", "user"),
        ("orchestrator skill payload", "user"),
    ]


def test_orch_slash_off_disables_dispatch_until_reenabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_tool-info":
            return completed(args, json.dumps(make_tool_info_payload()))
        if args[0] == "_session-mode":
            return completed(args)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext(session_id="cli-session")
    plugin.register(ctx)
    calls.clear()
    slash_handler = ctx.commands[0]["handler"]
    dispatch_handler = next(
        tool["handler"] for tool in ctx.tools if tool["name"] == "orch_dispatch"
    )

    assert slash_handler("off") == (
        "Hermes /orch off succeeded: Orchestra dispatch disabled for this session"
    )
    assert dispatch_handler({"goal": "do work"}, session_id="cli-session") == json.dumps(
        {
            "error": (
                "Hermes orch_dispatch is disabled for this session; "
                "run /orch on to enable it again"
            )
        }
    )
    assert calls == [
        ["_session-mode", "set", "--session-id", "hermes:cli-session", "--mode", "off"],
    ]


def test_orch_slash_on_after_off_requires_second_call_to_inject_skill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_tool-info":
            return completed(args, json.dumps(make_tool_info_payload()))
        if args[0] == "_session-mode":
            return completed(args)
        if args[0] == "_orchestrator-skill":
            return completed(args, "orchestrator skill payload\n")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext(session_id="cli-session")
    plugin.register(ctx)
    calls.clear()
    handler = ctx.commands[0]["handler"]

    assert handler("off") == (
        "Hermes /orch off succeeded: Orchestra dispatch disabled for this session"
    )
    assert handler("on") == (
        "Hermes /orch on succeeded: Orchestra dispatch enabled for this session. "
        'Run "/orch on" again to inject the orchestrator skill'
    )
    assert handler("on") == "Hermes /orch on succeeded: orchestrator skill injected"

    assert calls == [
        ["_session-mode", "set", "--session-id", "hermes:cli-session", "--mode", "off"],
        ["_session-mode", "set", "--session-id", "hermes:cli-session", "--mode", "on"],
        ["_orchestrator-skill"],
        [
            "_session-mode",
            "set",
            "--session-id",
            "hermes:cli-session",
            "--mode",
            "orchestrator",
        ],
    ]
    assert ctx.injected == [("orchestrator skill payload", "user")]


def test_orch_slash_off_records_session_mode_off_in_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_tool-info":
            return completed(args, json.dumps(make_tool_info_payload()))
        if args[0] == "_session-mode":
            return completed(args)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext(session_id="cli-session")
    plugin.register(ctx)
    calls.clear()

    output = ctx.commands[0]["handler"]("off")

    assert output == (
        "Hermes /orch off succeeded: Orchestra dispatch disabled for this session"
    )
    assert calls == [
        ["_session-mode", "set", "--session-id", "hermes:cli-session", "--mode", "off"],
    ]


@pytest.mark.parametrize("scenario", ["nonzero_exit", "raises"])
def test_orch_slash_off_keeps_success_echo_and_warns_when_core_write_fails(
    scenario: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if args[0] == "_tool-info":
            return completed(args, json.dumps(make_tool_info_payload()))
        if args[0] == "_session-mode":
            if scenario == "raises":
                raise RuntimeError("core unavailable")
            return completed(args, stderr="mode write failed\n", code=1)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext(session_id="cli-session")
    plugin.register(ctx)

    output = ctx.commands[0]["handler"]("off")

    assert output.startswith(
        "Hermes /orch off succeeded: Orchestra dispatch disabled for this session"
    )
    assert "could not record session mode in core" in output


def test_orch_slash_on_first_enable_records_mode_before_local_dispatch_enablement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []
    mode_write_seen_disabled: bool | None = None

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal mode_write_seen_disabled
        calls.append(args)
        if args[0] == "_tool-info":
            return completed(args, json.dumps(make_tool_info_payload()))
        if args[0] == "_session-mode":
            mode_write_seen_disabled = plugin._orch_dispatch_is_disabled("hermes:cli-session")
            return completed(args)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext(session_id="cli-session")
    plugin.register(ctx)
    calls.clear()
    plugin._orch_dispatch_disable("hermes:cli-session")

    output = ctx.commands[0]["handler"]("on")

    assert output == (
        "Hermes /orch on succeeded: Orchestra dispatch enabled for this session. "
        'Run "/orch on" again to inject the orchestrator skill'
    )
    assert calls == [
        ["_session-mode", "set", "--session-id", "hermes:cli-session", "--mode", "on"],
    ]
    assert mode_write_seen_disabled is True


def test_orch_status_tool_on_action_records_core_session_mode_through_same_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []
    mode_write_seen_disabled: bool | None = None

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal mode_write_seen_disabled
        calls.append(args)
        if args[0] == "_tool-info":
            return completed(args, json.dumps(make_tool_info_payload()))
        if args[0] == "_session-mode":
            mode_write_seen_disabled = plugin._orch_dispatch_is_disabled("hermes:runtime")
            return completed(args)
        if args[0] == "_orchestrator-skill":
            return completed(args, "orchestrator skill payload\n")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext(session_id="runtime")
    plugin.register(ctx)
    calls.clear()
    handler = next(tool["handler"] for tool in ctx.tools if tool["name"] == "orch_status")
    plugin._orch_dispatch_disable("hermes:runtime")

    assert handler({"action": "on"}, session_id="runtime") == (
        "Hermes /orch on succeeded: Orchestra dispatch enabled for this session. "
        'Run "/orch on" again to inject the orchestrator skill'
    )
    assert mode_write_seen_disabled is True
    assert calls == [
        ["_session-mode", "set", "--session-id", "hermes:runtime", "--mode", "on"],
    ]

    output = handler({"action": "on"}, session_id="runtime")

    assert output == "Hermes /orch on succeeded: orchestrator skill injected"
    assert calls[-2:] == [
        ["_orchestrator-skill"],
        ["_session-mode", "set", "--session-id", "hermes:runtime", "--mode", "orchestrator"],
    ]
    assert ctx.injected == [("orchestrator skill payload", "user")]


def test_orch_session_cleanup_clears_dispatch_disabled_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_tool-info":
            return completed(args, json.dumps(make_tool_info_payload()))
        if args[0] == "do":
            return completed(args, "run_id: abc123\nrole: builder\ntimeout_seconds: 60\n")
        if args[0] == "_session-mode":
            return completed(args)
        if args[0] == "_dispatch-ack":
            return completed(args, "orchestra dispatched: builder abc123\n")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    monkeypatch.setattr(plugin, "_start_session_report_watcher", lambda *args, **kwargs: None)
    ctx = FakeHermesPluginContext(session_id="cli-session")
    plugin.register(ctx)
    calls.clear()
    slash_handler = ctx.commands[0]["handler"]
    dispatch_handler = next(
        tool["handler"] for tool in ctx.tools if tool["name"] == "orch_dispatch"
    )

    assert slash_handler("off") == (
        "Hermes /orch off succeeded: Orchestra dispatch disabled for this session"
    )
    plugin._on_session_cleanup(session_id="cli-session")
    output = dispatch_handler({"goal": "do work"}, session_id="cli-session")

    assert output == "orchestra dispatched: builder abc123"
    assert calls == [
        ["_session-mode", "set", "--session-id", "hermes:cli-session", "--mode", "off"],
        ["do", "--session-id", "hermes:cli-session", "--goal", "do work", "--json"],
        ["_dispatch-ack", "--run-id", "abc123", "--role", "builder"],
    ]


def test_orch_slash_on_clears_active_state_if_helper_raises_then_retry_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []
    orchestrator_skill_calls = 0

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal orchestrator_skill_calls
        calls.append(args)
        if args[0] == "_tool-info":
            return completed(args, json.dumps(make_tool_info_payload()))
        if args[0] == "_session-mode":
            return completed(args)
        if args[0] == "_orchestrator-skill":
            orchestrator_skill_calls += 1
            if orchestrator_skill_calls == 1:
                raise RuntimeError("boom")
            return completed(args, "orchestrator skill payload\n")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext(session_id="cli-session")
    plugin.register(ctx)
    calls.clear()
    handler = ctx.commands[0]["handler"]

    assert handler("on") == "Hermes /orch on failed: orchestrator skill helper raised: boom"
    assert handler("on") == "Hermes /orch on succeeded: orchestrator skill injected"

    assert calls == [
        ["_orchestrator-skill"],
        ["_orchestrator-skill"],
        [
            "_session-mode",
            "set",
            "--session-id",
            "hermes:cli-session",
            "--mode",
            "orchestrator",
        ],
    ]
    assert ctx.injected == [("orchestrator skill payload", "user")]


@pytest.mark.parametrize(
    ("ctx_factory", "ctx_setup", "helper_stdout", "helper_code", "expected"),
    [
        (
            lambda: FakeHermesPluginContext(session_id="cli-session"),
            lambda ctx: None,
            "orchestrator skill payload\n",
            1,
            "Hermes /orch on failed: orchestrator skill helper failed",
        ),
        (
            lambda: FakeHermesPluginContext(session_id="cli-session"),
            lambda ctx: None,
            "   \n",
            0,
            "Hermes /orch on failed: orchestrator skill payload was empty",
        ),
        (
            lambda: NoInjectHermesPluginContext(session_id="cli-session"),
            lambda ctx: None,
            "orchestrator skill payload\n",
            0,
            "Hermes /orch on failed: ctx.inject_message is unavailable",
        ),
        (
            lambda: FakeHermesPluginContext(session_id="cli-session"),
            lambda ctx: setattr(
                ctx,
                "inject_message",
                lambda content, role="user": (_ for _ in ()).throw(RuntimeError("inject boom")),
            ),
            "orchestrator skill payload\n",
            0,
            "Hermes /orch on failed: ctx.inject_message raised: inject boom",
        ),
        (
            lambda: FakeHermesPluginContext(session_id="cli-session"),
            lambda ctx: setattr(ctx, "inject_success", False),
            "orchestrator skill payload\n",
            0,
            "Hermes /orch on failed: ctx.inject_message returned False",
        ),
    ],
)
def test_orch_slash_on_reports_deterministic_failures(
    monkeypatch: pytest.MonkeyPatch,
    ctx_factory: Any,
    ctx_setup: Any,
    helper_stdout: str,
    helper_code: int,
    expected: str,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_tool-info":
            return completed(args, json.dumps(make_tool_info_payload()))
        if args[0] == "_orchestrator-skill":
            return completed(args, helper_stdout, code=helper_code)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = ctx_factory()
    ctx_setup(ctx)
    plugin.register(ctx)
    calls.clear()

    output = ctx.commands[0]["handler"]("on")

    assert output == expected
    assert calls == [["_orchestrator-skill"]]


def test_orch_slash_doctor_help_are_sessionless_safe_wrappers_and_scoped_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return completed(args, "ok\n")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)

    assert plugin._orch_command("help") == "ok\n"
    assert plugin._orch_command("doctor") == "ok\n"
    assert plugin._orch_command("roles") == "ok\n"
    assert plugin._orch_command("roles reviewer enabled false") == "ok\n"
    assert "runtime session context" in plugin._orch_command("status")
    assert "runtime session context" in plugin._orch_command("history 7")
    assert "runtime session context" in plugin._orch_command("stop run-1")

    assert calls == [
        ["help-host"],
        ["doctor"],
        ["roles", "--all"],
        ["roles", "reviewer", "enabled", "false"],
    ]


def test_orch_slash_cli_private_session_fallback_scopes_roles_status_history_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_tool-info":
            return completed(args, json.dumps(make_tool_info_payload()))
        return completed(args, "ok\n")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext(session_id="cli-session")
    plugin.register(ctx)
    calls.clear()

    assert ctx.commands[0]["handler"]("roles") == "ok\n"
    assert ctx.commands[0]["handler"]("roles reviewer model openai-codex/gpt-5.5") == "ok\n"
    assert ctx.commands[0]["handler"]("status") == "ok\n"
    assert ctx.commands[0]["handler"]("history 7") == "ok\n"
    assert ctx.commands[0]["handler"]("stop run-1") == "ok\n"

    assert calls == [
        ["roles", "--all"],
        ["roles", "reviewer", "model", "openai-codex/gpt-5.5"],
        ["status", "--session-id", "hermes:cli-session"],
        ["history", "--session-id", "hermes:cli-session", "--limit", "7"],
        ["stop", "--session-id", "hermes:cli-session", "--run-id", "run-1"],
    ]


def test_orch_slash_cli_private_session_fallback_dispatches_do_and_injects_when_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_tool-info":
            return completed(args, json.dumps(make_tool_info_payload()))
        if args[0] == "do":
            # Extract the --timeout value from args to return matching timeout_seconds
            timeout_value = "600"
            for i, arg in enumerate(args):
                if arg == "--timeout" and i + 1 < len(args):
                    timeout_value = args[i + 1]
                    break
            return completed(
                args, f"run_id: cli-run\ntimeout_seconds: {timeout_value}\nstatus: queued\n"
            )
        if args[0] == "_await-session-report":
            return completed(
                args,
                json.dumps({"runIds": ["cli-run"], "report": "reviewer done"}),
            )
        if args[0] == "_await-run":
            return completed(
                args,
                "status: done\nrole: reviewer\nactive_runs_remaining: 0\n",
            )
        if args[0] == "_progress-message":
            return completed(args, "orchestra: reviewer cli-run returned done (1/1)\n")
        if args[0] == "_dispatch-ack":
            return completed(args, "orchestra dispatched: reviewer cli-run\n")
        if args[0] == "_mark-session-report-delivered":
            return completed(args)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext(session_id="hermes:cli-session")
    plugin.register(ctx)
    calls.clear()

    output = ctx.commands[0]["handler"](
        'do --role reviewer --timeout 5 --task-label "cli task" "session_id attacker ship it"'
    )

    assert output == "orchestra dispatched: reviewer cli-run"
    assert wait_for_condition(
        lambda: [call[0] for call in calls].count("_await-session-report") == 1
        and any(call[0] == "_mark-session-report-delivered" for call in calls)
    )
    assert [
        "do",
        "--session-id",
        "hermes:cli-session",
        "--goal",
        "session_id attacker ship it",
        "--role",
        "reviewer",
        "--timeout",
        "5",
        "--task-label",
        "cli task",
        "--json",
    ] in calls
    assert [
        "_await-session-report",
        "--session-id",
        "hermes:cli-session",
        "--run-id",
        "cli-run",
        "--timeout",
        "35",
        "--json",
    ] in calls
    assert [
        "_dispatch-ack",
        "--run-id",
        "cli-run",
        "--role",
        "reviewer",
    ] in calls
    assert [
        "_mark-session-report-delivered",
        "--session-id",
        "hermes:cli-session",
        "--run-id",
        "cli-run",
    ] in calls
    assert "_await-run" not in [call[0] for call in calls]
    assert "_progress-message" not in [call[0] for call in calls]
    assert ctx.steered == []
    assert ctx.injected == [("reviewer done", "user")]


def test_orch_slash_cli_private_session_fallback_dispatches_do_and_steers_when_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_tool-info":
            return completed(args, json.dumps(make_tool_info_payload()))
        if args[0] == "do":
            return completed(args, "run_id: cli-run\ntimeout_seconds: 5\nstatus: queued\n")
        if args[0] == "_await-session-report":
            return completed(
                args,
                json.dumps({"runIds": ["cli-run"], "report": "reviewer done"}),
            )
        if args[0] == "_dispatch-ack":
            return completed(args, "orchestra dispatched: reviewer cli-run\n")
        if args[0] == "_mark-session-report-delivered":
            return completed(args)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext(session_id="hermes:cli-session", agent_running=True)
    plugin.register(ctx)
    calls.clear()

    output = ctx.commands[0]["handler"]('do --role reviewer "ship it"')

    assert output == "orchestra dispatched: reviewer cli-run"
    assert wait_for_condition(
        lambda: [call[0] for call in calls].count("_await-session-report") == 1
        and any(call[0] == "_mark-session-report-delivered" for call in calls)
    )
    assert [
        "do",
        "--session-id",
        "hermes:cli-session",
        "--goal",
        "ship it",
        "--role",
        "reviewer",
        "--json",
    ] in calls
    assert [
        "_await-session-report",
        "--session-id",
        "hermes:cli-session",
        "--run-id",
        "cli-run",
        "--timeout",
        "35",
        "--json",
    ] in calls
    assert [
        "_mark-session-report-delivered",
        "--session-id",
        "hermes:cli-session",
        "--run-id",
        "cli-run",
    ] in calls
    assert ctx.injected == []
    assert ctx.steered == ["reviewer done"]
    assert list(ctx.pending_input.queue) == []


def test_orch_slash_fails_closed_without_hook_session_context() -> None:
    plugin = load_plugin()

    output = plugin._orch_command("status")

    assert "runtime session context" in output


def test_hermes_plugin_source_uses_session_cleanup_hooks() -> None:
    source = PLUGIN_PATH.read_text(encoding="utf-8")

    assert "_CURRENT_SESSION_ID" not in source
    assert 'register_hook("on_session_end"' not in source
    assert "on_session_finalize" in source
    assert "on_session_reset" in source
    assert "on_session_start" in source
    assert "_AWAIT_RUN_WATCHERS" not in source
    assert "_AWAIT_RUN_WATCHERS_LOCK" not in source
    assert "_parse_await_run_output" not in source
    assert "_format_await_run_progress" not in source
    assert "_log_watcher_progress" not in source
    assert "_start_session_await_run_watcher" not in source
    assert "_watch_await_run" not in source


@pytest.mark.parametrize(
    "kwargs",
    [{}, {"session_id": ""}, {"session_id": "   "}, {"session_id": None}],
)
def test_orch_dispatch_rejects_missing_runtime_session_id(kwargs: dict[str, Any]) -> None:
    plugin = load_plugin()

    payload = json.loads(plugin.orch_dispatch({"goal": "do work"}, **kwargs))

    assert "error" in payload
    assert "session_id" in payload["error"]


@pytest.mark.parametrize("identity_arg", ["session_id", "identity", "orchestrator_session_id"])
def test_orch_dispatch_rejects_model_supplied_identity_args(identity_arg: str) -> None:
    plugin = load_plugin()

    payload = json.loads(
        plugin.orch_dispatch({"goal": "do work", identity_arg: "attacker"}, session_id="runtime")
    )

    assert payload == {
        "error": "identity arguments are not accepted; Hermes runtime session_id is used instead"
    }


@pytest.mark.parametrize("timeout", [42, 1.5, "42", 0, -1, True])
def test_orch_dispatch_rejects_timeout_parameter(
    monkeypatch: pytest.MonkeyPatch,
    timeout: object,
) -> None:
    plugin = load_plugin()

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if args == ["_tool-info"]:
            return completed(
                args,
                json.dumps(
                    {
                        "dispatchTimeoutError": (
                            "timeout is not accepted by orch_dispatch; "
                            "configured default_timeout applies."
                        )
                    }
                ),
            )
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)

    payload = json.loads(
        plugin.orch_dispatch({"goal": "do work", "timeout": timeout}, session_id="runtime")
    )

    assert payload == {
        "error": "timeout is not accepted by orch_dispatch; configured default_timeout applies."
    }


def test_parse_do_args_supports_shell_quoted_goal_and_task_label() -> None:
    plugin = load_plugin()

    payload = plugin._parse_do_args(
        '--role reviewer --timeout 5 --task-label "cli task" "ship focused task"'
    )

    assert payload == {
        "role": "reviewer",
        "timeout": 5,
        "taskLabel": "cli task",
        "goal": "ship focused task",
    }


def test_parse_do_args_supports_hermes_escaped_quoted_goal_and_task_label() -> None:
    plugin = load_plugin()

    payload = plugin._parse_do_args(
        '--role researcher --timeout 120 --task-label \\\"quoted smoke label\\\" '
        '\\\"Smoke test only. Do not edit files. Inspect README.md, PLAN.md, and '
        'agent-catalog.yaml. Return status, files inspected, configured worker role '
        'harness, one-sentence project purpose, blockers.\\\"'
    )

    assert payload == {
        "role": "researcher",
        "timeout": 120,
        "taskLabel": "quoted smoke label",
        "goal": "Smoke test only. Do not edit files. Inspect README.md, PLAN.md, and "
        "agent-catalog.yaml. Return status, files inspected, configured worker role "
        "harness, one-sentence project purpose, blockers.",
    }


def test_orch_slash_cli_private_session_fallback_dispatches_hermes_escaped_quoted_do(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_tool-info":
            return completed(args, json.dumps(make_tool_info_payload()))
        if args[0] == "do":
            return completed(args, "run_id: cli-run\ntimeout_seconds: 600\nstatus: queued\n")
        if args[0] == "_await-run":
            return completed(
                args,
                "status: done\nrole: researcher\nactive_runs_remaining: 0\n",
            )
        if args[0] == "_progress-message":
            return completed(args, "orchestra: researcher cli-run returned done (1/1)\n")
        if args[0] == "_dispatch-ack":
            return completed(args, "orchestra dispatched: researcher cli-run\n")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    monkeypatch.setattr(plugin, "_start_session_report_watcher", lambda *_args, **_kwargs: None)
    ctx = FakeHermesPluginContext(session_id="hermes:cli-session")
    plugin.register(ctx)
    calls.clear()

    output = ctx.commands[0]["handler"](
        'do --role researcher --timeout 120 --task-label \\\"quoted smoke label\\\" '
        '\\\"Smoke test only. Do not edit files. Inspect README.md, PLAN.md, and '
        'agent-catalog.yaml. Return status, files inspected, configured worker role '
        'harness, one-sentence project purpose, blockers.\\\"'
    )

    assert output == "orchestra dispatched: researcher cli-run"
    assert [
        "do",
        "--session-id",
        "hermes:cli-session",
        "--goal",
        "Smoke test only. Do not edit files. Inspect README.md, PLAN.md, and "
        "agent-catalog.yaml. Return status, files inspected, configured worker role "
        "harness, one-sentence project purpose, blockers.",
        "--role",
        "researcher",
        "--timeout",
        "120",
        "--task-label",
        "quoted smoke label",
        "--json",
    ] in calls
    assert [
        "_dispatch-ack",
        "--run-id",
        "cli-run",
        "--role",
        "researcher",
    ] in calls
    assert calls == [
        [
            "do",
            "--session-id",
            "hermes:cli-session",
            "--goal",
            "Smoke test only. Do not edit files. Inspect README.md, PLAN.md, and "
            "agent-catalog.yaml. Return status, files inspected, configured worker role "
            "harness, one-sentence project purpose, blockers.",
            "--role",
            "researcher",
            "--timeout",
            "120",
            "--task-label",
            "quoted smoke label",
            "--json",
        ],
        ["_dispatch-ack", "--run-id", "cli-run", "--role", "researcher"],
    ]
    assert "_await-run" not in [call[0] for call in calls]
    assert "_progress-message" not in [call[0] for call in calls]


def test_orch_slash_do_rejects_malformed_quotes_without_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_tool-info":
            return completed(args, json.dumps(make_tool_info_payload()))
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext(session_id="cli-session")
    plugin.register(ctx)
    calls.clear()

    output = ctx.commands[0]["handler"]('do --task-label "broken goal')

    assert output == "Malformed quoted string in /orch do arguments"
    assert calls == []


def test_orch_dispatch_builds_cli_args_from_runtime_kwargs_and_returns_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "do":
            return completed(args, "run_id: abc123\ntimeout_seconds: 600\nstatus: queued\n")
        if args[0] == "_dispatch-ack":
            return completed(args, "orchestra dispatched: reviewer abc123\n")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)

    output = plugin.orch_dispatch(
        {
            "goal": "ship focused task",
            "role": "reviewer",
            "taskLabel": "review-task",
        },
        session_id="runtime-session",
    )

    assert output == "orchestra dispatched: reviewer abc123"
    assert calls == [
        [
            "do",
            "--session-id",
            "hermes:runtime-session",
            "--goal",
            "ship focused task",
            "--role",
            "reviewer",
            "--task-label",
            "review-task",
            "--json",
        ],
        ["_dispatch-ack", "--run-id", "abc123", "--role", "reviewer"],
    ]

def test_orch_dispatch_uses_effective_default_role_from_cli_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "do":
            output = (
                "run_id: abc123\n"
                "timeout_seconds: 600\n"
                "role: reviewer\n"
                "status: queued\n"
            )
            return completed(args, output)
        if args[0] == "_await-run":
            return completed(
                args,
                "status: done\nrole: reviewer\nactive_runs_remaining: 0\n",
            )
        if args[0] == "_progress-message":
            return completed(args, "orchestra: reviewer abc123 returned done (1/1)\n")
        if args[0] == "_dispatch-ack":
            return completed(args, "orchestra dispatched: reviewer abc123\n")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)

    output = plugin.orch_dispatch({"goal": "do work"}, session_id="runtime")

    assert output == "orchestra dispatched: reviewer abc123"
    assert calls == [
        ["do", "--session-id", "hermes:runtime", "--goal", "do work", "--json"],
        ["_dispatch-ack", "--run-id", "abc123", "--role", "reviewer"],
    ]


def test_orch_dispatch_requires_run_id_before_ack(monkeypatch: pytest.MonkeyPatch) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return completed(args, "status: queued\n")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)

    payload = json.loads(plugin.orch_dispatch({"goal": "do work"}, session_id="runtime"))

    assert calls == [["do", "--session-id", "hermes:runtime", "--goal", "do work", "--json"]]
    assert payload == {"error": "orchestra dispatch did not return a run_id"}


def test_registered_orch_dispatch_injects_when_idle_and_marks_report_delivered(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_tool-info":
            return completed(args, json.dumps(make_tool_info_payload()))
        if args[0] == "do":
            return completed(args, "run_id: abc123\ntimeout_seconds: 600\nstatus: queued\n")
        if args[0] == "_dispatch-ack":
            return completed(args, "orchestra dispatched: worker abc123\n")
        if args[0] == "_await-session-report":
            return completed(
                args,
                json.dumps({"runIds": ["abc123"], "report": "worker done"}),
            )
        if args[0] == "_await-run":
            return completed(
                args,
                "status: done\nrole: reviewer\nactive_runs_remaining: 0\n",
            )
        if args[0] == "_progress-message":
            return completed(args, "orchestra: reviewer abc123 returned done (1/1)\n")
        if args[0] == "_mark-session-report-delivered":
            return completed(args)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext()
    plugin.register(ctx)

    output = ctx.tools[0]["handler"]({"goal": "do work"}, session_id="runtime")

    assert output == "orchestra dispatched: worker abc123"
    assert wait_for_condition(
        lambda: [call[0] for call in calls].count("_await-session-report") == 1
        and any(call[0] == "_mark-session-report-delivered" for call in calls)
    )
    assert ctx.steered == []
    assert ctx.injected == [("worker done", "user")]
    assert capsys.readouterr().err == ""
    assert [
        "_await-session-report",
        "--session-id",
        "hermes:runtime",
        "--run-id",
        "abc123",
        "--timeout",
        "630",
        "--json",
    ] in calls
    assert [
        "_dispatch-ack",
        "--run-id",
        "abc123",
        "--role",
        "worker",
    ] in calls
    assert [
        "_mark-session-report-delivered",
        "--session-id",
        "hermes:runtime",
        "--run-id",
        "abc123",
    ] in calls
    assert "_await-run" not in [call[0] for call in calls]
    assert "_progress-message" not in [call[0] for call in calls]


def test_registered_orch_dispatch_prefers_runtime_tool_context_for_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_tool-info":
            return completed(args, json.dumps(make_tool_info_payload()))
        if args[0] == "do":
            return completed(args, "run_id: abc123\ntimeout_seconds: 600\nstatus: queued\n")
        if args[0] == "_dispatch-ack":
            return completed(args, "orchestra dispatched: worker abc123\n")
        if args[0] == "_await-session-report":
            return completed(
                args,
                json.dumps({"runIds": ["abc123"], "report": "worker done"}),
            )
        if args[0] == "_await-run":
            return completed(
                args,
                "status: done\nrole: reviewer\nactive_runs_remaining: 0\n",
            )
        if args[0] == "_progress-message":
            return completed(args, "orchestra: reviewer abc123 returned done (1/1)\n")
        if args[0] == "_mark-session-report-delivered":
            return completed(args)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    register_ctx = RegistrationOnlyContext()
    runtime_ctx = FakeHermesPluginContext()
    plugin.register(register_ctx)

    output = register_ctx.tools[0]["handler"](
        {"goal": "do work"},
        session_id="runtime",
        _ctx=runtime_ctx,
    )

    assert output == "orchestra dispatched: worker abc123"
    assert wait_for_condition(lambda: runtime_ctx.injected == [("worker done", "user")])
    assert runtime_ctx.steered == []
    assert [
        "_await-session-report",
        "--session-id",
        "hermes:runtime",
        "--run-id",
        "abc123",
        "--timeout",
        "630",
        "--json",
    ] in calls
    assert [
        "_dispatch-ack",
        "--run-id",
        "abc123",
        "--role",
        "worker",
    ] in calls
    assert [
        "_mark-session-report-delivered",
        "--session-id",
        "hermes:runtime",
        "--run-id",
        "abc123",
    ] in calls
    assert "_await-run" not in [call[0] for call in calls]
    assert "_progress-message" not in [call[0] for call in calls]


def test_final_report_uses_inject_fallback_without_steer(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "do":
            return completed(args, "run_id: abc123\ntimeout_seconds: 600\nstatus: queued\n")
        if args[0] == "_dispatch-ack":
            return completed(args, "orchestra dispatched: worker abc123\n")
        if args[0] == "_await-session-report":
            return completed(
                args,
                json.dumps({"runIds": ["abc123"], "report": "worker done"}),
            )
        if args[0] == "_await-run":
            return completed(
                args,
                "status: done\nrole: reviewer\nactive_runs_remaining: 0\n",
            )
        if args[0] == "_progress-message":
            return completed(args, "orchestra: reviewer abc123 returned done (1/1)\n")
        if args[0] == "_mark-session-report-delivered":
            return completed(args)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = InjectOnlyContext()

    output = plugin._dispatch_orchestra_run(
        {"goal": "do work"},
        "hermes:runtime",
        ctx=ctx,
    )

    assert output == "orchestra dispatched: worker abc123"
    assert wait_for_condition(
        lambda: [call[0] for call in calls].count("_await-session-report") == 1
        and any(call[0] == "_mark-session-report-delivered" for call in calls)
    )
    assert ctx.injected == [("worker done", "user")]
    assert not hasattr(ctx, "steered") or ctx.steered == []
    assert capsys.readouterr().err == ""
    assert [
        "_await-session-report",
        "--session-id",
        "hermes:runtime",
        "--run-id",
        "abc123",
        "--timeout",
        "630",
        "--json",
    ] in calls
    assert [
        "_dispatch-ack",
        "--run-id",
        "abc123",
        "--role",
        "worker",
    ] in calls
    assert [
        "_mark-session-report-delivered",
        "--session-id",
        "hermes:runtime",
        "--run-id",
        "abc123",
    ] in calls
    assert "_await-run" not in [call[0] for call in calls]
    assert "_progress-message" not in [call[0] for call in calls]


def test_session_report_watcher_thread_is_daemon_like_hermes_background_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    created_threads: list[dict[str, Any]] = []

    class FakeThread:
        def __init__(self, **kwargs: Any) -> None:
            created_threads.append(kwargs)

        def start(self) -> None:
            pass

    monkeypatch.setattr(plugin.threading, "Thread", FakeThread)

    plugin._start_session_report_watcher(FakeHermesPluginContext(), "hermes:runtime", "abc123", 35)

    assert created_threads[0]["daemon"] is True


def test_session_report_watcher_uses_expanded_retry_budget_and_backoff() -> None:
    plugin = load_plugin()

    assert plugin._REPORT_WATCHER_ATTEMPTS == 8
    assert [plugin._report_watcher_retry_delay_seconds(attempt) for attempt in range(7)] == [
        0.25,
        0.5,
        1.0,
        2.0,
        3.0,
        3.0,
        3.0,
    ]


def test_watcher_wait_budget_exceeds_observed_worker_timeout() -> None:
    plugin = load_plugin()

    wait_budget = plugin._watcher_wait_budget_seconds(600)

    assert wait_budget > 600
    assert plugin._watcher_subprocess_timeout_seconds(wait_budget) > wait_budget


def test_watcher_wait_budget_uses_payload_timeout_not_default() -> None:
    plugin = load_plugin()

    assert plugin._watcher_wait_budget_seconds(5) == 35


def test_extract_dispatch_timeout_seconds_parses_output() -> None:
    plugin = load_plugin()

    assert plugin._extract_dispatch_timeout_seconds(
        "run_id: abc123\ntimeout_seconds: 120\nstatus: queued\n"
    ) == 120


def test_extract_dispatch_timeout_seconds_raises_on_missing_output() -> None:
    plugin = load_plugin()

    with pytest.raises(ValueError, match="did not include timeout_seconds"):
        plugin._extract_dispatch_timeout_seconds("run_id: abc123\nstatus: queued\n")


def test_extract_dispatch_timeout_seconds_raises_on_non_numeric_output() -> None:
    plugin = load_plugin()

    with pytest.raises(ValueError, match="must be a positive integer"):
        plugin._extract_dispatch_timeout_seconds("timeout_seconds: abc\n")


def test_extract_dispatch_timeout_seconds_raises_on_zero() -> None:
    plugin = load_plugin()

    with pytest.raises(ValueError, match="must be a positive integer"):
        plugin._extract_dispatch_timeout_seconds("timeout_seconds: 0\n")


def test_session_report_watcher_retries_after_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        await_report_calls = [call for call in calls if call[0] == "_await-session-report"]
        if args[0] == "_await-session-report" and len(await_report_calls) == 1:
            return completed(args, stderr="unable to open database file", code=1)
        if args[0] == "_await-session-report":
            return completed(
                args,
                json.dumps({"runIds": ["abc123"], "report": "worker done"}),
            )
        if args[0] == "_mark-session-report-delivered":
            return completed(args)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    monkeypatch.setattr(plugin.time, "sleep", lambda _seconds: None)
    ctx = FakeHermesPluginContext()

    plugin._watch_session_report(ctx, "hermes:runtime", "abc123", 630)
    assert ctx.steered == []
    assert ctx.injected == [("worker done", "user")]
    assert [call[0] for call in calls].count("_await-session-report") == 2
    assert [
        "_await-session-report",
        "--session-id",
        "hermes:runtime",
        "--run-id",
        "abc123",
        "--timeout",
        "630",
        "--json",
    ] in calls
    assert [
        "_mark-session-report-delivered",
        "--session-id",
        "hermes:runtime",
        "--run-id",
        "abc123",
    ] in calls

    assert ctx.steered == []
    assert ctx.injected == [("worker done", "user")]
    assert [call[0] for call in calls].count("_await-session-report") == 2
    assert [
        "_await-session-report",
        "--session-id",
        "hermes:runtime",
        "--run-id",
        "abc123",
        "--timeout",
        "630",
        "--json",
    ] in calls
    assert [
        "_mark-session-report-delivered",
        "--session-id",
        "hermes:runtime",
        "--run-id",
        "abc123",
    ] in calls




def test_session_report_busy_prefers_steer_and_marks_delivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_mark-session-report-delivered":
            return completed(args)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext(agent_running=True)

    plugin._handle_session_report_result(
        ctx,
        "hermes:runtime",
        completed(
            ["_await-session-report"],
            json.dumps({"runIds": ["abc123"], "report": "worker done"}),
        ),
    )

    assert ctx.steered == ["worker done"]
    assert ctx.injected == []
    assert list(ctx.pending_input.queue) == []
    assert calls == [
        [
            "_mark-session-report-delivered",
            "--session-id",
            "hermes:runtime",
            "--run-id",
            "abc123",
        ]
    ]


def test_session_report_tui_busy_steers_live_session_without_cli_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []
    steered: list[str] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_mark-session-report-delivered":
            return completed(args)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext(agent_running=False)
    ctx._manager._cli_ref = None
    def steer(message: str) -> bool:
        steered.append(message)
        return True

    agent = SimpleNamespace(steer=steer)
    fake_server = SimpleNamespace(
        _find_live_session_by_key=lambda key: (
            "tui-session",
            {"running": True, "session_key": key, "agent": agent},
        )
    )
    monkeypatch.setitem(sys.modules, "tui_gateway", SimpleNamespace(server=fake_server))

    plugin._handle_session_report_result(
        ctx,
        "hermes:runtime",
        completed(
            ["_await-session-report"],
            json.dumps({"runIds": ["abc123"], "report": "worker done"}),
        ),
    )

    assert steered == ["worker done"]
    assert ctx.injected == []
    assert calls == [
        [
            "_mark-session-report-delivered",
            "--session-id",
            "hermes:runtime",
            "--run-id",
            "abc123",
        ]
    ]



def test_session_report_busy_queue_failure_releases_without_marking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_release-session-report":
            return completed(args)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext(agent_running=True)
    ctx.steer_success = False
    delattr(ctx._manager._cli_ref, "_pending_input")

    plugin._handle_session_report_result(
        ctx,
        "hermes:runtime",
        completed(
            ["_await-session-report"],
            json.dumps({"runIds": ["abc123"], "report": "worker done"}),
        ),
    )

    assert ctx.steered == ["worker done"]
    assert ctx.injected == []
    assert list(ctx.pending_input.queue) == []
    assert calls == [
        [
            "_release-session-report",
            "--session-id",
            "hermes:runtime",
            "--run-id",
            "abc123",
        ]
    ]


def test_session_report_idle_mark_failure_releases_for_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
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
        "hermes:runtime",
        completed(
            ["_await-session-report"],
            json.dumps({"runIds": ["abc123"], "report": "worker done"}),
        ),
    )

    assert ctx.steered == []
    assert ctx.injected == [("worker done", "user")]
    assert calls == [
        [
            "_mark-session-report-delivered",
            "--session-id",
            "hermes:runtime",
            "--run-id",
            "abc123",
        ],
        [
            "_release-session-report",
            "--session-id",
            "hermes:runtime",
            "--run-id",
            "abc123",
        ],
    ]


def test_session_report_malformed_json_releases_fallback_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[0] == "_release-session-report":
            return completed(args)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)

    plugin._handle_session_report_result(
        FakeHermesPluginContext(),
        "hermes:runtime",
        completed(["_await-session-report"], "{not json"),
        ["abc123"],
    )

    assert calls == [
        [
            "_release-session-report",
            "--session-id",
            "hermes:runtime",
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

    runtime_root = plugin._hermes_runtime_orchestra_dir()
    assert result.returncode == 0
    assert calls == [
        {
            "args": [
                "orchestra",
                "--config",
                str(runtime_root / "config.yaml"),
                "--agent-catalog",
                str(runtime_root / "agent-catalog.yaml"),
                "_tool-info",
            ],
            "check": False,
            "capture_output": True,
            "text": True,
            "timeout": plugin._SUBPROCESS_TIMEOUT_SECONDS,
        }
    ]


def test_watcher_subprocess_calls_use_larger_hard_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    plugin = load_plugin()
    calls: list[dict[str, Any]] = []

    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"args": args, **kwargs})
        return completed(args)

    monkeypatch.setattr(plugin.subprocess, "run", fake_run)

    wait_budget = plugin._watcher_wait_budget_seconds(5)
    result = plugin._run_orchestra(
        ["_await-run", "--timeout", str(wait_budget)],
        timeout_seconds=plugin._watcher_subprocess_timeout_seconds(wait_budget),
    )

    runtime_root = plugin._hermes_runtime_orchestra_dir()
    assert result.returncode == 0
    assert calls == [
        {
            "args": [
                "orchestra",
                "--config",
                str(runtime_root / "config.yaml"),
                "--agent-catalog",
                str(runtime_root / "agent-catalog.yaml"),
                "_await-run",
                "--timeout",
                "35",
            ],
            "check": False,
            "capture_output": True,
            "text": True,
            "timeout": 65,
        }
    ]
