"""Multiple-subagent/session isolation functional tests.

Two connected Hermes journeys:

1. Same originating runtime session dispatches two real controlled subagents.
   The first completes (success) while the second is held active (barrier).
   No report is available and no host delivery occurs while the second is
   active. Releasing the second to a nonzero failure produces one
   consolidated report carrying both IDs and correct outcomes. Actual host
   acceptance and core mark clear both pending results.

2. Two distinct runtime host sessions run concurrently. A completes while B
   is provably active. A delivers without waiting for B and contains only A's
   IDs. Releasing B delivers only B's IDs. A foreign-session mark cannot
   clear the other session's pending results while the report is actually
   pending (not after already acked).

Infrastructure: real Hermes plugin dispatch + watcher thread, real
CLI/core/SQLite, real detached supervisors, controlled fake workers.
Only the host-context delivery boundary is simulated (in-process
FakeHermesPluginContext). The runner seam invokes the real
``python -m orchestra`` with the isolated config.

Limitations: proves host-context delivery into the simulated Hermes context,
not live-chat delivery or model consumption. Does not prove exactly-once
delivery (a next watcher can redeliver an unmarked report).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
import yaml

from orchestra.state import STATUS_DONE, STATUS_FAILED, TERMINAL_STATUSES, StateStore
from tests.helpers import wait_for_condition
from tests.test_hermes_plugin_source import FakeHermesPluginContext, load_plugin
from tests.test_success_delivery_flow import (
    _make_seam,
    _process_alive,
    _set_config,
)

_SESSION_A = "hermes:journey-a"
_SESSION_B = "hermes:journey-b"


def _add_harness_config(
    catalog_path: Path,
    name: str,
    command: list[str],
) -> None:
    """Add a second harness config + role to the catalog for a distinct worker."""
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    catalog["harness_configs"][name] = {"harness": name, "command": command}
    catalog["roles"][f"worker-{name}"] = {"harness_config": name}
    catalog_path.write_text(yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8")


def _gate_mark(
    plugin: Any, monkeypatch: pytest.MonkeyPatch
) -> tuple[threading.Event, threading.Event]:
    """Gate the real core mark-delivered so the unreported-before-acceptance
    state is observable deterministically. The real mark still runs once released."""
    mark_reached = threading.Event()
    proceed_mark = threading.Event()
    real_mark = plugin._mark_session_report_delivered

    def gated_mark(runtime_session_id: str, run_ids: list[str]) -> Any:
        mark_reached.set()
        proceed_mark.wait(timeout=30)
        return real_mark(runtime_session_id, run_ids)

    monkeypatch.setattr(plugin, "_mark_session_report_delivered", gated_mark)
    return mark_reached, proceed_mark


def _cleanup_runs(
    seam: Any,
    store: StateStore,
    *,
    session_ids: list[str],
    run_ids: list[str],
) -> None:
    """Robust bounded cleanup: stop any still-active runs, wait for processes to die.
    Never raises, so cleanup cannot mask the original test failure."""
    for run_id in run_ids:
        try:
            record = store.get_run(run_id)
            if record.status not in TERMINAL_STATUSES:
                session = record.orchestrator_session_id
                seam(["stop", "--session-id", session, "--run-id", run_id])
            supervisor_pid = record.supervisor_pid
            process_id = record.process_id

            def _both_dead(s: int | None = supervisor_pid, p: int | None = process_id) -> bool:
                return not _process_alive(s) and not _process_alive(p)

            wait_for_condition(_both_dead, timeout=15)
        except Exception:  # cleanup must never mask the original test failure
            pass


def test_same_session_two_subagents_consolidated_report(
    tmp_path: Path,
    runtime_files_factory: Any,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Journey 1: same session, two subagents.

    First done while second held active -> no report available/no host
    delivery. Release second to nonzero failure -> one consolidated report
    both IDs/outcomes -> actual host acceptance/core mark both pending cleared.
    """
    barrier_a = tmp_path / "barrier_a"
    barrier_b = tmp_path / "barrier_b"
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [
            python_executable,
            str(fake_worker_script),
            "success",
            "--output",
            "worker A ok",
            "--barrier",
            str(barrier_a),
        ],
    )
    _set_config(config_path, default_timeout=60, global_limit=4, per_session=4)
    # Second harness: barrier + fail (nonzero exit).
    _add_harness_config(
        catalog_path,
        "hermes",
        [
            python_executable,
            str(fake_worker_script),
            "fail",
            "--output",
            "worker B fail",
            "--stderr",
            "B exploded",
            "--barrier",
            str(barrier_b),
        ],
    )
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    seam = _make_seam(config_dir)
    plugin = load_plugin()
    monkeypatch.setattr(plugin, "_run_orchestra", seam)
    mark_reached, proceed_mark = _gate_mark(plugin, monkeypatch)

    ctx = FakeHermesPluginContext(session_id=_SESSION_A)
    run_ids: list[str] = []
    try:
        # Dispatch A (barrier + success, role "worker" → harness "pi").
        ack_a = plugin._dispatch_orchestra_run(
            {"goal": "first subagent"}, _SESSION_A, ctx=ctx
        )
        assert isinstance(ack_a, str) and ack_a
        runs_a = store.list_runs(_SESSION_A)
        assert len(runs_a) == 1
        run_id_a = runs_a[0].run_id
        run_ids.append(run_id_a)

        # Dispatch B (barrier + fail, role "worker-hermes" → harness "hermes").
        ack_b = plugin._dispatch_orchestra_run(
            {"goal": "second subagent", "role": "worker-hermes"}, _SESSION_A, ctx=ctx
        )
        assert isinstance(ack_b, str) and ack_b
        runs_a = store.list_runs(_SESSION_A)
        assert len(runs_a) == 2
        run_id_b = next(r.run_id for r in runs_a if r.run_id != run_id_a)
        run_ids.append(run_id_b)

        # Both workers are held by their barriers (both active).
        assert wait_for_condition(
            lambda: barrier_a.exists() and barrier_b.exists(), timeout=30
        )
        assert store.get_run(run_id_a).status not in TERMINAL_STATUSES
        assert store.get_run(run_id_b).status not in TERMINAL_STATUSES

        # Release A: A's worker exits with code 0 (success).
        barrier_a.unlink(missing_ok=True)
        assert wait_for_condition(
            lambda: store.get_run(run_id_a).status in TERMINAL_STATUSES, timeout=30
        )
        assert store.get_run(run_id_a).status == STATUS_DONE
        # B is still active (barrier holding it).
        assert barrier_b.exists()
        assert store.get_run(run_id_b).status not in TERMINAL_STATUSES

        # No report available while B is still active: the session has an active
        # run, so list_pending_report_runs returns empty.
        assert store.list_pending_report_runs(_SESSION_A) == []
        # No host delivery yet: the watcher thread is still waiting for the
        # session to become idle.
        assert ctx.injected == []

        # Release B: delete the barrier file so the worker exits with code 1.
        barrier_b.unlink(missing_ok=True)
        assert wait_for_condition(
            lambda: store.get_run(run_id_b).status in TERMINAL_STATUSES, timeout=30
        )
        assert store.get_run(run_id_b).status == STATUS_FAILED

        # The watcher thread delivers the consolidated report once both are
        # terminal. The mark is gated, so the report stays unreported.
        assert mark_reached.wait(timeout=30)
        assert ctx.injected
        assert store.get_run(run_id_a).reported_at is None
        assert store.get_run(run_id_b).reported_at is None
        pending = store.list_pending_report_runs(_SESSION_A)
        assert {r.run_id for r in pending} == {run_id_a, run_id_b}

        # The consolidated report carries both IDs with correct outcomes.
        report = next(content for content, _ in ctx.injected if run_id_a in content)
        assert run_id_a in report
        assert run_id_b in report
        # A is success, B is fail.
        assert f"{run_id_a} success]" in report
        assert f"{run_id_b} fail]" in report
        # B's failure diagnostic is present.
        assert "B exploded" in report

        # Release the barrier: the real core mark-delivered runs for both.
        proceed_mark.set()
        assert wait_for_condition(
            lambda: store.get_run(run_id_a).reported_at is not None, timeout=30
        )
        assert wait_for_condition(
            lambda: store.get_run(run_id_b).reported_at is not None, timeout=30
        )

        # Both pending reports disappear after successful host acceptance.
        assert store.list_pending_report_runs(_SESSION_A) == []

        # Capacity released and all processes terminated.
        assert store.count_active_runs(_SESSION_A) == 0
        for rid in run_ids:
            rec = store.get_run(rid)
            sup_pid = rec.supervisor_pid
            proc_pid = rec.process_id

            def _sup_dead(s: int | None = sup_pid) -> bool:
                return not _process_alive(s)

            def _proc_dead(p: int | None = proc_pid) -> bool:
                return not _process_alive(p)

            assert wait_for_condition(_sup_dead, timeout=15)
            assert wait_for_condition(_proc_dead, timeout=15)
    finally:
        proceed_mark.set()
        barrier_a.unlink(missing_ok=True)
        barrier_b.unlink(missing_ok=True)
        _cleanup_runs(seam, store, session_ids=[_SESSION_A], run_ids=run_ids)


