from __future__ import annotations

from pathlib import Path

import pytest

from orchestra.state import STATUS_DONE, StateStore
from tests.helpers import extract_run_id, wait_for_condition
from tests.types import RuntimeFilesFactory


def test_do_status_history_flow(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "worker done"],
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:test-session",
            "--goal",
            "Summarize repository status.",
        ]
    )
    do_output = capsys.readouterr().out

    assert exit_code == 0
    assert "dispatch: queued for supervision" in do_output
    run_id = extract_run_id(do_output)

    assert wait_for_condition(
        lambda: StateStore(db_path).get_run(run_id).status == STATUS_DONE,
        timeout=5,
    )

    history_exit = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "history",
            "--session-id",
            "manual:test-session",
        ]
    )
    history_output = capsys.readouterr().out

    assert history_exit == 0
    assert "history_count: 1" in history_output
    assert "worker done" in history_output


def test_roles_lists_configured_worker_roles(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, _ = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success"],
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "roles",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "roles:" in output
    assert "- worker harness=pi" in output


def test_status_reports_active_run(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "sleep", "--sleep", "2", "--output", "slept"],
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:test-session",
            "--goal",
            "Run a long worker.",
        ]
    )
    do_output = capsys.readouterr().out
    run_id = extract_run_id(do_output)

    assert exit_code == 0
    assert wait_for_condition(
        lambda: StateStore(db_path).get_run(run_id).status == "running",
        timeout=5,
    )

    status_exit = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "status",
            "--session-id",
            "manual:test-session",
        ]
    )
    status_output = capsys.readouterr().out

    assert status_exit == 0
    assert "active_runs: 1" in status_output
    assert run_id in status_output


def test_stop_command_enforces_ownership(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, _ = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success"],
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "stop",
            "--session-id",
            "manual:other",
            "--run-id",
            "missing",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "run not found" in captured.out


def test_doctor_command_checks_local_setup(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, _ = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success"],
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "doctor",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "config: ok" in captured.out
    assert "agent_catalog: ok" in captured.out
    assert "database: ok" in captured.out
    assert "harness:worker: ok" in captured.out
