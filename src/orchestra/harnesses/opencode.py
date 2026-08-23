"""OpenCode one-shot harness implementation."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from orchestra.harnesses.subprocess import Starter, SubprocessHarness, WorkerSessionMode


@dataclass
class OpenCodeHarness(SubprocessHarness):
    starter: Starter = subprocess.Popen
    name: str = "opencode"
    worker_session_mode: WorkerSessionMode = "none"
