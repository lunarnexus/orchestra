"""Report formatting and pending-report lifecycle helpers for Orchestra."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
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
    STATUS_FAILED,
    STATUS_INCOMPLETE,
    TERMINAL_STATUSES,
    RunRecord,
)

__all__ = [
    "REPORT_HEADER",
    "SessionReport",
    "SessionStatusDetails",
    "aggregate_completed_run_accounting",
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


def _parse_iso_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def aggregate_completed_run_accounting(runs: list[RunRecord]) -> dict[str, int | bool | None]:
    completed_runs = [run for run in runs if run.status in TERMINAL_STATUSES]
    totals: dict[str, int | bool | None] = {
        "completed_runs": len(completed_runs),
        "elapsed_seconds": None,
        "elapsed_seconds_complete": True,
        "input_tokens": None,
        "output_tokens": None,
        "cache_read_tokens": None,
        "cache_write_tokens": None,
        "tokens_complete": True,
        "total_tokens": None,
    }
    if not completed_runs:
        return totals

    elapsed_seconds = 0
    input_tokens = 0
    output_tokens = 0
    cache_read_tokens = 0
    cache_write_tokens = 0

    for run in completed_runs:
        if run.started_at is None or run.ended_at is None:
            totals["elapsed_seconds_complete"] = False
        else:
            elapsed_seconds += int(
                (
                    _parse_iso_timestamp(run.ended_at)
                    - _parse_iso_timestamp(run.started_at)
                ).total_seconds()
            )

        for key, value in (
            ("input_tokens", run.input_tokens),
            ("output_tokens", run.output_tokens),
            ("cache_read_tokens", run.cache_read_tokens),
            ("cache_write_tokens", run.cache_write_tokens),
        ):
            if value is None:
                totals["tokens_complete"] = False
            elif key == "input_tokens":
                input_tokens += value
            elif key == "output_tokens":
                output_tokens += value
            elif key == "cache_read_tokens":
                cache_read_tokens += value
            else:
                cache_write_tokens += value

    totals["elapsed_seconds"] = elapsed_seconds if totals["elapsed_seconds_complete"] else None
    totals["input_tokens"] = input_tokens
    totals["output_tokens"] = output_tokens
    totals["cache_read_tokens"] = cache_read_tokens
    totals["cache_write_tokens"] = cache_write_tokens
    if totals["tokens_complete"]:
        totals["total_tokens"] = (
            input_tokens + output_tokens + cache_read_tokens + cache_write_tokens
        )
    return totals


def _format_token_accounting(run: RunRecord) -> str | None:
    parts: list[str] = []
    if run.input_tokens is not None:
        parts.append(f"input={run.input_tokens}")
    if run.output_tokens is not None:
        parts.append(f"output={run.output_tokens}")
    if run.cache_read_tokens is not None:
        parts.append(f"cache_read={run.cache_read_tokens}")
    if run.cache_write_tokens is not None:
        parts.append(f"cache_write={run.cache_write_tokens}")
    if not parts:
        return None
    return "tokens: " + " ".join(parts)


def _format_accounting_totals(accounting: dict[str, int | bool | None]) -> list[str]:
    return [
        f"accounting_elapsed_seconds_complete: {accounting['elapsed_seconds_complete']}",
        f"accounting_tokens_complete: {accounting['tokens_complete']}",
        f"accounting_completed_runs: {accounting['completed_runs']}",
        f"accounting_elapsed_seconds: {accounting['elapsed_seconds']}",
        f"accounting_input_tokens: {accounting['input_tokens']}",
        f"accounting_output_tokens: {accounting['output_tokens']}",
        f"accounting_cache_read_tokens: {accounting['cache_read_tokens']}",
        f"accounting_cache_write_tokens: {accounting['cache_write_tokens']}",
        f"accounting_total_tokens: {accounting['total_tokens']}",
    ]


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
    if record.error_text:
        lines.append(f"error: {record.error_text}")
    if record.blocker_text:
        lines.append(f"blocker: {record.blocker_text}")
    token_accounting = _format_token_accounting(record)
    if token_accounting:
        lines.append(token_accounting)
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
    if run.role == "builder" and run.status == STATUS_DONE:
        return (
            prompts.return_hint_done if prompts is not None else DEFAULT_RETURN_HINT_DONE
        )
    if run.role == "builder" and run.status in {STATUS_FAILED, STATUS_CANCELLED, STATUS_INCOMPLETE}:
        if prompts is not None and prompts.return_hint_failed != DEFAULT_RETURN_HINT_FAILED:
            return prompts.return_hint_failed
        return (
            "examine durable builder references and redispatch one bounded "
            "fix-only builder follow-up"
        )
    if run.status == STATUS_INCOMPLETE:
        return (
            prompts.return_hint_incomplete
            if prompts is not None
            else DEFAULT_RETURN_HINT_INCOMPLETE
        )
    if run.status == STATUS_CANCELLED:
        return None
    if run.status == STATUS_DONE:
        return (
            prompts.return_hint_done if prompts is not None else DEFAULT_RETURN_HINT_DONE
        )
    return prompts.return_hint_failed if prompts is not None else DEFAULT_RETURN_HINT_FAILED


def _format_run_summary(run: RunRecord) -> str:
    summary = clean_result_summary(run.blocker_text or run.error_text or run.result_summary)
    if run.result_summary_truncated:
        return f"{summary} [truncated]"
    return summary


def _should_show_return_hint(run: RunRecord, runs: list[RunRecord]) -> bool:
    from orchestra.supervision import AUTOMATIC_DISPATCH_CHAINS

    if not run.trigger_reason or not run.triggered_by_run_id:
        return True
    chain = AUTOMATIC_DISPATCH_CHAINS.get(run.trigger_reason)
    if chain is None or not chain.child_hints_suppressed():
        return True
    return not any(other.run_id == run.triggered_by_run_id for other in runs)


def _auto_verify_dispatch_failure_note(run: RunRecord) -> str | None:
    try:
        log_path = Path(run.log_path)
        log_lines = log_path.read_text(encoding="utf-8").splitlines()
    except (AttributeError, TypeError, OSError):
        return None

    for line in log_lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        from orchestra.supervision import AUTOMATIC_DISPATCH_CHAINS

        chain = AUTOMATIC_DISPATCH_CHAINS["auto_verify"]
        if event.get("event") != chain.auto_return_event():
            continue
        error_type = event.get("error_type")
        error = event.get("error")
        return chain.dispatch_failure_note(error_type, error)
    return None


def _semantic_failure_verdict(run: RunRecord) -> str | None:
    verdict_re = re.compile(
        r"\b(?:Verdict|Status):\s*(fail|failed|blocked)\b",
        re.IGNORECASE,
    )
    for text in (run.result_summary, run.result_output):
        if text is None:
            continue
        match = verdict_re.search(text)
        if match:
            verdict = match.group(1).lower()
            return "fail" if verdict == "failed" else verdict
    return None


def format_orchestrator_return(
    runs: list[RunRecord],
    *,
    prompts: PromptConfig | None = None,
) -> str:
    if not runs:
        return "[orchestra: all background processes returned]"
    semantic_failures = [_semantic_failure_verdict(run) for run in runs]
    report_has_issue = any(
        run.status != STATUS_DONE or semantic_failure
        for run, semantic_failure in zip(runs, semantic_failures, strict=True)
    )
    blocks = []
    for run, semantic_failure in zip(runs, semantic_failures, strict=True):
        outcome = "success" if run.status == STATUS_DONE and not semantic_failure else "fail"
        lines = [
            f"[orchestra: {run.role} {run.run_id} {outcome}]",
            f"summary: {_format_run_summary(run)}",
        ]
        token_accounting = _format_token_accounting(run)
        if token_accounting:
            lines.append(token_accounting)
        dispatch_failure = _auto_verify_dispatch_failure_note(run)
        if dispatch_failure:
            lines.append(f"auto_verify: {dispatch_failure}")
        if semantic_failure:
            hint = prompts.return_hint_failed if prompts is not None else DEFAULT_RETURN_HINT_FAILED
        elif report_has_issue and run.status == STATUS_DONE:
            hint = None
        else:
            hint = (
                _return_hint(run, prompts=prompts)
                if _should_show_return_hint(run, runs)
                else None
            )
        if hint:
            lines.append(f"next: {hint}")
        if outcome != "success" or semantic_failure:
            if semantic_failure:
                lines.append(f"verdict: {semantic_failure}")
            lines.append(f"status: {run.status}")
            lines.append(f"run_id: {run.run_id}")
            lines.append(f"debug: orchestra debug --run-id {run.run_id}")
            lines.append("DB location: runs.result_output")
            if run.worker_session_id:
                lines.append(f"worker_session: {run.worker_session_id}")
            if run.transcript_path:
                lines.append(f"transcript: {run.transcript_path}")
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
    lines.extend(_format_accounting_totals(aggregate_completed_run_accounting(runs)))
    if not runs:
        lines.append("runs: none")
        return "\n".join(lines)

    lines.append("runs:")
    for run in runs:
        summary = _format_run_summary(run)
        lines.append(
            f"- {run.run_id} [{run.status}] {run.role} :: {run.task_label} :: {summary}"
        )
        token_accounting = _format_token_accounting(run)
        if token_accounting:
            lines.append(f"  {token_accounting}")
        dispatch_failure = _auto_verify_dispatch_failure_note(run)
        if dispatch_failure:
            lines.append(f"  auto_verify: {dispatch_failure}")
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
