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
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from orchestra.artifacts import Response, append, recall
from orchestra.harness import Budgets, CommandJob, Harness, HarnessError, Outcome
from orchestra.queue import Job, JobQueue

_TERMINAL = frozenset({"succeeded", "failed", "skipped"})
# Maximum seconds the loop sleeps when nothing can be claimed; a completion
# signal wakes it earlier. Covers the prerequisite-release edge where no
# worker is running to notify.
_FALLBACK_WAIT = 0.25


def _now() -> str:
    return datetime.now(UTC).isoformat()


def recorded_reasons(state_dir: Path | str, run_id: str) -> dict[str, str]:
    """Read-only accessor: job_id -> recorded outcome reason for a run.

    Reads the run's recorded Response artifacts; guidance consumes this
    mapping via ``derive_return_category``.
    """
    return {
        record.job_id: record.response
        for record in recall(state_dir, run_id)
        if isinstance(record, Response)
    }


def _output_path(state_dir: Path | str, run_id: str, job_id: str) -> Path:
    return Path(state_dir) / "artifacts" / run_id / f"{job_id}.output"


def _failure_reason(outcome: Outcome) -> str:
    if outcome.terminated:
        return "failed: terminated (hard timeout or cancellation)"
    return f"failed: exit status {outcome.exit_status}"


def _record(
    state_dir: Path | str,
    run_id: str,
    job_id: str,
    reason: str,
    combined_output: str,
) -> str | None:
    """Write one output file when there is output, append one Response."""
    transcript: str | None = None
    if combined_output:
        path = _output_path(state_dir, run_id, job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(combined_output, encoding="utf-8")
        transcript = str(path)
    append(
        state_dir,
        run_id,
        Response(job_id=job_id, timestamp=_now(), response=reason, transcript=transcript),
    )
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
) -> None:
    """Execute every queued job of ``run_id`` to a terminal state.

    Claims eligible jobs (limits are passed straight to the queue), runs
    each claimed job in its own worker thread through ``harness``, records
    one minimal Response per executed job, and updates the queue so
    dependents release or are skipped. Returns once all jobs of the run
    are terminal, or immediately when the run has no jobs.

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
            thread = threading.Thread(
                target=_execute_job,
                args=(queue, state_dir, harness, run_id, claimed, payloads, state),
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
            _record(state_dir, run_id, job.job_id, "failed: no command payload", "")
            queue.complete_job(job.job_id, "failed")
            return
        budgets = Budgets(
            soft_timeout=job.soft_timeout,
            hard_timeout=job.hard_timeout,
            turn_limit=job.turn_limit,
        )
        outcome = harness.execute(
            CommandJob(job_id=job.job_id, argv=argv), budgets, handle
        )
        combined = outcome.output + outcome.error
        reason = "succeeded" if outcome.success else _failure_reason(outcome)
        _record(state_dir, run_id, job.job_id, reason, combined)
        queue.complete_job(job.job_id, "succeeded" if outcome.success else "failed")
    except Exception as exc:  # noqa: BLE001 - worker must never die silently
        # Unexpected failure: record it and mark the job failed, never hang.
        with suppress(Exception):
            _record(state_dir, run_id, job.job_id, f"failed: {exc}", "")
        with suppress(Exception):
            queue.complete_job(job.job_id, "failed")
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
