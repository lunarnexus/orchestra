from __future__ import annotations

from pathlib import Path

import yaml

from orchestra.app import load_context
from orchestra.state import (
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_INCOMPLETE,
    RunRecord,
    StateStore,
)
from tests.helpers import extract_run_id, run_cli, wait_for_condition
from tests.types import RuntimeFilesFactory


def test_stop_terminates_owned_worker_process(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    marker = tmp_path / "marker.txt"
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [
            python_executable,
            str(fake_worker_script),
            "sleep",
            "--sleep",
            "10",
            "--marker",
            str(marker),
            "--output",
            "finished",
        ],
    )

    result = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "do",
        "--session-id",
        "manual:proc",
        "--goal",
        "Run a long worker.",
    )
    assert result.returncode == 0
    run_id = extract_run_id(result.stdout)

    assert wait_for_condition(marker.exists, timeout=5)
    store = StateStore(db_path)
    assert wait_for_condition(lambda: store.get_run(run_id).status == "running", timeout=5)

    stop = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "stop",
        "--session-id",
        "manual:proc",
        "--run-id",
        run_id,
    )
    assert stop.returncode == 0
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_CANCELLED, timeout=5)

    record = store.get_run(run_id)
    assert record.blocker_text == "Cancelled by orchestra stop"
    assert record.process_id is not None


def test_timeout_marks_run_failed_and_keeps_terminal_state(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "sleep", "--sleep", "3", "--output", "late"],
    )

    result = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "do",
        "--session-id",
        "manual:timeout",
        "--goal",
        "Run a timeout worker.",
        "--timeout",
        "1",
    )
    assert result.returncode == 0
    run_id = extract_run_id(result.stdout)

    store = StateStore(db_path)
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_FAILED, timeout=5)

    record = store.get_run(run_id)
    assert record.blocker_text == "Worker exceeded timeout"
    assert record.error_text == "Worker timed out"

    history = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "history",
        "--session-id",
        "manual:timeout",
    )
    assert history.returncode == 0
    assert "Worker exceeded timeout" in history.stdout


def test_status_reconciles_stale_queued_run_without_supervisor_owner(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "unused"],
    )
    context = load_context(config_path=config_path, catalog_path=catalog_path)
    context.store.create_run(
        RunRecord(
            run_id="stalequeued1",
            orchestrator_session_id="manual:stale",
            harness="pi",
            role="worker",
            task_label="stale queued",
            log_path=tmp_path / "logs" / "stalequeued1.jsonl",
            created_at="2000-01-01T00:00:00Z",
        )
    )

    status = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "status",
        "--session-id",
        "manual:stale",
    )

    assert status.returncode == 0
    record = StateStore(db_path).get_run("stalequeued1")
    assert record.status == STATUS_FAILED
    assert record.error_text == "Worker supervisor ownership was not recorded"
    assert "active_runs: 0" in status.stdout
    assert "supervisor.reconciled" in (tmp_path / "logs" / "stalequeued1.jsonl").read_text()


def test_zero_exit_empty_output_marks_run_failed_for_pi_hermes_and_opencode(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, "-c", "import sys"],
    )
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "pi",
                "roles": {
                    harness: {
                        "harness": harness,
                        "command": [python_executable, "-c", "import sys"],
                    }
                    for harness in ("pi", "hermes", "opencode")
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    for harness in ("pi", "hermes", "opencode"):
        result = run_cli(
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            f"manual:empty-output-{harness}",
            "--role",
            harness,
            "--goal",
            f"Run an empty-output {harness} worker.",
        )
        assert result.returncode == 0
        run_id = extract_run_id(result.stdout)

        store = StateStore(db_path)
        def run_failed(run_id: str = run_id, store: StateStore = store) -> bool:
            return store.get_run(run_id).status == STATUS_FAILED

        assert wait_for_condition(run_failed, timeout=5)

        record = store.get_run(run_id)
        assert record.harness == harness
        assert record.result_summary is None
        assert record.error_text == "Worker exited successfully without a meaningful result"
        assert record.blocker_text == "Worker protocol error: empty result"
        assert store.list_active_runs(f"manual:empty-output-{harness}") == []


def test_budget_handoff_marker_marks_run_incomplete(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    output = (
        "ORCHESTRA_STATUS: incomplete\n"
        "ORCHESTRA_STOP_REASON: budget_exceeded\n"
        "## Budget Handoff\nCompleted:\n- one slice\nRemaining:\n- next slice\n"
    )
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", output],
    )

    result = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "do",
        "--session-id",
        "manual:incomplete",
        "--goal",
        "Run a budget handoff worker.",
    )
    assert result.returncode == 0
    run_id = extract_run_id(result.stdout)

    store = StateStore(db_path)
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_INCOMPLETE, timeout=5)

    record = store.get_run(run_id)
    assert record.result_summary is not None
    assert "Budget Handoff" in record.result_summary
    assert record.blocker_text == "Worker budget exceeded; redispatch from continuation handoff"

    await_run = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "_await-run",
        "--session-id",
        "manual:incomplete",
        "--run-id",
        run_id,
    )
    assert "status: incomplete" in await_run.stdout
    assert "redispatch a smaller continuation task" in await_run.stdout

    debug = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "debug",
        "--run-id",
        run_id,
    )
    assert debug.returncode == 0
    assert "# Orchestra debug bundle" in debug.stdout
    assert "## Lifecycle log" in debug.stdout
    assert "supervisor.spawned" in debug.stdout
    assert "worker.started" in debug.stdout
    assert "## Return artifact" in debug.stdout
    assert "## Harness transcript" in debug.stdout


