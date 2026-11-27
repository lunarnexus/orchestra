"""Status query and rendering for Orchestra 2.

Pure query over the job queue plus the only display formatting for
`/orch status`. No cache, no LLM, no timestamps.
"""

from __future__ import annotations

from dataclasses import dataclass

from orchestra.queue import JobQueue, SessionSnapshot


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


def status(
    queue: JobQueue,
    parent_session: str,
    *,
    snapshot: SessionSnapshot | None = None,
) -> StatusData:
    """Query the authoritative queue snapshot for session and global status.

    Every fact comes from one :meth:`JobQueue.snapshot` read: session jobs are
    that session's pending/running rows ordered by sequence (``waiting_on``
    lists prerequisite ids within the snapshot that are not yet terminal), the
    global tallies are the snapshot's cross-session counts, and
    ``last_completed`` tallies the session's most recently finished run. When a
    caller already holds a snapshot (the core session evaluator reuses one for
    status, readiness selection, and Results) pass it as ``snapshot`` so the
    status view is derived from that same consistent read instead of re-reading
    the queue. There is no list_jobs scan and no re-implemented owner/terminal
    filter here: both views come from the queue-owned snapshot.
    """
    if not isinstance(queue, JobQueue):
        raise StatusError(f"queue must be a JobQueue, got {type(queue).__name__}")
    if not isinstance(parent_session, str):
        raise StatusError(
            f"parent_session must be a str, got {type(parent_session).__name__}"
        )
    if snapshot is None:
        snap = queue.snapshot(parent_session)
    else:
        if not isinstance(snapshot, SessionSnapshot):
            raise StatusError(
                f"snapshot must be a SessionSnapshot, got {type(snapshot).__name__}"
            )
        snap = snapshot

    # A prerequisite of a session job is inserted in the same submission, so it
    # is always among this session's own snapshot rows; resolve against them.
    job_by_id = {job.job_id: job for job in snap.jobs}

    session_jobs = tuple(
        StatusEntry(
            sequence=job.sequence,
            role=job.role,
            status=job.status,
            run_id=job.run_id,
            waiting_on=tuple(
                prereq_id
                for prereq_id in job.prerequisites
                if prereq_id in job_by_id and not job_by_id[prereq_id].is_terminal
            ),
        )
        for job in sorted(
            (job for job in snap.jobs if not job.is_terminal),
            key=lambda job: job.sequence,
        )
    )

    global_running = snap.global_running
    global_pending = snap.global_pending

    finished = [
        job
        for job in snap.jobs
        if job.is_terminal and job.finished_at is not None
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


def render_session_counts(data: StatusData) -> str:
    """One factual session-workload snapshot line for dispatch acknowledgements.

    Counts the originating session's currently active (running/pending) jobs
    from a queue snapshot. It is a point-in-time count, not a promise that job
    state cannot change afterward; freshly submitted work is still pending
    until the dispatcher claims it.
    """
    running = sum(1 for entry in data.session_jobs if entry.status == "running")
    pending = sum(1 for entry in data.session_jobs if entry.status == "pending")
    return f"Session jobs: {running} running, {pending} pending."


def render_running_meter(data: StatusData) -> str:
    """Compact running-only role meter for the live below-editor widget.

    Counts only the originating session's currently RUNNING jobs grouped by
    role, from the same queue snapshot as ``status``. Pending and terminal
    work is excluded, and no role is listed unless at least one of its jobs is
    running. The native host renders this verbatim; it must not derive the
    counts itself.
    """
    counts: dict[str, int] = {}
    for entry in data.session_jobs:
        if entry.status == "running":
            counts[entry.role] = counts.get(entry.role, 0) + 1
    if not counts:
        return "Orchestra: no running jobs"
    meter = ", ".join(f"{role}×{n}" for role, n in sorted(counts.items()))
    return f"Orchestra: running {meter}"


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
