"""Crash and cancel artifact flow tests.

Test 1: Actual supervisor crash → reconcile → terminal failed report.
Test 2: Controlled worker partial output → real cancel → terminal cancelled report.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from orchestra.admission import admit_run
from orchestra.artifacts import canonical_return_path
from orchestra.context import load_context
from orchestra.dispatch import start_run
from orchestra.state import (
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_RUNNING,
    RunRecord,
)
from orchestra.supervision import reconcile_stale_queued_runs, stop_run
from tests.helpers import run_cli, wait_for_condition
from tests.types import RuntimeFilesFactory


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _is_dead_or_zombie(pid: int) -> bool:
    """Check if a process is gone or a zombie (works for non-child PIDs)."""
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "stat="],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0:
            return True  # process not found
        return "Z" in result.stdout  # zombie
    except (subprocess.TimeoutExpired, OSError):
        return False


def _wait_for_dead(pid: int, timeout: float = 10.0) -> bool:
    """Wait for a process to exit, handling both child and non-child PIDs."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # Try waitpid first (reaps zombies for direct children)
        try:
            wpid, _ = os.waitpid(pid, os.WNOHANG)
            if wpid != 0:
                return True
        except ChildProcessError:
            pass  # not our child or already reaped
        except OSError:
            return False
        # Check for gone or zombie (covers non-child PIDs)
        if _is_dead_or_zombie(pid):
            return True
        time.sleep(0.1)
    return False


def _cleanup_pids(*pids: int | None) -> None:
    """Kill only the recorded PIDs and reap zombies; never a global kill."""
    for pid in pids:
        if pid is None:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(pid, os.WNOHANG)
        except (ChildProcessError, OSError):
            pass


def test_supervisor_crash_reconciles_to_failed_with_report(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    """Actual supervisor crash: kill supervisor after worker started, reconcile to FAILED.

    Proves: (1) real supervisor + worker PIDs are recorded live, (2) killing only
    the supervisor leaves the worker running in its own session, (3) after both
    die, reconciliation marks the run FAILED with correct error semantics, (4)
    capacity is released, (5) the report includes the accepted run_id and failure
    semantics.
    """
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [
            python_executable,
            str(fake_worker_script),
            "sleep",
            "--sleep",
            "3",
            "--output",
            "crash-test-worker",
        ],
    )
    context = load_context(config_path=config_path, catalog_path=catalog_path)
    store = context.store

    run_id: str | None = None
    supervisor_pid: int | None = None
    worker_pid: int | None = None

    try:
        started = start_run(
            context,
            session_id="manual:crash",
            role_name=None,
            goal="crash test",
            additional_context="",
            boundaries="",
            acceptance_target="",
            return_format="",
            timeout_seconds=30,
            task_label="crash",
            batch_id=None,
        )
        run_id = started.record.run_id

        assert wait_for_condition(
            lambda: store.get_run(run_id).status == STATUS_RUNNING,
            timeout=10,
        ), "run did not reach RUNNING state"

        record = store.get_run(run_id)
        supervisor_pid = record.supervisor_pid
        worker_pid = record.process_id
        assert supervisor_pid is not None, "supervisor_pid not recorded"
        assert worker_pid is not None, "worker process_id not recorded"
        assert _process_alive(supervisor_pid), "supervisor not alive"
        assert _process_alive(worker_pid), "worker not alive"

        # Kill ONLY the supervisor (SIGKILL for deterministic termination).
        # The worker is in its own session and continues running until its
        # 3s sleep expires.
        os.kill(supervisor_pid, signal.SIGKILL)
        assert _wait_for_dead(supervisor_pid, timeout=5), "supervisor did not die"

        # Wait for the worker to finish naturally.
        assert _wait_for_dead(worker_pid, timeout=10), "worker did not die"

        # Both PIDs dead → reconcile to FAILED.
        reconciled = reconcile_stale_queued_runs(context)
        assert len(reconciled) == 1, f"expected 1 reconciled, got {len(reconciled)}"

        final_record = store.get_run(run_id)
        assert final_record.status == STATUS_FAILED
        assert final_record.error_text == (
            "worker process exited/disappeared without terminal status"
        )
        assert final_record.blocker_text == "stale running worker reconciled"
        assert final_record.ended_at is not None

        # Report includes the accepted run_id and failure semantics.
        # (Must check before reserving a new run, since pending-report
        # requires no active runs in the session.)
        report = run_cli(
            "--config",
            str(config_path.parent),
            "_pending-report",
            "--session-id",
            "manual:crash",
        )
        assert report.returncode == 0
        assert f"[orchestra: worker {run_id} fail]" in report.stdout
        assert f"status: {STATUS_FAILED}" in report.stdout
        assert f"run_id: {run_id}" in report.stdout

        # Capacity released: a new run can be reserved in the same session.
        now = datetime.now(UTC)
        admit_run(
            context.jobs,
            context.store,
            RunRecord(
                run_id="after-crash-retry",
                orchestrator_session_id="manual:crash",
                harness="pi",
                role="worker",
                task_label="after crash",
                log_path=tmp_path / "logs" / "after-crash-retry.jsonl",
                created_at=now.strftime("%Y-%m-%dT%H:%M:%S.") + "000000+00:00",
            ),
        )

    finally:
        _cleanup_pids(supervisor_pid, worker_pid)


