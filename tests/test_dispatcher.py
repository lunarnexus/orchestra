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
