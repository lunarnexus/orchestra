"""Harness plugin interfaces for worker runtimes."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from orchestra.config import PromptConfig, RoleConfig


@dataclass(frozen=True)
class WorkerRequest:
    role_name: str
    goal: str
    timeout_seconds: int
    run_id: str = ""
    approved_context: str = ""
    boundaries: str = ""
    acceptance_target: str = ""
    return_format: str = ""
    task_label: str = ""
    worker_budget: int | None = None
    turn_limit: int | None = None
    soft_timeout: int | None = None
    budget_exceeded_prompt: str = ""
    log_path: Path | None = None
    skill_roots: tuple[Path, ...] = ()
    prompts: PromptConfig = PromptConfig()


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
    result_summary_truncated: bool = False
    timed_out: bool = False
    worker_session_id: str | None = None
    transcript_path: Path | None = None
    approval_needed: bool = False


class Harness(Protocol):
    name: str

    def build_prompt(self, request: WorkerRequest, role: RoleConfig) -> str: ...

    def build_command(self, role: RoleConfig, prompt: str) -> list[str]: ...

    def start(self, request: WorkerRequest, role: RoleConfig) -> WorkerProcess: ...


class HarnessLoadError(KeyError):
    """Raised when a configured harness cannot be loaded."""


class HarnessRegistry:
    def __init__(self) -> None:
        self._harnesses: dict[str, Harness] = {}
        self._loaders: dict[str, Callable[[], Harness]] = {}

    def register(self, harness: Harness) -> None:
        self._harnesses[harness.name] = harness
        self._loaders.pop(harness.name, None)

    def register_loader(self, name: str, loader: Callable[[], Harness]) -> None:
        self._loaders[name] = loader

    def get(self, name: str) -> Harness:
        if name not in self._harnesses and name in self._loaders:
            self._harnesses[name] = self._load(name)
        try:
            return self._harnesses[name]
        except KeyError as exc:
            raise KeyError(f"unknown harness: {name}") from exc

    def _load(self, name: str) -> Harness:
        loader = self._loaders[name]
        try:
            harness = loader()
        except Exception as exc:
            raise HarnessLoadError(f"failed to load harness: {name}: {exc}") from exc
        if harness.name != name:
            raise HarnessLoadError(
                f"loaded harness name mismatch: expected {name!r}, got {harness.name!r}"
            )
        return harness
