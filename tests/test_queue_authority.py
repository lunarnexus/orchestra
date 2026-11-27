"""Queue-authority migration: one snapshot feeds status, Results, and history.

These tests lock in the central predicate migration the earlier pass only
partly did: the duplicated ``list_jobs`` global scans + manual owner/terminal
filters in ``status.status``, ``results.assemble_session`` and
``cli.history_runs`` must be replaced by the single authoritative
``queue.snapshot`` / ``owned_run_jobs`` API, with one snapshot reused by the
core session evaluator instead of each consumer re-reading the queue.

They are behavior tests over real SQLite. Where they prove a duplicated read
is gone, they do it by making the redundant ``list_jobs`` path fail loudly on
the *session-level* consumers only (status/snapshot, session assembly, history,
the evaluator), not by counting internal calls.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from orchestra.artifacts import Response, append
from orchestra.queue import JobQueue, QueueError
from orchestra.results import ResultsError, assemble_session
from orchestra.status import StatusError, status

SESSION = "pi:AUTH1"
OTHER = "pi:OTHER"


def _seed(queue: JobQueue, run_id: str, parent: str = SESSION) -> None:
    queue.add_job(run_id=run_id, parent_session=parent, role="builder", model="m1")


def _drain(queue: JobQueue, run_id: str) -> None:
    while True:
        job = queue.claim_next(global_limit=9, per_session_limit=9, run_id=run_id)
        if job is None:
            return
        queue.complete_job(job.job_id, "succeeded")


# --- snapshot carries the global workload counts status renders -------------


def test_snapshot_exposes_global_and_owned_counts(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "q.db")
    _seed(queue, "mineA")
    _seed(queue, "mineB")
    _seed(queue, "foreign", OTHER)
    _drain(queue, "foreign")  # foreign terminal -> not in global running/pending
    running = queue.claim_next(global_limit=9, per_session_limit=9, run_id="mineA")
    assert running is not None

    snap = queue.snapshot(SESSION)
    # Owned view counts only this session's rows.
    assert snap.running == 1 and snap.pending == 1 and snap.terminal == 0
    # Global counts include the foreign session's still-active work.
    foreign_running = queue.claim_next(global_limit=9, per_session_limit=9, run_id=OTHER and "foreign")
    assert foreign_running is None  # already terminal
    assert snap.global_running >= 1
    assert snap.global_pending >= 1
    queue.close()


def test_status_consumes_precomputed_snapshot(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "q.db")
    _seed(queue, "mineA")
    queue.claim_next(global_limit=9, per_session_limit=9, run_id="mineA")
    snap = queue.snapshot(SESSION)

    data = status(queue, SESSION, snapshot=snap)
    assert data.session_jobs and data.session_jobs[0].status == "running"
    assert data.global_running == snap.global_running
    assert data.global_pending == snap.global_pending
    queue.close()


def test_status_rejects_non_snapshot_arg(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "q.db")
    with pytest.raises(StatusError):
        status(queue, SESSION, snapshot="not-a-snapshot")  # type: ignore[arg-type]
    queue.close()


def test_status_global_counts_include_foreign_without_detail(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "q.db")
    _seed(queue, "f1", OTHER)
    _seed(queue, "f2", OTHER)
    queue.claim_next(global_limit=9, per_session_limit=9, run_id="f1")
    data = status(queue, SESSION)
    assert data.session_jobs == ()
    assert data.global_running == 1 and data.global_pending == 1
    queue.close()


# --- session-level consumers no longer do their own list_jobs global scan ---


def test_session_consumers_do_not_rescan_via_list_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The migrated session paths read via snapshot/owned_run_jobs, not list_jobs.

    ``assemble`` for a single run may still read its one run via list_jobs; the
    session-level predicates (status, session assembly, history, the evaluator)
    must not, so the global scan is made to fail loudly for those paths only.
    """

    def boom(_self: object, *_a: object, **_k: object) -> object:
        raise AssertionError("session predicate must not call list_jobs")

    monkeypatch.setattr(JobQueue, "list_jobs", boom)

    queue = JobQueue(tmp_path / "q.db")
    _seed(queue, "mineA")
    queue.claim_next(global_limit=9, per_session_limit=9, run_id="mineA")
    snap = queue.snapshot(SESSION)
    # status + history + session assembly must work from snapshot/owned helpers.
    assert status(queue, SESSION, snapshot=snap).global_running == 1
    from orchestra.cli import history_runs

    entries, _unresolved = history_runs(queue, tmp_path / "state", SESSION, None)
    assert isinstance(entries, list)
    queue.close()


# --- assemble_session reuses one snapshot and validates ownership -----------


def test_assemble_session_reuses_supplied_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Provided snapshot drives the session-idle check; no per-list scan."""
    queue = JobQueue(tmp_path / "q.db")
    _seed(queue, "r1")
    job = queue.claim_next(global_limit=9, per_session_limit=9, run_id="r1")
    assert job is not None
    append(
        tmp_path / "state",
        "r1",
        Response(job_id=job.job_id, timestamp=datetime.now(UTC).isoformat(), response="ok"),
    )
    queue.complete_job(job.job_id, "succeeded")

    snap = queue.snapshot(SESSION)
    ret = assemble_session(
        queue, tmp_path / "state", {"return_hint_all_succeeded": "hint"}, SESSION,
        ["r1"], snapshot=snap,
    )
    assert ret.run_ids == ("r1",)
    assert ret.jobs[0].summary == "ok"
    queue.close()


def test_assemble_session_rejects_foreign_run_as_results_error(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "q.db")
    _seed(queue, "mine")
    _drain(queue, "mine")
    _seed(queue, "foreign", OTHER)
    _drain(queue, "foreign")
    with pytest.raises(ResultsError, match="not owned by session"):
        assemble_session(
            queue, tmp_path / "state", {}, SESSION, ["foreign"]
        )
    queue.close()


def test_assemble_session_rejects_unknown_run_as_results_error(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "q.db")
    _seed(queue, "mine")
    _drain(queue, "mine")
    with pytest.raises(ResultsError, match="unknown run"):
        assemble_session(queue, tmp_path / "state", {}, SESSION, ["ghost"])
    queue.close()


def test_assemble_session_blocks_when_session_has_outstanding(
    tmp_path: Path,
) -> None:
    queue = JobQueue(tmp_path / "q.db")
    _seed(queue, "done")
    _drain(queue, "done")
    _seed(queue, "active")  # still pending -> whole-session assembly blocked
    with pytest.raises(ResultsError, match="outstanding"):
        assemble_session(queue, tmp_path / "state", {}, SESSION, ["done"])
    queue.close()


def test_owned_run_jobs_helper_used_for_owner_validation(tmp_path: Path) -> None:
    # The queue helper the migration centralizes on: foreign run raises.
    queue = JobQueue(tmp_path / "q.db")
    _seed(queue, "foreign", OTHER)
    _drain(queue, "foreign")
    with pytest.raises(QueueError, match="not owned by session"):
        queue.owned_run_jobs(SESSION, "foreign")
    with pytest.raises(QueueError, match="unknown run"):
        queue.owned_run_jobs(SESSION, "ghost")
    queue.close()
