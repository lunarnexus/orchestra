"""Delivery-failure and recovery functional tests.

Connected journeys for the owner-approved connected Hermes delivery-failure/
recovery slice: the real Hermes plugin dispatch entry point and report watcher
drive the real Orchestra CLI/core/SQLite with an isolated config, a real
detached supervisor, and a controlled fake subagent. Only the Hermes host
delivery-acceptance boundary is simulated (the in-process host context that
accepts or refuses the injected report); in the mark-failure journey the real
``_mark-session-report-delivered`` command is made to fail exactly once at the
runner seam. Dispatch, terminal state, report generation, and the recovery
mark are never stubbed.

Observed scheduling semantics (asserted, not changed): after a delivery
refusal or a mark-delivered command failure the watcher thread exits without
retrying inside the same watcher; recovery happens on the next watcher trigger
(the next real dispatch). Unmarked reports remain pending; a later watcher
trigger can redeliver them, including duplicates after host acceptance. These
tests do not establish guaranteed or exactly-once delivery.

Limitations: this proves delivery into the simulated Hermes context, not
live-chat delivery or model consumption, and it does not promise exactly-once
delivery.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from orchestra.state import STATUS_DONE, TERMINAL_STATUSES, StateStore
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


def _watcher_finished(plugin: Any, session_id: str, timeout: float = 30.0) -> bool:
    """Bounded barrier: the session's report watcher thread has fully exited.

    The watcher discards the session from ``_REPORT_WATCHERS`` in its ``finally``
    block, after the delivery attempt and the mark decision, so this guarantees
    the attempt happened and that the next dispatch starts a fresh watcher."""
    return wait_for_condition(
        lambda: session_id not in plugin._REPORT_WATCHERS, timeout=timeout
    )


def _seam_with_first_mark_failure(config_dir: str) -> tuple[Any, list[list[str]]]:
    """Runner seam that delegates everything to the real Orchestra CLI except the
    first ``_mark-session-report-delivered`` invocation, which is made to fail
    exactly once. Every other command (dispatch, await, ack, the recovery mark)
    runs the real core. Returns the seam and a record of mark-command argv."""
    real_seam = _make_seam(config_dir)
    mark_calls: list[list[str]] = []

    def seam(
        args: list[str],
        *,
        timeout_seconds: int = 300,
        input: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if args and args[0] == "_mark-session-report-delivered":
            mark_calls.append(list(args))
            if len(mark_calls) == 1:
                return subprocess.CompletedProcess(
                    args=args, returncode=1, stdout="", stderr="simulated mark failure"
                )
        result: subprocess.CompletedProcess[str] = real_seam(
            args, timeout_seconds=timeout_seconds, input=input
        )
        return result

    return seam, mark_calls


def _injected_reports(ctx: FakeHermesPluginContext, run_id: str) -> list[str]:
    return [content for content, _ in ctx.injected if run_id in content]


def _wait_run_processes_dead(store: StateStore, run_id: str) -> None:
    """Nonvacuous process death: the run recorded real worker/supervisor pids
    (processes actually launched) and both are now dead."""
    record = store.get_run(run_id)
    assert record.process_id is not None
    assert record.supervisor_pid is not None
    worker_pid = record.process_id
    supervisor_pid = record.supervisor_pid
    assert wait_for_condition(lambda: not _process_alive(worker_pid), timeout=15)
    assert wait_for_condition(lambda: not _process_alive(supervisor_pid), timeout=15)


def _assert_terminated_and_released(store: StateStore, run_ids: list[str]) -> None:
    """Every run in the journey terminated with real processes, and no active
    capacity remains in the origin session."""
    for run_id in run_ids:
        _wait_run_processes_dead(store, run_id)
    assert store.count_active_runs(_ORIGIN) == 0


def test_host_refused_delivery_recovers_on_next_watcher(
    tmp_path: Path,
    runtime_files_factory: Any,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Host refuses delivery -> run completes, report stays unreported/retrievable,
    no successful mark -> the next watcher (a second real dispatch) recovers the
    same report to the origin, the mark persists, and the pending report
    disappears."""
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

    # Simulated host boundary: the host context refuses to accept the report.
    ctx = FakeHermesPluginContext(session_id=_ORIGIN)
    ctx.inject_success = False

    run_ids: list[str] = []
    try:
        ack = plugin._dispatch_orchestra_run({"goal": "ship the refusal slice"}, _ORIGIN, ctx=ctx)
        assert isinstance(ack, str) and ack

        # Exact originating identity: the run belongs to the runtime session.
        runs = store.list_runs(_ORIGIN)
        assert len(runs) == 1
        run_id = runs[0].run_id
        run_ids.append(run_id)
        record = store.get_run(run_id)
        assert record.orchestrator_session_id == _ORIGIN
        assert record.role == "worker"

        # The real supervisor ran the controlled fake subagent to done.
        assert wait_for_condition(
            lambda: store.get_run(run_id).status in TERMINAL_STATUSES, timeout=30
        )
        record = store.get_run(run_id)
        assert record.status == STATUS_DONE
        assert record.process_id is not None
        # Terminal run retains result and artifact.
        assert "worker ok" in (record.result_summary or "")
        return_path = tmp_path / "state" / "runs" / run_id / "return.md"
        assert return_path.exists()
        assert "worker ok" in return_path.read_text(encoding="utf-8")
        terminal_snapshot = (
            record.status,
            record.result_summary,
            record.error_text,
            record.blocker_text,
        )

        # The watcher made its delivery attempt and exited (no same-watcher retry).
        assert _watcher_finished(plugin, _ORIGIN)

        # The host was offered the report (acceptance boundary exercised)...
        offered = _injected_reports(ctx, run_id)
        assert len(offered) == 1
        assert "worker ok" in offered[0]
        assert f"{run_id} success]" in offered[0]
        # ...but refused it: no successful mark, report still unreported.
        assert store.get_run(run_id).reported_at is None
        # The report remains retrievable by the origin session's next watcher.
        assert any(run.run_id == run_id for run in store.list_pending_report_runs(_ORIGIN))

        # A foreign session cannot consume or ack the report.
        assert not any(run.run_id == run_id for run in store.list_pending_report_runs(_OTHER))
        store.mark_report_runs_delivered(_OTHER, [run_id])
        assert store.get_run(run_id).reported_at is None

        # Recovery via the actual supported plugin path: the next dispatch starts
        # the next watcher, which delivers the same pending report to the origin.
        ctx.inject_success = True
        ack2 = plugin._dispatch_orchestra_run({"goal": "recover the report"}, _ORIGIN, ctx=ctx)
        assert isinstance(ack2, str) and ack2
        runs = store.list_runs(_ORIGIN)
        assert len(runs) == 2
        second_run_id = next(run.run_id for run in runs if run.run_id != run_id)
        run_ids.append(second_run_id)
        assert store.get_run(second_run_id).orchestrator_session_id == _ORIGIN

        assert wait_for_condition(
            lambda: store.get_run(second_run_id).status in TERMINAL_STATUSES, timeout=30
        )
        # The recovery watcher finished its delivery attempt.
        assert _watcher_finished(plugin, _ORIGIN)

        # The recovered report reached the origin and carries the original run.
        # The report was offered twice: the refused first delivery, then the
        # recovery redelivery (at-least-once, not exactly-once).
        recovered = _injected_reports(ctx, run_id)
        assert len(recovered) == 2
        assert "worker ok" in recovered[1]
        assert f"{run_id} success]" in recovered[1]
        assert second_run_id in recovered[1]

        # The mark persisted for the original run (and the recovery run).
        assert store.get_run(run_id).reported_at is not None
        assert store.get_run(second_run_id).reported_at is not None
        # The pending report disappeared.
        assert store.list_pending_report_runs(_ORIGIN) == []

        # Unrelated runs unmodified: the original run's terminal fields are intact
        # and the foreign session has no runs at all.
        final = store.get_run(run_id)
        assert (
            final.status,
            final.result_summary,
            final.error_text,
            final.blocker_text,
        ) == terminal_snapshot
        assert store.list_runs(_OTHER) == []

        # Capacity released and both runs' processes terminated (nonvacuously).
        _assert_terminated_and_released(store, run_ids)
    finally:
        for pending_run_id in run_ids:
            _stop_run_and_wait(seam, store, session_id=_ORIGIN, run_id=pending_run_id)


