"""Submit module for Orchestra 2.

The single submission entry point for every job. Validates the assignment,
resolves the role (explicit or the catalog default), rejects disabled and
auto-only roles as directly callable, resolves model and runtime budgets,
and queues the submission's jobs — including automatic ``auto_verify``
follow-ups — in one queue transaction, appending one Task artifact record
per job.

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

from orchestra.artifacts import Task, append, render_reference
from orchestra.config import AgentCatalog, OrchestraConfig, RoleConfig
from orchestra.queue import Job, JobQueue, JobSpec

CONTEXT_SUFFIX: Final[str] = ".parent-context"
RETURN_FORMAT_KEY: Final[str] = "default_return_format"


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
    prompts: Mapping[str, str],
) -> str:
    """Assemble the full agent prompt from data Submit already has.

    Sections, in stable order, joined by blank lines (skipped when absent):
    role header, assignment goal, parent-context artifact reference, role
    skills, and the return-format contract. Shell jobs (explicit argv
    payload) never reach assembly.
    """
    sections = [f"Role: {role_name}", goal]
    if parent_context is not None:
        sections.append(render_reference(parent_context))
    if skills:
        sections.append("Skills: " + ", ".join(skills))
    return_format = prompts.get(RETURN_FORMAT_KEY, "")
    if return_format:
        sections.append(return_format)
    return "\n\n".join(sections)


@dataclass(frozen=True)
class _Resolved:
    """One assignment with its role resolved (internal)."""

    name: str
    role: RoleConfig
    assignment: Assignment


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
    assignment's role defaults to the catalog ``default_role``. When the
    resolved role has ``auto_verify`` enabled, a verifier follow-up job is
    created through the same pipeline inside the same queue transaction;
    the verifier's only input is the builder's Task record path.
    ``context_provider`` is the host-supplied parent-context callback; it
    is invoked only for roles that opt in via ``parent_context: true``.
    """
    if not parent_session or not parent_session.strip():
        raise SubmitError("parent_session is required")
    if not assignments:
        raise SubmitError("a submission requires at least one assignment")
    for index, assignment in enumerate(assignments):
        if not assignment.goal or not assignment.goal.strip():
            raise SubmitError(f"assignment {index} requires non-empty goal text")

    runtime = config.runtime
    resolved: list[_Resolved] = []
    for index, assignment in enumerate(assignments):
        name = assignment.role if assignment.role is not None else config.catalog.default_role
        role = _callable_role(config.catalog, name, f"assignment {index}")
        resolved.append(_Resolved(name=name, role=role, assignment=assignment))

    run_id = uuid.uuid4().hex
    artifacts_path = Path(state_dir) / "artifacts" / f"{run_id}.jsonl"

    # Pre-compute everything that can fail before touching the queue; job
    # ids of a fresh run are deterministic: sequence == insert order.
    specs: list[JobSpec] = []
    tasks: list[Task] = []
    payloads: dict[str, tuple[str, ...]] = {}
    skills: dict[str, tuple[str, ...]] = {}
    follow_ups: list[tuple[str, str, RoleConfig]] = []  # (builder job, role, config)
    for item in resolved:
        job_id = f"{run_id}:{len(specs) + 1}"
        parent_context = _capture_parent_context(
            Path(state_dir), run_id, job_id, item.role, context_provider
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
        prompt = (
            item.assignment.goal
            if item.assignment.payload
            else _assemble_prompt(
                item.name,
                item.assignment.goal,
                parent_context,
                item.role.skills,
                config.prompts,
            )
        )
        tasks.append(
            Task(
                job_id=job_id,
                timestamp=_now(),
                prompt=prompt,
                role=item.name,
                parent_context=parent_context,
                inputs=tuple(item.assignment.inputs),
            )
        )
        if item.assignment.payload:
            payloads[job_id] = tuple(item.assignment.payload)
        else:
            payloads[job_id] = (prompt,)
        skills[job_id] = item.role.skills
        if item.role.auto_verify:
            follow_ups.append((job_id, item.name, item.role))

    # Automatic verifier follow-ups through the same pipeline. The verifier
    # receives the builder's Task record only: prerequisite on the builder
    # job, single input link to the builder's Task record path. A verifier
    # never gains its own verifier, even when the verifier role sets
    # ``auto_verify: true`` (no recursive verification).
    seen: set[str] = set()
    while follow_ups:
        builder_job_id, builder_name, _builder_role = follow_ups.pop(0)
        if builder_name in seen:
            continue
        seen.add(builder_name)
        verifier_name, verifier_role = _verifier_role(
            config.catalog, f"auto_verify for role {builder_name!r}"
        )
        job_id = f"{run_id}:{len(specs) + 1}"
        specs.append(
            JobSpec(
                run_id=run_id,
                parent_session=parent_session,
                role=verifier_name,
                model=verifier_role.model,
                prerequisites=(builder_job_id,),
                soft_timeout=runtime.soft_timeout,
                hard_timeout=runtime.default_timeout,
                turn_limit=runtime.turn_limit,
            )
        )
        # Verifier isolation: its prompt contains only the builder Task
        # record reference, never builder/orchestrator context.
        reference = render_reference(str(artifacts_path))
        prompt = _assemble_prompt(
            verifier_name,
            reference,
            None,
            verifier_role.skills,
            config.prompts,
        )
        tasks.append(
            Task(
                job_id=job_id,
                timestamp=_now(),
                prompt=prompt,
                role=verifier_name,
                inputs=({"job_id": builder_job_id, "path": str(artifacts_path)},),
            )
        )
        payloads[job_id] = (prompt,)
        skills[job_id] = verifier_role.skills
    jobs = queue.add_jobs(specs)
    for task in tasks:
        append(state_dir, run_id, task)
    return Submission(run_id=run_id, jobs=jobs, payloads=payloads, skills=skills)


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
    path = state_dir / "artifacts" / run_id / f"{job_id}{CONTEXT_SUFFIX}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)
