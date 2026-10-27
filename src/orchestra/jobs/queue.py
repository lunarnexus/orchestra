"""Durable job queue: dependency eligibility, capacity claims, and outcomes.

The queue stores and decides. It never executes work, imports execution code,
or interprets subagent prose.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from orchestra.jobs.models import (
    DEPENDENCY_DONE,
    DEPENDENCY_TERMINAL,
    JOB_STATE_CANCELLED,
    JOB_STATE_CLAIMED,
    JOB_STATE_DONE,
    JOB_STATE_QUEUED,
    JOB_STATE_SKIPPED,
    OPEN_JOB_STATES,
    SKIPPED_DEPENDENCY_REASON,
    TERMINAL_JOB_STATES,
    CapacityUnavailableError,
    Claim,
    ClaimRejectedError,
    Dependency,
    DependencyUnresolvedError,
    Job,
    JobConflictError,
    JobForbiddenError,
    JobNotFoundError,
    JobOutcome,
    JobSpec,
    JobSpecError,
    Limits,
    PolicyError,
    QueueError,
    deserialize_json_payload,
    limits_from_json,
)
from orchestra.jobs.sqlite import JobStore, QueueSchemaError


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


_READY = "ready"
_WAITING = "waiting"
_UNSATISFIED = "unsatisfied"


def _new_token() -> str:
    return uuid.uuid4().hex


class JobQueue:
    """Queue facade owning jobs, dependencies, limits, claims, and outcomes.

    Constructed with a path, each call owns its transaction. Constructed with
    an open connection, calls compose inside that connection without beginning
    or ending any transaction; use :meth:`bind` to obtain that form.
    """

    def __init__(self, source: str | Path | sqlite3.Connection) -> None:
        self._store = JobStore(source)

    @property
    def database_path(self) -> Path | None:
        return self._store.database_path

    @property
    def is_bound(self) -> bool:
        return self._store.is_bound

    def bind(self, connection: sqlite3.Connection) -> JobQueue:
        """Return a queue writing through ``connection`` without owning it."""
        if self._store.is_bound:
            raise QueueError("this queue is already bound to a connection")
        return JobQueue(connection)

    def initialize(self, limits: Limits) -> Limits:
        """Create schema and persist ``limits``, or verify the stored policy.

        An already-initialized queue is verified on a read connection, so
        read-only commands never need a write lock.
        """
        self._store.create_schema()
        stored = self._stored_policy(allow_missing=True)
        if stored is not None:
            return _checked_policy(stored, limits)

        with self._store.connection() as connection:
            concurrent = self._store.current_revision_on(connection)
            if concurrent is not None:
                concurrent_policy = limits_from_json(
                    self._store.read_policy_on(connection)[1], revision=concurrent
                )
                return _checked_policy(concurrent_policy, limits)
            JobStore.append_policy(connection, 1, limits.policy_json)
            return limits.with_revision(1)

    def _stored_policy(self, *, allow_missing: bool = False) -> Limits | None:
        with self._store.read_connection() as connection:
            revision = self._store.current_revision_on(connection)
            if revision is None:
                if allow_missing:
                    return None
                raise QueueSchemaError("job queue limit policy is missing")
            return limits_from_json(
                self._store.read_policy_on(connection)[1],
                revision=revision,
            )

    def schema_initialized(self) -> bool:
        """Report whether the queue tables already exist in this database."""
        return self._store.schema_exists()

    def validate_schema(self) -> None:
        """Fail when the stored queue schema is absent or unsupported."""
        self._store.validate_schema()

    def get_limits(self) -> Limits:
        stored = self._stored_policy()
        assert stored is not None
        return stored

    def configure_limits(self, limits: Limits, *, expected_revision: int) -> Limits:
        """Atomically append a new policy revision under optimistic checking."""
        with self._store.connection() as connection:
            current_revision = self._store.current_revision_on(connection)
            if current_revision is None:
                raise PolicyError("job queue is not initialized")
            stored = limits_from_json(
                self._store.read_policy_on(connection)[1],
                revision=current_revision,
            )
            if stored.same_policy(limits):
                return stored
            if current_revision != expected_revision:
                raise PolicyError(
                    f"job queue limit policy revision conflict: expected "
                    f"{expected_revision}, current is {current_revision}"
                )
            revision = current_revision + 1
            JobStore.append_policy(connection, revision, limits.policy_json)
            return limits.with_revision(revision)

    def submit(self, spec: JobSpec) -> Job:
        with self._store.connection() as connection:
            return self._submit(connection, [spec])[spec.job_id]

    def submit_many(self, specs: Sequence[JobSpec]) -> tuple[Job, ...]:
        with self._store.connection() as connection:
            created = self._submit(connection, list(specs))
        return tuple(created[spec.job_id] for spec in specs)

    def admit(self, spec: JobSpec) -> Claim:
        """Submit and claim together, or leave no job behind."""
        with self._store.connection() as connection:
            created = self._submit(connection, [spec])[spec.job_id]
            if created.state != JOB_STATE_QUEUED:
                raise DependencyUnresolvedError(
                    f"job {spec.job_id} is not immediately eligible (state={created.state})"
                )
            if not self._is_eligible(connection, created):
                raise DependencyUnresolvedError(
                    f"job {spec.job_id} still has unresolved dependencies"
                )
            policy = self._load_policy(connection)
            self._require_capacity(connection, created, policy)
            return self._claim(connection, created)

    def claim_next(self, owner_id: str) -> Claim | None:
        owner = _checked_owner(owner_id)
        with self._store.connection() as connection:
            self._advance(connection, owner)
            policy = self._load_policy(connection)
            if self._claimed_count(connection) >= policy.global_limit:
                return None
            if self._claimed_count(connection, owner_id=owner) >= policy.per_owner_limit:
                return None
            for job in self._queued_jobs(connection, owner):
                if not self._is_eligible(connection, job):
                    continue
                if not self._resource_available(connection, job.resource_key, policy):
                    continue
                return self._claim(connection, job)
            return None

    def change_resource(self, claim: Claim, resource_key: str | None) -> Claim:
        with self._store.connection() as connection:
            job = self._require_claimed_job(connection, claim)
            key = None if resource_key is None else _checked_key(resource_key)
            if key == job.resource_key:
                return _claim_of(job)
            policy = self._load_policy(connection)
            if key is not None:
                limit = policy.resource_limits.get(key)
                active = self._claimed_count(connection, resource_key=key)
                if limit is not None and active >= limit:
                    raise CapacityUnavailableError(
                        f"resource capacity limit reached: {key}",
                        reason="resource",
                        resource_key=key,
                        active=active,
                        limit=limit,
                    )
            connection.execute(
                "UPDATE orchestra_jobs SET resource_key = ? WHERE job_id = ?",
                (key, job.job_id),
            )
            return _claim_of(self._load(connection, job.job_id))

    def finish(self, claim: Claim, outcome: JobOutcome) -> Job:
        with self._store.connection() as connection:
            return self._finish(connection, claim, outcome)

    def claim_for(self, job_id: str, owner_id: str) -> Claim:
        """Recover the live claim for a claimed job.

        Execution layers persist only the job id, so a supervisor that restarted
        or holds no in-memory claim can resume authority over its own job.
        """
        job = self.get(job_id, owner_id)
        if job.state != JOB_STATE_CLAIMED:
            raise ClaimRejectedError(
                f"job {job_id} is not claimed by {owner_id} (state: {job.state})"
            )
        return _claim_of(job)

    def cancel(self, job_id: str, owner_id: str) -> Job:
        owner = _checked_owner(owner_id)
        with self._store.connection() as connection:
            row = self._row(connection, job_id)
            if row is None or str(row["owner_id"]) != owner:
                raise JobNotFoundError(f"job not found: {job_id}")
            dependencies = self._store.dependencies_for(connection, [job_id])
            job = self._store.load_job(connection, row, dependencies=dependencies[job_id])
            if not job.is_open:
                return job
            if job.state == JOB_STATE_QUEUED:
                self._terminate(
                    connection,
                    job,
                    JobOutcome(
                        status=JOB_STATE_CANCELLED,
                        blocker_text="Cancelled before execution",
                    ),
                )
                self._advance(connection, owner)
                return self._load(connection, job.job_id)
            if not job.cancel_requested:
                connection.execute(
                    "UPDATE orchestra_jobs SET cancel_requested = 1, reason = ? WHERE job_id = ?",
                    ("cancellation requested", job.job_id),
                )
            return self._load(connection, job.job_id)

    def get(self, job_id: str, owner_id: str) -> Job:
        owner = _checked_owner(owner_id)
        with self._store.connection() as connection:
            row = self._row(connection, job_id)
            if row is None or str(row["owner_id"]) != owner:
                raise JobNotFoundError(f"job not found: {job_id}")
            dependencies = self._store.dependencies_for(connection, [job_id])
            return self._store.load_job(connection, row, dependencies=dependencies[job_id])

    def list_jobs(self, owner_id: str, state: str | None = None) -> tuple[Job, ...]:
        owner = _checked_owner(owner_id)
        with self._store.connection() as connection:
            if state is None:
                rows = connection.execute(
                    "SELECT * FROM orchestra_jobs WHERE owner_id = ? ORDER BY seq",
                    (owner,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM orchestra_jobs WHERE owner_id = ? AND state = ?"
                    " ORDER BY seq",
                    (owner, state),
                ).fetchall()
            if not rows:
                return ()
            job_ids = [str(row["job_id"]) for row in rows]
            dependencies = self._store.dependencies_for(connection, job_ids)
            return tuple(
                self._store.load_job(connection, row, dependencies=dependencies[str(row["job_id"])])
                for row in rows
            )

    def has_outstanding(self, owner_id: str) -> bool:
        owner = _checked_owner(owner_id)
        with self._store.connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM orchestra_jobs WHERE owner_id = ? AND state IN (?, ?) LIMIT 1",
                (owner, *sorted(OPEN_JOB_STATES)),
            ).fetchone()
            return row is not None

    # ---- submission and graph validation ----

    def _submit(
        self,
        connection: sqlite3.Connection,
        specs: Sequence[JobSpec],
    ) -> dict[str, Job]:
        if not specs:
            return {}
        batch_ids = [spec.job_id for spec in specs]
        if len(set(batch_ids)) != len(batch_ids):
            raise JobSpecError("submission contains duplicate job ids")
        batch_owner = {spec.job_id: spec.owner_id for spec in specs}
        existing = [
            str(row["job_id"])
            for row in connection.execute(
                "SELECT job_id FROM orchestra_jobs WHERE job_id IN ("
                + ", ".join("?" for _ in batch_ids)
                + ")",
                tuple(batch_ids),
            ).fetchall()
        ]
        if existing:
            raise JobSpecError("job ids already exist: " + ", ".join(sorted(existing)))
        for spec_item in specs:
            for dependency in spec_item.dependencies:
                if dependency.job_id in batch_owner:
                    if batch_owner[dependency.job_id] != spec_item.owner_id:
                        raise JobForbiddenError(
                            f"job {spec_item.job_id} cannot depend on another owner's job"
                            f" {dependency.job_id}"
                        )
                    continue
                self._require_external_predecessor(connection, spec_item, dependency.job_id)
        self._require_acyclic(specs)

        sequence = self._store.next_seq(connection)
        created: dict[str, Job] = {}
        now = _utc_now()
        pending: list[Job] = []
        for spec in specs:
            job = Job(
                job_id=spec.job_id,
                owner_id=spec.owner_id,
                state=JOB_STATE_QUEUED,
                seq=sequence,
                created_at=now,
                parameters=deserialize_json_payload(spec.parameters_json),
                dependencies=spec.dependencies,
                resource_key=spec.resource_key,
            )
            sequence += 1
            pending.append(job)
        # Rows first, then edges: an edge may point at a job later in the batch.
        for job in pending:
            self._store.insert_job_row(connection, job)
        for job in pending:
            self._store.insert_dependencies(connection, job)
            created[job.job_id] = job
        owners = {spec.owner_id for spec in specs}
        for owner in owners:
            self._advance(connection, owner)
        loaded = self._store.load_by_ids(connection, batch_ids)
        created.update(loaded)
        return created

    @staticmethod
    def _require_external_predecessor(
        connection: sqlite3.Connection,
        spec: JobSpec,
        predecessor_id: str,
    ) -> None:
        row = connection.execute(
            "SELECT owner_id FROM orchestra_jobs WHERE job_id = ?",
            (predecessor_id,),
        ).fetchone()
        if row is None:
            raise JobSpecError(
                f"job {spec.job_id} depends on unknown job {predecessor_id}"
            )
        if str(row["owner_id"]) != spec.owner_id:
            raise JobForbiddenError(
                f"job {spec.job_id} cannot depend on another owner's job {predecessor_id}"
            )

    @staticmethod
    def _require_acyclic(specs: Sequence[JobSpec]) -> None:
        batch_ids = {spec.job_id for spec in specs}
        edges = {
            item.job_id: tuple(
                dependency.job_id
                for dependency in item.dependencies
                if dependency.job_id in batch_ids
            )
            for item in specs
        }
        visited: set[str] = set()
        active: set[str] = set()

        def visit(job_id: str) -> None:
            if job_id in active:
                raise JobSpecError(f"dependency cycle detected at job {job_id}")
            if job_id in visited:
                return
            active.add(job_id)
            for parent in edges.get(job_id, ()):
                visit(parent)
            active.remove(job_id)
            visited.add(job_id)

        for job_id in batch_ids:
            visit(job_id)

    # ---- capacity and claims ----

    def _load_policy(self, connection: sqlite3.Connection) -> Limits:
        revision, policy = self._store.read_policy_on(connection)
        return limits_from_json(policy, revision=revision)

    @staticmethod
    def _claimed_count(
        connection: sqlite3.Connection,
        *,
        owner_id: str | None = None,
        resource_key: str | None = None,
        exclude_job_id: str | None = None,
    ) -> int:
        sql = "SELECT COUNT(*) AS total FROM orchestra_jobs WHERE state = ?"
        params: list[object] = [JOB_STATE_CLAIMED]
        if owner_id is not None:
            sql += " AND owner_id = ?"
            params.append(owner_id)
        if resource_key is not None:
            sql += " AND resource_key = ?"
            params.append(resource_key)
        if exclude_job_id is not None:
            sql += " AND job_id <> ?"
            params.append(exclude_job_id)
        return int(connection.execute(sql, tuple(params)).fetchone()["total"])

    def _resource_available(
        self,
        connection: sqlite3.Connection,
        resource_key: str | None,
        policy: Limits,
        *,
        exclude_job_id: str | None = None,
    ) -> bool:
        if resource_key is None:
            return True
        limit = policy.resource_limits.get(resource_key)
        if limit is None:
            return True
        return (
            self._claimed_count(
                connection,
                resource_key=resource_key,
                exclude_job_id=exclude_job_id,
            )
            < limit
        )

    def _require_capacity(
        self,
        connection: sqlite3.Connection,
        job: Job,
        policy: Limits,
    ) -> None:
        global_active = self._claimed_count(connection)
        if global_active >= policy.global_limit:
            raise CapacityUnavailableError(
                "global concurrency limit reached",
                reason="global",
                active=global_active,
                limit=policy.global_limit,
            )
        owner_active = self._claimed_count(connection, owner_id=job.owner_id)
        if owner_active >= policy.per_owner_limit:
            raise CapacityUnavailableError(
                "owner concurrency limit reached",
                reason="owner",
                active=owner_active,
                limit=policy.per_owner_limit,
            )
        key = job.resource_key
        if key is not None:
            limit = policy.resource_limits.get(key)
            active = self._claimed_count(connection, resource_key=key)
            if limit is not None and active >= limit:
                raise CapacityUnavailableError(
                    f"resource capacity limit reached: {key}",
                    reason="resource",
                    resource_key=key,
                    active=active,
                    limit=limit,
                )

    def _claim(self, connection: sqlite3.Connection, job: Job) -> Claim:
        token = _new_token()
        claimed_at = _utc_now()
        connection.execute(
            "UPDATE orchestra_jobs SET state = ?, claim_token = ?, claimed_at = ?, reason = NULL"
            " WHERE job_id = ? AND state = ?",
            (JOB_STATE_CLAIMED, token, claimed_at, job.job_id, JOB_STATE_QUEUED),
        )
        return Claim(
            job_id=job.job_id,
            owner_id=job.owner_id,
            token=token,
            seq=job.seq,
            resource_key=job.resource_key,
            claimed_at=claimed_at,
            cancel_requested=job.cancel_requested,
        )

    def _require_claimed_job(self, connection: sqlite3.Connection, claim: Claim) -> Job:
        row = self._row(connection, claim.job_id)
        if row is None:
            raise ClaimRejectedError(f"claim references an unknown job: {claim.job_id}")
        if (
            str(row["owner_id"]) != claim.owner_id
            or row["claim_token"] is None
            or str(row["claim_token"]) != claim.token
        ):
            raise ClaimRejectedError(f"claim identity is not valid for job {claim.job_id}")
        if str(row["state"]) != JOB_STATE_CLAIMED:
            raise ClaimRejectedError(
                f"claim for job {claim.job_id} is no longer active (state={row['state']})"
            )
        dependencies = self._store.dependencies_for(connection, [claim.job_id])
        return self._store.load_job(connection, row, dependencies=dependencies[claim.job_id])

    # ---- completion and eligibility ----

    def _finish(self, connection: sqlite3.Connection, claim: Claim, outcome: JobOutcome) -> Job:
        row = self._row(connection, claim.job_id)
        if row is None:
            raise ClaimRejectedError(f"claim references an unknown job: {claim.job_id}")
        dependencies = self._store.dependencies_for(connection, [claim.job_id])
        job = self._store.load_job(connection, row, dependencies=dependencies[claim.job_id])
        if str(row["owner_id"]) != claim.owner_id or job.claim_token != claim.token:
            raise ClaimRejectedError(f"claim identity is not valid for job {claim.job_id}")
        if not job.is_open:
            if job.outcome is not None and job.outcome.same_facts(outcome):
                return job
            raise JobConflictError(
                f"job {claim.job_id} is already terminal as {job.state};"
                " a conflicting outcome cannot replace it"
            )
        if job.state != JOB_STATE_CLAIMED:
            raise ClaimRejectedError(f"job {claim.job_id} has no active claim")
        self._terminate(connection, job, outcome)
        self._advance(connection, job.owner_id)
        return self._load(connection, job.job_id)

    @staticmethod
    def _terminate(
        connection: sqlite3.Connection,
        job: Job,
        outcome: JobOutcome,
    ) -> None:
        connection.execute(
            "UPDATE orchestra_jobs SET state = ?, finished_at = ?, outcome_json = ?, reason = ?"
            " WHERE job_id = ? AND state IN (?, ?)",
            (
                outcome.status,
                _utc_now(),
                outcome.outcome_json,
                outcome.blocker_text,
                job.job_id,
                JOB_STATE_QUEUED,
                JOB_STATE_CLAIMED,
            ),
        )

    def _queued_jobs(self, connection: sqlite3.Connection, owner_id: str) -> tuple[Job, ...]:
        rows = connection.execute(
            "SELECT * FROM orchestra_jobs WHERE owner_id = ? AND state = ? ORDER BY seq",
            (owner_id, JOB_STATE_QUEUED),
        ).fetchall()
        if not rows:
            return ()
        job_ids = [str(row["job_id"]) for row in rows]
        dependencies = self._store.dependencies_for(connection, job_ids)
        return tuple(
            self._store.load_job(connection, row, dependencies=dependencies[str(row["job_id"])])
            for row in rows
        )

    def _advance(self, connection: sqlite3.Connection, owner_id: str) -> None:
        """Skip jobs whose predecessors can no longer satisfy their edges."""
        while True:
            candidates = self._queued_jobs(connection, owner_id)
            if not candidates:
                return
            predecessor_ids = {
                dependency.job_id for job in candidates for dependency in job.dependencies
            }
            predecessors = self._store.load_by_ids(connection, sorted(predecessor_ids))
            skipped = False
            for job in candidates:
                status, blocking = self._evaluate(job, predecessors)
                if status != _UNSATISFIED:
                    continue
                assert blocking is not None
                self._terminate(
                    connection,
                    job,
                    JobOutcome(
                        status=JOB_STATE_SKIPPED,
                        blocker_text=(
                            f"{SKIPPED_DEPENDENCY_REASON}: {blocking.job_id}"
                            f" ({blocking.condition})"
                        ),
                    ),
                )
                predecessors[job.job_id] = self._load(connection, job.job_id)
                skipped = True
            if not skipped:
                return

    @staticmethod
    def _evaluate(
        job: Job,
        predecessors: dict[str, Job],
    ) -> tuple[str, Dependency | None]:
        """Classify dependency state as ready, waiting, or unsatisfiable."""
        if not job.dependencies:
            return _READY, None
        unsatisfied: Dependency | None = None
        for dependency in job.dependencies:
            predecessor = predecessors.get(dependency.job_id)
            if predecessor is None:
                raise JobNotFoundError(
                    f"job {job.job_id} depends on missing job {dependency.job_id}"
                )
            if predecessor.state not in TERMINAL_JOB_STATES:
                return _WAITING, None
            if not _edge_satisfied(dependency.condition, predecessor) and unsatisfied is None:
                unsatisfied = dependency
        if unsatisfied is not None:
            return _UNSATISFIED, unsatisfied
        return _READY, None

    def _is_eligible(self, connection: sqlite3.Connection, job: Job) -> bool:
        if not job.dependencies:
            return True
        predecessors = self._store.load_by_ids(
            connection,
            sorted(dependency.job_id for dependency in job.dependencies),
        )
        status, _ = self._evaluate(job, predecessors)
        return status == _READY

    # ---- storage helpers ----

    @staticmethod
    def _row(connection: sqlite3.Connection, job_id: str) -> sqlite3.Row | None:
        row = connection.execute(
            "SELECT * FROM orchestra_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        return None if row is None else row

    def _load(self, connection: sqlite3.Connection, job_id: str) -> Job:
        row = self._row(connection, job_id)
        if row is None:
            raise JobNotFoundError(f"job not found: {job_id}")
        dependencies = self._store.dependencies_for(connection, [job_id])
        return self._store.load_job(connection, row, dependencies=dependencies[job_id])


def _edge_satisfied(condition: str, predecessor: Job) -> bool:
    if condition == DEPENDENCY_TERMINAL:
        return predecessor.state in TERMINAL_JOB_STATES
    if condition == DEPENDENCY_DONE:
        return predecessor.state == JOB_STATE_DONE
    return (
        predecessor.state == JOB_STATE_DONE
        and predecessor.outcome is not None
        and predecessor.outcome.satisfies_pass
    )


def _claim_of(job: Job) -> Claim:
    if job.claim_token is None:
        raise ClaimRejectedError(f"job {job.job_id} has no claim token")
    return Claim(
        job_id=job.job_id,
        owner_id=job.owner_id,
        token=job.claim_token,
        seq=job.seq,
        resource_key=job.resource_key,
        claimed_at=job.claimed_at or "",
        cancel_requested=job.cancel_requested,
    )


def _checked_owner(owner_id: str) -> str:
    if not isinstance(owner_id, str) or not owner_id.strip():
        raise JobSpecError("owner_id must be a non-empty string")
    return owner_id.strip()


def _checked_key(resource_key: str) -> str:
    trimmed = resource_key.strip()
    if not trimmed:
        raise JobSpecError("resource_key must be a non-empty string")
    if any(character.isspace() for character in trimmed):
        raise JobSpecError("resource_key must not contain whitespace")
    return trimmed


__all__ = ["JobQueue"]


def _checked_policy(stored: Limits, requested: Limits) -> Limits:
    """Return the stored policy, or fail when the requested policy disagrees."""
    if not stored.same_policy(requested):
        raise PolicyError(
            "job queue limit policy conflict: stored policy differs from the "
            "requested policy; use configure_limits with the current revision"
        )
    return stored
