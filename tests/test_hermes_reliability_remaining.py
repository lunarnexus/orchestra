"""Remaining bounded Hermes reliability functional tests.

Connected journeys for the remaining bounded Hermes reliability slice: the real
Hermes plugin dispatch entry point and report watcher drive the real Orchestra
CLI/core/SQLite with an isolated config, a real detached supervisor, and a
controlled fake subagent. Only the Hermes host boundary is simulated: the
in-process host context (delivery acceptance, busy/steer state) and, in the
corruption journey, a post-acceptance transport loss on the accepted ``do``
response only. Dispatch, terminal state, report generation, and the mark are
never stubbed.

The corruption journey proves recovery: when the accepted ``do`` response loses
its timeout after acceptance, the plugin keeps the accepted run id in the tool
response, starts the report watcher on the configured core default timeout,
and delivers+marks the completion report. The corruption seam only touches the
``do`` response, so a missing fallback would leave the report undelivered and
the test would fail.

Limitations: this proves delivery into the simulated Hermes context, not
live-chat delivery or model consumption, and it does not promise exactly-once
delivery.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from orchestra.state import STATUS_DONE, TERMINAL_STATUSES, StateStore
from tests.helpers import wait_for_condition
from tests.test_delivery_failure_recovery_flow import _watcher_finished
from tests.test_hermes_plugin_source import FakeHermesPluginContext, load_plugin
from tests.test_success_delivery_flow import (
    _ORIGIN,
    _make_seam,
    _set_config,
    _stop_run_and_wait,
)


def _corrupt_do_timeout_seam(config_dir: str) -> Any:
    """Runner seam: runs the real Orchestra CLI for every command, then corrupts
    only the accepted ``do`` response by dropping its ``timeout_seconds`` field,
    simulating a post-acceptance transport loss. Every other command (ack,
    await, stop, ...) is returned uncorrupted, so only the ``do`` response is
    corrupted and the run is still accepted by the real core."""
    real_seam = _make_seam(config_dir)

    def seam(
        args: list[str],
        *,
        timeout_seconds: int = 300,
        input: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        result: subprocess.CompletedProcess[str] = real_seam(
            args, timeout_seconds=timeout_seconds, input=input
        )
        if args and args[0] == "do" and result.returncode == 0:
            payload = json.loads(result.stdout)
            payload.pop("timeout_seconds", None)
            return subprocess.CompletedProcess(
                args=args,
                returncode=result.returncode,
                stdout=json.dumps(payload),
                stderr=result.stderr,
            )
        return result

    return seam


def _await_fault_seam(
    config_dir: str, should_fault: Callable[[int], bool]
) -> tuple[Any, list[int]]:
    """Runner seam that delegates every command to the real Orchestra CLI, but
    injects a fault into selected ``_await-session-report`` invocations. ``should_fault``
    receives the 0-based index of the await call and returns True to fail that
    await (returncode 1) and False to delegate to the real CLI. Only the Hermes
    host await boundary is faulted; dispatch/ack/mark run the real core. Returns
    the seam and the list of faulted await indices (the fault trace)."""
    real_seam = _make_seam(config_dir)
    faulted: list[int] = []
    await_count: list[int] = [0]

    def seam(
        args: list[str],
        *,
        timeout_seconds: int = 300,
        input: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if args and args[0] == "_await-session-report":
            index = await_count[0]
            await_count[0] += 1
            if should_fault(index):
                faulted.append(index)
                return subprocess.CompletedProcess(
                    args=args, returncode=1, stdout="", stderr="simulated await fault"
                )
        result: subprocess.CompletedProcess[str] = real_seam(
            args, timeout_seconds=timeout_seconds, input=input
        )
        return result

    return seam, faulted


def test_post_acceptance_corrupted_do_response_missing_timeout_recovers(
    tmp_path: Path,
    runtime_files_factory: Any,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Post-acceptance transport corruption drops only the accepted ``do``
    response's timeout. The run is already accepted by the real core; the fix
    keeps the accepted run id in the tool response, starts the report watcher on
    the configured core default timeout, and delivers+marks the completion
    report. The corruption seam only touches the ``do`` response, so a missing
    fallback would leave the report undelivered and this test would fail."""
    config_path, _, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "worker ok"],
    )
    _set_config(config_path, default_timeout=60, global_limit=4, per_session=4)
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    seam = _corrupt_do_timeout_seam(config_dir)
    plugin = load_plugin()
    # Narrow test-time retry delays only; the retry count and delivery outcome are
    # unchanged and no actual timing is asserted.
    monkeypatch.setattr(plugin, "_REPORT_WATCHER_RETRY_BASE_DELAY_SECONDS", 0.01)
    monkeypatch.setattr(plugin, "_REPORT_WATCHER_RETRY_MAX_DELAY_SECONDS", 0.02)
    monkeypatch.setattr(plugin, "_run_orchestra", seam)

    ctx = FakeHermesPluginContext(session_id=_ORIGIN)
    run_id: str | None = None
    try:
        ack = plugin._dispatch_orchestra_run(
            {"goal": "ship the corruption slice"}, _ORIGIN, ctx=ctx
        )

        # The ack reflects acceptance (real _dispatch-ack text, not an error ack)
        # and the accepted run id is recoverable from the tool response.
        assert isinstance(ack, str) and ack
        assert "orchestra dispatched" in ack

        # The run was accepted by the real core under the origin.
        runs = store.list_runs(_ORIGIN)
        assert len(runs) == 1
        run_id = runs[0].run_id
        assert store.get_run(run_id).orchestrator_session_id == _ORIGIN
        assert store.get_run(run_id).role == "worker"

        # The accepted run id is recoverable from the tool response.
        assert run_id in ack

        # The accepted run completes normally (real supervisor, controlled worker).
        assert wait_for_condition(
            lambda: store.get_run(run_id).status in TERMINAL_STATUSES, timeout=30
        )
        assert store.get_run(run_id).status == STATUS_DONE

        # The report watcher ran to completion and exited.
        assert _watcher_finished(plugin, _ORIGIN)

        # The completion report was delivered to the host context and the real core
        # mark persisted: nothing remains pending.
        offered = [content for content, _ in ctx.injected if run_id in content]
        assert len(offered) == 1
        assert "worker ok" in offered[0]
        assert f"{run_id} success]" in offered[0]
        assert store.get_run(run_id).reported_at is not None
        assert store.list_pending_report_runs(_ORIGIN) == []
        assert store.count_active_runs(_ORIGIN) == 0
    finally:
        if run_id is not None:
            _stop_run_and_wait(seam, store, session_id=_ORIGIN, run_id=run_id)


