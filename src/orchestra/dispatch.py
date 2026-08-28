"""Dispatch acceptance and run-creation helpers for Orchestra."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from orchestra.config import ModelLimitConfig, PromptConfig
from orchestra.context import CONTRACT_VERSION, AppContext, AppError
from orchestra.harnesses.common import orchestra_can_dispatch
from orchestra.logs import utc_now
from orchestra.reports import format_run_report
from orchestra.roles import _select_role
from orchestra.state import ConcurrencyLimitError, RunRecord
from orchestra.status import format_status

if TYPE_CHECKING:
    pass


def _app_error(message: str) -> Exception:
    return AppError(message)

__all__ = [
    "PendingRunRequest",
    "StartedRun",
    "format_started_run",
    "started_run_payload",
    "start_run",
]


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
    cycle_id: str | None = None
    triggered_by_run_id: str | None = None
    trigger_reason: str | None = None
    sequence_index: int | None = None


@dataclass(frozen=True)
class StartedRun:
    record: RunRecord
    request_file: Path
    timeout_seconds: int


def _require_session_id(session_id: str) -> None:
    if not session_id.strip():
        raise _app_error("session_id is required")


def _default_task_label(goal: str) -> str:
    compact = " ".join(goal.split())
    return compact[:77] + "..." if len(compact) > 80 else compact


def _expanded_model_limits(
    model_limits: dict[str, ModelLimitConfig],
) -> dict[str, int]:
    expanded: dict[str, int] = {}
    for model, limit in model_limits.items():
        expanded[model] = limit.concurrency
        if "/" in model:
            expanded.setdefault(model.rsplit("/", 1)[1], limit.concurrency)
    return expanded


def _format_concurrency_limit_error(
    message: str,
    *,
    context: AppContext,
    session_id: str,
) -> str:
    guidance = (
        "dispatch was not accepted; wait for current subagents to return, "
        "then re-dispatch. Do not poll while waiting."
    )
    return f"{message}; {guidance}\n{format_status(context, session_id)}"


def format_started_run(
    started: StartedRun,
    *,
    prompts: PromptConfig | None = None,
) -> str:
    lines = [
        format_run_report(started.record, prompts=prompts),
        f"timeout_seconds: {started.timeout_seconds}",
        f"request_file: {started.request_file}",
        "dispatch: queued for supervision",
    ]
    return "\n".join(lines)


def started_run_payload(
    started: StartedRun,
    *,
    prompts: PromptConfig | None = None,
) -> dict[str, object]:
    return {
        "contract_version": CONTRACT_VERSION,
        "kind": "dispatch",
        "ok": True,
        "run_id": started.record.run_id,
        "role": started.record.role,
        "status": started.record.status,
        "timeout_seconds": started.timeout_seconds,
        "request_file": str(started.request_file),
        "message": format_started_run(started, prompts=prompts),
    }


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
    cycle_id: str | None = None,
    triggered_by_run_id: str | None = None,
    trigger_reason: str | None = None,
    sequence_index: int | None = None,
    allow_auto_only: bool = False,
) -> StartedRun:
    _require_session_id(session_id)

    if not orchestra_can_dispatch():
        raise _app_error("ORCHESTRA_DISPATCH_BUDGET dispatch budget exhausted")
    selected_role = _select_role(
        context.catalog,
        role_name,
        allow_auto_only=allow_auto_only,
    )
    role = selected_role.config

    run_id = uuid.uuid4().hex[:12]
    log_path = context.config.log_dir / f"{run_id}.jsonl"
    effective_task_label = task_label.strip() or _default_task_label(goal)
    request_dir = context.config.state_dir / "requests"
    request_dir.mkdir(parents=True, exist_ok=True)
    request_file = request_dir / f"{run_id}.json"
    effective_timeout = timeout_seconds or context.config.default_timeout
    effective_soft_timeout = role.soft_timeout or context.config.soft_timeout
    if effective_soft_timeout is not None and effective_soft_timeout >= effective_timeout:
        raise _app_error("soft_timeout must be less than effective worker timeout")

    pending_request = PendingRunRequest(
        run_id=run_id,
        role_name=selected_role.name,
        goal=goal,
        approved_context=approved_context,
        boundaries=boundaries,
        acceptance_target=acceptance_target,
        return_format=return_format,
        timeout_seconds=effective_timeout,
        task_label=effective_task_label,
        request_file=request_file,
        cycle_id=cycle_id,
        triggered_by_run_id=triggered_by_run_id,
        trigger_reason=trigger_reason,
        sequence_index=sequence_index,
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
        cycle_id=cycle_id,
        triggered_by_run_id=triggered_by_run_id,
        trigger_reason=trigger_reason,
        sequence_index=sequence_index,
    )

    from orchestra.supervision import _spawn_supervisor, reconcile_stale_queued_runs

    reconcile_stale_queued_runs(context)

    try:
        context.store.reserve_run(
            record,
            global_limit=context.config.concurrency.global_limit,
            per_session_limit=context.config.concurrency.per_session_limit,
            per_model_limits=_expanded_model_limits(context.catalog.model_limits),
        )
    except ConcurrencyLimitError as exc:
        raise _app_error(
            _format_concurrency_limit_error(str(exc), context=context, session_id=session_id)
        ) from exc

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
                "cycle_id": pending_request.cycle_id,
                "triggered_by_run_id": pending_request.triggered_by_run_id,
                "trigger_reason": pending_request.trigger_reason,
                "sequence_index": pending_request.sequence_index,
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
