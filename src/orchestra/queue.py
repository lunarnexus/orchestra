"""Job queue for Orchestra 2.

Persists jobs in SQLite and schedules them by prerequisite readiness and
concurrency limits. Limits are plain arguments; this module never reads
configuration files. Failed or skipped prerequisites mark dependent jobs
skipped; there is no retry or recovery.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal, Self

Status = Literal["pending", "running", "succeeded", "failed", "skipped"]
_TERMINAL: Final[frozenset[str]] = frozenset({"succeeded", "failed", "skipped"})


@dataclass(frozen=True)
class JobSpec:
    """Arguments for adding one pending job, as a batch-compatible value."""

    run_id: str
    parent_session: str
    role: str
    model: str
    prerequisites: tuple[str, ...] = ()
    soft_timeout: int | None = None
    hard_timeout: int | None = None
    turn_limit: int | None = None


class QueueError(ValueError):
    """Raised on invalid job state transitions or invalid queue arguments."""


@dataclass(frozen=True)
class Job:
    job_id: str
    run_id: str
    sequence: int
    parent_session: str
    role: str
    model: str
    status: Status
    prerequisites: tuple[str, ...]
    created_at: str
    started_at: str | None
    finished_at: str | None
    soft_timeout: int | None
    hard_timeout: int | None
    turn_limit: int | None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    parent_session TEXT NOT NULL,
    role TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN
        ('pending', 'running', 'succeeded', 'failed', 'skipped')),
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    soft_timeout INTEGER,
    hard_timeout INTEGER,
    turn_limit INTEGER
);
CREATE TABLE IF NOT EXISTS job_prerequisites (
    job_id TEXT NOT NULL REFERENCES jobs(job_id),
    prerequisite_id TEXT NOT NULL REFERENCES jobs(job_id),
    PRIMARY KEY (job_id, prerequisite_id)
);
CREATE INDEX IF NOT EXISTS jobs_run_sequence ON jobs (run_id, sequence);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def run_id_of(job_id: str) -> str:
    """Return the run id embedded in a job id (``<run_id>:<sequence>``).

    Job ids are built by :meth:`JobQueue.add_jobs`; dependents that only
    know an upstream job id use this to locate that job's own records.
    """
    run_id, separator, sequence = job_id.rpartition(":")
    if not separator or not run_id or not sequence:
        raise QueueError(f"{job_id!r} is not a job id of the form <run_id>:<sequence>")
    return run_id


class JobQueue:
    """SQLite-backed job queue with dependency and concurrency gating."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        # isolation_level=None disables implicit transactions; every write runs
        # inside an explicit BEGIN IMMEDIATE transaction (see _transaction) so
        # concurrent claimers from other threads/processes serialize on the
        # database write lock instead of racing between count and claim.
        self._conn = sqlite3.connect(
            self._path,
            timeout=10.0,
            isolation_level=None,
            check_same_thread=False,
        )
        # The dispatcher runs worker threads on this instance; every use of
        # the shared connection is serialized by this re-entrant lock.
        self._lock = threading.RLock()
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA busy_timeout = 10000")
        self._conn.executescript(_SCHEMA)
        with self._lock:
            self._migrate_schema()

    def _migrate_schema(self) -> None:
        """Update databases from older schemas to the current one."""
        existing = {
            str(row[1])  # column name
            for row in self._conn.execute("PRAGMA table_info (jobs)").fetchall()
        }
        if "session_id" in existing:
            self._conn.execute(
                "ALTER TABLE jobs RENAME COLUMN session_id TO parent_session"
            )
        for column in ("soft_timeout", "hard_timeout", "turn_limit"):
            if column not in existing:
                self._conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} INTEGER")

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        """Run writes atomically, serializing with other claimers immediately."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def add_job(
        self,
        *,
        run_id: str,
        parent_session: str,
        role: str,
        model: str,
        prerequisites: tuple[str, ...] | list[str] = (),
        soft_timeout: int | None = None,
        hard_timeout: int | None = None,
        turn_limit: int | None = None,
    ) -> Job:
        """Add a pending job. Its sequence number is per-run, 1-based, in add order."""
        return self.add_jobs(
            (
                JobSpec(
                    run_id=run_id,
                    parent_session=parent_session,
                    role=role,
                    model=model,
                    prerequisites=tuple(prerequisites),
                    soft_timeout=soft_timeout,
                    hard_timeout=hard_timeout,
                    turn_limit=turn_limit,
                ),
            )
        )[0]

    def add_jobs(self, specs: Sequence[JobSpec]) -> tuple[Job, ...]:
        """Add multiple pending jobs in ONE atomic transaction.

        Every spec must pass validation before any job is inserted; a
        failure rolls the whole batch back. Prerequisites may reference
        jobs inserted earlier in the same batch. Sequence numbers are
        per-run, 1-based, in add order.
        """
        for spec in specs:
            if (
                not spec.run_id
                or not spec.parent_session
                or not spec.role
                or not spec.model
            ):
                raise QueueError("run_id, parent_session, role, and model are required")
        with self._transaction():
            jobs = tuple(self._insert_locked(spec) for spec in specs)
        return jobs

    def _insert_locked(self, spec: JobSpec) -> Job:
        """Insert one pending job; must run inside a BEGIN IMMEDIATE transaction."""
        for prerequisite_id in spec.prerequisites:
            self.get_job(prerequisite_id)  # raises QueueError if unknown
        sequence = self._next_sequence(spec.run_id)
        job_id = f"{spec.run_id}:{sequence}"
        now = _now()
        self._conn.execute(
            "INSERT INTO jobs (job_id, run_id, sequence, parent_session, role,"
            " model, status, created_at, soft_timeout, hard_timeout,"
            " turn_limit) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)",
            (
                job_id,
                spec.run_id,
                sequence,
                spec.parent_session,
                spec.role,
                spec.model,
                now,
                spec.soft_timeout,
                spec.hard_timeout,
                spec.turn_limit,
            ),
        )
        for prerequisite_id in spec.prerequisites:
            self._conn.execute(
                "INSERT INTO job_prerequisites (job_id, prerequisite_id)"
                " VALUES (?, ?)",
                (job_id, prerequisite_id),
            )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> Job:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise QueueError(f"unknown job {job_id!r}")
            return self._job_from_row(row)

    def list_jobs(self, run_id: str | None = None) -> tuple[Job, ...]:
        with self._lock:
            if run_id is None:
                rows = self._conn.execute(
                    "SELECT * FROM jobs ORDER BY created_at, job_id"
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM jobs WHERE run_id = ? ORDER BY sequence",
                    (run_id,),
                ).fetchall()
            return tuple(self._job_from_row(row) for row in rows)

    def claim_next(
        self,
        *,
        global_limit: int,
        per_session_limit: int,
        model_limits: dict[str, int] | None = None,
        run_id: str | None = None,
    ) -> Job | None:
        """Claim the earliest ready pending job, respecting all limits.

        A job is ready when every prerequisite has succeeded. When ``run_id``
        is given, only that run's jobs are eligible. Returns None when no
        pending job is both ready and within the limits.
        """
        if global_limit < 1 or per_session_limit < 1:
            raise QueueError("limits must be positive integers")
        limits = model_limits or {}
        for model, required_limit in limits.items():
            if required_limit < 1:
                raise QueueError(
                    f"model limit for {model!r} must be a positive integer"
                )
        with self._transaction():
            claimed = self._claim_next_locked(
                global_limit, per_session_limit, limits, run_id
            )
        return claimed

    def _claim_next_locked(
        self,
        global_limit: int,
        per_session_limit: int,
        limits: dict[str, int],
        run_id: str | None,
    ) -> Job | None:
        """Claim body; must run inside a BEGIN IMMEDIATE transaction."""
        running_global = self._running_count()
        for job in self._ready_pending_jobs(run_id):
            if running_global >= global_limit:
                return None
            if self._running_count(parent_session=job.parent_session) >= per_session_limit:
                continue
            model_limit = limits.get(job.model)
            if model_limit is not None and self._running_count(
                model=job.model
            ) >= model_limit:
                continue
            self._conn.execute(
                "UPDATE jobs SET status = 'running', started_at = ?"
                " WHERE job_id = ?",
                (_now(), job.job_id),
            )
            return self.get_job(job.job_id)
        return None

    def complete_job(
        self, job_id: str, outcome: Literal["succeeded", "failed"]
    ) -> Job:
        """Transition a running job to succeeded or failed.

        Failure marks every transitively dependent pending job skipped.
        """
        with self._transaction():
            job = self.get_job(job_id)
            if job.status != "running":
                raise QueueError(
                    f"job {job_id!r} has status {job.status!r}; only a running job"
                    " can be completed"
                )
            self._conn.execute(
                "UPDATE jobs SET status = ?, finished_at = ? WHERE job_id = ?",
                (outcome, _now(), job_id),
            )
            if outcome == "failed":
                self._skip_dependents(job_id)
        return self.get_job(job_id)

    def _skip_dependents(self, blocked_job_id: str) -> None:
        rows = self._conn.execute(
            "SELECT job_id FROM job_prerequisites WHERE prerequisite_id = ?",
            (blocked_job_id,),
        ).fetchall()
        for row in rows:
            dependent_id = str(row["job_id"])
            dependent = self.get_job(dependent_id)
            if dependent.status in _TERMINAL:
                continue
            self._conn.execute(
                "UPDATE jobs SET status = 'skipped', finished_at = ?"
                " WHERE job_id = ?",
                (_now(), dependent_id),
            )
            self._skip_dependents(dependent_id)

    def _running_count(
        self, *, parent_session: str | None = None, model: str | None = None
    ) -> int:
        query = "SELECT COUNT(*) FROM jobs WHERE status = 'running'"
        params: list[str] = []
        if parent_session is not None:
            query += " AND parent_session = ?"
            params.append(parent_session)
        if model is not None:
            query += " AND model = ?"
            params.append(model)
        return int(self._conn.execute(query, params).fetchone()[0])

    def _ready_pending_jobs(
        self, run_id: str | None = None
    ) -> tuple[Job, ...]:
        if run_id is None:
            pending = self._conn.execute(
                "SELECT * FROM jobs WHERE status = 'pending' ORDER BY sequence"
            ).fetchall()
        else:
            pending = self._conn.execute(
                "SELECT * FROM jobs WHERE status = 'pending' AND run_id = ?"
                " ORDER BY sequence",
                (run_id,),
            ).fetchall()
        return tuple(
            self._job_from_row(row)
            for row in pending
            if not self._has_unsatisfied_prerequisites(str(row["job_id"]))
        )

    def _has_unsatisfied_prerequisites(self, job_id: str) -> bool:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM job_prerequisites p"
            " JOIN jobs j ON j.job_id = p.prerequisite_id"
            " WHERE p.job_id = ? AND j.status != 'succeeded'",
            (job_id,),
        ).fetchone()
        return int(row[0]) > 0

    def _next_sequence(self, run_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM jobs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return int(row[0])

    def _job_from_row(self, row: sqlite3.Row) -> Job:
        prereq_rows = self._conn.execute(
            "SELECT prerequisite_id FROM job_prerequisites WHERE job_id = ?"
            " ORDER BY prerequisite_id",
            (row["job_id"],),
        ).fetchall()
        return Job(
            job_id=str(row["job_id"]),
            run_id=str(row["run_id"]),
            sequence=int(row["sequence"]),
            parent_session=str(row["parent_session"]),
            role=str(row["role"]),
            model=str(row["model"]),
            status=str(row["status"]),  # type: ignore[arg-type]
            prerequisites=tuple(str(r["prerequisite_id"]) for r in prereq_rows),
            created_at=str(row["created_at"]),
            started_at=None if row["started_at"] is None else str(row["started_at"]),
            finished_at=(
                None if row["finished_at"] is None else str(row["finished_at"])
            ),
            soft_timeout=(
                None if row["soft_timeout"] is None else int(row["soft_timeout"])
            ),
            hard_timeout=(
                None if row["hard_timeout"] is None else int(row["hard_timeout"])
            ),
            turn_limit=(
                None if row["turn_limit"] is None else int(row["turn_limit"])
            ),
        )
