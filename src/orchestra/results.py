"""Results for Orchestra 2.

Assembles one consolidated return after all jobs of a run are terminal,
and one session-level consolidated return across an explicit set of
completed runs for one originating session. Pure mechanical assembly: no
LLM calls, no reformatting of child responses, no delivery. Core exposes
the assembled data; harness plugins deliver it to the originating session.

``assemble`` covers the single-run path; ``assemble_session`` covers the
consolidated path: the caller supplies the explicit set of run ids to
include, core validates ownership and that every outstanding job of the
session is terminal before assembling, and the hint is computed over the
combined outcomes. Historical runs not listed are not included.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from orchestra.artifacts import Response, Task, recall
from orchestra.dispatcher import recorded_reasons, resolve_answer
from orchestra.guidance import (
    SUCCESS_VERDICTS,
    VERIFIER_ROLE,
    categorize,
    derive_return_category,
    extract_verdict,
    is_semantic_failure,
    return_hint,
)
from orchestra.queue import Job, JobQueue, QueueError, SessionSnapshot

# Factual line for a job that never ran because a prerequisite failed.
SKIPPED_LINE = "did not run — prerequisite failed"

# Owner-approved scope note included in every assembled return.
RUN_SCOPE_NOTE = (
    "This return covers one run; jobs from other runs of the same session"
    " are not included."
)

# Scope note for the session-consolidated return.
SESSION_SCOPE_NOTE = (
    "This return consolidates every completed run listed for this session;"
    " jobs from unlisted runs are not included."
)


class ResultsError(ValueError):
    """Raised when a run cannot be assembled (unknown, non-terminal, incomplete)."""


@dataclass(frozen=True)
class JobReturn:
    """One job's compact block in the assembled return.

    ``step`` is the job's 1-based position in the assembled return, so a
    reader distinguishes each job as an individually labeled step in stable
    order without inferring boundaries from prose; it carries the job's own
    ``role``/``status``/``summary`` and its own ``artifact_paths``. Jobs are
    emitted in prerequisite order, so an upstream job always precedes its
    follow-up.
    """

    step: int
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


@dataclass(frozen=True)
class SessionReturn:
    """The one consolidated return across completed runs of one session."""

    parent_session: str
    run_ids: tuple[str, ...]
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
    outstanding = tuple(job for job in jobs if not job.is_terminal)
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

    blocks = tuple(
        _job_return(job, responses, tasks, index + 1, state_dir, run_id)
        for index, job in enumerate(jobs)
    )

    # Semantic override: when all hard statuses pass, a verifier-role job
    # whose response text reports a non-success verdict changes the category
    # to verification_disagreement. Hard statuses are never mutated.
    if category == "all_succeeded":
        for block in blocks:
            if (
                block.role == VERIFIER_ROLE
                and block.status == "succeeded"
                and is_semantic_failure(block.summary)
            ):
                category = "verification_disagreement"
                break

    hint = return_hint(prompts, category)

    return AssembledReturn(
        run_id=run_id,
        category=category,
        hint=hint,
        jobs=blocks,
        note=RUN_SCOPE_NOTE,
    )


def assemble_session(
    queue: JobQueue,
    state_dir: Path | str,
    prompts: Mapping[str, str],
    parent_session: str,
    run_ids: Sequence[str],
    *,
    snapshot: SessionSnapshot | None = None,
) -> SessionReturn:
    """Assemble one consolidated return across explicit completed runs.

    Every listed run must exist and be owned by ``parent_session`` (validated
    per run through the queue-owned :meth:`JobQueue.owned_run_jobs`), and every
    job of the session (including unlisted runs) must be terminal before
    assembly, so an outstanding run blocks the final return loudly. Only the
    listed runs' jobs are included, in the order given. The category and hint
    are computed over the combined outcomes.

    The whole-session idle check reuses the authoritative queue snapshot: when
    a caller already holds one (the core session evaluator reuses a single
    snapshot for status, readiness selection, and assembly) pass it as
    ``snapshot`` so assembly does not re-read the session. Ownership and
    terminality always come from the queue, never a re-implemented filter.
    """
    if not run_ids:
        raise ResultsError("no runs supplied for session assembly")
    seen: set[str] = set()
    unique_ids: list[str] = []
    for run_id in run_ids:
        if run_id in seen:
            raise ResultsError(f"run {run_id!r} listed twice in session assembly")
        seen.add(run_id)
        unique_ids.append(run_id)

    snap = snapshot if snapshot is not None else queue.snapshot(parent_session)
    session_jobs = list(snap.jobs)
    if not session_jobs:
        raise ResultsError(f"session {parent_session!r} has no jobs")
    outstanding = [job for job in session_jobs if not job.is_terminal]
    if outstanding:
        raise ResultsError(
            f"session {parent_session!r} has"
            f" {len(outstanding)} outstanding job(s);"
            " final assembly is blocked until every session job is terminal"
        )

    blocks: list[JobReturn] = []
    reasons: dict[str, str] = {}
    combined_jobs: list[Job] = []
    for run_id in unique_ids:
        try:
            jobs = queue.owned_run_jobs(parent_session, run_id)
        except QueueError as exc:
            # The queue is the ownership/terminality authority; surface its
            # rejection through the Results contract without copying filters.
            raise ResultsError(str(exc)) from exc
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
        combined_jobs.extend(jobs)
        reasons.update(recorded_reasons(state_dir, run_id))
        blocks.extend(
            _job_return(job, responses, tasks, len(blocks) + 1, state_dir, run_id)
            for job in jobs
        )

    category = categorize(combined_jobs, reasons)

    # Semantic override for session assembly: same as assemble.
    if category == "all_succeeded":
        for block in blocks:
            if (
                block.role == VERIFIER_ROLE
                and block.status == "succeeded"
                and is_semantic_failure(block.summary)
            ):
                category = "verification_disagreement"
                break

    return SessionReturn(
        parent_session=parent_session,
        run_ids=tuple(unique_ids),
        category=category,
        hint=return_hint(prompts, category),
        jobs=tuple(blocks),
        note=SESSION_SCOPE_NOTE,
    )


def render_report_text(session_return: SessionReturn) -> str:
    """Render the final core-owned report text for one session return.

    This is the single assembled text the core produces for a completed
    session. The native adapter delivers it verbatim (``deliver_report`` carries
    this text); core never forces the host to reassemble a report from the
    structured record. Deterministic, no LLM, no reformatting of job answers.
    """
    lines = [
        (
            f"Orchestra report ({session_return.parent_session}) — "
            f"{session_return.category}"
        ),
        f"Runs: {', '.join(session_return.run_ids)}",
        "",
    ]
    for job in session_return.jobs:
        header = f"  #{job.step} {job.role} [{job.status}] {job.job_id}"
        lines.append(header)
        # Annotate succeeded jobs whose response reports a non-success verdict.
        if job.status == "succeeded":
            verdict = extract_verdict(job.summary)
            if verdict is not None and verdict not in SUCCESS_VERDICTS:
                lines.append(f"      [reported verdict: {verdict}]")
        for body_line in job.summary.splitlines() or [""]:
            lines.append(f"      {body_line}")
    lines.append("")
    lines.append(session_return.hint)
    lines.append("")
    lines.append(session_return.note)
    return "\n".join(lines) + "\n"


def _job_return(
    job: Job,
    responses: Mapping[str, Response],
    tasks: Mapping[str, Task],
    step: int,
    state_dir: Path | str,
    run_id: str,
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
        # One shared core resolution: the summary is the text the job actually
        # returned, reading the output file when the record kept only a reason.
        summary = resolve_answer(state_dir, run_id, response)
    paths: list[str] = []
    if response is not None and response.transcript is not None:
        paths.append(response.transcript)
    task = tasks.get(job.job_id)
    if task is not None:
        paths.extend(item["path"] for item in task.inputs)
    return JobReturn(
        step=step,
        job_id=job.job_id,
        role=job.role,
        status=job.status,
        summary=summary,
        artifact_paths=tuple(paths),
    )
