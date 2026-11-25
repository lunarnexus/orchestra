"""Connected dispatcher journeys: real queue, real shell subprocess, real artifacts."""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from orchestra.artifacts import Response, recall
from orchestra.dispatcher import JobEvent, run
from orchestra.harness import Budgets, CommandJob, Handle, Outcome
from orchestra.queue import Job, JobQueue
from orchestra.shell import ShellHarness

SESSION = "sess-main"


@pytest.fixture()
def queue(tmp_path: Path) -> Iterator[JobQueue]:
    q = JobQueue(tmp_path / "state.db")
    yield q
    q.close()


def _add(
    queue: JobQueue,
    run_id: str,
    prerequisites: tuple[str, ...] | list[str] = (),
    hard_timeout: int | None = None,
) -> Job:
    return queue.add_job(
        run_id=run_id,
        parent_session=SESSION,
        role="shell",
        model="sh",
        prerequisites=prerequisites,
        hard_timeout=hard_timeout,
    )


def _run(
    queue: JobQueue,
    tmp_path: Path,
    run_id: str,
    payloads: dict[str, list[str]],
    stop_event: threading.Event | None = None,
    on_event: object = None,
) -> None:
    run(
        queue,
        tmp_path / "state",
        ShellHarness(),
        run_id,
        global_limit=4,
        per_session_limit=4,
        payloads=payloads,
        stop_event=stop_event,
        on_event=on_event,  # type: ignore[arg-type]
    )


def _responses(tmp_path: Path, run_id: str) -> dict[str, str]:
    return {
        r.job_id: r.response
        for r in recall(tmp_path / "state", run_id)
        if isinstance(r, Response)
    }


def _wait_status(queue: JobQueue, job_id: str, status: str) -> None:
    for _ in range(500):
        if queue.get_job(job_id).status == status:
            return
        time.sleep(0.01)
    pytest.fail(f"job {job_id} never reached {status!r}")


def test_end_to_end_success_two_independent_jobs(
    queue: JobQueue, tmp_path: Path
) -> None:
    a = _add(queue, "r1")
    b = _add(queue, "r1")
    _run(queue, tmp_path, "r1", {a.job_id: ["true"], b.job_id: ["printf", "hello"]})

    assert queue.get_job(a.job_id).status == "succeeded"
    assert queue.get_job(b.job_id).status == "succeeded"
    responses = _responses(tmp_path, "r1")
    # The recorded response is the text the job actually returned; a job that
    # returned nothing records its status marker instead.
    assert responses == {a.job_id: "succeeded", b.job_id: "hello"}
    out_b = tmp_path / "state" / "artifacts" / "r1" / f"{b.job_id}.output"
    assert out_b.read_text() == "hello"
    out_a = tmp_path / "state" / "artifacts" / "r1" / f"{a.job_id}.output"
    assert not out_a.exists()  # no output -> no file


def test_dependency_verifier_runs_after_builder_succeeds(
    queue: JobQueue, tmp_path: Path
) -> None:
    builder = _add(queue, "r1")
    verifier = _add(queue, "r1", prerequisites=[builder.job_id])
    _run(
        queue,
        tmp_path,
        "r1",
        {builder.job_id: ["true"], verifier.job_id: ["true"]},
    )

    assert queue.get_job(builder.job_id).status == "succeeded"
    assert queue.get_job(verifier.job_id).status == "succeeded"
    assert _responses(tmp_path, "r1") == {
        builder.job_id: "succeeded",
        verifier.job_id: "succeeded",
    }
    # The verifier started only after the builder finished.
    builder_finished = datetime.fromisoformat(queue.get_job(builder.job_id).finished_at or "")
    verifier_started = datetime.fromisoformat(queue.get_job(verifier.job_id).started_at or "")
    assert builder_finished <= verifier_started


