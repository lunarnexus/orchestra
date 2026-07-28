"""Application service layer for Orchestra CLI."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from shlex import split as shell_split

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
    HarnessRegistry,
    PiHarness,
    WorkerProcess,
    WorkerRequest,
    WorkerResult,
)
from orchestra.harnesses.pi import compact_summary, process_group_id
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


@dataclass(frozen=True)
class InitPiResult:
    files: list[InitFileResult]
    verification_command: str


@dataclass(frozen=True)
class ToolInfo:
    description: str
    prompt_snippet: str
    prompt_guidelines: list[str]
    goal_description: str
    role_description: str
    timeout_description: str
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


def create_default_registry() -> HarnessRegistry:
    registry = HarnessRegistry()
    registry.register(PiHarness())
    return registry


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
    role_name: str,
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
    role = _get_role(context.catalog, role_name)

    run_id = uuid.uuid4().hex[:12]
    log_path = context.config.log_dir / f"{run_id}.jsonl"
    effective_task_label = task_label.strip() or _default_task_label(goal)
    request_dir = context.config.state_dir / "requests"
    request_dir.mkdir(parents=True, exist_ok=True)
    request_file = request_dir / f"{run_id}.json"
    pending_request = PendingRunRequest(
        run_id=run_id,
        role_name=role_name,
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
        role=role_name,
        task_label=effective_task_label,
        log_path=log_path,
        created_at=utc_now(),
    )

    try:
        context.store.reserve_run(
            record,
            global_limit=context.config.concurrency.global_limit,
            per_session_limit=context.config.concurrency.per_session_limit,
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
    return StartedRun(record=record, request_file=request_file)


def run_supervisor(context: AppContext, *, run_id: str, request_file: str | Path) -> RunRecord:
    record = context.store.get_run(run_id)
    if record.status not in ACTIVE_STATUSES:
        return record

    pending_request = _load_pending_request(run_id, Path(request_file))
    role = _get_role(context.catalog, record.role)
    harness = context.registry.get(role.harness)
    request = WorkerRequest(
        role_name=pending_request.role_name,
        goal=pending_request.goal,
        approved_context=pending_request.approved_context,
        boundaries=pending_request.boundaries,
        acceptance_target=pending_request.acceptance_target,
        return_format=pending_request.return_format,
        timeout_seconds=pending_request.timeout_seconds,
        task_label=pending_request.task_label,
        log_path=record.log_path,
        prompts=context.config.prompts,
    )

    worker = harness.start(request, role)
    pgid = process_group_id(worker.process.pid)
    updated = context.store.update_run(
        run_id,
        RunUpdate(
            status=STATUS_RUNNING,
            process_id=worker.process.pid,
            process_group_id=pgid,
            worker_session_id=worker.worker_session_id,
            transcript_path=worker.transcript_path,
            approval_needed=worker.approval_needed,
        ),
    )
    if updated.status != STATUS_RUNNING:
        _terminate_worker(worker.process, pgid)
        _safe_unlink(pending_request.request_file)
        return updated

    try:
        stdout, stderr = worker.process.communicate(timeout=request.timeout_seconds)
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
            error_text="Pi worker timed out",
            blocker_text="Worker exceeded timeout",
            timed_out=True,
            worker_session_id=worker.worker_session_id,
            transcript_path=worker.transcript_path,
            approval_needed=worker.approval_needed,
        )
    else:
        result = _result_from_completed_worker(worker, stdout, stderr)

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
        lines.append(f"result: {record.result_summary}")
    if record.error_text:
        lines.append(f"error: {record.error_text}")
    if record.blocker_text:
        lines.append(f"blocker: {record.blocker_text}")
    if record.transcript_path:
        lines.append(f"transcript_path: {record.transcript_path}")
    return "\n".join(lines)


def format_started_run(started: StartedRun) -> str:
    lines = [
        format_run_report(started.record),
        f"request_file: {started.request_file}",
        "dispatch: queued for supervision",
    ]
    return "\n".join(lines)


def format_dispatch_ack(run_id: str) -> str:
    return f"orchestra dispatched: {run_id}"


def format_progress_notification(
    *,
    completed_count: int,
    total_count: int,
    run_id: str,
    status: str,
) -> str:
    return f"orchestra: {run_id} returned {status} ({completed_count}/{total_count})"


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
        summary = clean_result_summary(run.blocker_text or run.error_text or run.result_summary)
        label = "Result" if outcome == "success" else "Summary"
        blocks.append(
            "\n".join(
                [
                    f"[orchestra: Worker {run.run_id} {outcome}]",
                    f"Request: {run.task_label}",
                    f"{label}: {summary}",
                    f"Log: {run.log_path}",
                ]
            )
        )
    return "\n\n".join(blocks)


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
        summary = clean_result_summary(run.blocker_text or run.error_text or run.result_summary)
        lines.append(
            f"- {run.run_id} [{run.status}] {run.role} :: {run.task_label} :: {summary}"
        )
        lines.append(f"  log: {run.log_path}")
    if active_remaining == 0:
        lines.append("session_report: all active workers for this session are complete")
    return "\n".join(lines)


def pending_session_report(context: AppContext, session_id: str) -> SessionReport | None:
    _require_session_id(session_id)
    if not context.config.auto_return:
        return None
    runs = context.store.list_pending_report_runs(session_id)
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

    while True:
        record = context.store.get_run(run_id)
        if record.orchestrator_session_id != session_id:
            raise AppError("run does not belong to the provided session_id")

        if record.status not in ACTIVE_STATUSES:
            if context.store.count_active_runs(session_id) == 0:
                return pending_session_report(context, session_id)

        if deadline is not None and time.monotonic() >= deadline:
            raise AppError("timed out waiting for session report")
        time.sleep(poll_interval)


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
    runs = context.store.list_active_runs(session_id)
    lines = [
        f"session_id: {session_id}",
        f"active_runs: {len(runs)}",
        f"global_active_runs: {len(context.store.list_active_runs())}",
    ]
    if not runs:
        lines.append("status: no active runs")
        return "\n".join(lines)

    lines.append("runs:")
    for run in runs:
        pid = f" pid={run.process_id}" if run.process_id is not None else ""
        lines.append(f"- {run.run_id} [{run.status}] {run.role} :: {run.task_label}{pid}")
    return "\n".join(lines)


def format_roles(context: AppContext) -> str:
    lines = ["roles:"]
    for role_name, role in sorted(context.catalog.roles.items()):
        model = f" model={role.model}" if role.model else ""
        profile = f" profile={role.profile}" if role.profile else ""
        lines.append(f"- {role_name} harness={role.harness}{model}{profile}")
    return "\n".join(lines)


def format_host_help(context: AppContext) -> str:
    return context.config.prompts.host_help.format(roles=format_roles(context))


def format_command_echo(raw_command: str) -> str:
    raw = raw_command.strip()
    if not raw:
        return "/orch"
    try:
        parts = shell_split(raw)
    except ValueError:
        parts = raw.split()
    if not parts:
        return "/orch"
    if parts[0] != "do":
        return f"/orch {raw}"

    request_parts: list[str] = []
    index = 1
    while index < len(parts):
        token = parts[index]
        if token in {"--role", "--timeout", "--task-label"} and index + 1 < len(parts):
            index += 2
            continue
        request_parts.append(token)
        index += 1
    return " ".join(request_parts).strip() or f"/orch {raw}"


def tool_info(context: AppContext) -> ToolInfo:
    roles = format_roles(context)
    prompts = context.config.prompts
    return ToolInfo(
        description=prompts.tool_description.format(roles=roles),
        prompt_snippet=prompts.tool_prompt_snippet.format(roles=roles),
        prompt_guidelines=list(prompts.tool_prompt_guidelines),
        goal_description=prompts.tool_goal_description,
        role_description=prompts.tool_role_description.format(roles=roles),
        timeout_description=prompts.tool_timeout_description,
        task_label_description=prompts.tool_task_label_description,
    )


def format_history(context: AppContext, session_id: str, limit: int) -> str:
    _require_session_id(session_id)
    runs = context.store.list_runs(session_id, limit=limit)
    lines = [f"session_id: {session_id}", f"history_count: {len(runs)}"]
    if not runs:
        lines.append("history: no runs found")
        return "\n".join(lines)

    lines.append("runs:")
    for run in runs:
        summary = clean_result_summary(run.blocker_text or run.error_text or run.result_summary)
        lines.append(
            f"- {run.run_id} [{run.status}] {run.role} :: {run.task_label} :: {summary}"
        )
        lines.append(f"  log: {run.log_path}")
    return "\n".join(lines)


def init_pi(*, force: bool = False, source_root: str | Path | None = None) -> InitPiResult:
    source_paths = _init_source_paths(source_root)
    pi_dir = default_pi_orchestra_dir().parent

    files = [
        _copy_init_file(
            source_paths["extension"],
            pi_dir / "extensions" / "orchestra" / "index.ts",
            force=force,
        ),
        _copy_init_file(
            source_paths["config"],
            pi_dir / "orchestra" / "config.yaml",
            force=force,
        ),
        _copy_init_file(
            source_paths["catalog"],
            pi_dir / "orchestra" / "agent-catalog.yaml",
            force=force,
        ),
    ]
    return InitPiResult(
        files=files,
        verification_command='pi --no-approve -p "/orch help"',
    )


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
    if source_root is not None:
        root = Path(source_root)
        return {
            "extension": root / "extensions" / "pi" / "orchestra" / "index.ts",
            "config": root / "config.yaml",
            "catalog": root / "agent-catalog.yaml",
        }

    repo_root = _find_source_root()
    if repo_root is not None:
        return {
            "extension": repo_root / "extensions" / "pi" / "orchestra" / "index.ts",
            "config": repo_root / "config.yaml",
            "catalog": repo_root / "agent-catalog.yaml",
        }

    assets = Path(__file__).resolve().parent / "assets"
    return {
        "extension": assets / "pi" / "orchestra" / "index.ts",
        "config": assets / "config.yaml",
        "catalog": assets / "agent-catalog.yaml",
    }


def _find_source_root() -> Path | None:
    candidates = [
        Path.cwd(),
        Path(__file__).resolve().parents[2],
    ]
    for candidate in candidates:
        if (candidate / "extensions" / "pi" / "orchestra" / "index.ts").exists():
            return candidate
    return None


def _copy_init_file(source: Path, target: Path, *, force: bool) -> InitFileResult:
    if not source.exists():
        raise AppError(f"init source file not found: {source}")
    if target.exists() and not force:
        return InitFileResult(source=source, target=target, action="exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return InitFileResult(source=source, target=target, action="updated" if force else "created")


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


def _result_from_completed_worker(
    worker: WorkerProcess,
    stdout: str,
    stderr: str,
) -> WorkerResult:
    normalized_stdout = stdout.strip()
    normalized_stderr = stderr.strip()
    result_summary = compact_summary(normalized_stdout)
    if worker.process.returncode == 0:
        return WorkerResult(
            status=STATUS_DONE,
            command=worker.command,
            prompt=worker.prompt,
            exit_code=worker.process.returncode,
            stdout=normalized_stdout,
            stderr=normalized_stderr,
            result_summary=result_summary,
            error_text=None,
            blocker_text=None,
            worker_session_id=worker.worker_session_id,
            transcript_path=worker.transcript_path,
            approval_needed=worker.approval_needed,
        )
    return WorkerResult(
        status=STATUS_FAILED,
        command=worker.command,
        prompt=worker.prompt,
        exit_code=worker.process.returncode,
        stdout=normalized_stdout,
        stderr=normalized_stderr,
        result_summary=result_summary,
        error_text=compact_summary(normalized_stderr) or "Pi worker failed",
        blocker_text=None,
        worker_session_id=worker.worker_session_id,
        transcript_path=worker.transcript_path,
        approval_needed=worker.approval_needed,
    )


def _finalize_run(context: AppContext, run_id: str, result: WorkerResult) -> RunRecord:
    terminal_status = (
        result.status
        if result.status in {STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED}
        else STATUS_FAILED
    )
    return context.store.update_run(
        run_id,
        RunUpdate(
            status=terminal_status,
            result_summary=result.result_summary,
            error_text=result.error_text,
            blocker_text=result.blocker_text,
            worker_session_id=result.worker_session_id,
            transcript_path=result.transcript_path,
            approval_needed=result.approval_needed,
        ),
    )


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
    return stdout.strip(), stderr.strip()


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


def _get_role(catalog: AgentCatalog, role_name: str) -> RoleConfig:
    try:
        return catalog.roles[role_name]
    except KeyError as exc:
        raise AppError(f"unknown role: {role_name}") from exc


def _require_session_id(session_id: str) -> None:
    if not session_id.strip():
        raise AppError("session_id is required")


def _default_task_label(goal: str) -> str:
    compact = " ".join(goal.split())
    return compact[:77] + "..." if len(compact) > 80 else compact
