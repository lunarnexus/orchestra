"""Incomplete budget-handoff functional tests.

Two connected Hermes builder journeys exercising the real incomplete/budget-handoff
path with auto_verify enabled: the real Hermes plugin dispatch entry point and
report watcher drive the real Orchestra CLI/core/SQLite with an isolated config,
a real detached supervisor, and a controlled fake subagent. Only the host delivery
boundary is simulated (the in-process host context that receives the injected
report).

Journey 1: builder zero-exit with explicit incomplete budget handoff marker.
  The worker prints the incomplete marker + handoff and exits 0. The supervisor
  classifies the run as INCOMPLETE. The auto-verify chain does NOT trigger (it
  only matches builder+done), so no verifier child is spawned. The consolidated
  report carries the budget_exceeded outcome with the continuation hint.

Journey 2: builder emits the same handoff then outlives the configured hard
  timeout. The timeout handling recovers the incomplete marker from the flushed
  stdout and preserves INCOMPLETE (not ordinary FAILED). No verifier child.

Both journeys prove: the worker truly ran (non-None PID, actual process death);
the incomplete terminal state; the original partial output and handoff in the
full return.md; the semantic report budget_exceeded outcome with the expected
fixture guidance/blocker/continuation; no verifier child; capacity released;
origin-only host acceptance; and actual mark-delivered/pending cleared.

Limitations: this proves host-context delivery into the simulated Hermes
context, not live-chat delivery or model consumption. It does not prove
exactly-once delivery (a next watcher can redeliver an unmarked report).
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from orchestra.state import (
    STATUS_INCOMPLETE,
    TERMINAL_STATUSES,
    StateStore,
)
from tests.helpers import wait_for_condition
from tests.test_hermes_plugin_source import FakeHermesPluginContext, load_plugin

_ORIGIN = "hermes:runtime"
_OTHER = "hermes:other"
ROOT_PROMPTS = Path(__file__).resolve().parents[1] / "prompts.yaml"

_HANDOFF_OUTPUT = (
    "ORCHESTRA_STATUS: incomplete\n"
    "ORCHESTRA_STOP_REASON: budget_exceeded\n"
    "## Budget Handoff\n"
    "Completed:\n"
    "- one slice\n"
    "Remaining:\n"
    "- next slice\n"
)


def _write_config(
    tmp_path: Path,
    python_executable: str,
    fake_worker_script: Path,
    *,
    worker_args: list[str],
    default_timeout: int = 60,
) -> tuple[Path, Path, Path]:
    """Write an isolated config with auto_verify enabled and builder+verifier roles.

    Returns (config_path, catalog_path, db_path).
    """
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
                "auto_verify": True,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    prompts_path.write_text(ROOT_PROMPTS.read_text(encoding="utf-8"), encoding="utf-8")

    builder_command = [
        python_executable,
        str(fake_worker_script),
        *worker_args,
    ]
    verifier_command = [
        python_executable,
        str(fake_worker_script),
        "success",
        "--output",
        "verifier ok",
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
    """Runner seam: invoke the real Orchestra CLI with the isolated config."""

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


def _gate_mark(
    plugin: Any, monkeypatch: pytest.MonkeyPatch
) -> tuple[threading.Event, threading.Event]:
    """Gate the real core mark-delivered so the unreported-before-acceptance state
    is observable deterministically. The real mark still runs once released."""
    mark_reached = threading.Event()
    proceed_mark = threading.Event()
    real_mark = plugin._mark_session_report_delivered

    def gated_mark(runtime_session_id: str, run_ids: list[str]) -> Any:
        mark_reached.set()
        proceed_mark.wait(timeout=30)
        return real_mark(runtime_session_id, run_ids)

    monkeypatch.setattr(plugin, "_mark_session_report_delivered", gated_mark)
    return mark_reached, proceed_mark


def _injected_report(ctx: FakeHermesPluginContext, run_id: str) -> str:
    return next(content for content, _ in ctx.injected if run_id in content)


def _cleanup_one_run(
    seam: Callable[[list[str]], subprocess.CompletedProcess[str]],
    store: StateStore,
    *,
    session_id: str,
    run_id: str,
    timeout: float = 20.0,
) -> None:
    try:
        record = store.get_run(run_id)
        if record.status not in TERMINAL_STATUSES:
            seam(["stop", "--session-id", session_id, "--run-id", run_id])
        wait_for_condition(
            lambda: (
                not _process_alive(store.get_run(run_id).process_id)
                and not _process_alive(store.get_run(run_id).supervisor_pid)
            ),
            timeout=timeout,
        )
    except Exception:
        pass


def _cleanup_runs(
    seam: Callable[[list[str]], subprocess.CompletedProcess[str]],
    store: StateStore,
    *,
    session_id: str,
    run_ids: list[str],
    timeout: float = 20.0,
) -> None:
    """Owner-scoped cleanup: stop any still-active runs and wait bounded for
    worker/supervisor termination. Never raises, so cleanup cannot mask the
    original test failure."""
    for run_id in run_ids:
        _cleanup_one_run(seam, store, session_id=session_id, run_id=run_id, timeout=timeout)


def _assert_no_verifier_child(store: StateStore, session_id: str, builder_run_id: str) -> None:
    """Assert no verifier child was spawned (auto-verify chain only matches builder+done)."""
    all_runs = store.list_runs(session_id, limit=10)
    verifier_runs = [
        run for run in all_runs if run.trigger_reason == "auto_verify"
    ]
    assert len(verifier_runs) == 0, (
        f"Expected no verifier child, but found: {[r.run_id for r in verifier_runs]}"
    )
    assert len(all_runs) == 1, (
        f"Expected exactly one run (the builder), but found {len(all_runs)}"
    )


def test_incomplete_budget_handoff_zero_exit_full_journey(
    tmp_path: Path,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Journey 1: builder zero-exit with explicit incomplete budget handoff.

    The worker prints the incomplete marker + handoff and exits 0. The supervisor
    classifies the run as INCOMPLETE. No verifier child is spawned. The report
    carries the budget_exceeded outcome with the continuation hint.
    """
    config_path, _, db_path = _write_config(
        tmp_path,
        python_executable,
        fake_worker_script,
        worker_args=["success", "--output", _HANDOFF_OUTPUT],
        default_timeout=60,
    )
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    seam = _make_seam(config_dir)
    plugin = load_plugin()
    monkeypatch.setattr(plugin, "_run_orchestra", seam)
    mark_reached, proceed_mark = _gate_mark(plugin, monkeypatch)

    ctx = FakeHermesPluginContext(session_id=_ORIGIN)
    run_id: str | None = None
    try:
        ack = plugin._dispatch_orchestra_run(
            {"goal": "ship the incomplete slice"}, _ORIGIN, ctx=ctx
        )
        assert isinstance(ack, str) and ack

        # The accepted run belongs to the runtime originating session.
        runs = store.list_runs(_ORIGIN)
        assert len(runs) == 1
        run_id = runs[0].run_id
        record = store.get_run(run_id)
        assert record.orchestrator_session_id == _ORIGIN
        assert record.role == "builder"

        # The worker truly ran: the supervisor recorded a real worker process.
        assert wait_for_condition(
            lambda: store.get_run(run_id).status in TERMINAL_STATUSES, timeout=30
        )
        record = store.get_run(run_id)
        assert record.status == STATUS_INCOMPLETE
        assert record.process_id is not None
        assert record.supervisor_pid is not None

        # The incomplete budget handoff blocker is set.
        assert record.blocker_text == "Worker budget exceeded; redispatch from continuation handoff"

        # The full return artifact preserves the original partial output and handoff.
        return_path = tmp_path / "state" / "runs" / run_id / "return.md"
        assert return_path.exists()
        return_text = return_path.read_text(encoding="utf-8")
        assert "ORCHESTRA_STATUS: incomplete" in return_text
        assert "ORCHESTRA_STOP_REASON: budget_exceeded" in return_text
        assert "## Budget Handoff" in return_text
        assert "one slice" in return_text
        assert "next slice" in return_text

        # No verifier child was spawned (auto-verify chain only matches builder+done).
        _assert_no_verifier_child(store, _ORIGIN, run_id)

        # The host context receives the report; the mark is gated, so the report
        # must still be unreported (host accepted delivery, core has not claimed it).
        assert mark_reached.wait(timeout=30)
        assert ctx.injected
        assert store.get_run(run_id).reported_at is None
        assert any(run.run_id == run_id for run in store.list_pending_report_runs(_ORIGIN))

        # Correct semantic consolidated report: budget_exceeded outcome with the
        # continuation hint, not a success or generic fail outcome.
        report = _injected_report(ctx, run_id)
        assert f"{run_id} budget_exceeded]" in report
        assert "Worker budget exceeded; redispatch from continuation handoff" in report
        assert "pass this return_path handoff artifact to a smaller continuation dispatch" in report
        assert "preserve completed work and do not repeat it" in report
        assert f"{run_id} success]" not in report
        assert f"{run_id} fail]" not in report

        # Origin-only host acceptance: another session cannot retrieve or mark it.
        assert not any(run.run_id == run_id for run in store.list_pending_report_runs(_OTHER))
        store.mark_report_runs_delivered(_OTHER, [run_id])
        assert store.get_run(run_id).reported_at is None

        # Release the barrier: the real core mark-delivered runs.
        proceed_mark.set()
        assert wait_for_condition(
            lambda: store.get_run(run_id).reported_at is not None, timeout=30
        )

        # Pending report disappears after successful host acceptance.
        assert not any(run.run_id == run_id for run in store.list_pending_report_runs(_ORIGIN))

        # Capacity released and worker/supervisor terminated.
        assert store.count_active_runs(_ORIGIN) == 0
        final = store.get_run(run_id)
        assert final.process_id is not None
        assert final.supervisor_pid is not None
        assert wait_for_condition(
            lambda: not _process_alive(final.supervisor_pid), timeout=15
        )
        assert wait_for_condition(
            lambda: not _process_alive(final.process_id), timeout=15
        )
    finally:
        proceed_mark.set()
        if run_id is not None:
            _cleanup_runs(seam, store, session_id=_ORIGIN, run_ids=[run_id])


