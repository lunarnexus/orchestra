"""Dispatcher for Orchestra 2.

Connects queued jobs to harness execution and records outcomes. The loop
runs only while jobs exist for its run: it claims eligible jobs through
``JobQueue.claim_next``, spawns one worker thread per claimed job, and
exits once every job in the run is terminal. Worker completion signals the
loop through a condition; a small bounded fallback wait covers the edge
where nothing is running and a prerequisite has just been released. Worker
threads block on their subprocesses, so waiting costs no CPU. The
dispatcher is not a daemon and owns no recovery machinery: if the host
process dies, its running jobs die with it (deferred tech debt).

The dispatcher owns clocks and decisions only. It passes each job's
soft timeout and turn limit through to the plugin and enforces hard
timeout expiry itself by calling ``harness.terminate(handle)``. Command
payloads arrive as the ``payloads`` mapping (job_id -> argv); reading
configuration, resolving roles, and creating Task records belong to
Submit, not here.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from orchestra.artifacts import Response, append, recall
from orchestra.harness import Budgets, CommandJob, Harness, HarnessError, Outcome
from orchestra.queue import Job, JobQueue, Status, run_id_of

_TERMINAL = frozenset({"succeeded", "failed", "skipped"})
# The dispatcher's success marker: the job's own returned text is the recorded
# response, so the marker is only the body when a job returned nothing.
SUCCEEDED = "succeeded"
# Answers up to this size are inlined in the run record; larger answers stay in
# the job's ``.output`` file and are resolved through :func:`resolve_answer`,
# keeping every run record compact and byte-exact in its output file.
_MAX_INLINE_BYTES = 4096
# Maximum seconds the loop sleeps when nothing can be claimed; a completion
# signal wakes it earlier. Covers the prerequisite-release edge where no
# worker is running to notify.
_FALLBACK_WAIT = 0.25


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class JobEvent:
    """One generic job lifecycle transition for a UI or caller to observe.

    A transition is published only after the durable queue/artifact state it
    describes is already persisted, so an observer never sees an event for
    state that is not yet real. The event carries the originating session,
    run, and job identity plus the new status; it is fully generic, with no
    role-specific handling.
    """

    job_id: str
    run_id: str
    session_id: str
    status: Status


def _emit(
    on_event: Callable[[JobEvent], None] | None, event: JobEvent
) -> None:
    """Publish one event; a callback failure never affects job execution."""
    if on_event is None:
        return
    with suppress(Exception):
        on_event(event)


def _pending_ids(queue: JobQueue, run_id: str) -> set[str]:
    return {job.job_id for job in queue.list_jobs(run_id) if job.status == "pending"}


def _emit_skipped(
    on_event: Callable[[JobEvent], None] | None,
    queue: JobQueue,
    run_id: str,
    was_pending: set[str],
) -> None:
    """Publish skip transitions that a just-failed job newly caused.

    Only jobs that were pending before the completion and are skipped after
    it are reported, so a concurrently running job is never misreported; a
    pending job can only become skipped through failure handling.
    """
    if on_event is None:
        return
    for job in queue.list_jobs(run_id):
        if job.status == "skipped" and job.job_id in was_pending:
            _emit(
                on_event,
                JobEvent(job.job_id, run_id, job.parent_session, "skipped"),
            )


def recorded_reasons(state_dir: Path | str, run_id: str) -> dict[str, str]:
    """Read-only accessor: job_id -> recorded response text for a run.

    A recorded body is the job's returned answer, or its failure reason
    followed by whatever it returned before failing. Guidance consumes this
    mapping through ``derive_return_category``, which consults it only for
    failed jobs.
    """
    return {
        record.job_id: record.response
        for record in recall(state_dir, run_id)
        if isinstance(record, Response)
    }


def _output_path(state_dir: Path | str, run_id: str, job_id: str) -> Path:
    return Path(state_dir) / "artifacts" / run_id / f"{job_id}.output"


def output_path(state_dir: Path | str, job_id: str) -> Path:
    """Path to one job's own captured-output file, located from its id alone.

    A dependent reads an upstream job's actual returned text from this file, so
    the answer is reachable from the job id whether or not it was small enough
    to inline in the run record.
    """
    return _output_path(state_dir, run_id_of(job_id), job_id)


def _failure_reason(outcome: Outcome) -> str:
    if outcome.reason:
        # Harness-owned diagnostic (budget wrap-up, rejected prompt): the real
        # reason, recorded before the queue releases dependents.
        return f"failed: {outcome.reason}"
    if outcome.terminated:
        return "failed: terminated (hard timeout or cancellation)"
    return f"failed: exit status {outcome.exit_status}"


def _response_body(reason: str, output: str) -> str:
    """Compose one job's compact recorded response.

    A successful job's response is its returned answer, so results and every
    dependent read the same text the child produced; the mechanical status
    remains the job's queue status. A failure keeps its diagnostic reason
    first, followed by whatever the job returned before it failed. A job that
    returned nothing records the reason alone.

    When the returned text is larger than the compact inline bound, the record
    keeps only the reason (the marker for a success) and references the full
    answer through the job's ``.output`` transcript; :func:`resolve_answer`
    reads it back so results and dependents still get the real text without
    copying a large answer into every record.
    """
    answer = output.rstrip("\n")
    if len(answer.encode("utf-8")) > _MAX_INLINE_BYTES:
        return reason
    if reason == SUCCEEDED:
        return answer or reason
    return f"{reason}\n\n{answer}" if answer else reason


def resolve_answer(state_dir: Path | str, run_id: str, record: Response) -> str:
    """Return the actual answer text one Response record stands for.

    This is the single core resolution path shared by Results and by dependent
    handoffs: it returns the text the job actually returned, reading the job's
    ``.output`` file when the record kept only a reason because the answer was
    too large to inline. A record that already carries the answer inline is
    returned unchanged, so small answers are never re-read.

    ``reason`` in a record is either the success marker (the answer was empty
    or too large to inline), an already-composed inline body (a reason followed
    by a blank line and the returned text), a bare failure reason whose answer
    lives in the output file, or an inlined success answer returned as-is.
    """
    reason = record.response
    path = _output_path(state_dir, run_id, record.job_id)
    body = (
        path.read_text(encoding="utf-8").rstrip("\n") if path.is_file() else ""
    )
    if reason == SUCCEEDED:
        return body or reason
    if "\n\n" in reason:
        return reason
    if reason.startswith("failed:") and body:
        return f"{reason}\n\n{body}"
    return reason


# Label header that separates a child's stderr/diagnostics from its stdout
# answer in the recorded transcript body, so a warning never splices onto the
# end of the answer text.
_STDERR_HEADER = "[stderr]"


def _transcript_body(output: str, error: str) -> str:
    """Join stdout answer and stderr diagnostics as separate, labeled sections.

    The answer (stdout) is the response body. Stderr is kept visible but in a
    distinctly labeled section, never inline-appended to the answer text.
    """
    if not error:
        return output
    if not output:
        return f"{_STDERR_HEADER}\n{error}"
    return f"{output.rstrip(chr(10))}\n\n{_STDERR_HEADER}\n{error}"


def _record(
    state_dir: Path | str,
    run_id: str,
    job_id: str,
    reason: str,
    output: str,
    error: str = "",
) -> str | None:
    """Write one output file when there is output, append one Response.

    The Response is recorded here, before the queue releases dependents, in
    two places: the run's whole-record audit file and the job's own records
    view. The view is what Submit hands to a dependent, so a follow-up always
    reads this job's assignment plus the text it actually returned.
    """
    transcript: str | None = None
    combined_output = _transcript_body(output, error)
    if combined_output:
        path = _output_path(state_dir, run_id, job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(combined_output, encoding="utf-8")
        transcript = str(path)
    record = Response(
        job_id=job_id,
        timestamp=_now(),
        response=_response_body(reason, output),
        transcript=transcript,
    )
    append(state_dir, run_id, record)
    append(state_dir, run_id, record, scope=job_id)
    return transcript


class _Run:
    """Shared state between the dispatcher loop and its worker threads."""

    def __init__(self) -> None:
        self.cond = threading.Condition()
        self.handles: dict[str, object] = {}
        self.threads: list[threading.Thread] = []

    def wake(self) -> None:
        with self.cond:
            self.cond.notify_all()


def run(
    queue: JobQueue,
    state_dir: Path | str,
    harness: Harness,
    run_id: str,
    *,
    global_limit: int,
    per_session_limit: int,
    model_limits: Mapping[str, int] | None = None,
    payloads: Mapping[str, Sequence[str]],
    stop_event: threading.Event | None = None,
    on_event: Callable[[JobEvent], None] | None = None,
) -> None:
    """Execute every queued job of ``run_id`` to a terminal state.

    Claims eligible jobs (limits are passed straight to the queue), runs
    each claimed job in its own worker thread through ``harness``, records
    one Response per executed job carrying the text it actually returned, and
    updates the queue so
    dependents release or are skipped. Returns once all jobs of the run
    are terminal, or immediately when the run has no jobs.

    When ``on_event`` is supplied, one :class:`JobEvent` is published for each
    started job and each terminal transition (including dependents a failure
    newly skips), always after the durable queue/artifact state already
    exists. A callback that raises is swallowed so it can never turn a
    successful job into a failure or hang the run.

    Stop semantics: when ``stop_event`` is set, running jobs are terminated
    through the harness and marked failed by their workers (dependents are
    skipped by the queue); pending jobs are left pending, and ``run``
    returns without executing them.
    """
    state = _Run()
    while True:
        if stop_event is not None and stop_event.is_set():
            with state.cond:
                handles = list(state.handles.values())
            for handle in handles:
                try:
                    harness.terminate(handle)
                except HarnessError:
                    pass  # handle not started or already gone
            break
        jobs = queue.list_jobs(run_id)
        if all(job.status in _TERMINAL for job in jobs):
            break
        claimed = queue.claim_next(
            global_limit=global_limit,
            per_session_limit=per_session_limit,
            model_limits=dict(model_limits) if model_limits is not None else None,
            run_id=run_id,
        )
        if claimed is not None:
            # The claim has already set the job running durably; publish the
            # started event after that transition, before the worker runs it.
            _emit(
                on_event,
                JobEvent(claimed.job_id, run_id, claimed.parent_session, "running"),
            )
            thread = threading.Thread(
                target=_execute_job,
                args=(
                    queue,
                    state_dir,
                    harness,
                    run_id,
                    claimed,
                    payloads,
                    state,
                    on_event,
                ),
                daemon=True,  # jobs die with the host process by design
            )
            state.threads.append(thread)
            thread.start()
            continue
        with state.cond:
            state.cond.wait(_FALLBACK_WAIT)
    for thread in state.threads:
        thread.join()


def _execute_job(
    queue: JobQueue,
    state_dir: Path | str,
    harness: Harness,
    run_id: str,
    job: Job,
    payloads: Mapping[str, Sequence[str]],
    state: _Run,
    on_event: Callable[[JobEvent], None] | None = None,
) -> None:
    """Run one claimed job and record its outcome; always wakes the loop."""
    handle = harness.new_handle()
    with state.cond:
        state.handles[job.job_id] = handle
    timer: threading.Timer | None = None
    if job.hard_timeout is not None:
        # Dispatcher-owned hard timeout: terminate if execute has not
        # returned by the deadline (plugins may also enforce it internally).
        timer = threading.Timer(
            job.hard_timeout, _terminate_quietly, (harness, handle)
        )
        timer.daemon = True
        timer.start()
    try:
        argv = tuple(payloads.get(job.job_id, ()))
        if not argv:
            was_pending = _pending_ids(queue, run_id)
            _record(state_dir, run_id, job.job_id, "failed: no command payload", "")
            queue.complete_job(job.job_id, "failed")
            _emit(on_event, JobEvent(job.job_id, run_id, job.parent_session, "failed"))
            _emit_skipped(on_event, queue, run_id, was_pending)
            return
        budgets = Budgets(
            soft_timeout=job.soft_timeout,
            hard_timeout=job.hard_timeout,
            turn_limit=job.turn_limit,
        )
        outcome = harness.execute(
            CommandJob(job_id=job.job_id, argv=argv), budgets, handle
        )
        reason = SUCCEEDED if outcome.success else _failure_reason(outcome)
        was_pending = _pending_ids(queue, run_id) if not outcome.success else set()
        _record(state_dir, run_id, job.job_id, reason, outcome.output, outcome.error)
        status: Literal["succeeded", "failed"] = "succeeded" if outcome.success else "failed"
        queue.complete_job(job.job_id, status)
        _emit(on_event, JobEvent(job.job_id, run_id, job.parent_session, status))
        if status == "failed":
            _emit_skipped(on_event, queue, run_id, was_pending)
    except Exception as exc:  # noqa: BLE001 - worker must never die silently
        # Unexpected failure: record it and mark the job failed, never hang.
        with suppress(Exception):
            _record(state_dir, run_id, job.job_id, f"failed: {exc}", "")
        was_pending = _pending_ids(queue, run_id)
        with suppress(Exception):
            queue.complete_job(job.job_id, "failed")
        _emit(on_event, JobEvent(job.job_id, run_id, job.parent_session, "failed"))
        _emit_skipped(on_event, queue, run_id, was_pending)
    finally:
        with state.cond:
            state.handles.pop(job.job_id, None)
        if timer is not None:
            timer.cancel()
        state.wake()


def _terminate_quietly(harness: Harness, handle: object) -> None:
    try:
        harness.terminate(handle)
    except HarnessError:
        pass  # never started or already gone