def test_zero_exit_bootstrap_only_output_marks_run_failed(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [
            python_executable,
            str(fake_worker_script),
            "success",
            "--output",
            "Bootstrapping worker runtime...\nWARNING: model cache missing\n",
        ],
    )

    result = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "do",
        "--session-id",
        "manual:bootstrap-output",
        "--goal",
        "Run a bootstrap-only worker.",
    )
    assert result.returncode == 0
    run_id = extract_run_id(result.stdout)

    store = StateStore(db_path)
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_FAILED, timeout=5)

    record = store.get_run(run_id)
    assert record.result_summary is None
    assert record.error_text == "Worker exited successfully without a meaningful result"
    assert record.blocker_text == "Worker protocol error: empty result"


def test_soft_timeout_must_be_less_than_effective_worker_timeout(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, _db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "unused"],
    )
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "worker",
                "roles": {
                    "worker": {
                        "harness": "pi",
                        "command": [
                            python_executable,
                            str(fake_worker_script),
                            "success",
                            "--output",
                            "unused",
                        ],
                        "soft_timeout": 5,
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "do",
        "--session-id",
        "manual:bad-soft-timeout",
        "--goal",
        "Run with invalid soft timeout.",
        "--timeout",
        "5",
    )

    assert result.returncode == 1
    assert "soft_timeout must be less than effective worker timeout" in result.stdout


def test_unknown_harness_marks_run_failed_and_clears_active_queue(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "unused"],
    )
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "worker",
                "roles": {
                    "worker": {
                        "harness": "missing",
                        "command": [
                            python_executable,
                            str(fake_worker_script),
                            "success",
                            "--output",
                            "unused",
                        ],
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "do",
        "--session-id",
        "manual:missing-harness",
        "--goal",
        "Run a worker with missing harness.",
    )
    assert result.returncode == 0
    run_id = extract_run_id(result.stdout)

    store = StateStore(db_path)
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_FAILED, timeout=5)

    record = store.get_run(run_id)
    assert record.error_text == "unknown harness: missing"
    assert record.blocker_text == "Worker harness is not configured"
    assert store.list_active_runs("manual:missing-harness") == []
    assert store.list_active_runs() == []
    assert (tmp_path / "state" / "requests" / f"{run_id}.json").exists() is True

    status = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "status",
        "--session-id",
        "manual:missing-harness",
    )
    assert status.returncode == 0
    assert "active_runs: 0" in status.stdout
    assert "status: no active runs" in status.stdout


def test_prestart_failure_uses_requested_role_harness_fallback(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "worker ok"],
    )
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "builder",
                "harness_configs": {
                    "pi": {
                        "harness": "pi",
                        "command": [
                            python_executable,
                            str(fake_worker_script),
                            "success",
                            "--output",
                            "worker ok",
                        ],
                    },
                    "hermes": {
                        "harness": "hermes",
                        "command": ["missing-hermes-binary", "-z", "{prompt}"],
                    },
                },
                "roles": {
                    "builder": {
                        "harness_config": "pi",
                    },
                    "reviewer": {
                        "harness_config": "hermes",
                        "harness_fallback": [{"harness_config": "pi"}],
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "do",
        "--session-id",
        "manual:fallback",
        "--role",
        "reviewer",
        "--goal",
        "Run with fallback.",
    )
    assert result.returncode == 0
    run_id = extract_run_id(result.stdout)

    store = StateStore(db_path)
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_DONE, timeout=5)

    record = store.get_run(run_id)
    note = "fallback: reviewer used harness_config pi after hermes failed to start"
    assert record.role == "reviewer"
    assert record.harness == "pi"
    assert not record.blocker_text
    assert record.result_summary is not None
    assert note in record.result_summary
    assert "worker ok" in record.result_summary

    await_run = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "_await-run",
        "--session-id",
        "manual:fallback",
        "--run-id",
        run_id,
    )
    assert "status: done" in await_run.stdout
    assert "role: reviewer" in await_run.stdout
    assert f"result: {note}; worker ok" in await_run.stdout
    assert "harness: pi" in await_run.stdout

    history = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "history",
        "--session-id",
        "manual:fallback",
    )
    assert note in history.stdout

    status = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "status",
        "--session-id",
        "manual:fallback",
    )
    assert "status: no active runs" in status.stdout


def test_poststart_worker_failure_does_not_fall_back_to_default_role(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "worker ok"],
    )
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "builder",
                "roles": {
                    "builder": {
                        "harness": "pi",
                        "command": [
                            python_executable,
                            str(fake_worker_script),
                            "success",
                            "--output",
                            "worker ok",
                        ],
                    },
                    "reviewer": {
                        "harness": "pi",
                        "command": [
                            python_executable,
                            str(fake_worker_script),
                            "fail",
                            "--output",
                            "reviewer failed",
                            "--stderr",
                            "reviewer stderr",
                        ],
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "do",
        "--session-id",
        "manual:no-fallback",
        "--role",
        "reviewer",
        "--goal",
        "Run without fallback.",
    )
    assert result.returncode == 0
    run_id = extract_run_id(result.stdout)

    store = StateStore(db_path)
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_FAILED, timeout=5)

    record = store.get_run(run_id)
    assert record.role == "reviewer"
    assert record.harness == "pi"
    assert record.error_text == "reviewer stderr"
    assert record.result_summary == "reviewer failed"
