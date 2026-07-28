"""Pi one-shot harness implementation."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Protocol

from orchestra.config import RoleConfig
from orchestra.harnesses.base import WorkerProcess, WorkerRequest

DEFAULT_RETURN_FORMAT = (
    "Return a concise response with success/fail, files changed/inspected, "
    "if fail: exact commands run, results, if blockers: blockers, if risks: risks"
)


class Starter(Protocol):
    def __call__(
        self,
        args: list[str],
        *,
        stdout: int,
        stderr: int,
        text: bool,
        start_new_session: bool,
    ) -> subprocess.Popen[str]: ...


@dataclass
class PiHarness:
    starter: Starter = subprocess.Popen
    name: str = "pi"

    def build_prompt(self, request: WorkerRequest, role: RoleConfig) -> str:
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

        return_format = request.return_format.strip() or DEFAULT_RETURN_FORMAT
        sections.append(f"Return format: {return_format}")
        return "\n\n".join(sections)

    def build_command(self, role: RoleConfig, prompt: str) -> list[str]:
        if not role.command:
            raise ValueError("Pi harness requires a command template")

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

    def start(self, request: WorkerRequest, role: RoleConfig) -> WorkerProcess:
        prompt = self.build_prompt(request, role)
        command = self.build_command(role, prompt)
        process = self.starter(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=_supports_process_groups(),
        )
        return WorkerProcess(
            process=process,
            command=command,
            prompt=prompt,
        )


def compact_summary(text: str, *, limit: int = 280) -> str | None:
    if not text:
        return None
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def process_group_id(process_id: int) -> int | None:
    if not _supports_process_groups():
        return None
    try:
        return os.getpgid(process_id)
    except OSError:
        return None


def _supports_process_groups() -> bool:
    return os.name != "nt"
