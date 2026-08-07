from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from orchestra.harnesses.common import ORCHESTRA_DISPATCH_BUDGET_ENV
from orchestra.state import STATUS_DONE, StateStore
from tests.helpers import extract_run_id, wait_for_condition
from tests.types import RuntimeFilesFactory


def test_do_output_exposes_effective_timeout_seconds(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, _ = runtime_files_factory(
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
            "--timeout",
            "17",
        ]
    )
    do_output = capsys.readouterr().out

    assert exit_code == 0
    assert "timeout_seconds: 17" in do_output
    assert "dispatch: queued for supervision" in do_output


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


def test_do_rejects_over_model_limit(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, "-c", "import time; time.sleep(2); print('done')"],
    )
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    catalog["model_limits"] = {"lmstudio/qwen": {"concurrency": 1}}
    catalog["roles"]["worker"]["model"] = "lmstudio/qwen"
    catalog_path.write_text(yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8")

    from orchestra.cli import main

    first_exit = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:model-limit-a",
            "--goal",
            "hold model slot",
        ]
    )
    first_output = capsys.readouterr().out
    run_id = extract_run_id(first_output)
    store = StateStore(db_path)
    assert wait_for_condition(lambda: bool(store.list_active_runs()))

    second_exit = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:model-limit-b",
            "--goal",
            "should fail fast",
        ]
    )
    second_output = capsys.readouterr().out

    assert first_exit == 0
    assert second_exit == 1
    assert "model concurrency limit exceeded: lmstudio/qwen" in second_output
    assert "active=1 limit=1" in second_output
    assert store.get_run(run_id).model == "lmstudio/qwen"