def test_busy_host_steer_delivers_connected_report_and_marks(
    tmp_path: Path,
    runtime_files_factory: Any,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Busy host (connected agent mid-turn): the watcher steers the connected
    report into the active turn instead of injecting a new message, and the
    real core mark clears the pending report."""
    config_path, _, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "worker ok"],
    )
    _set_config(config_path, default_timeout=60, global_limit=4, per_session=4)
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    seam = _make_seam(config_dir)
    plugin = load_plugin()
    monkeypatch.setattr(plugin, "_run_orchestra", seam)

    ctx = FakeHermesPluginContext(session_id=_ORIGIN, agent_running=True)

    run_id: str | None = None
    try:
        ack = plugin._dispatch_orchestra_run(
            {"goal": "ship the busy steer slice"}, _ORIGIN, ctx=ctx
        )
        assert isinstance(ack, str) and ack

        runs = store.list_runs(_ORIGIN)
        assert len(runs) == 1
        run_id = runs[0].run_id
        assert store.get_run(run_id).orchestrator_session_id == _ORIGIN
        assert store.get_run(run_id).role == "worker"

        assert wait_for_condition(
            lambda: store.get_run(run_id).status in TERMINAL_STATUSES, timeout=30
        )
        assert store.get_run(run_id).status == STATUS_DONE

        # The watcher finished its delivery attempt and exited.
        assert _watcher_finished(plugin, _ORIGIN)

        # The connected report reached the active turn via steer (not injection).
        offered = [content for content in ctx.steered if run_id in content]
        assert len(offered) == 1
        assert "worker ok" in offered[0]
        assert f"{run_id} success]" in offered[0]
        assert ctx.injected == []

        # The real core mark persisted: the report is no longer pending.
        assert store.get_run(run_id).reported_at is not None
        assert store.list_pending_report_runs(_ORIGIN) == []
        assert store.count_active_runs(_ORIGIN) == 0
    finally:
        if run_id is not None:
            _stop_run_and_wait(seam, store, session_id=_ORIGIN, run_id=run_id)


def test_busy_host_steer_refusal_falls_back_to_queue_and_marks(
    tmp_path: Path,
    runtime_files_factory: Any,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Busy host that refuses the steer: the watcher falls back to queueing the
    report as the next turn's input, and the real core mark clears the pending
    report."""
    config_path, _, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "worker ok"],
    )
    _set_config(config_path, default_timeout=60, global_limit=4, per_session=4)
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    seam = _make_seam(config_dir)
    plugin = load_plugin()
    monkeypatch.setattr(plugin, "_run_orchestra", seam)

    ctx = FakeHermesPluginContext(session_id=_ORIGIN, agent_running=True)
    ctx.steer_success = False

    run_id: str | None = None
    try:
        ack = plugin._dispatch_orchestra_run(
            {"goal": "ship the busy queue slice"}, _ORIGIN, ctx=ctx
        )
        assert isinstance(ack, str) and ack

        runs = store.list_runs(_ORIGIN)
        assert len(runs) == 1
        run_id = runs[0].run_id
        assert store.get_run(run_id).orchestrator_session_id == _ORIGIN
        assert store.get_run(run_id).role == "worker"

        assert wait_for_condition(
            lambda: store.get_run(run_id).status in TERMINAL_STATUSES, timeout=30
        )
        assert store.get_run(run_id).status == STATUS_DONE

        # The watcher finished its delivery attempt and exited.
        assert _watcher_finished(plugin, _ORIGIN)

        # The steer was attempted and refused; the report was queued instead.
        offered = [content for content in ctx.steered if run_id in content]
        assert len(offered) == 1
        assert ctx.pending_input.qsize() == 1
        queued = ctx.pending_input.get_nowait()
        assert run_id in queued
        assert "worker ok" in queued
        assert f"{run_id} success]" in queued
        assert ctx.injected == []

        # The real core mark persisted: the report is no longer pending.
        assert store.get_run(run_id).reported_at is not None
        assert store.list_pending_report_runs(_ORIGIN) == []
        assert store.count_active_runs(_ORIGIN) == 0
    finally:
        if run_id is not None:
            _stop_run_and_wait(seam, store, session_id=_ORIGIN, run_id=run_id)


