"""Focused recovery-flow tests: supervisor launch failure and stale queued reconciliation."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from orchestra.artifacts import canonical_return_path
from orchestra.context import load_context
from orchestra.dispatch import start_run
from orchestra.state import (
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    TERMINAL_STATUSES,
    RunRecord,
    RunUpdate,
    StateStore,
)
from orchestra.supervision import reconcile_stale_queued_runs, run_supervisor_guarded
from tests.types import RuntimeFilesFactory


def test_supervisor_launch_failure_releases_capacity(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Supervisor Popen OSError -> terminal FAILED in SQLite, capacity slot freed."""
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "unused"],
    )
    context = load_context(config_path=config_path, catalog_path=catalog_path)

    # Fault injection: make subprocess.Popen raise OSError in _spawn_supervisor.
    def _failing_popen(*args: object, **kwargs: object) -> subprocess.Popen[str]:
        raise OSError("injected launch failure")

    monkeypatch.setattr("orchestra.supervision.subprocess.Popen", _failing_popen)

    started = start_run(
        context,
        session_id="manual:recovery",
        role_name=None,
        goal="recovery launch test",
        additional_context="",
        boundaries="",
        acceptance_target="",
        return_format="",
        timeout_seconds=30,
        task_label="recovery",
        batch_id=None,
    )

    run_id = started.record.run_id
    record = StateStore(db_path).get_run(run_id)
    assert record.status == STATUS_FAILED
    assert record.error_text == "Worker supervisor could not be launched"
    assert record.blocker_text == "Worker supervisor launch failed"
    assert record.ended_at is not None

    # Capacity released: a second run can be reserved in the same session.
    started2 = start_run(
        context,
        session_id="manual:recovery",
        role_name=None,
        goal="second run after failure",
        additional_context="",
        boundaries="",
        acceptance_target="",
        return_format="",
        timeout_seconds=30,
        task_label="recovery2",
        batch_id=None,
    )
    assert started2.record.status == STATUS_QUEUED


