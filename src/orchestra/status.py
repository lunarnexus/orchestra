"""Status, history, and debug formatting helpers for Orchestra."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

from orchestra.config import PromptConfig
from orchestra.context import CONTRACT_VERSION, AppContext, AppError
from orchestra.reports import clean_result_summary, format_run_report, session_status_details
from orchestra.session_mode import default_main_session_mode, resolve_main_session_mode
from orchestra.state import STATUS_INCOMPLETE, RunRecord

if TYPE_CHECKING:
    from orchestra.reports import SessionStatusDetails

__all__ = [
    "await_run_payload",
    "format_debug_run",
    "format_debug_session",
    "format_history",
    "format_status",
    "status_payload",
]


def _require_session_id(session_id: str) -> None:
    if not session_id.strip():
        raise AppError("session_id is required")


def _reconcile_stale_queued_runs(context: AppContext) -> None:
    from orchestra.supervision import reconcile_stale_queued_runs

    reconcile_stale_queued_runs(context)


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _append_session_status_details(lines: list[str], details: SessionStatusDetails) -> None:
    lines.extend(
        [
            f"descendants_terminal: {_yes_no(details.descendants_terminal)}",
            f"session_report_available: {_yes_no(details.session_report_available)}",
            f"session_report_delivered: {_yes_no(details.session_report_delivered)}",
        ]
    )


def _compact_active_run_line(run: RunRecord, *, include_owner: bool = False) -> str:
    parts = [f"- {run.run_id}", run.role, run.status, f"task={json.dumps(run.task_label)}"]
    if include_owner:
        parts.append(f"owner={run.orchestrator_session_id}")
    if run.cycle_id:
        parts.append(f"cycle={run.cycle_id}")
    if run.triggered_by_run_id:
        parts.append(f"triggered_by={run.triggered_by_run_id}")
    if run.trigger_reason:
        parts.append(f"trigger={run.trigger_reason}")
    if run.sequence_index is not None:
        parts.append(f"seq={run.sequence_index}")
    if run.blocker_text:
        parts.append(f"blocker={json.dumps(run.blocker_text)}")
    return " ".join(parts)


def _format_run_linkage_details(run: RunRecord) -> str | None:
    if not (
        run.cycle_id
        or run.triggered_by_run_id
        or run.trigger_reason
        or run.sequence_index is not None
    ):
        return None
    lines = ["## Cycle linkage"]
    if run.cycle_id:
        lines.append(f"cycle_id: {run.cycle_id}")
    if run.triggered_by_run_id:
        lines.append(f"triggered_by_run_id: {run.triggered_by_run_id}")
    if run.trigger_reason:
        lines.append(f"trigger_reason: {run.trigger_reason}")
    if run.sequence_index is not None:
        lines.append(f"sequence_index: {run.sequence_index}")
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


def status_payload(context: AppContext, session_id: str | None = None) -> dict[str, object]:
    from orchestra.supervision import reconcile_stale_queued_runs

    reconcile_stale_queued_runs(context)
    global_runs = context.store.list_active_runs()
    global_limit = context.config.concurrency.global_limit
    per_session_limit = context.config.concurrency.per_session_limit
    if session_id is not None:
        _require_session_id(session_id)
    payload: dict[str, object] = {
        "contract_version": CONTRACT_VERSION,
        "kind": "status",
        "ok": True,
        "scope": "global" if session_id is None else "session",
        "orchestra_tools": (
            default_main_session_mode(context)
            if session_id is None
            else resolve_main_session_mode(context, session_id)
        ),
        "active_runs": {
            "count": len(global_runs) if session_id is None else 0,
            "limit": global_limit if session_id is None else per_session_limit,
            "runs": [],
        },
        "global_active_runs": {
            "count": len(global_runs),
            "limit": global_limit,
        },
    }
    if session_id is None:
        payload["active_runs"] = {
            "count": len(global_runs),
            "limit": global_limit,
            "runs": [
                {
                    "run_id": run.run_id,
                    "role": run.role,
                    "status": run.status,
                    "task_label": run.task_label,
                    "owner": run.orchestrator_session_id,
                    "model": run.model,
                    **(
                        {
                            "cycle_id": run.cycle_id,
                            "triggered_by_run_id": run.triggered_by_run_id,
                            "trigger_reason": run.trigger_reason,
                            "sequence_index": run.sequence_index,
                        }
                        if (
                            run.cycle_id
                            or run.triggered_by_run_id
                            or run.trigger_reason
                            or run.sequence_index is not None
                        )
                        else {}
                    ),
                }
                for run in global_runs
            ],
        }
        return payload

    lineage_session_ids = _orchestrator_lineage_session_ids(session_id)
    runs = _list_active_runs_for_session_ids(context, lineage_session_ids)
    role_counts: dict[str, int] = {}
    for run in runs:
        role_counts[run.role] = role_counts.get(run.role, 0) + 1
    details = session_status_details(context, lineage_session_ids, active_runs=runs)
    payload.update(
        {
            "session_id": session_id,
            "lineage_session_ids": lineage_session_ids if len(lineage_session_ids) > 1 else None,
            "active_runs": {
                "count": len(runs),
                "limit": per_session_limit,
                "runs": [
                    {
                        "run_id": run.run_id,
                        "role": run.role,
                        "status": run.status,
                        "task_label": run.task_label,
                        "model": run.model,
                        **(
                            {
                                "cycle_id": run.cycle_id,
                                "triggered_by_run_id": run.triggered_by_run_id,
                                "trigger_reason": run.trigger_reason,
                                "sequence_index": run.sequence_index,
                            }
                            if (
                                run.cycle_id
                                or run.triggered_by_run_id
                                or run.trigger_reason
                                or run.sequence_index is not None
                            )
                            else {}
                        ),
                    }
                    for run in runs
                ],
            },
            "role_counts": [
                {"role": role, "count": count}
                for role, count in sorted(role_counts.items())
            ],
            "descendants_terminal": details.descendants_terminal,
            "session_report_available": details.session_report_available,
            "session_report_delivered": details.session_report_delivered,
        }
    )
    return payload


def format_status(context: AppContext, session_id: str | None = None) -> str:
    from orchestra.supervision import reconcile_stale_queued_runs

    reconcile_stale_queued_runs(context)
    global_runs = context.store.list_active_runs()
    global_limit = context.config.concurrency.global_limit
    per_session_limit = context.config.concurrency.per_session_limit
    model_limits = context.catalog.model_limits
    if session_id is None:
        lines = [
            f"orchestra_tools: {default_main_session_mode(context)}",
            "scope: global",
            f"active_runs: {len(global_runs)}/{global_limit}",
            f"global_active_runs: {len(global_runs)}/{global_limit}",
        ]
        if model_limits:
            lines.append("model_active_runs:")
            for model in sorted(model_limits):
                active = sum(1 for run in global_runs if run.model == model)
                lines.append(f"- {model}: {active}/{model_limits[model].concurrency}")
        if not global_runs:
            lines.append("status: no active runs")
            return "\n".join(lines)

        lines.append("active:")
        for run in global_runs:
            lines.append(_compact_active_run_line(run, include_owner=True))
        return "\n".join(lines)

    _require_session_id(session_id)
    lineage_session_ids = _orchestrator_lineage_session_ids(session_id)
    runs = _list_active_runs_for_session_ids(context, lineage_session_ids)
    lines = [
        f"orchestra_tools: {resolve_main_session_mode(context, session_id)}",
        f"session_id: {session_id}",
    ]
    if len(lineage_session_ids) > 1:
        lines.append(f"lineage_current_session_id: {lineage_session_ids[-1]}")
        lines.append(f"lineage_session_ids: {', '.join(lineage_session_ids)}")
    lines.extend(
        [
            f"active_runs: {len(runs)}/{per_session_limit}",
            f"global_active_runs: {len(global_runs)}/{global_limit}",
        ]
    )
    if model_limits:
        lines.append("model_active_runs:")
        for model in sorted(model_limits):
            active = sum(1 for run in runs if run.model == model)
            lines.append(f"- {model}: {active}/{model_limits[model].concurrency}")
    details = session_status_details(context, lineage_session_ids, active_runs=runs)
    if not runs:
        lines.append("status: no active runs")
        _append_session_status_details(lines, details)
        return "\n".join(lines)

    _append_session_status_details(lines, details)
    lines.append("active:")
    for run in runs:
        lines.append(_compact_active_run_line(run, include_owner=len(lineage_session_ids) > 1))
    return "\n".join(lines)


def await_run_payload(
    record: RunRecord,
    *,
    active_remaining: int,
    details: SessionStatusDetails,
    prompts: PromptConfig | None = None,
) -> dict[str, object]:
    return {
        "contract_version": CONTRACT_VERSION,
        "kind": "await_run",
        "ok": True,
        "run_id": record.run_id,
        "status": record.status,
        "role": record.role,
        "harness": record.harness,
        "result": record.result_summary,
        "error": record.error_text,
        "blocker": record.blocker_text,
        "next": (
            _return_hint(record, prompts=prompts)
            if record.status == STATUS_INCOMPLETE
            else None
        ),
        "active_runs_remaining": active_remaining,
        "descendants_terminal": details.descendants_terminal,
        "session_report_available": details.session_report_available,
        "session_report_delivered": details.session_report_delivered,
    }


def _return_hint(run: RunRecord, *, prompts: PromptConfig | None = None) -> str | None:
    from orchestra.config import (
        DEFAULT_RETURN_HINT_DONE,
        DEFAULT_RETURN_HINT_FAILED,
        DEFAULT_RETURN_HINT_INCOMPLETE,
    )
    from orchestra.state import STATUS_CANCELLED, STATUS_DONE

    if run.status == STATUS_DONE:
        return prompts.return_hint_done if prompts is not None else DEFAULT_RETURN_HINT_DONE
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


def _find_pi_transcript(worker_session_id: str) -> Path | None:
    session_root = Path(
        os.environ.get(
            "PI_CODING_AGENT_SESSION_DIR",
            str(Path.home() / ".pi" / "agent" / "sessions"),
        )
    )
    if not session_root.is_dir():
        return None
    matches = list(session_root.rglob(f"*_{worker_session_id}.jsonl"))
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def _debug_file_section(title: str, path: Path) -> str:
    lines = [f"## {title}", f"path: {path}"]
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        lines.append("missing")
    else:
        lines.extend(["", text.rstrip()])
    return "\n".join(lines)


def _debug_transcript_section(record: RunRecord) -> str:
    lines = ["## Harness transcript"]
    if record.worker_session_id:
        lines.append(f"worker_session_id: {record.worker_session_id}")
    if record.transcript_path:
        lines.append(_debug_file_section("Transcript content", record.transcript_path))
        return "\n".join(lines)
    if record.worker_session_id and record.harness == "pi":
        fallback = _find_pi_transcript(record.worker_session_id)
        if fallback is not None:
            lines.append("transcript_path: discovered by Pi fallback search")
            lines.append(_debug_file_section("Transcript content", fallback))
            return "\n".join(lines)
        lines.append("transcript_path: not recorded")
        lines.append(
            "fallback_search: find \"${PI_CODING_AGENT_SESSION_DIR:-$HOME/.pi/agent/sessions}\" "
            f"-type f -name '*_{record.worker_session_id}.jsonl'"
        )
    else:
        lines.append("transcript_path: not available")
    return "\n".join(lines)


def _format_debug_bundle(context: AppContext, record: RunRecord) -> str:
    sections = [
        "# Orchestra debug bundle",
        "",
        "## Run state",
        format_run_report(record, prompts=context.config.prompts),
    ]
    linkage_details = _format_run_linkage_details(record)
    if linkage_details is not None:
        sections.append(linkage_details)
    request_path = context.config.state_dir / "requests" / f"{record.run_id}.json"
    sections.append(_debug_file_section("Request", request_path))
    sections.append(_debug_file_section("Lifecycle log", record.log_path))
    supervisor_output_path = record.supervisor_output_path or (
        record.log_path.parent / f"{record.run_id}.supervisor.log"
    )
    sections.append(_debug_file_section("Supervisor output", supervisor_output_path))
    if record.result_output:
        sections.append("## Full return")
        sections.append(record.result_output.rstrip())
    else:
        sections.append("## Full return\nmissing")
    sections.append(_debug_transcript_section(record))
    return "\n\n".join(sections)


def format_debug_run(context: AppContext, run_id: str) -> str:
    _reconcile_stale_queued_runs(context)
    record = context.store.get_run(run_id)
    return _format_debug_bundle(context, record)


def format_debug_session(context: AppContext, session_id: str, limit: int = 20) -> str:
    _reconcile_stale_queued_runs(context)
    _require_session_id(session_id)
    lineage_session_ids = _orchestrator_lineage_session_ids(session_id)
    runs = _list_runs_for_session_ids(context, lineage_session_ids, limit=limit)
    lines = ["# Orchestra debug session", "", f"session_id: {session_id}", f"runs: {len(runs)}"]
    for run in runs:
        lines.extend(["", _format_debug_bundle(context, run)])
    return "\n".join(lines)


def format_history(context: AppContext, session_id: str, limit: int) -> str:
    _reconcile_stale_queued_runs(context)
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
        if run.cycle_id:
            lines.append(f"  cycle_id: {run.cycle_id}")
        if run.triggered_by_run_id:
            lines.append(f"  triggered_by_run_id: {run.triggered_by_run_id}")
        if run.trigger_reason:
            lines.append(f"  trigger_reason: {run.trigger_reason}")
        if run.sequence_index is not None:
            lines.append(f"  sequence_index: {run.sequence_index}")
        if run.worker_session_id:
            lines.append(f"  worker_session_id: {run.worker_session_id}")
        lines.append(f"  log: {run.log_path}")
    return "\n".join(lines)
