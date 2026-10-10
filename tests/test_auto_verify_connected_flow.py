"""Connected automatic verification journeys.

Two full connected Hermes journeys exercising the real auto-verify chain:
real Hermes plugin dispatch entry point, real Orchestra CLI/core/SQLite,
real detached builder AND verifier supervisors/processes, and controlled fake
subagents. Only the host delivery boundary is simulated (the in-process
host context that receives the injected report).

Journey 1: builder done -> real verifier launch -> verifier done ->
  consolidated report with both success outcomes delivered.
Journey 2: builder done -> real verifier launch -> verifier nonzero failed ->
  consolidated report with builder success + verifier failure delivered.

The barrier mechanism holds the verifier worker active so the test can
deterministically observe the intermediate state (builder done, verifier
active, no report available) before releasing the verifier to complete.

Limitations: this proves host-context delivery into the simulated Hermes
context, not live-chat delivery or model consumption. Atomicity of the
terminalize+reserve transaction is proven by the existing gap-checking
test (tests/test_auto_verify.py::test_builder_finalization_reserves_verifier_
without_zero_active_gap), not by E2E scheduling observations alone.
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

from orchestra.state import STATUS_DONE, STATUS_FAILED, TERMINAL_STATUSES, StateStore
from tests.helpers import wait_for_condition
from tests.test_hermes_plugin_source import FakeHermesPluginContext, load_plugin

_ORIGIN = "hermes:runtime"
ROOT_PROMPTS = Path(__file__).resolve().parents[1] / "prompts.yaml"


def _write_auto_verify_config(
    tmp_path: Path,
    python_executable: str,
    fake_worker_script: Path,
    *,
    verifier_args: list[str],
    default_timeout: int = 60,
    global_limit: int = 4,
    per_session: int = 4,
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
                "concurrency": {"global": global_limit, "per_session": per_session},
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
        "success",
        "--output",
        "builder done",
    ]
    verifier_command = [
        python_executable,
        str(fake_worker_script),
        *verifier_args,
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
    """Owner-scoped cleanup: stop any still-active runs and wait bounded for
    worker/supervisor termination. Never raises, so cleanup cannot mask the
    original test failure."""
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


def test_auto_verify_connected_builder_done_verifier_done(
    tmp_path: Path,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Journey 1: builder operational done -> actual automatic verifier launch
    -> verifier done. Consolidated report with both success outcomes."""
    barrier_path = tmp_path / "verifier_barrier"
    config_path, _, db_path = _write_auto_verify_config(
        tmp_path,
        python_executable,
        fake_worker_script,
        verifier_args=["success", "--output", "verifier done", "--barrier", str(barrier_path)],
    )
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    seam = _make_seam(config_dir)
    plugin = load_plugin()
    monkeypatch.setattr(plugin, "_run_orchestra", seam)

    ctx = FakeHermesPluginContext(session_id=_ORIGIN)
    run_ids: list[str] = []
    try:
        ack = plugin._dispatch_orchestra_run({"goal": "ship the feature"}, _ORIGIN, ctx=ctx)
        assert isinstance(ack, str) and ack

        # The accepted builder run belongs to the originating session.
        runs = store.list_runs(_ORIGIN)
        assert len(runs) == 1
        builder_run_id = runs[0].run_id
        run_ids.append(builder_run_id)
        builder_record = store.get_run(builder_run_id)
        assert builder_record.orchestrator_session_id == _ORIGIN
        assert builder_record.role == "builder"

        # Wait for the builder to reach terminal (done).
        assert wait_for_condition(
            lambda: store.get_run(builder_run_id).status in TERMINAL_STATUSES, timeout=30
        )
        builder_record = store.get_run(builder_run_id)
        assert builder_record.status == STATUS_DONE

        # The builder produced a non-empty return artifact.
        builder_return = tmp_path / "state" / "runs" / builder_run_id / "return.md"
        assert builder_return.exists()
        assert "builder done" in builder_return.read_text(encoding="utf-8")

        # The real auto-verify chain reserved and launched the verifier child.
        # Wait for the verifier run to appear in the store.
        assert wait_for_condition(
            lambda: len(store.list_runs(_ORIGIN, limit=10)) == 2, timeout=15
        )
        all_runs = store.list_runs(_ORIGIN, limit=10)
        verifier_runs = [
            run for run in all_runs if run.trigger_reason == "auto_verify"
        ]
        assert len(verifier_runs) == 1
        verifier_run = verifier_runs[0]
        run_ids.append(verifier_run.run_id)

        # Exactly one linked normal verifier with correct owner/trigger/builder link.
        assert verifier_run.role == "verifier"
        assert verifier_run.triggered_by_run_id == builder_run_id
        assert verifier_run.trigger_reason == "auto_verify"
        assert verifier_run.orchestrator_session_id == _ORIGIN

        # Wait for the verifier to be provably active (barrier file exists = worker started).
        assert wait_for_condition(lambda: barrier_path.exists(), timeout=30)

        # While the verifier is provably active: the report is unavailable.
        verifier_record = store.get_run(verifier_run.run_id)
        assert verifier_record.status in ("queued", "running")
        assert store.list_pending_report_runs(_ORIGIN) == []

        # No host delivery yet (the report watcher is still waiting).
        assert not ctx.injected

        # Release the barrier: the verifier worker proceeds and exits successfully.
        barrier_path.unlink()

        # Wait for the verifier to reach terminal (done).
        assert wait_for_condition(
            lambda: store.get_run(verifier_run.run_id).status in TERMINAL_STATUSES,
            timeout=30,
        )
        verifier_record = store.get_run(verifier_run.run_id)
        assert verifier_record.status == STATUS_DONE

        # The verifier produced a non-empty return artifact.
        verifier_return = tmp_path / "state" / "runs" / verifier_run.run_id / "return.md"
        assert verifier_return.exists()
        assert "verifier done" in verifier_return.read_text(encoding="utf-8")

        # After both are terminal: the host context receives the consolidated report.
        assert wait_for_condition(lambda: bool(ctx.injected), timeout=30)
        injected = next(content for content, _ in ctx.injected)

        # One consolidated report includes both run IDs and proper outcomes.
        assert builder_run_id in injected
        assert verifier_run.run_id in injected
        assert "builder done" in injected
        assert "verifier done" in injected
        assert "success" in injected

        # The core mark-delivered clears the pending report.
        assert wait_for_condition(
            lambda: store.get_run(builder_run_id).reported_at is not None
            and store.get_run(verifier_run.run_id).reported_at is not None,
            timeout=30,
        )
        assert store.list_pending_report_runs(_ORIGIN) == []

        # Capacity released and worker/supervisor terminated for both runs.
        assert store.count_active_runs(_ORIGIN) == 0
        builder_final = store.get_run(builder_run_id)
        verifier_final = store.get_run(verifier_run.run_id)
        assert builder_final.supervisor_pid is not None
        assert verifier_final.supervisor_pid is not None
        assert builder_final.process_id is not None
        assert verifier_final.process_id is not None
        assert wait_for_condition(
            lambda: not _process_alive(builder_final.supervisor_pid)
            and not _process_alive(verifier_final.supervisor_pid),
            timeout=15,
        )
        assert wait_for_condition(
            lambda: not _process_alive(builder_final.process_id)
            and not _process_alive(verifier_final.process_id),
            timeout=15,
        )

        # Original assignment scope/acceptance/evidence references preserved
        # in the verifier's request (semantic: the verifier was told what to verify).
        verifier_request_path = (
            tmp_path / "state" / "runs" / verifier_run.run_id / "request.json"
        )
        assert verifier_request_path.exists()
        verifier_request = yaml.safe_load(verifier_request_path.read_text(encoding="utf-8"))
        assert "Verify only builder run" in verifier_request["goal"]
        assert "ship the feature" in verifier_request["additional_context"]

    finally:
        _cleanup_runs(seam, store, session_id=_ORIGIN, run_ids=run_ids)


