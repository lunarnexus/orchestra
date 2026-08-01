"""Shared harness helpers for prompt, command, and summary handling."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from orchestra.config import RoleConfig
from orchestra.harnesses.base import WorkerRequest

ORCHESTRA_WORKER_ENV = "ORCHESTRA_WORKER"
SKILL_LIBRARY_DIR = "skills"
SKILL_FILENAME = "SKILL.md"


def orchestra_worker_budget(env: Mapping[str, str] | None = None) -> int:
    raw = (env or os.environ).get(ORCHESTRA_WORKER_ENV)
    if raw is None or not raw.strip():
        return 0
    try:
        budget = int(raw.strip())
    except ValueError:
        return 1
    return max(budget, 0)


def orchestra_can_dispatch(env: Mapping[str, str] | None = None) -> bool:
    return orchestra_worker_budget(env) != 1


def worker_subprocess_env(
    *,
    worker_budget: int | None = None,
    role_env: Mapping[str, str] | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    worker_env = dict(env or os.environ)
    worker_env.update(role_env or {})
    current_budget = orchestra_worker_budget(worker_env)
    configured_budget = worker_budget or 1
    if current_budget > 1:
        child_budget = min(current_budget - 1, configured_budget)
    else:
        child_budget = configured_budget
    worker_env[ORCHESTRA_WORKER_ENV] = str(child_budget)
    return worker_env


def render_worker_prompt(request: WorkerRequest, role: RoleConfig) -> str:
    prompts = request.prompts
    sections = [
        f"Role: {request.role_name}",
    ]
    sections.extend(_role_skill_sections(role.skills))
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


def _role_skill_sections(skill_names: tuple[str, ...]) -> list[str]:
    sections: list[str] = []
    for skill_name in skill_names:
        skill_path = _find_project_skill(skill_name)
        if skill_path is not None:
            sections.append(
                f"Role skill: {skill_name}\n\n"
                f"{skill_path.read_text(encoding='utf-8').strip()}"
            )
        else:
            sections.append(
                f"Role skill: {skill_name}\n"
                f"Load the native skill named '{skill_name}' before doing the task."
            )
    return sections


def _find_project_skill(skill_name: str) -> Path | None:
    candidate = Path.cwd() / SKILL_LIBRARY_DIR / skill_name / SKILL_FILENAME
    if candidate.is_file():
        return candidate
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
