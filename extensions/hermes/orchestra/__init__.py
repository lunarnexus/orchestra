"""Hermes plugin for safe Orchestra dispatch."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from typing import Any

_IDENTITY_ARG_NAMES = frozenset({"session_id", "identity", "orchestrator_session_id"})
_RUN_ID_RE = re.compile(r"^run_id:\s*(?P<run_id>\S+)\s*$")
_SUBPROCESS_TIMEOUT_SECONDS = 300
_REPORT_WATCHERS: set[str] = set()
_REPORT_WATCHERS_LOCK = threading.Lock()

_FALLBACK_TOOL_INFO = {
    "description": "Delegate or dispatch a focused task to an Orchestra worker/subagent.",
    "promptSnippet": "Dispatch focused work to Orchestra workers/subagents.",
    "promptGuidelines": ["Use orch_dispatch for narrow delegated worker tasks."],
    "goalDescription": "Focused worker request/task to delegate.",
    "roleDescription": "Optional exact configured role. Omit for default worker role.",
    "timeoutDescription": "Optional timeout in seconds.",
    "taskLabelDescription": "Optional short request label.",
}


def normalize_hermes_session_id(raw_session_id: str) -> str:
    """Normalize a trusted Hermes runtime session id for Orchestra ownership."""
    normalized = raw_session_id.strip()
    if not normalized:
        raise ValueError("hermes session id is required")
    if normalized.startswith("hermes:"):
        return normalized
    return f"hermes:{normalized}"


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


def _log_watcher_error(message: str) -> None:
    sys.stderr.write(f"orchestra auto-return watcher failed: {message}\n")


def _report_run_id_args(run_ids: list[str]) -> list[str]:
    args: list[str] = []
    for run_id in run_ids:
        args.extend(["--run-id", run_id])
    return args


def _release_session_report(trusted_session_id: str, run_ids: list[str]) -> None:
    if not run_ids:
        return
    result = _run_orchestra(
        [
            "_release-session-report",
            "--session-id",
            trusted_session_id,
            *_report_run_id_args(run_ids),
        ]
    )
    if result.returncode != 0:
        _log_watcher_error((result.stdout or result.stderr).strip() or "report release failed")


def _mark_session_report_delivered(trusted_session_id: str, run_ids: list[str]) -> None:
    if not run_ids:
        return
    result = _run_orchestra(
        [
            "_mark-session-report-delivered",
            "--session-id",
            trusted_session_id,
            *_report_run_id_args(run_ids),
        ]
    )
    if result.returncode != 0:
        _log_watcher_error(
            (result.stdout or result.stderr).strip() or "report delivery mark failed"
        )


def _inject_report(ctx: Any, message: str) -> bool:
    inject_message = getattr(ctx, "inject_message", None)
    if not callable(inject_message):
        return False
    return bool(inject_message(message, role="user"))


def _handle_session_report_result(
    ctx: Any,
    trusted_session_id: str,
    result: subprocess.CompletedProcess[str],
    fallback_run_ids: list[str] | None = None,
) -> None:
    if result.returncode != 0:
        error_text = (result.stdout or result.stderr).strip()
        if error_text:
            _log_watcher_error(error_text)
        return

    raw_report = result.stdout.strip()
    if not raw_report:
        return

    run_ids = list(fallback_run_ids or [])
    try:
        payload = json.loads(raw_report)
        raw_run_ids = payload.get("runIds") if isinstance(payload, dict) else None
        if isinstance(raw_run_ids, list):
            parsed_run_ids = [run_id for run_id in raw_run_ids if isinstance(run_id, str)]
            if parsed_run_ids:
                run_ids = parsed_run_ids
        message = payload.get("report") if isinstance(payload, dict) else None
        if not isinstance(message, str) or not message.strip():
            _release_session_report(trusted_session_id, run_ids)
            return
        if not _inject_report(ctx, message.strip()):
            _release_session_report(trusted_session_id, run_ids)
            return
        _mark_session_report_delivered(trusted_session_id, run_ids)
    except Exception as exc:  # noqa: BLE001 - plugin must not crash watcher thread
        _release_session_report(trusted_session_id, run_ids)
        _log_watcher_error(str(exc))


def _watch_session_report(ctx: Any, trusted_session_id: str, run_id: str) -> None:
    try:
        result = _run_orchestra(
            [
                "_await-session-report",
                "--session-id",
                trusted_session_id,
                "--run-id",
                run_id,
                "--json",
            ]
        )
        _handle_session_report_result(ctx, trusted_session_id, result, [run_id])
    finally:
        with _REPORT_WATCHERS_LOCK:
            _REPORT_WATCHERS.discard(trusted_session_id)


def _start_session_report_watcher(ctx: Any | None, trusted_session_id: str, run_id: str) -> None:
    if ctx is None:
        return
    with _REPORT_WATCHERS_LOCK:
        if trusted_session_id in _REPORT_WATCHERS:
            return
        _REPORT_WATCHERS.add(trusted_session_id)
    thread = threading.Thread(
        target=_watch_session_report,
        args=(ctx, trusted_session_id, run_id),
        daemon=True,
        name=f"orchestra-report-{run_id}",
    )
    thread.start()


def _dispatch_orchestra_run(
    payload: dict[str, Any],
    trusted_session_id: str,
    ctx: Any | None = None,
) -> str:
    goal = str(payload.get("goal", "")).strip()
    if not goal:
        return _error("goal is required")

    timeout = payload.get("timeout")
    if timeout is not None and (type(timeout) is not int or timeout <= 0):
        return _error("timeout must be a positive integer")

    role = str(payload.get("role") or "worker").strip() or "worker"
    command = [
        "do",
        "--session-id",
        trusted_session_id,
        "--role",
        role,
        "--goal",
        goal,
    ]
    if timeout is not None:
        command.extend(["--timeout", str(timeout)])
    task_label = str(payload.get("taskLabel", "")).strip()
    if task_label:
        command.extend(["--task-label", task_label])

    result = _run_orchestra(command)
    if result.returncode != 0:
        return _error((result.stdout or result.stderr).strip() or "orchestra dispatch failed")

    run_id = _extract_run_id(result.stdout)
    if not run_id:
        return _error("orchestra dispatch did not return a run_id")

    _start_session_report_watcher(ctx, trusted_session_id, run_id)

    ack = _run_orchestra(["_dispatch-ack", "--run-id", run_id, "--role", role])
    if ack.returncode != 0:
        return _error((ack.stdout or ack.stderr).strip() or "orchestra dispatch ack failed")
    return json.dumps({"runId": run_id, "ack": ack.stdout.strip()})


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

    return _dispatch_orchestra_run(args, trusted_session_id, ctx=kwargs.get("_ctx"))


def _orch_command(_raw_args: str) -> str:
    return (
        "Hermes /orch is disabled for safety: slash command handlers do not expose "
        "trusted session_id. Ask Hermes to delegate naturally so it can use the "
        "orch_dispatch tool."
    )


def register(ctx: Any) -> None:
    """Register Hermes tool and fail-closed slash command."""
    tool_info = _load_tool_info()

    def dispatch_handler(args: dict[str, Any], **kwargs: Any) -> str:
        kwargs["_ctx"] = ctx
        return orch_dispatch(args, **kwargs)

    ctx.register_tool(
        name="orch_dispatch",
        toolset="orchestra",
        schema=_schema(tool_info),
        handler=dispatch_handler,
    )
    ctx.register_command(
        "orch",
        handler=_orch_command,
        description="Orchestra help (fails closed; use orch_dispatch)",
    )