def test_stale_queued_run_at_grace_boundary_reconciled(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    """Queued run past grace boundary with no supervisor -> FAILED, retry slot available."""
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "unused"],
    )
    context = load_context(config_path=config_path, catalog_path=catalog_path)

    # Create a queued run whose created_at is exactly at the grace boundary.
    # startup_timeout_seconds=5, created_at = now - 5s (at the boundary).
    now = datetime.now(UTC)
    boundary = (now - timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%S.")
    created_at_boundary = boundary + "000000+00:00"

    context.store.create_run(
        RunRecord(
            run_id="staleboundary1",
            orchestrator_session_id="manual:boundary",
            harness="pi",
            role="worker",
            task_label="boundary test",
            log_path=tmp_path / "logs" / "staleboundary1.jsonl",
            created_at=created_at_boundary,
        )
    )

    # No supervisor_pid: the run never got a supervisor recorded.
    reconciled = reconcile_stale_queued_runs(context, startup_timeout_seconds=5)

    assert len(reconciled) == 1
    record = StateStore(db_path).get_run("staleboundary1")
    assert record.status == STATUS_FAILED
    assert record.error_text == "Worker supervisor ownership was not recorded"
    assert record.blocker_text == "Worker supervisor launch state missing"
    assert record.ended_at is not None

    # Retry slot available: a new run can be reserved in the same session.
    context.store.reserve_run(
        RunRecord(
            run_id="retry-after-boundary",
            orchestrator_session_id="manual:boundary",
            harness="pi",
            role="worker",
            task_label="retry",
            log_path=tmp_path / "logs" / "retry.jsonl",
            created_at=now.strftime("%Y-%m-%dT%H:%M:%S.") + "000000+00:00",
        ),
        global_limit=4,
        per_session_limit=3,
    )


def test_post_reservation_request_write_failure_releases_slot_immediately(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the request file write fails after reserve_run, the slot is released immediately.

    Post-reservation failure terminalizes the run to FAILED, freeing the capacity
    slot so the caller can retry without waiting for reconciliation.
    """
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "unused"],
    )
    context = load_context(config_path=config_path, catalog_path=catalog_path)
    store = context.store

    original_reserve_run = store.reserve_run
    captured_run_dirs: list[Path] = []

    def _fault_reserve_run(
        record: RunRecord,
        *,
        global_limit: int,
        per_session_limit: int,
        per_model_limits: dict[str, int] | None = None,
    ) -> RunRecord:
        result = original_reserve_run(
            record,
            global_limit=global_limit,
            per_session_limit=per_session_limit,
            per_model_limits=per_model_limits,
        )
        # Make the run directory read-only to cause a real filesystem fault
        # on the subsequent request file write.
        run_dir = record.log_path.parent
        os.chmod(run_dir, 0o500)
        captured_run_dirs.append(run_dir)
        return result

    monkeypatch.setattr(store, "reserve_run", _fault_reserve_run)

    try:
        try:
            start_run(
                context,
                session_id="manual:write-fault",
                role_name=None,
                goal="write fault test",
                additional_context="",
                boundaries="",
                acceptance_target="",
                return_format="",
                timeout_seconds=30,
                task_label="write-fault",
                batch_id=None,
            )
        except OSError:
            pass  # expected: the request file write fails

        # Desired: the run should be FAILED (slot released), not stuck in QUEUED.
        assert store.count_active_runs("manual:write-fault") == 0, (
            "run not released after request-write failure; slot still occupied"
        )
    finally:
        # Restore permissions so pytest can clean up tmp_path.
        for d in captured_run_dirs:
            os.chmod(d, 0o755)


def test_stale_running_run_dead_pids_reconciles_to_failed(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    """Integration: seeded stale running state with dead PIDs reconciles to FAILED.

    Seeds a RUNNING run record with supervisor/worker PIDs from real short-lived
    processes that have already exited, then exercises
    ``_reconcile_stale_running_run``. This is NOT the actual supervisor-crash
    journey (supervisor spawned, worker started, then supervisor dies); that
    path is owned by a separate test.
    """
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "unused"],
    )
    context = load_context(config_path=config_path, catalog_path=catalog_path)
    store = context.store

    # Spawn two short-lived processes to get deterministic dead PIDs.
    proc_worker = subprocess.Popen([python_executable, "-c", "pass"])
    proc_supervisor = subprocess.Popen([python_executable, "-c", "pass"])
    proc_worker.wait()
    proc_supervisor.wait()
    worker_pid = proc_worker.pid
    supervisor_pid = proc_supervisor.pid

    # Guard: verify both PIDs are actually dead (no startup race).
    for pid in (worker_pid, supervisor_pid):
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)

    now = datetime.now(UTC)
    created_at = now.strftime("%Y-%m-%dT%H:%M:%S.") + "000000+00:00"

    store.create_run(
        RunRecord(
            run_id="crash-after-start",
            orchestrator_session_id="manual:crash",
            harness="pi",
            role="worker",
            task_label="crash test",
            log_path=tmp_path / "logs" / "crash-after-start.jsonl",
            created_at=created_at,
        )
    )
    # Transition to RUNNING with the dead PIDs.
    store.update_run(
        "crash-after-start",
        RunUpdate(
            status=STATUS_RUNNING,
            process_id=worker_pid,
            process_group_id=worker_pid,
            supervisor_pid=supervisor_pid,
            supervisor_started_at=created_at,
        ),
    )

    # Reconcile: both PIDs dead -> stale running run -> FAILED.
    reconciled = reconcile_stale_queued_runs(context)

    assert len(reconciled) == 1
    record = store.get_run("crash-after-start")
    assert record.status == STATUS_FAILED
    assert record.error_text == "worker process exited/disappeared without terminal status"
    assert record.blocker_text == "stale running worker reconciled"
    assert record.ended_at is not None

    # Capacity released: a new run can be reserved in the same session.
    store.reserve_run(
        RunRecord(
            run_id="after-crash",
            orchestrator_session_id="manual:crash",
            harness="pi",
            role="worker",
            task_label="after crash",
            log_path=tmp_path / "logs" / "after-crash.jsonl",
            created_at=now.strftime("%Y-%m-%dT%H:%M:%S.") + "000000+00:00",
        ),
        global_limit=4,
        per_session_limit=3,
    )


def test_artifact_write_then_terminal_db_update_failure_recovers(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the terminal DB update fails after the artifact is written, the guarded handler recovers.

    Proves: (1) the artifact is durably on disk, (2) the exception is visible
    and caught by run_supervisor_guarded, (3) the run ends FAILED via the
    guarded recovery path, (4) capacity is released.
    """
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "unused"],
    )
    context = load_context(config_path=config_path, catalog_path=catalog_path)
    store = context.store

    now = datetime.now(UTC)
    created_at = now.strftime("%Y-%m-%dT%H:%M:%S.") + "000000+00:00"
    run_id = "artifact-db-fault"

    store.create_run(
        RunRecord(
            run_id=run_id,
            orchestrator_session_id="manual:artifact-fault",
            harness="pi",
            role="worker",
            task_label="artifact fault test",
            log_path=tmp_path / "logs" / f"{run_id}.jsonl",
            created_at=created_at,
        )
    )

    # Write a valid request file for the supervisor to load.
    request_file = tmp_path / "state" / "runs" / run_id / "request.json"
    request_file.parent.mkdir(parents=True, exist_ok=True)
    request_file.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "role_name": "worker",
                "goal": "test goal",
                "additional_context": "",
                "boundaries": "",
                "acceptance_target": "",
                "return_format": "",
                "timeout_seconds": 30,
                "task_label": "artifact fault test",
            }
        ),
        encoding="utf-8",
    )

    # Patch update_run to fail on the first terminal update (from _finalize_run).
    # The guarded handler's subsequent update will succeed.
    first_terminal_update_failed = False
    original_update_run = store.update_run

    def _patched_update_run(rid: str, update: RunUpdate) -> RunRecord:
        nonlocal first_terminal_update_failed
        if update.status in TERMINAL_STATUSES and not first_terminal_update_failed:
            first_terminal_update_failed = True
            raise OSError("simulated terminal DB update failure")
        return original_update_run(rid, update)

    monkeypatch.setattr(store, "update_run", _patched_update_run)

    # Call the guarded supervisor directly (in-process, no subprocess).
    record = run_supervisor_guarded(context, run_id=run_id, request_file=request_file)

    # The guarded handler recovered: run is FAILED.
    assert record.status == STATUS_FAILED
    assert record.error_text == "Worker supervisor failed before completing run"
    assert record.blocker_text == "Worker supervisor failure"
    assert record.ended_at is not None

    # The artifact was durably written before the DB failure.
    return_path = canonical_return_path(context.config.state_dir, run_id)
    assert return_path.exists()
    assert return_path.read_text(encoding="utf-8").strip() != ""

    # Capacity released: a new run can be reserved in the same session.
    store.reserve_run(
        RunRecord(
            run_id="after-artifact-fault",
            orchestrator_session_id="manual:artifact-fault",
            harness="pi",
            role="worker",
            task_label="after fault",
            log_path=tmp_path / "logs" / "after-artifact-fault.jsonl",
            created_at=now.strftime("%Y-%m-%dT%H:%M:%S.") + "000000+00:00",
        ),
        global_limit=4,
        per_session_limit=3,
    )
