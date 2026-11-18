"""Shared harness plugin contract for Orchestra 2.

One plugin per supported runtime implements this contract: run the assigned
work, cooperatively ask it to wrap up, and hard-terminate it. The dispatcher
owns budget clocks and decisions; plugins own launch, signaling, and kill
mechanics. This module never reads configuration or the job queue; budgets
arrive as arguments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class HarnessError(ValueError):
    """Raised when a harness plugin cannot launch or execute assigned work."""


@dataclass(frozen=True)
class Budgets:
    """Execution budgets taken verbatim from the job record values."""

    soft_timeout: int | None = None
    hard_timeout: int | None = None
    turn_limit: int | None = None


@dataclass(frozen=True)
class CommandJob:
    """A job executed as an external command; assignment text is argv data."""

    job_id: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class Outcome:
    """Result of one execution.

    ``success`` is False for nonzero exit status, termination, or hard
    timeout. ``exit_status`` is None when the process did not exit on its
    own (terminated or killed). ``output`` and ``error`` carry captured
    stdout and stderr. ``transcript`` locates the harness's native
    transcript; None when the harness has none (shell commands).
    ``started_at``/``finished_at`` are wall-clock Unix timestamps.
    ``reason`` is the harness-owned diagnostic for a failed run (a budget
    wrap-up or a rejected prompt); the dispatcher records it before the
    queue releases dependents, so guidance and follow-ups read the real
    reason without waiting for the run to end.
    """

    success: bool
    exit_status: int | None
    output: str
    error: str
    started_at: float
    finished_at: float
    terminated: bool = False
    transcript: str | None = None
    reason: str | None = None


@runtime_checkable
class Handle(Protocol):
    """Execution state the dispatcher can use between contract calls."""


@runtime_checkable
class Harness(Protocol):
    """Contract every harness plugin implements."""

    def execute(
        self, job: CommandJob, budgets: Budgets, handle: Handle | None = None
    ) -> Outcome:
        """Run the job to completion and return the outcome.

        ``handle`` lets the dispatcher hold execution state before the call
        returns, so it can request wrap-up or terminate while the job runs.
        Passing None has the plugin create its own handle.
        """
        ...

    def new_handle(self) -> Handle:
        """Return a fresh handle the dispatcher can pass to execute."""
        ...

    def request_wrap_up(self, handle: Handle) -> None:
        """Cooperatively ask a running job to wrap up; no-op where meaningless."""
        ...

    def terminate(self, handle: Handle) -> None:
        """Hard-terminate a running job, including its process group."""
        ...