def test_do_uses_role_worker_budget_for_worker_env(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path, catalog_path, db_path = runtime_files_factory(
        tmp_path,
        [
            python_executable,
            "-c",
            "import os; print(os.environ.get('ORCHESTRA_DISPATCH_BUDGET', 'missing'))",
        ],
    )
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    catalog["roles"]["worker"]["worker_budget"] = 2
    catalog_path.write_text(yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8")

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:worker-budget-role",
            "--goal",
            "Print worker budget env.",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    run_id = extract_run_id(output)
    assert wait_for_condition(
        lambda: StateStore(db_path).get_run(run_id).status == STATUS_DONE,
        timeout=5,
    )
    assert StateStore(db_path).get_run(run_id).result_summary == "2"


def test_do_rejects_when_orchestra_dispatch_budget_is_exhausted(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path, catalog_path, _ = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "should not run"],
    )
    monkeypatch.setenv(ORCHESTRA_DISPATCH_BUDGET_ENV, "1")

    from orchestra.cli import main

    exit_code = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:worker-budget-exhausted",
            "--goal",
            "Should be rejected.",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "ORCHESTRA_DISPATCH_BUDGET dispatch budget exhausted" in output


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
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    catalog["default_role"] = "builder"
    catalog["roles"] = {"builder": {"harness_config": "pi"}}
    catalog_path.write_text(yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8")

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
    assert "Configured roles" in output
    assert "Default: builder" in output
    assert "  D  builder [pi]" in output
    assert "      harness: pi" in output


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


def test_internal_orchestrator_skill_renders_project_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    skill_dir = tmp_path / "skills" / "orchestrator"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text("# Test skill\n\nUse it.", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    from orchestra.cli import main

    exit_code = main(["_orchestrator-skill"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output == "Load this Orchestra main-session skill:\n\n# Test skill\n\nUse it.\n"


def test_internal_orchestrator_skill_errors_when_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    import orchestra.app as app
    from orchestra.cli import main

    monkeypatch.setattr(app, "_find_source_root", lambda source_root=None: None)

    exit_code = main(["_orchestrator-skill"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "error: orchestrator skill file not found; looked for:" in output
    assert "skills/orchestrator/SKILL.md" in output


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
        yaml.safe_dump(
            {"state_dir": str(tmp_path / "state"), "log_dir": str(tmp_path / "logs"), "default_timeout": 600},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    prompts_path.write_text("{}\n", encoding="utf-8")
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "reviewer",
                "harness_configs": {
                    "pi": {"harness": "pi", "command": ["pi", "-p", "{prompt}"]},
                    "hermes": {"harness": "hermes", "command": ["hermes", "-z", "{prompt}"]},
                },
                "roles": {
                    "worker": {"harness_config": "pi", "enabled": False},
                    "reviewer": {"harness_config": "hermes"},
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
    assert "Configured roles" in default_output
    assert "Default: reviewer" in default_output
    assert "  D  reviewer [hermes]" in default_output
    assert "  ✗  worker [pi]" not in default_output

    assert all_exit_code == 0
    assert "Default: reviewer" in all_output
    assert "  D  reviewer [hermes]" in all_output
    assert "  ✗  worker [pi]" in all_output


@pytest.mark.parametrize("value", ["true", "yes", "y", "1", "on"])
def test_roles_command_accepts_common_true_enabled_values(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    value: str,
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump({"state_dir": str(tmp_path / "state"), "log_dir": str(tmp_path / "logs"), "default_timeout": 600}),
        encoding="utf-8",
    )
    prompts_path.write_text("{}\n", encoding="utf-8")
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "builder",
                "harness_configs": {
                    "pi": {"harness": "pi", "command": ["pi", "-p", "{prompt}"]},
                },
                "roles": {
                    "builder": {"harness_config": "pi"},
                    "reviewer": {"harness_config": "pi", "enabled": False},
                },
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
            "roles",
            "reviewer",
            "enabled",
            value,
        ]
    )
    output = capsys.readouterr().out
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert "Updated role reviewer: enabled=true" in output
    assert "  ✓  reviewer [pi]" in output
    assert catalog["roles"]["reviewer"]["enabled"] is True


@pytest.mark.parametrize("value", ["false", "no", "n", "0", "off"])
def test_roles_command_accepts_common_false_enabled_values(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    value: str,
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump({"state_dir": str(tmp_path / "state"), "log_dir": str(tmp_path / "logs"), "default_timeout": 600}),
        encoding="utf-8",
    )
    prompts_path.write_text("{}\n", encoding="utf-8")
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "builder",
                "harness_configs": {
                    "pi": {"harness": "pi", "command": ["pi", "-p", "{prompt}"]},
                },
                "roles": {
                    "builder": {"harness_config": "pi"},
                    "reviewer": {"harness_config": "pi"},
                },
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
            "roles",
            "reviewer",
            "enabled",
            value,
        ]
    )
    output = capsys.readouterr().out
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert "Updated role reviewer: enabled=false" in output
    assert "  ✗  reviewer [pi]" in output
    assert catalog["roles"]["reviewer"]["enabled"] is False


def test_roles_command_rejects_disabling_default_role(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump({"state_dir": str(tmp_path / "state"), "log_dir": str(tmp_path / "logs"), "default_timeout": 600}),
        encoding="utf-8",
    )
    prompts_path.write_text("{}\n", encoding="utf-8")
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "builder",
                "harness_configs": {
                    "pi": {"harness": "pi", "command": ["pi", "-p", "{prompt}"]},
                },
                "roles": {"builder": {"harness_config": "pi"}},
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
            "roles",
            "builder",
            "enabled",
            "off",
        ]
    )
    output = capsys.readouterr().out
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert "error: cannot disable default role: builder" in output
    assert "enabled" not in catalog["roles"]["builder"]


def test_roles_command_updates_role_routing_settings(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "state_dir": str(tmp_path / "state"),
                "log_dir": str(tmp_path / "logs"),
                "default_timeout": 600,
            }
        ),
        encoding="utf-8",
    )
    prompts_path.write_text("{}\n", encoding="utf-8")
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "worker",
                "harness_configs": {
                    "pi": {"harness": "pi", "command": ["pi", "-p", "{prompt}"]},
                    "hermes": {"harness": "hermes", "command": ["hermes", "-z", "{prompt}"]},
                },
                "roles": {"worker": {"harness_config": "pi", "model": "old-model"}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    from orchestra.cli import main

    updates = [
        ("harness", "hermes", "harness_config", "hermes"),
        ("model", "new/model", "model", "new/model"),
        ("profile", "tori", "profile", "tori"),
        ("agent", "plan", "agent", "plan"),
    ]
    for setting, value, yaml_key, expected_value in updates:
        exit_code = main(
            [
                "--config",
                str(config_path),
                "--agent-catalog",
                str(catalog_path),
                "roles",
                "worker",
                setting,
                value,
            ]
        )
        output = capsys.readouterr().out

        assert exit_code == 0
        assert f"Updated role worker: {yaml_key}={expected_value}" in output

    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    assert catalog["roles"]["worker"]["harness_config"] == "hermes"
    assert catalog["roles"]["worker"]["model"] == "new/model"
    assert catalog["roles"]["worker"]["profile"] == "tori"
    assert catalog["roles"]["worker"]["agent"] == "plan"


def test_roles_command_rejects_invalid_role_mutations(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump({"state_dir": str(tmp_path / "state"), "log_dir": str(tmp_path / "logs"), "default_timeout": 600}),
        encoding="utf-8",
    )
    prompts_path.write_text("{}\n", encoding="utf-8")
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "builder",
                "harness_configs": {
                    "pi": {"harness": "pi", "command": ["pi", "-p", "{prompt}"]},
                },
                "roles": {
                    "builder": {"harness_config": "pi"},
                    "reviewer": {"harness_config": "pi", "model": "old-model"},
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    from orchestra.cli import main

    cases = [
        (["missing", "enabled", "true"], "error: unknown role: missing"),
        (
            ["reviewer", "enabled", "maybe"],
            "error: enabled must be one of true/yes/y/1/on or false/no/n/0/off; got 'maybe'",
        ),
        (
            ["reviewer", "enabled", "2"],
            "error: enabled must be one of true/yes/y/1/on or false/no/n/0/off; got '2'",
        ),
        (["reviewer", "model", ""], "error: model must be a non-empty string"),
        (["reviewer", "harness", "missing"], "error: unknown harness config: missing"),
        (["reviewer", "harness", ""], "error: harness must be a non-empty string"),
        (["reviewer", "enabled"], "error: missing value for role setting"),
    ]
    incomplete_usage_output = ""
    for role_args, expected_error in cases:
        exit_code = main(
            [
                "--config",
                str(config_path),
                "--agent-catalog",
                str(catalog_path),
                "roles",
                *role_args,
            ]
        )
        output = capsys.readouterr().out

        assert exit_code == 1
        assert expected_error in output
        if role_args == ["reviewer", "enabled"]:
            incomplete_usage_output = output

    assert "/orch roles ROLE SETTING VALUE" in incomplete_usage_output
    assert "harness   selected harness config name" in incomplete_usage_output
    assert "profile   optional harness profile, when supported" in incomplete_usage_output

    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    assert catalog["roles"]["reviewer"]["model"] == "old-model"
    assert "enabled" not in catalog["roles"]["reviewer"]


def test_role_metadata_lists_unused_harness_configs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "state_dir": str(tmp_path / "state"),
                "log_dir": str(tmp_path / "logs"),
                "default_timeout": 600,
            }
        ),
        encoding="utf-8",
    )
    prompts_path.write_text("{}\n", encoding="utf-8")
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "worker",
                "harness_configs": {
                    "pi": {"harness": "pi", "command": ["pi", "-p", "{prompt}"]},
                    "unused": {"harness": "hermes", "command": ["hermes", "-z", "{prompt}"]},
                },
                "roles": {"worker": {"harness_config": "pi"}},
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
            "_role-metadata",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload == {"roles": ["worker"], "harnessConfigs": ["pi", "unused"]}


