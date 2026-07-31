from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

from orchestra.state import StateStore
from tests.types import RuntimeFilesFactory


def test_read_only_status_does_not_run_schema_writes_under_held_writer(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "ok"],
    )
    StateStore(db_path).initialize()

    writer = sqlite3.connect(db_path, timeout=1)
    writer.execute("BEGIN IMMEDIATE")
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "orchestra",
                "--config",
                str(config_path),
                "--agent-catalog",
                str(catalog_path),
                "status",
                "--session-id",
                "manual:read-lock",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    finally:
        writer.rollback()
        writer.close()

    assert result.returncode == 0
    assert "status: no active runs" in result.stdout


def test_begin_immediate_retries_transient_lock(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    _, _, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "ok"],
    )
    store = StateStore(db_path)
    store.initialize()

    attempts = 0
    original_delay = store._connect_retry_delay_seconds

    def release_after_first_retry(attempt: int) -> float:
        nonlocal attempts
        attempts += 1
        writer.rollback()
        writer.close()
        return 0.0

    writer = sqlite3.connect(db_path, timeout=1)
    writer.execute("BEGIN IMMEDIATE")
    store._connect_retry_delay_seconds = release_after_first_retry  # type: ignore[method-assign]
    try:
        with store._connect() as connection:
            store._begin_immediate(connection, operation="test")
            connection.rollback()

        assert attempts == 1
    finally:
        store._connect_retry_delay_seconds = original_delay  # type: ignore[method-assign]
