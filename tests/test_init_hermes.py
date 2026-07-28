from __future__ import annotations

import subprocess
from typing import Any

import pytest

from orchestra.app import AppError, init_hermes
from orchestra.cli import main


def completed(
    args: list[str],
    stdout: str = "",
    stderr: str = "",
    code: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=args, returncode=code, stdout=stdout, stderr=stderr)


def test_init_hermes_installs_plugin_with_profile_and_enable() -> None:
    calls: list[dict[str, Any]] = []

    def fake_runner(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"args": args, **kwargs})
        return completed(args, stdout="installed")

    result = init_hermes(profile="tori", runner=fake_runner)

    assert calls == [
        {
            "args": [
                "hermes",
                "-p",
                "tori",
                "plugins",
                "install",
                "lunarnexus/orchestra/extensions/hermes/orchestra",
                "--enable",
            ],
            "check": False,
            "capture_output": True,
            "text": True,
            "timeout": 120,
        }
    ]
    assert result.stdout == "installed"
    assert result.stderr == ""
    assert result.verification_command == "hermes -p tori plugins list"


def test_init_hermes_passes_force_to_official_installer() -> None:
    calls: list[list[str]] = []

    def fake_runner(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return completed(args)

    init_hermes(profile="tori", force=True, runner=fake_runner)

    assert calls == [
        [
            "hermes",
            "-p",
            "tori",
            "plugins",
            "install",
            "lunarnexus/orchestra/extensions/hermes/orchestra",
            "--enable",
            "--force",
        ]
    ]


def test_init_hermes_requires_profile() -> None:
    with pytest.raises(AppError, match="Hermes profile is required"):
        init_hermes(profile="   ")


def test_init_hermes_reports_installer_failure() -> None:
    def fake_runner(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return completed(args, stderr="clone failed", code=1)

    with pytest.raises(AppError, match="Hermes plugin install failed: clone failed"):
        init_hermes(profile="tori", runner=fake_runner)


def test_cli_init_hermes_requires_profile(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["init", "hermes"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "--profile" in captured.err


def test_cli_init_hermes_prints_verify_command(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from orchestra import cli
    from orchestra.app import InitHermesResult

    def fake_init_hermes(*, profile: str, force: bool = False) -> InitHermesResult:
        assert profile == "tori"
        assert force is True
        return InitHermesResult(
            command=[
                "hermes",
                "-p",
                profile,
                "plugins",
                "install",
                "source",
                "--enable",
                "--force",
            ],
            stdout="enabled",
            stderr="",
            verification_command="hermes -p tori plugins list",
        )

    monkeypatch.setattr(cli, "init_hermes", fake_init_hermes)

    exit_code = main(["init", "hermes", "--profile", "tori", "--force"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "installed: hermes -p tori plugins install source --enable --force" in captured.out
    assert "enabled" in captured.out
    assert "verify: hermes -p tori plugins list" in captured.out
