"""Report formatting and pending-report lifecycle helpers for Orchestra."""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from orchestra.config import (
    DEFAULT_RETURN_HINT_DONE,
    DEFAULT_RETURN_HINT_FAILED,
    DEFAULT_RETURN_HINT_INCOMPLETE,
    PromptConfig,
)
from orchestra.context import CONTRACT_VERSION, AppContext, AppError
from orchestra.state import (
    ACTIVE_STATUSES,
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_INCOMPLETE,
    RunRecord,
)

__all__ = [
    "REPORT_HEADER",
    "SessionReport",
    "SessionStatusDetails",
    "await_run_terminal_status",
    "await_session_report",
    "await_session_report_payload",
    "build_session_report",
    "clean_result_summary",
    "consume_pending_session_report",
    "format_orchestrator_return",
    "format_run_report",
    "mark_session_report_delivered",
    "pending_session_report",
    "release_session_report",
    "session_report_payload",
    "session_status_details",
]

REPORT_HEADER = "Orchestra session report"


@dataclass(frozen=True)
class SessionReport:
    run_ids: list[str]
    text: str


@dataclass(frozen=True)
class SessionStatusDetails:
    descendants_terminal: bool
    session_report_available: bool
    session_report_delivered: bool


def _require_session_id(session_id: str) -> None:
    if not session_id.strip():
        raise AppError("session_id is required")


def _require_app_error(message: str) -> Exception:
    return AppError(message)


def _orchestrator_lineage_session_ids(session_id: str) -> list[str]:
    from orchestra.status import _orchestrator_lineage_session_ids as status_lineage

    return status_lineage(session_id)


def _reconcile_stale_queued_runs(context: AppContext) -> None:
    from orchestra.supervision import reconcile_stale_queued_runs

    reconcile_stale_queued_runs(context)


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


def format_run_report(
    record: RunRecord,
    *,
    prompts: PromptConfig | None = None,
) -> str:
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
    if record.supervisor_pid is not None:
        lines.append(f"supervisor_pid: {record.supervisor_pid}")
    if record.supervisor_started_at:
        lines.append(f"supervisor_started_at: {record.supervisor_started_at}")
    if record.supervisor_output_path:
        lines.append(f"supervisor_output_path: {record.supervisor_output_path}")
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
    hint = (
        prompts.return_hint_incomplete
        if prompts is not None
        else DEFAULT_RETURN_HINT_INCOMPLETE
    )
    if record.status == STATUS_INCOMPLETE:
        lines.append(f"next: {hint}")
    if record.worker_session_id:
        lines.append(f"worker_session_id: {record.worker_session_id}")
    if record.transcript_path:
        lines.append(f"transcript_path: {record.transcript_path}")
    return "\n".join(lines)


