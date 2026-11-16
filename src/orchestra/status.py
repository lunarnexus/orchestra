"""Status query and rendering for Orchestra 2.

Pure query over the job queue plus the only display formatting for
`/orch status`. No cache, no LLM, no timestamps.
"""

from __future__ import annotations

from dataclasses import dataclass

from orchestra.queue import JobQueue

_TERMINAL: frozenset[str] = frozenset({"succeeded", "failed", "skipped"})


class StatusError(ValueError):
    """Raised on invalid input types for status functions."""


@dataclass(frozen=True)
class StatusEntry:
    """One active (pending or running) session job."""

    sequence: int
    role: str
    status: str
    run_id: str
    waiting_on: tuple[str, ...]


@dataclass(frozen=True)
class LastCompleted:
    """Tallies for the most recently finished run of a session."""

    run_id: str
    succeeded: int
    failed: int
    skipped: int


@dataclass(frozen=True)
class StatusData:
    """Typed result of a status query, independent of any rendering."""

    session_jobs: tuple[StatusEntry, ...]
    global_running: int
    global_pending: int
    last_completed: LastCompleted | None


def status(queue: JobQueue, parent_session: str) -> StatusData:
    """Query the queue for session and global status.

    Session jobs are the matching session's pending and running jobs,
    ordered by sequence. ``waiting_on`` lists prerequisite job ids that are
    not yet terminal. ``last_completed`` tallies the most recently finished
    run (max finished_at among terminal jobs of that session's runs).
    """
    if not isinstance(queue, JobQueue):
        raise StatusError(f"queue must be a JobQueue, got {type(queue).__name__}")
    if not isinstance(parent_session, str):
        raise StatusError(
            f"parent_session must be a str, got {type(parent_session).__name__}"
        )

    all_jobs = queue.list_jobs()
    job_by_id = {job.job_id: job for job in all_jobs}

    session_jobs = tuple(
        StatusEntry(
            sequence=job.sequence,
            role=job.role,
            status=job.status,
            run_id=job.run_id,
            waiting_on=tuple(
                prereq_id
                for prereq_id in job.prerequisites
                if prereq_id in job_by_id
                and job_by_id[prereq_id].status not in _TERMINAL
            ),
        )
        for job in sorted(
            (
                job
                for job in all_jobs
                if job.parent_session == parent_session
                and job.status in ("pending", "running")
            ),
            key=lambda job: job.sequence,
        )
    )

    global_running = sum(1 for job in all_jobs if job.status == "running")
    global_pending = sum(1 for job in all_jobs if job.status == "pending")

    session_run_ids = {
        job.run_id
        for job in all_jobs
        if job.parent_session == parent_session and job.status in _TERMINAL
    }
    finished = [
        job
        for job in all_jobs
        if job.run_id in session_run_ids
        and job.status in _TERMINAL
        and job.finished_at is not None
    ]
    last_completed: LastCompleted | None = None
    if finished:
        latest_run = max(finished, key=lambda job: job.finished_at or "").run_id
        tallies = {"succeeded": 0, "failed": 0, "skipped": 0}
        for job in finished:
            if job.run_id == latest_run:
                tallies[job.status] += 1
        last_completed = LastCompleted(
            run_id=latest_run,
            succeeded=tallies["succeeded"],
            failed=tallies["failed"],
            skipped=tallies["skipped"],
        )

    return StatusData(
        session_jobs=session_jobs,
        global_running=global_running,
        global_pending=global_pending,
        last_completed=last_completed,
    )


def render_status(data: StatusData, mode: str) -> str:
    """Format StatusData for display. The only display formatting for status."""
    lines = [f"Orchestra: {mode}", ""]
    if data.session_jobs:
        lines.append("This session:")
        lines.extend(
            _entry_line(entry, _sequence_of(entry.waiting_on))
            for entry in data.session_jobs
        )
    else:
        lines.append("This session: no active jobs.")
    lines.append("")
    lines.append(
        f"Global: {data.global_running} running, {data.global_pending} pending"
    )
    completed = data.last_completed
    if completed is not None:
        lines.append("")
        tally = f"{completed.succeeded} succeeded, {completed.failed} failed"
        if completed.skipped:
            tally += f", {completed.skipped} skipped"
        lines.append(f"Last completed: run {completed.run_id} — {tally}")
    return "\n".join(lines) + "\n"


def _sequence_of(job_ids: tuple[str, ...]) -> dict[str, int]:
    """Map prerequisite job ids to their sequence numbers.

    Queue job ids have the ``<run_id>:<sequence>`` form; anything else is
    rendered verbatim via a sequence of -1 placeholder avoided by keeping
    the raw id in the mapping lookup.
    """
    mapping: dict[str, int] = {}
    for job_id in job_ids:
        _, _, tail = job_id.rpartition(":")
        mapping[job_id] = int(tail) if tail.isdigit() else -1
    return mapping


def _entry_line(entry: StatusEntry, sequence_of: dict[str, int]) -> str:
    line = f"  #{entry.sequence}".ljust(7) + entry.role.ljust(12)
    line += entry.status.ljust(10) + f"run {entry.run_id}"
    if entry.waiting_on:
        refs = ", ".join(f"#{sequence_of[job_id]}" for job_id in entry.waiting_on)
        line += f"   (waiting on {refs})"
    return line
