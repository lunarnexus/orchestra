"""Dispatch acceptance flow tests.

Connected behavioral coverage for the acceptance journey: real CLI/core with
isolated config/SQLite/artifacts, a real detached supervisor, and a controlled
fake subagent. Fixture config values drive admission and timeouts; shipped
defaults are never asserted. Scope ends at acceptance/ack; terminal completion
is awaited only for deterministic process cleanup and state observation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from orchestra.context import AppError, load_context
from orchestra.dispatch import start_run
from orchestra.state import STATUS_DONE, STATUS_QUEUED, TERMINAL_STATUSES, StateStore
from tests.helpers import extract_run_id, run_cli, wait_for_condition
from tests.test_hermes_plugin_source import (
    ROLE_METADATA_NO_OPT_IN_JSON,
    FakeHermesPluginContext,
    _core_error_envelope,
    completed,
    load_plugin,
)
from tests.types import RuntimeFilesFactory

_SESSION = "manual:acceptance"


def _set_config(
    config_path: Path,
    *,
    default_timeout: int,
    global_limit: int,
    per_session: int,
) -> None:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["default_timeout"] = default_timeout
    config["concurrency"] = {"global": global_limit, "per_session": per_session}
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def _set_catalog_roles(catalog_path: Path, extra_roles: dict[str, dict[str, Any]]) -> None:
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    catalog["roles"].update(extra_roles)
    catalog_path.write_text(yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8")


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


def _wait_terminal(store: StateStore, run_id: str, *, timeout: float = 20.0) -> bool:
    return wait_for_condition(
        lambda: store.get_run(run_id).status in TERMINAL_STATUSES,
        timeout=timeout,
    )


def _wait_session_idle(store: StateStore, session_id: str, *, timeout: float = 25.0) -> bool:
    return wait_for_condition(
        lambda: store.count_active_runs(session_id) == 0,
        timeout=timeout,
    )


def _immediate_worker(python_executable: str, fake_worker_script: Path) -> list[str]:
    return [python_executable, str(fake_worker_script), "success", "--output", "worker ok"]


def _sleep_worker(python_executable: str, fake_worker_script: Path, seconds: str) -> list[str]:
    return [
        python_executable,
        str(fake_worker_script),
        "sleep",
        "--sleep",
        seconds,
        "--output",
        "late",
    ]


def test_dispatch_acceptance_full_flow(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, _, db_path = runtime_files_factory(
        tmp_path,
        _immediate_worker(python_executable, fake_worker_script),
    )
    _set_config(config_path, default_timeout=45, global_limit=2, per_session=2)
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    do = run_cli(
        "--config",
        config_dir,
        "do",
        "--session-id",
        _SESSION,
        "--goal",
        "acceptance flow goal",
        "--task-label",
        "flow label",
        "--json",
    )
    assert do.returncode == 0, do.stderr

    payload = json.loads(do.stdout)
    assert payload["kind"] == "dispatch"
    assert payload["ok"] is True
    run_id = payload["run_id"]
    assert isinstance(run_id, str) and run_id
    assert payload["role"] == "worker"
    assert payload["status"] == STATUS_QUEUED
    # Effective timeout comes from the fixture config (45), not the shipped default (1500).
    assert payload["timeout_seconds"] == 45

    # Owner-scoped durable assignment in the real store.
    record = store.get_run(run_id)
    assert record.orchestrator_session_id == _SESSION
    assert record.role == "worker"
    assert record.task_label == "flow label"

    # Durable assignment persisted for the supervisor.
    request_file = tmp_path / "state" / "runs" / run_id / "request.json"
    request = json.loads(request_file.read_text(encoding="utf-8"))
    assert request["goal"] == "acceptance flow goal"
    assert request["role_name"] == "worker"
    assert request["task_label"] == "flow label"
    assert request["timeout_seconds"] == 45

    # Actual launch: a detached supervisor is recorded and alive.
    assert wait_for_condition(lambda: store.get_run(run_id).supervisor_pid is not None, timeout=5)
    supervisor_pid = store.get_run(run_id).supervisor_pid
    assert _process_alive(supervisor_pid)

    # State observation only (no host-return claim): the controlled fake subagent completes.
    assert _wait_terminal(store, run_id)
    record = store.get_run(run_id)
    assert record.status == STATUS_DONE
    assert "worker ok" in (record.result_summary or "")

    # Deterministic process cleanup: worker and supervisor both exit.
    assert wait_for_condition(
        lambda: not _process_alive(store.get_run(run_id).supervisor_pid), timeout=10
    )
    assert wait_for_condition(
        lambda: not _process_alive(store.get_run(run_id).process_id), timeout=10
    )

    # Owner scope: another session does not see this run.
    other = run_cli("--config", config_dir, "status", "--session-id", "manual:other")
    assert other.returncode == 0
    assert run_id not in other.stdout

    # Ack contract: "accepted", with capacity reflecting the fixture config.
    ack = run_cli(
        "--config",
        config_dir,
        "_dispatch-ack",
        "--run-id",
        run_id,
        "--role",
        "worker",
        "--json",
    )
    assert ack.returncode == 0, ack.stderr
    ack_payload = json.loads(ack.stdout)
    assert ack_payload["kind"] == "dispatch_ack"
    assert ack_payload["ok"] is True
    assert ack_payload["run_id"] == run_id
    assert ack_payload["role"] == "worker"
    assert ack_payload["concurrency_limit"] == 2
    assert ack_payload["concurrency_slots_remaining"] == 2


def test_dispatch_per_session_admission_responds_to_fixture_config(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, _, db_path = runtime_files_factory(
        tmp_path,
        _sleep_worker(python_executable, fake_worker_script, "2.5"),
    )
    _set_config(config_path, default_timeout=60, global_limit=4, per_session=2)
    config_dir = str(config_path.parent)
    session = "manual:cap"
    store = StateStore(db_path)

    first = run_cli(
        "--config", config_dir, "do", "--session-id", session, "--goal", "hold slot one"
    )
    second = run_cli(
        "--config", config_dir, "do", "--session-id", session, "--goal", "hold slot two"
    )
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert wait_for_condition(lambda: store.count_active_runs(session) == 2, timeout=5)

    rejected = run_cli(
        "--config", config_dir, "do", "--session-id", session, "--goal", "should fail fast"
    )
    assert rejected.returncode == 1
    combined = rejected.stdout + rejected.stderr
    assert "per-session concurrency limit exceeded" in combined
    assert "re-dispatch" in combined
    # Fail fast, no queueing: the rejected goal never becomes a run.
    assert all(run.task_label != "should fail fast" for run in store.list_runs(session))

    # Slots release after completion; a new dispatch is accepted.
    assert _wait_session_idle(store, session)
    released = run_cli(
        "--config", config_dir, "do", "--session-id", session, "--goal", "after release"
    )
    assert released.returncode == 0, released.stderr
    released_id = extract_run_id(released.stdout)
    assert _wait_terminal(store, released_id)
    assert store.get_run(released_id).status == STATUS_DONE


def test_dispatch_global_limit_responds_to_fixture_config(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, _, db_path = runtime_files_factory(
        tmp_path,
        _sleep_worker(python_executable, fake_worker_script, "2.5"),
    )
    _set_config(config_path, default_timeout=60, global_limit=1, per_session=2)
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    first = run_cli(
        "--config", config_dir, "do",
        "--session-id", "manual:global-a", "--goal", "hold global slot",
    )
    assert first.returncode == 0, first.stderr
    assert wait_for_condition(lambda: store.count_active_runs("manual:global-a") == 1, timeout=5)

    rejected = run_cli(
        "--config", config_dir, "do",
        "--session-id", "manual:global-b", "--goal", "should fail fast",
    )
    assert rejected.returncode == 1
    combined = rejected.stdout + rejected.stderr
    assert "global concurrency limit exceeded" in combined
    assert "re-dispatch" in combined
    assert store.count_active_runs("manual:global-b") == 0

    assert _wait_session_idle(store, "manual:global-a")
    released = run_cli(
        "--config", config_dir, "do", "--session-id", "manual:global-b", "--goal", "after release"
    )
    assert released.returncode == 0, released.stderr
    released_id = extract_run_id(released.stdout)
    assert _wait_terminal(store, released_id)
    assert store.get_run(released_id).status == STATUS_DONE


def test_dispatch_role_selection_and_rejections(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        _immediate_worker(python_executable, fake_worker_script),
    )
    _set_config(config_path, default_timeout=60, global_limit=2, per_session=2)
    _set_catalog_roles(
        catalog_path,
        {
            "disabled-role": {"harness_config": "pi", "enabled": False},
            "auto-role": {"harness_config": "pi", "enabled": "auto"},
        },
    )
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    default = run_cli(
        "--config", config_dir, "do", "--session-id", _SESSION, "--goal", "default role task"
    )
    assert default.returncode == 0, default.stderr
    default_id = extract_run_id(default.stdout)
    # The fixture catalog's default_role is used, not a shipped default.
    assert store.get_run(default_id).role == "worker"
    assert _wait_terminal(store, default_id)

    unknown = run_cli(
        "--config", config_dir, "do",
        "--session-id", _SESSION, "--goal", "x", "--role", "missing-role",
    )
    assert unknown.returncode == 1
    assert "unknown role: missing-role" in unknown.stdout + unknown.stderr

    disabled = run_cli(
        "--config", config_dir, "do",
        "--session-id", _SESSION, "--goal", "x", "--role", "disabled-role",
    )
    assert disabled.returncode == 1
    assert "role is disabled: disabled-role" in disabled.stdout + disabled.stderr

    auto_only = run_cli(
        "--config", config_dir, "do", "--session-id", _SESSION, "--goal", "x", "--role", "auto-role"
    )
    assert auto_only.returncode == 1
    assert "role is auto-only: auto-role" in auto_only.stdout + auto_only.stderr

    assert store.count_active_runs(_SESSION) == 0


def test_dispatch_budget_env_admission(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, _, db_path = runtime_files_factory(
        tmp_path,
        _immediate_worker(python_executable, fake_worker_script),
    )
    _set_config(config_path, default_timeout=60, global_limit=2, per_session=2)
    config_dir = str(config_path.parent)
    store = StateStore(db_path)

    # Invalid budget values fail closed as exhausted (budget=1 rejection is covered elsewhere).
    monkeypatch.setenv("ORCHESTRA_DISPATCH_BUDGET", "banana")
    invalid = run_cli(
        "--config", config_dir, "do", "--session-id", _SESSION, "--goal", "invalid budget"
    )
    assert invalid.returncode == 1
    assert "ORCHESTRA_DISPATCH_BUDGET dispatch budget exhausted" in invalid.stdout + invalid.stderr

    monkeypatch.setenv("ORCHESTRA_DISPATCH_BUDGET", "2")
    allowed = run_cli(
        "--config", config_dir, "do", "--session-id", _SESSION, "--goal", "budget two"
    )
    assert allowed.returncode == 0, allowed.stderr
    allowed_id = extract_run_id(allowed.stdout)
    assert _wait_terminal(store, allowed_id)
    assert store.get_run(allowed_id).status == STATUS_DONE


def test_dispatch_post_reservation_write_failure_reports_error(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, _, _ = runtime_files_factory(
        tmp_path,
        [python_executable, "-c", "print('never')"],
    )
    _set_config(config_path, default_timeout=60, global_limit=4, per_session=1)
    context = load_context(config_path=str(config_path.parent))

    source = tmp_path / "parent-context.jsonl"
    source.write_text('{"role": "user", "content": "captured"}\n', encoding="utf-8")

    def _fail_copy(source_path: Any, target_path: Any) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr("orchestra.dispatch.copy_private_file", _fail_copy)

    with pytest.raises(AppError, match="parent context artifact could not be read"):
        start_run(
            context,
            session_id=_SESSION,
            role_name=None,
            goal="fail after reserve",
            additional_context="",
            boundaries="",
            acceptance_target="",
            return_format="",
            timeout_seconds=None,
            task_label="",
            batch_id=None,
            parent_context_artifact=str(source),
        )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known defect (dispatch-acceptance audit F1): a post-reservation parent-context "
        "write failure raises without releasing the capacity reservation. The orphaned "
        "queued run has no supervisor_pid, so reconcile_stale_queued_runs skips it until "
        "the 30s startup grace period elapses; an immediate re-dispatch - the action the "
        "error guidance recommends - spuriously fails the per-session limit. Desired "
        "invariant: the failed acceptance releases the session slot so the re-dispatch "
        "succeeds."
    ),
)
def test_dispatch_post_reservation_write_failure_releases_session_slot(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, _, _ = runtime_files_factory(
        tmp_path,
        [python_executable, "-c", "print('never')"],
    )
    _set_config(config_path, default_timeout=60, global_limit=4, per_session=1)
    context = load_context(config_path=str(config_path.parent))

    source = tmp_path / "parent-context.jsonl"
    source.write_text('{"role": "user", "content": "captured"}\n', encoding="utf-8")

    def _fail_copy(source_path: Any, target_path: Any) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr("orchestra.dispatch.copy_private_file", _fail_copy)

    with pytest.raises(AppError, match="parent context artifact could not be read"):
        start_run(
            context,
            session_id=_SESSION,
            role_name=None,
            goal="fail after reserve",
            additional_context="",
            boundaries="",
            acceptance_target="",
            return_format="",
            timeout_seconds=None,
            task_label="",
            batch_id=None,
            parent_context_artifact=str(source),
        )

    # Desired invariant: the failed acceptance releases the session's capacity, so the
    # immediate re-dispatch the error guidance recommends can succeed.
    retry = start_run(
        context,
        session_id=_SESSION,
        role_name=None,
        goal="immediate re-dispatch",
        additional_context="",
        boundaries="",
        acceptance_target="",
        return_format="",
        timeout_seconds=None,
        task_label="",
        batch_id=None,
    )
    assert retry.record.status == STATUS_QUEUED


def test_hermes_dispatch_starts_watcher_before_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()
    events: list[str] = []

    def fake_run(args: list[str], **_kwargs: Any) -> Any:
        events.append(args[0])
        if args[0] == "do":
            return completed(
                args,
                json.dumps(
                    {
                        "kind": "dispatch",
                        "ok": True,
                        "run_id": "abc123",
                        "role": "worker",
                        "timeout_seconds": 600,
                    }
                ),
            )
        if args[0] == "_dispatch-ack":
            return completed(args, "orchestra dispatched: worker abc123\nack instruction")
        if args[0] == "_role-metadata":
            return completed(args, ROLE_METADATA_NO_OPT_IN_JSON)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    monkeypatch.setattr(
        plugin,
        "_start_session_report_watcher",
        lambda *_args, **_kwargs: events.append("watcher-started"),
    )

    result = plugin._dispatch_orchestra_run({"goal": "ship it"}, "hermes:runtime")

    assert "abc123" in result
    assert events.index("do") < events.index("watcher-started") < events.index("_dispatch-ack")


def test_hermes_ack_error_preserves_accepted_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = load_plugin()

    def fake_run(args: list[str], **_kwargs: Any) -> Any:
        if args[0] == "do":
            return completed(
                args,
                json.dumps(
                    {
                        "kind": "dispatch",
                        "ok": True,
                        "run_id": "abc123",
                        "role": "worker",
                        "timeout_seconds": 600,
                    }
                ),
            )
        if args[0] == "_dispatch-ack":
            return completed(args, _core_error_envelope("ack exploded"), code=1)
        if args[0] == "_await-session-report":
            return completed(
                args,
                json.dumps(
                    {
                        "runIds": ["abc123"],
                        "report": "[orchestra: worker abc123 success]\nsummary: done",
                    }
                ),
            )
        if args[0] == "_role-metadata":
            return completed(args, ROLE_METADATA_NO_OPT_IN_JSON)
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(plugin, "_run_orchestra", fake_run)
    ctx = FakeHermesPluginContext(session_id="hermes:runtime")

    result = plugin._dispatch_orchestra_run({"goal": "ship it"}, "hermes:runtime", ctx=ctx)

    # The model is told the ack failed...
    assert json.loads(result) == {"error": "ack exploded"}
    # ...but the accepted run is preserved: its watcher still delivers the report.
    assert wait_for_condition(
        lambda: any("abc123" in content for content, _ in ctx.injected),
        timeout=10,
    )