def test_incomplete_budget_handoff_timeout_preserves_incomplete_full_journey(
    tmp_path: Path,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Journey 2: builder emits the same handoff then outlives the configured hard
    timeout. The timeout handling recovers the incomplete marker from the flushed
    stdout and preserves INCOMPLETE (not ordinary FAILED). No verifier child.

    The barrier file proves the handoff was flushed before the timeout fired.
    """
    flush_marker = tmp_path / "handoff_flush_marker"
    config_path, _, db_path = _write_config(
        tmp_path,
        python_executable,
        fake_worker_script,
        worker_args=[
            "handoff_sleep",
            "--output",
            _HANDOFF_OUTPUT,
            "--sleep",
            "120",
            "--marker",
            str(flush_marker),
        ],
        default_timeout=3,
    )
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    seam = _make_seam(config_dir)
    plugin = load_plugin()
    monkeypatch.setattr(plugin, "_run_orchestra", seam)
    mark_reached, proceed_mark = _gate_mark(plugin, monkeypatch)

    ctx = FakeHermesPluginContext(session_id=_ORIGIN)
    run_id: str | None = None
    try:
        ack = plugin._dispatch_orchestra_run(
            {"goal": "ship the timeout incomplete slice"}, _ORIGIN, ctx=ctx
        )
        assert isinstance(ack, str) and ack

        # The accepted run belongs to the runtime originating session.
        runs = store.list_runs(_ORIGIN)
        assert len(runs) == 1
        run_id = runs[0].run_id
        record = store.get_run(run_id)
        assert record.orchestrator_session_id == _ORIGIN
        assert record.role == "builder"

        # Bounded synchronization: the flush marker proves the handoff was flushed
        # before the timeout fired.
        assert wait_for_condition(
            lambda: (
                flush_marker.exists()
                and flush_marker.read_text(encoding="utf-8") == "flushed\n"
            ),
            timeout=30,
        )

        # The worker truly ran: the supervisor recorded a real worker process before
        # the hard timeout fired.
        assert wait_for_condition(
            lambda: store.get_run(run_id).status in TERMINAL_STATUSES, timeout=30
        )
        record = store.get_run(run_id)
        # The timeout handling preserves INCOMPLETE, not ordinary FAILED.
        assert record.status == STATUS_INCOMPLETE
        assert record.process_id is not None
        assert record.supervisor_pid is not None

        # The incomplete budget handoff blocker is set (same as zero-exit variant).
        assert record.blocker_text == "Worker budget exceeded; redispatch from continuation handoff"

        # The full return artifact preserves the original partial output and handoff.
        return_path = tmp_path / "state" / "runs" / run_id / "return.md"
        assert return_path.exists()
        return_text = return_path.read_text(encoding="utf-8")
        assert "ORCHESTRA_STATUS: incomplete" in return_text
        assert "ORCHESTRA_STOP_REASON: budget_exceeded" in return_text
        assert "## Budget Handoff" in return_text
        assert "one slice" in return_text
        assert "next slice" in return_text

        # No verifier child was spawned (auto-verify chain only matches builder+done).
        _assert_no_verifier_child(store, _ORIGIN, run_id)

        # The host context receives the report; the mark is gated, so the report
        # must still be unreported.
        assert mark_reached.wait(timeout=30)
        assert ctx.injected
        assert store.get_run(run_id).reported_at is None
        assert any(run.run_id == run_id for run in store.list_pending_report_runs(_ORIGIN))

        # Correct semantic consolidated report: budget_exceeded outcome with the
        # continuation hint, not a success or generic fail outcome.
        report = _injected_report(ctx, run_id)
        assert f"{run_id} budget_exceeded]" in report
        assert "Worker budget exceeded; redispatch from continuation handoff" in report
        assert "pass this return_path handoff artifact to a smaller continuation dispatch" in report
        assert "preserve completed work and do not repeat it" in report
        assert f"{run_id} success]" not in report
        assert f"{run_id} fail]" not in report

        # Origin-only host acceptance: another session cannot retrieve or mark it.
        assert not any(run.run_id == run_id for run in store.list_pending_report_runs(_OTHER))
        store.mark_report_runs_delivered(_OTHER, [run_id])
        assert store.get_run(run_id).reported_at is None

        # Release the barrier: the real core mark-delivered runs.
        proceed_mark.set()
        assert wait_for_condition(
            lambda: store.get_run(run_id).reported_at is not None, timeout=30
        )

        # Pending report disappears after successful host acceptance.
        assert not any(run.run_id == run_id for run in store.list_pending_report_runs(_ORIGIN))

        # Capacity released and the timed-out worker process group terminated.
        assert store.count_active_runs(_ORIGIN) == 0
        final = store.get_run(run_id)
        assert final.process_id is not None
        assert final.supervisor_pid is not None
        assert wait_for_condition(
            lambda: not _process_alive(final.supervisor_pid), timeout=15
        )
        assert wait_for_condition(
            lambda: not _process_alive(final.process_id), timeout=15
        )
    finally:
        proceed_mark.set()
        if run_id is not None:
            _cleanup_runs(seam, store, session_id=_ORIGIN, run_ids=[run_id])
