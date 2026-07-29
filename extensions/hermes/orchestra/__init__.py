"""Hermes plugin for safe Orchestra dispatch."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from typing import Any

_IDENTITY_ARG_NAMES = frozenset({"session_id", "identity", "orchestrator_session_id"})
_RUN_ID_RE = re.compile(r"^run_id:\s*(?P<run_id>\S+)\s*$")
_SUBPROCESS_TIMEOUT_SECONDS = 300
_REPORT_WATCHER_ATTEMPTS = 3
_REPORT_WATCHER_RETRY_DELAY_SECONDS = 0.25
_REPORT_WATCHERS: set[str] = set()
_REPORT_WATCHER_FAILED_SESSIONS: set[str] = set()
_REPORT_WATCHERS_LOCK = threading.Lock()
_SESSION_LOCK = threading.Lock()
_SESSION_RUNS: dict[str, set[str]] = {}
_SESSION_COMPLETED_RUNS: dict[str, set[str]] = {}

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
    """Normalize a Hermes runtime session id for Orchestra ownership."""
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


def _parse_do_args(raw_args: str) -> dict[str, Any]:
    parts = raw_args.strip().split()
    payload: dict[str, Any] = {"role": "worker"}
    goal_parts: list[str] = []
    index = 0
    while index < len(parts):
        token = parts[index]
        if token == "--role" and index + 1 < len(parts):
            payload["role"] = parts[index + 1]
            index += 2
            continue
        if token == "--timeout" and index + 1 < len(parts):
            try:
                payload["timeout"] = int(parts[index + 1])
            except ValueError:
                payload["timeout"] = parts[index + 1]
            index += 2
            continue
        if token == "--task-label" and index + 1 < len(parts):
            payload["taskLabel"] = parts[index + 1]
            index += 2
            continue
        goal_parts.append(token)
        index += 1
    payload["goal"] = " ".join(goal_parts).strip()
    return payload


def _extract_field(output: str, field: str) -> str | None:
    prefix = f"{field}:"
    for line in output.splitlines():
        trimmed = line.strip()
        if trimmed.startswith(prefix):
            value = trimmed[len(prefix) :].strip()
            if value:
                return value
    return None


def _error(message: str) -> str:
    return json.dumps({"error": message})


def _log_watcher_error(message: str) -> None:
    sys.stderr.write(f"orchestra auto-return watcher failed: {message}\n")


def _log_progress_error(message: str) -> None:
    sys.stderr.write(f"orchestra progress watcher failed: {message}\n")


def _slash_session_id(ctx: Any | None) -> str | None:
    # Hermes slash handlers currently receive only raw user text. Public Hermes does
    # not expose a runtime per-command session id here yet, but interactive CLI keeps
    # the active session id on the private CLI ref. Trust only that in-process CLI
    # runtime object; never read identity from slash args, tool args, or globals.
    manager = getattr(ctx, "_manager", None)
    cli_ref = getattr(manager, "_cli_ref", None)
    raw_session_id = getattr(cli_ref, "session_id", None)
    if not isinstance(raw_session_id, str):
        return None
    try:
        return normalize_hermes_session_id(raw_session_id)
    except ValueError:
        return None


def _track_run(runtime_session_id: str, run_id: str) -> None:
    with _SESSION_LOCK:
        runs = _SESSION_RUNS.setdefault(runtime_session_id, set())
        runs.add(run_id)
        _SESSION_COMPLETED_RUNS.setdefault(runtime_session_id, set())


def _record_completed_run(
    runtime_session_id: str,
    run_id: str,
    active_remaining: int | None,
) -> tuple[int, int]:
    with _SESSION_LOCK:
        completed = _SESSION_COMPLETED_RUNS.setdefault(runtime_session_id, set())
        completed.add(run_id)
        tracked_total = len(_SESSION_RUNS.get(runtime_session_id, set()))
        total = max(tracked_total, len(completed) + (active_remaining or 0))
        if active_remaining == 0:
            _SESSION_RUNS.pop(runtime_session_id, None)
            _SESSION_COMPLETED_RUNS.pop(runtime_session_id, None)
        return len(completed), total


def _emit_progress(ctx: Any, message: str) -> bool:
    notify = getattr(ctx, "notify", None)
    if callable(notify):
        notify(message)
        return True
    ui = getattr(ctx, "ui", None)
    ui_notify = getattr(ui, "notify", None)
    if callable(ui_notify):
        ui_notify(message, "info")
        return True
    return False


def _has_progress_notifier(ctx: Any) -> bool:
    if callable(getattr(ctx, "notify", None)):
        return True
    ui = getattr(ctx, "ui", None)
    return callable(getattr(ui, "notify", None))


def _report_run_id_args(run_ids: list[str]) -> list[str]:
    args: list[str] = []
    for run_id in run_ids:
        args.extend(["--run-id", run_id])
    return args


def _release_session_report(runtime_session_id: str, run_ids: list[str]) -> None:
    if not run_ids:
        return
    result = _run_orchestra(
        [
            "_release-session-report",
            "--session-id",
            runtime_session_id,
            *_report_run_id_args(run_ids),
        ]
    )
    if result.returncode != 0:
        _log_watcher_error((result.stdout or result.stderr).strip() or "report release failed")


def _mark_session_report_delivered(runtime_session_id: str, run_ids: list[str]) -> bool:
    if not run_ids:
        return True
    result = _run_orchestra(
        [
            "_mark-session-report-delivered",
            "--session-id",
            runtime_session_id,
            *_report_run_id_args(run_ids),
        ]
    )
    if result.returncode != 0:
        _log_watcher_error(
            (result.stdout or result.stderr).strip() or "report delivery mark failed"
        )
        return False
    return True


def _inject_report(ctx: Any, message: str) -> bool:
    inject_message = getattr(ctx, "inject_message", None)
    if not callable(inject_message):
        return False
    return bool(inject_message(message, role="user"))


def _handle_session_report_result(
    ctx: Any,
    runtime_session_id: str,
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
            _release_session_report(runtime_session_id, run_ids)
            return
        if not _inject_report(ctx, message.strip()):
            _release_session_report(runtime_session_id, run_ids)
            return
        if not _mark_session_report_delivered(runtime_session_id, run_ids):
            _release_session_report(runtime_session_id, run_ids)
    except Exception as exc:  # noqa: BLE001 - plugin must not crash watcher thread
        _release_session_report(runtime_session_id, run_ids)
        _log_watcher_error(str(exc))


def _watch_session_report(ctx: Any, runtime_session_id: str, run_id: str) -> None:
    try:
        for attempt in range(_REPORT_WATCHER_ATTEMPTS):
            result = _run_orchestra(
                [
                    "_await-session-report",
                    "--session-id",
                    runtime_session_id,
                    "--run-id",
                    run_id,
                    "--json",
                ]
            )
            if result.returncode == 0:
                _handle_session_report_result(ctx, runtime_session_id, result, [run_id])
                with _REPORT_WATCHERS_LOCK:
                    _REPORT_WATCHER_FAILED_SESSIONS.discard(runtime_session_id)
                return
            if attempt == _REPORT_WATCHER_ATTEMPTS - 1:
                _handle_session_report_result(ctx, runtime_session_id, result, [run_id])
                with _REPORT_WATCHERS_LOCK:
                    _REPORT_WATCHER_FAILED_SESSIONS.add(runtime_session_id)
                return
            time.sleep(_REPORT_WATCHER_RETRY_DELAY_SECONDS * (attempt + 1))
    except Exception as exc:  # plugin watcher thread must survive unexpected command failures
        _log_watcher_error(str(exc))
        with _REPORT_WATCHERS_LOCK:
            _REPORT_WATCHER_FAILED_SESSIONS.add(runtime_session_id)
    finally:
        with _REPORT_WATCHERS_LOCK:
            _REPORT_WATCHERS.discard(runtime_session_id)


def _start_session_report_watcher(ctx: Any | None, runtime_session_id: str, run_id: str) -> None:
    if ctx is None:
        return
    with _REPORT_WATCHERS_LOCK:
        if runtime_session_id in _REPORT_WATCHERS:
            return
        _REPORT_WATCHERS.add(runtime_session_id)
    thread = threading.Thread(
        target=_watch_session_report,
        args=(ctx, runtime_session_id, run_id),
        daemon=True,
        name=f"orchestra-report-{run_id}",
    )
    thread.start()


def _session_report_watcher_failed(runtime_session_id: str) -> bool:
    with _REPORT_WATCHERS_LOCK:
        return runtime_session_id in _REPORT_WATCHER_FAILED_SESSIONS


def _watch_run_progress(ctx: Any, runtime_session_id: str, run_id: str) -> None:
    result = _run_orchestra(
        [
            "_await-run",
            "--session-id",
            runtime_session_id,
            "--run-id",
            run_id,
        ]
    )
    if result.returncode != 0:
        error_text = (result.stdout or result.stderr).strip()
        if error_text:
            _log_progress_error(error_text)
        return
    status = _extract_field(result.stdout, "status") or "done"
    role = _extract_field(result.stdout, "role")
    raw_active_remaining = _extract_field(result.stdout, "active_runs_remaining")
    active_remaining = int(raw_active_remaining) if raw_active_remaining is not None else None
    completed, total = _record_completed_run(runtime_session_id, run_id, active_remaining)
    command = [
        "_progress-message",
        "--completed",
        str(completed),
        "--total",
        str(total),
        "--run-id",
        run_id,
        "--status",
        status,
    ]
    if role:
        command.extend(["--role", role])
    message_result = _run_orchestra(command)
    role_text = f" {role}" if role else ""
    message = (
        message_result.stdout.strip()
        if message_result.returncode == 0 and message_result.stdout.strip()
        else f"orchestra:{role_text} {run_id} returned {status} ({completed}/{total})"
    )
    _emit_progress(ctx, message)
    if active_remaining == 0 and _session_report_watcher_failed(runtime_session_id):
        _start_session_report_watcher(ctx, runtime_session_id, run_id)


def _start_run_progress_watcher(ctx: Any | None, runtime_session_id: str, run_id: str) -> None:
    if ctx is None or not _has_progress_notifier(ctx):
        return
    thread = threading.Thread(
        target=_watch_run_progress,
        args=(ctx, runtime_session_id, run_id),
        daemon=True,
        name=f"orchestra-progress-{run_id}",
    )
    thread.start()


def _dispatch_orchestra_run(
    payload: dict[str, Any],
    runtime_session_id: str,
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
        runtime_session_id,
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

    _track_run(runtime_session_id, run_id)
    _start_run_progress_watcher(ctx, runtime_session_id, run_id)
    _start_session_report_watcher(ctx, runtime_session_id, run_id)

    ack = _run_orchestra(["_dispatch-ack", "--run-id", run_id, "--role", role])
    if ack.returncode != 0:
        return _error((ack.stdout or ack.stderr).strip() or "orchestra dispatch ack failed")
    return ack.stdout.strip() or f"orchestra dispatched: {role} {run_id}"


def orch_dispatch(args: dict[str, Any], **kwargs: Any) -> str:
    """Dispatch a worker using only Hermes' runtime tool-call session_id kwarg."""
    supplied_identity_args = sorted(_IDENTITY_ARG_NAMES.intersection(args))
    if supplied_identity_args:
        return _error(
            "identity arguments are not accepted; Hermes runtime session_id is used instead"
        )

    raw_session_id = kwargs.get("session_id")
    if not isinstance(raw_session_id, str):
        return _error("Hermes session_id is required")
    try:
        runtime_session_id = normalize_hermes_session_id(raw_session_id)
    except ValueError:
        return _error("Hermes session_id is required")

    return _dispatch_orchestra_run(args, runtime_session_id, ctx=kwargs.get("_ctx"))


