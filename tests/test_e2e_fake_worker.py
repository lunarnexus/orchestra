from __future__ import annotations

from pathlib import Path

from orchestra.state import STATUS_CANCELLED, StateStore
from tests.helpers import extract_run_id, run_cli, wait_for_condition
from tests.types import RuntimeFilesFactory


def test_fake_worker_e2e_stop_history_and_pending_report(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "sleep", "--sleep", "5", "--output", "late"],
    )

    do = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "do",
        "--session-id",
        "manual:e2e",
        "--goal",
        "long running task",
    )
    assert do.returncode == 0
    run_id = extract_run_id(do.stdout)

    status = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "status",
        "--session-id",
        "manual:e2e",
    )
    assert status.returncode == 0
    assert run_id in status.stdout

    stop = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "stop",
        "--session-id",
        "manual:e2e",
        "--run-id",
        run_id,
    )
    assert stop.returncode == 0

    store = StateStore(db_path)
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_CANCELLED, timeout=5)

    history = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "history",
        "--session-id",
        "manual:e2e",
    )
    assert history.returncode == 0
    assert "Cancelled by orchestra stop" in history.stdout

    report = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "_pending-report",
        "--session-id",
        "manual:e2e",
    )
    assert report.returncode == 0
    assert f"[orchestra: worker {run_id} fail]" in report.stdout
    assert "Request: long running task" in report.stdout
    assert "Cancelled by orchestra stop" in report.stdout
