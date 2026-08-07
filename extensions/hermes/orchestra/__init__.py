"""Hermes plugin for safe Orchestra dispatch."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

_IDENTITY_ARG_NAMES = frozenset({"session_id", "identity", "orchestrator_session_id"})
_RUN_ID_RE = re.compile(r"^run_id:\s*(?P<run_id>\S+)\s*$")
_SUBPROCESS_TIMEOUT_SECONDS = 300
_WATCHER_TIMEOUT_MARGIN_SECONDS = 30
_REPORT_WATCHER_ATTEMPTS = 8
_REPORT_WATCHER_RETRY_BASE_DELAY_SECONDS = 0.25
_REPORT_WATCHER_RETRY_MAX_DELAY_SECONDS = 3.0
_REPORT_WATCHERS: set[str] = set()
_REPORT_WATCHERS_LOCK = threading.Lock()

_FALLBACK_TOOL_INFO = {
    "description": "Delegate or dispatch a focused task to an Orchestra worker/subagent.",
    "promptSnippet": "Dispatch focused work to Orchestra workers/subagents.",
    "promptGuidelines": ["Use orch_dispatch for narrow delegated worker tasks."],
    "goalDescription": "Focused worker request/task to delegate.",
    "roleDescription": "(Optional) specific role; omit for default.",
    "taskLabelDescription": "Optional short request label.",
}

_TOOL_TIMEOUT_ERROR = (
    "timeout is not accepted by orch_dispatch; configured default_timeout applies."
)
_ORCHESTRA_WORKER_ENV = "ORCHESTRA_WORKER"


def _orchestra_worker_budget() -> int:
    raw = os.environ.get(_ORCHESTRA_WORKER_ENV, "").strip()
    if not raw:
        return 0
    try:
        budget = int(raw)
    except ValueError:
        return 1
    return max(budget, 0)


def _can_dispatch_orchestra_worker() -> bool:
    return _orchestra_worker_budget() != 1


def normalize_hermes_session_id(raw_session_id: str) -> str:
    """Normalize a Hermes runtime session id for Orchestra ownership."""
    normalized = raw_session_id.strip()
    if not normalized:
        raise ValueError("hermes session id is required")
    if normalized.startswith("hermes:"):
        return normalized
    return f"hermes:{normalized}"


def _source_checkout_root() -> Path | None:
    for candidate in Path(__file__).resolve().parents:
        if (
            (candidate / "config.yaml").exists()
            and (candidate / "prompts.yaml").exists()
            and (candidate / "agent-catalog.yaml").exists()
        ):
            return candidate
    return None


def _hermes_runtime_orchestra_dir() -> Path:
    source_root = _source_checkout_root()
    if source_root is not None:
        return source_root
    return Path(__file__).resolve().parents[2] / "orchestra"


def _orchestra_base_args() -> list[str]:
    args: list[str] = []
    if config := os.environ.get("ORCHESTRA_CONFIG"):
        args.extend(["--config", config])
    else:
        args.extend(["--config", str(_hermes_runtime_orchestra_dir() / "config.yaml")])
    if catalog := os.environ.get("ORCHESTRA_AGENT_CATALOG"):
        args.extend(["--agent-catalog", catalog])
    else:
        args.extend([
            "--agent-catalog",
            str(_hermes_runtime_orchestra_dir() / "agent-catalog.yaml"),
        ])
    return args


def _watcher_wait_budget_seconds(timeout_seconds: int) -> int:
    return timeout_seconds + _WATCHER_TIMEOUT_MARGIN_SECONDS


def _watcher_subprocess_timeout_seconds(wait_budget_seconds: int) -> int:
    return wait_budget_seconds + _WATCHER_TIMEOUT_MARGIN_SECONDS


def _run_orchestra(
    args: list[str],
    *,
    timeout_seconds: int = _SUBPROCESS_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    command = ["orchestra", *_orchestra_base_args(), *args]
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else exc.stdout or ""
        return subprocess.CompletedProcess(
            args=command,
            returncode=124,
            stdout=stdout,
            stderr=f"orchestra command timed out after {timeout_seconds} seconds",
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
                "taskLabel": {
                    "type": "string",
                    "description": str(tool_info["taskLabelDescription"]),
                },
            },
            "required": ["goal"],
        },
    }


def _extract_dispatch_timeout_seconds(output: str) -> int:
    timeout_text = _extract_field(output, "timeout_seconds")
    if not timeout_text:
        raise ValueError("orchestra do output did not include timeout_seconds")
    if not timeout_text.isdigit() or int(timeout_text) <= 0:
        raise ValueError("timeout_seconds must be a positive integer")
    return int(timeout_text)


def _extract_run_id(output: str) -> str | None:
    for line in output.splitlines():
        match = _RUN_ID_RE.match(line.strip())
        if match:
            return match.group("run_id")
    return None


def _parse_do_args(raw_args: str) -> dict[str, Any]:
    normalized_args = raw_args.replace(r'\"', '"')
    try:
        parts = shlex.split(normalized_args)
    except ValueError:
        return {"error": "Malformed quoted string in /orch do arguments"}
    payload: dict[str, Any] = {}
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


def _cli_ref(ctx: Any) -> Any | None:
    manager = getattr(ctx, "_manager", None)
    return getattr(manager, "_cli_ref", None)


def _session_is_busy(ctx: Any) -> bool:
    cli_ref = _cli_ref(ctx)
    return bool(getattr(cli_ref, "_agent_running", False))


def _steer_report(ctx: Any, message: str) -> bool:
    """Deliver a report message via Hermes steer without interrupting the active turn."""
    cli_ref = _cli_ref(ctx)
    agent = getattr(cli_ref, "agent", None)
    steer = getattr(agent, "steer", None)
    if not callable(steer):
        return False
    return bool(steer(message))


def _inject_report(ctx: Any, message: str) -> bool:
    inject_message = getattr(ctx, "inject_message", None)
    if not callable(inject_message):
        return False
    return bool(inject_message(message, role="user"))


def _deliver_report(ctx: Any, message: str) -> bool:
    if _session_is_busy(ctx):
        return _steer_report(ctx, message)
    return _inject_report(ctx, message)


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
        if not _deliver_report(ctx, message.strip()):
            _release_session_report(runtime_session_id, run_ids)
            return
        if not _mark_session_report_delivered(runtime_session_id, run_ids):
            _release_session_report(runtime_session_id, run_ids)
    except Exception as exc:  # noqa: BLE001 - plugin must not crash watcher thread
        _release_session_report(runtime_session_id, run_ids)
        _log_watcher_error(str(exc))


def _watch_session_report(
    ctx: Any,
    runtime_session_id: str,
    run_id: str,
    wait_budget_seconds: int,
) -> None:
    try:
        for attempt in range(_REPORT_WATCHER_ATTEMPTS):
            result = _run_orchestra(
                [
                    "_await-session-report",
                    "--session-id",
                    runtime_session_id,
                    "--run-id",
                    run_id,
                    "--timeout",
                    str(wait_budget_seconds),
                    "--json",
                ],
                timeout_seconds=_watcher_subprocess_timeout_seconds(wait_budget_seconds),
            )
            if result.returncode == 0:
                _handle_session_report_result(ctx, runtime_session_id, result, [run_id])
                return
            if attempt == _REPORT_WATCHER_ATTEMPTS - 1:
                _handle_session_report_result(ctx, runtime_session_id, result, [run_id])
                return
            time.sleep(_report_watcher_retry_delay_seconds(attempt))
    except Exception as exc:  # plugin watcher thread must survive unexpected command failures
        _log_watcher_error(str(exc))
    finally:
        with _REPORT_WATCHERS_LOCK:
            _REPORT_WATCHERS.discard(runtime_session_id)


def _report_watcher_retry_delay_seconds(attempt: int) -> float:
    return min(
        _REPORT_WATCHER_RETRY_BASE_DELAY_SECONDS * (2**attempt),
        _REPORT_WATCHER_RETRY_MAX_DELAY_SECONDS,
    )


def _start_session_report_watcher(
    ctx: Any | None,
    runtime_session_id: str,
    run_id: str,
    wait_budget_seconds: int,
) -> None:
    if ctx is None:
        return
    with _REPORT_WATCHERS_LOCK:
        if runtime_session_id in _REPORT_WATCHERS:
            return
        _REPORT_WATCHERS.add(runtime_session_id)
    thread = threading.Thread(
        target=_watch_session_report,
        args=(ctx, runtime_session_id, run_id, wait_budget_seconds),
        daemon=True,
        name=f"orchestra-report-{run_id}",
    )
    thread.start()


def _dispatch_orchestra_run(
    payload: dict[str, Any],
    runtime_session_id: str,
    ctx: Any | None = None,
    *,
    allow_timeout: bool = False,
) -> str:
    goal = str(payload.get("goal", "")).strip()
    if not goal:
        return _error("goal is required")

    timeout = payload.get("timeout")
    if timeout is not None:
        if not allow_timeout:
            return _error(_TOOL_TIMEOUT_ERROR)
        if type(timeout) is not int or timeout <= 0:
            return _error("timeout must be a positive integer")

    requested_role = str(payload.get("role") or "").strip()
    command = [
        "do",
        "--session-id",
        runtime_session_id,
        "--goal",
        goal,
    ]
    if requested_role:
        command.extend(["--role", requested_role])
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

    dispatch_timeout = _extract_dispatch_timeout_seconds(result.stdout)
    wait_budget_seconds = _watcher_wait_budget_seconds(dispatch_timeout)
    _start_session_report_watcher(ctx, runtime_session_id, run_id, wait_budget_seconds)

    effective_role = _extract_field(result.stdout, "role") or requested_role or "worker"
    ack = _run_orchestra(["_dispatch-ack", "--run-id", run_id, "--role", effective_role])
    if ack.returncode != 0:
        return _error((ack.stdout or ack.stderr).strip() or "orchestra dispatch ack failed")
    return ack.stdout.strip() or f"orchestra dispatched: {effective_role} {run_id}"


def orch_dispatch(args: dict[str, Any], **kwargs: Any) -> str:
    """Dispatch a worker using Hermes runtime session_id and configured default timeout."""
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

    if subcommand == "roles":
        if rest.strip():
            try:
                role_args = shlex.split(rest)
            except ValueError as exc:
                return f"Invalid /orch roles arguments: {exc}"
            result = _run_orchestra(["roles", *role_args])
        else:
            result = _run_orchestra(["roles", "--all"])
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
        if "error" in payload:
            return str(payload["error"])
        if not str(payload.get("goal", "")).strip():
            return "Usage: /orch do [--role ROLE] [--timeout SEC] [--task-label LABEL] <goal>"
        return _dispatch_orchestra_run(
            payload,
            runtime_session_id,
            ctx=ctx,
            allow_timeout=True,
        )

    result = _run_orchestra(["help-host"])
    return f"Unknown /orch subcommand: {subcommand}\n\n{result.stdout or result.stderr}"


def register(ctx: Any) -> None:
    """Register Hermes tool, slash command, and report watcher."""

    def dispatch_handler(args: dict[str, Any], **kwargs: Any) -> str:
        kwargs.setdefault("_ctx", ctx)
        return orch_dispatch(args, **kwargs)

    def command_handler(raw_args: str) -> str:
        return _orch_command(raw_args, ctx=ctx)

    if _can_dispatch_orchestra_worker():
        tool_info = _load_tool_info()
        ctx.register_tool(
            name="orch_dispatch",
            toolset="orchestra",
            schema=_schema(tool_info),
            handler=dispatch_handler,
        )
    ctx.register_command(
        "orch",
        handler=command_handler,
        description="Orchestra host adapter: /orch help|do|roles|status|stop|doctor|history",
    )