def test_failure_skips_dependents_and_records_once(
    queue: JobQueue, tmp_path: Path
) -> None:
    failing = _add(queue, "r1")
    dependent = _add(queue, "r1", prerequisites=[failing.job_id])
    _run(queue, tmp_path, "r1", {failing.job_id: ["sh", "-c", "echo boom; exit 3"]})

    assert queue.get_job(failing.job_id).status == "failed"
    assert queue.get_job(dependent.job_id).status == "skipped"
    responses = _responses(tmp_path, "r1")
    # Only the executed job has a response; the skipped one never ran.
    assert list(responses) == [failing.job_id]
    # A failure keeps its diagnostic reason first, then the output it produced
    # before failing, so the recorded answer is honest evidence, not a status.
    assert responses[failing.job_id] == "failed: exit status 3\n\nboom"
    out = tmp_path / "state" / "artifacts" / "r1" / f"{failing.job_id}.output"
    assert out.read_text() == "boom\n"
    record = next(
        r
        for r in recall(tmp_path / "state", "r1")
        if isinstance(r, Response) and r.job_id == failing.job_id
    )
    assert record.transcript == str(out)


def test_missing_command_payload_marks_failed_with_response(
    queue: JobQueue, tmp_path: Path
) -> None:
    """A job with no command payload fails loudly with a concise Response."""
    no_payload = _add(queue, "r1")
    _run(queue, tmp_path, "r1", {no_payload.job_id: []})

    assert queue.get_job(no_payload.job_id).status == "failed"
    responses = _responses(tmp_path, "r1")
    assert responses == {no_payload.job_id: "failed: no command payload"}


def test_parallelism_respects_global_limit(queue: JobQueue, tmp_path: Path) -> None:
    jobs = [_add(queue, "r1") for _ in range(5)]
    payloads = {job.job_id: ["sleep", "0.3"] for job in jobs}
    run(
        queue,
        tmp_path / "state",
        ShellHarness(),
        "r1",
        global_limit=2,
        per_session_limit=4,
        payloads=payloads,
    )

    resolved = [queue.get_job(job.job_id) for job in jobs]
    assert all(job.status == "succeeded" for job in resolved)
    # Reconstruct concurrency from real start/finish timestamps: at every
    # job's start moment, at most `global_limit` jobs were running.
    intervals = [
        (
            datetime.fromisoformat(job.started_at or ""),
            datetime.fromisoformat(job.finished_at or ""),
        )
        for job in resolved
    ]
    for start_i, end_i in intervals:
        concurrent = sum(
            1 for start_j, end_j in intervals if start_j <= start_i < end_j
        )
        assert concurrent <= 2


def test_hard_timeout_kills_process_group_full_stack(
    queue: JobQueue, tmp_path: Path
) -> None:
    runaway = _add(queue, "r1", hard_timeout=1)
    dependent = _add(queue, "r1", prerequisites=[runaway.job_id])
    pgid_file = tmp_path / "pgid.txt"
    payload = (
        "import os, subprocess;"
        f"open({str(pgid_file)!r}, 'w').write(str(os.getpgrp()));"
        "subprocess.run(['sleep', '30'])"
    )
    _run(queue, tmp_path, "r1", {runaway.job_id: ["python3", "-c", payload]})

    assert queue.get_job(runaway.job_id).status == "failed"
    assert queue.get_job(dependent.job_id).status == "skipped"
    responses = _responses(tmp_path, "r1")
    assert responses[runaway.job_id] == (
        "failed: terminated (hard timeout or cancellation)"
    )
    assert list(responses) == [runaway.job_id]
    pgid = int(pgid_file.read_text())
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        pass
    else:
        pytest.fail(f"process group {pgid} is still alive")


