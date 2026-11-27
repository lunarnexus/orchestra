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

# The single queue-owned terminal classification. Every caller reuses this
# constant (or ``Job.is_terminal``) instead of repeating terminal sets, so the
# queue is the one authority for what counts as finished.
TERMINAL_STATUSES: Final[frozenset[Status]] = frozenset(
    {"succeeded", "failed", "skipped"}
)
_TERMINAL: Final[frozenset[str]] = TERMINAL_STATUSES


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
    dispatcher_token: str | None = None
    child_pgid: int | None = None
    child_start: float | None = None

    @property
    def is_terminal(self) -> bool:
        """Whether this job has reached the queue-owned terminal classification."""
        return self.status in TERMINAL_STATUSES


@dataclass(frozen=True)
class SessionSnapshot:
    """One immutable, read-only view of an attached session's live state.

    ``jobs`` are the durable rows for the owning session; the counts, ``active``
    and ``ready`` are derived from those rows plus the queue-owned admission and
    report membership. It is a pure read: producing a snapshot never claims,
    completes, reconciles, or acknowledges a job, and never opens a session or
    resets a baseline. ``ready`` is true only when there are no open admissions,
    no pending/running session job, and a non-empty eligible report selection.

    ``global_running``/``global_pending`` are the cross-session workload tallies
    status rendering needs; they are read from the same held lock as ``jobs``
    so the owned and global views come from one consistent read (every write
    serializes on the same lock). They are display counts, not schema.
    """

    parent_session: str
    jobs: tuple[Job, ...]
    running: int
    pending: int
    terminal: int
    global_running: int
    global_pending: int
    open_admissions: tuple[str, ...]
    baseline_run_ids: tuple[str, ...]
    reported_run_ids: tuple[str, ...]
    active: bool
    ready: bool
    ready_run_ids: tuple[str, ...]

    @property
    def counts(self) -> dict[str, int]:
        """Derived per-status tallies over the session's own job rows."""
        return {"running": self.running, "pending": self.pending, "terminal": self.terminal}


