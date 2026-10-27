"""SQLite persistence for the durable job queue.

Storage is namespaced to ``orchestra_job_*`` tables and owns its own version
record. It never touches Orchestra's run/session tables or the database-global
``PRAGMA foreign_keys`` behaviour of other stores.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import cast

from orchestra.jobs.models import (
    DEPENDENCY_CONDITIONS,
    Dependency,
    Job,
    JobOutcome,
    QueueError,
    deserialize_json_payload,
)

SCHEMA_VERSION = 1

META_TABLE = "orchestra_job_meta"
JOBS_TABLE = "orchestra_jobs"
DEPENDENCIES_TABLE = "orchestra_job_dependencies"
LIMITS_TABLE = "orchestra_job_limits"

_SCHEMA_VERSION_KEY = "schema_version"
_BUSY_TIMEOUT_MILLISECONDS = 1000

_OPEN_STATES_SQL = "'queued','claimed'"

_DDL: tuple[str, ...] = (
    f"""
    CREATE TABLE IF NOT EXISTS {META_TABLE} (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS {LIMITS_TABLE} (
        revision INTEGER PRIMARY KEY CHECK (revision >= 1),
        policy_json TEXT NOT NULL
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS {JOBS_TABLE} (
        job_id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN
            ('queued','claimed','done','failed','incomplete','cancelled','skipped')),
        seq INTEGER NOT NULL UNIQUE CHECK (seq >= 1),
        created_at TEXT NOT NULL,
        claimed_at TEXT,
        finished_at TEXT,
        reason TEXT,
        parameters_json TEXT NOT NULL,
        resource_key TEXT,
        claim_token TEXT,
        cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
        outcome_json TEXT,
        CHECK (state <> 'queued' OR claim_token IS NULL),
        CHECK ((state IN ({_OPEN_STATES_SQL})) = (finished_at IS NULL)),
        CHECK ((state IN ({_OPEN_STATES_SQL})) = (outcome_json IS NULL))
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS {DEPENDENCIES_TABLE} (
        job_id TEXT NOT NULL
            REFERENCES {JOBS_TABLE}(job_id) ON DELETE CASCADE,
        depends_on_job_id TEXT NOT NULL
            REFERENCES {JOBS_TABLE}(job_id) ON DELETE CASCADE,
        condition TEXT NOT NULL CHECK (condition IN ('done','terminal','pass')),
        PRIMARY KEY (job_id, depends_on_job_id)
    )
    """,
    f"""
    CREATE INDEX IF NOT EXISTS idx_orchestra_jobs_owner_state
        ON {JOBS_TABLE}(owner_id, state, seq)
    """,
    f"""
    CREATE INDEX IF NOT EXISTS idx_orchestra_job_dependencies_job
        ON {DEPENDENCIES_TABLE}(job_id)
    """,
)


class QueueSchemaError(QueueError):
    """Raised when stored queue schema or policy state is unusable."""


class JobStore:
    """Connection handling and row mapping for the job queue.

    Constructed with a path, each operation opens its own connection and owns a
    ``BEGIN IMMEDIATE`` transaction. Constructed with an open connection, the
    store uses it without beginning, committing, or rolling it back so callers
    can compose queue and execution writes atomically.
    """

    def __init__(self, source: str | Path | sqlite3.Connection) -> None:
        if isinstance(source, sqlite3.Connection) or hasattr(source, "execute"):
            # Accept sqlite3.Connection and duck-typed connection wrappers
            # (e.g. test harnesses that wrap connections for gap checking).
            conn = cast(sqlite3.Connection, source)
            self.database_path: Path | None = None
            self._connection: sqlite3.Connection | None = conn
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
        else:
            self.database_path = Path(source)
            self._connection = None
            self.database_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def is_bound(self) -> bool:
        return self._connection is not None

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        if self._connection is not None:
            yield self._connection
            return
        assert self.database_path is not None
        handle = sqlite3.connect(
            self.database_path,
            timeout=_BUSY_TIMEOUT_MILLISECONDS / 1000,
            isolation_level=None,
        )
        try:
            handle.row_factory = sqlite3.Row
            handle.execute("PRAGMA foreign_keys = ON")
            handle.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MILLISECONDS}")
            handle.execute("BEGIN IMMEDIATE")
            yield handle
            handle.execute("COMMIT")
        except BaseException:
            if handle.in_transaction:
                handle.execute("ROLLBACK")
            raise
        finally:
            handle.close()

    @contextmanager
    def read_connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection for reads, without taking a write lock.

        Read-only commands must stay usable while another process holds a write
        transaction, so nothing on a read path may begin ``BEGIN IMMEDIATE``.
        """
        if self._connection is not None:
            yield self._connection
            return
        assert self.database_path is not None
        handle = sqlite3.connect(
            self.database_path,
            timeout=_BUSY_TIMEOUT_MILLISECONDS / 1000,
            isolation_level=None,
        )
        try:
            handle.row_factory = sqlite3.Row
            handle.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MILLISECONDS}")
            yield handle
        finally:
            handle.close()

    def create_schema(self) -> None:
        with self.read_connection() as connection:
            if self._table_exists(connection, LIMITS_TABLE):
                self._check_schema_version(connection)
                return
        with self.connection() as connection:
            for statement in _DDL:
                connection.execute(statement)
            self._check_schema_version(connection)
            if self._meta_value(connection, _SCHEMA_VERSION_KEY) is None:
                connection.execute(
                    f"INSERT INTO {META_TABLE} (key, value) VALUES (?, ?)",
                    (_SCHEMA_VERSION_KEY, str(SCHEMA_VERSION)),
                )

    def schema_exists(self) -> bool:
        if self._connection is not None:
            return self._table_exists(self._connection, LIMITS_TABLE)
        assert self.database_path is not None
        if not self.database_path.exists():
            return False
        with sqlite3.connect(
            f"file:{self.database_path}?mode=ro",
            uri=True,
            timeout=_BUSY_TIMEOUT_MILLISECONDS / 1000,
        ) as connection:
            return self._table_exists(connection, LIMITS_TABLE)

    def validate_schema(self) -> None:
        with self.read_connection() as connection:
            if not self._table_exists(connection, LIMITS_TABLE):
                raise QueueSchemaError("job queue schema is not initialized")
            self._check_schema_version(connection)

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _meta_value(connection: sqlite3.Connection, key: str) -> str | None:
        if not JobStore._table_exists(connection, META_TABLE):
            return None
        row = connection.execute(
            f"SELECT value FROM {META_TABLE} WHERE key = ?",
            (key,),
        ).fetchone()
        return None if row is None else str(row["value"])

    @staticmethod
    def _check_schema_version(connection: sqlite3.Connection) -> None:
        row = connection.execute(
            f"SELECT value FROM {META_TABLE} WHERE key = ?",
            (_SCHEMA_VERSION_KEY,),
        ).fetchone()
        if row is None:
            return
        stored = int(row["value"])
        if stored != SCHEMA_VERSION:
            raise QueueSchemaError(
                f"unsupported job queue schema version {stored}; expected {SCHEMA_VERSION}"
            )

    def read_policy(self) -> tuple[int, str]:
        with self.read_connection() as connection:
            return self.read_policy_on(connection)

    def current_revision(self) -> int | None:
        with self.read_connection() as connection:
            return self.current_revision_on(connection)

    @staticmethod
    def current_revision_on(connection: sqlite3.Connection) -> int | None:
        row = connection.execute(
            f"SELECT MAX(revision) AS revision FROM {LIMITS_TABLE}"
        ).fetchone()
        if row is None or row["revision"] is None:
            return None
        return int(row["revision"])

    @staticmethod
    def read_policy_on(connection: sqlite3.Connection) -> tuple[int, str]:
        row = connection.execute(
            f"SELECT revision, policy_json FROM {LIMITS_TABLE} ORDER BY revision DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise QueueSchemaError("job queue limit policy is missing")
        return int(row["revision"]), str(row["policy_json"])

    @staticmethod
    def append_policy(connection: sqlite3.Connection, revision: int, policy_json: str) -> None:
        connection.execute(
            f"INSERT INTO {LIMITS_TABLE} (revision, policy_json) VALUES (?, ?)",
            (revision, policy_json),
        )

    def next_seq(self, connection: sqlite3.Connection) -> int:
        row = connection.execute(
            f"SELECT COALESCE(MAX(seq), 0) AS seq FROM {JOBS_TABLE}"
        ).fetchone()
        return int(row["seq"]) + 1

    def insert_job_row(self, connection: sqlite3.Connection, job: Job) -> None:
        connection.execute(
            f"""
            INSERT INTO {JOBS_TABLE} (
                job_id, owner_id, state, seq, created_at, claimed_at, finished_at,
                reason, parameters_json, resource_key, claim_token, cancel_requested,
                outcome_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.job_id,
                job.owner_id,
                job.state,
                job.seq,
                job.created_at,
                job.claimed_at,
                job.finished_at,
                job.reason,
                json.dumps(dict(job.parameters), ensure_ascii=False, sort_keys=True),
                job.resource_key,
                job.claim_token,
                1 if job.cancel_requested else 0,
                job.outcome.outcome_json if job.outcome is not None else None,
            ),
        )

    def insert_dependencies(
        self,
        connection: sqlite3.Connection,
        job: Job,
    ) -> None:
        for dependency in job.dependencies:
            connection.execute(
                f"""
                INSERT INTO {DEPENDENCIES_TABLE} (job_id, depends_on_job_id, condition)
                VALUES (?, ?, ?)
                """,
                (job.job_id, dependency.job_id, dependency.condition),
            )

    def dependencies_for(
        self,
        connection: sqlite3.Connection,
        job_ids: Sequence[str],
    ) -> dict[str, tuple[Dependency, ...]]:
        if not job_ids:
            return {}
        grouped: dict[str, list[Dependency]] = {job_id: [] for job_id in job_ids}
        placeholders = ", ".join("?" for _ in job_ids)
        rows = connection.execute(
            f"""
            SELECT job_id, depends_on_job_id, condition
            FROM {DEPENDENCIES_TABLE}
            WHERE job_id IN ({placeholders})
            ORDER BY job_id, depends_on_job_id
            """,
            tuple(job_ids),
        ).fetchall()
        for row in rows:
            condition = str(row["condition"])
            if condition not in DEPENDENCY_CONDITIONS:
                raise QueueSchemaError(f"stored dependency condition is unsupported: {condition}")
            grouped.setdefault(str(row["job_id"]), []).append(
                Dependency(job_id=str(row["depends_on_job_id"]), condition=condition)
            )
        return {job_id: tuple(items) for job_id, items in grouped.items()}

    def load_job(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        dependencies: Sequence[Dependency] = (),
    ) -> Job:
        outcome_text = row["outcome_json"]
        return Job(
            job_id=str(row["job_id"]),
            owner_id=str(row["owner_id"]),
            state=str(row["state"]),
            seq=int(row["seq"]),
            created_at=str(row["created_at"]),
            parameters=deserialize_json_payload(row["parameters_json"]),
            dependencies=tuple(dependencies),
            resource_key=None if row["resource_key"] is None else str(row["resource_key"]),
            reason=None if row["reason"] is None else str(row["reason"]),
            claim_token=None if row["claim_token"] is None else str(row["claim_token"]),
            claimed_at=None if row["claimed_at"] is None else str(row["claimed_at"]),
            finished_at=None if row["finished_at"] is None else str(row["finished_at"]),
            cancel_requested=bool(row["cancel_requested"]),
            outcome=_outcome_from_json(outcome_text),
        )

    def load_by_ids(
        self,
        connection: sqlite3.Connection,
        job_ids: Sequence[str],
    ) -> dict[str, Job]:
        if not job_ids:
            return {}
        placeholders = ", ".join("?" for _ in job_ids)
        rows = connection.execute(
            f"SELECT * FROM {JOBS_TABLE} WHERE job_id IN ({placeholders})",
            tuple(job_ids),
        ).fetchall()
        found = {str(row["job_id"]): row for row in rows}
        missing = sorted(job_id for job_id in job_ids if job_id not in found)
        if missing:
            raise QueueSchemaError(f"referenced jobs are missing: {', '.join(missing)}")
        dependencies = self.dependencies_for(connection, list(found))
        return {
            job_id: self.load_job(
                connection,
                found[job_id],
                dependencies=dependencies.get(job_id, ()),
            )
            for job_id in found
        }


def _outcome_from_json(text: str | None) -> JobOutcome | None:
    if not text:
        return None
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise QueueSchemaError("stored job outcome is not a mapping")
    artifacts = payload.get("artifacts") or {}
    if not isinstance(artifacts, dict):
        raise QueueSchemaError("stored job outcome artifacts are not a mapping")
    return JobOutcome(
        status=str(payload["status"]),
        verdict=None if payload.get("verdict") is None else str(payload["verdict"]),
        summary=None if payload.get("summary") is None else str(payload["summary"]),
        error_text=None if payload.get("error_text") is None else str(payload["error_text"]),
        blocker_text=None if payload.get("blocker_text") is None else str(payload["blocker_text"]),
        artifacts={str(key): str(value) for key, value in artifacts.items()},
    )


__all__ = [
    "DEPENDENCIES_TABLE",
    "JOBS_TABLE",
    "LIMITS_TABLE",
    "META_TABLE",
    "SCHEMA_VERSION",
    "JobStore",
    "QueueSchemaError",
]
