from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from orchestra.app import init_pi
from tests.helpers import wait_for_condition
from tests.types import RuntimeFilesFactory


@pytest.mark.skipif(shutil.which("pi") is None, reason="pi executable not found")
def test_pi_extension_host_command_path(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "adapter ok"],
    )
    pi_dir = tmp_path / "pi-agent"
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(pi_dir))
    init_pi(source_root=Path(__file__).resolve().parents[1])
    session_id = f"orch-host-e2e-{uuid.uuid4().hex}"
    env = {
        **os.environ,
        "ORCHESTRA_CONFIG": str(config_path),
        "ORCHESTRA_AGENT_CATALOG": str(catalog_path),
        "PI_CODING_AGENT_DIR": str(pi_dir),
    }

    help_result = subprocess.run(
        [
            "pi",
            "--no-approve",
            "--session-id",
            session_id,
            "-p",
            "/orch help",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert help_result.returncode == 0
    help_output = help_result.stdout + help_result.stderr
    assert "Orchestra commands:" in help_output
    assert "Configured roles" in help_output
    assert "D worker  pi" in help_output

    doctor = subprocess.run(
        [
            "pi",
            "--no-approve",
            "--session-id",
            session_id,
            "-p",
            "/orch doctor",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert doctor.returncode == 0
    assert "config: ok" in doctor.stdout or "config: ok" in doctor.stderr

    dispatch = subprocess.run(
        [
            "pi",
            "--no-approve",
            "--session-id",
            session_id,
            "-p",
            '/orch do --task-label "adapter task" adapter e2e worker',
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert dispatch.returncode == 0
    assert "orchestra dispatched:" in dispatch.stdout or "orchestra dispatched:" in dispatch.stderr

    def history_contains_result() -> bool:
        result = subprocess.run(
            [
                "pi",
                "--no-approve",
                "--session-id",
                session_id,
                "-p",
                "/orch history 10",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        output = result.stdout + result.stderr
        return "adapter ok" in output and "adapter task" in output

    history_ready = wait_for_condition(history_contains_result, timeout=8)
    assert history_ready
