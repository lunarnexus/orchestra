from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from orchestra.admission import admit_run
from orchestra.config import AppConfig
from orchestra.jobs import JobQueue, Limits
from orchestra.state import RunRecord, StateStore

ROOT_PROMPTS = Path(__file__).resolve().parents[1] / "prompts.yaml"


def write_runtime_files(
    tmp_path: Path,
    python_executable: str,
    command: list[str],
) -> tuple[Path, Path, Path]:
    state_dir = tmp_path / "state"
    log_dir = tmp_path / "logs"
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"

    config_path.write_text(
        yaml.safe_dump(
            {
                "state_dir": str(state_dir),
                "log_dir": str(log_dir),
                "default_timeout": 30,
                "mode": "on",
                "concurrency": {"global": 4, "per_session": 3},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    prompts_path.write_text(ROOT_PROMPTS.read_text(encoding="utf-8"), encoding="utf-8")
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "worker",
                "harness_configs": {
                    "pi": {
                        "harness": "pi",
                        "command": command,
                    }
                },
                "roles": {
                    "worker": {
                        "harness_config": "pi",
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return config_path, catalog_path, state_dir / "orchestra.db"


def wait_for_condition(
    predicate: Callable[[], bool],
    *,
    timeout: float = 5.0,
    interval: float = 0.05,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "orchestra", *args],
        check=False,
        capture_output=True,
        text=True,
    )


def extract_run_id(output: str) -> str:
    return next(
        line.split(": ", 1)[1]
        for line in output.splitlines()
        if line.startswith("run_id:")
    )


def make_jobs(store: Any, config: AppConfig) -> JobQueue:
    """Build the durable job queue sharing ``store``'s database with ``config`` limits.

    Mirrors :func:`orchestra.context.load_context` so tests exercise the same
    admission policy the runtime uses.
    """
    queue = JobQueue(store.database_path)
    queue.initialize(
        Limits(
            global_limit=config.concurrency.global_limit,
            per_owner_limit=config.concurrency.per_session_limit,
        )
    )
    return queue


def seed_run(jobs: JobQueue, store: StateStore, record: RunRecord) -> RunRecord:
    """Create ``record`` together with its admitted queue job.

    Run rows never exist without a claim after the job-queue cutover, so tests
    that need a pre-existing run admit it the same way dispatch does.
    """
    admit_run(jobs, store, record)
    return record