def test_stop_terminates_running_and_fails_them(
    queue: JobQueue, tmp_path: Path
) -> None:
    running = _add(queue, "r1")
    never_claimed = _add(queue, "r1")
    dependent = _add(queue, "r1", prerequisites=[running.job_id])
    stop_event = threading.Event()
    worker = threading.Thread(
        target=run,
        args=(
            queue,
            tmp_path / "state",
            ShellHarness(),
            "r1",
        ),
        kwargs={
            "global_limit": 1,
            "per_session_limit": 1,
            "payloads": {running.job_id: ["sleep", "10"]},
            "stop_event": stop_event,
        },
    )
    worker.start()
    _wait_status(queue, running.job_id, "running")
    stop_event.set()
    worker.join(timeout=15)

    assert not worker.is_alive()
    assert queue.get_job(running.job_id).status == "failed"
    # With global_limit=1 the second job was never claimed: stop leaves
    # pending work pending. The failed job's dependent is skipped by the
    # queue's normal failure handling.
    assert queue.get_job(never_claimed.job_id).status == "pending"
    assert queue.get_job(dependent.job_id).status == "skipped"
    responses = _responses(tmp_path, "r1")
    assert list(responses) == [running.job_id]
    assert responses[running.job_id] == (
        "failed: terminated (hard timeout or cancellation)"
    )


def test_dispatch_registers_dispatch_and_execution_identity(
    queue: JobQueue, tmp_path: Path
) -> None:
    # A launched job records its owning dispatcher token at claim time and its
    # execution-group identity immediately after launch, so a later dispatcher
    # loss can be reconciled against a durable record.
    slow = _add(queue, "r1")
    thread = threading.Thread(
        target=run,
        args=(queue, tmp_path / "state", ShellHarness(), "r1"),
        kwargs={
            "global_limit": 1,
            "per_session_limit": 1,
            "payloads": {slow.job_id: ["sleep", "5"]},
            "dispatcher_token": "tok-xyz",
        },
    )
    thread.start()
    try:
        _wait_status(queue, slow.job_id, "running")
        for _ in range(500):
            job = queue.get_job(slow.job_id)
            if job.child_pgid is not None:
                break
            time.sleep(0.01)
        job = queue.get_job(slow.job_id)
        assert job.dispatcher_token == "tok-xyz"
        assert job.child_pgid is not None
        assert job.child_start is not None
    finally:
        harness_pgid = queue.get_job(slow.job_id).child_pgid
        if harness_pgid is not None:
            import os

            try:
                os.killpg(harness_pgid, 9)
            except ProcessLookupError:
                pass
        thread.join(timeout=10)


