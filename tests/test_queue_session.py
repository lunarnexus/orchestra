"""Queue-owned runtime session membership: admission, snapshot, reporting.

Slice 1 owns the queue contract for one attached core session: an idempotent
session open that baselines already-terminal history, in-flight admission
tracking (before any DB insert), one authoritative pure-read snapshot, and
report acknowledgement validated only after a real native success.

Admission/report membership is in-memory runtime state owned by the single
core session process; the job rows are the cross-process durable truth. These
tests use real SQLite (including two connections on one database) to prove the
snapshot reads committed rows from another writer while admissions block
readiness without any new row.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestra.queue import (
    TERMINAL_STATUSES,
    JobQueue,
    QueueError,
    SessionSnapshot,
)


def _add(queue: JobQueue, run_id: str, parent_session: str = "s1") -> str:
    return queue.add_job(
        run_id=run_id, parent_session=parent_session, role="builder", model="m"
    ).job_id


def _run_to_terminal(queue: JobQueue, run_id: str, parent_session: str = "s1") -> None:
    # Seed one owned job when the run is empty, then drain every ready job to a
    # durable succeeded outcome (resolving prerequisite/follow-up chains).
    owned = [job for job in queue.list_jobs(run_id) if job.parent_session == parent_session]
    if not owned:
        queue.add_job(
            run_id=run_id, parent_session=parent_session, role="builder", model="m"
        )
    while True:
        job = queue.claim_next(global_limit=5, per_session_limit=5, run_id=run_id)
        if job is None:
            break
        queue.complete_job(job.job_id, "succeeded")


# --- terminal classification ------------------------------------------------


def test_terminal_classification_is_queue_owned_public(tmp_path: Path) -> None:
    # A single reused public classification so callers stop repeating sets.
    assert TERMINAL_STATUSES == frozenset({"succeeded", "failed", "skipped"})
    queue = JobQueue(tmp_path / "jobs.sqlite")
    jid = _add(queue, "r1")
    assert queue.get_job(jid).is_terminal is False
    queue.claim_next(global_limit=5, per_session_limit=5)
    queue.complete_job(jid, "succeeded")
    assert queue.get_job(jid).is_terminal is True
    queue.close()


# --- open / idempotency -----------------------------------------------------


def test_open_session_is_idempotent_and_keeps_receipts(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "jobs.sqlite")
    queue.open_session("s1")
    _run_to_terminal(queue, "r1")
    # Baseline is empty because r1 became terminal only after open.
    queue.acknowledge_report("s1", ["r1"])
    # Re-opening must not erase the report receipt or reset the baseline.
    queue.open_session("s1")
    snap = queue.snapshot("s1")
    assert "r1" in snap.reported_run_ids
    queue.close()


def test_terminal_history_baselined_at_open_is_not_replayed(tmp_path: Path) -> None:
    # Seed a terminal run BEFORE open so it is history, then open.
    seed = JobQueue(tmp_path / "jobs.sqlite")
    _run_to_terminal(seed, "old")
    seed.close()

    queue = JobQueue(tmp_path / "jobs.sqlite")
    queue.open_session("s1")
    snap = queue.snapshot("s1")
    assert "old" in snap.baseline_run_ids
    assert "old" not in snap.ready_run_ids
    assert snap.ready is False  # no replay of already-terminal history
    queue.close()


def test_snapshot_is_pure_read_without_opening_session(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "jobs.sqlite")
    _run_to_terminal(queue, "r1")
    # A pure snapshot must serve status/Results facts without opening a session
    # or resetting any baseline: it must not create session state.
    snap = queue.snapshot("s1")
    assert isinstance(snap, SessionSnapshot)
    assert snap.parent_session == "s1"
    assert snap.ready is True
    assert snap.ready_run_ids == ("r1",)
    # Opening afterwards must then baseline the now-terminal run as history.
    queue.open_session("s1")
    assert "r1" in queue.snapshot("s1").baseline_run_ids
    queue.close()


# --- admissions block readiness --------------------------------------------


def test_runtime_actions_require_opened_session(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "jobs.sqlite")
    with pytest.raises(QueueError):
        queue.begin_submission("nope", "req1")
    with pytest.raises(QueueError):
        queue.finish_submission("nope", "req1")
    with pytest.raises(QueueError):
        queue.acknowledge_report("nope", ["r1"])
    queue.close()


def test_open_admission_stops_ready_even_with_no_new_rows(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "jobs.sqlite")
    _run_to_terminal(queue, "r1")
    assert queue.snapshot("s1").ready is True
    queue.open_session("s1")  # baselines r1 as history -> no replay
    # r1 is history; nothing else outstanding, so session would otherwise idle.
    # An open admission (pre-DB request still crossing the boundary) keeps it
    # not-ready even though it adds zero job rows.
    queue.begin_submission("s1", "req-open")
    snap = queue.snapshot("s1")
    assert snap.open_admissions == ("req-open",)
    assert snap.active is True
    assert snap.ready is False
    queue.close()


def test_rejected_admission_releases_ready(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "jobs.sqlite")
    _run_to_terminal(queue, "r1")
    queue.open_session("s1")  # r1 baselined as history
    # Add a genuinely eligible NEW run that is not baseline/reported.
    _run_to_terminal(queue, "r2")
    assert queue.snapshot("s1").ready is True
    queue.begin_submission("s1", "req2")
    assert queue.snapshot("s1").ready is False
    # Definite submission failure / process closure releases the admission.
    queue.finish_submission("s1", "req2")
    snap = queue.snapshot("s1")
    assert snap.open_admissions == ()
    assert snap.ready is True
    queue.close()


def test_automatic_followup_terminal_blocks_readiness(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "jobs.sqlite")
    queue.open_session("s1")
    builder = _add(queue, "r1")
    _run_to_terminal(queue, "r1")  # builder succeeded
    # Submit's automatic verification follow-up depends on the builder.
    queue.add_job(
        run_id="r1",
        parent_session="s1",
        role="verifier",
        model="m",
        prerequisites=(builder,),
    )
    mid = queue.snapshot("s1")
    assert mid.ready is False  # follow-up pending blocks the report
    assert "r1" not in mid.ready_run_ids
    _run_to_terminal(queue, "r1")  # verifier reaches terminal
    assert queue.snapshot("s1").ready is True
    assert queue.snapshot("s1").ready_run_ids == ("r1",)
    queue.close()


# --- report acknowledgement -------------------------------------------------


def test_empty_selection_is_not_ready(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "jobs.sqlite")
    queue.open_session("s1")
    # No owned jobs at all -> empty report selection is never "ready".
    snap = queue.snapshot("s1")
    assert snap.ready_run_ids == ()
    assert snap.ready is False
    queue.close()


def test_acknowledge_report_records_membership_and_is_idempotent(
    tmp_path: Path,
) -> None:
    queue = JobQueue(tmp_path / "jobs.sqlite")
    queue.open_session("s1")
    _run_to_terminal(queue, "r1")
    queue.acknowledge_report("s1", ["r1"])
    queue.acknowledge_report("s1", ["r1"])  # repeated ack is harmless
    snap = queue.snapshot("s1")
    assert "r1" in snap.reported_run_ids
    assert "r1" not in snap.ready_run_ids  # reported -> no re-delivery
    queue.close()


def test_acknowledge_rejects_foreign_and_non_terminal(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "jobs.sqlite")
    queue.open_session("s1")
    # A foreign session's terminal run must not be ackable by s1.
    _run_to_terminal(queue, "foreign", parent_session="other")
    with pytest.raises(QueueError):
        queue.acknowledge_report("s1", ["foreign"])
    # An unknown run is rejected too.
    with pytest.raises(QueueError):
        queue.acknowledge_report("s1", ["ghost"])
    # A non-terminal owned run cannot be acknowledged.
    _add(queue, "active")
    with pytest.raises(QueueError):
        queue.acknowledge_report("s1", ["active"])
    queue.close()


def test_acknowledge_after_new_admission_does_not_require_idle(
    tmp_path: Path,
) -> None:
    # A report chosen while idle stays valid even if a NEW job is admitted
    # before the native ack arrives: validate selected-run terminality/ownership
    # only, not whole-session idleness at receipt time.
    queue = JobQueue(tmp_path / "jobs.sqlite")
    queue.open_session("s1")
    _run_to_terminal(queue, "r1")
    # New work admitted after the report was selected (still crossing the
    # boundary), so the session is no longer idle.
    queue.begin_submission("s1", "req-new")
    snap = queue.snapshot("s1")
    assert snap.ready is False  # admission blocks new selection
    # The already-selected r1 report can still be acknowledged on native success.
    queue.acknowledge_report("s1", ["r1"])
    assert "r1" in queue.snapshot("s1").reported_run_ids
    queue.close()


# --- real SQLite, two connections ------------------------------------------


def test_two_connection_snapshot_reads_committed_rows(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite"
    conn_a = JobQueue(path)  # the core session-owning connection
    conn_b = JobQueue(path)  # an independent writer (e.g. dispatcher/submit)

    conn_a.open_session("s1")
    # conn_b inserts and completes a run; conn_a must see it via real SQLite.
    _run_to_terminal(conn_b, "r1")
    snap = conn_a.snapshot("s1")
    assert snap.terminal == 1
    assert snap.ready_run_ids == ("r1",)
    assert snap.ready is True

    # An admission is in-memory per owning connection: conn_a admits a request,
    # its readiness blocks with zero new rows, and conn_b is unaffected.
    conn_a.begin_submission("s1", "req-inflight")
    assert conn_a.snapshot("s1").ready is False
    assert conn_b.snapshot("s1").ready is True
    conn_a.close()
    conn_b.close()
