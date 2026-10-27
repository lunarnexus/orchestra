"""Durability, schema, and coexistence tests for the job queue store."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from orchestra.jobs import JOB_STATE_CLAIMED, JobQueue, JobSpec, Limits, QueueSchemaError
from tests.jobs.helpers import OWNER, make_queue, outcome, spec


def test_queued_and_claimed_jobs_survive_reopen(tmp_path: Path) -> None:
    database = tmp_path / "jobs.db"
    queue = make_queue(database, global_limit=2, per_owner_limit=2)
    queue.submit(spec("job-1"))
    queue.submit(spec("job-2"))
    claim = queue.claim_next(OWNER)
    assert claim is not None

    reopened = JobQueue(database)
    assert reopened.get_limits().global_limit == 2
    claimed = reopened.get("job-1", OWNER)
    assert claimed.state == JOB_STATE_CLAIMED
    assert claimed.claim_token == claim.token

    assert reopened.finish(claim, outcome(summary="after restart")).state == "done"
    assert reopened.claim_next(OWNER) is not None


def test_reopened_queue_does_not_resurrect_finished_work(tmp_path: Path) -> None:
    database = tmp_path / "jobs.db"
    queue = make_queue(database)
    claim = queue.admit(spec("job-1"))
    queue.finish(claim, outcome())

    assert JobQueue(database).claim_next(OWNER) is None
    assert JobQueue(database).has_outstanding(OWNER) is False


def test_history_is_retained_for_owner_listing(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db")
    claim = queue.admit(spec("job-1"))
    queue.finish(claim, outcome(summary="done earlier"))
    queue.submit(spec("job-2"))

    jobs = queue.list_jobs(OWNER)
    assert [job.job_id for job in jobs] == ["job-1", "job-2"]
    assert [job.job_id for job in queue.list_jobs(OWNER, "queued")] == ["job-2"]


def test_queue_tables_do_not_touch_run_schema_or_version(tmp_path: Path) -> None:
    database = tmp_path / "shared.db"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version = 16")
        connection.execute(
            "CREATE TABLE runs (run_id TEXT PRIMARY KEY, orchestrator_session_id TEXT)"
        )
        connection.execute("INSERT INTO runs VALUES ('old-run', 'pi:old')")

    queue = make_queue(database)
    queue.submit(spec("job-1"))

    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == 16
        runs = connection.execute("SELECT run_id FROM runs").fetchall()
        assert [str(row["run_id"]) for row in runs] == ["old-run"]
        assert queue.get_limits().revision == 1


def test_unsupported_schema_version_is_reported_without_data_loss(
    tmp_path: Path,
) -> None:
    database = tmp_path / "jobs.db"
    make_queue(database)
    queue_ref = JobQueue(database)
    queue_ref.submit(spec("job-1"))

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE orchestra_job_meta SET value = '99' WHERE key = 'schema_version'"
        )

    with pytest.raises(QueueSchemaError, match="unsupported job queue schema version"):
        JobQueue(database).validate_schema()

    with sqlite3.connect(database) as connection:
        assert int(connection.execute("SELECT COUNT(*) FROM orchestra_jobs").fetchone()[0]) == 1


def test_missing_policy_is_reported(tmp_path: Path) -> None:
    with pytest.raises(QueueSchemaError, match="not initialized"):
        JobQueue(tmp_path / "unwritten.db").validate_schema()


def test_initialize_creates_schema_without_writing_jobs(tmp_path: Path) -> None:
    database = tmp_path / "jobs.db"
    queue = JobQueue(database)
    queue.initialize(Limits(global_limit=2, per_owner_limit=2))
    assert queue.list_jobs(OWNER) == ()
    assert database.exists()


def test_dependency_edge_to_missing_job_is_rejected_before_write(
    tmp_path: Path,
) -> None:
    from orchestra.jobs import Dependency, JobSpecError

    queue = make_queue(tmp_path / "jobs.db")
    with pytest.raises(JobSpecError, match="unknown job"):
        queue.submit(JobSpec(job_id="x", owner_id=OWNER, dependencies=(Dependency("ghost"),)))
    assert queue.list_jobs(OWNER) == ()


def test_foreign_keys_are_enforced_for_dependency_edges(tmp_path: Path) -> None:
    database = tmp_path / "jobs.db"
    make_queue(database)

    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO orchestra_job_dependencies (job_id, depends_on_job_id, condition)"
                " VALUES ('nope', 'also-nope', 'done')"
            )


def test_duplicate_dependency_edge_is_rejected(tmp_path: Path) -> None:
    from orchestra.jobs import Dependency, JobSpecError

    queue = make_queue(tmp_path / "jobs.db")
    queue.submit_many([spec("a"), spec("b")])

    with pytest.raises(JobSpecError, match="duplicate dependency edge"):
        queue.submit(spec("c", dependencies=[Dependency("a"), Dependency("a")]))
