"""Shared harness helpers for prompt, command, and summary handling."""

from __future__ import annotations

from orchestra.config import RoleConfig
from orchestra.harnesses.base import WorkerRequest


def render_worker_prompt(request: WorkerRequest, role: RoleConfig) -> str:
    prompts = request.prompts
    sections = [
        f"{prompts.worker_role_label}: {request.role_name}",
        f"{prompts.worker_goal_label}: {request.goal.strip()}",
    ]
    if role.prompt_addition:
        sections.append(
            f"{prompts.worker_role_instructions_label}: {role.prompt_addition.strip()}"
        )
    if request.approved_context.strip():
        sections.append(
            f"{prompts.worker_approved_context_label}: {request.approved_context.strip()}"
        )
    if request.boundaries.strip():
        sections.append(f"{prompts.worker_boundaries_label}: {request.boundaries.strip()}")
    if request.acceptance_target.strip():
        sections.append(
            f"{prompts.worker_acceptance_target_label}: {request.acceptance_target.strip()}"
        )

    return_format = request.return_format.strip() or prompts.default_return_format
    sections.append(f"{prompts.worker_return_format_label}: {return_format}")
    return "\n\n".join(sections)


def expand_command_template(role: RoleConfig, prompt: str) -> list[str]:
    if not role.command:
        raise ValueError("Harness requires a command template")

    values = {
        "{prompt}": prompt,
        "{model}": role.model,
        "{profile}": role.profile,
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
    if not text:
        return None
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."