def _orch_command(raw_args: str, ctx: Any | None = None) -> str:
    trimmed = raw_args.strip()
    if not trimmed or trimmed == "help":
        result = _run_orchestra(["help-host"])
        return result.stdout or result.stderr

    parts = trimmed.split(maxsplit=1)
    subcommand = parts[0]
    rest = parts[1] if len(parts) > 1 else ""

    if subcommand == "doctor":
        result = _run_orchestra(["doctor"])
        return result.stdout or result.stderr

    runtime_session_id = _slash_session_id(ctx)
    if runtime_session_id is None:
        return (
            "Hermes /orch requires runtime session context. "
            "Start a new Hermes session or use the orch_dispatch tool."
        )

    if subcommand == "status":
        result = _run_orchestra(["status", "--session-id", runtime_session_id])
        return result.stdout or result.stderr

    if subcommand == "history":
        limit = rest.strip() or "10"
        result = _run_orchestra(
            ["history", "--session-id", runtime_session_id, "--limit", limit]
        )
        return result.stdout or result.stderr

    if subcommand == "stop":
        run_id = rest.strip().split(maxsplit=1)[0] if rest.strip() else ""
        if not run_id:
            return "Usage: /orch stop <run-id>"
        result = _run_orchestra(
            ["stop", "--session-id", runtime_session_id, "--run-id", run_id]
        )
        return result.stdout or result.stderr

    if subcommand == "do":
        payload = _parse_do_args(rest)
        if not str(payload.get("goal", "")).strip():
            return "Usage: /orch do [--role ROLE] [--timeout SEC] [--task-label LABEL] <goal>"
        return _dispatch_orchestra_run(payload, runtime_session_id, ctx=ctx)

    result = _run_orchestra(["help-host"])
    return f"Unknown /orch subcommand: {subcommand}\n\n{result.stdout or result.stderr}"


def register(ctx: Any) -> None:
    """Register Hermes tool, slash command, and report watcher."""
    tool_info = _load_tool_info()

    def dispatch_handler(args: dict[str, Any], **kwargs: Any) -> str:
        kwargs["_ctx"] = ctx
        return orch_dispatch(args, **kwargs)

    def command_handler(raw_args: str) -> str:
        return _orch_command(raw_args, ctx=ctx)

    ctx.register_tool(
        name="orch_dispatch",
        toolset="orchestra",
        schema=_schema(tool_info),
        handler=dispatch_handler,
    )
    ctx.register_command(
        "orch",
        handler=command_handler,
        description="Orchestra host adapter: /orch help|do|status|stop|doctor|history",
    )
