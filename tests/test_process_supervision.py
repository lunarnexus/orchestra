from __future__ import annotations

from pathlib import Path

import yaml

from orchestra.state import STATUS_CANCELLED, STATUS_FAILED, StateStore
from tests.helpers import extract_run_id, run_cli, wait_for_condition
from tests.types import RuntimeFilesFactory


def test_stop_terminates_owned_worker_process(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    marker = tmp_path / "marker.txt"
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [
            python_executable,
            str(fake_worker_script),
            "sleep",
            "--sleep",
            "10",
            "--marker",
            str(marker),
            "--output",
            "finished",
        ],
    )

    result = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "do",
        "--session-id",
        "manual:proc",
        "--goal",
        "Run a long worker.",
    )
    assert result.returncode == 0
    run_id = extract_run_id(result.stdout)

    assert wait_for_condition(marker.exists, timeout=5)
    store = StateStore(db_path)
    assert wait_for_condition(lambda: store.get_run(run_id).status == "running", timeout=5)

    stop = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "stop",
        "--session-id",
        "manual:proc",
        "--run-id",
        run_id,
    )
    assert stop.returncode == 0
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_CANCELLED, timeout=5)

    record = store.get_run(run_id)
    assert record.blocker_text == "Cancelled by orchestra stop"
    assert record.process_id is not None


def test_timeout_marks_run_failed_and_keeps_terminal_state(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "sleep", "--sleep", "3", "--output", "late"],
    )

    result = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "do",
        "--session-id",
        "manual:timeout",
        "--goal",
        "Run a timeout worker.",
        "--timeout",
        "1",
    )
    assert result.returncode == 0
    run_id = extract_run_id(result.stdout)

    store = StateStore(db_path)
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_FAILED, timeout=5)

    record = store.get_run(run_id)
    assert record.blocker_text == "Worker exceeded timeout"
    assert record.error_text == "Worker timed out"

    history = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "history",
        "--session-id",
        "manual:timeout",
    )
    assert history.returncode == 0
    assert "Worker exceeded timeout" in history.stdout


def test_unknown_harness_marks_run_failed_and_clears_active_queue(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "unused"],
    )
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "roles": {
                    "worker": {
                        "harness": "missing",
                        "command": [
                            python_executable,
                            str(fake_worker_script),
                            "success",
                            "--output",
                            "unused",
                        ],
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "do",
        "--session-id",
        "manual:missing-harness",
        "--goal",
        "Run a worker with missing harness.",
    )
    assert result.returncode == 0
    run_id = extract_run_id(result.stdout)

    store = StateStore(db_path)
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_FAILED, timeout=5)

    record = store.get_run(run_id)
    assert record.error_text == "unknown harness: missing"
    assert record.blocker_text == "Worker harness is not configured"
    assert store.list_active_runs("manual:missing-harness") == []
    assert store.list_active_runs() == []
    assert (tmp_path / "state" / "requests" / f"{run_id}.json").exists() is False

    status = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "status",
        "--session-id",
        "manual:missing-harness",
    )
    assert status.returncode == 0
    assert "active_runs: 0" in status.stdout
    assert "status: no active runs" in status.stdout
