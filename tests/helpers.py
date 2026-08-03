from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import yaml


def write_runtime_files(
    tmp_path: Path,
    python_executable: str,
    command: list[str],
    *,
    auto_return: bool = True,
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
                "concurrency": {"global": 4, "per_session": 3},
                "auto_return": auto_return,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    prompts_path.write_text("{}\n", encoding="utf-8")
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