def test_host_help_and_tool_info_reflect_current_enabled_and_default_roles(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump({"state_dir": str(tmp_path / "state"), "log_dir": str(tmp_path / "logs"), "default_timeout": 600}),
        encoding="utf-8",
    )
    prompts_path.write_text("{}\n", encoding="utf-8")
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "reviewer",
                "harness_configs": {
                    "pi": {"harness": "pi", "command": ["pi", "-p", "{prompt}"]},
                    "hermes": {"harness": "hermes", "command": ["hermes", "-z", "{prompt}"]},
                },
                "roles": {
                    "worker": {"harness_config": "pi"},
                    "reviewer": {"harness_config": "hermes", "model": "gpt-5"},
                    "critic": {"harness_config": "hermes", "enabled": False},
                },
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
    assert (
        "/orch on                           Load the orchestra orchestrator skill"
        in help_output
    )
    assert "/orch roles" in help_output
    assert "/orch roles ROLE SETTING VALUE" in help_output
    assert "Settings: harness, enabled, model, profile, agent" in help_output
    assert "VALUE for enabled: true, yes, y, 1, on | false, no, n, 0, off" in help_output
    assert "harness-config" not in help_output
    assert "Configured roles" in help_output
    assert "Default: reviewer" in help_output
    assert "  ✓  worker [pi]" in help_output
    assert "  D  reviewer [hermes]" in help_output
    assert "      model: gpt-5" in help_output
    assert "  ✗  critic" not in help_output
    assert "  ✓  worker [pi]" in tool_info["description"]
    assert "  D  reviewer [hermes]" in tool_info["description"]
    assert "      model: gpt-5" in tool_info["description"]
    assert tool_info["roleDescription"].startswith("(Optional) specific role; omit for default.")
    assert "  ✓  worker [pi]" in tool_info["roleDescription"]
    assert "  D  reviewer [hermes]" in tool_info["roleDescription"]
    assert "  ✗  critic" not in tool_info["description"]
    assert "  ✗  critic" not in tool_info["roleDescription"]
    assert "timeoutDescription" not in tool_info


