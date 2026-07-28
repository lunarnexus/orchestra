"""Harness plugin interfaces for worker runtimes."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from orchestra.config import RoleConfig


@dataclass(frozen=True)
class WorkerRequest:
    role_name: str
    goal: str
    approved_context: str = ""
    boundaries: str = ""
    acceptance_target: str = ""
    return_format: str = ""
    timeout_seconds: int = 600
    task_label: str = ""
    log_path: Path | None = None


@dataclass
class WorkerProcess:
    process: subprocess.Popen[str]
    command: list[str]
    prompt: str
    worker_session_id: str | None = None
    transcript_path: Path | None = None
    approval_needed: bool = False


@dataclass(frozen=True)
class WorkerResult:
    status: str
    command: list[str]
    prompt: str
    exit_code: int | None
    stdout: str
    stderr: str
    result_summary: str | None
    error_text: str | None
    blocker_text: str | None
    timed_out: bool = False
    worker_session_id: str | None = None
    transcript_path: Path | None = None
    approval_needed: bool = False


class Harness(Protocol):
    name: str

    def build_prompt(self, request: WorkerRequest, role: RoleConfig) -> str: ...

    def build_command(self, role: RoleConfig, prompt: str) -> list[str]: ...

    def start(self, request: WorkerRequest, role: RoleConfig) -> WorkerProcess: ...


class HarnessRegistry:
    def __init__(self) -> None:
        self._harnesses: dict[str, Harness] = {}

    def register(self, harness: Harness) -> None:
        self._harnesses[harness.name] = harness

    def get(self, name: str) -> Harness:
        try:
            return self._harnesses[name]
        except KeyError as exc:
            raise KeyError(f"unknown harness: {name}") from exc
