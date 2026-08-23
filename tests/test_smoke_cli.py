from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from orchestra.state import STATUS_DONE, StateStore
from tests.helpers import extract_run_id, run_cli, wait_for_condition

PROMPTS_TEXT = (Path(__file__).resolve().parents[1] / "prompts.yaml").read_text(encoding="utf-8")


def _write_cli_runtime(
    tmp_path: Path,
    *,
    catalog: dict[str, object],
    auto_return: bool = True,
) -> tuple[Path, Path, Path]:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    catalog_path = tmp_path / "agent-catalog.yaml"

    config_path.write_text(
        yaml.safe_dump(
            {
                "state_dir": str(tmp_path / "state"),
                "log_dir": str(tmp_path / "logs"),
                "default_timeout": 30,
                "concurrency": {"global": 4, "per_session": 3},
                "auto_return": auto_return,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    prompts_path.write_text(PROMPTS_TEXT, encoding="utf-8")
    catalog_path.write_text(yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8")
    return config_path, catalog_path, tmp_path / "state" / "orchestra.db"


def test_python_module_do_smoke(tmp_path: Path) -> None:
    config_path, catalog_path, _ = _write_cli_runtime(
        tmp_path,
        catalog={
            "default_role": "worker",
            "roles": {
                "worker": {
                    "harness": "pi",
                    "command": [
                        sys.executable,
                        "-c",
                        "print('smoke ok')",
                    ],
                }
            },
        },
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "orchestra",
            "--config",
            str(config_path),
            "--agent-catalog",
            str(catalog_path),
            "do",
            "--session-id",
            "manual:smoke",
            "--goal",
            "Run a smoke worker.",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "dispatch: queued for supervision" in result.stdout


def test_python_module_do_without_role_uses_builder_default(tmp_path: Path) -> None:
    config_path, catalog_path, db_path = _write_cli_runtime(
        tmp_path,
        catalog={
            "default_role": "builder",
            "harness_configs": {
                "builder": {
                    "harness": "pi",
                    "command": [sys.executable, "-c", "print('builder default ran')"],
                },
                "reviewer": {
                    "harness": "pi",
                    "command": [sys.executable, "-c", "print('reviewer ran')"],
                },
            },
            "roles": {
                "builder": {"harness_config": "builder"},
                "reviewer": {"harness_config": "reviewer"},
            },
        },
    )

    result = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "do",
        "--session-id",
        "manual:builder-default",
        "--goal",
        "Run without an explicit role.",
    )

    assert result.returncode == 0
    assert "role: builder" in result.stdout

    run_id = extract_run_id(result.stdout)
    store = StateStore(db_path)
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_DONE, timeout=5)

    record = store.get_run(run_id)
    assert record.role == "builder"
    assert record.result_summary == "builder default ran"


def test_python_module_requested_role_fallback_is_visible_in_history_and_final_report(
    tmp_path: Path,
) -> None:
    config_path, catalog_path, db_path = _write_cli_runtime(
        tmp_path,
        catalog={
            "default_role": "builder",
            "harness_configs": {
                "pi": {
                    "harness": "pi",
                    "command": [sys.executable, "-c", "print('fallback worker ran')"],
                },
                "hermes": {
                    "harness": "hermes",
                    "command": ["missing-hermes-binary", "-z", "{prompt}"],
                },
            },
            "roles": {
                "builder": {"harness_config": "pi"},
                "reviewer": {
                    "harness_config": "hermes",
                    "harness_fallback": [{"harness_config": "pi"}],
                },
            },
        },
    )
    note = "fallback: reviewer used harness_config pi after hermes failed to start"

    do = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "do",
        "--session-id",
        "manual:fallback-smoke",
        "--role",
        "reviewer",
        "--goal",
        "Run with fallback.",
    )
    assert do.returncode == 0
    assert "role: reviewer" in do.stdout
    run_id = extract_run_id(do.stdout)

    store = StateStore(db_path)
    assert wait_for_condition(lambda: store.get_run(run_id).status == STATUS_DONE, timeout=5)
    record = store.get_run(run_id)
    assert record.role == "reviewer"
    assert record.harness == "pi"
    assert record.result_summary is not None and note in record.result_summary

    history = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "history",
        "--session-id",
        "manual:fallback-smoke",
    )
    assert history.returncode == 0
    assert "reviewer ::" in history.stdout
    assert note in history.stdout

    report = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "_await-session-report",
        "--session-id",
        "manual:fallback-smoke",
        "--run-id",
        run_id,
        "--timeout",
        "5",
    )
    assert report.returncode == 0
    assert f"[orchestra: reviewer {run_id} success]" in report.stdout
    assert note in report.stdout


def test_python_module_rejects_disabled_requested_role_before_fallback(tmp_path: Path) -> None:
    config_path, catalog_path, _ = _write_cli_runtime(
        tmp_path,
        catalog={
            "default_role": "builder",
            "harness_configs": {
                "pi": {
                    "harness": "pi",
                    "command": [sys.executable, "-c", "print('builder ran')"],
                },
                "hermes": {
                    "harness": "hermes",
                    "command": ["missing-hermes-binary", "-z", "{prompt}"],
                },
            },
            "roles": {
                "builder": {"harness_config": "pi"},
                "critic": {
                    "harness_config": "hermes",
                    "enabled": False,
                    "harness_fallback": [{"harness_config": "pi"}],
                },
            },
        },
    )

    result = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "do",
        "--session-id",
        "manual:disabled-role",
        "--role",
        "critic",
        "--goal",
        "Do not run.",
    )

    assert result.returncode == 1
    assert "error: role is disabled: critic" in result.stdout


def test_python_module_roles_enabled_accepts_on_off_and_rejects_maybe(tmp_path: Path) -> None:
    config_path, catalog_path, _ = _write_cli_runtime(
        tmp_path,
        catalog={
            "default_role": "builder",
            "harness_configs": {
                "pi": {
                    "harness": "pi",
                    "command": [sys.executable, "-c", "print('unused')"],
                },
            },
            "roles": {
                "builder": {"harness_config": "pi"},
                "reviewer": {"harness_config": "pi", "enabled": False},
            },
        },
    )

    enable = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "roles",
        "reviewer",
        "enabled",
        "on",
    )
    assert enable.returncode == 0
    assert "Updated role reviewer: enabled=true" in enable.stdout
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    assert catalog["roles"]["reviewer"]["enabled"] is True

    disable = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "roles",
        "reviewer",
        "enabled",
        "off",
    )
    assert disable.returncode == 0
    assert "Updated role reviewer: enabled=false" in disable.stdout
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    assert catalog["roles"]["reviewer"]["enabled"] is False

    invalid = run_cli(
        "--config",
        str(config_path),
        "--agent-catalog",
        str(catalog_path),
        "roles",
        "reviewer",
        "enabled",
        "maybe",
    )
    assert invalid.returncode == 1
    assert (
        "error: enabled must be one of true/yes/y/1/on or false/no/n/0/off; got 'maybe'"
        in invalid.stdout
    )
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    assert catalog["roles"]["reviewer"]["enabled"] is False