def test_accepted_report_failed_mark_redelivers_and_marks(
    tmp_path: Path,
    runtime_files_factory: Any,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Host accepts the report but the mark-delivered command fails once -> the
    report stays pending (acceptance is not acknowledgement) -> the next watcher
    redelivers the report and the real core mark persists. Delivery is
    at-least-once: the report is delivered twice, not exactly once."""
    config_path, _, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "worker ok"],
    )
    _set_config(config_path, default_timeout=60, global_limit=4, per_session=4)
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    seam, mark_calls = _seam_with_first_mark_failure(config_dir)
    plugin = load_plugin()
    monkeypatch.setattr(plugin, "_run_orchestra", seam)

    ctx = FakeHermesPluginContext(session_id=_ORIGIN)

    run_ids: list[str] = []
    try:
        ack = plugin._dispatch_orchestra_run(
            {"goal": "ship the mark failure slice"}, _ORIGIN, ctx=ctx
        )
        assert isinstance(ack, str) and ack

        runs = store.list_runs(_ORIGIN)
        assert len(runs) == 1
        run_id = runs[0].run_id
        run_ids.append(run_id)
        record = store.get_run(run_id)
        assert record.orchestrator_session_id == _ORIGIN
        assert record.role == "worker"

        assert wait_for_condition(
            lambda: store.get_run(run_id).status in TERMINAL_STATUSES, timeout=30
        )
        record = store.get_run(run_id)
        assert record.status == STATUS_DONE
        assert record.process_id is not None
        return_path = tmp_path / "state" / "runs" / run_id / "return.md"
        assert return_path.exists()
        assert "worker ok" in return_path.read_text(encoding="utf-8")
        terminal_snapshot = (
            record.status,
            record.result_summary,
            record.error_text,
            record.blocker_text,
        )

        # The watcher delivered the report and attempted the mark exactly once.
        assert _watcher_finished(plugin, _ORIGIN)
        assert wait_for_condition(lambda: len(mark_calls) >= 1, timeout=30)
        assert mark_calls[0][:1] == ["_mark-session-report-delivered"]
        assert "--run-id" in mark_calls[0] and run_id in mark_calls[0]

        # The host accepted the report (acceptance)...
        delivered = _injected_reports(ctx, run_id)
        assert len(delivered) == 1
        assert f"{run_id} success]" in delivered[0]
        # ...but the acknowledgement (core mark) failed: the report is still
        # pending and retrievable. Acceptance without acknowledgement.
        assert store.get_run(run_id).reported_at is None
        assert any(run.run_id == run_id for run in store.list_pending_report_runs(_ORIGIN))

        # A foreign session cannot consume or ack the pending report.
        assert not any(run.run_id == run_id for run in store.list_pending_report_runs(_OTHER))
        store.mark_report_runs_delivered(_OTHER, [run_id])
        assert store.get_run(run_id).reported_at is None

        # The next watcher (next real dispatch) redelivers and marks successfully.
        ack2 = plugin._dispatch_orchestra_run({"goal": "redeliver the report"}, _ORIGIN, ctx=ctx)
        assert isinstance(ack2, str) and ack2
        runs = store.list_runs(_ORIGIN)
        assert len(runs) == 2
        second_run_id = next(run.run_id for run in runs if run.run_id != run_id)
        run_ids.append(second_run_id)
        assert store.get_run(second_run_id).orchestrator_session_id == _ORIGIN

        assert wait_for_condition(
            lambda: store.get_run(second_run_id).status in TERMINAL_STATUSES, timeout=30
        )
        assert _watcher_finished(plugin, _ORIGIN)

        # Redelivery, not exactly-once: the original run's report reached the
        # host twice (first delivery + recovery redelivery).
        redelivered = _injected_reports(ctx, run_id)
        assert len(redelivered) == 2
        assert "worker ok" in redelivered[1]
        assert second_run_id in redelivered[1]

        # The recovery mark used the real core command and persisted.
        assert wait_for_condition(lambda: len(mark_calls) >= 2, timeout=30)
        assert "--run-id" in mark_calls[1] and run_id in mark_calls[1]
        assert second_run_id in mark_calls[1]
        assert store.get_run(run_id).reported_at is not None
        assert store.get_run(second_run_id).reported_at is not None
        assert store.list_pending_report_runs(_ORIGIN) == []

        # Unrelated runs unmodified.
        final = store.get_run(run_id)
        assert (
            final.status,
            final.result_summary,
            final.error_text,
            final.blocker_text,
        ) == terminal_snapshot
        assert store.list_runs(_OTHER) == []

        # Capacity released and both runs' processes terminated (nonvacuously).
        _assert_terminated_and_released(store, run_ids)
    finally:
        for pending_run_id in run_ids:
            _stop_run_and_wait(seam, store, session_id=_ORIGIN, run_id=pending_run_id)