def test_disabled_role_is_rejected_without_fallback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump({"state_dir": str(tmp_path / "state"), "log_dir": str(tmp_path / "logs"), "default_timeout": 600}),
        encoding="utf-8",
    )
    prompts_path.write_text("{}\n", encoding="utf-8")
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "worker",
                "harness_configs": {
                    "pi": {"harness": "pi", "command": ["pi", "-p", "{prompt}"]},
                    "hermes": {"harness": "hermes", "command": ["hermes", "-z", "{prompt}"]},
                },
                "roles": {
                    "worker": {"harness_config": "pi"},
                    "critic": {
                        "harness_config": "hermes",
                        "enabled": False,
                        "harness_fallback": [{"harness_config": "pi"}],
                    },
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


def test_requested_role_startup_fallback_preserves_requested_role_runtime_behavior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    python_executable: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    skill_dir = tmp_path / "skills" / "reviewer"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text("# Reviewer Skill\n\nInspect only.", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {"state_dir": str(tmp_path / "state"), "log_dir": str(tmp_path / "logs"), "default_timeout": 600},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    prompts_path.write_text("{}\n", encoding="utf-8")
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "builder",
                "harness_configs": {
                    "pi": {
                        "harness": "pi",
                        "command": [
                            python_executable,
                            "-c",
                            (
                                "import json, os, sys; "
                                "print(json.dumps({"
                                "'argv': sys.argv[1:-1], "
                                "'prompt': sys.argv[-1], "
                                "'worker_budget': os.environ.get('ORCHESTRA_DISPATCH_BUDGET'), "
                                "'role_env': os.environ.get('ROLE_ENV_TEST')"
                                "}))"
                            ),
                            "--model",
                            "{model}",
                            "{prompt}",
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
                        "model": "builder-model",
                    },
                    "reviewer": {
                        "harness_config": "hermes",
                        "harness_fallback": [{"harness_config": "pi", "model": "fallback-model"}],
                        "model": "requested-model",
                        "prompt_addition": "Review only.",
                        "skills": ["reviewer"],
                        "worker_budget": 2,
                        "env": {"ROLE_ENV_TEST": "configured"},
                    },
                },
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
            "manual:fallback-requested-role",
            "--role",
            "reviewer",
            "--goal",
            "Run the requested role with fallback.",
        ]
    )
    do_output = capsys.readouterr().out

    assert exit_code == 0
    run_id = extract_run_id(do_output)
    store = StateStore(tmp_path / "state" / "orchestra.db")
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_DONE, timeout=5)

    record = store.get_run(run_id)
    note = "fallback: reviewer used harness_config pi after hermes failed to start"
    assert record.role == "reviewer"
    assert record.harness == "pi"
    assert record.result_summary is not None
    assert note in record.result_summary
    assert not record.blocker_text
    assert record.result_artifact_path is not None

    artifact_text = record.result_artifact_path.read_text(encoding="utf-8")
    payload = json.loads(artifact_text.split("## stdout\n\n", 1)[1].strip())
    assert payload["argv"] == ["--model", "fallback-model"]
    assert payload["worker_budget"] == "2"
    assert payload["role_env"] == "configured"
    assert "Role: reviewer" in payload["prompt"]
    assert "Role skill: reviewer" in payload["prompt"]
    assert f"Skill directory: {skill_dir}" in payload["prompt"]
    assert "Resolve relative resource paths against this directory." in payload["prompt"]
    assert "# Reviewer Skill" in payload["prompt"]
    assert "Role instructions: Review only." in payload["prompt"]

    history_exit = main(
        [
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "history",
            "--session-id",
            "manual:fallback-requested-role",
        ]
    )
    history_output = capsys.readouterr().out

    assert history_exit == 0
    assert note in history_output
    assert "reviewer ::" in history_output


def test_do_without_role_uses_default_role(
    tmp_path: Path,
    python_executable: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {"state_dir": str(tmp_path / "state"), "log_dir": str(tmp_path / "logs"), "default_timeout": 600},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    prompts_path.write_text("{}\n", encoding="utf-8")
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "default_role": "reviewer",
                "harness_configs": {
                    "pi": {
                        "harness": "pi",
                        "command": [python_executable, "-c", "print('default reviewer ran')"],
                    },
                },
                "roles": {
                    "worker": {"harness_config": "pi"},
                    "reviewer": {"harness_config": "pi"},
                },
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
            "manual:default-role",
            "--goal",
            "Use the default role.",
        ]
    )
    do_output = capsys.readouterr().out

    assert exit_code == 0
    run_id = extract_run_id(do_output)
    store = StateStore(tmp_path / "state" / "orchestra.db")
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_DONE, timeout=5)

    record = store.get_run(run_id)
    assert record.role == "reviewer"
    assert record.harness == "pi"
    assert record.result_summary == "default reviewer ran"