def test_cancel_preserves_partial_output_in_return(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
) -> None:
    """Worker outputs unique partial stdout/stderr, stays running, then is cancelled.

    Proves: (1) the partial output was actually emitted before cancel (marker file),
    (2) the run reaches terminal CANCELLED via real stop_run, (3) the report
    includes the run_id and cancelled status, (4) return.md preserves the partial
    output (strict xfail if the known cancellation-skip-artifact defect is present).
    """
    marker_path = tmp_path / "worker_marker.txt"
    worker_script = tmp_path / "partial_worker.py"
    worker_script.write_text(
        "import signal, sys, time\n"
        "print('UNIQUE_PARTIAL_STDOUT_MARKER', flush=True)\n"
        "print('UNIQUE_PARTIAL_STDERR_MARKER', file=sys.stderr, flush=True)\n"
        f"open({str(marker_path)!r}, 'w').write('flushed\\n')\n"
        "def _h(s, f):\n"
        "    raise SystemExit(143)\n"
        "signal.signal(signal.SIGTERM, _h)\n"
        "signal.signal(signal.SIGINT, _h)\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )

    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(worker_script)],
    )
    context = load_context(config_path=config_path, catalog_path=catalog_path)
    store = context.store

    run_id: str | None = None
    supervisor_pid: int | None = None
    worker_pid: int | None = None

    try:
        started = start_run(
            context,
            session_id="manual:cancel",
            role_name=None,
            goal="cancel test",
            additional_context="",
            boundaries="",
            acceptance_target="",
            return_format="",
            timeout_seconds=30,
            task_label="cancel",
            batch_id=None,
        )
        run_id = started.record.run_id

        assert wait_for_condition(
            lambda: store.get_run(run_id).status == STATUS_RUNNING,
            timeout=10,
        ), "run did not reach RUNNING state"

        record = store.get_run(run_id)
        supervisor_pid = record.supervisor_pid
        worker_pid = record.process_id
        assert supervisor_pid is not None
        assert worker_pid is not None

        # Verify the partial output was actually emitted (prerequisite).
        assert wait_for_condition(marker_path.exists, timeout=5), (
            "worker did not emit partial output before cancel"
        )

        # Real cancel via stop_run.
        stop_run(context, "manual:cancel", run_id)

        assert wait_for_condition(
            lambda: store.get_run(run_id).status == STATUS_CANCELLED,
            timeout=10,
        ), "run did not reach CANCELLED state"

        final_record = store.get_run(run_id)
        assert final_record.status == STATUS_CANCELLED
        assert final_record.blocker_text == "Cancelled by orchestra stop"

        # Report includes the run_id and cancelled status.
        report = run_cli(
            "--config",
            str(config_path.parent),
            "_pending-report",
            "--session-id",
            "manual:cancel",
        )
        assert report.returncode == 0
        assert f"[orchestra: worker {run_id} fail]" in report.stdout
        assert f"status: {STATUS_CANCELLED}" in report.stdout
        assert f"run_id: {run_id}" in report.stdout

        # Check return.md for partial output preservation.
        # The supervisor writes return.md asynchronously after the worker exits.
        return_path = canonical_return_path(context.config.state_dir, run_id)
        assert wait_for_condition(return_path.exists, timeout=10), (
            "return.md not written for cancelled run; "
            "cancellation skips return artifact"
        )
        content = return_path.read_text(encoding="utf-8")
        assert "UNIQUE_PARTIAL_STDOUT_MARKER" in content, (
            "partial stdout not preserved in return.md"
        )
        assert "UNIQUE_PARTIAL_STDERR_MARKER" in content, (
            "partial stderr not preserved in return.md"
        )

    finally:
        _cleanup_pids(supervisor_pid, worker_pid)