def test_registration_failure_terminates_and_fails_untracked_launch(
    queue: JobQueue, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A launched child whose execution identity cannot be durably registered
    # would run unowned and could outlive this dispatcher with nothing left to
    # terminate it. The dispatcher must fail closed: surface a visible error,
    # mark the job failed, and leave no orphaned running group.
    slow = _add(queue, "r1")
    launched: list[int] = []

    def boom(job_id: str, *, pgid: int, child_start: float | None) -> None:
        launched.append(pgid)
        raise RuntimeError("injected queue registration failure")

    monkeypatch.setattr(queue, "register_execution", boom)
    _run(queue, tmp_path, "r1", {slow.job_id: ["sleep", "5"]})

    # The injected failure really fired against a real launched child.
    assert launched, "launch registration callback never ran"
    pgid = launched[0]

    # The job failed with a visible registration error through the evidence path.
    assert queue.get_job(slow.job_id).status == "failed"
    responses = _responses(tmp_path, "r1")
    assert list(responses) == [slow.job_id]  # recorded exactly once
    assert "execution registration failed" in responses[slow.job_id]

    # No orphan: the launched process group was terminated, not left running.
    for _ in range(200):
        try:
            reaped, _status = os.waitpid(pgid, os.WNOHANG)
        except ChildProcessError:
            break  # already gone
        if reaped == pgid:
            break  # terminated and reaped here
        time.sleep(0.01)
    else:
        pytest.fail(f"launched group {pgid} still running after failed registration")


class _BadSetupHarness:
    """Harness whose handle rejects dispatcher setup (mirrors a bare object)."""

    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute(
        self, job: CommandJob, budgets: Budgets, handle: Handle | None = None
    ) -> Outcome:
        self.executed.append(job.job_id)  # must never be reached
        raise AssertionError("execute must not run when handle setup fails")

    def new_handle(self) -> Handle:
        return object()  # type: ignore[return-value]  # no __dict__: on_launch raises

    def request_wrap_up(self, handle: Handle) -> None:
        return None

    def terminate(self, handle: Handle) -> None:
        return None


def test_failing_handle_setup_yields_durable_failure_and_run_returns(
    queue: JobQueue, tmp_path: Path
) -> None:
    """A handle that rejects setup must fail durably, never hang the run.

    Regression for the fan-in hang: ``handle.on_launch`` wiring once ran
    outside the worker's try/finally, so a handle rejecting the assignment
    killed the thread before the terminal state/wake, leaving the job stuck in
    "running" and the dispatch loop spinning forever. Setup must instead record
    a durable failure and wake the loop.
    """
    job = _add(queue, "r1")
    harness = _BadSetupHarness()

    thread = threading.Thread(
        target=lambda: run(
            queue,
            tmp_path / "state",
            harness,
            "r1",
            global_limit=1,
            per_session_limit=1,
            payloads={job.job_id: ["true"]},
        ),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=10)  # bounded: the guarded-setup fix makes run() return
    assert not thread.is_alive(), (
        "run() hung: worker died on handle setup without waking the loop"
    )

    # Setup failed before execute, so the command never launched.
    assert harness.executed == []
    # The failure is durable and visible through the evidence path, not a
    # silent thread death leaving the job stuck in "running".
    assert queue.get_job(job.job_id).status == "failed"
    responses = _responses(tmp_path, "r1")
    assert list(responses) == [job.job_id]  # recorded exactly once
    assert "on_launch" in responses[job.job_id]


def test_loop_exits_and_second_run_returns_promptly(
    queue: JobQueue, tmp_path: Path
) -> None:
    _run(queue, tmp_path, "r1", {})  # no jobs at all
    job = _add(queue, "r1")
    _run(queue, tmp_path, "r1", {job.job_id: ["true"]})
    # All jobs terminal: a second run returns promptly without re-executing.
    _run(queue, tmp_path, "r1", {job.job_id: ["true"]})
    responses = _responses(tmp_path, "r1")
    assert list(responses) == [job.job_id]  # recorded exactly once


def test_stderr_is_separated_from_answer_body(queue: JobQueue, tmp_path: Path) -> None:
    """A stderr line must never splice onto the end of the child's answer.

    Regression: the dispatcher recorded ``output + error`` with no delimiter,
    so a benign harness startup warning appended directly after the last
    answer line in the delivered response/transcript body.
    """
    job = _add(queue, "r1")
    # Answer has no trailing newline; stderr is a distinct warning line.
    payload = [
        "sh",
        "-c",
        "printf 'the final answer'; printf 'Warning: No project session found; creating a new session.\\n' 1>&2",
    ]
    _run(queue, tmp_path, "r1", {job.job_id: payload})

    assert queue.get_job(job.job_id).status == "succeeded"
    out = tmp_path / "state" / "artifacts" / "r1" / f"{job.job_id}.output"
    body = out.read_text()
    # The stderr warning must not be spliced directly onto the answer text.
    assert "the final answerWarning" not in body
    # The answer stands alone as the leading response body.
    assert body.split("\n")[0] == "the final answer"
    # Stderr is preserved, but in a separately labeled diagnostic section.
    assert "Warning: No project session found; creating a new session." in body
    assert "[stderr]" in body


def test_large_output_captured_byte_exact_record_stays_small(
    queue: JobQueue, tmp_path: Path
) -> None:
    job = _add(queue, "r1")
    payload = ["python3", "-c", "import sys; sys.stdout.write('x' * 100_000)"]
    _run(queue, tmp_path, "r1", {job.job_id: payload})

    out = tmp_path / "state" / "artifacts" / "r1" / f"{job.job_id}.output"
    assert out.read_bytes() == b"x" * 100_000
    jsonl = tmp_path / "state" / "artifacts" / "r1.jsonl"
    responses = [
        json.loads(line)
        for line in jsonl.read_text().splitlines()
        if line.strip() and json.loads(line)["record_type"] == "response"
    ]
    assert len(responses) == 1
    response = responses[0]
    assert response["response"] == "succeeded"
    assert response["transcript"] == str(out)
    assert len(json.dumps(response)) < 500


def test_events_report_started_then_terminal_after_durable_state(
    queue: JobQueue, tmp_path: Path
) -> None:
    """One job emits started then terminal, each after durable queue state."""
    job = _add(queue, "r1")
    events: list[JobEvent] = []
    statuses_at_emit: list[str] = []

    def on_event(event: JobEvent) -> None:
        # The durable status observed at emit time must already match the
        # event: started is published only once the claim set the job running,
        # terminal only once the queue records the final status.
        statuses_at_emit.append(queue.get_job(event.job_id).status)
        events.append(event)

    _run(queue, tmp_path, "r1", {job.job_id: ["true"]}, on_event=on_event)

    assert [(e.job_id, e.status) for e in events] == [
        (job.job_id, "running"),
        (job.job_id, "succeeded"),
    ]
    assert all(e.run_id == "r1" and e.session_id == SESSION for e in events)
    # Each event's status matched the already-persisted queue status.
    assert statuses_at_emit == ["running", "succeeded"]


def test_events_report_verifier_started_only_after_builder_terminal(
    queue: JobQueue, tmp_path: Path
) -> None:
    """A follow-up verifier's started event follows the builder's terminal one."""
    builder = _add(queue, "r1")
    verifier = _add(queue, "r1", prerequisites=[builder.job_id])
    events: list[tuple[str, str]] = []
    lock = threading.Lock()

    def on_event(event: JobEvent) -> None:
        with lock:
            events.append((event.job_id, event.status))

    _run(
        queue,
        tmp_path,
        "r1",
        {builder.job_id: ["true"], verifier.job_id: ["true"]},
        on_event=on_event,
    )

    assert events == [
        (builder.job_id, "running"),
        (builder.job_id, "succeeded"),
        (verifier.job_id, "running"),
        (verifier.job_id, "succeeded"),
    ]


def test_events_report_skipped_dependent_after_failure(
    queue: JobQueue, tmp_path: Path
) -> None:
    """A failure is reported terminal, then the dependent it skips."""
    failing = _add(queue, "r1")
    dependent = _add(queue, "r1", prerequisites=[failing.job_id])
    events: list[tuple[str, str]] = []

    def on_event(event: JobEvent) -> None:
        events.append((event.job_id, event.status))

    _run(
        queue,
        tmp_path,
        "r1",
        {failing.job_id: ["sh", "-c", "exit 3"]},
        on_event=on_event,
    )

    # The skipped dependent is reported once, after the failure, and its
    # durable skip has already been written by the time the event fires.
    assert (dependent.job_id, "skipped") in events
    assert [s for j, s in events if j == failing.job_id] == ["running", "failed"]
    assert events.index((dependent.job_id, "skipped")) > events.index(
        (failing.job_id, "failed")
    )
    # A never-running skipped dependent has no started event of its own.
    assert (dependent.job_id, "running") not in events


def test_raising_event_callback_never_fails_a_successful_job(
    queue: JobQueue, tmp_path: Path
) -> None:
    """A callback that always raises cannot turn success into failure."""
    job = _add(queue, "r1")

    def on_event(event: JobEvent) -> None:
        raise RuntimeError("ui exploded")

    _run(queue, tmp_path, "r1", {job.job_id: ["printf", "ok"]}, on_event=on_event)

    assert queue.get_job(job.job_id).status == "succeeded"
    assert _responses(tmp_path, "r1") == {job.job_id: "ok"}
