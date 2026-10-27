"""Capacity admission, ordering, resource accounting, and contention tests."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from orchestra.jobs import (
    JOB_STATE_CLAIMED,
    CapacityUnavailableError,
    ClaimRejectedError,
    JobQueue,
    Limits,
)
from tests.jobs.helpers import OWNER, make_queue, outcome, spec


def test_queued_backlog_does_not_consume_capacity(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db", global_limit=2, per_owner_limit=2)
    for index in range(10):
        queue.submit(spec(f"job-{index}"))

    assert queue.claim_next(OWNER) is not None
    assert queue.claim_next(OWNER) is not None
    assert queue.claim_next(OWNER) is None
    assert len(queue.list_jobs(OWNER, "queued")) == 8


def test_admission_is_fifo_among_eligible_jobs(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db", global_limit=1, per_owner_limit=1)
    queue.submit_many([spec(f"job-{index}") for index in range(3)])

    claim = queue.claim_next(OWNER)
    assert claim is not None and claim.job_id == "job-0"


def test_blocked_candidate_is_bypassed_for_resource_reasons(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "jobs.db")
    queue.initialize(
        Limits(
            global_limit=4,
            per_owner_limit=4,
            resource_limits={"model-a": 1},
        )
    )
    queue.submit_many(
        [
            spec("blocked-first", resource_key="model-a"),
            spec("blocked-second", resource_key="model-a"),
            spec("other-model", resource_key="model-b"),
        ]
    )

    first = queue.claim_next(OWNER)
    assert first is not None and first.job_id == "blocked-first"

    second = queue.claim_next(OWNER)
    assert second is not None and second.job_id == "other-model"
    assert queue.claim_next(OWNER) is None
    assert queue.get("blocked-second", OWNER).state == "queued"


def test_global_limit_spans_owners(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db", global_limit=1, per_owner_limit=1)
    queue.submit(spec("a", owner="pi:a"))
    queue.submit(spec("b", owner="pi:b"))

    assert queue.claim_next("pi:a") is not None
    assert queue.claim_next("pi:b") is None


def test_admit_rolls_back_when_capacity_is_unavailable(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db", global_limit=1, per_owner_limit=1)
    queue.submit(spec("occupied"))
    assert queue.claim_next(OWNER) is not None

    with pytest.raises(CapacityUnavailableError):
        queue.admit(spec("rejected"))
    assert [job.job_id for job in queue.list_jobs(OWNER)] == ["occupied"]
    with pytest.raises(Exception, match="not found"):
        queue.get("rejected", OWNER)


def test_admit_claims_immediately(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db")
    claim = queue.admit(spec("now"))
    assert queue.get("now", OWNER).state == JOB_STATE_CLAIMED
    assert queue.get("now", OWNER).claim_token == claim.token
    assert queue.has_outstanding(OWNER)


def test_change_resource_moves_accounting_without_a_second_slot(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "jobs.db")
    queue.initialize(
        Limits(global_limit=1, per_owner_limit=1, resource_limits={"model-a": 1, "model-b": 1})
    )
    claim = queue.admit(spec("job-1", resource_key="model-a"))

    moved = queue.change_resource(claim, "model-b")
    assert moved.resource_key == "model-b"
    assert queue.get("job-1", OWNER).resource_key == "model-b"
    assert queue.claim_next(OWNER) is None

    finished = queue.finish(claim, outcome())
    assert finished.resource_key == "model-b"
    assert not queue.has_outstanding(OWNER)


def test_change_resource_rejects_a_full_target_resource(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "jobs.db")
    queue.initialize(
        Limits(global_limit=4, per_owner_limit=4, resource_limits={"model-a": 1, "model-b": 1})
    )
    first = queue.admit(spec("job-1", resource_key="model-a"))
    queue.admit(spec("job-2", resource_key="model-b"))

    with pytest.raises(CapacityUnavailableError):
        queue.change_resource(first, "model-b")
    assert queue.get("job-1", OWNER).resource_key == "model-a"


def test_change_resource_can_clear_a_resource_key(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "jobs.db")
    queue.initialize(Limits(global_limit=2, per_owner_limit=2, resource_limits={"model-a": 1}))
    claim = queue.admit(spec("job-1", resource_key="model-a"))

    assert queue.change_resource(claim, None).resource_key is None
    assert queue.admit(spec("job-2", resource_key="model-a")).resource_key == "model-a"


def test_change_resource_rejects_invalid_claims(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db")
    claim = queue.admit(spec("job-1"))

    with pytest.raises(ClaimRejectedError):
        queue.change_resource(replace(claim, token="forged"), "model-x")
    with pytest.raises(ClaimRejectedError):
        queue.change_resource(replace(claim, owner_id="pi:other"), "model-x")
    assert queue.get("job-1", OWNER).resource_key is None

    queue.finish(claim, outcome())
    with pytest.raises(ClaimRejectedError):
        queue.change_resource(claim, "model-x")


def test_limit_lowering_preserves_claims_and_blocks_new_ones(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db", global_limit=4, per_owner_limit=4)
    queue.submit_many([spec(f"job-{index}") for index in range(6)])
    claims = [queue.claim_next(OWNER) for _ in range(4)]
    assert all(claim is not None for claim in claims)
    resolved = [claim for claim in claims if claim is not None]

    queue.configure_limits(
        Limits(global_limit=1, per_owner_limit=1),
        expected_revision=1,
    )
    assert queue.claim_next(OWNER) is None

    # Existing claims survive the lowered limit, and no new work is admitted
    # until occupancy falls below it.
    for index, claim in enumerate(resolved):
        queue.finish(claim, outcome())
        expected_claim = index == len(resolved) - 1
        assert (queue.claim_next(OWNER) is not None) is expected_claim
    assert len(queue.list_jobs(OWNER, JOB_STATE_CLAIMED)) == 1


def test_stale_client_observes_newer_policy_on_next_claim(tmp_path: Path) -> None:
    database = tmp_path / "jobs.db"
    old_client = make_queue(database, global_limit=4, per_owner_limit=4)
    queue = JobQueue(database)
    queue.submit_many([spec(f"job-{index}") for index in range(4)])

    queue.configure_limits(
        Limits(global_limit=2, per_owner_limit=2),
        expected_revision=1,
    )

    assert old_client.claim_next(OWNER) is not None
    assert old_client.claim_next(OWNER) is not None
    assert old_client.claim_next(OWNER) is None


def test_concurrent_claims_never_double_claim_a_job(tmp_path: Path) -> None:
    database = tmp_path / "jobs.db"
    queue = make_queue(database, global_limit=10, per_owner_limit=10)
    queue.submit_many([spec(f"job-{index}") for index in range(8)])

    barrier = threading.Barrier(8)
    claimed: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        competitor = JobQueue(database)
        barrier.wait()
        claim = competitor.claim_next(OWNER)
        if claim is not None:
            with lock:
                claimed.append(claim.job_id)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(claimed) == 8
    assert len(set(claimed)) == 8
    assert len(queue.list_jobs(OWNER, JOB_STATE_CLAIMED)) == 8


def test_concurrent_claims_respect_global_limit(tmp_path: Path) -> None:
    database = tmp_path / "jobs.db"
    queue = make_queue(database, global_limit=3, per_owner_limit=3)
    queue.submit_many([spec(f"job-{index}") for index in range(12)])

    barrier = threading.Barrier(12)
    granted: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        competitor = JobQueue(database)
        barrier.wait()
        claim = competitor.claim_next(OWNER)
        if claim is not None:
            with lock:
                granted.append(claim.job_id)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(granted) == 3
    assert len(queue.list_jobs(OWNER, JOB_STATE_CLAIMED)) == 3


def test_transaction_rollback_leaves_no_queue_rows(tmp_path: Path) -> None:
    database = tmp_path / "jobs.db"
    make_queue(database)

    connection = sqlite3.connect(database, isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE")
        bound = JobQueue(database).bind(connection)
        bound.submit(spec("rolled-back"))
        connection.execute("ROLLBACK")
    finally:
        connection.close()

    assert JobQueue(database).list_jobs(OWNER) == ()
