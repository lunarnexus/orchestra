from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from orchestra.cli import build_parser, main

ROOT_PROMPTS = Path(__file__).resolve().parents[1] / "prompts.yaml"


def test_cli_without_command_shows_help(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "usage:" in captured.out


def test_parser_exposes_mvp_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    parser = build_parser()

    help_text = parser.format_help()

    for command in ("do", "status", "stop", "doctor", "roles", "config", "history"):
        assert command in help_text

    with pytest.raises(SystemExit):
        parser.parse_args(["do", "--help"])
    do_help = capsys.readouterr().out
    assert "local/manual session id" in do_help


def test_roles_parser_exposes_supported_settings_only() -> None:
    parser = build_parser()

    args = parser.parse_args(["roles", "worker", "harness", "pi"])
    assert args.setting == "harness"

    with pytest.raises(SystemExit):
        parser.parse_args(["roles", "worker", "harness-config", "pi"])


def test_public_help_hides_internal_subcommands() -> None:
    parser = build_parser()

    help_text = parser.format_help()

    assert "==SUPPRESS==" not in help_text
    for command in (
        "help-host",
        "_run-supervisor",
        "_pending-report",
        "_await-session-report",
        "_await-run",
        "_mark-session-report-delivered",
        "_release-session-report",
        "_dispatch-ack",
        "_progress-message",
        "_command-echo",
        "_tool-info",
    ):
        assert command not in help_text


def test_internal_command_still_executes(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["_dispatch-ack", "--run-id", "run-123"])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "run-123" in captured.out


def test_config_command_reads_and_updates_values(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    config_path.write_text(
        "default_timeout: 120\nauto_verify: false\nconcurrency:\n  global: 4\n  per_session: 3\n",
        encoding="utf-8",
    )
    prompts_path.write_text(ROOT_PROMPTS.read_text(encoding="utf-8"), encoding="utf-8")

    exit_code = main(["--config", str(config_path), "config"])
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "default_timeout: 120" in output

    exit_code = main(["--config", str(config_path), "config", "auto_verify"])
    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.strip() == "False"

    exit_code = main(["--config", str(config_path), "config", "auto_verify", "true"])
    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.strip() == "True"
    assert "auto_verify: true" in config_path.read_text(encoding="utf-8")


def test_invalid_public_command_does_not_reveal_internal_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["nope"])
    captured = capsys.readouterr()

    assert "_run-supervisor" not in captured.err
    assert "_tool-info" not in captured.err
    assert "help-host" not in captured.err


def test_python_module_help_smoke() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "orchestra", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "usage: orchestra" in result.stdout


@pytest.mark.skipif(
    shutil.which("orchestra") is None,
    reason="installed orchestra command not found",
)
def test_installed_command_help_smoke() -> None:
    result = subprocess.run(
        ["orchestra", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "usage: orchestra" in result.stdout
