"""Durable execution ownership and outcome transitions in the queue.

Slice 3 adds three nullable job fields (dispatcher token, child execution
group id, process creation identity) that let reconciliation attribute running
work to a dispatcher and terminate verified surviving execution.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from orchestra.queue import JobQueue


@pytest.fixture()
def queue(tmp_path: Path) -> Iterator[JobQueue]:
    q = JobQueue(tmp_path / "jobs.sqlite")
    yield q
    q.close()


def _add(queue: JobQueue, run_id: str = "r1") -> str:
    return queue.add_job(
        run_id=run_id, parent_session="s1", role="shell", model="sh"
    ).job_id


def test_new_fields_default_none_and_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite"
    q = JobQueue(path)
    job_id = _add(q)
    job = q.get_job(job_id)
    assert job.dispatcher_token is None
    assert job.child_pgid is None
    assert job.child_start is None

    claimed = q.claim_next(global_limit=1, per_session_limit=1, dispatcher_token="tok-1")
    assert claimed is not None
    assert claimed.dispatcher_token == "tok-1"  # stamped at claim time
    # Ownership of execution is registered right after launch.
    q.register_execution(job_id, pgid=4321, child_start=123.5)
    registered = q.get_job(job_id)
    assert (registered.child_pgid, registered.child_start) == (4321, 123.5)
    q.close()

    reopened = JobQueue(path)
    again = reopened.get_job(job_id)
    assert again.dispatcher_token == "tok-1"
    assert (again.child_pgid, again.child_start) == (4321, 123.5)
    reopened.close()


def test_claim_without_token_leaves_token_none(queue: JobQueue) -> None:
    _add(queue)
    claimed = queue.claim_next(global_limit=1, per_session_limit=1)
    assert claimed is not None
    assert claimed.dispatcher_token is None


def test_registration_clears_when_job_finalizes(queue: JobQueue) -> None:
    job_id = _add(queue)
    queue.claim_next(global_limit=1, per_session_limit=1, dispatcher_token="tok")
    queue.register_execution(job_id, pgid=99, child_start=1.0)
    assert queue.get_job(job_id).child_pgid == 99
    queue.complete_job(job_id, "succeeded")
    done = queue.get_job(job_id)
    # Terminal ownership bookkeeping is cleared so a reused PID is never
    # mistaken for still-owned execution.
    assert done.child_pgid is None and done.child_start is None
    assert done.dispatcher_token is None


def test_running_jobs_filter_by_token_and_status(tmp_path: Path) -> None:
    q = JobQueue(tmp_path / "a.sqlite")
    dead = _add(q, "r1")
    live = _add(q, "r1")
    # Claim both, then attribute them to two different dispatcher tokens.
    q.claim_next(global_limit=2, per_session_limit=2, dispatcher_token="tok-dead")
    # The second claim picks the remaining pending job with its own token.
    q.claim_next(global_limit=2, per_session_limit=2, dispatcher_token="tok-live")
    dead_job, live_job = q.get_job(dead), q.get_job(live)
    assert {dead_job.dispatcher_token, live_job.dispatcher_token} == {
        "tok-dead",
        "tok-live",
    }
    by_token = q.running_jobs(dispatcher_token="tok-dead")
    assert [job.job_id for job in by_token] == [dead]
    q.close()


def test_migration_adds_nullable_ownership_columns(tmp_path: Path) -> None:
    path = tmp_path / "jobs.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE jobs ("
            " job_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,"
            " sequence INTEGER NOT NULL, parent_session TEXT NOT NULL,"
            " role TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL,"
            " created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,"
            " soft_timeout INTEGER, hard_timeout INTEGER, turn_limit INTEGER)"
        )
        conn.execute(
            "INSERT INTO jobs VALUES ('r1:1','r1',1,'s1','builder','m1',"
            " 'pending','2025-01-01T00:00:00+00:00',NULL,NULL,NULL,NULL,NULL)"
        )
    q = JobQueue(path)  # migrates on open
    job = q.get_job("r1:1")
    assert job.dispatcher_token is None
    assert job.child_pgid is None
    assert job.child_start is None
    q.close()
