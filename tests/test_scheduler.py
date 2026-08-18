from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from tests.helpers import default_prompts_text, run_cli


def test_global_concurrency_limit_is_atomic(
    tmp_path: Path,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "state_dir": str(tmp_path / "state"),
                "log_dir": str(tmp_path / "logs"),
                "default_timeout": 30,
                "concurrency": {"global": 1, "per_session": 1},
                "auto_return": True,
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
                "roles": {
                    "worker": {
                        "harness": "pi",
                        "command": [
                            python_executable,
                            str(fake_worker_script),
                            "sleep",
                            "--sleep",
                            "2",
                            "--output",
                            "slept",
                        ],
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    def invoke(session_id: str) -> tuple[int, str]:
        result = run_cli(
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            session_id,
            "--goal",
            f"goal {session_id}",
        )
        return result.returncode, result.stdout + result.stderr

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(invoke, "manual:a")
        second = pool.submit(invoke, "manual:b")
        results = [first.result(), second.result()]

    codes = sorted(code for code, _ in results)
    assert codes == [0, 1]


def test_per_session_concurrency_limit_is_atomic(
    tmp_path: Path,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "state_dir": str(tmp_path / "state"),
                "log_dir": str(tmp_path / "logs"),
                "default_timeout": 30,
                "concurrency": {"global": 4, "per_session": 1},
                "auto_return": True,
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
                "roles": {
                    "worker": {
                        "harness": "pi",
                        "command": [
                            python_executable,
                            str(fake_worker_script),
                            "sleep",
                            "--sleep",
                            "2",
                            "--output",
                            "slept",
                        ],
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    def invoke() -> tuple[int, str]:
        result = run_cli(
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:shared",
            "--goal",
            "same session",
        )
        return result.returncode, result.stdout + result.stderr

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(invoke).result(), pool.submit(invoke).result()]

    codes = sorted(code for code, _ in results)
    assert codes == [0, 1]
