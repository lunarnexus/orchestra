"""Connected automatic verification remaining branches.

Covers the auto-verify branches not yet exercised by the existing
connected-flow tests (tests/test_auto_verify_connected_flow.py):

1. auto_verify disabled → builder success report without verifier.
2. Builder failed → no verifier, report shows failure.
3. Builder ordinary timeout (not budget handoff) → no verifier, report
   shows timeout.
4. Builder cancelled → no verifier, report shows cancel.
5. Verifier reservation/startup failure → builder success preserved,
   verification failure visible in report.
6. Verifier timeout → both terminal, report delivered, no runaway
   recursion (no second verifier).
7. Builder done with negative semantic verdict → verifier still
   dispatched (decided behavior: chain matches on status=done only).

All tests use real core/SQLite/supervisor with controlled fake workers.
Only the host delivery boundary is simulated (Hermes in-process context).
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

import pytest
import yaml

from orchestra.state import (
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_FAILED,
    TERMINAL_STATUSES,
    StateStore,
)
from tests.helpers import wait_for_condition
from tests.test_hermes_plugin_source import FakeHermesPluginContext, load_plugin

_ORIGIN = "hermes:runtime"
ROOT_PROMPTS = Path(__file__).resolve().parents[1] / "prompts.yaml"


def _write_config(
    tmp_path: Path,
    python_executable: str,
    fake_worker_script: Path,
    *,
    auto_verify: bool = True,
    builder_command: list[str] | None = None,
    verifier_command: list[str] | None = None,
    default_timeout: int = 60,
) -> tuple[Path, Path, Path]:
    """Write an isolated config. Returns (config_path, catalog_path, db_path)."""
    state_dir = tmp_path / "state"
    log_dir = tmp_path / "logs"
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"

    config_path.write_text(
        yaml.safe_dump(
            {
                "state_dir": str(state_dir),
                "log_dir": str(log_dir),
                "default_timeout": default_timeout,
                "mode": "on",
                "concurrency": {"global": 4, "per_session": 4},
                "auto_verify": auto_verify,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    prompts_path.write_text(ROOT_PROMPTS.read_text(encoding="utf-8"), encoding="utf-8")

    if builder_command is None:
        builder_command = [
            python_executable,
            str(fake_worker_script),
            "success",
            "--output",
            "builder done",
        ]
    if verifier_command is None:
        verifier_command = [
            python_executable,
            str(fake_worker_script),
            "success",
            "--output",
            "verifier done",
        ]

    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "builder",
                "harness_configs": {
                    "builder_harness": {
                        "harness": "shell",
                        "command": builder_command,
                    },
                    "verifier_harness": {
                        "harness": "shell",
                        "command": verifier_command,
                    },
                },
                "roles": {
                    "builder": {
                        "harness_config": "builder_harness",
                    },
                    "verifier": {
                        "harness_config": "verifier_harness",
                        "enabled": "auto",
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return config_path, catalog_path, state_dir / "orchestra.db"


def _process_alive(process_id: int | None) -> bool:
    if process_id is None:
        return False
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _make_seam(config_dir: str) -> Any:
    def seam_run_orchestra(
        args: list[str],
        *,
        timeout_seconds: int = 300,
        input: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, "-m", "orchestra", "--config", config_dir, *args]
        try:
            return subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                input=input,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            return subprocess.CompletedProcess(
                args=command,
                returncode=124,
                stdout=stdout,
                stderr=f"orchestra command timed out after {timeout_seconds} seconds",
            )

    return seam_run_orchestra


def _processes_dead(proc_id: int | None, sup_pid: int | None) -> bool:
    return not _process_alive(proc_id) and not _process_alive(sup_pid)


def _cleanup_runs(
    seam: Callable[[list[str]], subprocess.CompletedProcess[str]],
    store: StateStore,
    *,
    session_id: str,
    run_ids: list[str],
    timeout: float = 20.0,
) -> None:
    for run_id in run_ids:
        try:
            record = store.get_run(run_id)
            if record.status not in TERMINAL_STATUSES:
                seam(["stop", "--session-id", session_id, "--run-id", run_id])
            proc_id = record.process_id
            sup_pid = record.supervisor_pid
            wait_for_condition(
                partial(_processes_dead, proc_id, sup_pid),
                timeout=timeout,
            )
        except Exception:
            pass


def _assert_no_verifier_runs(store: StateStore, session_id: str) -> None:
    runs = store.list_runs(session_id, limit=10)
    verifier_runs = [r for r in runs if r.trigger_reason == "auto_verify"]
    assert verifier_runs == [], f"Expected no verifier runs, found: {verifier_runs}"


def _assert_report_delivered(
    ctx: FakeHermesPluginContext,
    timeout: float = 30,
) -> str:
    assert wait_for_condition(lambda: bool(ctx.injected), timeout=timeout)
    return next(content for content, _ in ctx.injected)


# ---------------------------------------------------------------------------
# 1. auto_verify off → builder success report without verifier
# ---------------------------------------------------------------------------


def test_auto_verify_off_builder_success_report_without_verifier(
    tmp_path: Path,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """auto_verify disabled: builder done, report delivered without verifier."""
    config_path, _, db_path = _write_config(
        tmp_path,
        python_executable,
        fake_worker_script,
        auto_verify=False,
    )
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    seam = _make_seam(config_dir)
    plugin = load_plugin()
    monkeypatch.setattr(plugin, "_run_orchestra", seam)

    ctx = FakeHermesPluginContext(session_id=_ORIGIN)
    run_ids: list[str] = []
    try:
        ack = plugin._dispatch_orchestra_run({"goal": "ship feature"}, _ORIGIN, ctx=ctx)
        assert isinstance(ack, str) and ack

        runs = store.list_runs(_ORIGIN)
        assert len(runs) == 1
        builder_run_id = runs[0].run_id
        run_ids.append(builder_run_id)

        # Builder reaches terminal (done).
        assert wait_for_condition(
            lambda: store.get_run(builder_run_id).status in TERMINAL_STATUSES, timeout=30
        )
        builder_record = store.get_run(builder_run_id)
        assert builder_record.status == STATUS_DONE

        # No verifier run was created.
        _assert_no_verifier_runs(store, _ORIGIN)

        # Report is delivered immediately (no verifier to wait for).
        injected = _assert_report_delivered(ctx)
        assert builder_run_id in injected
        assert "builder done" in injected
        assert "success" in injected

        # Mark-delivered clears the pending report.
        assert wait_for_condition(
            lambda: store.get_run(builder_run_id).reported_at is not None, timeout=30
        )
        assert store.list_pending_report_runs(_ORIGIN) == []

    finally:
        _cleanup_runs(seam, store, session_id=_ORIGIN, run_ids=run_ids)


# ---------------------------------------------------------------------------
# 2. Builder failed → no verifier, report shows failure
# ---------------------------------------------------------------------------


def test_auto_verify_builder_failed_no_verifier_report_shows_failure(
    tmp_path: Path,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """auto_verify enabled, builder fails: no verifier, report shows failure."""
    config_path, _, db_path = _write_config(
        tmp_path,
        python_executable,
        fake_worker_script,
        auto_verify=True,
        builder_command=[
            python_executable,
            str(fake_worker_script),
            "fail",
            "--output",
            "builder crashed",
        ],
    )
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    seam = _make_seam(config_dir)
    plugin = load_plugin()
    monkeypatch.setattr(plugin, "_run_orchestra", seam)

    ctx = FakeHermesPluginContext(session_id=_ORIGIN)
    run_ids: list[str] = []
    try:
        ack = plugin._dispatch_orchestra_run({"goal": "fix bug"}, _ORIGIN, ctx=ctx)
        assert isinstance(ack, str) and ack

        runs = store.list_runs(_ORIGIN)
        assert len(runs) == 1
        builder_run_id = runs[0].run_id
        run_ids.append(builder_run_id)

        # Builder reaches terminal (failed).
        assert wait_for_condition(
            lambda: store.get_run(builder_run_id).status in TERMINAL_STATUSES, timeout=30
        )
        builder_record = store.get_run(builder_run_id)
        assert builder_record.status == STATUS_FAILED

        # No verifier run was created (chain only matches builder+done).
        _assert_no_verifier_runs(store, _ORIGIN)

        # Report is delivered showing the failure.
        injected = _assert_report_delivered(ctx)
        assert builder_run_id in injected
        assert "fail" in injected

        # Mark-delivered clears the pending report.
        assert wait_for_condition(
            lambda: store.get_run(builder_run_id).reported_at is not None, timeout=30
        )

    finally:
        _cleanup_runs(seam, store, session_id=_ORIGIN, run_ids=run_ids)


# ---------------------------------------------------------------------------
# 3. Builder ordinary timeout (not budget handoff) → no verifier
# ---------------------------------------------------------------------------


def test_auto_verify_builder_timeout_no_verifier_report_shows_timeout(
    tmp_path: Path,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """auto_verify enabled, builder times out (ordinary timeout, not budget
    handoff): no verifier, report shows timeout failure."""
    # Short timeout (3s) with a sleeping worker (30s) → supervisor kills it.
    # This produces STATUS_FAILED with "Worker timed out", NOT STATUS_INCOMPLETE.
    config_path, _, db_path = _write_config(
        tmp_path,
        python_executable,
        fake_worker_script,
        auto_verify=True,
        default_timeout=3,
        builder_command=[
            python_executable,
            str(fake_worker_script),
            "sleep",
            "--sleep",
            "30",
        ],
    )
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    seam = _make_seam(config_dir)
    plugin = load_plugin()
    monkeypatch.setattr(plugin, "_run_orchestra", seam)

    ctx = FakeHermesPluginContext(session_id=_ORIGIN)
    run_ids: list[str] = []
    try:
        ack = plugin._dispatch_orchestra_run({"goal": "slow task"}, _ORIGIN, ctx=ctx)
        assert isinstance(ack, str) and ack

        runs = store.list_runs(_ORIGIN)
        assert len(runs) == 1
        builder_run_id = runs[0].run_id
        run_ids.append(builder_run_id)

        # Builder reaches terminal (failed due to timeout).
        assert wait_for_condition(
            lambda: store.get_run(builder_run_id).status in TERMINAL_STATUSES, timeout=30
        )
        builder_record = store.get_run(builder_run_id)
        # Ordinary timeout → STATUS_FAILED (not STATUS_INCOMPLETE which would
        # indicate a budget handoff).
        assert builder_record.status == STATUS_FAILED
        assert "timed out" in (builder_record.error_text or "").lower()

        # No verifier run was created.
        _assert_no_verifier_runs(store, _ORIGIN)

        # Report is delivered showing the timeout failure.
        injected = _assert_report_delivered(ctx)
        assert builder_run_id in injected
        assert "fail" in injected

        # Mark-delivered clears the pending report.
        assert wait_for_condition(
            lambda: store.get_run(builder_run_id).reported_at is not None, timeout=30
        )

    finally:
        _cleanup_runs(seam, store, session_id=_ORIGIN, run_ids=run_ids)


# ---------------------------------------------------------------------------
# 4. Builder cancelled → no verifier, report shows cancel
# ---------------------------------------------------------------------------


def test_auto_verify_builder_cancelled_no_verifier_report_shows_cancel(
    tmp_path: Path,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """auto_verify enabled, builder cancelled: no verifier, report shows cancel."""
    config_path, _, db_path = _write_config(
        tmp_path,
        python_executable,
        fake_worker_script,
        auto_verify=True,
        default_timeout=60,
        builder_command=[
            python_executable,
            str(fake_worker_script),
            "sleep",
            "--sleep",
            "30",
        ],
    )
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    seam = _make_seam(config_dir)
    plugin = load_plugin()
    monkeypatch.setattr(plugin, "_run_orchestra", seam)

    ctx = FakeHermesPluginContext(session_id=_ORIGIN)
    run_ids: list[str] = []
    try:
        ack = plugin._dispatch_orchestra_run({"goal": "cancel me"}, _ORIGIN, ctx=ctx)
        assert isinstance(ack, str) and ack

        runs = store.list_runs(_ORIGIN)
        assert len(runs) == 1
        builder_run_id = runs[0].run_id
        run_ids.append(builder_run_id)

        # Wait for the builder to be running (worker process started).
        assert wait_for_condition(
            lambda: store.get_run(builder_run_id).status == "running", timeout=30
        )

        # Cancel the run.
        seam(["stop", "--session-id", _ORIGIN, "--run-id", builder_run_id])

        # Builder reaches terminal (cancelled).
        assert wait_for_condition(
            lambda: store.get_run(builder_run_id).status in TERMINAL_STATUSES, timeout=30
        )
        builder_record = store.get_run(builder_run_id)
        assert builder_record.status == STATUS_CANCELLED

        # No verifier run was created.
        _assert_no_verifier_runs(store, _ORIGIN)

        # Report is delivered showing the cancellation.
        injected = _assert_report_delivered(ctx)
        assert builder_run_id in injected

        # Mark-delivered clears the pending report.
        assert wait_for_condition(
            lambda: store.get_run(builder_run_id).reported_at is not None, timeout=30
        )

    finally:
        _cleanup_runs(seam, store, session_id=_ORIGIN, run_ids=run_ids)


# ---------------------------------------------------------------------------
# 5. Verifier reservation/startup failure → builder success preserved
# ---------------------------------------------------------------------------


def test_auto_verify_verifier_startup_failure_preserves_builder_success(
    tmp_path: Path,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """auto_verify enabled, builder done, verifier harness fails to start:
    builder remains done, report shows both builder success and verifier
    failure."""
    # Verifier command points to a non-existent binary → Popen fails.
    config_path, _, db_path = _write_config(
        tmp_path,
        python_executable,
        fake_worker_script,
        auto_verify=True,
        verifier_command=["/nonexistent/binary_that_does_not_exist_xyz"],
    )
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    seam = _make_seam(config_dir)
    plugin = load_plugin()
    monkeypatch.setattr(plugin, "_run_orchestra", seam)

    ctx = FakeHermesPluginContext(session_id=_ORIGIN)
    run_ids: list[str] = []
    try:
        ack = plugin._dispatch_orchestra_run({"goal": "verify me"}, _ORIGIN, ctx=ctx)
        assert isinstance(ack, str) and ack

        runs = store.list_runs(_ORIGIN)
        assert len(runs) == 1
        builder_run_id = runs[0].run_id
        run_ids.append(builder_run_id)

        # Builder reaches terminal (done).
        assert wait_for_condition(
            lambda: store.get_run(builder_run_id).status in TERMINAL_STATUSES, timeout=30
        )
        builder_record = store.get_run(builder_run_id)
        assert builder_record.status == STATUS_DONE

        # Verifier run appears and reaches terminal (failed — startup failure).
        assert wait_for_condition(
            lambda: len(store.list_runs(_ORIGIN, limit=10)) == 2, timeout=15
        )
        all_runs = store.list_runs(_ORIGIN, limit=10)
        verifier_runs = [r for r in all_runs if r.trigger_reason == "auto_verify"]
        assert len(verifier_runs) == 1
        verifier_run = verifier_runs[0]
        run_ids.append(verifier_run.run_id)

        assert verifier_run.role == "verifier"
        assert verifier_run.triggered_by_run_id == builder_run_id

        # Verifier reaches terminal (failed).
        assert wait_for_condition(
            lambda: store.get_run(verifier_run.run_id).status in TERMINAL_STATUSES,
            timeout=30,
        )
        verifier_record = store.get_run(verifier_run.run_id)
        assert verifier_record.status == STATUS_FAILED

        # Builder remains done (verifier failure is non-fatal per D-RETURN-014).
        builder_final = store.get_run(builder_run_id)
        assert builder_final.status == STATUS_DONE

        # Report is delivered showing both outcomes.
        injected = _assert_report_delivered(ctx)
        assert builder_run_id in injected
        assert verifier_run.run_id in injected
        # Builder success is visible.
        assert "builder done" in injected
        # Verifier failure is visible.
        assert "fail" in injected

        # Mark-delivered clears both.
        assert wait_for_condition(
            lambda: store.get_run(builder_run_id).reported_at is not None
            and store.get_run(verifier_run.run_id).reported_at is not None,
            timeout=30,
        )
        assert store.list_pending_report_runs(_ORIGIN) == []

    finally:
        _cleanup_runs(seam, store, session_id=_ORIGIN, run_ids=run_ids)


# ---------------------------------------------------------------------------
# 6. Verifier timeout → both terminal, report delivered, no recursion
# ---------------------------------------------------------------------------


def test_auto_verify_verifier_timeout_report_delivered_no_recursion(
    tmp_path: Path,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """auto_verify enabled, builder done, verifier times out: both terminal,
    report delivered, no recursive verifier dispatch."""
    # Verifier sleeps past the timeout → supervisor kills it → failed.
    config_path, _, db_path = _write_config(
        tmp_path,
        python_executable,
        fake_worker_script,
        auto_verify=True,
        default_timeout=3,
        verifier_command=[
            python_executable,
            str(fake_worker_script),
            "sleep",
            "--sleep",
            "30",
        ],
    )
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    seam = _make_seam(config_dir)
    plugin = load_plugin()
    monkeypatch.setattr(plugin, "_run_orchestra", seam)

    ctx = FakeHermesPluginContext(session_id=_ORIGIN)
    run_ids: list[str] = []
    try:
        ack = plugin._dispatch_orchestra_run({"goal": "timeout verifier"}, _ORIGIN, ctx=ctx)
        assert isinstance(ack, str) and ack

        runs = store.list_runs(_ORIGIN)
        assert len(runs) == 1
        builder_run_id = runs[0].run_id
        run_ids.append(builder_run_id)

        # Builder reaches terminal (done).
        assert wait_for_condition(
            lambda: store.get_run(builder_run_id).status in TERMINAL_STATUSES, timeout=30
        )
        builder_record = store.get_run(builder_run_id)
        assert builder_record.status == STATUS_DONE

        # Verifier run appears.
        assert wait_for_condition(
            lambda: len(store.list_runs(_ORIGIN, limit=10)) == 2, timeout=15
        )
        all_runs = store.list_runs(_ORIGIN, limit=10)
        verifier_runs = [r for r in all_runs if r.trigger_reason == "auto_verify"]
        assert len(verifier_runs) == 1
        verifier_run = verifier_runs[0]
        run_ids.append(verifier_run.run_id)

        # Verifier reaches terminal (failed due to timeout).
        assert wait_for_condition(
            lambda: store.get_run(verifier_run.run_id).status in TERMINAL_STATUSES,
            timeout=30,
        )
        verifier_record = store.get_run(verifier_run.run_id)
        assert verifier_record.status == STATUS_FAILED
        assert "timed out" in (verifier_record.error_text or "").lower()

        # No recursive verifier (no second auto_verify run).
        all_runs_final = store.list_runs(_ORIGIN, limit=10)
        verifier_runs_final = [r for r in all_runs_final if r.trigger_reason == "auto_verify"]
        assert len(verifier_runs_final) == 1, (
            f"Expected exactly 1 verifier run (no recursion), found: {verifier_runs_final}"
        )

        # Builder remains done.
        builder_final = store.get_run(builder_run_id)
        assert builder_final.status == STATUS_DONE

        # Report is delivered showing both outcomes.
        injected = _assert_report_delivered(ctx)
        assert builder_run_id in injected
        assert verifier_run.run_id in injected
        assert "builder done" in injected
        assert "fail" in injected

        # Mark-delivered clears both.
        assert wait_for_condition(
            lambda: store.get_run(builder_run_id).reported_at is not None
            and store.get_run(verifier_run.run_id).reported_at is not None,
            timeout=30,
        )
        assert store.list_pending_report_runs(_ORIGIN) == []

    finally:
        _cleanup_runs(seam, store, session_id=_ORIGIN, run_ids=run_ids)


# ---------------------------------------------------------------------------
# 7. Builder done with negative semantic verdict → verifier still dispatched
# ---------------------------------------------------------------------------


def test_auto_verify_builder_done_negative_verdict_still_dispatches_verifier(
    tmp_path: Path,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Builder is operationally done (exit 0) but has a negative semantic
    verdict. The chain matches on status=done only (decided behavior), so
    the verifier IS dispatched. The verifier's request context includes the
    negative verdict."""
    # Builder outputs "Status: complete\nVerdict: fail" and exits 0.
    builder_command = [
        python_executable,
        "-c",
        'print("Status: complete"); print("Verdict: fail")',
    ]
    config_path, _, db_path = _write_config(
        tmp_path,
        python_executable,
        fake_worker_script,
        auto_verify=True,
        builder_command=builder_command,
    )
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    seam = _make_seam(config_dir)
    plugin = load_plugin()
    monkeypatch.setattr(plugin, "_run_orchestra", seam)

    ctx = FakeHermesPluginContext(session_id=_ORIGIN)
    run_ids: list[str] = []
    try:
        ack = plugin._dispatch_orchestra_run({"goal": "negative verdict"}, _ORIGIN, ctx=ctx)
        assert isinstance(ack, str) and ack

        # The builder is fast (prints two lines and exits), so the verifier may
        # already be dispatched by the time we check. Find the builder run.
        assert wait_for_condition(
            lambda: len(store.list_runs(_ORIGIN, limit=10)) >= 1, timeout=10
        )
        all_runs = store.list_runs(_ORIGIN, limit=10)
        builder_runs = [r for r in all_runs if r.role == "builder"]
        assert len(builder_runs) == 1
        builder_run_id = builder_runs[0].run_id
        run_ids.append(builder_run_id)

        # Builder reaches terminal (done — exit 0 with meaningful output).
        assert wait_for_condition(
            lambda: store.get_run(builder_run_id).status in TERMINAL_STATUSES, timeout=30
        )
        builder_record = store.get_run(builder_run_id)
        assert builder_record.status == STATUS_DONE
        # The semantic verdict is "fail" (parsed from the worker output).
        assert builder_record.semantic_verdict == "fail"

        # Verifier IS dispatched (chain matches on status=done, not verdict).
        assert wait_for_condition(
            lambda: len(store.list_runs(_ORIGIN, limit=10)) == 2, timeout=15
        )
        all_runs = store.list_runs(_ORIGIN, limit=10)
        verifier_runs = [r for r in all_runs if r.trigger_reason == "auto_verify"]
        assert len(verifier_runs) == 1
        verifier_run = verifier_runs[0]
        run_ids.append(verifier_run.run_id)

        # The verifier's request context includes the negative verdict.
        verifier_request_path = (
            tmp_path / "state" / "runs" / verifier_run.run_id / "request.json"
        )
        assert verifier_request_path.exists()
        verifier_request = yaml.safe_load(verifier_request_path.read_text(encoding="utf-8"))
        assert "fail" in verifier_request["additional_context"]

        # Wait for the verifier to reach terminal.
        assert wait_for_condition(
            lambda: store.get_run(verifier_run.run_id).status in TERMINAL_STATUSES,
            timeout=30,
        )

        # Report is delivered.
        injected = _assert_report_delivered(ctx)
        assert builder_run_id in injected
        assert verifier_run.run_id in injected

        # Mark-delivered clears both.
        assert wait_for_condition(
            lambda: store.get_run(builder_run_id).reported_at is not None
            and store.get_run(verifier_run.run_id).reported_at is not None,
            timeout=30,
        )

    finally:
        _cleanup_runs(seam, store, session_id=_ORIGIN, run_ids=run_ids)
