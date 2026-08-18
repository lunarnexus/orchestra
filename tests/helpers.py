from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import yaml

from orchestra.config import PromptConfig


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
    prompts_path.write_text(default_prompts_text(), encoding="utf-8")
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


def default_prompts_text() -> str:
    return (Path(__file__).parents[1] / "src/orchestra/assets/prompts.yaml").read_text(
        encoding="utf-8"
    )


def default_prompt_config() -> PromptConfig:
    prompts = yaml.safe_load(default_prompts_text())
    return PromptConfig(
        default_return_format=prompts["default_return_format"],
        tool_description=prompts["tool_description"],
        tool_prompt_snippet=prompts["tool_prompt_snippet"],
        tool_prompt_guidelines=tuple(prompts["tool_prompt_guidelines"]),
        tool_goal_description=prompts["tool_goal_description"],
        tool_role_description=prompts["tool_role_description"],
        tool_task_label_description=prompts["tool_task_label_description"],
        status_description=prompts["status_description"],
        status_action_description=prompts["status_action_description"],
        status_limit_description=prompts["status_limit_description"],
        status_run_id_description=prompts["status_run_id_description"],
        status_role_description=prompts["status_role_description"],
        status_setting_description=prompts["status_setting_description"],
        status_value_description=prompts["status_value_description"],
        host_help=prompts["host_help"],
        budget_exceeded_prompt=prompts["budget_exceeded_prompt"],
    )


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
