"""SQLite-backed runtime state for Orchestra."""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from orchestra.logs import append_jsonl_event, utc_now

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_INCOMPLETE = "incomplete"

MAIN_SESSION_MODE_OFF = "off"
MAIN_SESSION_MODE_ON = "on"
MAIN_SESSION_MODE_ORCHESTRATOR = "orchestrator"
ALLOWED_MAIN_SESSION_MODES = frozenset(
    {MAIN_SESSION_MODE_OFF, MAIN_SESSION_MODE_ON, MAIN_SESSION_MODE_ORCHESTRATOR}
)

ACTIVE_STATUSES = frozenset({STATUS_QUEUED, STATUS_RUNNING})
TERMINAL_STATUSES = frozenset({STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED, STATUS_INCOMPLETE})
ALL_STATUSES = ACTIVE_STATUSES | TERMINAL_STATUSES
_SCHEMA_VERSION = 14
_CONNECT_ATTEMPTS = 8
_CONNECT_RETRY_BASE_DELAY_SECONDS = 0.25
_CONNECT_RETRY_MAX_DELAY_SECONDS = 3.0
_SQLITE_CONNECT_TIMEOUT_SECONDS = 1.0
_BEGIN_IMMEDIATE_SLOW_LOG_SECONDS = 0.1
_REPORT_CLAIM_LEASE_SECONDS = 300
ALLOWED_TRANSITIONS = {
    STATUS_QUEUED: frozenset({STATUS_QUEUED, STATUS_RUNNING, STATUS_FAILED, STATUS_CANCELLED}),
    STATUS_RUNNING: frozenset({STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED, STATUS_INCOMPLETE}),
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
    model: str | None = None
    status: str = STATUS_QUEUED
    batch_id: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    supervisor_pid: int | None = None
    supervisor_started_at: str | None = None
    supervisor_output_path: Path | None = None
    process_id: int | None = None
    process_group_id: int | None = None
    result_summary: str | None = None
    result_output: str | None = None
    result_summary_truncated: bool = False
    error_text: str | None = None
    blocker_text: str | None = None
    worker_session_id: str | None = None
    transcript_path: Path | None = None
    approval_needed: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    report_claimed_at: str | None = None
    reported_at: str | None = None
    cycle_id: str | None = None
    triggered_by_run_id: str | None = None
    trigger_reason: str | None = None
    sequence_index: int | None = None


@dataclass(frozen=True)
class MainSessionState:
    session_id: str
    main_session_mode: str
    updated_at: str | None = None


@dataclass(frozen=True)
class PruneCandidate:
    run_id: str
    orchestrator_session_id: str
    role: str
    status: str
    created_at: str
    cutoff_at: str
    owned_paths: tuple[Path, ...]


@dataclass(frozen=True)
class PrunePlan:
    retention_days: int
    cutoff_at: str
    candidates: tuple[PruneCandidate, ...]
    orphan_candidates: tuple[Path, ...] = ()

    @property
    def owned_paths(self) -> tuple[Path, ...]:
        paths: list[Path] = []
        for candidate in self.candidates:
            paths.extend(candidate.owned_paths)
        return tuple(paths)


@dataclass(frozen=True)
class PruneResult:
    deleted_run_ids: tuple[str, ...]
    deleted_session_ids: tuple[str, ...]
    deleted_paths: tuple[Path, ...]
    skipped_paths: tuple[Path, ...]
    failed_paths: tuple[Path, ...]


@dataclass(frozen=True)
class RunUpdate:
    status: str
    harness: str | None = None
    role: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    supervisor_pid: int | None = None
    supervisor_started_at: str | None = None
    supervisor_output_path: Path | None = None
    process_id: int | None = None
    process_group_id: int | None = None
    result_summary: str | None = None
    result_output: str | None = None
    result_summary_truncated: bool | None = None
    error_text: str | None = None
    blocker_text: str | None = None
    worker_session_id: str | None = None
    transcript_path: Path | None = None
    approval_needed: bool | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    reported_at: str | None = None
    cycle_id: str | None = None
    triggered_by_run_id: str | None = None
    trigger_reason: str | None = None
    sequence_index: int | None = None


_LOG = logging.getLogger(__name__)


class StateStore:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        if self._has_current_schema():
            return

        last_error: sqlite3.OperationalError | None = None
        for attempt in range(_CONNECT_ATTEMPTS):
            try:
                self._initialize_schema()
                return
            except sqlite3.OperationalError as exc:
                last_error = exc
                if not _is_transient_sqlite_error(exc) or attempt == _CONNECT_ATTEMPTS - 1:
                    break
                time.sleep(self._connect_retry_delay_seconds(attempt))

        assert last_error is not None
        raise last_error

    def _initialize_schema(self) -> None:
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
                    model TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    ended_at TEXT,
                    supervisor_pid INTEGER,
                    supervisor_started_at TEXT,
                    supervisor_output_path TEXT,
                    process_id INTEGER,
                    process_group_id INTEGER,
                    task_label TEXT NOT NULL,
                    result_summary TEXT,
                    result_output TEXT,
                    result_summary_truncated INTEGER NOT NULL DEFAULT 0,
                    error_text TEXT,
                    blocker_text TEXT,
                    log_path TEXT NOT NULL,
                    worker_session_id TEXT,
                    transcript_path TEXT,
                    approval_needed INTEGER NOT NULL DEFAULT 0,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    cache_read_tokens INTEGER,
                    cache_write_tokens INTEGER,
                    report_claimed_at TEXT,
                    reported_at TEXT,
                    cycle_id TEXT,
                    triggered_by_run_id TEXT,
                    trigger_reason TEXT,
                    sequence_index INTEGER
                )
                """
            )
            self._ensure_column(connection, "runs", "model", "TEXT")
            self._ensure_column(connection, "runs", "supervisor_pid", "INTEGER")
            self._ensure_column(connection, "runs", "supervisor_started_at", "TEXT")
            self._ensure_column(connection, "runs", "supervisor_output_path", "TEXT")
            self._ensure_column(connection, "runs", "process_group_id", "INTEGER")
            self._ensure_column(connection, "runs", "result_output", "TEXT")
            self._ensure_column(
                connection,
                "runs",
                "result_summary_truncated",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(connection, "runs", "input_tokens", "INTEGER")
            self._ensure_column(connection, "runs", "output_tokens", "INTEGER")
            self._ensure_column(connection, "runs", "cache_read_tokens", "INTEGER")
            self._ensure_column(connection, "runs", "cache_write_tokens", "INTEGER")
            self._ensure_column(connection, "runs", "report_claimed_at", "TEXT")
            self._ensure_column(connection, "runs", "reported_at", "TEXT")
            self._ensure_column(connection, "runs", "cycle_id", "TEXT")
            self._ensure_column(connection, "runs", "triggered_by_run_id", "TEXT")
            self._ensure_column(connection, "runs", "trigger_reason", "TEXT")
            self._ensure_column(connection, "runs", "sequence_index", "INTEGER")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    main_session_mode TEXT NOT NULL DEFAULT 'on',
                    updated_at TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_session_status "
                "ON runs(orchestrator_session_id, status)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_runs_session_reported "
                "ON runs(orchestrator_session_id, reported_at)"
            )
            connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            connection.commit()

    def reserve_run(
        self,
        record: RunRecord,
        *,
        global_limit: int,
        per_session_limit: int,
        per_model_limits: dict[str, int] | None = None,
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

            model = record.model
            model_limit = (per_model_limits or {}).get(model or "")
            if model and model_limit is not None:
                model_active = int(
                    connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM runs
                        WHERE model = ?
                          AND status IN (?, ?)
                        """,
                        (model, STATUS_QUEUED, STATUS_RUNNING),
                    ).fetchone()[0]
                )
                if model_active >= model_limit:
                    connection.rollback()
                    raise ConcurrencyLimitError(
                        f"model concurrency limit exceeded: {model} "
                        f"active={model_active} limit={model_limit}"
                    )

            connection.execute(
                """
                INSERT INTO runs (
                    run_id,
                    orchestrator_session_id,
                    batch_id,
                    harness,
                    role,
                    model,
                    status,
                    created_at,
                    started_at,
                    ended_at,
                    supervisor_pid,
                    supervisor_started_at,
                    supervisor_output_path,
                    process_id,
                    process_group_id,
                    task_label,
                    result_summary,
                    result_output,
                    result_summary_truncated,
                    error_text,
                    blocker_text,
                    log_path,
                    worker_session_id,
                    transcript_path,
                    approval_needed,
                    input_tokens,
                    output_tokens,
                    cache_read_tokens,
                    cache_write_tokens,
                    report_claimed_at,
                    reported_at,
                    cycle_id,
                    triggered_by_run_id,
                    trigger_reason,
                    sequence_index
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
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
                "model": record.model,
            },
        )
        return record

    def create_run(self, record: RunRecord) -> RunRecord:
        return self.reserve_run(
            record,
            global_limit=10_000_000,
            per_session_limit=10_000_000,
        )

    def set_main_session_mode(self, session_id: str, mode: str) -> MainSessionState:
        if not session_id.strip():
            raise StateError("session_id must be a non-empty string")
        _validate_main_session_mode(mode)
        updated_at = utc_now()
        with self._connect() as connection:
            self._begin_immediate(connection, operation="set_main_session_mode")
            connection.execute(
                """
                INSERT INTO sessions (session_id, main_session_mode, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    main_session_mode = excluded.main_session_mode,
                    updated_at = excluded.updated_at
                """,
                (session_id, mode, updated_at),
            )
            connection.commit()
        return MainSessionState(
            session_id=session_id,
            main_session_mode=mode,
            updated_at=updated_at,
        )

    def get_main_session_state(self, session_id: str) -> MainSessionState | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        return MainSessionState(
            session_id=str(row["session_id"]),
            main_session_mode=str(row["main_session_mode"]),
            updated_at=_optional_text(row["updated_at"]),
        )

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
                "harness": next_record.harness,
                "role": next_record.role,
                "supervisor_pid": next_record.supervisor_pid,
                "supervisor_output_path": str(next_record.supervisor_output_path)
                if next_record.supervisor_output_path
                else None,
                "process_id": next_record.process_id,
                "process_group_id": next_record.process_group_id,
                "result_summary": next_record.result_summary,
                "result_summary_truncated": next_record.result_summary_truncated,
                "error_text": next_record.error_text,
                "blocker_text": next_record.blocker_text,
                "worker_session_id": next_record.worker_session_id,
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

    def list_all_runs(self, *, limit: int = 20) -> list[RunRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM runs
                ORDER BY created_at DESC, run_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def plan_prune(
        self,
        retention_days: int,
        *,
        now: datetime | None = None,
        request_dir: Path | None = None,
        log_dir: Path | None = None,
    ) -> PrunePlan:
        if retention_days <= 0:
            raise StateError("retention_days must be a positive integer")
        reference_dt = now or datetime.now(UTC)
        cutoff_dt = reference_dt - timedelta(days=retention_days)
        cutoff_at = cutoff_dt.isoformat(timespec="seconds").replace("+00:00", "Z")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM runs
                WHERE status IN (?, ?, ?, ?)
                ORDER BY created_at, run_id
                """,
                (STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED, STATUS_INCOMPLETE),
            ).fetchall()
            all_rows = connection.execute("SELECT * FROM runs ORDER BY run_id").fetchall()
        candidates = []
        owned_paths: set[Path] = set()
        for row in rows:
            record = self._row_to_record(row)
            prune_at = _prune_reference_timestamp(record)
            if prune_at >= cutoff_dt:
                continue
            candidate_paths = tuple(
                path
                for path in (
                    record.log_path,
                    record.transcript_path,
                    record.supervisor_output_path,
                    request_dir / f"{record.run_id}.json" if request_dir is not None else None,
                )
                if path is not None
            )
            owned_paths.update(candidate_paths)
            candidates.append(
                PruneCandidate(
                    run_id=record.run_id,
                    orchestrator_session_id=record.orchestrator_session_id,
                    role=record.role,
                    status=record.status,
                    created_at=record.created_at,
                    cutoff_at=cutoff_at,
                    owned_paths=candidate_paths,
                )
            )
        for row in all_rows:
            record = self._row_to_record(row)
            owned_paths.update(
                path
                for path in (
                    record.log_path,
                    record.transcript_path,
                    record.supervisor_output_path,
                    request_dir / f"{record.run_id}.json" if request_dir is not None else None,
                )
                if path is not None
            )
        orphan_candidates = _list_orphan_candidates(
            cutoff_dt=cutoff_dt,
            request_dir=request_dir,
            log_dir=log_dir,
            owned_paths=owned_paths,
        )
        return PrunePlan(
            retention_days=retention_days,
            cutoff_at=cutoff_at,
            candidates=tuple(candidates),
            orphan_candidates=tuple(orphan_candidates),
        )

    def delete_prune_candidates(
        self,
        plan: PrunePlan,
        *,
        allowed_roots: tuple[Path, ...],
    ) -> PruneResult:
        deleted_paths: list[Path] = []
        skipped_paths: list[Path] = []
        failed_paths: list[Path] = []
        deletable_run_ids: list[str] = []
        allowed = tuple(root.resolve() for root in allowed_roots)
        for candidate in plan.candidates:
            candidate_failed = False
            for path in candidate.owned_paths:
                if not _path_is_under_roots(path, allowed):
                    skipped_paths.append(path)
                    continue
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    failed_paths.append(path)
                    candidate_failed = True
                    continue
                deleted_paths.append(path)
            if not candidate_failed:
                deletable_run_ids.append(candidate.run_id)

        for path in plan.orphan_candidates:
            if not _path_is_under_roots(path, allowed):
                skipped_paths.append(path)
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError:
                failed_paths.append(path)
                continue
            deleted_paths.append(path)

        deleted_session_ids: tuple[str, ...] = ()
        if deletable_run_ids:
            placeholders = ", ".join("?" for _ in deletable_run_ids)
            with self._connect() as connection:
                self._begin_immediate(connection, operation="delete_prune_candidates")
                connection.execute(
                    f"DELETE FROM runs WHERE run_id IN ({placeholders})",
                    tuple(deletable_run_ids),
                )
                session_rows = connection.execute(
                    """
                    SELECT session_id
                    FROM sessions
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM runs
                        WHERE runs.orchestrator_session_id = sessions.session_id
                    )
                    ORDER BY session_id
                    """
                ).fetchall()
                deleted_session_ids = tuple(str(row["session_id"]) for row in session_rows)
                if deleted_session_ids:
                    session_placeholders = ", ".join("?" for _ in deleted_session_ids)
                    connection.execute(
                        f"DELETE FROM sessions WHERE session_id IN ({session_placeholders})",
                        deleted_session_ids,
                    )
                connection.commit()

        return PruneResult(
            deleted_run_ids=tuple(deletable_run_ids),
            deleted_session_ids=deleted_session_ids,
            deleted_paths=tuple(deleted_paths),
            skipped_paths=tuple(skipped_paths),
            failed_paths=tuple(failed_paths),
        )

    def list_pending_report_runs(self, orchestrator_session_id: str) -> list[RunRecord]:
        claim_stale_before = _report_claim_stale_before()
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
                  AND status IN (?, ?, ?, ?)
                  AND reported_at IS NULL
                  AND (report_claimed_at IS NULL OR report_claimed_at < ?)
                ORDER BY created_at, run_id
                """,
                (
                    orchestrator_session_id,
                    STATUS_DONE,
                    STATUS_FAILED,
                    STATUS_CANCELLED,
                    STATUS_INCOMPLETE,
                    claim_stale_before,
                ),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def claim_pending_report_runs(self, orchestrator_session_id: str) -> list[RunRecord]:
        claim_stale_before = _report_claim_stale_before()
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
                  AND status IN (?, ?, ?, ?)
                  AND reported_at IS NULL
                  AND (report_claimed_at IS NULL OR report_claimed_at < ?)
                ORDER BY created_at, run_id
                """,
                (
                    orchestrator_session_id,
                    STATUS_DONE,
                    STATUS_FAILED,
                    STATUS_CANCELLED,
                    STATUS_INCOMPLETE,
                    claim_stale_before,
                ),
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
                  AND reported_at IS NULL
                  AND (report_claimed_at IS NULL OR report_claimed_at < ?)
                """,
                (claimed_at, orchestrator_session_id, *run_ids, claim_stale_before),
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
            self._begin_immediate(connection, operation="release_report_runs")
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
                connection = sqlite3.connect(
                    self.database_path,
                    timeout=_SQLITE_CONNECT_TIMEOUT_SECONDS,
                )
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
        last_error: sqlite3.OperationalError | None = None
        for attempt in range(_CONNECT_ATTEMPTS):
            started = time.perf_counter()
            try:
                connection.execute("BEGIN IMMEDIATE")
                elapsed = time.perf_counter() - started
                if elapsed > _BEGIN_IMMEDIATE_SLOW_LOG_SECONDS:
                    _LOG.warning(
                        "StateStore BEGIN IMMEDIATE slow: "
                        "operation=%s elapsed_ms=%.1f database_path=%s",
                        operation,
                        elapsed * 1000,
                        self.database_path,
                    )
                return
            except sqlite3.OperationalError as exc:
                last_error = exc
                if not _is_transient_sqlite_error(exc) or attempt == _CONNECT_ATTEMPTS - 1:
                    break
                time.sleep(self._connect_retry_delay_seconds(attempt))
        assert last_error is not None
        raise last_error

    def _has_current_schema(self) -> bool:
        if not self.database_path.exists():
            return False
        try:
            with sqlite3.connect(
                f"file:{self.database_path}?mode=ro",
                uri=True,
                timeout=_SQLITE_CONNECT_TIMEOUT_SECONDS,
            ) as connection:
                row = connection.execute("PRAGMA user_version").fetchone()
        except sqlite3.OperationalError:
            return False
        return row is not None and int(row[0]) >= _SCHEMA_VERSION

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
            harness=update.harness if update.harness is not None else current.harness,
            role=update.role if update.role is not None else current.role,
            started_at=update.started_at if update.started_at is not None else current.started_at,
            ended_at=update.ended_at if update.ended_at is not None else current.ended_at,
            supervisor_pid=(
                update.supervisor_pid
                if update.supervisor_pid is not None
                else current.supervisor_pid
            ),
            supervisor_started_at=(
                update.supervisor_started_at
                if update.supervisor_started_at is not None
                else current.supervisor_started_at
            ),
            supervisor_output_path=(
                update.supervisor_output_path
                if update.supervisor_output_path is not None
                else current.supervisor_output_path
            ),
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
            result_output=(
                update.result_output
                if update.result_output is not None
                else current.result_output
            ),
            result_summary_truncated=(
                update.result_summary_truncated
                if update.result_summary_truncated is not None
                else current.result_summary_truncated
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
            input_tokens=(
                update.input_tokens if update.input_tokens is not None else current.input_tokens
            ),
            output_tokens=(
                update.output_tokens if update.output_tokens is not None else current.output_tokens
            ),
            cache_read_tokens=(
                update.cache_read_tokens
                if update.cache_read_tokens is not None
                else current.cache_read_tokens
            ),
            cache_write_tokens=(
                update.cache_write_tokens
                if update.cache_write_tokens is not None
                else current.cache_write_tokens
            ),
            report_claimed_at=current.report_claimed_at,
            reported_at=(
                update.reported_at if update.reported_at is not None else current.reported_at
            ),
            cycle_id=update.cycle_id if update.cycle_id is not None else current.cycle_id,
            triggered_by_run_id=(
                update.triggered_by_run_id
                if update.triggered_by_run_id is not None
                else current.triggered_by_run_id
            ),
            trigger_reason=(
                update.trigger_reason
                if update.trigger_reason is not None
                else current.trigger_reason
            ),
            sequence_index=(
                update.sequence_index
                if update.sequence_index is not None
                else current.sequence_index
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
            SET harness = ?,
                role = ?,
                status = ?,
                started_at = ?,
                ended_at = ?,
                supervisor_pid = ?,
                supervisor_started_at = ?,
                supervisor_output_path = ?,
                process_id = ?,
                process_group_id = ?,
                result_summary = ?,
                result_output = ?,
                result_summary_truncated = ?,
                error_text = ?,
                blocker_text = ?,
                worker_session_id = ?,
                transcript_path = ?,
                approval_needed = ?,
                input_tokens = ?,
                output_tokens = ?,
                cache_read_tokens = ?,
                cache_write_tokens = ?,
                report_claimed_at = ?,
                reported_at = ?,
                cycle_id = ?,
                triggered_by_run_id = ?,
                trigger_reason = ?,
                sequence_index = ?
            WHERE run_id = ?
              AND status = ?
            """,
            (
                record.harness,
                record.role,
                record.status,
                record.started_at,
                record.ended_at,
                record.supervisor_pid,
                record.supervisor_started_at,
                str(record.supervisor_output_path) if record.supervisor_output_path else None,
                record.process_id,
                record.process_group_id,
                record.result_summary,
                record.result_output,
                int(record.result_summary_truncated),
                record.error_text,
                record.blocker_text,
                record.worker_session_id,
                str(record.transcript_path) if record.transcript_path else None,
                int(record.approval_needed),
                record.input_tokens,
                record.output_tokens,
                record.cache_read_tokens,
                record.cache_write_tokens,
                record.report_claimed_at,
                record.reported_at,
                record.cycle_id,
                record.triggered_by_run_id,
                record.trigger_reason,
                record.sequence_index,
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
            record.model,
            record.status,
            record.created_at,
            record.started_at,
            record.ended_at,
            record.supervisor_pid,
            record.supervisor_started_at,
            str(record.supervisor_output_path) if record.supervisor_output_path else None,
            record.process_id,
            record.process_group_id,
            record.task_label,
            record.result_summary,
            record.result_output,
            int(record.result_summary_truncated),
            record.error_text,
            record.blocker_text,
            str(record.log_path),
            record.worker_session_id,
            str(record.transcript_path) if record.transcript_path else None,
            int(record.approval_needed),
            record.input_tokens,
            record.output_tokens,
            record.cache_read_tokens,
            record.cache_write_tokens,
            record.report_claimed_at,
            record.reported_at,
            record.cycle_id,
            record.triggered_by_run_id,
            record.trigger_reason,
            record.sequence_index,
        )

    def _row_to_record(self, row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            run_id=str(row["run_id"]),
            orchestrator_session_id=str(row["orchestrator_session_id"]),
            batch_id=_optional_text(row["batch_id"]),
            harness=str(row["harness"]),
            role=str(row["role"]),
            model=_optional_text(row["model"]),
            status=str(row["status"]),
            created_at=str(row["created_at"]),
            started_at=_optional_text(row["started_at"]),
            ended_at=_optional_text(row["ended_at"]),
            supervisor_pid=(
                int(row["supervisor_pid"]) if row["supervisor_pid"] is not None else None
            ),
            supervisor_started_at=_optional_text(row["supervisor_started_at"]),
            supervisor_output_path=(
                Path(str(row["supervisor_output_path"]))
                if row["supervisor_output_path"] is not None
                else None
            ),
            process_id=int(row["process_id"]) if row["process_id"] is not None else None,
            process_group_id=(
                int(row["process_group_id"]) if row["process_group_id"] is not None else None
            ),
            task_label=str(row["task_label"]),
            result_summary=_optional_text(row["result_summary"]),
            result_output=_optional_text(row["result_output"]),
            result_summary_truncated=bool(row["result_summary_truncated"]),
            error_text=_optional_text(row["error_text"]),
            blocker_text=_optional_text(row["blocker_text"]),
            log_path=Path(str(row["log_path"])),
            worker_session_id=_optional_text(row["worker_session_id"]),
            transcript_path=(
                Path(str(row["transcript_path"])) if row["transcript_path"] is not None else None
            ),
            approval_needed=bool(row["approval_needed"]),
            input_tokens=_optional_int(row["input_tokens"]),
            output_tokens=_optional_int(row["output_tokens"]),
            cache_read_tokens=_optional_int(row["cache_read_tokens"]),
            cache_write_tokens=_optional_int(row["cache_write_tokens"]),
            report_claimed_at=_optional_text(row["report_claimed_at"]),
            reported_at=_optional_text(row["reported_at"]),
            cycle_id=_optional_text(row["cycle_id"]),
            triggered_by_run_id=_optional_text(row["triggered_by_run_id"]),
            trigger_reason=_optional_text(row["trigger_reason"]),
            sequence_index=(
                int(row["sequence_index"]) if row["sequence_index"] is not None else None
            ),
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


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _report_claim_stale_before() -> str:
    stale_before = datetime.now(UTC) - timedelta(seconds=_REPORT_CLAIM_LEASE_SECONDS)
    return stale_before.isoformat(timespec="seconds").replace("+00:00", "Z")


def _is_transient_sqlite_error(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).lower()
    return "database is locked" in message or "database is busy" in message


def _validate_main_session_mode(mode: str) -> None:
    if mode not in ALLOWED_MAIN_SESSION_MODES:
        raise StateError(f"invalid main session mode: {mode}")


def _validate_status(status: str) -> None:
    if status not in ALL_STATUSES:
        raise StateError(f"invalid run status: {status}")


def _list_orphan_candidates(
    *,
    cutoff_dt: datetime,
    request_dir: Path | None,
    log_dir: Path | None,
    owned_paths: set[Path],
) -> list[Path]:
    candidates: list[Path] = []
    for base_dir in (request_dir, log_dir):
        if base_dir is None or not base_dir.exists():
            continue
        for path in sorted(base_dir.rglob("*")):
            if not path.is_file():
                continue
            try:
                modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            except FileNotFoundError:
                continue
            if modified_at >= cutoff_dt:
                continue
            if path in owned_paths:
                continue
            candidates.append(path)
    return candidates


def _prune_reference_timestamp(record: RunRecord) -> datetime:
    for raw in (record.ended_at, record.reported_at, record.created_at):
        if raw:
            return _parse_utc_timestamp(raw)
    return _parse_utc_timestamp(record.created_at)


def _path_is_under_roots(path: Path, roots: tuple[Path, ...]) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()
    return any(resolved == root or root in resolved.parents for root in roots)


def _parse_utc_timestamp(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def _validate_transition(current: str, target: str) -> None:
    if current not in ALLOWED_TRANSITIONS or target not in ALLOWED_TRANSITIONS[current]:
        raise StateError(f"invalid status transition: {current} -> {target}")
