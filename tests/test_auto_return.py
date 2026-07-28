from __future__ import annotations

from pathlib import Path

from orchestra.app import await_session_report, consume_pending_session_report, load_context
from orchestra.state import STATUS_DONE, StateStore
from tests.helpers import extract_run_id, run_cli, wait_for_condition
from tests.types import RuntimeFilesFactory


def test_auto_return_enabled_exposes_one_pending_report(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "done"],
        auto_return=True,
    )

    result = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "do",
        "--session-id",
        "manual:auto",
        "--goal",
        "auto-return",
    )
    run_id = extract_run_id(result.stdout)

    store = StateStore(db_path)
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_DONE, timeout=5)

    context = load_context(config_path=config_path, catalog_path=catalog_path)
    report = consume_pending_session_report(context, "manual:auto")
    assert report is not None
    assert run_id in report
    assert consume_pending_session_report(context, "manual:auto") is None


def test_await_session_report_returns_once_final_run_completes(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "sleep", "--sleep", "0.3", "--output", "done"],
        auto_return=True,
    )

    result = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "do",
        "--session-id",
        "manual:await",
        "--goal",
        "await report",
    )
    run_id = extract_run_id(result.stdout)

    context = load_context(config_path=config_path, catalog_path=catalog_path)
    report = await_session_report(context, "manual:await", run_id=run_id, timeout_seconds=5)
    assert report is not None
    assert run_id in report

    store = StateStore(db_path)
    assert store.get_run(run_id).status == STATUS_DONE
    assert consume_pending_session_report(context, "manual:await") is None


def test_auto_return_disabled_stays_quiet(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "done"],
        auto_return=False,
    )

    result = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "do",
        "--session-id",
        "manual:no-auto",
        "--goal",
        "no auto-return",
    )
    run_id = extract_run_id(result.stdout)

    store = StateStore(db_path)
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_DONE, timeout=5)

    context = load_context(config_path=config_path, catalog_path=catalog_path)
    assert consume_pending_session_report(context, "manual:no-auto") is None
