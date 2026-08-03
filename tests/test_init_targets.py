from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from orchestra.app import AppError, init_all, init_opencode, init_pi


def completed(
    args: list[str],
    stdout: str = "",
    stderr: str = "",
    code: int = 0,
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=args, returncode=code, stdout=stdout, stderr=stderr)


def _write_source_tree(root: Path, catalog_text: str) -> None:
    extension = root / "extensions" / "pi" / "orchestra" / "index.ts"
    extension.parent.mkdir(parents=True)
    extension.write_text("extension", encoding="utf-8")
    (root / "config.yaml").write_text("state_dir: state\n", encoding="utf-8")
    (root / "prompts.yaml").write_text("{}\n", encoding="utf-8")
    (root / "agent-catalog.yaml").write_text(catalog_text, encoding="utf-8")


def test_init_opencode_reports_no_action_required() -> None:
    result = init_opencode()

    assert result.message == "opencode: no Orchestra host/plugin install action required"


def test_init_all_detects_harnesses_and_deduplicates_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    pi_dir = tmp_path / "pi-agent"
    hermes_home = tmp_path / "hermes-home"
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

    calls: list[list[str]] = []

    def fake_runner(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return completed(args, stdout="installed")

    result = init_all(source_root=source, runner=fake_runner)

    assert result.pi is not None
    assert len(result.hermes) == 2
    assert result.opencode is not None
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
    assert not (pi_dir / "orchestra" / "config.yaml").is_symlink()
