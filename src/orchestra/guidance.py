"""Guidance for Orchestra 2.

Selects configured advice for acknowledgements and returns. Pure functions
over job outcomes and the prompt key map: no LLM calls, no log parsing, no
role-keyed hint sections, and no condition expression language. Missing
prompt content raises :class:`GuidanceError`; there are no defaults or
fallbacks.

Return categories and the documented, tie-free, deterministic precedence
(first match wins, evaluated top to bottom):

1. ``budget_exhausted`` — some job failed and its dispatcher-recorded
   outcome reason marks a budget wrap-up (turn limit or soft timeout).
2. ``verification_disagreement`` — some verifier-role job failed while a
   builder-style prerequisite of it succeeded.
3. ``hard_failure`` — some job failed for any other reason.
4. ``all_succeeded`` — nothing failed (skipped jobs never ran and do not
   count; they are reported factually by Results).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from orchestra.config import (
    ACK_PROMPT_KEY,
    RETURN_CATEGORIES,
    _return_hint_key,
)
from orchestra.queue import Job, JobQueue

ALL_SUCCEEDED = "all_succeeded"
VERIFICATION_DISAGREEMENT = "verification_disagreement"
BUDGET_EXHAUSTED = "budget_exhausted"
HARD_FAILURE = "hard_failure"

# Role names classifying prerequisite/follow-up pairs. The catalog convention
# defines exactly one auto-enabled verifier role; its name is "verifier", and
# builder-style work roles are named "builder".
VERIFIER_ROLE = "verifier"
BUILDER_ROLE = "builder"

# A dispatcher-recorded outcome reason containing this mark indicates a
# budget wrap-up (turn limit or soft timeout), never a plain crash.
BUDGET_REASON_MARK = "budget wrap-up"


class GuidanceError(ValueError):
    """Raised when guidance content is missing or a category is unknown."""


def derive_return_category(
    queue: JobQueue,
    run_id: str,
    reasons: Mapping[str, str],
) -> str:
    """Categorize a finished run from its job outcomes and failure reasons.

    ``reasons`` maps job_id -> the dispatcher's recorded outcome reason
    (see :func:`orchestra.dispatcher.recorded_reasons`); it is consulted
    only for failed jobs. Precedence is documented at module level.
    """
    jobs = queue.list_jobs(run_id)
    if not jobs:
        raise GuidanceError(f"run {run_id!r} has no jobs")
    return categorize(jobs, reasons)


def categorize(
    jobs: Sequence[Job],
    reasons: Mapping[str, str],
) -> str:
    """Categorize an explicit set of jobs (one run or several combined).

    ``reasons`` maps job_id -> the dispatcher's recorded outcome reason and
    is consulted only for failed jobs. Same documented precedence.
    """
    failed = [job for job in jobs if job.status == "failed"]
    if failed:
        if any(BUDGET_REASON_MARK in str(reasons.get(job.job_id, "")) for job in failed):
            return BUDGET_EXHAUSTED
        succeeded_ids = {job.job_id for job in jobs if job.status == "succeeded"}
        for job in failed:
            if job.role == VERIFIER_ROLE and any(
                prerequisite_id in succeeded_ids for prerequisite_id in job.prerequisites
            ):
                return VERIFICATION_DISAGREEMENT
        return HARD_FAILURE
    return ALL_SUCCEEDED


def return_hint(prompts: Mapping[str, str], category: str) -> str:
    """Return the configured hint line for one return category; loud if missing."""
    if category not in RETURN_CATEGORIES:
        raise GuidanceError(f"unknown return category {category!r}")
    key = _return_hint_key(category)
    hint = prompts.get(key)
    if not isinstance(hint, str) or not hint.strip():
        raise GuidanceError(f"prompts are missing required return hint '{key}'")
    return hint


def acknowledgement(prompts: Mapping[str, str]) -> str:
    """Return the dispatch acknowledgement text; loud if missing."""
    ack = prompts.get(ACK_PROMPT_KEY)
    if not isinstance(ack, str) or not ack.strip():
        raise GuidanceError(f"prompts are missing required '{ACK_PROMPT_KEY}'")
    return ack
