from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from orchestra.app import (
    await_session_report_payload,
    consume_pending_session_report,
    load_context,
    mark_session_report_delivered,
)
from orchestra.state import STATUS_DONE, STATUS_RUNNING, RunRecord, RunUpdate, StateStore
from tests.helpers import extract_run_id, run_cli, wait_for_condition
from tests.types import RuntimeFilesFactory


def _create_terminal_run(
    store: StateStore,
    tmp_path: Path,
    *,
    run_id: str,
    session_id: str,
) -> None:
    store.create_run(
        RunRecord(
            run_id=run_id,
            orchestrator_session_id=session_id,
            batch_id=None,
            harness="pi",
            role="worker",
            status="queued",
            created_at="2026-07-31T00:00:00Z",
            task_label="await report",
            log_path=tmp_path / "logs" / f"{run_id}.jsonl",
        )
    )
    store.update_run(run_id, RunUpdate(status=STATUS_RUNNING, process_id=1234))
    store.update_run(run_id, RunUpdate(status=STATUS_DONE, result_summary="done"))


class FlakyGetRunStore:
    def __init__(
        self,
        wrapped: StateStore,
        error: sqlite3.OperationalError,
        *,
        failures_before_success: int | None = 1,
    ) -> None:
        self.wrapped = wrapped
        self.error = error
        self.failures_before_success = failures_before_success
        self.get_run_calls = 0

    def get_run(self, run_id: str) -> RunRecord:
        self.get_run_calls += 1
        if (
            self.failures_before_success is None
            or self.get_run_calls <= self.failures_before_success
        ):
            raise self.error
        return self.wrapped.get_run(run_id)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.wrapped, name)


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
    report = await_session_report_payload(
        context,
        "manual:await",
        run_id=run_id,
        timeout_seconds=5,
    )
    assert report is not None
    assert run_id in report.text
    assert report.run_ids == [run_id]

    store = StateStore(db_path)
    assert store.get_run(run_id).status == STATUS_DONE
    assert consume_pending_session_report(context, "manual:await") is None

    mark_session_report_delivered(context, "manual:await", report.run_ids)
    assert consume_pending_session_report(context, "manual:await") is None


def test_await_session_report_retries_transient_database_open_failure(
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
    store = StateStore(db_path)
    store.initialize()
    _create_terminal_run(store, tmp_path, run_id="run-transient", session_id="manual:await")
    context = load_context(config_path=config_path, catalog_path=catalog_path)
    flaky_store = FlakyGetRunStore(
        context.store,
        sqlite3.OperationalError("unable to open database file"),
    )

    report = await_session_report_payload(
        replace(context, store=cast(StateStore, flaky_store)),
        "manual:await",
        run_id="run-transient",
        poll_interval=0,
        timeout_seconds=1,
    )

    assert report is not None
    assert report.run_ids == ["run-transient"]
    assert "[orchestra: Worker run-transient success]" in report.text
    assert flaky_store.get_run_calls == 2


def test_await_session_report_surfaces_non_transient_database_error(
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
    store = StateStore(db_path)
    store.initialize()
    _create_terminal_run(store, tmp_path, run_id="run-non-transient", session_id="manual:await")
    context = load_context(config_path=config_path, catalog_path=catalog_path)
    flaky_store = FlakyGetRunStore(
        context.store,
        sqlite3.OperationalError("database disk image is malformed"),
    )

    with pytest.raises(sqlite3.OperationalError, match="database disk image is malformed"):
        await_session_report_payload(
            replace(context, store=cast(StateStore, flaky_store)),
            "manual:await",
            run_id="run-non-transient",
            poll_interval=0,
            timeout_seconds=1,
        )

    assert flaky_store.get_run_calls == 1


@pytest.mark.parametrize(
    ("timeout_seconds", "expected_get_run_calls"),
    [(None, 4), (0.0, 1)],
)
def test_await_session_report_reraises_persistent_database_open_failure(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    timeout_seconds: float | None,
    expected_get_run_calls: int,
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "done"],
        auto_return=True,
    )
    store = StateStore(db_path)
    store.initialize()
    _create_terminal_run(store, tmp_path, run_id="run-persistent", session_id="manual:await")
    context = load_context(config_path=config_path, catalog_path=catalog_path)
    flaky_store = FlakyGetRunStore(
        context.store,
        sqlite3.OperationalError("unable to open database file"),
        failures_before_success=None,
    )

    with pytest.raises(sqlite3.OperationalError, match="unable to open database file"):
        await_session_report_payload(
            replace(context, store=cast(StateStore, flaky_store)),
            "manual:await",
            run_id="run-persistent",
            poll_interval=0,
            timeout_seconds=timeout_seconds,
        )

    assert flaky_store.get_run_calls == expected_get_run_calls


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
