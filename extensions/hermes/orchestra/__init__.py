"""Hermes plugin for safe Orchestra dispatch."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

_IDENTITY_ARG_NAMES = frozenset({"session_id", "identity", "orchestrator_session_id"})
_SUBPROCESS_TIMEOUT_SECONDS = 300
_WATCHER_TIMEOUT_MARGIN_SECONDS = 30
_REPORT_WATCHER_ATTEMPTS = 8
_REPORT_WATCHER_RETRY_BASE_DELAY_SECONDS = 0.25
_REPORT_WATCHER_RETRY_MAX_DELAY_SECONDS = 3.0
_REPORT_WATCHERS: set[str] = set()
_REPORT_WATCHERS_LOCK = threading.Lock()
_SESSION_WATCHER_GENERATIONS: dict[str, int] = {}
_SESSION_WATCHER_GENERATIONS_LOCK = threading.Lock()


class _BudgetState:
    __slots__ = (
        "turn_budget",
        "soft_timeout_seconds",
        "session_started_at",
        "budget_prompt_delivered",
    )

    def __init__(
        self,
        turn_budget: int,
        soft_timeout_seconds: int,
        session_started_at: float,
        budget_prompt_delivered: bool,
    ) -> None:
        self.turn_budget = turn_budget
        self.soft_timeout_seconds = soft_timeout_seconds
        self.session_started_at = session_started_at
        self.budget_prompt_delivered = budget_prompt_delivered


_BUDGET_STATES: dict[str, _BudgetState] = {}
_BUDGET_STATES_LOCK = threading.Lock()
_ORCH_ON_ACTIVE_SESSIONS: set[str] = set()
_ORCH_ON_ACTIVE_SESSIONS_LOCK = threading.Lock()
_ORCH_DISABLED_SESSIONS: set[str] = set()
_ORCH_DISABLED_SESSIONS_LOCK = threading.Lock()

_ORCH_COMMAND_ARGS_HINT = (
    "help | on | off | do [--role ROLE] [--timeout SEC] [--task-label LABEL] <goal> | "
    "roles ... | status | stop <run-id> | doctor | history [LIMIT]"
)

_ORCHESTRA_DISPATCH_BUDGET_ENV = "ORCHESTRA_DISPATCH_BUDGET"
_ORCHESTRA_TURN_BUDGET_ENV = "ORCHESTRA_TURN_BUDGET"
_ORCHESTRA_SOFT_TIMEOUT_SECONDS_ENV = "ORCHESTRA_SOFT_TIMEOUT_SECONDS"
_ORCHESTRA_BUDGET_EXCEEDED_PROMPT_ENV = "ORCHESTRA_BUDGET_EXCEEDED_PROMPT"


def _parse_budget_env(name: str) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return 0
    try:
        budget = int(raw)
    except ValueError:
        return 1
    return budget if budget >= 0 else 1


def _budget_exceeded_prompt_message(reason: str, budget_trigger_label: str) -> str | None:
    prompt = os.environ.get(_ORCHESTRA_BUDGET_EXCEEDED_PROMPT_ENV, "").strip()
    if not prompt:
        return None
    return f"{prompt}\n\n{budget_trigger_label}: {reason}"


def _hook_session_id(ctx: Any | None, kwargs: dict[str, Any]) -> str | None:
    raw_session_id = kwargs.get("session_id")
    if isinstance(raw_session_id, str):
        try:
            return normalize_hermes_session_id(raw_session_id)
        except ValueError:
            return None
    if ctx is None:
        return None
    return _slash_session_id(ctx)


def _reset_budget_state(runtime_session_id: str) -> None:
    with _BUDGET_STATES_LOCK:
        _BUDGET_STATES[runtime_session_id] = _BudgetState(
            turn_budget=_parse_budget_env(_ORCHESTRA_TURN_BUDGET_ENV),
            soft_timeout_seconds=_parse_budget_env(_ORCHESTRA_SOFT_TIMEOUT_SECONDS_ENV),
            session_started_at=time.monotonic(),
            budget_prompt_delivered=False,
        )


def _budget_state(runtime_session_id: str) -> _BudgetState:
    state = _BUDGET_STATES.get(runtime_session_id)
    if state is None:
        state = _BudgetState(
            turn_budget=_parse_budget_env(_ORCHESTRA_TURN_BUDGET_ENV),
            soft_timeout_seconds=_parse_budget_env(_ORCHESTRA_SOFT_TIMEOUT_SECONDS_ENV),
            session_started_at=time.monotonic(),
            budget_prompt_delivered=False,
        )
        _BUDGET_STATES[runtime_session_id] = state
    return state


def _clear_budget_state(runtime_session_id: str) -> None:
    with _BUDGET_STATES_LOCK:
        _BUDGET_STATES.pop(runtime_session_id, None)


def _orch_on_mark_active(runtime_session_id: str) -> bool:
    with _ORCH_ON_ACTIVE_SESSIONS_LOCK:
        if runtime_session_id in _ORCH_ON_ACTIVE_SESSIONS:
            return False
        _ORCH_ON_ACTIVE_SESSIONS.add(runtime_session_id)
        return True


def _orch_on_clear(runtime_session_id: str) -> None:
    with _ORCH_ON_ACTIVE_SESSIONS_LOCK:
        _ORCH_ON_ACTIVE_SESSIONS.discard(runtime_session_id)


def _orch_dispatch_disable(runtime_session_id: str) -> None:
    with _ORCH_DISABLED_SESSIONS_LOCK:
        _ORCH_DISABLED_SESSIONS.add(runtime_session_id)


def _orch_dispatch_enable(runtime_session_id: str) -> bool:
    with _ORCH_DISABLED_SESSIONS_LOCK:
        if runtime_session_id not in _ORCH_DISABLED_SESSIONS:
            return False
        _ORCH_DISABLED_SESSIONS.discard(runtime_session_id)
        return True


def _orch_dispatch_is_disabled(runtime_session_id: str) -> bool:
    with _ORCH_DISABLED_SESSIONS_LOCK:
        return runtime_session_id in _ORCH_DISABLED_SESSIONS


def _core_dispatch_disabled(payload: Any) -> bool:
    """Resolve dispatch gating from core `_tool-info` session-mode keys."""
    if not isinstance(payload, dict):
        return False
    mode = payload.get("mainSessionMode")
    if isinstance(mode, str) and mode in {"off", "on", "orchestrator"}:
        return mode == "off"
    return payload.get("toolsEnabledByDefault") is False


def _apply_core_session_mode_gating(runtime_session_id: str) -> None:
    """Apply per-session dispatch gating from core main-session mode.

    Core `off` disables local orchestration dispatch; any other resolvable
    state keeps it enabled. A failed or raising core call falls back to
    enabled so an unavailable core never locks out the host adapter.
    """
    payload: Any = None
    try:
        result = _run_orchestra(["_tool-info", "--session-id", runtime_session_id])
        if result.returncode == 0 and result.stdout.strip():
            payload = json.loads(result.stdout)
    except Exception:
        payload = None
    if _core_dispatch_disabled(payload):
        _orch_dispatch_disable(runtime_session_id)
    else:
        _orch_dispatch_enable(runtime_session_id)


def _record_core_session_mode(runtime_session_id: str, mode: str) -> str | None:
    """Record a session mode in core; return a warning message on failure."""
    try:
        result = _run_orchestra(
            ["_session-mode", "set", "--session-id", runtime_session_id, "--mode", mode]
        )
    except Exception as exc:  # noqa: BLE001 - plugin must not crash on helper failure
        return f"could not record session mode in core (helper raised: {exc})"
    if result.returncode == 0:
        return None
    detail = " ".join((result.stderr or "").split()) or f"exit code {result.returncode}"
    return f"could not record session mode in core ({detail})"


def _orchestra_dispatch_budget() -> int:
    return _parse_budget_env(_ORCHESTRA_DISPATCH_BUDGET_ENV)


def _can_dispatch_orchestra_worker() -> bool:
    return _orchestra_dispatch_budget() != 1


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
    error = "failed to load orch_dispatch and orch_status metadata from orchestra _tool-info"
    result = _run_orchestra(["_tool-info"])
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(error)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(error) from exc
    return payload


def _tool_timeout_error() -> str:
    return str(_load_tool_info()["dispatchTimeoutError"])


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


def _status_schema(tool_info: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": "orch_status",
        "description": str(tool_info["statusDescription"]),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["on", "status", "history", "help", "doctor", "roles", "stop"],
                    "description": str(tool_info["statusActionDescription"]),
                },
                "limit": {
                    "type": "integer",
                    "description": str(tool_info["statusLimitDescription"]),
                },
                "runId": {
                    "type": "string",
                    "description": str(tool_info["statusRunIdDescription"]),
                },
                "role": {
                    "type": "string",
                    "description": str(tool_info["statusRoleDescription"]),
                },
                "setting": {
                    "type": "string",
                    "description": str(tool_info["statusSettingDescription"]),
                },
                "value": {
                    "type": "string",
                    "description": str(tool_info["statusValueDescription"]),
                },
            },
            "required": ["action"],
        },
    }


def _normalize_status_limit(limit: Any) -> str:
    if type(limit) is int:
        if limit <= 0:
            raise ValueError("limit must be a positive integer")
        return str(limit)
    if isinstance(limit, str):
        normalized = limit.strip()
        if not normalized.isdigit() or int(normalized) <= 0:
            raise ValueError("limit must be a positive integer")
        return normalized
    raise ValueError("limit must be a positive integer")


def _filter_role_lines(output: str) -> str:
    return output.strip()


def _orch_status_error(reason: str) -> str:
    return f"Hermes /orch status failed: {reason}"


def _orch_status_runtime_session_id(raw_session_id: Any) -> str | None:
    if not isinstance(raw_session_id, str):
        return None
    try:
        return normalize_hermes_session_id(raw_session_id)
    except ValueError:
        return None


def _extract_dispatch_timeout_seconds(output: str) -> int:
    try:
        payload = _parse_dispatch_payload(output)
        timeout_seconds = payload.get("timeout_seconds")
        if type(timeout_seconds) is int and timeout_seconds > 0:
            return timeout_seconds
    except ValueError:
        pass
    timeout_text = _extract_field(output, "timeout_seconds")
    if not timeout_text:
        raise ValueError("orchestra do output did not include timeout_seconds")
    if not timeout_text.isdigit() or int(timeout_text) <= 0:
        raise ValueError("timeout_seconds must be a positive integer")
    return int(timeout_text)


def _extract_run_id(output: str) -> str | None:
    try:
        payload = _parse_dispatch_payload(output)
        run_id = payload.get("run_id")
        if isinstance(run_id, str) and run_id.strip():
            return run_id.strip()
    except ValueError:
        pass
    return _extract_field(output, "run_id")


def _parse_dispatch_payload(output: str) -> dict[str, Any]:
    payload = json.loads(output)
    if not isinstance(payload, dict):
        raise ValueError("dispatch payload must be a JSON object")
    return payload


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


def _current_session_watcher_generation(runtime_session_id: str) -> int:
    with _SESSION_WATCHER_GENERATIONS_LOCK:
        return _SESSION_WATCHER_GENERATIONS.get(runtime_session_id, 0)


def _invalidate_session_watcher_generation(runtime_session_id: str) -> None:
    with _SESSION_WATCHER_GENERATIONS_LOCK:
        _SESSION_WATCHER_GENERATIONS[runtime_session_id] = (
            _SESSION_WATCHER_GENERATIONS.get(runtime_session_id, 0) + 1
        )


def _session_watcher_generation_is_current(runtime_session_id: str, generation: int) -> bool:
    with _SESSION_WATCHER_GENERATIONS_LOCK:
        return _SESSION_WATCHER_GENERATIONS.get(runtime_session_id, 0) == generation


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


def _runtime_session_key(runtime_session_id: str | None) -> str | None:
    if not runtime_session_id:
        return None
    value = runtime_session_id.strip()
    if value.startswith("hermes:"):
        value = value[len("hermes:") :]
    return value or None


def _cli_ref_matches_session(cli_ref: Any, runtime_session_id: str | None) -> bool:
    session_key = _runtime_session_key(runtime_session_id)
    if session_key is None:
        return True
    raw_session_id = getattr(cli_ref, "session_id", None)
    if not isinstance(raw_session_id, str) or not raw_session_id.strip():
        return True
    return _runtime_session_key(raw_session_id) == session_key


def _tui_live_session(runtime_session_id: str | None) -> dict[str, Any] | None:
    session_key = _runtime_session_key(runtime_session_id)
    if session_key is None:
        return None
    try:
        from tui_gateway import server as tui_server  # type: ignore
    except Exception:
        return None
    find_live = getattr(tui_server, "_find_live_session_by_key", None)
    if callable(find_live):
        try:
            live = find_live(session_key)
        except Exception:
            live = None
        if live is not None:
            try:
                return live[1]
            except Exception:
                return None
    sessions = getattr(tui_server, "_sessions", None)
    if not isinstance(sessions, dict):
        return None
    lock = getattr(tui_server, "_sessions_lock", None)
    try:
        if lock is None:
            items = list(sessions.items())
        else:
            with lock:
                items = list(sessions.items())
    except Exception:
        return None
    for sid, session in items:
        if not isinstance(session, dict) or session.get("_finalized"):
            continue
        if sid == session_key or session.get("session_key") == session_key:
            return session
        agent = session.get("agent")
        if getattr(agent, "session_id", None) == session_key:
            return session
    return None


def _session_is_busy(ctx: Any, runtime_session_id: str | None = None) -> bool:
    cli_ref = _cli_ref(ctx)
    if _cli_ref_matches_session(cli_ref, runtime_session_id) and bool(
        getattr(cli_ref, "_agent_running", False)
    ):
        return True
    live_session = _tui_live_session(runtime_session_id)
    return bool(live_session and live_session.get("running"))


def _queue_report(ctx: Any, message: str) -> bool:
    """Queue a report as the next Hermes CLI turn without interrupting the active turn."""
    cli_ref = _cli_ref(ctx)
    pending_input = getattr(cli_ref, "_pending_input", None)
    put = getattr(pending_input, "put", None)
    if not callable(put):
        return False
    put(message)
    return True


def _steer_report(ctx: Any, message: str, runtime_session_id: str | None = None) -> bool:
    cli_ref = _cli_ref(ctx)
    if _cli_ref_matches_session(cli_ref, runtime_session_id):
        agent = getattr(cli_ref, "agent", None)
        steer = getattr(agent, "steer", None)
        if callable(steer):
            try:
                return bool(steer(message))
            except Exception:
                return False
    live_session = _tui_live_session(runtime_session_id)
    agent = live_session.get("agent") if live_session else None
    steer = getattr(agent, "steer", None)
    if not callable(steer):
        return False
    try:
        return bool(steer(message))
    except Exception:
        return False


def _inject_report(ctx: Any, message: str) -> bool:
    inject_message = getattr(ctx, "inject_message", None)
    if not callable(inject_message):
        return False
    try:
        return bool(inject_message(message, role="user"))
    except Exception:
        return False


def _deliver_report(ctx: Any, runtime_session_id: str, message: str) -> bool:
    if _session_is_busy(ctx, runtime_session_id):
        return _steer_report(ctx, message, runtime_session_id) or _queue_report(ctx, message)
    return _inject_report(ctx, message)


def _handle_session_report_result(
    ctx: Any,
    runtime_session_id: str,
    result: subprocess.CompletedProcess[str],
    fallback_run_ids: list[str] | None = None,
    *,
    session_generation: int | None = None,
) -> None:
    if session_generation is None:
        session_generation = _current_session_watcher_generation(runtime_session_id)
    if not _session_watcher_generation_is_current(runtime_session_id, session_generation):
        return
    if result.returncode != 0:
        error_text = (result.stdout or result.stderr).strip()
        if error_text:
            _log_watcher_error(error_text)
        return

    if not _session_watcher_generation_is_current(runtime_session_id, session_generation):
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
            if _session_watcher_generation_is_current(runtime_session_id, session_generation):
                _release_session_report(runtime_session_id, run_ids)
            return
        if not _session_watcher_generation_is_current(runtime_session_id, session_generation):
            return
        if not _deliver_report(ctx, runtime_session_id, message.strip()):
            if _session_watcher_generation_is_current(runtime_session_id, session_generation):
                _release_session_report(runtime_session_id, run_ids)
            return
        if not _session_watcher_generation_is_current(runtime_session_id, session_generation):
            return
        if not _mark_session_report_delivered(runtime_session_id, run_ids):
            if _session_watcher_generation_is_current(runtime_session_id, session_generation):
                _release_session_report(runtime_session_id, run_ids)
    except Exception as exc:  # noqa: BLE001 - plugin must not crash watcher thread
        if _session_watcher_generation_is_current(runtime_session_id, session_generation):
            _release_session_report(runtime_session_id, run_ids)
            _log_watcher_error(str(exc))


def _watch_session_report(
    ctx: Any,
    runtime_session_id: str,
    run_id: str,
    wait_budget_seconds: int,
    session_generation: int | None = None,
) -> None:
    try:
        if session_generation is None:
            session_generation = _current_session_watcher_generation(runtime_session_id)
        if not _session_watcher_generation_is_current(runtime_session_id, session_generation):
            return
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
            if not _session_watcher_generation_is_current(runtime_session_id, session_generation):
                return
            if result.returncode == 0:
                _handle_session_report_result(
                    ctx,
                    runtime_session_id,
                    result,
                    [run_id],
                    session_generation=session_generation,
                )
                return
            if attempt == _REPORT_WATCHER_ATTEMPTS - 1:
                _handle_session_report_result(
                    ctx,
                    runtime_session_id,
                    result,
                    [run_id],
                    session_generation=session_generation,
                )
                return
            if not _session_watcher_generation_is_current(runtime_session_id, session_generation):
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
    session_generation = _current_session_watcher_generation(runtime_session_id)
    with _REPORT_WATCHERS_LOCK:
        if runtime_session_id in _REPORT_WATCHERS:
            return
        _REPORT_WATCHERS.add(runtime_session_id)
    thread = threading.Thread(
        target=_watch_session_report,
        args=(ctx, runtime_session_id, run_id, wait_budget_seconds, session_generation),
        daemon=True,
        name=f"orchestra-report-{run_id}",
    )
    thread.start()


def _on_session_cleanup(**kwargs: Any) -> None:
    raw_session_id = kwargs.get("session_id")
    if not isinstance(raw_session_id, str):
        return
    try:
        runtime_session_id = normalize_hermes_session_id(raw_session_id)
    except ValueError:
        return
    _invalidate_session_watcher_generation(runtime_session_id)
    _clear_budget_state(runtime_session_id)
    _orch_on_clear(runtime_session_id)
    _orch_dispatch_enable(runtime_session_id)
    with _REPORT_WATCHERS_LOCK:
        _REPORT_WATCHERS.discard(runtime_session_id)


def _dispatch_orchestra_run(
    payload: dict[str, Any],
    runtime_session_id: str,
    ctx: Any | None = None,
    *,
    allow_timeout: bool = False,
) -> str:
    if _orch_dispatch_is_disabled(runtime_session_id):
        return _error(
            "Hermes orch_dispatch is disabled for this session; run /orch on to enable it again"
        )

    goal = str(payload.get("goal", "")).strip()
    if not goal:
        return _error("goal is required")

    timeout = payload.get("timeout")
    if timeout is not None:
        if not allow_timeout:
            return _error(_tool_timeout_error())
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

    command.append("--json")
    result = _run_orchestra(command)
    if result.returncode != 0:
        return _error((result.stdout or result.stderr).strip() or "orchestra dispatch failed")

    run_id = _extract_run_id(result.stdout)
    if not run_id:
        return _error("orchestra dispatch did not return a run_id")

    try:
        dispatch = _parse_dispatch_payload(result.stdout)
    except (ValueError, json.JSONDecodeError):
        dispatch = {}

    try:
        dispatch_timeout = _extract_dispatch_timeout_seconds(result.stdout)
    except ValueError as exc:
        return _error(str(exc))
    wait_budget_seconds = _watcher_wait_budget_seconds(dispatch_timeout)
    _start_session_report_watcher(ctx, runtime_session_id, run_id, wait_budget_seconds)

    effective_role = str(
        dispatch.get("role")
        or _extract_field(result.stdout, "role")
        or requested_role
        or "worker"
    ).strip() or "worker"
    ack = _run_orchestra(["_dispatch-ack", "--run-id", run_id, "--role", effective_role])
    if ack.returncode != 0:
        return _error((ack.stdout or ack.stderr).strip() or "orchestra dispatch ack failed")
    if not ack.stdout.strip():
        return _error("orchestra dispatch ack failed")
    return ack.stdout.strip()


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


def _orch_on_error(reason: str) -> str:
    return f"Hermes /orch on failed: {reason}"


def _orch_on(ctx: Any | None, runtime_session_id: str) -> str:
    if _orch_dispatch_is_disabled(runtime_session_id):
        warning = _record_core_session_mode(runtime_session_id, "on")
        _orch_dispatch_enable(runtime_session_id)
        _orch_on_clear(runtime_session_id)
        message = (
            'Hermes /orch on succeeded: Orchestra dispatch enabled for this session. '
            'Run "/orch on" again to inject the orchestrator skill'
        )
        if warning is not None:
            message += f"\nWarning: {warning}"
        return message

    if not _orch_on_mark_active(runtime_session_id):
        return "Hermes /orch on already active for this session"

    success = False
    try:
        try:
            result = _run_orchestra(["_orchestrator-skill"])
        except Exception as exc:  # noqa: BLE001 - plugin must not crash on helper failure
            return _orch_on_error(f"orchestrator skill helper raised: {exc}")
        if result.returncode != 0:
            return _orch_on_error("orchestrator skill helper failed")
        try:
            payload = result.stdout.strip()
        except Exception as exc:
            return _orch_on_error(f"orchestrator skill payload processing raised: {exc}")
        if not payload:
            return _orch_on_error("orchestrator skill payload was empty")
        try:
            inject_message = getattr(ctx, "inject_message", None)
            if not callable(inject_message):
                return _orch_on_error("ctx.inject_message is unavailable")
            injected = inject_message(payload, role="user")
        except Exception as exc:  # noqa: BLE001 - plugin must not crash on inject failure
            return _orch_on_error(f"ctx.inject_message raised: {exc}")
        if not injected:
            return _orch_on_error("ctx.inject_message returned False")
        success = True
        warning = _record_core_session_mode(runtime_session_id, "orchestrator")
        message = "Hermes /orch on succeeded: orchestrator skill injected"
        if warning is not None:
            message += f"\nWarning: {warning}"
        return message
    finally:
        if not success:
            _orch_on_clear(runtime_session_id)


def orch_status(args: dict[str, Any], **kwargs: Any) -> str:
    supplied_identity_args = sorted(_IDENTITY_ARG_NAMES.intersection(args))
    if supplied_identity_args:
        return _orch_status_error(
            "identity arguments are not accepted; Hermes runtime session_id is used instead"
        )

    action = str(args.get("action") or "").strip()
    if not action:
        return _orch_status_error("action is required")

    if action not in {"on", "status", "history", "help", "doctor", "roles", "stop"}:
        return _orch_status_error(f"unsupported action: {action}")

    runtime_session_id: str | None = None
    if action in {"on", "status", "history", "stop"}:
        runtime_session_id = _orch_status_runtime_session_id(kwargs.get("session_id"))
        if runtime_session_id is None:
            return _orch_status_error("Hermes session_id is required")

    if action == "on":
        return _orch_on(kwargs.get("_ctx"), runtime_session_id)

    if action == "status":
        result = _run_orchestra(["status", "--session-id", runtime_session_id])
        return result.stdout or result.stderr

    if action == "history":
        limit = args.get("limit")
        limit_text = "10" if limit is None else _normalize_status_limit(limit)
        result = _run_orchestra(
            ["history", "--session-id", runtime_session_id, "--limit", limit_text]
        )
        return result.stdout or result.stderr

    if action == "help":
        result = _run_orchestra(["help-host"])
        return result.stdout or result.stderr

    if action == "doctor":
        result = _run_orchestra(["doctor"])
        return result.stdout or result.stderr

    if action == "roles":
        result = _run_orchestra(["roles", "--all"])
        return _filter_role_lines(result.stdout or result.stderr)

    run_id = str(args.get("runId") or "").strip()
    if not run_id:
        return _orch_status_error("runId is required for orch_status stop")
    result = _run_orchestra(["stop", "--session-id", runtime_session_id, "--run-id", run_id])
    return result.stdout or result.stderr


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

    if subcommand == "on":
        return _orch_on(ctx, runtime_session_id)

    if subcommand == "off":
        _orch_dispatch_disable(runtime_session_id)
        _orch_on_clear(runtime_session_id)
        message = (
            "Hermes /orch off succeeded: Orchestra dispatch disabled for this session"
        )
        if warning := _record_core_session_mode(runtime_session_id, "off"):
            message += f"\nWarning: {warning}"
        return message

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
    """Register Hermes tool, slash command, hooks, and report watcher."""

    def dispatch_handler(args: dict[str, Any], **kwargs: Any) -> str:
        kwargs.setdefault("_ctx", ctx)
        return orch_dispatch(args, **kwargs)

    def status_handler(args: dict[str, Any], **kwargs: Any) -> str:
        kwargs.setdefault("_ctx", ctx)
        return orch_status(args, **kwargs)

    def command_handler(raw_args: str) -> str:
        return _orch_command(raw_args, ctx=ctx)

    initial_session_id = _slash_session_id(ctx)
    if initial_session_id is not None:
        _reset_budget_state(initial_session_id)
        _apply_core_session_mode_gating(initial_session_id)

    def inject_budget_prompt(reason: str) -> bool:
        message = _budget_exceeded_prompt_message(reason, budget_trigger_label)
        if not message:
            return False
        inject_message = getattr(ctx, "inject_message", None)
        if not callable(inject_message):
            return False
        try:
            return bool(inject_message(message, role="user"))
        except Exception:
            return False

    def pre_tool_call_handler(**_kwargs: Any) -> dict[str, str] | None:
        runtime_session_id = _hook_session_id(ctx, _kwargs)
        if runtime_session_id is None:
            return None
        with _BUDGET_STATES_LOCK:
            state = _budget_state(runtime_session_id)
            elapsed = time.monotonic() - state.session_started_at
            if state.soft_timeout_seconds <= 0 or elapsed < state.soft_timeout_seconds:
                return None
            if state.budget_prompt_delivered:
                return {"action": "block", "message": soft_timeout_block_reason}
            state.budget_prompt_delivered = True
        inject_budget_prompt("soft_timeout")
        return {"action": "block", "message": soft_timeout_block_reason}

    def pre_llm_call_handler(**_kwargs: Any) -> dict[str, str] | None:
        runtime_session_id = _hook_session_id(ctx, _kwargs)
        if runtime_session_id is None:
            return None
        message: str | None = None
        with _BUDGET_STATES_LOCK:
            state = _budget_state(runtime_session_id)
            if state.budget_prompt_delivered:
                return None
            if state.turn_budget > 1:
                state.turn_budget -= 1
                return None
            message = _budget_exceeded_prompt_message("turn_limit", budget_trigger_label)
            if message is None:
                return None
            state.budget_prompt_delivered = True
        inject_message = getattr(ctx, "inject_message", None)
        if callable(inject_message):
            try:
                injected = inject_message(message, role="user")
            except Exception:
                injected = False
            if injected:
                return None
        return {"context": message}

    def on_session_start_handler(**_kwargs: Any) -> None:
        runtime_session_id = _hook_session_id(ctx, _kwargs)
        if runtime_session_id is None:
            return
        _reset_budget_state(runtime_session_id)
        _apply_core_session_mode_gating(runtime_session_id)

    tool_info = _load_tool_info()
    budget_trigger_label = str(tool_info["budgetTriggerLabel"])
    soft_timeout_block_reason = str(tool_info["softTimeoutBlockReason"])
    if _can_dispatch_orchestra_worker():
        ctx.register_tool(
            name="orch_dispatch",
            toolset="orchestra",
            schema=_schema(tool_info),
            handler=dispatch_handler,
        )
    ctx.register_tool(
        name="orch_status",
        toolset="orchestra",
        schema=_status_schema(tool_info),
        handler=status_handler,
    )
    ctx.register_command(
        "orch",
        handler=command_handler,
        description=(
            "Orchestra host adapter: /orch help|on|off|do|roles|status|stop|doctor|history "
            "(use /orch on to inject the orchestrator skill)"
        ),
        args_hint=_ORCH_COMMAND_ARGS_HINT,
    )
    register_hook = getattr(ctx, "register_hook", None)
    if callable(register_hook):
        register_hook("on_session_finalize", _on_session_cleanup)
        register_hook("on_session_reset", _on_session_cleanup)
        register_hook("on_session_start", on_session_start_handler)
        register_hook("pre_tool_call", pre_tool_call_handler)
        register_hook("pre_llm_call", pre_llm_call_handler)
