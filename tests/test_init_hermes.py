from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from orchestra.app import AppError, init_hermes
from orchestra.cli import main
from tests.helpers import default_prompts_text


def completed(
    args: list[str],
    stdout: str = "",
    stderr: str = "",
    code: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=args, returncode=code, stdout=stdout, stderr=stderr)


def _write_source_tree(root: Path) -> None:
    extension = root / "extensions" / "pi" / "orchestra" / "index.ts"
    extension.parent.mkdir(parents=True)
    extension.write_text("extension", encoding="utf-8")
    (root / "config.yaml").write_text("state_dir: state\n", encoding="utf-8")
    (root / "prompts.yaml").write_text(default_prompts_text(), encoding="utf-8")
    (root / "agent-catalog.yaml").write_text(
        "harness_configs:\n"
        "  hermes:\n"
        "    harness: hermes\n"
        "    command:\n"
        "      - hermes\n"
        "      - -z\n"
        "      - '{prompt}'\n"
        "roles:\n"
        "  critic:\n"
        "    harness_config: hermes\n",
        encoding="utf-8",
    )


def test_init_hermes_installs_plugin_with_default_profile_and_materializes_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    source = tmp_path / "source"
    hermes_home = tmp_path / "hermes-home"
    source.mkdir()
    _write_source_tree(source)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    def fake_runner(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"args": args, **kwargs})
        return completed(args, stdout="installed")

    result = init_hermes(source_root=source, runner=fake_runner)

    assert calls == [
        {
            "args": [
                "hermes",
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
    assert result.verification_command == "hermes plugins list"
    assert (hermes_home / "orchestra" / "config.yaml").is_symlink()
    assert (hermes_home / "orchestra" / "prompts.yaml").is_symlink()
    assert (hermes_home / "orchestra" / "agent-catalog.yaml").is_symlink()


def test_init_hermes_explicit_profile_override_still_works(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    source = tmp_path / "source"
    hermes_home = tmp_path / "hermes-home"
    source.mkdir()
    _write_source_tree(source)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    def fake_runner(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return completed(args)

    result = init_hermes(profile="tori", source_root=source, runner=fake_runner)

    assert calls == [
        [
            "hermes",
            "-p",
            "tori",
            "plugins",
            "install",
            "lunarnexus/orchestra/extensions/hermes/orchestra",
            "--enable",
        ]
    ]
    assert result.verification_command == "hermes -p tori plugins list"
    assert (hermes_home / "profiles" / "tori" / "orchestra" / "config.yaml").is_symlink()


def test_init_hermes_passes_force_to_official_installer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    source = tmp_path / "source"
    hermes_home = tmp_path / "hermes-home"
    source.mkdir()
    _write_source_tree(source)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    def fake_runner(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return completed(args)

    init_hermes(profile="tori", force=True, source_root=source, runner=fake_runner)

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


def test_init_hermes_reports_installer_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    hermes_home = tmp_path / "hermes-home"
    source.mkdir()
    _write_source_tree(source)
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    def fake_runner(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return completed(args, stderr="clone failed", code=1)

    with pytest.raises(AppError, match="Hermes plugin install failed: clone failed"):
        init_hermes(source_root=source, runner=fake_runner)


def test_cli_init_hermes_allows_default_profile(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from orchestra import cli
    from orchestra.app import InitHermesResult

    def fake_init_hermes(
        *,
        profile: str | None = None,
        force: bool = False,
        copy: bool = False,
    ) -> InitHermesResult:
        assert profile is None
        assert force is False
        assert copy is False
        return InitHermesResult(
            files=[],
            command=["hermes", "plugins", "install", "source", "--enable"],
            stdout="enabled",
            stderr="",
            verification_command="hermes plugins list",
        )

    monkeypatch.setattr(cli, "init_hermes", fake_init_hermes)

    exit_code = main(["init", "hermes"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "installed: hermes plugins install source --enable" in captured.out
    assert "verify: hermes plugins list" in captured.out


def test_cli_init_hermes_prints_verify_command(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from orchestra import cli
    from orchestra.app import InitHermesResult

    def fake_init_hermes(
        *,
        profile: str | None = None,
        force: bool = False,
        copy: bool = False,
    ) -> InitHermesResult:
        assert profile == "tori"
        assert force is True
        assert copy is False
        return InitHermesResult(
            files=[],
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


def test_real_hermes_plugin_integration_skips_without_isolated_runtime_credentials(
    tmp_path: Path,
) -> None:
    hermes = shutil.which("hermes")
    if hermes is None:
        pytest.skip("hermes command not found")

    plugin_help = subprocess.run(
        [hermes, "plugins", "list", "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if plugin_help.returncode != 0:
        pytest.skip("hermes plugins list help unavailable")

    hermes_home = tmp_path / "hermes-home"
    plugins_dir = hermes_home / "plugins"
    plugins_dir.mkdir(parents=True)
    os.symlink(Path("extensions/hermes/orchestra").resolve(), plugins_dir / "orchestra")
    (hermes_home / "config.yaml").write_text(
        "plugins:\n  enabled:\n    - orchestra\n",
        encoding="utf-8",
    )

    env = {**os.environ, "HERMES_HOME": str(hermes_home), "HOME": str(hermes_home)}
    plugins_list = subprocess.run(
        [hermes, "plugins", "list", "--json"],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )
    assert plugins_list.returncode == 0
    plugins = json.loads(plugins_list.stdout)
    assert any(
        item.get("name") == "orchestra" and item.get("status") == "enabled"
        for item in plugins
        if isinstance(item, dict)
    )

    oneshot = subprocess.run(
        [hermes, "--ignore-user-config", "--ignore-rules", "-z", "/orch help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
    )
    if "No inference provider configured" in (oneshot.stderr or ""):
        pytest.skip(
            "real Hermes plugin automation requires a configured inference provider even for "
            "isolated one-shot /orch help; test stays manual to avoid depending on user "
            "credentials"
        )
    pytest.skip(
        "real Hermes plugin automation requires an interactive/runtime-capable Hermes session; "
        "run manual sequence in SMOKETEST.md"
    )
