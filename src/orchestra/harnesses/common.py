"""Shared harness helpers for prompt, command, and summary handling."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from orchestra.config import RoleConfig
from orchestra.harnesses.base import WorkerRequest

ORCHESTRA_DISPATCH_BUDGET_ENV = "ORCHESTRA_DISPATCH_BUDGET"
ORCHESTRA_TURN_BUDGET_ENV = "ORCHESTRA_TURN_BUDGET"
ORCHESTRA_SOFT_TIMEOUT_SECONDS_ENV = "ORCHESTRA_SOFT_TIMEOUT_SECONDS"
ORCHESTRA_BUDGET_EXCEEDED_PROMPT_ENV = "ORCHESTRA_BUDGET_EXCEEDED_PROMPT"
SKILL_LIBRARY_DIR = "skills"
SKILL_FILENAME = "SKILL.md"


def orchestra_dispatch_budget(env: Mapping[str, str] | None = None) -> int:
    raw = (env or os.environ).get(ORCHESTRA_DISPATCH_BUDGET_ENV)
    if raw is None or not raw.strip():
        return 0
    try:
        budget = int(raw.strip())
    except ValueError:
        return 1
    return max(budget, 0)


def orchestra_can_dispatch(env: Mapping[str, str] | None = None) -> bool:
    return orchestra_dispatch_budget(env) != 1


def worker_subprocess_env(
    *,
    worker_budget: int | None = None,
    turn_limit: int | None = None,
    soft_timeout: int | None = None,
    budget_exceeded_prompt: str = "",
    role_env: Mapping[str, str] | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    worker_env = dict(env or os.environ)
    worker_env.update(role_env or {})
    current_budget = orchestra_dispatch_budget(worker_env)
    configured_budget = worker_budget or 1
    if current_budget > 1:
        child_budget = min(current_budget - 1, configured_budget)
    else:
        child_budget = configured_budget
    worker_env[ORCHESTRA_DISPATCH_BUDGET_ENV] = str(child_budget)
    if turn_limit is not None:
        worker_env[ORCHESTRA_TURN_BUDGET_ENV] = str(turn_limit)
    if soft_timeout is not None:
        worker_env[ORCHESTRA_SOFT_TIMEOUT_SECONDS_ENV] = str(soft_timeout)
    if turn_limit is not None or soft_timeout is not None:
        worker_env[ORCHESTRA_BUDGET_EXCEEDED_PROMPT_ENV] = budget_exceeded_prompt
    return worker_env


def render_worker_prompt(request: WorkerRequest, role: RoleConfig) -> str:
    prompts = request.prompts
    sections = [
        f"Role: {request.role_name}",
    ]
    sections.extend(_role_skill_sections(role.skills, request.skill_roots))
    sections.append(f"Goal: {request.goal.strip()}")
    if role.prompt_addition:
        sections.append(f"Role instructions: {role.prompt_addition.strip()}")
    if request.approved_context.strip():
        sections.append(f"Approved context: {request.approved_context.strip()}")
    if request.boundaries.strip():
        sections.append(f"Out of scope: {request.boundaries.strip()}")
    if request.acceptance_target.strip():
        sections.append(f"Acceptance target: {request.acceptance_target.strip()}")

    return_format = request.return_format.strip() or prompts.default_return_format
    sections.append(f"Return format: {return_format}")
    return "\n\n".join(sections)


def _role_skill_sections(
    skill_names: tuple[str, ...], skill_roots: tuple[Path, ...]
) -> list[str]:
    sections: list[str] = []
    roots = skill_roots or (Path.cwd() / SKILL_LIBRARY_DIR,)
    for skill_name in skill_names:
        skill_path = _find_project_skill(skill_name, roots)
        if skill_path is not None:
            sections.append(
                f"Role skill: {skill_name}\n"
                f"Skill directory: {skill_path.parent.resolve()}\n"
                "Resolve relative resource paths against this directory.\n\n"
                f"{skill_path.read_text(encoding='utf-8').strip()}"
            )
        else:
            sections.append(
                f"Role skill: {skill_name}\n"
                f"Load the native skill named '{skill_name}' before doing the task."
            )
    return sections


def _find_project_skill(skill_name: str, skill_roots: tuple[Path, ...]) -> Path | None:
    for skills_root in skill_roots:
        candidate = skills_root / skill_name / SKILL_FILENAME
        if candidate.is_file():
            return candidate
        if not skills_root.is_dir():
            continue
        for nested_candidate in skills_root.rglob(SKILL_FILENAME):
            if nested_candidate.parent.name == skill_name:
                return nested_candidate
    return None


def expand_command_template(role: RoleConfig, prompt: str) -> list[str]:
    if not role.command:
        raise ValueError("Harness requires a command template")

    values = {
        "{prompt}": prompt,
        "{model}": role.model,
        "{profile}": role.profile,
        "{agent}": role.agent,
    }
    command: list[str] = []

    for token in role.command:
        if token in values:
            value = values[token]
            if value is None:
                if command and command[-1].startswith("--"):
                    command.pop()
                continue
            command.append(value)
            continue
        command.append(token)

    return command


def compact_summary(text: str, *, limit: int = 280) -> str | None:
    normalized = _normalized_summary_text(text)
    if not normalized:
        return None
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def summary_was_truncated(text: str, *, limit: int = 280) -> bool:
    normalized = _normalized_summary_text(text)
    return len(normalized) > limit


def _normalized_summary_text(text: str) -> str:
    return " ".join(text.split())
