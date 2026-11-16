"""Results for Orchestra 2.

Assembles one consolidated return after all jobs of a run are terminal.
Pure mechanical assembly: no LLM calls, no reformatting of child
responses, no delivery. Core exposes the assembled data; harness plugins
deliver it to the originating session.

Scope limitation (recorded for the plugin phase): Results assembles one
run. If a future session feature spans multiple runs, the plugin phase
must deliver one return per run or extend assembly; outstanding waiting
prerequisites/follow-ups of other runs are not collected here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from orchestra.artifacts import Response, Task, recall
from orchestra.dispatcher import recorded_reasons
from orchestra.guidance import derive_return_category, return_hint
from orchestra.queue import Job, JobQueue

_TERMINAL = frozenset({"succeeded", "failed", "skipped"})

# Factual line for a job that never ran because a prerequisite failed.
SKIPPED_LINE = "did not run — prerequisite failed"

# Owner-approved scope note included in every assembled return.
RUN_SCOPE_NOTE = (
    "This return covers one run; jobs from other runs of the same session"
    " are not included."
)


class ResultsError(ValueError):
    """Raised when a run cannot be assembled (unknown, non-terminal, incomplete)."""


@dataclass(frozen=True)
class JobReturn:
    """One job's compact block in the assembled return."""

    job_id: str
    role: str
    status: str
    summary: str
    artifact_paths: tuple[str, ...]


@dataclass(frozen=True)
class AssembledReturn:
    """The one consolidated return for a terminal run."""

    run_id: str
    category: str
    hint: str
    jobs: tuple[JobReturn, ...]
    note: str


def assemble(
    queue: JobQueue,
    state_dir: Path | str,
    prompts: Mapping[str, str],
    run_id: str,
) -> AssembledReturn:
    """Assemble the return for ``run_id`` once every job of the run is terminal.

    Reads terminal outcomes from the queue, task/response records via
    ``orchestra.artifacts.recall``, the dispatcher-recorded failure reasons,
    and selects the configured guidance hint. Loud on an unknown run or a
    run that is not yet terminal.
    """
    jobs = queue.list_jobs(run_id)
    if not jobs:
        raise ResultsError(f"unknown run {run_id!r}: no jobs")
    outstanding = tuple(job for job in jobs if job.status not in _TERMINAL)
    if outstanding:
        raise ResultsError(
            f"run {run_id!r} is not terminal:"
            f" {len(outstanding)} job(s) still outstanding"
        )

    responses = {
        record.job_id: record
        for record in recall(state_dir, run_id)
        if isinstance(record, Response)
    }
    tasks = {
        record.job_id: record
        for record in recall(state_dir, run_id)
        if isinstance(record, Task)
    }

    category = derive_return_category(
        queue, run_id, recorded_reasons(state_dir, run_id)
    )
    hint = return_hint(prompts, category)

    blocks = tuple(
        _job_return(job, responses, tasks) for job in jobs
    )
    return AssembledReturn(
        run_id=run_id,
        category=category,
        hint=hint,
        jobs=blocks,
        note=RUN_SCOPE_NOTE,
    )


def _job_return(
    job: Job,
    responses: Mapping[str, Response],
    tasks: Mapping[str, Task],
) -> JobReturn:
    if job.status == "skipped":
        summary = SKIPPED_LINE
        response = None
    else:
        response = responses.get(job.job_id)
        if response is None:
            raise ResultsError(
                f"job {job.job_id!r} is {job.status} but has no response record"
            )
        summary = response.response
    paths: list[str] = []
    if response is not None and response.transcript is not None:
        paths.append(response.transcript)
    task = tasks.get(job.job_id)
    if task is not None:
        paths.extend(item["path"] for item in task.inputs)
    return JobReturn(
        job_id=job.job_id,
        role=job.role,
        status=job.status,
        summary=summary,
        artifact_paths=tuple(paths),
    )
