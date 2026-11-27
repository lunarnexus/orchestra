"""Guidance for Orchestra 2.

Selects configured advice for acknowledgements and returns. Pure functions
over job outcomes and the prompt key map: no LLM calls, no log parsing, no
role-keyed hint sections, and no condition expression language. Missing
prompt content raises :class:`GuidanceError`; there are no defaults or
fallbacks.

Report categories use this precedence. The functions in this module classify
hard job outcomes; Results additionally examines reported verifier assessments
when assembling a report from response text:

1. ``budget_exhausted`` — some job failed and its dispatcher-recorded
   outcome reason marks a budget wrap-up (turn limit or soft timeout).
2. ``verification_disagreement`` — some verifier-role job failed while a
   builder-style prerequisite of it succeeded, OR a verifier-role job
   succeeded (hard status) but its response text reports a non-success
   verdict (semantic/prose disagreement).
3. ``hard_failure`` — some job failed for any other reason.
4. ``all_succeeded`` — nothing failed and no prose verdict disagrees
   (skipped jobs never ran and do not count; they are reported factually
   by Results).
"""

from __future__ import annotations

import re
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

# Verdict classification: a response text's Verdict: line (if present) is a
# *reported assessment*, not an authoritative execution status. Only these
# values are treated as a success endorsement; any other non-neutral value
# is a non-success (semantic failure). Unknown values are NOT invented as
# pass.
SUCCESS_VERDICTS: frozenset[str] = frozenset(
    {"complete", "completed", "done", "pass", "passed", "success"}
)
NEUTRAL_VERDICTS: frozenset[str] = frozenset(
    {"none", "n/a", "na", "not applicable"}
)

# Pattern matching the Verdict: line convention from return format schemas.
# Supports optional markdown bold/italic markers around the line.
_VERDICT_RE = re.compile(
    r"^[\*_ ]*[Vv]erdict[\*_ ]*:\s*(.+?)[\*_ ]*\s*$", re.MULTILINE
)


class GuidanceError(ValueError):
    """Raised when guidance content is missing or a category is unknown."""


def extract_verdict(text: str) -> str | None:
    """Extract the reported verdict from a job response text.

    Returns the lowercased verdict value, or None when no Verdict: line is
    present or the verdict is neutral (n/a, none, etc.).  The returned value
    is a *reported assessment* label, never an authoritative execution status.
    """
    match = _VERDICT_RE.search(text)
    if match is None:
        return None
    value = match.group(1).strip().lower()
    if not value or value in NEUTRAL_VERDICTS:
        return None
    return value


def is_semantic_failure(text: str) -> bool:
    """Return True when a response text reports a non-success verdict.

    A verdict is a semantic failure when it is present, non-neutral, and not
    in the success set. Unknown verdict values are NOT invented as pass.
    """
    verdict = extract_verdict(text)
    if verdict is None:
        return False
    return verdict not in SUCCESS_VERDICTS


def derive_return_category(
    queue: JobQueue,
    run_id: str,
    reasons: Mapping[str, str],
) -> str:
    """Categorize a finished run from its job outcomes and failure reasons.

    ``reasons`` maps job_id -> the dispatcher's recorded outcome reason
    (see :func:`orchestra.dispatcher.recorded_reasons`); it is consulted
    only for failed jobs. This classifies hard execution outcomes; Results
    applies the reported-verdict override when response text is available.
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
    is consulted only for failed jobs. This classifies hard execution outcomes;
    Results applies the reported-verdict override when assembling the report.
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
