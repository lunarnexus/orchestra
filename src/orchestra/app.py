"""Application service layer for Orchestra CLI."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from orchestra.config import (
    AgentCatalog,
    AppConfig,
    ConfigError,
    RoleConfig,
    default_pi_orchestra_dir,
    load_agent_catalog,
    load_app_config,
    resolve_agent_catalog_path,
    resolve_config_path,
)
from orchestra.harnesses import (
    HarnessLoadError,
    HarnessRegistry,
    WorkerProcess,
    WorkerRequest,
    WorkerResult,
    register_builtin_harnesses,
)
from orchestra.harnesses.common import (
    SKILL_FILENAME,
    SKILL_LIBRARY_DIR,
    compact_summary,
    orchestra_can_dispatch,
    summary_was_truncated,
)
from orchestra.harnesses.processes import process_group_id
from orchestra.logs import utc_now
from orchestra.state import (
    ACTIVE_STATUSES,
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_RUNNING,
    ConcurrencyLimitError,
    RunRecord,
    RunUpdate,
    StateStore,
)

REPORT_HEADER = "Orchestra session report"
WORKER_EMPTY_RESULT_ERROR = "Worker exited successfully without a meaningful result"
WORKER_EMPTY_RESULT_BLOCKER = "Worker protocol error: empty result"
ROLE_USAGE = """Usage:
  /orch roles
  /orch roles ROLE SETTING VALUE

Settings:
  harness   selected harness config name
  enabled   true/false
  model     model name for the selected harness
  profile   optional harness profile, when supported
  agent     optional harness agent, when supported

Examples:
  /orch roles reviewer harness pi
  /orch roles appsec enabled false
  /orch roles reviewer model openai-codex/gpt-5.4

