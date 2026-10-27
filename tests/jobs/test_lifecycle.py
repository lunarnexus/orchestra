"""Lifecycle, claim identity, and limit policy tests for the job queue."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from orchestra.jobs import (
    JOB_STATE_CANCELLED,
    JOB_STATE_CLAIMED,
    JOB_STATE_DONE,
    JOB_STATE_QUEUED,
    CapacityUnavailableError,
    Claim,
    ClaimRejectedError,
    JobConflictError,
    JobQueue,
    JobSpec,
    JobSpecError,
    Limits,
    PolicyError,
)
from tests.jobs.helpers import OWNER, make_queue, outcome, spec


def test_initialize_is_idempotent_and_reopens(tmp_path: Path) -> None:
    database = tmp_path / "jobs.db"
    queue = make_queue(database)
    assert queue.get_limits().revision == 1

    reopened = JobQueue(database)
    reopened.initialize(Limits(global_limit=4, per_owner_limit=3))
    assert reopened.get_limits().revision == 1


def test_initialize_rejects_conflicting_stored_policy(tmp_path: Path) -> None:
    database = tmp_path / "jobs.db"
    make_queue(database, global_limit=4)

    with pytest.raises(PolicyError, match="conflict"):
        JobQueue(database).initialize(Limits(global_limit=9, per_owner_limit=3))


def test_configure_limits_uses_revision_checking(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db")

    updated = queue.configure_limits(
        Limits(global_limit=8, per_owner_limit=3),
        expected_revision=1,
    )
    assert updated.revision == 2
    assert queue.get_limits().global_limit == 8

    noop = queue.configure_limits(
        Limits(global_limit=8, per_owner_limit=3),
        expected_revision=1,
    )
    assert noop.revision == 2

    with pytest.raises(PolicyError, match="revision conflict"):
        queue.configure_limits(
            Limits(global_limit=2, per_owner_limit=1),
            expected_revision=1,
        )


def test_limits_reject_non_positive_and_boolean_values() -> None:
    with pytest.raises(PolicyError):
        Limits(global_limit=0, per_owner_limit=1)
    with pytest.raises(PolicyError):
        Limits(global_limit=True, per_owner_limit=1)
    with pytest.raises(PolicyError):
        Limits(global_limit=1, per_owner_limit=1, resource_limits={"m": 0})


def test_submit_persists_immutable_parameters(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db")
    parameters: dict[str, object] = {"goal": "build", "nested": ["a", "b"]}
    job = queue.submit(spec("job-1", parameters=parameters))

    parameters["goal"] = "mutated"
    reloaded = queue.get("job-1", OWNER)
    assert job.parameters == {"goal": "build", "nested": ["a", "b"]}
    assert reloaded.parameters == {"goal": "build", "nested": ["a", "b"]}

    dict(reloaded.parameters)["goal"] = "again"
    assert queue.get("job-1", OWNER).parameters["goal"] == "build"


def test_submit_rejects_invalid_specs_without_writing(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db")

    with pytest.raises(JobSpecError, match="non-empty"):
        queue.submit(JobSpec(job_id=" ", owner_id=OWNER))
    with pytest.raises(JobSpecError, match="whitespace"):
        queue.submit(JobSpec(job_id="has space", owner_id=OWNER))
    with pytest.raises(JobSpecError, match="JSON"):
        queue.submit(spec("job-1", parameters={"bad": {1, 2}}))
    with pytest.raises(JobSpecError, match="non-finite"):
        queue.submit(spec("job-1", parameters={"x": float("nan")}))
    with pytest.raises(JobSpecError, match="budget"):
        queue.submit(spec("job-1", parameters={"blob": "x" * (70 * 1024)}))
    assert queue.list_jobs(OWNER) == ()


def test_duplicate_job_id_rejected_atomically(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db")
    queue.submit(spec("job-1"))

    with pytest.raises(JobSpecError, match="already exist"):
        queue.submit_many([spec("job-2"), spec("job-1")])
    assert [job.job_id for job in queue.list_jobs(OWNER)] == ["job-1"]


def test_claim_finish_lifecycle_and_claim_retention(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db")
    queue.submit(spec("job-1"))

    claim = queue.claim_next(OWNER)
    assert claim is not None
    claimed = queue.get("job-1", OWNER)
    assert claimed.state == JOB_STATE_CLAIMED
    assert claimed.claim_token == claim.token
    assert claimed.occupies_capacity

    finished = queue.finish(claim, outcome(summary="built"))
    assert finished.state == JOB_STATE_DONE
    assert finished.outcome is not None
    assert finished.outcome.summary == "built"
    assert finished.claim_token == claim.token
    assert not finished.occupies_capacity
    assert queue.claim_next(OWNER) is None


def test_finish_is_idempotent_and_conflict_guarded(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db")
    queue.submit(spec("job-1"))
    claim = queue.claim_next(OWNER)
    assert claim is not None

    first = queue.finish(claim, outcome(summary="built"))
    assert queue.finish(claim, outcome(summary="built")) == first

    with pytest.raises(JobConflictError, match="already terminal"):
        queue.finish(claim, outcome(status="failed", error_text="late"))


def test_finish_rejects_wrong_claim_identity(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db")
    queue.submit(spec("job-1"))
    claim = queue.claim_next(OWNER)
    assert claim is not None

    with pytest.raises(ClaimRejectedError, match="not valid"):
        queue.finish(replace(claim, token="forged"), outcome())
    with pytest.raises(ClaimRejectedError, match="not valid"):
        queue.finish(replace(claim, owner_id="pi:other"), outcome())
    with pytest.raises(ClaimRejectedError, match="unknown job"):
        queue.finish(replace(claim, job_id="missing"), outcome())


def test_outcome_metadata_is_bounded(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db")
    queue.submit(spec("job-1"))
    claim = queue.claim_next(OWNER)
    assert claim is not None

    with pytest.raises(JobSpecError, match="budget"):
        queue.finish(claim, outcome(summary="x" * (70 * 1024)))


def test_cancel_unclaimed_job_is_terminal(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db")
    queue.submit(spec("job-1"))

    cancelled = queue.cancel("job-1", OWNER)
    assert cancelled.state == JOB_STATE_CANCELLED
    assert cancelled.outcome is not None
    assert cancelled.outcome.status == JOB_STATE_CANCELLED
    assert queue.claim_next(OWNER) is None


def test_cancel_claimed_job_requests_and_keeps_capacity(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db", global_limit=1, per_owner_limit=1)
    queue.submit(spec("job-1"))
    claim = queue.claim_next(OWNER)
    assert claim is not None

    pending = queue.cancel("job-1", OWNER)
    assert pending.cancel_requested
    assert pending.state == JOB_STATE_CLAIMED

    with pytest.raises(CapacityUnavailableError):
        queue.admit(spec("job-2"))

    queue.finish(claim, outcome(summary="finished despite request"))
    assert queue.admit(spec("job-2")).job_id == "job-2"


def test_cancel_never_rewrites_a_terminal_job(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db")
    queue.submit(spec("job-1"))
    claim = queue.claim_next(OWNER)
    assert claim is not None
    queue.cancel("job-1", OWNER)

    done = queue.finish(claim, outcome(summary="real completion"))
    assert done.state == JOB_STATE_DONE
    assert queue.cancel("job-1", OWNER).state == JOB_STATE_DONE


def test_owner_scope_is_enforced(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db")
    queue.submit(spec("job-1", owner="pi:a"))

    with pytest.raises(Exception, match="not found"):
        queue.get("job-1", "pi:b")
    with pytest.raises(Exception, match="not found"):
        queue.cancel("job-1", "pi:b")
    assert queue.list_jobs("pi:b") == ()
    assert queue.claim_next("pi:b") is None
    assert not queue.has_outstanding("pi:b")
    assert queue.has_outstanding("pi:a")


def test_owner_id_must_be_provided(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db")
    with pytest.raises(JobSpecError, match="owner_id"):
        queue.submit(JobSpec(job_id="job-1", owner_id="  "))


def test_terminal_state_requires_outcome(tmp_path: Path) -> None:
    database = tmp_path / "jobs.db"
    make_queue(database)

    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO orchestra_jobs (job_id, owner_id, state, seq, created_at,"
                " parameters_json) VALUES ('x', 'pi:a', 'done', 9, 'now', '{}')"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO orchestra_jobs (job_id, owner_id, state, seq, created_at,"
                " parameters_json, claim_token) VALUES ('y', 'pi:a', 'queued', 10, 'now',"
                " '{}', 'unexpected')"
            )


def test_queued_state_reports_open_but_not_occupying(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db")
    queued = queue.submit(spec("job-1"))
    assert queued.state == JOB_STATE_QUEUED
    assert queued.is_open
    assert not queued.occupies_capacity


def test_claim_type_is_returned_by_claim_next(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db")
    queue.submit(spec("job-1"))
    claim = queue.claim_next(OWNER)
    assert isinstance(claim, Claim)
    assert claim.cancel_requested is False