def clean_result_summary(summary: str | None) -> str:
    if not summary:
        return "-"
    cleaned = re.sub(r"\bBlockers?:\s*(None|none|No blockers?\.?)", "", summary)
    cleaned = re.sub(r"\bRisks?:\s*(None|none|No risks?\.?)", "", cleaned)
    cleaned = re.sub(r"[^\x09\x0A\x0D\x20-\x7E]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "-"


def _return_hint(run: RunRecord, *, prompts: PromptConfig | None = None) -> str | None:
    if run.status == STATUS_DONE:
        return (
            prompts.return_hint_done if prompts is not None else DEFAULT_RETURN_HINT_DONE
        )
    if run.status == STATUS_INCOMPLETE:
        return (
            prompts.return_hint_incomplete
            if prompts is not None
            else DEFAULT_RETURN_HINT_INCOMPLETE
        )
    if run.status == STATUS_CANCELLED:
        return None
    return prompts.return_hint_failed if prompts is not None else DEFAULT_RETURN_HINT_FAILED


def _format_run_summary(run: RunRecord) -> str:
    summary = clean_result_summary(run.blocker_text or run.error_text or run.result_summary)
    if run.result_summary_truncated:
        return f"{summary} [truncated]"
    return summary


def format_orchestrator_return(
    runs: list[RunRecord],
    *,
    prompts: PromptConfig | None = None,
) -> str:
    if not runs:
        return "[orchestra: all background processes returned]"
    blocks = []
    for run in runs:
        outcome = "success" if run.status == STATUS_DONE else "fail"
        lines = [
            f"[orchestra: {run.role} {run.run_id} {outcome}]",
            f"summary: {_format_run_summary(run)}",
        ]
        if run.result_artifact_path:
            lines.append(f"artifact: {run.result_artifact_path}")
        hint = _return_hint(run, prompts=prompts)
        if hint:
            lines.append(f"next: {hint}")
        if outcome != "success":
            if run.worker_session_id:
                lines.append(f"worker_session: {run.worker_session_id}")
            lines.append(f"log: {run.log_path}")
        blocks.append("\n".join(lines))
    report = "\n\n".join(blocks)
    if len(runs) == 1:
        return report
    return f"[orchestra: {len(runs)} subagents returned]\n\n{report}"


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
        if run.result_artifact_path:
            lines.append(f"  artifact: {run.result_artifact_path}")
        if run.worker_session_id:
            lines.append(f"  worker_session_id: {run.worker_session_id}")
        lines.append(f"  log: {run.log_path}")
    if active_remaining == 0:
        lines.append("session_report: all active subagents for this session are complete")
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
        text=format_orchestrator_return(runs, prompts=context.config.prompts),
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
    return format_orchestrator_return(runs, prompts=context.config.prompts)


def await_run_terminal_status(
    context: AppContext,
    session_id: str,
    *,
    run_id: str,
    poll_interval: float = 0.1,
    timeout_seconds: float | None = None,
) -> tuple[RunRecord, int, SessionStatusDetails]:
    _require_session_id(session_id)
    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds

    while True:
        _reconcile_stale_queued_runs(context)
        record = context.store.get_run(run_id)
        if record.orchestrator_session_id != session_id:
            raise _require_app_error("run does not belong to the provided session_id")
        if record.status not in ACTIVE_STATUSES:
            lineage_session_ids = _orchestrator_lineage_session_ids(session_id)
            active_runs = _list_active_runs_for_session_ids(context, lineage_session_ids)
            return record, len(active_runs), session_status_details(
                context,
                lineage_session_ids,
                active_runs=active_runs,
            )
        if deadline is not None and time.monotonic() >= deadline:
            raise _require_app_error("timed out waiting for run completion")
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
            _reconcile_stale_queued_runs(context)
            record = context.store.get_run(run_id)
            if record.orchestrator_session_id != session_id:
                raise _require_app_error("run does not belong to the provided session_id")

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
            raise _require_app_error("timed out waiting for session report")
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


def session_report_payload(report: SessionReport) -> dict[str, object]:
    return {
        "contract_version": CONTRACT_VERSION,
        "kind": "session_report",
        "ok": True,
        "runIds": report.run_ids,
        "report": report.text,
    }


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


def session_status_details(
    context: AppContext,
    lineage_session_ids: list[str],
    *,
    active_runs: list[RunRecord] | None = None,
) -> SessionStatusDetails:
    active = active_runs
    if active is None:
        active = _list_active_runs_for_session_ids(context, lineage_session_ids)
    descendants_terminal = len(active) == 0
    if not descendants_terminal:
        return SessionStatusDetails(
            descendants_terminal=False,
            session_report_available=False,
            session_report_delivered=False,
        )
    pending_report_runs = (
        [
            run
            for lineage_session_id in lineage_session_ids
            for run in context.store.list_pending_report_runs(lineage_session_id)
        ]
        if context.config.auto_return
        else []
    )
    historical_runs = _list_runs_for_session_ids(
        context,
        lineage_session_ids,
        limit=10_000_000,
    )
    return SessionStatusDetails(
        descendants_terminal=True,
        session_report_available=bool(pending_report_runs),
        session_report_delivered=any(run.reported_at is not None for run in historical_runs),
    )