Enabled values:
  true, yes, y, 1, on
  false, no, n, 0, off"""

class AppError(ValueError):
    """Raised for user-facing application errors."""


@dataclass(frozen=True)
class OrchestraPaths:
    config_path: Path
    catalog_path: Path


@dataclass(frozen=True)
class AppContext:
    config: AppConfig
    catalog: AgentCatalog
    store: StateStore
    registry: HarnessRegistry
    paths: OrchestraPaths


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class InitFileResult:
    source: Path
    target: Path
    action: str
    mode: str


@dataclass(frozen=True)
class InitPiResult:
    files: list[InitFileResult]
    verification_command: str


@dataclass(frozen=True)
class InitHermesResult:
    files: list[InitFileResult]
    command: list[str]
    stdout: str
    stderr: str
    verification_command: str


@dataclass(frozen=True)
class InitOpencodeResult:
    files: list[InitFileResult]
    verification_command: str


@dataclass(frozen=True)
class InitAllResult:
    pi: InitPiResult | None
    hermes: list[InitHermesResult]
    opencode: InitOpencodeResult | None


@dataclass(frozen=True)
class ToolInfo:
    description: str
    prompt_snippet: str
    prompt_guidelines: list[str]
    goal_description: str
    role_description: str
    task_label_description: str


@dataclass(frozen=True)
class PendingRunRequest:
    run_id: str
    role_name: str
    goal: str
    approved_context: str
    boundaries: str
    acceptance_target: str
    return_format: str
    timeout_seconds: int
    task_label: str
    request_file: Path


@dataclass(frozen=True)
class SessionReport:
    run_ids: list[str]
    text: str


@dataclass(frozen=True)
class StartedRun:
    record: RunRecord
    request_file: Path
    timeout_seconds: int


@dataclass(frozen=True)
class SelectedRole:
    name: str
    config: RoleConfig


def create_default_registry() -> HarnessRegistry:
    return register_builtin_harnesses(HarnessRegistry())


def load_context(
    *,
    config_path: str | Path | None = None,
    catalog_path: str | Path | None = None,
    registry: HarnessRegistry | None = None,
) -> AppContext:
    config_file = resolve_config_path(config_path)
    catalog_file = resolve_agent_catalog_path(catalog_path)
    config = load_app_config(config_file)
    catalog = load_agent_catalog(catalog_file)
    store = StateStore(config.state_dir / "orchestra.db")
    store.initialize()
    return AppContext(
        config=config,
        catalog=catalog,
        store=store,
        registry=registry or create_default_registry(),
        paths=OrchestraPaths(config_path=config_file, catalog_path=catalog_file),
    )


def start_run(
    context: AppContext,
    *,
    session_id: str,
    role_name: str | None,
    goal: str,
    approved_context: str,
    boundaries: str,
    acceptance_target: str,
    return_format: str,
    timeout_seconds: int | None,
    task_label: str,
    batch_id: str | None,
) -> StartedRun:
    _require_session_id(session_id)
    if not orchestra_can_dispatch():
        raise AppError("ORCHESTRA_DISPATCH_BUDGET dispatch budget exhausted")
    selected_role = _select_role(context.catalog, role_name)
    role = selected_role.config

    run_id = uuid.uuid4().hex[:12]
    log_path = context.config.log_dir / f"{run_id}.jsonl"
    effective_task_label = task_label.strip() or _default_task_label(goal)
    request_dir = context.config.state_dir / "requests"
    request_dir.mkdir(parents=True, exist_ok=True)
    request_file = request_dir / f"{run_id}.json"
    pending_request = PendingRunRequest(
        run_id=run_id,
        role_name=selected_role.name,
        goal=goal,
        approved_context=approved_context,
        boundaries=boundaries,
        acceptance_target=acceptance_target,
        return_format=return_format,
        timeout_seconds=timeout_seconds or context.config.default_timeout,
        task_label=effective_task_label,
        request_file=request_file,
    )

    record = RunRecord(
        run_id=run_id,
        orchestrator_session_id=session_id,
        batch_id=batch_id,
        harness=role.harness,
        role=selected_role.name,
        model=role.model,
        task_label=effective_task_label,
        log_path=log_path,
        created_at=utc_now(),
    )

    try:
        context.store.reserve_run(
            record,
            global_limit=context.config.concurrency.global_limit,
            per_session_limit=context.config.concurrency.per_session_limit,
            per_model_limits={
                model: limit.concurrency
                for model, limit in context.catalog.model_limits.items()
            },
        )
    except ConcurrencyLimitError as exc:
        raise AppError(str(exc)) from exc

    request_file.write_text(
        json.dumps(
            {
                "run_id": pending_request.run_id,
                "role_name": pending_request.role_name,
                "goal": pending_request.goal,
                "approved_context": pending_request.approved_context,
                "boundaries": pending_request.boundaries,
                "acceptance_target": pending_request.acceptance_target,
                "return_format": pending_request.return_format,
                "timeout_seconds": pending_request.timeout_seconds,
                "task_label": pending_request.task_label,
            }
        ),
        encoding="utf-8",
    )
    _spawn_supervisor(context, request_file, run_id)
    return StartedRun(
        record=record,
        request_file=request_file,
        timeout_seconds=pending_request.timeout_seconds,
    )


def run_supervisor(context: AppContext, *, run_id: str, request_file: str | Path) -> RunRecord:
    record = context.store.get_run(run_id)
    if record.status not in ACTIVE_STATUSES:
        return record

    pending_request = _load_pending_request(run_id, Path(request_file))
    selected_role = _select_role(context.catalog, record.role)
    fallback_note: str | None = None

    try:
        started_role, worker = _start_worker_process(
            context,
            selected_role,
            pending_request,
            log_path=record.log_path,
        )
    except AppError as exc:
        startup_failures = [str(exc)]
        last_failure_text = str(exc)
        attempted_role = selected_role
        started_role = None
        worker = None

        for fallback_role in _fallback_roles_for(context.catalog, selected_role):
            candidate_note = _fallback_note(
                role_name=selected_role.name,
                fallback_harness_config=fallback_role.config.harness_config,
                failed_harness=attempted_role.config.harness,
            )
            try:
                started_role, worker = _start_worker_process(
                    context,
                    fallback_role,
                    pending_request,
                    log_path=record.log_path,
                )
                fallback_note = candidate_note
                break
            except AppError as fallback_exc:
                startup_failures.append(
                    "fallback harness_config "
                    f"{fallback_role.config.harness_config} also failed: {fallback_exc}"
                )
                last_failure_text = str(fallback_exc)
                attempted_role = fallback_role

        if started_role is None or worker is None:
            _safe_unlink(pending_request.request_file)
            return _finalize_supervisor_setup_failure(
                context,
                run_id,
                error_text="; ".join(startup_failures),
                blocker_text=_setup_failure_blocker(last_failure_text),
            )

    assert started_role is not None
    assert worker is not None
    pgid = process_group_id(worker.process.pid)
    updated = context.store.update_run(
        run_id,
        RunUpdate(
            status=STATUS_RUNNING,
            harness=started_role.config.harness,
            role=started_role.name,
            process_id=worker.process.pid,
            process_group_id=pgid,
            worker_session_id=worker.worker_session_id,
            transcript_path=worker.transcript_path,
            approval_needed=worker.approval_needed,
            blocker_text=fallback_note,
        ),
    )
    if updated.status != STATUS_RUNNING:
        _terminate_worker(worker.process, pgid)
        _safe_unlink(pending_request.request_file)
        return updated

    try:
        stdout, stderr = worker.process.communicate(timeout=pending_request.timeout_seconds)
    except subprocess.TimeoutExpired:
        stdout, stderr = _terminate_subprocess(worker.process, pgid)
        result = WorkerResult(
            status=STATUS_FAILED,
            command=worker.command,
            prompt=worker.prompt,
            exit_code=None,
            stdout=stdout,
            stderr=stderr,
            result_summary=compact_summary(stdout),
            error_text="Worker timed out",
            blocker_text="Worker exceeded timeout",
            result_summary_truncated=False,
            timed_out=True,
            worker_session_id=worker.worker_session_id,
            transcript_path=worker.transcript_path,
            approval_needed=worker.approval_needed,
        )
    else:
        result = _result_from_completed_worker(worker, stdout, stderr)

    if fallback_note:
        result = _annotate_result_with_fallback(result, fallback_note)

    _safe_unlink(pending_request.request_file)
    return _finalize_run(context, record.run_id, result)


def stop_run(context: AppContext, session_id: str, run_id: str) -> RunRecord:
    _require_session_id(session_id)
    record = context.store.get_run(run_id)
    if record.orchestrator_session_id != session_id:
        raise AppError("run does not belong to the provided session_id")
    if record.status not in ACTIVE_STATUSES:
        raise AppError("run is not active")

    cancelled = context.store.update_run(
        run_id,
        RunUpdate(status=STATUS_CANCELLED, blocker_text="Cancelled by orchestra stop"),
    )
    if record.process_id is not None:
        _terminate_owned_process(record.process_id, record.process_group_id)
    return cancelled


def format_run_report(record: RunRecord) -> str:
    lines = [
        f"run_id: {record.run_id}",
        f"status: {record.status}",
        f"session_id: {record.orchestrator_session_id}",
        f"role: {record.role}",
        f"harness: {record.harness}",
        f"task: {record.task_label}",
        f"created_at: {record.created_at}",
        f"log_path: {record.log_path}",
    ]
    if record.started_at:
        lines.append(f"started_at: {record.started_at}")
    if record.ended_at:
        lines.append(f"ended_at: {record.ended_at}")
    if record.process_id is not None:
        lines.append(f"process_id: {record.process_id}")
    if record.process_group_id is not None:
        lines.append(f"process_group_id: {record.process_group_id}")
    if record.result_summary:
        result = record.result_summary
        if record.result_summary_truncated:
            result = f"{result} [truncated]"
        lines.append(f"result: {result}")
    if record.result_summary_truncated and record.result_artifact_path:
        lines.append(f"result_artifact_path: {record.result_artifact_path}")
    if record.error_text:
        lines.append(f"error: {record.error_text}")
    if record.blocker_text:
        lines.append(f"blocker: {record.blocker_text}")
    if record.worker_session_id:
        lines.append(f"worker_session_id: {record.worker_session_id}")
    if record.transcript_path:
        lines.append(f"transcript_path: {record.transcript_path}")
    return "\n".join(lines)


def format_started_run(started: StartedRun) -> str:
    lines = [
        format_run_report(started.record),
        f"timeout_seconds: {started.timeout_seconds}",
        f"request_file: {started.request_file}",
        "dispatch: queued for supervision",
    ]
    return "\n".join(lines)


def format_dispatch_ack(run_id: str, *, role: str | None = None) -> str:
    role_text = f" {role}" if role else ""
    return f"orchestra dispatched:{role_text} {run_id}"


def format_progress_notification(
    *,
    completed_count: int,
    total_count: int,
    run_id: str,
    status: str,
    role: str | None = None,
) -> str:
    role_text = f" {role}" if role else ""
    return f"orchestra:{role_text} {run_id} returned {status} ({completed_count}/{total_count})"


def clean_result_summary(summary: str | None) -> str:
    if not summary:
        return "-"
    cleaned = re.sub(r"\bBlockers?:\s*(None|none|No blockers?\.?)", "", summary)
    cleaned = re.sub(r"\bRisks?:\s*(None|none|No risks?\.?)", "", cleaned)
    cleaned = re.sub(r"[^\x09\x0A\x0D\x20-\x7E]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "-"


def format_orchestrator_return(runs: list[RunRecord]) -> str:
    if not runs:
        return "[orchestra: all background processes returned]"
    blocks = []
    for run in runs:
        outcome = "success" if run.status == STATUS_DONE else "fail"
        summary = _format_run_summary(run)
        label = "Result" if outcome == "success" else "Summary"
        lines = [
            f"[orchestra: Worker {run.run_id} {outcome}]",
            f"Request: {run.task_label}",
            f"{label}: {summary}",
        ]
        full_result_line = _full_result_line(run)
        if full_result_line:
            lines.append(full_result_line)
        if run.worker_session_id:
            lines.append(f"Worker session: {run.worker_session_id}")
        lines.append(f"Log: {run.log_path}")
        blocks.append("\n".join(lines))
    report = "\n\n".join(blocks)
    if len(runs) == 1:
        return report
    return f"[orchestra: {len(runs)} workers returned]\n\n{report}"


def _format_run_summary(run: RunRecord) -> str:
    summary = clean_result_summary(run.blocker_text or run.error_text or run.result_summary)
    if run.result_summary_truncated:
        return f"{summary} [truncated]"
    return summary


def _full_result_line(run: RunRecord) -> str | None:
    if run.result_summary_truncated and run.result_artifact_path:
        return f"Full result: {run.result_artifact_path}"
    return None


def build_session_report(session_id: str, runs: list[RunRecord], *, active_remaining: int) -> str:
    lines = [
        REPORT_HEADER,
        f"session_id: {session_id}",
        f"reported_runs: {len(runs)}",
        f"active_runs_remaining: {active_remaining}",
    ]
    if not runs:
        lines.append("runs: none")
        return "\n".join(lines)

    lines.append("runs:")
    for run in runs:
        summary = _format_run_summary(run)
        lines.append(
            f"- {run.run_id} [{run.status}] {run.role} :: {run.task_label} :: {summary}"
        )
        full_result_line = _full_result_line(run)
        if full_result_line:
            lines.append(f"  {full_result_line}")
        if run.worker_session_id:
            lines.append(f"  worker_session_id: {run.worker_session_id}")
        lines.append(f"  log: {run.log_path}")
    if active_remaining == 0:
        lines.append("session_report: all active workers for this session are complete")
    return "\n".join(lines)


def pending_session_report(context: AppContext, session_id: str) -> SessionReport | None:
    _require_session_id(session_id)
    if not context.config.auto_return:
        return None
    runs = context.store.claim_pending_report_runs(session_id)
    if not runs:
        return None
    return SessionReport(
        run_ids=[run.run_id for run in runs],
        text=format_orchestrator_return(runs),
    )


def mark_session_report_delivered(
    context: AppContext,
    session_id: str,
    run_ids: list[str],
) -> None:
    _require_session_id(session_id)
    context.store.mark_report_runs_delivered(session_id, run_ids)


def release_session_report(context: AppContext, session_id: str, run_ids: list[str]) -> None:
    _require_session_id(session_id)
    context.store.release_report_runs(session_id, run_ids)


def consume_pending_session_report(context: AppContext, session_id: str) -> str | None:
    _require_session_id(session_id)
    if not context.config.auto_return:
        return None
    runs = context.store.consume_pending_report_runs(session_id)
    if not runs:
        return None
    return format_orchestrator_return(runs)


def await_run_terminal_status(
    context: AppContext,
    session_id: str,
    *,
    run_id: str,
    poll_interval: float = 0.1,
    timeout_seconds: float | None = None,
) -> tuple[RunRecord, int]:
    _require_session_id(session_id)
    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds

    while True:
        record = context.store.get_run(run_id)
        if record.orchestrator_session_id != session_id:
            raise AppError("run does not belong to the provided session_id")
        if record.status not in ACTIVE_STATUSES:
            return record, context.store.count_active_runs(session_id)
        if deadline is not None and time.monotonic() >= deadline:
            raise AppError("timed out waiting for run completion")
        time.sleep(poll_interval)


_SESSION_REPORT_DB_OPEN_RETRY_LIMIT = 3


def await_session_report_payload(
    context: AppContext,
    session_id: str,
    *,
    run_id: str,
    poll_interval: float = 0.1,
    timeout_seconds: float | None = None,
) -> SessionReport | None:
    _require_session_id(session_id)
    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
    db_open_failures = 0
    last_db_open_error: sqlite3.OperationalError | None = None

    while True:
        try:
            record = context.store.get_run(run_id)
            if record.orchestrator_session_id != session_id:
                raise AppError("run does not belong to the provided session_id")

            if record.status not in ACTIVE_STATUSES:
                if context.store.count_active_runs(session_id) == 0:
                    return pending_session_report(context, session_id)
            db_open_failures = 0
            last_db_open_error = None
        except sqlite3.OperationalError as exc:
            if not _is_transient_session_report_db_open_error(context, exc):
                raise
            db_open_failures += 1
            last_db_open_error = exc
            if db_open_failures > _SESSION_REPORT_DB_OPEN_RETRY_LIMIT:
                raise

        if deadline is not None and time.monotonic() >= deadline:
            if last_db_open_error is not None:
                raise last_db_open_error
            raise AppError("timed out waiting for session report")
        time.sleep(poll_interval)


def _is_transient_session_report_db_open_error(
    context: AppContext,
    exc: sqlite3.OperationalError,
) -> bool:
    if "unable to open database file" not in str(exc).lower():
        return False
    database_path = getattr(context.store, "database_path", None)
    if database_path is None:
        return True
    return Path(database_path).parent.exists()


def await_session_report(
    context: AppContext,
    session_id: str,
    *,
    run_id: str,
    poll_interval: float = 0.1,
    timeout_seconds: float | None = None,
) -> str | None:
    report = await_session_report_payload(
        context,
        session_id,
        run_id=run_id,
        poll_interval=poll_interval,
        timeout_seconds=timeout_seconds,
    )
    return report.text if report else None


def format_status(context: AppContext, session_id: str) -> str:
    _require_session_id(session_id)
    lineage_session_ids = _orchestrator_lineage_session_ids(session_id)
    runs = _list_active_runs_for_session_ids(context, lineage_session_ids)
    lines = [f"session_id: {session_id}"]
    if len(lineage_session_ids) > 1:
        lines.append(f"lineage_current_session_id: {lineage_session_ids[-1]}")
        lines.append(f"lineage_session_ids: {', '.join(lineage_session_ids)}")
    lines.extend(
        [
            f"active_runs: {len(runs)}",
            f"global_active_runs: {len(context.store.list_active_runs())}",
        ]
    )
    if not runs:
        lines.append("status: no active runs")
        return "\n".join(lines)

    lines.append("runs:")
    for run in runs:
        pid = f" pid={run.process_id}" if run.process_id is not None else ""
        owner = (
            f" session={run.orchestrator_session_id}" if len(lineage_session_ids) > 1 else ""
        )
        blocker = f" blocker={run.blocker_text}" if run.blocker_text else ""
        lines.append(
            f"- {run.run_id} [{run.status}] {run.role} :: {run.task_label}{pid}{owner}{blocker}"
        )
    return "\n".join(lines)


def role_metadata(context: AppContext) -> dict[str, list[str]]:
    return {
        "roles": sorted(context.catalog.roles),
        "harnessConfigs": sorted(context.catalog.harness_configs),
    }


def format_roles(context: AppContext, *, include_disabled: bool = False) -> str:
    enabled_roles = _enabled_roles(context.catalog)
    disabled_roles = [
        (role_name, role)
        for role_name, role in sorted(context.catalog.roles.items())
        if not role.enabled
    ]

    visible_roles = [*enabled_roles, *(disabled_roles if include_disabled else [])]
    lines = ["Configured roles", f"Default: {context.catalog.default_role}", ""]
    if visible_roles:
        lines.extend(_format_role_lines(context, visible_roles))
    else:
        lines.append("  - none")
    return "\n".join(lines)


def set_role_setting(context: AppContext, role_name: str, setting: str, value: str) -> str:
    role_key = role_name.strip()
    if role_key not in context.catalog.roles:
        raise AppError(f"unknown role: {role_key}")

    raw_catalog = _load_catalog_mapping(context.paths.catalog_path)
    roles_raw = raw_catalog.get("roles")
    if not isinstance(roles_raw, dict):
        raise AppError("agent catalog roles must be a mapping")
    role_raw = roles_raw.get(role_key)
    if not isinstance(role_raw, dict):
        raise AppError(f"role '{role_key}' must be a mapping")

    if setting == "enabled":
        enabled = _parse_user_toggle_bool(value, setting_name="enabled")
        if not enabled and role_key == context.catalog.default_role:
            raise AppError(f"cannot disable default role: {role_key}")
        role_raw["enabled"] = enabled
        changed = f"enabled={str(enabled).lower()}"
    elif setting == "model":
        model = value.strip()
        if not model:
            raise AppError("model must be a non-empty string")
        role_raw["model"] = model
        changed = f"model={model}"
    elif setting == "profile":
        profile = value.strip()
        if not profile:
            raise AppError("profile must be a non-empty string")
        role_raw["profile"] = profile
        changed = f"profile={profile}"
    elif setting == "agent":
        agent = value.strip()
        if not agent:
            raise AppError("agent must be a non-empty string")
        role_raw["agent"] = agent
        changed = f"agent={agent}"
    elif setting == "harness":
        harness_config = value.strip()
        if not harness_config:
            raise AppError("harness must be a non-empty string")
        harness_configs_raw = raw_catalog.get("harness_configs")
        if not isinstance(harness_configs_raw, dict):
            raise AppError("agent catalog harness_configs must be a mapping")
        if harness_config not in harness_configs_raw:
            raise AppError(f"unknown harness config: {harness_config}")
        role_raw["harness_config"] = harness_config
        changed = f"harness_config={harness_config}"
    else:
        raise AppError(
            "role setting must be one of: harness, enabled, model, profile, agent"
        )

    _write_catalog_mapping(context.paths.catalog_path, raw_catalog)
    updated_catalog = load_agent_catalog(context.paths.catalog_path)
    updated_context = replace(context, catalog=updated_catalog)
    roles_output = format_roles(updated_context, include_disabled=True)
    return f"Updated role {role_key}: {changed}\n\n{roles_output}"


def _load_catalog_mapping(path: Path) -> dict[str, object]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AppError(f"agent catalog not found: {path}") from exc
    if not isinstance(loaded, dict):
        raise AppError(f"agent catalog must contain a mapping: {path}")
    return loaded


def _write_catalog_mapping(path: Path, catalog: dict[str, object]) -> None:
    path.write_text(yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8")


def _parse_user_toggle_bool(value: str, *, setting_name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "yes", "y", "1", "on"}:
        return True
    if normalized in {"false", "no", "n", "0", "off"}:
        return False
    raise AppError(
        f"{setting_name} must be one of true/yes/y/1/on or false/no/n/0/off; got {value!r}"
    )


def _format_role_lines(
    context: AppContext,
    roles: list[tuple[str, RoleConfig]],
) -> list[str]:
    lines: list[str] = []
    for index, (role_name, role) in enumerate(roles):
        if index:
            lines.append("")
        if role_name == context.catalog.default_role:
            role_marker = "D"
        else:
            role_marker = "✓" if role.enabled else "✗"
        lines.append(f"  {role_marker}  {role_name} [{role.harness}]")
        if role.harness_config:
            lines.append(f"      harness: {role.harness_config}")
        if role.model:
            lines.append(f"      model: {role.model}")
        if role.profile:
            lines.append(f"      profile: {role.profile}")
        if role.agent:
            lines.append(f"      agent: {role.agent}")
        if role.worker_budget is not None:
            lines.append(f"      worker_budget: {role.worker_budget}")
        if role.skills:
            lines.append(f"      skills: {', '.join(role.skills)}")
        if role.env:
            env_values = ", ".join(
                f"{key}={value}" for key, value in sorted(role.env.items())
            )
            lines.append(f"      env: {env_values}")
    return lines


def format_host_help(context: AppContext) -> str:
    return context.config.prompts.host_help.format(
        roles=format_roles(context),
        role_usage=ROLE_USAGE,
    )


def format_command_echo(raw_command: str) -> str:
    raw = raw_command.strip()
    if not raw:
        return "/orch"
    return f"/orch {raw}"


def tool_info(context: AppContext) -> ToolInfo:
    roles = format_roles(context)
    prompts = context.config.prompts
    return ToolInfo(
        description=prompts.tool_description.format(roles=roles),
        prompt_snippet=prompts.tool_prompt_snippet.format(roles=roles),
        prompt_guidelines=list(prompts.tool_prompt_guidelines),
        goal_description=prompts.tool_goal_description,
        role_description=prompts.tool_role_description.format(roles=roles),
        task_label_description=prompts.tool_task_label_description,
    )


def render_orchestrator_skill_message(
    *,
    cwd: str | Path | None = None,
    source_root: str | Path | None = None,
) -> str:
    skill_path = _resolve_orchestrator_skill_path(cwd=cwd, source_root=source_root)
    try:
        skill_text = skill_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise AppError(f"orchestrator skill file not found: {skill_path}") from exc
    return f"Load this Orchestra main-session skill:\n\n{skill_text}"


def _resolve_orchestrator_skill_path(
    *,
    cwd: str | Path | None = None,
    source_root: str | Path | None = None,
) -> Path:
    candidates = _orchestrator_skill_candidates(cwd=cwd, source_root=source_root)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    looked = ", ".join(str(candidate) for candidate in candidates)
    raise AppError(f"orchestrator skill file not found; looked for: {looked}")


def _orchestrator_skill_candidates(
    *,
    cwd: str | Path | None = None,
    source_root: str | Path | None = None,
) -> list[Path]:
    search_root = Path(cwd).resolve() if cwd is not None else Path.cwd().resolve()
    candidates: list[Path] = []
    seen: set[Path] = set()

    def add_candidate(root: Path) -> None:
        candidate = root / SKILL_LIBRARY_DIR / "orchestrator" / SKILL_FILENAME
        if candidate not in seen:
            candidates.append(candidate)
            seen.add(candidate)

    for root in (search_root, *search_root.parents):
        add_candidate(root)

    resolved_source_root = Path(source_root) if source_root is not None else _find_source_root()
    if resolved_source_root is not None:
        add_candidate(resolved_source_root.resolve())

    return candidates


def format_history(context: AppContext, session_id: str, limit: int) -> str:
    _require_session_id(session_id)
    lineage_session_ids = _orchestrator_lineage_session_ids(session_id)
    runs = _list_runs_for_session_ids(context, lineage_session_ids, limit=limit)
    lines = [f"session_id: {session_id}"]
    if len(lineage_session_ids) > 1:
        lines.append(f"lineage_current_session_id: {lineage_session_ids[-1]}")
        lines.append(f"lineage_session_ids: {', '.join(lineage_session_ids)}")
    lines.append(f"history_count: {len(runs)}")
    if not runs:
        lines.append("history: no runs found")
        return "\n".join(lines)

    lines.append("runs:")
    for run in runs:
        summary = _format_run_summary(run)
        owner = (
            f" session={run.orchestrator_session_id}" if len(lineage_session_ids) > 1 else ""
        )
        lines.append(
            f"- {run.run_id} [{run.status}] {run.role}{owner} :: {run.task_label} :: {summary}"
        )
        full_result_line = _full_result_line(run)
        if full_result_line:
            lines.append(f"  {full_result_line}")
        if run.worker_session_id:
            lines.append(f"  worker_session_id: {run.worker_session_id}")
        lines.append(f"  log: {run.log_path}")
    return "\n".join(lines)


def _list_active_runs_for_session_ids(
    context: AppContext,
    session_ids: list[str],
) -> list[RunRecord]:
    if len(session_ids) == 1:
        return context.store.list_active_runs(session_ids[0])
    runs = [
        run
        for lineage_session_id in session_ids
        for run in context.store.list_active_runs(lineage_session_id)
    ]
    return sorted(runs, key=lambda run: (run.created_at, run.run_id))


def _list_runs_for_session_ids(
    context: AppContext,
    session_ids: list[str],
    *,
    limit: int,
) -> list[RunRecord]:
    if len(session_ids) == 1:
        return context.store.list_runs(session_ids[0], limit=limit)
    runs = [
        run
        for lineage_session_id in session_ids
        for run in context.store.list_runs(lineage_session_id, limit=limit)
    ]
    runs.sort(key=lambda run: (run.created_at, run.run_id), reverse=True)
    return runs[:limit]


def _orchestrator_lineage_session_ids(session_id: str) -> list[str]:
    if not session_id.startswith("hermes:"):
        return [session_id]

    raw_session_id = session_id.removeprefix("hermes:")
    try:
        raw_ids = _read_hermes_compression_lineage(raw_session_id)
    except (OSError, sqlite3.Error):
        return [session_id]
    if len(raw_ids) <= 1:
        return [session_id]
    return [f"hermes:{raw_id}" for raw_id in raw_ids]


def _read_hermes_compression_lineage(session_id: str) -> list[str]:
    db_path = _hermes_state_db_path()
    if not db_path.exists():
        return [session_id]

    with sqlite3.connect(
        f"file:{db_path}?mode=ro",
        uri=True,
        timeout=0.25,
    ) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        rows = connection.execute(
            "SELECT id, parent_session_id, started_at, ended_at, end_reason FROM sessions"
        ).fetchall()

    by_id = {str(row["id"]): row for row in rows if row["id"]}
    if session_id not in by_id:
        return [session_id]

    root_id = _hermes_compression_root_id(session_id, by_id)
    return _hermes_compression_descendant_ids(root_id, by_id)


def _hermes_state_db_path() -> Path:
    explicit_home = os.environ.get("HERMES_HOME", "").strip()
    if explicit_home:
        return Path(explicit_home).expanduser() / "state.db"

    root_home = Path.home() / ".hermes"
    try:
        active_profile = (root_home / "active_profile").read_text(encoding="utf-8").strip()
    except OSError:
        active_profile = ""
    if active_profile and active_profile != "default":
        return root_home / "profiles" / active_profile / "state.db"
    return root_home / "state.db"


def _hermes_compression_root_id(session_id: str, by_id: dict[str, sqlite3.Row]) -> str:
    current = session_id
    seen: set[str] = set()
    while current not in seen:
        seen.add(current)
        row = by_id.get(current)
        if row is None:
            return current
        parent_id = row["parent_session_id"]
        if not parent_id or str(parent_id) not in by_id:
            return current
        parent = by_id[str(parent_id)]
        if not _hermes_is_compression_edge(parent, row):
            return current
        current = str(parent_id)
    return current


def _hermes_compression_descendant_ids(root_id: str, by_id: dict[str, sqlite3.Row]) -> list[str]:
    children_by_parent: dict[str, list[sqlite3.Row]] = {}
    for row in by_id.values():
        parent_id = row["parent_session_id"]
        if parent_id:
            children_by_parent.setdefault(str(parent_id), []).append(row)

    lineage_ids: list[str] = []
    stack = [root_id]
    seen: set[str] = set()
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        lineage_ids.append(current)
        parent = by_id.get(current)
        if parent is None:
            continue
        children = [
            row
            for row in children_by_parent.get(current, [])
            if _hermes_is_compression_edge(parent, row)
        ]
        children.sort(
            key=lambda row: (float(row["started_at"] or 0.0), str(row["id"])),
            reverse=True,
        )
        stack.extend(str(row["id"]) for row in children)

    return sorted(
        lineage_ids,
        key=lambda raw_id: (float(by_id[raw_id]["started_at"] or 0.0), raw_id),
    )


def _hermes_is_compression_edge(parent: sqlite3.Row, child: sqlite3.Row) -> bool:
    parent_ended_at = _optional_float(parent["ended_at"])
    child_started_at = _optional_float(child["started_at"])
    return (
        parent["end_reason"] == "compression"
        and parent_ended_at is not None
        and child_started_at is not None
        and child_started_at >= parent_ended_at
    )


def _optional_float(value: object) -> float | None:
    if not isinstance(value, (int, float, str, bytes)):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def init_pi(
    *,
    force: bool = False,
    copy: bool = False,
    source_root: str | Path | None = None,
) -> InitPiResult:
    source_paths = _init_source_paths(source_root)
    config_source_paths = _config_source_paths(source_root, copy=copy)
    pi_dir = default_pi_orchestra_dir().parent

    files = [
        _copy_init_file(
            source_paths["extension"],
            pi_dir / "extensions" / "orchestra" / "index.ts",
            force=force,
        ),
        *_materialize_runtime_config(
            config_source_paths,
            _runtime_config_targets(default_pi_orchestra_dir()),
            force=force,
            copy=copy,
        ),
    ]
    return InitPiResult(
        files=files,
        verification_command='pi --no-approve -p "/orch help"',
    )


def init_hermes(
    *,
    profile: str | None = None,
    force: bool = False,
    copy: bool = False,
    source_root: str | Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> InitHermesResult:
    hermes_profile = _normalized_optional_profile(profile)
    config_source_paths = _config_source_paths(source_root, copy=copy)
    plugin_source = "lunarnexus/orchestra/extensions/hermes/orchestra"
    command = ["hermes"]
    if hermes_profile is not None:
        command.extend(["-p", hermes_profile])
    command.extend(["plugins", "install", plugin_source, "--enable"])
    if force:
        command.append("--force")

    try:
        result = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError as exc:
        raise AppError("hermes command not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise AppError("hermes plugin install timed out") from exc

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if result.returncode != 0:
        detail = stderr or stdout or f"hermes exited with status {result.returncode}"
        raise AppError(f"Hermes plugin install failed: {detail}")

    files = _materialize_runtime_config(
        config_source_paths,
        _runtime_config_targets(default_hermes_orchestra_dir(hermes_profile)),
        force=force,
        copy=copy,
    )

    verify_command = (
        f"hermes -p {hermes_profile} plugins list"
        if hermes_profile is not None
        else "hermes plugins list"
    )
    return InitHermesResult(
        files=files,
        command=command,
        stdout=stdout,
        stderr=stderr,
        verification_command=verify_command,
    )


def init_opencode(
    *,
    force: bool = False,
    copy: bool = False,
    source_root: str | Path | None = None,
) -> InitOpencodeResult:
    root = _find_source_root(source_root)
    if root is None:
        raise AppError("opencode init source root not found; rerun from a source checkout")

    files = [
        _copy_init_file(
            root / "extensions" / "opencode" / "orchestra" / "index.ts",
            default_opencode_orchestra_dir() / "index.ts",
            force=force,
        )
    ]
    return InitOpencodeResult(files=files, verification_command="opencode --help")


def init_all(
    *,
    force: bool = False,
    copy: bool = False,
    catalog_path: str | Path | None = None,
    source_root: str | Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> InitAllResult:
    source_root_path = _find_source_root(source_root)
    resolved_catalog = (
        source_root_path / "agent-catalog.yaml"
        if catalog_path is None and source_root_path is not None
        else resolve_agent_catalog_path(catalog_path)
    )
    catalog = load_agent_catalog(resolved_catalog)
    harnesses = {role.harness for role in catalog.roles.values()}

    pi_result = (
        init_pi(force=force, copy=copy, source_root=source_root)
        if "pi" in harnesses
        else None
    )

    hermes_profiles = sorted(
        {
            role.profile.strip()
            for role in catalog.roles.values()
            if role.harness == "hermes" and role.profile is not None and role.profile.strip()
        }
    )
    include_default_hermes = any(
        role.harness == "hermes" and _normalized_optional_profile(role.profile) is None
        for role in catalog.roles.values()
    )
    hermes_results: list[InitHermesResult] = []
    if include_default_hermes:
        hermes_results.append(
            init_hermes(
                force=force,
                copy=copy,
                source_root=source_root,
                runner=runner,
            )
        )
    hermes_results.extend(
        init_hermes(
            profile=hermes_profile,
            force=force,
            copy=copy,
            source_root=source_root,
            runner=runner,
        )
        for hermes_profile in hermes_profiles
    )

    opencode_result = (
        init_opencode(force=force, copy=copy, source_root=source_root)
        if "opencode" in harnesses
        else None
    )
    return InitAllResult(pi=pi_result, hermes=hermes_results, opencode=opencode_result)


def run_doctor(
    *,
    config_path: str | Path | None = None,
    catalog_path: str | Path | None = None,
    registry: HarnessRegistry | None = None,
) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    try:
        context = load_context(
            config_path=config_path,
            catalog_path=catalog_path,
            registry=registry,
        )
    except ConfigError as exc:
        return [DoctorCheck(name="config", ok=False, detail=str(exc))]

    checks.append(DoctorCheck("config", True, str(context.paths.config_path)))
    checks.append(DoctorCheck("agent_catalog", True, str(context.paths.catalog_path)))
    checks.append(DoctorCheck("database", True, str(context.store.database_path)))

    context.config.log_dir.mkdir(parents=True, exist_ok=True)
    checks.append(DoctorCheck("log_dir", True, str(context.config.log_dir)))

    for role_name, role in sorted(context.catalog.roles.items()):
        try:
            harness = context.registry.get(role.harness)
        except HarnessLoadError as exc:
            checks.append(
                DoctorCheck(
                    f"harness:{role_name}",
                    False,
                    exc.args[0],
                )
            )
            continue
        except KeyError:
            checks.append(
                DoctorCheck(
                    f"harness:{role_name}",
                    False,
                    f"unknown harness {role.harness}",
                )
            )
            continue
        command = harness.build_command(role, prompt="doctor prompt")
        executable = command[0]
        resolved = shutil.which(executable)
        if resolved is None:
            checks.append(
                DoctorCheck(
                    f"harness:{role_name}",
                    False,
                    f"executable not found: {executable}",
                )
            )
            continue
        checks.append(DoctorCheck(f"harness:{role_name}", True, resolved))
    return checks


def format_doctor_checks(checks: list[DoctorCheck]) -> str:
    lines = []
    for check in checks:
        state = "ok" if check.ok else "fail"
        lines.append(f"{check.name}: {state} :: {check.detail}")
    return "\n".join(lines)


def _init_source_paths(source_root: str | Path | None) -> dict[str, Path]:
    root = _find_source_root(source_root)
    if root is not None:
        return {
            "extension": root / "extensions" / "pi" / "orchestra" / "index.ts",
            "config": root / "config.yaml",
            "prompts": root / "prompts.yaml",
            "catalog": root / "agent-catalog.yaml",
        }

    assets = Path(__file__).resolve().parent / "assets"
    return {
        "extension": assets / "pi" / "orchestra" / "index.ts",
        "config": assets / "config.yaml",
        "prompts": assets / "prompts.yaml",
        "catalog": assets / "agent-catalog.yaml",
    }


def _config_source_paths(source_root: str | Path | None, *, copy: bool) -> dict[str, Path]:
    root = _find_source_root(source_root)
    if root is not None:
        return {
            "config": root / "config.yaml",
            "prompts": root / "prompts.yaml",
            "catalog": root / "agent-catalog.yaml",
        }
    if not copy:
        raise AppError("config link source root not found; rerun with --copy")
    assets = Path(__file__).resolve().parent / "assets"
    return {
        "config": assets / "config.yaml",
        "prompts": assets / "prompts.yaml",
        "catalog": assets / "agent-catalog.yaml",
    }


def _find_source_root(source_root: str | Path | None = None) -> Path | None:
    if source_root is not None:
        candidate = Path(source_root)
        if _is_source_root(candidate):
            return candidate
        return None
    candidates = [
        Path.cwd(),
        Path(__file__).resolve().parents[2],
    ]
    for candidate in candidates:
        if _is_source_root(candidate):
            return candidate
    return None


def _is_source_root(candidate: Path) -> bool:
    return (
        (candidate / "extensions" / "pi" / "orchestra" / "index.ts").exists()
        and (candidate / "config.yaml").exists()
        and (candidate / "prompts.yaml").exists()
        and (candidate / "agent-catalog.yaml").exists()
    )


def _runtime_config_targets(runtime_dir: Path) -> dict[str, Path]:
    return {
        "config": runtime_dir / "config.yaml",
        "prompts": runtime_dir / "prompts.yaml",
        "catalog": runtime_dir / "agent-catalog.yaml",
    }


def _materialize_runtime_config(
    source_paths: dict[str, Path],
    targets: dict[str, Path],
    *,
    force: bool,
    copy: bool,
) -> list[InitFileResult]:
    writer = _copy_init_file if copy else _link_init_file
    return [
        writer(source_paths["config"], targets["config"], force=force),
        writer(source_paths["prompts"], targets["prompts"], force=force),
        writer(source_paths["catalog"], targets["catalog"], force=force),
    ]


def _copy_init_file(source: Path, target: Path, *, force: bool) -> InitFileResult:
    if not source.exists():
        raise AppError(f"init source file not found: {source}")
    target_exists = target.exists() or target.is_symlink()
    if target_exists and not force:
        return InitFileResult(source=source, target=target, action="exists", mode="copy")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target_exists:
        _remove_existing_target(target)
    shutil.copy2(source, target)
    return InitFileResult(
        source=source,
        target=target,
        action="updated" if target_exists else "created",
        mode="copy",
    )


def _link_init_file(source: Path, target: Path, *, force: bool) -> InitFileResult:
    if not source.exists():
        raise AppError(f"init source file not found: {source}")
    target_exists = target.exists() or target.is_symlink()
    if target_exists and not force:
        return InitFileResult(source=source, target=target, action="exists", mode="link")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target_exists:
        _remove_existing_target(target)
    target.symlink_to(source)
    return InitFileResult(
        source=source,
        target=target,
        action="updated" if target_exists else "created",
        mode="link",
    )


def _remove_existing_target(target: Path) -> None:
    if target.is_symlink() or target.is_file():
        target.unlink()
        return
    if target.exists():
        raise AppError(f"init target is not a file: {target}")


def default_hermes_home() -> Path:
    explicit_home = os.environ.get("HERMES_HOME", "").strip()
    if explicit_home:
        return Path(explicit_home).expanduser()
    return Path.home() / ".hermes"


def default_hermes_orchestra_dir(profile: str | None = None) -> Path:
    root_home = default_hermes_home()
    selected_profile = _normalized_optional_profile(profile)
    if selected_profile is None:
        try:
            selected_profile = (root_home / "active_profile").read_text(encoding="utf-8").strip()
        except OSError:
            selected_profile = "default"
    if selected_profile and selected_profile != "default":
        return root_home / "profiles" / selected_profile / "orchestra"
    return root_home / "orchestra"


def default_opencode_home() -> Path:
    explicit_home = os.environ.get("OPENCODE_CONFIG_DIR", "").strip()
    if explicit_home:
        return Path(explicit_home).expanduser()
    return Path.home() / ".config" / "opencode"


def default_opencode_orchestra_dir() -> Path:
    return default_opencode_home() / "plugins" / "orchestra"


def _normalized_optional_profile(profile: str | None) -> str | None:
    if profile is None:
        return None
    normalized = profile.strip()
    return normalized or None


def _spawn_supervisor(context: AppContext, request_file: Path, run_id: str) -> None:
    command = [
        sys.executable,
        "-m",
        "orchestra",
        "--config",
        str(context.paths.config_path),
        "--agent-catalog",
        str(context.paths.catalog_path),
        "_run-supervisor",
        "--run-id",
        run_id,
        "--request-file",
        str(request_file),
    ]
    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _load_pending_request(run_id: str, request_file: Path) -> PendingRunRequest:
    payload = json.loads(request_file.read_text(encoding="utf-8"))
    return PendingRunRequest(
        run_id=run_id,
        role_name=str(payload["role_name"]),
        goal=str(payload["goal"]),
        approved_context=str(payload["approved_context"]),
        boundaries=str(payload["boundaries"]),
        acceptance_target=str(payload["acceptance_target"]),
        return_format=str(payload["return_format"]),
        timeout_seconds=int(payload["timeout_seconds"]),
        task_label=str(payload["task_label"]),
        request_file=request_file,
    )


def _finalize_supervisor_setup_failure(
    context: AppContext,
    run_id: str,
    *,
    error_text: str,
    blocker_text: str,
) -> RunRecord:
    return context.store.update_run(
        run_id,
        RunUpdate(
            status=STATUS_FAILED,
            result_summary=clean_result_summary(error_text),
            error_text=error_text,
            blocker_text=blocker_text,
        ),
    )



def _start_worker_process(
    context: AppContext,
    selected_role: SelectedRole,
    pending_request: PendingRunRequest,
    *,
    log_path: Path,
) -> tuple[SelectedRole, WorkerProcess]:
    role = selected_role.config
    try:
        harness = context.registry.get(role.harness)
    except HarnessLoadError as exc:
        detail = exc.args[0] if exc.args else str(exc)
        raise AppError(detail) from exc
    except KeyError as exc:
        detail = exc.args[0] if exc.args else str(exc)
        raise AppError(detail) from exc

    request = WorkerRequest(
        role_name=selected_role.name,
        goal=pending_request.goal,
        run_id=pending_request.run_id,
        approved_context=pending_request.approved_context,
        boundaries=pending_request.boundaries,
        acceptance_target=pending_request.acceptance_target,
        return_format=pending_request.return_format,
        timeout_seconds=pending_request.timeout_seconds,
        task_label=pending_request.task_label,
        worker_budget=role.worker_budget,
        log_path=log_path,
        skill_roots=_worker_skill_roots(context.paths.catalog_path),
        prompts=context.config.prompts,
    )

    try:
        return selected_role, harness.start(request, role)
    except Exception as exc:
        raise AppError(f"failed to start harness: {role.harness}: {exc}") from exc


def _worker_skill_roots(catalog_path: Path) -> tuple[Path, ...]:
    roots = (Path.cwd() / SKILL_LIBRARY_DIR, catalog_path.resolve().parent / SKILL_LIBRARY_DIR)
    return tuple(dict.fromkeys(root.resolve() for root in roots))


def _annotate_result_with_fallback(result: WorkerResult, note: str) -> WorkerResult:
    result_summary = f"{note}; {result.result_summary}" if result.result_summary else note
    error_text = f"{note}; {result.error_text}" if result.error_text else result.error_text
    blocker_text = f"{note}; {result.blocker_text}" if result.blocker_text else ""
    return WorkerResult(
        status=result.status,
        command=result.command,
        prompt=result.prompt,
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        result_summary=result_summary,
        error_text=error_text,
        blocker_text=blocker_text,
        result_summary_truncated=result.result_summary_truncated,
        timed_out=result.timed_out,
        worker_session_id=result.worker_session_id,
        transcript_path=result.transcript_path,
        approval_needed=result.approval_needed,
    )


def _setup_failure_blocker(error_text: str) -> str:
    if error_text.startswith("failed to load harness:"):
        return "Worker harness could not be loaded"
    if error_text.startswith("unknown harness:"):
        return "Worker harness is not configured"
    return "Worker harness could not start"


def _meaningful_worker_summary(stdout: str) -> str | None:
    return compact_summary(_meaningful_worker_output(stdout))


def _meaningful_worker_output(stdout: str) -> str:
    lines = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if lowered.startswith("bootstrapping") or lowered.startswith("warning"):
            continue
        lines.append(stripped)
    return "\n".join(lines)


def _result_from_completed_worker(
    worker: WorkerProcess,
    stdout: str,
    stderr: str,
) -> WorkerResult:
    result_summary = _meaningful_worker_summary(stdout)
    if worker.process.returncode == 0:
        if not result_summary:
            return WorkerResult(
                status=STATUS_FAILED,
                command=worker.command,
                prompt=worker.prompt,
                exit_code=worker.process.returncode,
                stdout=stdout,
                stderr=stderr,
                result_summary=None,
                error_text=WORKER_EMPTY_RESULT_ERROR,
                blocker_text=WORKER_EMPTY_RESULT_BLOCKER,
                result_summary_truncated=False,
                worker_session_id=worker.worker_session_id,
                transcript_path=worker.transcript_path,
                approval_needed=worker.approval_needed,
            )
        return WorkerResult(
            status=STATUS_DONE,
            command=worker.command,
            prompt=worker.prompt,
            exit_code=worker.process.returncode,
            stdout=stdout,
            stderr=stderr,
            result_summary=result_summary,
            error_text=None,
            blocker_text=None,
            result_summary_truncated=summary_was_truncated(_meaningful_worker_output(stdout)),
            worker_session_id=worker.worker_session_id,
            transcript_path=worker.transcript_path,
            approval_needed=worker.approval_needed,
        )
    return WorkerResult(
        status=STATUS_FAILED,
        command=worker.command,
        prompt=worker.prompt,
        exit_code=worker.process.returncode,
        stdout=stdout,
        stderr=stderr,
        result_summary=result_summary,
        error_text=compact_summary(stderr) or "Worker failed",
        blocker_text=None,
        result_summary_truncated=summary_was_truncated(stderr) if stderr else False,
        worker_session_id=worker.worker_session_id,
        transcript_path=worker.transcript_path,
        approval_needed=worker.approval_needed,
    )


def _finalize_run(context: AppContext, run_id: str, result: WorkerResult) -> RunRecord:
    current = context.store.get_run(run_id)
    if current.status not in ACTIVE_STATUSES:
        return current

    terminal_status = (
        result.status
        if result.status in {STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED}
        else STATUS_FAILED
    )
    artifact_path: Path | None = None
    blocker_text = result.blocker_text
    effective_blocker_text = current.blocker_text if blocker_text is None else blocker_text
    try:
        artifact_path = _write_return_artifact(context, run_id, result)
    except OSError as exc:
        artifact_error = f"Return artifact could not be written: {exc}"
        effective_blocker_text = (
            f"{effective_blocker_text}; {artifact_error}"
            if effective_blocker_text
            else artifact_error
        )
        blocker_text = effective_blocker_text

    result_summary_truncated = (
        result.result_summary_truncated if not effective_blocker_text else False
    )
    return context.store.update_run(
        run_id,
        RunUpdate(
            status=terminal_status,
            result_summary=result.result_summary,
            result_artifact_path=artifact_path,
            result_summary_truncated=result_summary_truncated,
            error_text=result.error_text,
            blocker_text=blocker_text,
            worker_session_id=result.worker_session_id,
            transcript_path=result.transcript_path,
            approval_needed=result.approval_needed,
        ),
    )


def _write_return_artifact(
    context: AppContext,
    run_id: str,
    result: WorkerResult,
) -> Path:
    artifact_dir = context.config.state_dir / "return-artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"{run_id}.md"
    artifact_path.write_text(
        _format_return_artifact(run_id, result),
        encoding="utf-8",
    )
    return artifact_path


def _format_return_artifact(run_id: str, result: WorkerResult) -> str:
    content = (
        "\n".join(
            [
                "# Orchestra worker return",
                "",
                f"Run: {run_id}",
                "",
                "## stdout",
                "",
            ]
        )
        + "\n"
    )
    content += result.stdout if result.stdout else "(empty)\n"
    content = _ensure_terminal_newline(content)
    if result.stderr:
        content += "\n## stderr\n\n"
        content += result.stderr
        content = _ensure_terminal_newline(content)
    return content


def _ensure_terminal_newline(text: str) -> str:
    return text if text.endswith("\n") else f"{text}\n"


def _terminate_owned_process(process_id: int, process_group_id_value: int | None) -> None:
    _send_termination(process_id, process_group_id_value, signal.SIGTERM)
    time.sleep(0.2)
    if _process_exists(process_id):
        _send_termination(process_id, process_group_id_value, signal.SIGKILL)


def _terminate_worker(process: subprocess.Popen[str], process_group_id_value: int | None) -> None:
    _send_termination(process.pid, process_group_id_value, signal.SIGTERM)


def _terminate_subprocess(
    process: subprocess.Popen[str],
    process_group_id_value: int | None,
) -> tuple[str, str]:
    _send_termination(process.pid, process_group_id_value, signal.SIGTERM)
    try:
        stdout, stderr = process.communicate(timeout=1.0)
    except subprocess.TimeoutExpired:
        _send_termination(process.pid, process_group_id_value, signal.SIGKILL)
        stdout, stderr = process.communicate(timeout=1.0)
    return stdout, stderr


def _send_termination(
    process_id: int,
    process_group_id_value: int | None,
    sig: signal.Signals,
) -> None:
    try:
        if process_group_id_value is not None and os.name != "nt":
            os.killpg(process_group_id_value, sig)
        else:
            os.kill(process_id, sig)
    except ProcessLookupError:
        return


def _process_exists(process_id: int) -> bool:
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    return True


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _enabled_roles(catalog: AgentCatalog) -> list[tuple[str, RoleConfig]]:
    return [
        (role_name, role)
        for role_name, role in sorted(catalog.roles.items())
        if role.enabled
    ]


def _select_role(catalog: AgentCatalog, role_name: str | None) -> SelectedRole:
    normalized_role_name = (role_name or "").strip() or catalog.default_role
    try:
        role = catalog.roles[normalized_role_name]
    except KeyError as exc:
        raise AppError(f"unknown role: {normalized_role_name}") from exc
    if not role.enabled:
        raise AppError(f"role is disabled: {normalized_role_name}")
    return SelectedRole(name=normalized_role_name, config=role)


def _fallback_roles_for(
    catalog: AgentCatalog,
    selected_role: SelectedRole,
) -> list[SelectedRole]:
    fallback_roles: list[SelectedRole] = []
    for fallback in selected_role.config.harness_fallback:
        harness_config = catalog.harness_configs[fallback.harness_config]
        fallback_roles.append(
            SelectedRole(
                name=selected_role.name,
                config=replace(
                    selected_role.config,
                    harness_config=fallback.harness_config,
                    harness=harness_config.harness,
                    command=harness_config.command,
                    model=(
                        fallback.model
                        if fallback.model is not None
                        else selected_role.config.model
                    ),
                    profile=(
                        fallback.profile
                        if fallback.profile is not None
                        else selected_role.config.profile
                    ),
                    agent=(
                        fallback.agent
                        if fallback.agent is not None
                        else selected_role.config.agent
                    ),
                ),
            )
        )
    return fallback_roles


def _fallback_note(
    *,
    role_name: str,
    fallback_harness_config: str,
    failed_harness: str,
) -> str:
    return (
        f"fallback: {role_name} used harness_config {fallback_harness_config} "
        f"after {failed_harness} failed to start"
    )


def _require_session_id(session_id: str) -> None:
    if not session_id.strip():
        raise AppError("session_id is required")


def _default_task_label(goal: str) -> str:
    compact = " ".join(goal.split())
    return compact[:77] + "..." if len(compact) > 80 else compact
