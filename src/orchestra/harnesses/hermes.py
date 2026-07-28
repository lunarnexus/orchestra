"""Hermes one-shot harness implementation."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Protocol

from orchestra.config import RoleConfig
from orchestra.harnesses.base import WorkerProcess, WorkerRequest
from orchestra.harnesses.common import expand_command_template, render_worker_prompt
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
    ) -> subprocess.Popen[str]: ...


@dataclass
class HermesHarness:
    starter: Starter = subprocess.Popen
    name: str = "hermes"

    def build_prompt(self, request: WorkerRequest, role: RoleConfig) -> str:
        return render_worker_prompt(request, role)

    def build_command(self, role: RoleConfig, prompt: str) -> list[str]:
        return expand_command_template(role, prompt)

    def start(self, request: WorkerRequest, role: RoleConfig) -> WorkerProcess:
        prompt = self.build_prompt(request, role)
        command = self.build_command(role, prompt)
        process = self.starter(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=supports_process_groups(),
        )
        return WorkerProcess(
            process=process,
            command=command,
            prompt=prompt,
        )
