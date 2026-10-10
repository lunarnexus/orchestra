"""Success-and-delivery functional test.

Connected journey for the owner-approved success/delivery slice: the real Hermes
plugin dispatch entry point and report watcher drive the real Orchestra
CLI/core/SQLite with an isolated config, a real detached supervisor, and a
controlled fake subagent. Only the Hermes host-context delivery boundary is
simulated (the in-process host context that receives the injected report). The
runner seam invokes the real ``python -m orchestra`` with the isolated config;
core responses are never stubbed and terminal runs are never seeded by hand.

The slice proves: the accepted run belongs to the runtime originating session;
the controlled worker produces the expected result and full return artifact; the
report stays unreported until the host accepts delivery; the report reaches only
the correct host/session (another session cannot retrieve or mark it, exact-owner
semantics); the core mark-delivered clears the pending report; capacity is
released and the worker/supervisor terminate.

Limitations: this proves host-context delivery into the simulated Hermes context,
not live-chat delivery or model consumption, and it does not prove exactly-once
delivery (a next watcher can redeliver an unmarked report).
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

from orchestra.state import STATUS_DONE, TERMINAL_STATUSES, StateStore
from tests.helpers import wait_for_condition
from tests.test_hermes_plugin_source import FakeHermesPluginContext, load_plugin

_ORIGIN = "hermes:runtime"
_OTHER = "hermes:other"


def _set_config(
    config_path: Path, *, default_timeout: int, global_limit: int, per_session: int
) -> None:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["default_timeout"] = default_timeout
    config["concurrency"] = {"global": global_limit, "per_session": per_session}
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


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
    """Runner seam: invoke the real Orchestra CLI (``python -m orchestra``) with the
    isolated config. This is not a stub -- it runs the real core, SQLite, and the
    real detached supervisor. Mirrors the plugin's ``_run_orchestra`` timeout/input
    contract so the watcher and dispatch behave exactly as in production."""

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


def _stop_run_and_wait(
    seam: Callable[[list[str]], subprocess.CompletedProcess[str]],
    store: StateStore,
    *,
    session_id: str,
    run_id: str,
    timeout: float = 15.0,
) -> None:
    """Owner-scoped cleanup: stop the run if still active, then wait bounded for the
    worker process and supervisor to terminate. A pre-terminal assertion failure must
    not leave the launched run running until the 60s default timeout. Never raises, so
    cleanup cannot mask the original test failure."""
    try:
        record = store.get_run(run_id)
        if record.status not in TERMINAL_STATUSES:
            seam(["stop", "--session-id", session_id, "--run-id", run_id])
        wait_for_condition(
            lambda: not _process_alive(record.process_id)
            and not _process_alive(record.supervisor_pid),
            timeout=timeout,
        )
    except Exception:  # cleanup must never mask the original test failure
        pass


def test_success_delivery_full_journey(
    tmp_path: Path,
    runtime_files_factory: Any,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    # Barrier: gate the real core mark-delivered so the unreported-before-acceptance
    # state is observable deterministically. The real mark still runs once released.
    mark_reached = threading.Event()
    proceed_mark = threading.Event()
    real_mark = plugin._mark_session_report_delivered

    def gated_mark(runtime_session_id: str, run_ids: list[str]) -> Any:
        mark_reached.set()
        proceed_mark.wait(timeout=30)
        return real_mark(runtime_session_id, run_ids)

    monkeypatch.setattr(plugin, "_mark_session_report_delivered", gated_mark)

    ctx = FakeHermesPluginContext(session_id=_ORIGIN)
    run_id: str | None = None
    try:
        ack = plugin._dispatch_orchestra_run({"goal": "ship the success slice"}, _ORIGIN, ctx=ctx)
        # Dispatch is async: it returns the ack, not the report.
        assert isinstance(ack, str) and ack

        # The accepted run belongs to the runtime originating session.
        runs = store.list_runs(_ORIGIN)
        assert len(runs) == 1
        run_id = runs[0].run_id
        record = store.get_run(run_id)
        assert record.orchestrator_session_id == _ORIGIN
        assert record.role == "worker"

        # Deterministic completion: the real supervisor runs the controlled fake
        # subagent to a terminal (done) state.
        assert wait_for_condition(
            lambda: store.get_run(run_id).status in TERMINAL_STATUSES, timeout=30
        )
        record = store.get_run(run_id)
        assert record.status == STATUS_DONE

        # Controlled worker produced the expected result and the full return artifact.
        assert "worker ok" in (record.result_summary or "")
        return_path = tmp_path / "state" / "runs" / run_id / "return.md"
        assert return_path.exists()
        assert "worker ok" in return_path.read_text(encoding="utf-8")

        # The host context receives the report; the mark is now gated, so the report
        # must still be unreported (host has accepted delivery, core has not claimed it).
        assert mark_reached.wait(timeout=30)
        assert ctx.injected
        assert store.get_run(run_id).reported_at is None
        assert any(run.run_id == run_id for run in store.list_pending_report_runs(_ORIGIN))

        # The report reaches only the correct host/session: another session cannot
        # retrieve it...
        assert not any(run.run_id == run_id for run in store.list_pending_report_runs(_OTHER))
        # ...or mark it (exact-owner semantics: the wrong session leaves reported_at unset).
        store.mark_report_runs_delivered(_OTHER, [run_id])
        assert store.get_run(run_id).reported_at is None

        # The injected report carries the originating run and a success outcome.
        injected = next(content for content, _ in ctx.injected if run_id in content)
        assert "worker ok" in injected
        assert "success" in injected

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
        # Never leave the watcher thread blocked on the barrier.
        proceed_mark.set()
        # Even when a pre-terminal assertion fails, terminate the launched run
        # promptly (owner-scoped) and wait bounded for the worker/supervisor to
        # exit instead of leaving them until the 60s default timeout.
        if run_id is not None:
            _stop_run_and_wait(seam, store, session_id=_ORIGIN, run_id=run_id)
