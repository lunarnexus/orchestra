"""Submit module for Orchestra 2.

The single submission entry point for every job. Validates the assignment,
resolves the role (explicit or the catalog default), rejects disabled and
auto-only roles as directly callable, resolves model and runtime budgets,
and queues the submission's jobs — including automatic ``auto_verify``
follow-ups — in one queue transaction, appending one Task artifact record
per job.

Every job is prepared by the same path: directly submitted assignments and
follow-ups Submit queues for itself share role access checks, model and
budget resolution, skills, prompt assembly, inputs, upstream handoffs, and
queue insertion. A dependent of any role is handed its prerequisites' own
records views, so upstream assignments and responses reach it without an
orchestrator round trip.

Submit never reads configuration files: the caller loads the configuration
once and passes the typed :class:`~orchestra.config.OrchestraConfig`. There
are no retries (resubmission means calling :func:`submit` again with new
job ids) and no parallel flags: all jobs of one submission are assumed
parallel-safe and run concurrently, bounded by the queue's limits; ordering
within a submission comes only from prerequisites. Non-parallel work is
separate submissions by the orchestrator.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from orchestra.artifacts import Task, append, render_reference, scoped_path
from orchestra.config import AgentCatalog, OrchestraConfig, RoleConfig
from orchestra.queue import Job, JobQueue, JobSpec, QueueError, run_id_of

CONTEXT_SUFFIX: Final[str] = ".parent-context"

# Goal line of the verification follow-up Submit queues for itself. Upstream
# assignments and responses arrive as artifact references, so this line only
# states what the follow-up exists to do.
VERIFY_GOAL: Final[str] = "Verify the upstream work referenced in this assignment."


class SubmitError(ValueError):
    """Raised when a submission is invalid or cannot be processed."""


@dataclass(frozen=True)
class Assignment:
    """One unit of submitted work.

    ``goal`` is the assignment text sent to the agent. ``payload`` carries
    the execution argv for external-command (shell) jobs; agent jobs leave
    it empty and their harness plugin builds the payload later.
    """

    goal: str
    role: str | None = None
    inputs: tuple[dict[str, str], ...] = ()
    prerequisites: tuple[str, ...] = ()
    payload: tuple[str, ...] = ()


@dataclass(frozen=True)
class Submission:
    """The created run: its id, every queued job, and execution payloads.

    ``skills`` maps each job id to the resolved role's configured skill
    names, so a harness plugin can look up ``job -> role -> skills`` without
    re-reading the catalog. Injection and missing-skill reporting are plugin
    responsibilities.
    """

    run_id: str
    jobs: tuple[Job, ...]
    payloads: Mapping[str, tuple[str, ...]]
    skills: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


def _assemble_prompt(
    role_name: str,
    goal: str,
    parent_context: str | None,
    skills: tuple[str, ...],
    dispatch_hint: str,
    references: Sequence[str] = (),
) -> str:
    """Assemble the full agent prompt from data Submit already has.

    Sections, in stable order, joined by blank lines (skipped when absent):
    role header, assignment goal, parent-context artifact reference, upstream
    handoff artifact references, role skills, and the role's
    ``dispatch_hint`` (its capabilities, boundaries, and response
    expectations). Shell jobs (explicit argv payload) never reach assembly.
    """
    sections = [f"Role: {role_name}", goal]
    if parent_context is not None:
        sections.append(render_reference(parent_context))
    if references:
        sections.append("\n".join(render_reference(path) for path in references))
    if skills:
        sections.append("Skills: " + ", ".join(skills))
    sections.append(dispatch_hint)
    return "\n\n".join(sections)


@dataclass(frozen=True)
class _Pending:
    """One job with its role and parent context resolved, awaiting assembly."""

    job_id: str
    name: str
    role: RoleConfig
    assignment: Assignment
    parent_context: str | None = None


def submit(
    state_dir: Path | str,
    queue: JobQueue,
    config: OrchestraConfig,
    parent_session: str,
    assignments: Sequence[Assignment],
    context_provider: Callable[[], str] | None = None,
) -> Submission:
    """Validate and queue one submission; return the run and its jobs.

    ``parent_session`` is the originating session id (required). Each
    assignment's role defaults to the catalog ``default_role``. Every job —
    submitted directly or queued by Submit itself — is prepared by the one
    loop below: role access, model, runtime budgets, skills, prompt assembly,
    inputs, upstream handoffs, and queue insertion, in a single queue
    transaction with one Task artifact record each.

    When any resolved role has ``auto_verify`` enabled, Submit queues ONE
    verifier follow-up for the submission, dependent on every auto-verified
    job of that submission and handed all of their records. Follow-ups are
    never grouped across runs, and a verifier never verifies itself.
    ``context_provider`` is the host-supplied parent-context callback; it is
    invoked only for directly submitted roles that opt in via
    ``parent_context: true``. Follow-ups Submit queues for itself never
    receive the orchestrator's conversation.
    """
    if not parent_session or not parent_session.strip():
        raise SubmitError("parent_session is required")
    if not assignments:
        raise SubmitError("a submission requires at least one assignment")
    for index, assignment in enumerate(assignments):
        if not assignment.goal or not assignment.goal.strip():
            raise SubmitError(f"assignment {index} requires non-empty goal text")

    runtime = config.runtime
    resolved: list[tuple[str, RoleConfig, Assignment]] = []
    for index, assignment in enumerate(assignments):
        name = assignment.role if assignment.role is not None else config.catalog.default_role
        role = _callable_role(config.catalog, name, f"assignment {index}")
        resolved.append((name, role, assignment))

    run_id = uuid.uuid4().hex

    # Pre-compute everything that can fail before touching the queue; job
    # ids of a fresh run are deterministic: sequence == insert order.
    pending: list[_Pending] = []
    for name, role, assignment in resolved:
        job_id = f"{run_id}:{len(pending) + 1}"
        parent_context = _capture_parent_context(
            Path(state_dir), run_id, job_id, role, context_provider
        )
        pending.append(
            _Pending(
                job_id=job_id,
                name=name,
                role=role,
                assignment=assignment,
                parent_context=parent_context,
            )
        )

    # Automatic verification is Submit's own follow-up: one verifier covering
    # every auto-verified job of THIS submission, queued as an ordinary job in
    # the same batch and dependent on all of them.
    covered = tuple(item.job_id for item in pending if item.role.auto_verify)
    if covered:
        verifier_name, verifier_role = _verifier_role(
            config.catalog, "auto_verify in this submission"
        )
        pending.append(
            _Pending(
                job_id=f"{run_id}:{len(pending) + 1}",
                name=verifier_name,
                role=verifier_role,
                assignment=Assignment(goal=VERIFY_GOAL, prerequisites=covered),
            )
        )

    specs: list[JobSpec] = []
    tasks: list[Task] = []
    payloads: dict[str, tuple[str, ...]] = {}
    skills: dict[str, tuple[str, ...]] = {}
    for item in pending:
        # Provision this job's own records view with its assignment, so any
        # dependent can be handed that one file and read this job's assignment
        # now and its actual response once it finishes. The view is a
        # projection of the assignment alone: no parent-context path, no
        # assembled prompt, and no other job's records.
        append(
            state_dir,
            run_id,
            Task(
                job_id=item.job_id,
                timestamp=_now(),
                prompt=item.assignment.goal,
                role=item.name,
                inputs=tuple(item.assignment.inputs),
            ),
            scope=item.job_id,
        )
        # Upstream handoff: every prerequisite is given the upstream job's own
        # records path, both in the assembled prompt and as a structured input
        # link. This is the general dependent facility, not verifier-specific.
        handoffs = [
            (_upstream_records(state_dir, prerequisite_id), prerequisite_id)
            for prerequisite_id in item.assignment.prerequisites
        ]
        prompt = (
            item.assignment.goal
            if item.assignment.payload
            else _assemble_prompt(
                item.name,
                item.assignment.goal,
                item.parent_context,
                item.role.skills,
                item.role.dispatch_hint,
                [path for path, _ in handoffs],
            )
        )
        specs.append(
            JobSpec(
                run_id=run_id,
                parent_session=parent_session,
                role=item.name,
                model=item.role.model,
                prerequisites=tuple(item.assignment.prerequisites),
                soft_timeout=runtime.soft_timeout,
                hard_timeout=runtime.default_timeout,
                turn_limit=runtime.turn_limit,
            )
        )
        tasks.append(
            Task(
                job_id=item.job_id,
                timestamp=_now(),
                prompt=prompt,
                role=item.name,
                parent_context=item.parent_context,
                inputs=tuple(item.assignment.inputs)
                + tuple(
                    {"job_id": prerequisite_id, "path": path}
                    for path, prerequisite_id in handoffs
                ),
            )
        )
        if item.assignment.payload:
            payloads[item.job_id] = tuple(item.assignment.payload)
        else:
            payloads[item.job_id] = (prompt,)
        skills[item.job_id] = item.role.skills

    jobs = queue.add_jobs(specs)
    for task in tasks:
        append(state_dir, run_id, task)
    return Submission(run_id=run_id, jobs=jobs, payloads=payloads, skills=skills)


def _upstream_records(state_dir: Path | str, job_id: str) -> str:
    """Return the path of one upstream job's own records view, from its id.

    A job's own records live under its own run's artifacts area, so a
    dependent reaches them from the job id alone, whether the upstream job is
    in this submission or an earlier one.
    """
    try:
        run_id = run_id_of(job_id)
    except QueueError as exc:
        raise SubmitError(f"unknown prerequisite job id: {exc}") from exc
    return str(scoped_path(state_dir, run_id, job_id))


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _callable_role(catalog: AgentCatalog, name: str, context: str) -> RoleConfig:
    """Resolve a directly callable role: known, and not disabled or auto."""
    role = catalog.roles.get(name)
    if role is None:
        raise SubmitError(f"{context}: unknown role {name!r}")
    if role.enabled == "disabled":
        raise SubmitError(f"{context}: role {name!r} is disabled")
    if role.enabled == "auto":
        raise SubmitError(
            f"{context}: role {name!r} is automation-only and cannot be submitted directly"
        )
    return role


def _verifier_role(catalog: AgentCatalog, context: str) -> tuple[str, RoleConfig]:
    """Find the catalog's single auto-enabled verifier role."""
    auto = [(name, role) for name, role in catalog.roles.items() if role.enabled == "auto"]
    if len(auto) != 1:
        raise SubmitError(
            f"{context}: the catalog must define exactly one auto-enabled "
            f"verifier role, found {len(auto)}"
        )
    return auto[0]


def _capture_parent_context(
    state_dir: Path,
    run_id: str,
    job_id: str,
    role: RoleConfig,
    context_provider: Callable[[], str] | None,
) -> str | None:
    """Capture parent context when the role opts in and a provider exists.

    Writes the capture as an artifact file under the run's artifacts area
    and returns its path; returns None otherwise.
    """
    if not role.parent_context or context_provider is None:
        return None
    text = context_provider()
    if not text.strip():
        raise SubmitError(
            f"parent context capture is empty for job {job_id}; "
            "refusing to queue a fake successful capture"
        )
    path = state_dir / "artifacts" / run_id / f"{job_id}{CONTEXT_SUFFIX}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)
