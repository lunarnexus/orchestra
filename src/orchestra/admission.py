"""Composition between the durable job queue and the run record store.

The queue owns eligibility, capacity, and claims; :class:`~orchestra.state.StateStore`
owns execution records. Both live in the same database, so one admission or
terminal transition is written as a single transaction: a run row never exists
without its claim, and a claim is never released while its run still looks live.

This module performs no execution and interprets no model output. It maps run
records to job specifications and back.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field

from orchestra.jobs import (
    JOB_STATE_CLAIMED,
    CapacityUnavailableError,
    Claim,
    Dependency,
    JobOutcome,
    JobQueue,
    JobSpec,
)
from orchestra.state import TERMINAL_STATUSES, RunRecord, RunUpdate, StateStore

__all__ = [
    "AdmissionError",
    "ChildAdmission",
    "PlannedChild",
    "TerminalResult",
    "admit_run",
    "run_job_spec",
    "terminalize_run",
]

class AdmissionError(RuntimeError):
    """Raised when a run transition and its job outcome disagree."""


@dataclass(frozen=True)
class PlannedChild:
    """One dependent run to admit in the same transaction as its parent result.

    Dependencies default to the parent job so the child cannot start before the
    result that produced it is durable.
    """

    record: RunRecord
    dependencies: tuple[Dependency, ...] | None = None

    def dependencies_for(self, parent_run_id: str) -> tuple[Dependency, ...]:
        if self.dependencies is not None:
            return self.dependencies
        return (Dependency(parent_run_id),)


@dataclass(frozen=True)
class ChildAdmission:
    """Outcome of one planned child admission."""

    record: RunRecord
    claim: Claim


@dataclass(frozen=True)
class TerminalResult:
    """Result of one terminal run transition."""

    record: RunRecord | None
    children: tuple[RunRecord, ...] = ()
    children_skipped: tuple[str, ...] = ()
    claim_released: bool = False
    reasons: tuple[str, ...] = field(default_factory=tuple)


def run_job_spec(
    record: RunRecord,
    dependencies: Sequence[Dependency] = (),
) -> JobSpec:
    """Build the job definition for one run record (job id == run id)."""
    return JobSpec(
        job_id=record.run_id,
        owner_id=record.orchestrator_session_id,
        resource_key=record.model,
        dependencies=tuple(dependencies),
        parameters={
            "role": record.role,
            "harness": record.harness,
            "task_label": record.task_label,
        },
    )


def admit_run(
    jobs: JobQueue,
    store: StateStore,
    record: RunRecord,
    dependencies: Sequence[Dependency] = (),
) -> Claim:
    """Admit capacity for ``record`` and insert its run row atomically.

    Raises :class:`~orchestra.jobs.CapacityUnavailableError` or
    :class:`~orchestra.jobs.DependencyUnresolvedError` without writing anything
    when the queue rejects the job.
    """
    if record.status != "queued":
        raise AdmissionError(f"admitted runs must start queued, got {record.status!r}")
    spec = run_job_spec(record, dependencies)
    with store.transaction(operation="admit_run") as connection:
        claim = jobs.bind(connection).admit(spec)
        store.insert_run_record(connection, record)
    store.log_run_created(record)
    return claim


def terminalize_run(
    jobs: JobQueue,
    store: StateStore,
    *,
    run_id: str,
    owner_id: str,
    update: RunUpdate,
    outcome: JobOutcome,
    children: Sequence[PlannedChild] = (),
) -> TerminalResult:
    """Write one terminal run result, release its claim, and admit children.

    All three happen in one transaction. Children that cannot be admitted under
    current limits are reported in ``children_skipped`` and leave the parent
    result intact.
    """
    if update.status not in TERMINAL_STATUSES:
        raise AdmissionError(f"terminal status required, got {update.status!r}")
    if outcome.status != update.status:
        raise AdmissionError(
            f"job outcome status {outcome.status!r} must match run status {update.status!r}"
        )
    with store.transaction(operation="terminalize_run") as connection:
        bound = jobs.bind(connection)
        transition = store.apply_run_update_on(connection, run_id, update)
        released = _release_claim(connection, bound, run_id, owner_id, outcome)
        admitted, skipped, reasons = _admit_children(
            connection, bound, store, run_id=run_id, children=children
        )

    if transition is not None:
        store.log_run_updated(transition.previous.status, transition.record)
    for child in admitted:
        store.log_run_created(child.record)
    return TerminalResult(
        record=transition.record if transition is not None else None,
        children=tuple(child.record for child in admitted),
        children_skipped=skipped,
        claim_released=released,
        reasons=reasons,
    )


def _release_claim(
    connection: sqlite3.Connection,
    bound: JobQueue,
    run_id: str,
    owner_id: str,
    outcome: JobOutcome,
) -> bool:
    """Finish ``run_id``'s claim inside ``connection``; false when already closed."""
    job = bound.get(run_id, owner_id)
    if job.state != JOB_STATE_CLAIMED:
        return False
    claim = bound.claim_for(run_id, owner_id)
    bound.finish(claim, outcome)
    return True


def _admit_children(
    connection: sqlite3.Connection,
    bound: JobQueue,
    store: StateStore,
    *,
    run_id: str,
    children: Sequence[PlannedChild],
) -> tuple[tuple[ChildAdmission, ...], tuple[str, ...], tuple[str, ...]]:
    admitted: list[ChildAdmission] = []
    skipped: list[str] = []
    reasons: list[str] = []
    for planned in children:
        savepoint = f"child_{planned.record.run_id.replace('-', '_')}"
        connection.execute(f"SAVEPOINT {savepoint}")
        try:
            claim = bound.admit(run_job_spec(planned.record, planned.dependencies_for(run_id)))
            store.insert_run_record(connection, planned.record)
        except CapacityUnavailableError as exc:
            connection.execute(f"ROLLBACK TO {savepoint}")
            connection.execute(f"RELEASE {savepoint}")
            skipped.append(planned.record.run_id)
            reasons.append(f"{planned.record.run_id}: {exc}")
        else:
            connection.execute(f"RELEASE {savepoint}")
            admitted.append(ChildAdmission(record=planned.record, claim=claim))
    return tuple(admitted), tuple(skipped), tuple(reasons)
