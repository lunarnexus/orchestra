"""Hermes plugin for safe Orchestra dispatch."""

from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any

from orchestra.adapters.hermes import normalize_hermes_session_id

_IDENTITY_ARG_NAMES = frozenset({"session_id", "identity", "orchestrator_session_id"})
_RUN_ID_RE = re.compile(r"^run_id:\s*(?P<run_id>\S+)\s*$")
_SUBPROCESS_TIMEOUT_SECONDS = 300

_FALLBACK_TOOL_INFO = {
    "description": "Delegate or dispatch a focused task to an Orchestra worker/subagent.",
    "promptSnippet": "Dispatch focused work to Orchestra workers/subagents.",
    "promptGuidelines": ["Use orch_dispatch for narrow delegated worker tasks."],
    "goalDescription": "Focused worker request/task to delegate.",
    "roleDescription": "Optional exact configured role. Omit for default worker role.",
    "timeoutDescription": "Optional timeout in seconds.",
    "taskLabelDescription": "Optional short request label.",
}


def _orchestra_base_args() -> list[str]:
    args: list[str] = []
    if config := os.environ.get("ORCHESTRA_CONFIG"):
        args.extend(["--config", config])
    if catalog := os.environ.get("ORCHESTRA_AGENT_CATALOG"):
        args.extend(["--agent-catalog", catalog])
    return args


def _run_orchestra(args: list[str]) -> subprocess.CompletedProcess[str]:
    command = ["orchestra", *_orchestra_base_args(), *args]
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else exc.stdout or ""
        return subprocess.CompletedProcess(
            args=command,
            returncode=124,
            stdout=stdout,
            stderr=f"orchestra command timed out after {_SUBPROCESS_TIMEOUT_SECONDS} seconds",
        )


def _load_tool_info() -> dict[str, Any]:
    result = _run_orchestra(["_tool-info"])
    if result.returncode != 0 or not result.stdout.strip():
        return dict(_FALLBACK_TOOL_INFO)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return dict(_FALLBACK_TOOL_INFO)
    info = dict(_FALLBACK_TOOL_INFO)
    info.update({key: payload[key] for key in info if key in payload})
    return info


def _schema(tool_info: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": "orch_dispatch",
        "description": str(tool_info["description"]),
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": str(tool_info["goalDescription"]),
                },
                "role": {
                    "type": "string",
                    "description": str(tool_info["roleDescription"]),
                },
                "timeout": {
                    "type": "integer",
                    "minimum": 1,
                    "description": str(tool_info["timeoutDescription"]),
                },
                "taskLabel": {
                    "type": "string",
                    "description": str(tool_info["taskLabelDescription"]),
                },
            },
            "required": ["goal"],
        },
    }


def _extract_run_id(output: str) -> str | None:
    for line in output.splitlines():
        match = _RUN_ID_RE.match(line.strip())
        if match:
            return match.group("run_id")
    return None


def _error(message: str) -> str:
    return json.dumps({"error": message})


def orch_dispatch(args: dict[str, Any], **kwargs: Any) -> str:
    """Dispatch a worker using only Hermes' trusted tool-call session_id kwarg."""
    supplied_identity_args = sorted(_IDENTITY_ARG_NAMES.intersection(args))
    if supplied_identity_args:
        return _error(
            "identity arguments are not accepted; Hermes runtime session_id is used instead"
        )

    raw_session_id = kwargs.get("session_id")
    if not isinstance(raw_session_id, str):
        return _error("trusted Hermes session_id is required")
    try:
        trusted_session_id = normalize_hermes_session_id(raw_session_id)
    except ValueError:
        return _error("trusted Hermes session_id is required")

    goal = str(args.get("goal", "")).strip()
    if not goal:
        return _error("goal is required")

    timeout = args.get("timeout")
    if timeout is not None and (type(timeout) is not int or timeout <= 0):
        return _error("timeout must be a positive integer")

    command = [
        "do",
        "--session-id",
        trusted_session_id,
        "--role",
        str(args.get("role") or "worker").strip() or "worker",
        "--goal",
        goal,
    ]
    if timeout is not None:
        command.extend(["--timeout", str(timeout)])
    task_label = str(args.get("taskLabel", "")).strip()
    if task_label:
        command.extend(["--task-label", task_label])

    result = _run_orchestra(command)
    if result.returncode != 0:
        return _error((result.stdout or result.stderr).strip() or "orchestra dispatch failed")

    run_id = _extract_run_id(result.stdout)
    if not run_id:
        return _error("orchestra dispatch did not return a run_id")

    ack = _run_orchestra(["_dispatch-ack", "--run-id", run_id])
    if ack.returncode != 0:
        return _error((ack.stdout or ack.stderr).strip() or "orchestra dispatch ack failed")
    return json.dumps({"runId": run_id, "ack": ack.stdout.strip()})


def _orch_command(_raw_args: str) -> str:
    return (
        "Hermes /orch is disabled for safety: slash command handlers do not expose "
        "trusted session_id. Ask Hermes to delegate naturally so it can use the "
        "orch_dispatch tool."
    )


def register(ctx: Any) -> None:
    """Register Hermes tool and fail-closed slash command."""
    tool_info = _load_tool_info()
    ctx.register_tool(
        name="orch_dispatch",
        toolset="orchestra",
        schema=_schema(tool_info),
        handler=orch_dispatch,
    )
    ctx.register_command(
        "orch",
        handler=_orch_command,
        description="Orchestra help (fails closed; use orch_dispatch)",
    )