@dataclass
class _SessionState:
    """Queue-owned runtime membership for one attached core session.

    Runtime state only (no schema/columns, no job-status copies): the terminal
    baseline captured at open, in-flight admitted request ids, and reported run
    ids. Guarded by the queue instance lock; this is the owning core session
    process's truth, while durable job rows stay the cross-process source.
    """

    baseline_run_ids: frozenset[str]
    admissions: set[str]
    reported_run_ids: set[str]


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
    turn_limit INTEGER,
    dispatcher_token TEXT,
    child_pgid INTEGER,
    child_start REAL
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
        # A fresh dispatch reaches the queue before any state storage exists, so
        # create the database's parent directory here instead of requiring a
        # prior bootstrap step; sqlite will not create missing parent dirs.
        self._path.parent.mkdir(parents=True, exist_ok=True)
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
        # Queue-owned runtime session membership (no schema, no status copies).
        self._sessions: dict[str, _SessionState] = {}
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
        # Execution-ownership columns (Slice 3): all nullable, additive only.
        if "dispatcher_token" not in existing:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN dispatcher_token TEXT")
        if "child_pgid" not in existing:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN child_pgid INTEGER")
        if "child_start" not in existing:
            self._conn.execute("ALTER TABLE jobs ADD COLUMN child_start REAL")

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
        # Serialize the close with every other use of the shared connection:
        # all reads/claims already take ``self._lock``, so a caller that joins
        # its session threads before closing the queue can never free the
        # underlying SQLite handle while another of its threads is mid-query
        # (which would crash inside ``_sqlite3``). A use that begins *after*
        # this returns raises a clean ``sqlite3.ProgrammingError`` rather than
        # a segfault, because the Python-level connection is now closed.
        with self._lock:
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
        dispatcher_token: str | None = None,
    ) -> Job | None:
        """Claim the earliest ready pending job, respecting all limits.

        A job is ready when every prerequisite has succeeded. When ``run_id``
        is given, only that run's jobs are eligible. Returns None when no
        pending job is both ready and within the limits. ``dispatcher_token``
        attributes the claimed job to the claiming dispatcher so abandoned
        work can later be reconciled.
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
                global_limit, per_session_limit, limits, run_id, dispatcher_token
            )
        return claimed

    def _claim_next_locked(
        self,
        global_limit: int,
        per_session_limit: int,
        limits: dict[str, int],
        run_id: str | None,
        dispatcher_token: str | None,
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
                "UPDATE jobs SET status = 'running', started_at = ?,"
                " dispatcher_token = ? WHERE job_id = ?",
                (_now(), dispatcher_token, job.job_id),
            )
            return self.get_job(job.job_id)
        return None

    def register_execution(
        self, job_id: str, *, pgid: int, child_start: float | None
    ) -> Job:
        """Record the launched execution group identity for a running job.

        Called by the harness launch callback immediately after the child is
        spawned, before its first prompt. ``child_start`` is the process
        creation identity used to reject a recycled PID at reconciliation;
        None means the identity could not be read and execution stays
        unverified.
        """
        with self._transaction():
            job = self.get_job(job_id)
            if job.status != "running":
                raise QueueError(
                    f"job {job_id!r} has status {job.status!r}; only a running"
                    " job can register execution"
                )
            self._conn.execute(
                "UPDATE jobs SET child_pgid = ?, child_start = ? WHERE job_id = ?",
                (pgid, child_start, job_id),
            )
        return self.get_job(job_id)

    def running_jobs(
        self, *, dispatcher_token: str | None = None
    ) -> tuple[Job, ...]:
        """Running jobs, optionally only those owned by one dispatcher token."""
        with self._lock:
            if dispatcher_token is None:
                rows = self._conn.execute(
                    "SELECT * FROM jobs WHERE status = 'running'"
                    " ORDER BY run_id, sequence"
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM jobs WHERE status = 'running'"
                    " AND dispatcher_token = ? ORDER BY run_id, sequence",
                    (dispatcher_token,),
                ).fetchall()
            return tuple(self._job_from_row(row) for row in rows)

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
            # Terminal transitions clear execution-ownership bookkeeping so a
            # recycled PID is never mistaken for still-owned execution.
            self._conn.execute(
                "UPDATE jobs SET status = ?, finished_at = ?,"
                " dispatcher_token = NULL, child_pgid = NULL, child_start = NULL"
                " WHERE job_id = ?",
                (outcome, _now(), job_id),
            )
            if outcome == "failed":
                self._skip_dependents(job_id)
        return self.get_job(job_id)

    def fail_unstarted(self, run_id: str, parent_session: str) -> tuple[Job, ...]:
        """Fail all pending jobs for an owned run (infrastructure failure).

        Authoritative transition used when execution cannot launch: validates
        that every affected job is still pending (not already claimed/running)
        and belongs to the owning session, then transitions them to failed and
        cascades skips to transitive dependents. Raises QueueError when the run
        has no jobs, belongs to a different session, or contains a non-pending
        job (so a caller never silently overwrites running or terminal state).
        """
        with self._transaction():
            jobs = self._owned_jobs_locked(parent_session, run_id=run_id)
            if not jobs:
                raise QueueError(
                    f"run {run_id!r} is not owned by session {parent_session!r}"
                )
            for job in jobs:
                if job.status != "pending":
                    raise QueueError(
                        f"job {job.job_id!r} has status {job.status!r};"
                        " fail_unstarted requires all jobs to be pending"
                    )
            now = _now()
            for job in jobs:
                self._conn.execute(
                    "UPDATE jobs SET status = 'failed', finished_at = ?"
                    " WHERE job_id = ?",
                    (now, job.job_id),
                )
                self._skip_dependents(job.job_id)
        return tuple(
            self.get_job(job.job_id) for job in jobs
        )

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

    # --- runtime session membership (Slice 1 queue contract) ---------------

    def open_session(self, parent_session: str) -> None:
        """Idempotently bind a core session and baseline its terminal history.

        The first open captures the run ids that are already fully terminal as
        an attachment baseline so historical reports are never auto-replayed.
        Re-opening an already-attached session is a no-op: it must never erase
        recorded report receipts, admitted requests, or reset the baseline.
        """
        if not parent_session:
            raise QueueError("parent_session is required to open a session")
        with self._lock:
            if parent_session in self._sessions:
                return  # idempotent: keep baseline, admissions, and receipts
            by_run: dict[str, list[bool]] = {}
            for job in self._owned_jobs_locked(parent_session):
                by_run.setdefault(job.run_id, []).append(job.is_terminal)
            baseline = frozenset(
                run_id
                for run_id, terminal_flags in by_run.items()
                if terminal_flags and all(terminal_flags)
            )
            self._sessions[parent_session] = _SessionState(
                baseline_run_ids=baseline, admissions=set(), reported_run_ids=set()
            )

    def begin_submission(self, parent_session: str, request_id: str) -> None:
        """Admit an in-flight submission before any job row exists.

        Tracks the request across the process boundary that SQLite cannot yet
        see, so readiness stays false while a submission is still being
        accepted. Requires an opened session; a duplicate request is rejected.
        """
        state = self._require_state(parent_session)
        with self._lock:
            if request_id in state.admissions:
                raise QueueError(
                    f"request {request_id!r} is already an open submission"
                )
            state.admissions.add(request_id)

    def finish_submission(self, parent_session: str, request_id: str) -> None:
        """Release a prior admission after ack or definite close.

        Idempotent: acknowledgement and process-closure can both call this, and
        a request that never admitted is ignored. Requires an opened session.
        """
        state = self._require_state(parent_session)
        with self._lock:
            state.admissions.discard(request_id)

    def acknowledge_report(self, parent_session: str, run_ids: Sequence[str]) -> None:
        """Record that selected reports were submitted to their native session.

        Callers invoke this only after a real native delivery success. For each
        selected run it validates ownership and per-run terminality (not that
        the whole session is still idle), then records reported membership.
        Repeated acknowledgement is harmless; foreign or non-terminal runs are
        rejected. An empty selection acknowledges nothing.
        """
        state = self._require_state(parent_session)
        with self._lock:
            for run_id in run_ids:
                jobs = self._owned_jobs_locked(parent_session, run_id=run_id)
                if not jobs:
                    raise QueueError(
                        f"run {run_id!r} is not owned by session {parent_session!r}"
                    )
                if not all(job.is_terminal for job in jobs):
                    raise QueueError(
                        f"run {run_id!r} is not terminal; cannot acknowledge its report"
                    )
                state.reported_run_ids.add(run_id)

    def snapshot(self, parent_session: str) -> SessionSnapshot:
        """Return one frozen, read-only session view (never opens a session).

        Reads the session's committed job rows and combines them with queue-
        owned admission/report membership. For an unopened session there is no
        baseline/report/admission state, so eligible runs are simply the
        session's all-terminal runs; this still supports status/Results without
        any lifecycle side effect.
        """
        with self._lock:
            jobs = self._owned_jobs_locked(parent_session)
            # Same held lock as the owned read: every write serializes on this
            # lock, so the global tallies are consistent with the rows above.
            global_running = self._running_count()
            global_pending = int(
                self._conn.execute(
                    "SELECT COUNT(*) FROM jobs WHERE status = 'pending'"
                ).fetchone()[0]
            )
            state = self._sessions.get(parent_session)
            baseline = state.baseline_run_ids if state else frozenset()
            reported = frozenset(state.reported_run_ids) if state else frozenset()
            admissions = tuple(sorted(state.admissions)) if state else ()

        running = sum(1 for job in jobs if job.status == "running")
        pending = sum(1 for job in jobs if job.status == "pending")
        terminal = sum(1 for job in jobs if job.is_terminal)

        by_run: dict[str, list[Job]] = {}
        for job in jobs:
            by_run.setdefault(job.run_id, []).append(job)
        ready_run_ids = tuple(
            sorted(
                run_id
                for run_id, run_jobs in by_run.items()
                if all(job.is_terminal for job in run_jobs)
                and run_id not in baseline
                and run_id not in reported
            )
        )
        active = running + pending > 0 or bool(admissions)
        ready = not active and bool(ready_run_ids)
        return SessionSnapshot(
            parent_session=parent_session,
            jobs=jobs,
            running=running,
            pending=pending,
            terminal=terminal,
            global_running=global_running,
            global_pending=global_pending,
            open_admissions=admissions,
            baseline_run_ids=tuple(sorted(baseline)),
            reported_run_ids=tuple(sorted(reported)),
            active=active,
            ready=ready,
            ready_run_ids=ready_run_ids,
        )

    def owned_run_jobs(self, parent_session: str, run_id: str) -> tuple[Job, ...]:
        """Return one session's jobs for one run from a single durable read.

        Cancellation, inspection, and Results that know a run id and their own
        session use this to validate, in one read, that the run exists and
        belongs to them, then act on the returned rows. A run with no job rows
        at all is unknown; a run whose jobs belong to another session is
        foreign; both raise :class:`QueueError` so a caller never leaks or acts
        on another session's work. This is a pure read: it claims, completes,
        reconciles, or acknowledges nothing.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE run_id = ? ORDER BY sequence", (run_id,)
            ).fetchall()
            jobs = tuple(self._job_from_row(row) for row in rows)
        owned = tuple(job for job in jobs if job.parent_session == parent_session)
        if not jobs:
            raise QueueError(f"unknown run {run_id!r}")
        if not owned:
            raise QueueError(
                f"run {run_id!r} is not owned by session {parent_session!r}"
            )
        return owned

    def _require_state(self, parent_session: str) -> _SessionState:
        with self._lock:
            state = self._sessions.get(parent_session)
        if state is None:
            raise QueueError(f"session {parent_session!r} is not open")
        return state

    def _owned_jobs_locked(
        self, parent_session: str, run_id: str | None = None
    ) -> tuple[Job, ...]:
        """Owned job rows for a session (optionally one run); lock must be held."""
        if run_id is None:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE parent_session = ?"
                " ORDER BY run_id, sequence",
                (parent_session,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE parent_session = ? AND run_id = ?"
                " ORDER BY sequence",
                (parent_session, run_id),
            ).fetchall()
        return tuple(self._job_from_row(row) for row in rows)

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
            dispatcher_token=(
                None if row["dispatcher_token"] is None else str(row["dispatcher_token"])
            ),
            child_pgid=(None if row["child_pgid"] is None else int(row["child_pgid"])),
            child_start=(None if row["child_start"] is None else float(row["child_start"])),
        )
