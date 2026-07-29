"""SQLite-backed runtime state for Orchestra."""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, replace
from pathlib import Path

from orchestra.logs import append_jsonl_event, utc_now

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

ACTIVE_STATUSES = frozenset({STATUS_QUEUED, STATUS_RUNNING})
TERMINAL_STATUSES = frozenset({STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED})
ALL_STATUSES = ACTIVE_STATUSES | TERMINAL_STATUSES
_CONNECT_ATTEMPTS = 8
_CONNECT_RETRY_BASE_DELAY_SECONDS = 0.25
_CONNECT_RETRY_MAX_DELAY_SECONDS = 3.0
_BEGIN_IMMEDIATE_SLOW_LOG_SECONDS = 0.1
ALLOWED_TRANSITIONS = {
    STATUS_QUEUED: frozenset({STATUS_RUNNING, STATUS_FAILED, STATUS_CANCELLED}),
    STATUS_RUNNING: frozenset({STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED}),
}


class StateError(ValueError):
    """Raised for invalid runtime state operations."""


class ConcurrencyLimitError(StateError):
    """Raised when an atomic reservation exceeds configured limits."""


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    orchestrator_session_id: str
    harness: str
    role: str
    task_label: str
    log_path: Path
    created_at: str
    status: str = STATUS_QUEUED
    batch_id: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    process_id: int | None = None
    process_group_id: int | None = None
    result_summary: str | None = None
    error_text: str | None = None
    blocker_text: str | None = None
    worker_session_id: str | None = None
    transcript_path: Path | None = None
    approval_needed: bool = False
    report_claimed_at: str | None = None
    reported_at: str | None = None


@dataclass(frozen=True)
class RunUpdate:
    status: str
    started_at: str | None = None
    ended_at: str | None = None
    process_id: int | None = None
    process_group_id: int | None = None
    result_summary: str | None = None
    error_text: str | None = None
    blocker_text: str | None = None
    worker_session_id: str | None = None
    transcript_path: Path | None = None
    approval_needed: bool | None = None
    reported_at: str | None = None


_LOG = logging.getLogger(__name__)