def test_auto_verify_connected_builder_done_verifier_failed(
    tmp_path: Path,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Journey 2: builder done -> actual verifier launch -> verifier nonzero
    failed. Builder remains done; consolidated report shows both outcomes."""
    barrier_path = tmp_path / "verifier_barrier"
    config_path, _, db_path = _write_auto_verify_config(
        tmp_path,
        python_executable,
        fake_worker_script,
        verifier_args=["fail", "--output", "verifier failed", "--barrier", str(barrier_path)],
    )
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    seam = _make_seam(config_dir)
    plugin = load_plugin()
    monkeypatch.setattr(plugin, "_run_orchestra", seam)

    ctx = FakeHermesPluginContext(session_id=_ORIGIN)
    run_ids: list[str] = []
    try:
        ack = plugin._dispatch_orchestra_run({"goal": "fix the parser"}, _ORIGIN, ctx=ctx)
        assert isinstance(ack, str) and ack

        # The accepted builder run belongs to the originating session.
        runs = store.list_runs(_ORIGIN)
        assert len(runs) == 1
        builder_run_id = runs[0].run_id
        run_ids.append(builder_run_id)
        builder_record = store.get_run(builder_run_id)
        assert builder_record.role == "builder"

        # Wait for the builder to reach terminal (done).
        assert wait_for_condition(
            lambda: store.get_run(builder_run_id).status in TERMINAL_STATUSES, timeout=30
        )
        builder_record = store.get_run(builder_run_id)
        assert builder_record.status == STATUS_DONE

        # The builder produced a non-empty return artifact.
        builder_return = tmp_path / "state" / "runs" / builder_run_id / "return.md"
        assert builder_return.exists()
        assert "builder done" in builder_return.read_text(encoding="utf-8")

        # Wait for the verifier run to appear.
        assert wait_for_condition(
            lambda: len(store.list_runs(_ORIGIN, limit=10)) == 2, timeout=15
        )
        all_runs = store.list_runs(_ORIGIN, limit=10)
        verifier_runs = [
            run for run in all_runs if run.trigger_reason == "auto_verify"
        ]
        assert len(verifier_runs) == 1
        verifier_run = verifier_runs[0]
        run_ids.append(verifier_run.run_id)

        # Exactly one linked normal verifier with correct owner/trigger/builder link.
        assert verifier_run.role == "verifier"
        assert verifier_run.triggered_by_run_id == builder_run_id
        assert verifier_run.trigger_reason == "auto_verify"

        # Wait for the verifier to be provably active.
        assert wait_for_condition(lambda: barrier_path.exists(), timeout=30)

        # While the verifier is provably active: no report available.
        verifier_record = store.get_run(verifier_run.run_id)
        assert verifier_record.status in ("queued", "running")
        assert store.list_pending_report_runs(_ORIGIN) == []
        assert not ctx.injected

        # Release the barrier: the verifier worker proceeds and exits nonzero.
        barrier_path.unlink()

        # Wait for the verifier to reach terminal (failed).
        assert wait_for_condition(
            lambda: store.get_run(verifier_run.run_id).status in TERMINAL_STATUSES,
            timeout=30,
        )
        verifier_record = store.get_run(verifier_run.run_id)
        assert verifier_record.status == STATUS_FAILED

        # Builder remains done (verifier failure does not change builder status).
        builder_final = store.get_run(builder_run_id)
        assert builder_final.status == STATUS_DONE

        # The verifier produced a non-empty return artifact.
        verifier_return = tmp_path / "state" / "runs" / verifier_run.run_id / "return.md"
        assert verifier_return.exists()
        content = verifier_return.read_text(encoding="utf-8")
        assert "verifier failed" in content

        # After both are terminal: the host context receives the consolidated report.
        assert wait_for_condition(lambda: bool(ctx.injected), timeout=30)
        injected = next(content for content, _ in ctx.injected)

        # One consolidated report includes both run IDs.
        assert builder_run_id in injected
        assert verifier_run.run_id in injected

        # Builder shows success; verifier shows failure.
        assert "builder done" in injected
        assert "success" in injected
        assert "fail" in injected

        # The core mark-delivered clears the pending report.
        assert wait_for_condition(
            lambda: store.get_run(builder_run_id).reported_at is not None
            and store.get_run(verifier_run.run_id).reported_at is not None,
            timeout=30,
        )
        assert store.list_pending_report_runs(_ORIGIN) == []

        # Capacity released and worker/supervisor terminated for both runs.
        assert store.count_active_runs(_ORIGIN) == 0
        verifier_final = store.get_run(verifier_run.run_id)
        assert builder_final.supervisor_pid is not None
        assert verifier_final.supervisor_pid is not None
        assert builder_final.process_id is not None
        assert verifier_final.process_id is not None
        assert wait_for_condition(
            lambda: not _process_alive(builder_final.supervisor_pid)
            and not _process_alive(verifier_final.supervisor_pid),
            timeout=15,
        )
        assert wait_for_condition(
            lambda: not _process_alive(builder_final.process_id)
            and not _process_alive(verifier_final.process_id),
            timeout=15,
        )

    finally:
        _cleanup_runs(seam, store, session_id=_ORIGIN, run_ids=run_ids)