def test_transient_await_fault_recovers_and_delivers_mark(
    tmp_path: Path,
    runtime_files_factory: Any,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transient await fault: the first ``_await-session-report`` fails once, then
    the real watcher retries, retrieves the actual report, delivers it, and the
    real core mark clears the pending report. Only the first await is faulted; the
    retry budget and delivery path are the real plugin's."""
    config_path, _, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "worker ok"],
    )
    _set_config(config_path, default_timeout=60, global_limit=4, per_session=4)
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    plugin = load_plugin()
    # Narrow test-time retry delays only; the retry count and delivery outcome are
    # unchanged and no actual timing is asserted.
    monkeypatch.setattr(plugin, "_REPORT_WATCHER_RETRY_BASE_DELAY_SECONDS", 0.01)
    monkeypatch.setattr(plugin, "_REPORT_WATCHER_RETRY_MAX_DELAY_SECONDS", 0.02)

    # Fault trace: fail only the first await, then delegate to the real CLI.
    seam, faulted = _await_fault_seam(config_dir, should_fault=lambda i: i == 0)
    monkeypatch.setattr(plugin, "_run_orchestra", seam)

    ctx = FakeHermesPluginContext(session_id=_ORIGIN)
    run_id: str | None = None
    try:
        ack = plugin._dispatch_orchestra_run(
            {"goal": "ship the transient await slice"}, _ORIGIN, ctx=ctx
        )
        assert isinstance(ack, str) and ack

        runs = store.list_runs(_ORIGIN)
        assert len(runs) == 1
        run_id = runs[0].run_id
        assert store.get_run(run_id).orchestrator_session_id == _ORIGIN
        assert store.get_run(run_id).role == "worker"

        assert wait_for_condition(
            lambda: store.get_run(run_id).status in TERMINAL_STATUSES, timeout=30
        )
        assert store.get_run(run_id).status == STATUS_DONE

        # The watcher finished its (recovered) delivery attempt and exited.
        assert _watcher_finished(plugin, _ORIGIN)

        # Fault trace: exactly the first await was faulted; the retry recovered.
        assert faulted == [0]

        # The report was delivered to the host context and the real core mark persisted.
        offered = [content for content, _ in ctx.injected if run_id in content]
        assert len(offered) == 1
        assert "worker ok" in offered[0]
        assert f"{run_id} success]" in offered[0]
        assert store.get_run(run_id).reported_at is not None
        assert store.list_pending_report_runs(_ORIGIN) == []
        assert store.count_active_runs(_ORIGIN) == 0
    finally:
        if run_id is not None:
            _stop_run_and_wait(seam, store, session_id=_ORIGIN, run_id=run_id)


