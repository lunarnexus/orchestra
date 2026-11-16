"""Behavior tests for Orchestra 2 status data and rendering."""

from __future__ import annotations

from pathlib import Path

from orchestra.queue import Job, JobQueue
from orchestra.status import (
    LastCompleted,
    StatusData,
    StatusEntry,
    StatusError,
    render_status,
    status,
)


def make_queue(tmp_path: Path) -> JobQueue:
    return JobQueue(tmp_path / "jobs.sqlite")


def add(
    queue: JobQueue,
    run_id: str = "runA",
    parent_session: str = "sess1",
    role: str = "builder",
    prerequisites: tuple[str, ...] = (),
) -> Job:
    return queue.add_job(
        run_id=run_id,
        parent_session=parent_session,
        role=role,
        model="m1",
        prerequisites=prerequisites,
    )


def test_status_rejects_invalid_input_types(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    try:
        status("not-a-queue", "sess")  # type: ignore[arg-type]
        raise AssertionError("expected StatusError")
    except StatusError:
        pass
    try:
        status(queue, 42)  # type: ignore[arg-type]
        raise AssertionError("expected StatusError")
    except StatusError:
        pass
    queue.close()


def test_empty_session_and_queue(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    data = status(queue, "sess1")
    assert isinstance(data, StatusData)
    assert data.session_jobs == ()
    assert data.global_running == 0
    assert data.global_pending == 0
    assert data.last_completed is None
    out = render_status(data, "on")
    assert out == "Orchestra: on\n\nThis session: no active jobs.\n\nGlobal: 0 running, 0 pending\n"
    assert "Last completed" not in out
    queue.close()


def test_running_and_pending_chain_with_waiting_on(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    first = add(queue, role="builder")
    queue.claim_next(global_limit=4, per_session_limit=4)
    add(queue, role="verifier", prerequisites=(str(first.job_id),))
    data = status(queue, "sess1")
    assert data.global_running == 1
    assert data.global_pending == 1
    assert data.last_completed is None
    assert len(data.session_jobs) == 2
    running_entry = data.session_jobs[0]
    assert isinstance(running_entry, StatusEntry)
    assert (running_entry.sequence, running_entry.role, running_entry.status) == (
        1,
        "builder",
        "running",
    )
    assert running_entry.waiting_on == ()
    pending_entry = data.session_jobs[1]
    assert (pending_entry.sequence, pending_entry.role, pending_entry.status) == (
        2,
        "verifier",
        "pending",
    )
    assert pending_entry.waiting_on == (str(first.job_id),)
    out = render_status(data, "on")
    assert "Orchestra: on" in out
    assert "#1" in out and "builder" in out and "running" in out
    assert "#2" in out and "verifier" in out and "pending" in out
    assert "(waiting on #1)" in out
    assert "run runA" in out
    queue.close()


def test_skipped_dependent_and_skipped_tally_in_last_completed(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    first = add(queue, role="builder")
    second = add(queue, role="verifier", prerequisites=(str(first.job_id),))
    queue.claim_next(global_limit=4, per_session_limit=4)
    queue.complete_job(str(first.job_id), "failed")
    skipped = queue.get_job(str(second.job_id))
    assert skipped.status == "skipped"
    data = status(queue, "sess1")
    assert data.session_jobs == ()
    assert data.last_completed is not None
    assert data.last_completed == LastCompleted(
        run_id="runA", succeeded=0, failed=1, skipped=1
    )
    out = render_status(data, "on")
    assert "Last completed: run runA — 0 succeeded, 1 failed, 1 skipped" in out
    queue.close()


def test_global_counts_include_other_sessions_without_detail(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    add(queue, run_id="runA", parent_session="other1")
    add(queue, run_id="runB", parent_session="other2")
    queue.claim_next(global_limit=4, per_session_limit=4)  # claims one of the others
    data = status(queue, "sess1")
    assert data.session_jobs == ()
    assert data.global_running == 1
    assert data.global_pending == 1
    out = render_status(data, "on")
    assert "Global: 1 running, 1 pending" in out
    assert "other" not in out
    queue.close()


def test_last_completed_picks_most_recent_finished_run(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    old = add(queue, run_id="runOld")
    queue.claim_next(global_limit=4, per_session_limit=4)
    queue.complete_job(str(old.job_id), "succeeded")
    newer = add(queue, run_id="runNew", role="reviewer")
    queue.claim_next(global_limit=4, per_session_limit=4)
    queue.complete_job(str(newer.job_id), "failed")
    data = status(queue, "sess1")
    assert data.last_completed is not None
    assert data.last_completed.run_id == "runNew"
    assert data.last_completed == LastCompleted(
        run_id="runNew", succeeded=0, failed=1, skipped=0
    )
    out = render_status(data, "on")
    assert "run runNew" in out
    assert "run runOld" not in out
    queue.close()


def test_render_status_is_deterministic_and_has_mode_line(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    first = add(queue)
    queue.claim_next(global_limit=4, per_session_limit=4)
    add(queue, role="verifier", prerequisites=(str(first.job_id),))
    data = status(queue, "sess1")
    first_out = render_status(data, "manual")
    assert render_status(data, "manual") == first_out
    assert first_out.startswith("Orchestra: manual\n")
    for token in ("sess1", "+00:00", "202"):
        assert token not in first_out
    queue.close()


def test_data_usable_without_render(tmp_path: Path) -> None:
    queue = make_queue(tmp_path)
    first = add(queue)
    queue.claim_next(global_limit=4, per_session_limit=4)
    second = add(queue, role="verifier", prerequisites=(str(first.job_id),))
    add(queue, role="reviewer", prerequisites=(str(second.job_id),))
    data = status(queue, "sess1")
    assert [entry.sequence for entry in data.session_jobs] == [1, 2, 3]
    assert data.session_jobs[1].waiting_on == (str(first.job_id),)
    assert data.session_jobs[2].waiting_on == (str(second.job_id),)
    assert data.session_jobs[0].run_id == "runA"
    assert data.global_running == 1
    assert data.global_pending == 2
    assert data.last_completed is None
    queue.close()
