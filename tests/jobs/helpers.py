"""Shared helpers for job queue tests."""

from __future__ import annotations

from pathlib import Path

from orchestra.jobs import JobOutcome, JobQueue, JobSpec, Limits

OWNER = "pi:main"


def make_queue(path: Path, *, global_limit: int = 4, per_owner_limit: int = 3) -> JobQueue:
    queue = JobQueue(path)
    queue.initialize(Limits(global_limit=global_limit, per_owner_limit=per_owner_limit))
    return queue


def spec(
    job_id: str,
    *,
    owner: str = OWNER,
    **kwargs: object,
) -> JobSpec:
    return JobSpec(job_id=job_id, owner_id=owner, **kwargs)  # type: ignore[arg-type]


def outcome(status: str = "done", **kwargs: object) -> JobOutcome:
    return JobOutcome(status=status, **kwargs)  # type: ignore[arg-type]