def test_exhausted_await_fault_leaves_unreported_then_next_dispatch_consolidates(
    tmp_path: Path,
    runtime_files_factory: Any,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persistent await fault exhausts the real watcher's own retry budget: no
    delivery, no mark, and the durable unreported result remains pending. After
    the injection is disabled, the next real dispatch's watcher retrieves the
    consolidated report (original + new run ids) and the real core mark clears
    both. The fault is persistent (every await fails while enabled); the watcher's
    own budget decides when it exhausts, not a hardcoded count."""
    config_path, _, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "worker ok"],
    )
    _set_config(config_path, default_timeout=60, global_limit=4, per_session=4)
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    plugin = load_plugin()
    # Narrow test-time retry delays only; the retry count and delivery outcome are
    # unchanged and no actual timing is asserted.
    monkeypatch.setattr(plugin, "_REPORT_WATCHER_RETRY_BASE_DELAY_SECONDS", 0.01)
    monkeypatch.setattr(plugin, "_REPORT_WATCHER_RETRY_MAX_DELAY_SECONDS", 0.02)

    # Persistent await fault while enabled: every await returns nonzero.
    fault_enabled = [True]
    seam, faulted = _await_fault_seam(config_dir, should_fault=lambda i: fault_enabled[0])
    monkeypatch.setattr(plugin, "_run_orchestra", seam)

    ctx = FakeHermesPluginContext(session_id=_ORIGIN)
    run_ids: list[str] = []
    try:
        # --- First dispatch: persistent fault exhausts the real watcher. ---
        ack = plugin._dispatch_orchestra_run(
            {"goal": "ship the exhausted await slice"}, _ORIGIN, ctx=ctx
        )
        assert isinstance(ack, str) and ack

        runs = store.list_runs(_ORIGIN)
        assert len(runs) == 1
        original_run_id = runs[0].run_id
        run_ids.append(original_run_id)
        assert store.get_run(original_run_id).orchestrator_session_id == _ORIGIN
        assert store.get_run(original_run_id).role == "worker"

        assert wait_for_condition(
            lambda: store.get_run(original_run_id).status in TERMINAL_STATUSES, timeout=30
        )
        assert store.get_run(original_run_id).status == STATUS_DONE

        # The real watcher exhausted its own retry budget and exited.
        assert _watcher_finished(plugin, _ORIGIN)

        # Fault trace: multi-retry evidenced (persistent fault, not exact count).
        assert len(faulted) > 1

        # Durable unreported result remains: no delivery, no mark, still pending.
        assert ctx.injected == []
        assert store.get_run(original_run_id).reported_at is None
        assert any(
            run.run_id == original_run_id
            for run in store.list_pending_report_runs(_ORIGIN)
        )

        # --- Disable injection; the next real dispatch consolidates and marks. ---
        fault_enabled[0] = False
        ack2 = plugin._dispatch_orchestra_run(
            {"goal": "ship the consolidation slice"}, _ORIGIN, ctx=ctx
        )
        assert isinstance(ack2, str) and ack2

        runs = store.list_runs(_ORIGIN)
        assert len(runs) == 2
        new_run_id = next(r.run_id for r in runs if r.run_id != original_run_id)
        run_ids.append(new_run_id)

        assert wait_for_condition(
            lambda: store.get_run(new_run_id).status in TERMINAL_STATUSES, timeout=30
        )
        assert store.get_run(new_run_id).status == STATUS_DONE

        # The second watcher finished its delivery attempt and exited.
        assert _watcher_finished(plugin, _ORIGIN)

        # Consolidated report: the injected report carries BOTH run ids.
        consolidated = [
            content
            for content, _ in ctx.injected
            if original_run_id in content and new_run_id in content
        ]
        assert len(consolidated) == 1
        assert f"{original_run_id} success]" in consolidated[0]
        assert f"{new_run_id} success]" in consolidated[0]

        # The real core mark persisted for BOTH runs; nothing remains pending.
        assert store.get_run(original_run_id).reported_at is not None
        assert store.get_run(new_run_id).reported_at is not None
        assert store.list_pending_report_runs(_ORIGIN) == []
        assert store.count_active_runs(_ORIGIN) == 0
    finally:
        for rid in run_ids:
            _stop_run_and_wait(seam, store, session_id=_ORIGIN, run_id=rid)
