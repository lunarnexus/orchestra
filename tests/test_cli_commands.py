from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from orchestra.state import STATUS_DONE, StateStore
from tests.helpers import extract_run_id, wait_for_condition
from tests.types import RuntimeFilesFactory


def test_do_status_history_flow(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "worker done"],
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:test-session",
            "--goal",
            "Summarize repository status.",
        ]
    )
    do_output = capsys.readouterr().out

    assert exit_code == 0
    assert "dispatch: queued for supervision" in do_output
    run_id = extract_run_id(do_output)

    assert wait_for_condition(
        lambda: StateStore(db_path).get_run(run_id).status == STATUS_DONE,
        timeout=5,
    )

    history_exit = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "history",
            "--session-id",
            "manual:test-session",
        ]
    )
    history_output = capsys.readouterr().out

    assert history_exit == 0
    assert "history_count: 1" in history_output
    assert "worker done" in history_output


def test_roles_lists_configured_worker_roles(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, _ = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success"],
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "roles",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "roles:" in output
    assert "- worker enabled=true harness=pi default=true" in output


def test_status_reports_active_run(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "sleep", "--sleep", "2", "--output", "slept"],
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:test-session",
            "--goal",
            "Run a long worker.",
        ]
    )
    do_output = capsys.readouterr().out
    run_id = extract_run_id(do_output)

    assert exit_code == 0
    assert wait_for_condition(
        lambda: StateStore(db_path).get_run(run_id).status == "running",
        timeout=5,
    )

    status_exit = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "status",
            "--session-id",
            "manual:test-session",
        ]
    )
    status_output = capsys.readouterr().out

    assert status_exit == 0
    assert "active_runs: 1" in status_output
    assert run_id in status_output


def test_stop_command_enforces_ownership(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, _ = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success"],
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "stop",
            "--session-id",
            "manual:other",
            "--run-id",
            "missing",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "run not found" in captured.out


def test_doctor_command_checks_local_setup(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, _ = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success"],
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "doctor",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "config: ok" in captured.out
    assert "agent_catalog: ok" in captured.out
    assert "database: ok" in captured.out
    assert "harness:worker: ok" in captured.out


def test_internal_command_echo_preserves_full_orch_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from orchestra.cli import main

    exit_code = main(["_command-echo", "do --role critic tell me a haiku"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.strip() == "/orch do --role critic tell me a haiku"


def test_internal_dispatch_ack_includes_role(capsys: pytest.CaptureFixture[str]) -> None:
    from orchestra.cli import main

    exit_code = main(["_dispatch-ack", "--run-id", "abc123", "--role", "critic"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.strip() == "orchestra dispatched: critic abc123"


def test_internal_progress_message_includes_role(capsys: pytest.CaptureFixture[str]) -> None:
    from orchestra.cli import main

    exit_code = main(
        [
            "_progress-message",
            "--completed",
            "1",
            "--total",
            "2",
            "--run-id",
            "abc123",
            "--status",
            "done",
            "--role",
            "critic",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.strip() == "orchestra: critic abc123 returned done (1/2)"


def test_internal_await_run_outputs_role(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "worker done"],
    )

    from orchestra.cli import main

    dispatch_exit = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:test-session",
            "--role",
            "worker",
            "--goal",
            "Finish a worker.",
        ]
    )
    dispatch_output = capsys.readouterr().out
    run_id = extract_run_id(dispatch_output)
    assert dispatch_exit == 0
    assert wait_for_condition(
        lambda: StateStore(db_path).get_run(run_id).status == STATUS_DONE,
        timeout=5,
    )

    wait_exit = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "_await-run",
            "--session-id",
            "manual:test-session",
            "--run-id",
            run_id,
        ]
    )

    output = capsys.readouterr().out
    assert wait_exit == 0
    assert "status: done" in output
    assert "role: worker" in output


def test_roles_command_lists_enabled_roles_by_default_and_all_roles_with_flag(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump({"state_dir": str(tmp_path / "state"), "log_dir": str(tmp_path / "logs")}),
        encoding="utf-8",
    )
    prompts_path.write_text("{}\n", encoding="utf-8")
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "reviewer",
                "roles": {
                    "worker": {"harness": "pi", "enabled": False},
                    "reviewer": {"harness": "hermes"},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    from orchestra.cli import main

    default_exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "roles",
        ]
    )
    default_output = capsys.readouterr().out

    all_exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "roles",
            "--all",
        ]
    )
    all_output = capsys.readouterr().out

    assert default_exit_code == 0
    assert "roles:" in default_output
    assert "default_role: reviewer" not in default_output
    assert "- reviewer enabled=true harness=hermes default=true" in default_output
    assert "disabled_roles:" not in default_output
    assert "- worker harness=pi" not in default_output

    assert all_exit_code == 0
    assert "default_role: reviewer" in all_output
    assert "- reviewer enabled=true harness=hermes default=true" in all_output
    assert "disabled_roles:" in all_output
    assert "- worker enabled=false harness=pi" in all_output


def test_host_help_and_tool_info_advertise_enabled_roles_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump({"state_dir": str(tmp_path / "state"), "log_dir": str(tmp_path / "logs")}),
        encoding="utf-8",
    )
    prompts_path.write_text("{}\n", encoding="utf-8")
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "roles": {
                    "worker": {"harness": "pi"},
                    "critic": {"harness": "hermes", "enabled": False},
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    from orchestra.cli import main

    help_exit = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "help-host",
        ]
    )
    help_output = capsys.readouterr().out

    tool_exit = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "_tool-info",
        ]
    )
    tool_output = capsys.readouterr().out
    tool_info = json.loads(tool_output)

    assert help_exit == 0
    assert tool_exit == 0
    assert "/orch roles" in help_output
    assert "- worker enabled=true harness=pi default=true" in help_output
    assert "- critic harness=hermes" not in help_output
    assert "- worker enabled=true harness=pi default=true" in tool_info["description"]
    assert "- critic harness=hermes" not in tool_info["description"]
    assert "- critic harness=hermes" not in tool_info["roleDescription"]


def test_disabled_role_is_rejected_without_fallback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump({"state_dir": str(tmp_path / "state"), "log_dir": str(tmp_path / "logs")}),
        encoding="utf-8",
    )
    prompts_path.write_text("{}\n", encoding="utf-8")
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "roles": {
                    "worker": {"harness": "pi"},
                    "critic": {"harness": "hermes", "enabled": False},
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:test-session",
            "--role",
            "critic",
            "--goal",
            "Do not run.",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "role is disabled: critic" in output
