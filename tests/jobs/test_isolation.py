"""Owner isolation and true cross-process claim contention tests."""

from __future__ import annotations

import multiprocessing
from pathlib import Path
from typing import Any

import pytest

from orchestra.jobs import JOB_STATE_DONE, Claim, JobOutcome, JobQueue
from tests.jobs.helpers import OWNER, make_queue, outcome, spec


def _claim_worker(database: str, barrier: Any, results: Any, owner: str) -> None:
    barrier.wait(timeout=30)
    claim = JobQueue(database).claim_next(owner)
    results.put(claim.job_id if claim is not None else None)


def _finish_worker(database: str, barrier: Any, results: Any, claim: Claim) -> None:
    barrier.wait(timeout=30)
    job = JobQueue(database).finish(claim, JobOutcome(status="done", summary="from worker"))
    results.put(job.state)


def _run_workers(target: Any, args_list: list[tuple[object, ...]]) -> list[object]:
    """Run one process per arg set, released together by a shared barrier."""
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(len(args_list))
    results: Any = context.Queue()
    processes = [
        context.Process(target=target, args=(database, barrier, results, *rest))
        for database, *rest in args_list
    ]
    for process in processes:
        process.start()
    collected = [results.get(timeout=60) for _ in args_list]
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0, f"worker exited with {process.exitcode}"
    results.close()
    return collected


def test_processes_cannot_double_claim(tmp_path: Path) -> None:
    database = tmp_path / "jobs.db"
    queue = make_queue(database, global_limit=1, per_owner_limit=1)
    queue.submit(spec("job-1"))

    collected = _run_workers(_claim_worker, [(str(database), OWNER)] * 4)
    assert collected.count("job-1") == 1
    assert collected.count(None) == 3
    assert len(queue.list_jobs(OWNER, "claimed")) == 1


def test_processes_cannot_exceed_global_limit(tmp_path: Path) -> None:
    database = tmp_path / "jobs.db"
    queue = make_queue(database, global_limit=2, per_owner_limit=2)
    queue.submit_many([spec(f"job-{index}") for index in range(10)])

    collected = _run_workers(_claim_worker, [(str(database), OWNER)] * 6)
    assert collected.count(None) == 4
    assert len(queue.list_jobs(OWNER, "claimed")) == 2


def test_processes_replay_completion_idempotently(tmp_path: Path) -> None:
    database = tmp_path / "jobs.db"
    queue = make_queue(database)
    claim = queue.admit(spec("job-1"))

    collected = _run_workers(_finish_worker, [(str(database), claim)] * 3)
    assert collected == [JOB_STATE_DONE] * 3

    finished = queue.get("job-1", OWNER)
    assert finished.state == JOB_STATE_DONE
    assert finished.outcome is not None
    assert finished.outcome.summary == "from worker"


def test_owner_cannot_finish_another_owners_claim(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db")
    claim = queue.admit(spec("job-1", owner="pi:a"))

    stolen = Claim(
        job_id=claim.job_id,
        owner_id="pi:b",
        token=claim.token,
        seq=claim.seq,
        resource_key=claim.resource_key,
        claimed_at=claim.claimed_at,
    )
    with pytest.raises(Exception, match="not valid"):
        queue.finish(stolen, outcome())
    assert queue.get("job-1", "pi:a").state == "claimed"


def test_owner_cannot_claim_another_owners_queued_job(tmp_path: Path) -> None:
    queue = make_queue(tmp_path / "jobs.db", global_limit=4, per_owner_limit=4)
    queue.submit(spec("job-1", owner="pi:a"))

    assert queue.claim_next("pi:b") is None
    assert queue.get("job-1", "pi:a").state == "queued"
