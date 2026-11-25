"""Shared dispatcher-loss reconciliation for Orchestra 2.

One core operation, invoked on demand through the existing status/stop/return
entry points, turns abandoned work into truthful persisted outcomes after a
dispatcher dies. It adds no supervisor, timer, retry, or redelivery: a job is
only touched when its owning dispatcher's lifetime lock is confirmed released,
so a live dispatcher's work is never touched (including a foreign session's).

Process termination is kept separate from queue finalization: an execution
group is terminated and confirmed gone before the unfinished job is marked
failed, and completed work is never rewritten. When execution identity cannot
be verified or termination cannot be confirmed, the job is retained and
reported instead of guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from orchestra import lifetime
from orchestra.artifacts import Response, append
from orchestra.queue import Job, JobQueue, QueueError, run_id_of
from orchestra.terminate import Termination, terminate_group

# Distinct, testable reasons for a process-loss failure (no new status value).
REASON_TERMINATED = "failed: abandoned execution terminated after dispatcher loss"


@dataclass(frozen=True)
class ReconcileEntry:
    """One reconciliation decision for a single running job."""

    job_id: str
    action: str
    detail: str = ""


@dataclass(frozen=True)
class ReconcileReport:
    """Every decision made by one reconciliation pass."""

    entries: tuple[ReconcileEntry, ...]

    def action_of(self, job_id: str) -> str | None:
        for entry in self.entries:
            if entry.job_id == job_id:
                return entry.action
        return None

    @property
    def retained(self) -> tuple[ReconcileEntry, ...]:
        return tuple(e for e in self.entries if e.action.startswith("retained"))


def _now() -> str:
    return datetime.now(UTC).isoformat()


def reconcile_abandoned(
    queue: JobQueue,
    state_dir: Path | str,
    *,
    run_id: str | None = None,
    parent_session: str | None = None,
    grace: float = 5.0,
) -> ReconcileReport:
    """Finalize work owned by confirmed-dead dispatchers.

    Only ``running`` jobs are examined (optionally narrowed by ``run_id`` or
    ``parent_session``). A job with no dispatcher token is left alone (it
    cannot be attributed). A job whose dispatcher lifetime lock is still held
    is left alone. A confirmed-dead dispatcher is the only case reconciliation
    acts on: a registered execution is terminated through the shared helper and,
    once confirmed gone, the job is marked failed (releasing dependents). A
    missing lock (no proof of death), an execution with no recorded group,
    or anything whose ownership or termination cannot be proven is retained and
    reported rather than signaled or finalized.
    """
    entries: list[ReconcileEntry] = []
    for job in queue.running_jobs():
        if run_id is not None and job.run_id != run_id:
            continue
        if parent_session is not None and job.parent_session != parent_session:
            continue
        if job.dispatcher_token is None:
            entries.append(
                ReconcileEntry(job.job_id, "unattributed", "no dispatcher token")
            )
            continue
        liveness = lifetime.probe(state_dir, job.dispatcher_token)
        if liveness is lifetime.Liveness.ALIVE:
            continue  # live dispatcher owns this work; leave it untouched
        if liveness is not lifetime.Liveness.DEAD:
            # No lock file (or any non-DEAD probe): the dispatcher's death is
            # unconfirmed, so ownership cannot be established. Retain and report
            # rather than finalize or signal on an unproven loss.
            entries.append(
                ReconcileEntry(
                    job.job_id,
                    "retained-missing",
                    "no dispatcher lifetime lock: loss unconfirmed",
                )
            )
            continue
        entries.append(_reconcile_one(queue, state_dir, job, grace))
    return ReconcileReport(tuple(entries))


def _reconcile_one(
    queue: JobQueue, state_dir: Path | str, job: Job, grace: float
) -> ReconcileEntry:
    if job.child_pgid is None:
        # The dispatcher died with no recorded execution group. The child may or
        # may not have been spawned; with nothing to verify or terminate, the
        # accepted spawn-before-registration limitation is retained and reported,
        # never finalized on a guess about the unfinished work.
        return ReconcileEntry(
            job.job_id,
            "retained-unverified",
            "no execution registered before dispatcher loss",
        )
    if job.child_start is None:
        # A group id is recorded but its creation identity is unavailable, so
        # ownership of the PID cannot be proven; never signal on doubt.
        return ReconcileEntry(
            job.job_id, "retained-unverified", "execution start identity unavailable"
        )
    result = terminate_group(job.child_pgid, job.child_start, grace=grace)
    if result.outcome is Termination.GONE:
        finalized = _finalize(queue, state_dir, job.job_id, REASON_TERMINATED)
        return ReconcileEntry(
            job.job_id,
            "terminated-finalized" if finalized else "already-terminal",
            result.detail,
        )
    # UNVERIFIED (recycled/inaccessible) or FAILED (still running after KILL):
    # retain unresolved work and report the blocker instead of guessing.
    return ReconcileEntry(
        job.job_id, f"retained-{result.outcome.value}", result.detail
    )


def _finalize(queue: JobQueue, state_dir: Path | str, job_id: str, reason: str) -> bool:
    """Mark one running job failed and record the loss reason.

    The queue re-checks status inside its atomic transaction, so a concurrent
    transition wins and this pass records nothing.
    """
    try:
        queue.complete_job(job_id, "failed")
    except QueueError:
        return False
    append(
        state_dir,
        run_id_of(job_id),
        Response(job_id=job_id, timestamp=_now(), response=reason, transcript=None),
    )
    return True