def test_two_sessions_concurrent_isolated_delivery(
    tmp_path: Path,
    runtime_files_factory: Any,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Journey 2: two distinct sessions run concurrently.

    A completes while B is provably active -> A delivers without waiting B and
    contains only A IDs. Release B -> B delivers only B IDs. Foreign-session
    mark cannot mark other's pending results while actually pending.
    """
    barrier_path = tmp_path / "barrier_b"
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "worker A ok"],
    )
    _set_config(config_path, default_timeout=60, global_limit=4, per_session=4)
    # Second harness: barrier + success (B will succeed once released).
    _add_harness_config(
        catalog_path,
        "hermes",
        [
            python_executable,
            str(fake_worker_script),
            "success",
            "--output",
            "worker B ok",
            "--barrier",
            str(barrier_path),
        ],
    )
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    seam = _make_seam(config_dir)
    plugin = load_plugin()
    monkeypatch.setattr(plugin, "_run_orchestra", seam)

    # Gate only session A's mark; B's mark runs immediately (not gated).
    mark_reached_a = threading.Event()
    proceed_mark_a = threading.Event()
    real_mark = plugin._mark_session_report_delivered

    def gated_mark(runtime_session_id: str, run_ids: list[str]) -> Any:
        if runtime_session_id == _SESSION_A:
            mark_reached_a.set()
            proceed_mark_a.wait(timeout=30)
        return real_mark(runtime_session_id, run_ids)

    monkeypatch.setattr(plugin, "_mark_session_report_delivered", gated_mark)

    # Two separate contexts: one per session. Cross-attribution cannot be
    # masked by a shared fake object.
    ctx_a = FakeHermesPluginContext(session_id=_SESSION_A)
    ctx_b = FakeHermesPluginContext(session_id=_SESSION_B)
    run_ids: list[str] = []
    try:
        # Dispatch A from session A (immediate success).
        ack_a = plugin._dispatch_orchestra_run(
            {"goal": "session A task"}, _SESSION_A, ctx=ctx_a
        )
        assert isinstance(ack_a, str) and ack_a
        runs_a = store.list_runs(_SESSION_A)
        assert len(runs_a) == 1
        run_id_a = runs_a[0].run_id
        run_ids.append(run_id_a)

        # Dispatch B from session B (barrier + success).
        ack_b = plugin._dispatch_orchestra_run(
            {"goal": "session B task", "role": "worker-hermes"}, _SESSION_B, ctx=ctx_b
        )
        assert isinstance(ack_b, str) and ack_b
        runs_b = store.list_runs(_SESSION_B)
        assert len(runs_b) == 1
        run_id_b = runs_b[0].run_id
        run_ids.append(run_id_b)

        # A completes (success) while B is held by the barrier (still active).
        assert wait_for_condition(
            lambda: store.get_run(run_id_a).status in TERMINAL_STATUSES, timeout=30
        )
        assert store.get_run(run_id_a).status == STATUS_DONE
        # B is still active (barrier holding it).
        assert wait_for_condition(
            lambda: barrier_path.exists()
            and store.get_run(run_id_b).status not in TERMINAL_STATUSES,
            timeout=30,
        )

        # A's watcher delivers A's report without waiting for B. The mark is
        # gated, so A's report stays pending (unreported).
        assert mark_reached_a.wait(timeout=30)
        assert ctx_a.injected
        # B's context has NOT received any delivery yet.
        assert ctx_b.injected == []
        # A's report contains only A's run ID, not B's.
        report_a = next(content for content, _ in ctx_a.injected if run_id_a in content)
        assert run_id_a in report_a
        assert run_id_b not in report_a
        # A's report has the success outcome.
        assert f"{run_id_a} success]" in report_a

        # Foreign-session mark: B cannot mark A's pending report.
        assert store.get_run(run_id_a).reported_at is None
        store.mark_report_runs_delivered(_SESSION_B, [run_id_a])
        # The foreign mark is a no-op: A's run still has reported_at unset.
        assert store.get_run(run_id_a).reported_at is None
        # A's run is still pending.
        assert any(r.run_id == run_id_a for r in store.list_pending_report_runs(_SESSION_A))

        # Release A's mark: the real core mark-delivered runs.
        proceed_mark_a.set()
        assert wait_for_condition(
            lambda: store.get_run(run_id_a).reported_at is not None, timeout=30
        )
        # A's pending report disappears.
        assert not any(
            r.run_id == run_id_a for r in store.list_pending_report_runs(_SESSION_A)
        )

        # Now release B: delete the barrier so B's worker exits with code 0.
        barrier_path.unlink(missing_ok=True)
        assert wait_for_condition(
            lambda: store.get_run(run_id_b).status in TERMINAL_STATUSES, timeout=30
        )
        assert store.get_run(run_id_b).status == STATUS_DONE

        # B's watcher delivers B's report. It contains only B's run ID.
        # (B's mark is NOT gated — only A's was — so it marks immediately.)
        assert wait_for_condition(
            lambda: bool(ctx_b.injected), timeout=30
        )
        report_b = next(content for content, _ in ctx_b.injected if run_id_b in content)
        assert run_id_b in report_b
        assert run_id_a not in report_b
        assert f"{run_id_b} success]" in report_b

        # B's mark ran without gating: wait for reported_at to be set.
        assert wait_for_condition(
            lambda: store.get_run(run_id_b).reported_at is not None, timeout=30
        )
        assert store.list_pending_report_runs(_SESSION_B) == []

        # A's context did NOT receive B's report (session isolation).
        a_contents = [content for content, _ in ctx_a.injected]
        assert all(run_id_b not in c for c in a_contents)

        # Capacity released and all processes terminated.
        assert store.count_active_runs(_SESSION_A) == 0
        assert store.count_active_runs(_SESSION_B) == 0
        for rid in run_ids:
            rec = store.get_run(rid)
            sup_pid = rec.supervisor_pid
            proc_pid = rec.process_id

            def _sup_dead(s: int | None = sup_pid) -> bool:
                return not _process_alive(s)

            def _proc_dead(p: int | None = proc_pid) -> bool:
                return not _process_alive(p)

            assert wait_for_condition(_sup_dead, timeout=15)
            assert wait_for_condition(_proc_dead, timeout=15)
    finally:
        proceed_mark_a.set()
        barrier_path.unlink(missing_ok=True)
        _cleanup_runs(seam, store, session_ids=[_SESSION_A, _SESSION_B], run_ids=run_ids)
