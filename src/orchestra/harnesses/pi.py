"""Pi one-shot harness implementation."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Protocol

from orchestra.config import RoleConfig
from orchestra.harnesses.base import WorkerProcess, WorkerRequest
from orchestra.harnesses.common import (
    expand_command_template,
    render_worker_prompt,
    worker_subprocess_env,
)
from orchestra.harnesses.processes import supports_process_groups


class Starter(Protocol):
    def __call__(
        self,
        args: list[str],
        *,
        stdout: int,
        stderr: int,
        text: bool,
        start_new_session: bool,
        env: dict[str, str],
    ) -> subprocess.Popen[str]: ...


@dataclass
class PiHarness:
    starter: Starter = subprocess.Popen
    name: str = "pi"

    def build_prompt(self, request: WorkerRequest, role: RoleConfig) -> str:
        return render_worker_prompt(request, role)

    def build_command(self, role: RoleConfig, prompt: str) -> list[str]:
        return expand_command_template(role, prompt)

    def start(self, request: WorkerRequest, role: RoleConfig) -> WorkerProcess:
        prompt = self.build_prompt(request, role)
        worker_session_id = _worker_session_id(request)
        command = _with_worker_session(self.build_command(role, prompt), worker_session_id)
        process = self.starter(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=supports_process_groups(),
            env=worker_subprocess_env(
                worker_budget=request.worker_budget,
                turn_limit=request.turn_limit,
                soft_timeout=request.soft_timeout,
                budget_exceeded_prompt=request.budget_exceeded_prompt,
                role_env=role.env,
            ),
        )
        return WorkerProcess(
            process=process,
            command=command,
            prompt=prompt,
            worker_session_id=worker_session_id,
        )


def _worker_session_id(request: WorkerRequest) -> str | None:
    return f"orchestra-worker-{request.run_id}" if request.run_id else None


def _with_worker_session(command: list[str], worker_session_id: str | None) -> list[str]:
    if worker_session_id is None or not command or not _is_pi_command(command[0]):
        return command
    stripped = [token for token in command if token != "--no-session"]
    if _has_session_arg(stripped):
        return stripped
    return [stripped[0], "--session-id", worker_session_id, *stripped[1:]]


def _is_pi_command(executable: str) -> bool:
    return executable == "pi" or executable.endswith("/pi")


def _has_session_arg(command: list[str]) -> bool:
    return any(token in {"--session", "--session-id"} for token in command)
