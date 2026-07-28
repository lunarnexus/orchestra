from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml


def test_python_module_do_smoke(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"

    config_path.write_text(
        yaml.safe_dump(
            {
                "state_dir": str(tmp_path / "state"),
                "log_dir": str(tmp_path / "logs"),
                "default_timeout": 30,
                "concurrency": {"global": 4, "per_session": 3},
                "auto_return": True,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "roles": {
                    "worker": {
                        "harness": "pi",
                        "command": [
                            sys.executable,
                            "-c",
                            "print('smoke ok')",
                        ],
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "orchestra",
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:smoke",
            "--goal",
            "Run a smoke worker.",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "dispatch: queued for supervision" in result.stdout