class StateStore:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    orchestrator_session_id TEXT NOT NULL,
                    batch_id TEXT,
                    harness TEXT NOT NULL,
                    role TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    ended_at TEXT,
                    process_id INTEGER,
                    process_group_id INTEGER,
                    task_label TEXT NOT NULL,
                    result_summary TEXT,
                    error_text TEXT,
                    blocker_text TEXT,
                    log_path TEXT NOT NULL,
                    worker_session_id TEXT,
                    transcript_path TEXT,
                    approval_needed INTEGER NOT NULL DEFAULT 0,
                    report_claimed_at TEXT,
                    reported_at TEXT
                )
                """
            )
            self._ensure_column(connection, "runs", "process_group_id", "INTEGER")
            self._ensure_column(connection, "runs", "report_claimed_at", "TEXT")
            self._ensure_column(connection, "runs", "reported_at", "TEXT")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_session_status "
                "ON runs(orchestrator_session_id, status)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_session_reported "
                "ON runs(orchestrator_session_id, reported_at)"
            )
            connection.execute("PRAGMA user_version = 4")
            connection.commit()

    def reserve_run(
        self,
        record: RunRecord,
        *,
        global_limit: int,
        per_session_limit: int,
    ) -> RunRecord:
        _validate_status(record.status)
        if record.status != STATUS_QUEUED:
            raise StateError("new runs must start in 'queued' status")
        if not record.run_id.strip():
            raise StateError("run_id must be a non-empty string")
        if not record.orchestrator_session_id.strip():
            raise StateError("orchestrator_session_id must be a non-empty string")

        with self._connect() as connection:
            self._begin_immediate(connection, operation="reserve_run")
            global_active = int(
                connection.execute(
                    "SELECT COUNT(*) FROM runs WHERE status IN (?, ?)",
                    (STATUS_QUEUED, STATUS_RUNNING),
                ).fetchone()[0]
            )
            if global_active >= global_limit:
                connection.rollback()
                raise ConcurrencyLimitError("global concurrency limit exceeded")

            session_active = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM runs
                    WHERE orchestrator_session_id = ?
                      AND status IN (?, ?)
                    """,
                    (record.orchestrator_session_id, STATUS_QUEUED, STATUS_RUNNING),
                ).fetchone()[0]
            )
            if session_active >= per_session_limit:
                connection.rollback()
                raise ConcurrencyLimitError("per-session concurrency limit exceeded")

            connection.execute(
                """
                INSERT INTO runs (
                    run_id,
                    orchestrator_session_id,
                    batch_id,
                    harness,
                    role,
                    status,
                    created_at,
                    started_at,
                    ended_at,
                    process_id,
                    process_group_id,
                    task_label,
                    result_summary,
                    error_text,
                    blocker_text,
                    log_path,
                    worker_session_id,
                    transcript_path,
                    approval_needed,
                    report_claimed_at,
                    reported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._serialize_record(record),
            )
            connection.commit()

        self._log_event(
            record,
            event="run.created",
            details={
                "task_label": record.task_label,
                "harness": record.harness,
                "role": record.role,
            },
        )
        return record

    def create_run(self, record: RunRecord) -> RunRecord:
        return self.reserve_run(record, global_limit=10_000_000, per_session_limit=10_000_000)

    def get_run(self, run_id: str) -> RunRecord:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise StateError(f"run not found: {run_id}")
        return self._row_to_record(row)

    def update_run(self, run_id: str, update: RunUpdate) -> RunRecord:
        _validate_status(update.status)
        with self._connect() as connection:
            self._begin_immediate(connection, operation="update_run")
            row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                connection.rollback()
                raise StateError(f"run not found: {run_id}")

            current = self._row_to_record(row)
            if current.status in TERMINAL_STATUSES:
                connection.rollback()
                return current
            _validate_transition(current.status, update.status)
            next_record = self._merge_record(current, update)
            changed = self._write_record(connection, next_record, expected_status=current.status)
            if not changed:
                connection.rollback()
                return self.get_run(run_id)
            connection.commit()

        self._log_event(
            next_record,
            event="run.updated",
            details={
                "previous_status": current.status,
                "process_id": next_record.process_id,
                "process_group_id": next_record.process_group_id,
                "result_summary": next_record.result_summary,
                "error_text": next_record.error_text,
                "blocker_text": next_record.blocker_text,
            },
        )
        return next_record

    def list_active_runs(self, orchestrator_session_id: str | None = None) -> list[RunRecord]:
        query = "SELECT * FROM runs WHERE status IN (?, ?)"
        params: tuple[str, ...] | tuple[str, str, str]
        if orchestrator_session_id is None:
            params = (STATUS_QUEUED, STATUS_RUNNING)
        else:
            query += " AND orchestrator_session_id = ?"
            params = (STATUS_QUEUED, STATUS_RUNNING, orchestrator_session_id)
        query += " ORDER BY created_at, run_id"

        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    def count_active_runs(self, orchestrator_session_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*)
                FROM runs
                WHERE orchestrator_session_id = ?
                  AND status IN (?, ?)
                """,
                (orchestrator_session_id, STATUS_QUEUED, STATUS_RUNNING),
            ).fetchone()
        return int(row[0])

    def list_runs(self, orchestrator_session_id: str, *, limit: int = 20) -> list[RunRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM runs
                WHERE orchestrator_session_id = ?
                ORDER BY created_at DESC, run_id DESC
                LIMIT ?
                """,
                (orchestrator_session_id, limit),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_pending_report_runs(self, orchestrator_session_id: str) -> list[RunRecord]:
        with self._connect() as connection:
            active = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM runs
                    WHERE orchestrator_session_id = ?
                      AND status IN (?, ?)
                    """,
                    (orchestrator_session_id, STATUS_QUEUED, STATUS_RUNNING),
                ).fetchone()[0]
            )
            if active > 0:
                return []

            rows = connection.execute(
                """
                SELECT *
                FROM runs
                WHERE orchestrator_session_id = ?
                  AND status IN (?, ?, ?)
                  AND report_claimed_at IS NULL
                  AND reported_at IS NULL
                ORDER BY created_at, run_id
                """,
                (orchestrator_session_id, STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def claim_pending_report_runs(self, orchestrator_session_id: str) -> list[RunRecord]:
        with self._connect() as connection:
            self._begin_immediate(connection, operation="claim_pending_report_runs")
            active = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM runs
                    WHERE orchestrator_session_id = ?
                      AND status IN (?, ?)
                    """,
                    (orchestrator_session_id, STATUS_QUEUED, STATUS_RUNNING),
                ).fetchone()[0]
            )
            if active > 0:
                connection.rollback()
                return []

            rows = connection.execute(
                """
                SELECT *
                FROM runs
                WHERE orchestrator_session_id = ?
                  AND status IN (?, ?, ?)
                  AND report_claimed_at IS NULL
                  AND reported_at IS NULL
                ORDER BY created_at, run_id
                """,
                (orchestrator_session_id, STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED),
            ).fetchall()
            if not rows:
                connection.rollback()
                return []

            claimed_at = utc_now()
            run_ids = [str(row["run_id"]) for row in rows]
            placeholders = ", ".join("?" for _ in run_ids)
            connection.execute(
                f"""
                UPDATE runs
                SET report_claimed_at = ?
                WHERE orchestrator_session_id = ?
                  AND run_id IN ({placeholders})
                  AND report_claimed_at IS NULL
                  AND reported_at IS NULL
                """,
                (claimed_at, orchestrator_session_id, *run_ids),
            )
            connection.commit()
        return [replace(self._row_to_record(row), report_claimed_at=claimed_at) for row in rows]

    def release_report_runs(
        self,
        orchestrator_session_id: str,
        run_ids: list[str],
    ) -> None:
        if not run_ids:
            return
        placeholders = ", ".join("?" for _ in run_ids)
        with self._connect() as connection:
            connection.execute(
                f"""
                UPDATE runs
                SET report_claimed_at = NULL
                WHERE orchestrator_session_id = ?
                  AND run_id IN ({placeholders})
                  AND reported_at IS NULL
                """,
                (orchestrator_session_id, *run_ids),
            )
            connection.commit()

    def mark_report_runs_delivered(
        self,
        orchestrator_session_id: str,
        run_ids: list[str],
    ) -> list[RunRecord]:
        if not run_ids:
            return []
        delivered_at = utc_now()
        placeholders = ", ".join("?" for _ in run_ids)
        with self._connect() as connection:
            self._begin_immediate(connection, operation="mark_report_runs_delivered")
            connection.execute(
                f"""
                UPDATE runs
                SET report_claimed_at = NULL,
                    reported_at = ?
                WHERE orchestrator_session_id = ?
                  AND run_id IN ({placeholders})
                  AND reported_at IS NULL
                """,
                (delivered_at, orchestrator_session_id, *run_ids),
            )
            rows = connection.execute(
                f"SELECT * FROM runs WHERE run_id IN ({placeholders}) ORDER BY created_at, run_id",
                (*run_ids,),
            ).fetchall()
            connection.commit()
        return [self._row_to_record(row) for row in rows]

    def consume_pending_report_runs(self, orchestrator_session_id: str) -> list[RunRecord]:
        runs = self.claim_pending_report_runs(orchestrator_session_id)
        return self.mark_report_runs_delivered(
            orchestrator_session_id,
            [run.run_id for run in runs],
        )

    def _connect(self) -> sqlite3.Connection:
        last_error: sqlite3.OperationalError | None = None
        for attempt in range(_CONNECT_ATTEMPTS):
            try:
                connection = sqlite3.connect(self.database_path, timeout=30.0)
                connection.row_factory = sqlite3.Row
                return connection
            except sqlite3.OperationalError as exc:
                last_error = exc
                if attempt == _CONNECT_ATTEMPTS - 1:
                    break
                time.sleep(self._connect_retry_delay_seconds(attempt))
        assert last_error is not None
        raise sqlite3.OperationalError(
            f"{last_error} (database_path={self.database_path})"
        ) from last_error

    def _begin_immediate(self, connection: sqlite3.Connection, *, operation: str) -> None:
        started = time.perf_counter()
        connection.execute("BEGIN IMMEDIATE")
        elapsed = time.perf_counter() - started
        if elapsed > _BEGIN_IMMEDIATE_SLOW_LOG_SECONDS:
            _LOG.warning(
                "StateStore BEGIN IMMEDIATE slow: operation=%s elapsed_ms=%.1f database_path=%s",
                operation,
                elapsed * 1000,
                self.database_path,
            )

    def _connect_retry_delay_seconds(self, attempt: int) -> float:
        return float(
            min(
                _CONNECT_RETRY_BASE_DELAY_SECONDS * (2**attempt),
                _CONNECT_RETRY_MAX_DELAY_SECONDS,
            )
        )

    def _merge_record(self, current: RunRecord, update: RunUpdate) -> RunRecord:
        next_record = replace(
            current,
            status=update.status,
            started_at=update.started_at if update.started_at is not None else current.started_at,
            ended_at=update.ended_at if update.ended_at is not None else current.ended_at,
            process_id=update.process_id if update.process_id is not None else current.process_id,
            process_group_id=(
                update.process_group_id
                if update.process_group_id is not None
                else current.process_group_id
            ),
            result_summary=(
                update.result_summary
                if update.result_summary is not None
                else current.result_summary
            ),
            error_text=(
                update.error_text if update.error_text is not None else current.error_text
            ),
            blocker_text=(
                update.blocker_text if update.blocker_text is not None else current.blocker_text
            ),
            worker_session_id=(
                update.worker_session_id
                if update.worker_session_id is not None
                else current.worker_session_id
            ),
            transcript_path=(
                update.transcript_path
                if update.transcript_path is not None
                else current.transcript_path
            ),
            approval_needed=(
                update.approval_needed
                if update.approval_needed is not None
                else current.approval_needed
            ),
            report_claimed_at=current.report_claimed_at,
            reported_at=(
                update.reported_at if update.reported_at is not None else current.reported_at
            ),
        )

        if update.status == STATUS_RUNNING and next_record.started_at is None:
            next_record = replace(next_record, started_at=utc_now())
        if update.status in TERMINAL_STATUSES and next_record.ended_at is None:
            next_record = replace(next_record, ended_at=utc_now())
        return next_record

    def _write_record(
        self,
        connection: sqlite3.Connection,
        record: RunRecord,
        *,
        expected_status: str,
    ) -> bool:
        cursor = connection.execute(
            """
            UPDATE runs
            SET status = ?,
                started_at = ?,
                ended_at = ?,
                process_id = ?,
                process_group_id = ?,
                result_summary = ?,
                error_text = ?,
                blocker_text = ?,
                worker_session_id = ?,
                transcript_path = ?,
                approval_needed = ?,
                report_claimed_at = ?,
                reported_at = ?
            WHERE run_id = ?
              AND status = ?
            """,
            (
                record.status,
                record.started_at,
                record.ended_at,
                record.process_id,
                record.process_group_id,
                record.result_summary,
                record.error_text,
                record.blocker_text,
                record.worker_session_id,
                str(record.transcript_path) if record.transcript_path else None,
                int(record.approval_needed),
                record.report_claimed_at,
                record.reported_at,
                record.run_id,
                expected_status,
            ),
        )
        return cursor.rowcount == 1

    def _serialize_record(self, record: RunRecord) -> tuple[object, ...]:
        return (
            record.run_id,
            record.orchestrator_session_id,
            record.batch_id,
            record.harness,
            record.role,
            record.status,
            record.created_at,
            record.started_at,
            record.ended_at,
            record.process_id,
            record.process_group_id,
            record.task_label,
            record.result_summary,
            record.error_text,
            record.blocker_text,
            str(record.log_path),
            record.worker_session_id,
            str(record.transcript_path) if record.transcript_path else None,
            int(record.approval_needed),
            record.report_claimed_at,
            record.reported_at,
        )

    def _row_to_record(self, row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            run_id=str(row["run_id"]),
            orchestrator_session_id=str(row["orchestrator_session_id"]),
            batch_id=_optional_text(row["batch_id"]),
            harness=str(row["harness"]),
            role=str(row["role"]),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            started_at=_optional_text(row["started_at"]),
            ended_at=_optional_text(row["ended_at"]),
            process_id=int(row["process_id"]) if row["process_id"] is not None else None,
            process_group_id=(
                int(row["process_group_id"]) if row["process_group_id"] is not None else None
            ),
            task_label=str(row["task_label"]),
            result_summary=_optional_text(row["result_summary"]),
            error_text=_optional_text(row["error_text"]),
            blocker_text=_optional_text(row["blocker_text"]),
            log_path=Path(str(row["log_path"])),
            worker_session_id=_optional_text(row["worker_session_id"]),
            transcript_path=(
                Path(str(row["transcript_path"])) if row["transcript_path"] is not None else None
            ),
            approval_needed=bool(row["approval_needed"]),
            report_claimed_at=_optional_text(row["report_claimed_at"]),
            reported_at=_optional_text(row["reported_at"]),
        )

    def _log_event(
        self,
        record: RunRecord,
        *,
        event: str,
        details: dict[str, object | None],
    ) -> None:
        append_jsonl_event(
            record.log_path,
            {
                "event": event,
                "run_id": record.run_id,
                "orchestrator_session_id": record.orchestrator_session_id,
                "status": record.status,
                **details,
            },
        )

    def _ensure_column(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_type: str,
    ) -> None:
        rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        existing = {str(row[1]) for row in rows}
        if column_name not in existing:
            connection.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
            )


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _validate_status(status: str) -> None:
    if status not in ALL_STATUSES:
        raise StateError(f"invalid run status: {status}")


def _validate_transition(current: str, target: str) -> None:
    if current not in ALLOWED_TRANSITIONS or target not in ALLOWED_TRANSITIONS[current]:
        raise StateError(f"invalid status transition: {current} -> {target}")
