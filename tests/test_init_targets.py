from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from orchestra.app import AppError, init_all, init_opencode, init_pi
from orchestra.cli import main


def completed(
    args: list[str],
    stdout: str = "",
    stderr: str = "",
    code: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=args, returncode=code, stdout=stdout, stderr=stderr)


def _write_source_tree(root: Path, catalog_text: str) -> None:
    pi_extension = root / "extensions" / "pi" / "orchestra" / "index.ts"
    pi_extension.parent.mkdir(parents=True)
    pi_extension.write_text("extension", encoding="utf-8")
    opencode_extension = root / "extensions" / "opencode" / "orchestra" / "index.ts"
    opencode_extension.parent.mkdir(parents=True)
    opencode_extension.write_text("opencode extension", encoding="utf-8")
    (root / "config.yaml").write_text("state_dir: state\n", encoding="utf-8")
    (root / "prompts.yaml").write_text("{}\n", encoding="utf-8")
    (root / "agent-catalog.yaml").write_text(catalog_text, encoding="utf-8")


def test_init_opencode_installs_global_plugin_from_source_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    opencode_config = tmp_path / "opencode-config"
    source.mkdir()
    _write_source_tree(
        source,
        """
default_role: builder
harness_configs:
  opencode:
    harness: opencode
    command: ["opencode", "run", "{prompt}"]
roles:
  builder:
    harness_config: opencode
""".lstrip(),
    )
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(opencode_config))

    result = init_opencode(source_root=source, copy=True)

    assert [item.action for item in result.files] == ["created"]
    assert [item.mode for item in result.files] == ["copy"]
    installed_extension = opencode_config / "plugins" / "orchestra" / "index.ts"
    assert installed_extension.read_text(encoding="utf-8") == "opencode extension"
    assert result.verification_command == "opencode --help"


def test_init_opencode_does_not_overwrite_without_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    opencode_config = tmp_path / "opencode-config"
    source.mkdir()
    _write_source_tree(
        source,
        """
default_role: builder
harness_configs:
  opencode:
    harness: opencode
    command: ["opencode", "run", "{prompt}"]
roles:
  builder:
    harness_config: opencode
""".lstrip(),
    )
    installed_extension = opencode_config / "plugins" / "orchestra" / "index.ts"
    installed_extension.parent.mkdir(parents=True)
    installed_extension.write_text("existing", encoding="utf-8")
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(opencode_config))

    result = init_opencode(source_root=source)

    assert result.files[0].action == "exists"
    assert installed_extension.read_text(encoding="utf-8") == "existing"


def test_init_opencode_force_overwrites(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    opencode_config = tmp_path / "opencode-config"
    source.mkdir()
    _write_source_tree(
        source,
        """
default_role: builder
harness_configs:
  opencode:
    harness: opencode
    command: ["opencode", "run", "{prompt}"]
roles:
  builder:
    harness_config: opencode
""".lstrip(),
    )
    installed_extension = opencode_config / "plugins" / "orchestra" / "index.ts"
    installed_extension.parent.mkdir(parents=True)
    installed_extension.write_text("existing", encoding="utf-8")
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(opencode_config))

    result = init_opencode(source_root=source, force=True, copy=True)

    assert result.files[0].action == "updated"
    assert installed_extension.read_text(encoding="utf-8") == "opencode extension"


def test_cli_init_opencode_uses_current_source_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    opencode_config = tmp_path / "opencode-config"
    source.mkdir()
    _write_source_tree(
        source,
        """
default_role: builder
harness_configs:
  opencode:
    harness: opencode
    command: ["opencode", "run", "{prompt}"]
roles:
  builder:
    harness_config: opencode
""".lstrip(),
    )
    monkeypatch.chdir(source)
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(opencode_config))

    exit_code = main(["init", "opencode"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "created:copy:" in captured.out
    assert "verify: opencode --help" in captured.out
    assert (opencode_config / "plugins" / "orchestra" / "index.ts").exists()


def test_init_all_detects_harnesses_and_deduplicates_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    pi_dir = tmp_path / "pi-agent"
    hermes_home = tmp_path / "hermes-home"
    opencode_config = tmp_path / "opencode-config"
    source.mkdir()
    _write_source_tree(
        source,
        """
default_role: builder
harness_configs:
  pi:
    harness: pi
    command: ["pi", "-p", "{prompt}"]
  hermes:
    harness: hermes
    command: ["hermes", "-z", "{prompt}"]
  opencode:
    harness: opencode
    command: ["opencode", "run", "{prompt}"]
roles:
  builder:
    harness_config: pi
  critic:
    harness_config: hermes
  reviewer:
    harness_config: hermes
    profile: tori
  appsec:
    harness_config: opencode
""".lstrip(),
    )
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(pi_dir))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(opencode_config))

    calls: list[list[str]] = []

    def fake_runner(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return completed(args, stdout="installed")

    result = init_all(source_root=source, runner=fake_runner)

    assert result.pi is not None
    assert len(result.hermes) == 2
    assert result.opencode is not None
    assert [item.action for item in result.opencode.files] == ["created"]
    assert result.opencode.files[0].target == opencode_config / "plugins" / "orchestra" / "index.ts"
    assert calls == [
        [
            "hermes",
            "plugins",
            "install",
            "lunarnexus/orchestra/extensions/hermes/orchestra",
            "--enable",
        ],
        [
            "hermes",
            "-p",
            "tori",
            "plugins",
            "install",
            "lunarnexus/orchestra/extensions/hermes/orchestra",
            "--enable",
        ],
    ]
    assert (pi_dir / "extensions" / "orchestra" / "index.ts").exists()
    assert (pi_dir / "orchestra" / "config.yaml").is_symlink()
    assert (hermes_home / "orchestra" / "config.yaml").is_symlink()
    assert (hermes_home / "profiles" / "tori" / "orchestra" / "config.yaml").is_symlink()


def test_init_pi_requires_copy_when_no_source_root_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pi_dir = tmp_path / "pi-agent"
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(pi_dir))
    from orchestra import app

    monkeypatch.setattr(app, "_find_source_root", lambda source_root=None: None)

    with pytest.raises(AppError, match="rerun with --copy"):
        init_pi()


def test_init_pi_copy_mode_uses_packaged_fallback_when_no_source_root_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pi_dir = tmp_path / "pi-agent"
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(pi_dir))
    from orchestra import app

    monkeypatch.setattr(app, "_find_source_root", lambda source_root=None: None)

    result = init_pi(copy=True)

    assert [item.mode for item in result.files] == ["copy", "copy", "copy", "copy"]
    assert (pi_dir / "extensions" / "orchestra" / "index.ts").is_file()
    assert (pi_dir / "orchestra" / "config.yaml").is_file()
    assert result.verification_command == 'pi --no-approve -p "/orch doctor"'
    assert not (pi_dir / "orchestra" / "config.yaml").is_symlink()
