from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

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
    assert "disabled for safety" in ctx.commands[0]["handler"]("")


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
            return completed(args, "orchestra dispatched: abc123\n")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)

    payload = json.loads(
        plugin.orch_dispatch(
            {
                "goal": "ship focused task",
                "role": "reviewer",
                "timeout": 42,
                "taskLabel": "review-task",
            },
            session_id="trusted-session",
        )
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
        ["_dispatch-ack", "--run-id", "abc123"],
    ]
    assert payload == {"runId": "abc123", "ack": "orchestra dispatched: abc123"}


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
