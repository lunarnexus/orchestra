"""Failure, timeout, and cancellation functional tests.

Connected journeys for the owner-approved failure/timeout/cancellation slice:
the real Hermes plugin dispatch entry point and report watcher drive the real
Orchestra CLI/core/SQLite with an isolated config, a real detached supervisor,
and a controlled fake subagent. Only the Hermes host-context delivery boundary
is simulated (the in-process host context that receives the injected report).
The runner seam invokes the real ``python -m orchestra`` with the isolated
config; core responses are never stubbed and terminal runs are never seeded by
hand.

Each journey proves: the accepted run belongs to the runtime originating
session; the controlled worker actually launches; the run reaches the expected
terminal outcome (failed/failed/cancelled); the consolidated report is
semantically correct for that outcome; the host accepts delivery and the core
mark-delivered clears the pending report; capacity is released and the
worker/supervisor terminate.

Cancellation additionally proves the run stays cancelled after the supervisor
exits, and that a wrong-session stop fails without cancelling the origin.

Limitations: this proves host-context delivery into the simulated Hermes
context, not live-chat delivery or model consumption, and it does not prove
exactly-once delivery (a next watcher can redeliver an unmarked report).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from orchestra.state import (
    ACTIVE_STATUSES,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_RUNNING,
    TERMINAL_STATUSES,
    StateStore,
)
from tests.helpers import wait_for_condition
from tests.test_hermes_plugin_source import FakeHermesPluginContext, load_plugin
from tests.test_success_delivery_flow import (
    _ORIGIN,
    _OTHER,
    _make_seam,
    _process_alive,
    _set_config,
    _stop_run_and_wait,
)


def _gate_mark(
    plugin: Any, monkeypatch: pytest.MonkeyPatch
) -> tuple[threading.Event, threading.Event]:
    """Gate the real core mark-delivered so the unreported-before-acceptance state is
    observable deterministically. The real mark still runs once released."""
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


def test_connected_hermes_failure_full_journey(
    tmp_path: Path,
    runtime_files_factory: Any,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, _, db_path = runtime_files_factory(
        tmp_path,
        [
            python_executable,
            str(fake_worker_script),
            "fail",
            "--output",
            "fail stdout",
            "--stderr",
            "boom stderr",
        ],
    )
    _set_config(config_path, default_timeout=60, global_limit=4, per_session=4)
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    seam = _make_seam(config_dir)
    plugin = load_plugin()
    monkeypatch.setattr(plugin, "_run_orchestra", seam)
    mark_reached, proceed_mark = _gate_mark(plugin, monkeypatch)

    ctx = FakeHermesPluginContext(session_id=_ORIGIN)
    run_id: str | None = None
    try:
        ack = plugin._dispatch_orchestra_run({"goal": "ship the failure slice"}, _ORIGIN, ctx=ctx)
        assert isinstance(ack, str) and ack

        # The accepted run belongs to the runtime originating session.
        runs = store.list_runs(_ORIGIN)
        assert len(runs) == 1
        run_id = runs[0].run_id
        record = store.get_run(run_id)
        assert record.orchestrator_session_id == _ORIGIN
        assert record.role == "worker"

        # Actual worker launch: the supervisor recorded a real worker process.
        assert wait_for_condition(
            lambda: store.get_run(run_id).status in TERMINAL_STATUSES, timeout=30
        )
        record = store.get_run(run_id)
        assert record.status == STATUS_FAILED
        assert record.process_id is not None

        # Failure preserves stdout/stderr diagnostics in the full return artifact.
        return_path = tmp_path / "state" / "runs" / run_id / "return.md"
        assert return_path.exists()
        return_text = return_path.read_text(encoding="utf-8")
        assert "fail stdout" in return_text
        assert "boom stderr" in return_text

        # The host context receives the report; the mark is gated, so the report
        # must still be unreported (host accepted delivery, core has not claimed it).
        assert mark_reached.wait(timeout=30)
        assert ctx.injected
        assert store.get_run(run_id).reported_at is None
        assert any(run.run_id == run_id for run in store.list_pending_report_runs(_ORIGIN))

        # Correct semantic consolidated report: a fail outcome carrying the stderr
        # diagnostic, not a success outcome.
        report = _injected_report(ctx, run_id)
        assert f"{run_id} fail]" in report
        assert "boom stderr" in report
        assert f"{run_id} success]" not in report

        # Release the barrier: the real core mark-delivered runs.
        proceed_mark.set()
        assert wait_for_condition(
            lambda: store.get_run(run_id).reported_at is not None, timeout=30
        )

        # Pending report disappears after successful host acceptance.
        assert not any(run.run_id == run_id for run in store.list_pending_report_runs(_ORIGIN))

        # Capacity released and worker/supervisor terminated.
        assert store.count_active_runs(_ORIGIN) == 0
        assert wait_for_condition(
            lambda: not _process_alive(store.get_run(run_id).supervisor_pid), timeout=15
        )
        assert wait_for_condition(
            lambda: not _process_alive(store.get_run(run_id).process_id), timeout=15
        )
    finally:
        proceed_mark.set()
        if run_id is not None:
            _stop_run_and_wait(seam, store, session_id=_ORIGIN, run_id=run_id)


def test_ordinary_hard_timeout_full_journey(
    tmp_path: Path,
    runtime_files_factory: Any,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, _, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "sleep", "--sleep", "120", "--output", "late"],
    )
    _set_config(config_path, default_timeout=3, global_limit=4, per_session=4)
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    seam = _make_seam(config_dir)
    plugin = load_plugin()
    monkeypatch.setattr(plugin, "_run_orchestra", seam)
    mark_reached, proceed_mark = _gate_mark(plugin, monkeypatch)

    ctx = FakeHermesPluginContext(session_id=_ORIGIN)
    run_id: str | None = None
    try:
        ack = plugin._dispatch_orchestra_run({"goal": "ship the timeout slice"}, _ORIGIN, ctx=ctx)
        assert isinstance(ack, str) and ack

        # The accepted run belongs to the runtime originating session.
        runs = store.list_runs(_ORIGIN)
        assert len(runs) == 1
        run_id = runs[0].run_id
        record = store.get_run(run_id)
        assert record.orchestrator_session_id == _ORIGIN
        assert record.role == "worker"

        # Actual worker launch: the supervisor recorded a real worker process before
        # the hard timeout fired.
        assert wait_for_condition(
            lambda: store.get_run(run_id).status in TERMINAL_STATUSES, timeout=30
        )
        record = store.get_run(run_id)
        assert record.status == STATUS_FAILED
        assert record.process_id is not None
        # The timeout is reported, not a generic failure.
        assert record.error_text == "Worker timed out"
        assert record.blocker_text == "Worker exceeded timeout"

        # The host context receives the report; the mark is gated, so the report
        # must still be unreported.
        assert mark_reached.wait(timeout=30)
        assert ctx.injected
        assert store.get_run(run_id).reported_at is None
        assert any(run.run_id == run_id for run in store.list_pending_report_runs(_ORIGIN))

        # Correct semantic consolidated report: a fail outcome that reports the
        # timeout, not a success outcome.
        report = _injected_report(ctx, run_id)
        assert f"{run_id} fail]" in report
        assert "Worker exceeded timeout" in report
        assert f"{run_id} success]" not in report

        # Release the barrier: the real core mark-delivered runs.
        proceed_mark.set()
        assert wait_for_condition(
            lambda: store.get_run(run_id).reported_at is not None, timeout=30
        )

        # Pending report disappears after successful host acceptance.
        assert not any(run.run_id == run_id for run in store.list_pending_report_runs(_ORIGIN))

        # Capacity released and the timed-out worker process group terminated.
        assert store.count_active_runs(_ORIGIN) == 0
        assert wait_for_condition(
            lambda: not _process_alive(store.get_run(run_id).supervisor_pid), timeout=15
        )
        assert wait_for_condition(
            lambda: not _process_alive(store.get_run(run_id).process_id), timeout=15
        )
    finally:
        proceed_mark.set()
        if run_id is not None:
            _stop_run_and_wait(seam, store, session_id=_ORIGIN, run_id=run_id)


def test_owner_cancellation_full_journey(
    tmp_path: Path,
    runtime_files_factory: Any,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, _, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "sleep", "--sleep", "120", "--output", "late"],
    )
    _set_config(config_path, default_timeout=60, global_limit=4, per_session=4)
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    seam = _make_seam(config_dir)
    plugin = load_plugin()
    monkeypatch.setattr(plugin, "_run_orchestra", seam)
    mark_reached, proceed_mark = _gate_mark(plugin, monkeypatch)

    ctx = FakeHermesPluginContext(session_id=_ORIGIN)
    run_id: str | None = None
    try:
        ack = plugin._dispatch_orchestra_run({"goal": "ship the cancel slice"}, _ORIGIN, ctx=ctx)
        assert isinstance(ack, str) and ack

        # The accepted run belongs to the runtime originating session.
        runs = store.list_runs(_ORIGIN)
        assert len(runs) == 1
        run_id = runs[0].run_id
        record = store.get_run(run_id)
        assert record.orchestrator_session_id == _ORIGIN
        assert record.role == "worker"

        # Actual worker launch: the supervisor recorded a real worker process.
        assert wait_for_condition(
            lambda: (
                store.get_run(run_id).status == STATUS_RUNNING
                and store.get_run(run_id).process_id is not None
            ),
            timeout=30,
        )

        # Wrong-session stop must fail without cancelling the origin.
        wrong = seam(["stop", "--session-id", _OTHER, "--run-id", run_id])
        assert wrong.returncode != 0
        assert store.get_run(run_id).status in ACTIVE_STATUSES

        # Owner cancellation: the origin session stops its own run.
        stop = seam(["stop", "--session-id", _ORIGIN, "--run-id", run_id])
        assert stop.returncode == 0
        assert wait_for_condition(
            lambda: store.get_run(run_id).status == STATUS_CANCELLED, timeout=15
        )
        record = store.get_run(run_id)
        assert record.blocker_text == "Cancelled by orchestra stop"

        # The host context receives the report; the mark is gated, so the report
        # must still be unreported.
        assert mark_reached.wait(timeout=30)
        assert ctx.injected
        assert store.get_run(run_id).reported_at is None
        assert any(run.run_id == run_id for run in store.list_pending_report_runs(_ORIGIN))

        # Correct semantic consolidated report: a fail outcome that reports the
        # cancellation, not a success outcome.
        report = _injected_report(ctx, run_id)
        assert f"{run_id} fail]" in report
        assert "Cancelled by orchestra stop" in report
        assert f"{run_id} success]" not in report

        # Release the barrier: the real core mark-delivered runs.
        proceed_mark.set()
        assert wait_for_condition(
            lambda: store.get_run(run_id).reported_at is not None, timeout=30
        )

        # Pending report disappears after successful host acceptance.
        assert not any(run.run_id == run_id for run in store.list_pending_report_runs(_ORIGIN))

        # The run stays cancelled even after the supervisor exits (the supervisor's
        # finalize must not overwrite the owner's terminal cancellation).
        assert wait_for_condition(
            lambda: not _process_alive(store.get_run(run_id).supervisor_pid), timeout=15
        )
        assert store.get_run(run_id).status == STATUS_CANCELLED

        # Capacity released and the cancelled worker process terminated.
        assert store.count_active_runs(_ORIGIN) == 0
        assert wait_for_condition(
            lambda: not _process_alive(store.get_run(run_id).process_id), timeout=15
        )
    finally:
        proceed_mark.set()
        if run_id is not None:
            _stop_run_and_wait(seam, store, session_id=_ORIGIN, run_id=run_id)
