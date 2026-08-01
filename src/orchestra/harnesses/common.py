"""Shared harness helpers for prompt, command, and summary handling."""

from __future__ import annotations

from orchestra.config import RoleConfig
from orchestra.harnesses.base import WorkerRequest


def render_worker_prompt(request: WorkerRequest, role: RoleConfig) -> str:
    prompts = request.prompts
    sections = [
        f"Role: {request.role_name}",
        f"Goal: {request.goal.strip()}",
    ]
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
    if not text:
        return None
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."
