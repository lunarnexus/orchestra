from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import orchestra.init as init_module
from orchestra.cli import main
from orchestra.context import AppError
from orchestra.init import init_all, init_codex, init_opencode, init_pi

OPENCODE_COMMAND_TEMPLATE = """# /orch
Args: `$ARGUMENTS`

Call exactly one Orchestra tool for this command, then return the tool output to the user:
- `on` -> `orch_status({ action: "on" })`
- `status` -> `orch_status({ action: "status" })`
- `history [limit]` -> `orch_status({ action: "history", limit })`
- `help` -> `orch_status({ action: "help" })`
- `doctor` -> `orch_status({ action: "doctor" })`
- `roles` -> `orch_status({ action: "roles" })`
- `roles ROLE SETTING VALUE` -> `orch_status({ action: "roles", role, setting, value })`
- `do [--role ROLE] ...` -> `orch_dispatch({ goal, role?, taskLabel? })`

Use only fields shown for the selected action. Never invent a session id.
Supported role settings: `harness`, `enabled`, `model`, `profile`, `agent`.
""".lstrip()


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
    opencode_command = root / "extensions" / "opencode" / "orchestra" / "commands" / "orch.md"
    opencode_command.parent.mkdir(parents=True)
    opencode_command.write_text(OPENCODE_COMMAND_TEMPLATE, encoding="utf-8")
    hermes_plugin = root / "extensions" / "hermes" / "orchestra" / "plugin.yaml"
    hermes_plugin.parent.mkdir(parents=True)
    hermes_plugin.write_text("name: orchestra\n", encoding="utf-8")
    (hermes_plugin.parent / "__init__.py").write_text("", encoding="utf-8")
    codex_manifest = root / "extensions" / "codex" / "orchestra" / ".codex-plugin" / "plugin.json"
    codex_manifest.parent.mkdir(parents=True)
    codex_manifest.write_text(
        json.dumps(
            {
                "name": "orchestra",
                "version": "0.1.0",
                "description": "test",
                "author": {"name": "test"},
                "skills": "./skills/",
                "interface": {
                    "displayName": "Orchestra",
                    "shortDescription": "test",
                    "longDescription": "test",
                    "developerName": "test",
                    "category": "Developer Tools",
                    "capabilities": ["Skills"],
                },
            }
        ),
        encoding="utf-8",
    )
    codex_skill = root / "extensions" / "codex" / "orchestra" / "skills" / "orchestra" / "SKILL.md"
    codex_skill.parent.mkdir(parents=True)
    codex_skill.write_text("---\nname: orchestra\n---\n# Orchestra\n", encoding="utf-8")
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

    assert [item.action for item in result.files] == ["created", "created"]
    assert [item.mode for item in result.files] == ["copy", "copy"]
    installed_extension = opencode_config / "plugins" / "orchestra.ts"
    installed_command = opencode_config / "commands" / "orch.md"
    assert installed_extension.read_text(encoding="utf-8") == "opencode extension"
    assert installed_command.read_text(encoding="utf-8") == OPENCODE_COMMAND_TEMPLATE
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
    installed_extension = opencode_config / "plugins" / "orchestra.ts"
    installed_command = opencode_config / "commands" / "orch.md"
    installed_extension.parent.mkdir(parents=True)
    installed_extension.write_text("existing", encoding="utf-8")
    installed_command.parent.mkdir(parents=True)
    installed_command.write_text("existing command", encoding="utf-8")
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(opencode_config))

    result = init_opencode(source_root=source)

    assert [item.action for item in result.files] == ["exists", "exists"]
    assert installed_extension.read_text(encoding="utf-8") == "existing"
    assert installed_command.read_text(encoding="utf-8") == "existing command"


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
    installed_extension = opencode_config / "plugins" / "orchestra.ts"
    installed_command = opencode_config / "commands" / "orch.md"
    installed_extension.parent.mkdir(parents=True)
    installed_extension.write_text("existing", encoding="utf-8")
    installed_command.parent.mkdir(parents=True)
    installed_command.write_text("existing command", encoding="utf-8")
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(opencode_config))

    result = init_opencode(source_root=source, force=True, copy=True)

    assert [item.action for item in result.files] == ["updated", "updated"]
    assert installed_extension.read_text(encoding="utf-8") == "opencode extension"
    assert installed_command.read_text(encoding="utf-8") == OPENCODE_COMMAND_TEMPLATE


def test_init_opencode_copy_mode_requires_canonical_source_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opencode_config = tmp_path / "opencode-config"
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(opencode_config))

    monkeypatch.setattr(init_module, "_find_source_root", lambda source_root=None: None)

    with pytest.raises(AppError, match="canonical opencode source root not found"):
        init_opencode(copy=True)


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
    assert captured.out.count("created:copy:") == 2
    assert "verify: opencode --help" in captured.out
    assert (opencode_config / "plugins" / "orchestra.ts").exists()
    assert (opencode_config / "commands" / "orch.md").exists()


def test_init_codex_installs_personal_plugin_from_source_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    home = tmp_path / "home"
    source.mkdir()
    _write_source_tree(
        source,
        """
default_role: builder
harness_configs:
  pi:
    harness: pi
    command: ["pi", "-p", "{prompt}"]
roles:
  builder:
    harness_config: pi
""".lstrip(),
    )
    monkeypatch.setenv("HOME", str(home))
    calls: list[list[str]] = []

    def fake_runner(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return completed(args, stdout="installed")

    result = init_codex(source_root=source, runner=fake_runner)

    plugin_dir = home / "plugins" / "orchestra"
    marketplace = home / ".agents" / "plugins" / "marketplace.json"
    assert [item.action for item in result.files] == ["created"]
    assert [item.mode for item in result.files] == ["link"]
    assert plugin_dir.is_symlink()
    assert plugin_dir.resolve() == source / "extensions" / "codex" / "orchestra"
    assert result.marketplace.action == "created"
    assert result.marketplace.mode == "json"
    payload = json.loads(marketplace.read_text(encoding="utf-8"))
    assert payload["name"] == "personal"
    assert payload["interface"]["displayName"] == "Personal"
    assert payload["plugins"] == [
        {
            "name": "orchestra",
            "source": {"source": "local", "path": "./plugins/orchestra"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Developer Tools",
        }
    ]
    assert calls == [["codex", "plugin", "add", "orchestra@personal"]]
    assert result.command == ["codex", "plugin", "add", "orchestra@personal"]
    assert result.stdout == "installed"
    assert result.stderr == ""
    assert result.verification_command == "codex plugin add orchestra@personal"


def test_init_codex_does_not_overwrite_without_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    home = tmp_path / "home"
    source.mkdir()
    _write_source_tree(
        source,
        """
default_role: builder
harness_configs:
  pi:
    harness: pi
    command: ["pi", "-p", "{prompt}"]
roles:
  builder:
    harness_config: pi
""".lstrip(),
    )
    plugin_dir = home / "plugins" / "orchestra"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "existing.txt").write_text("existing", encoding="utf-8")
    marketplace = home / ".agents" / "plugins" / "marketplace.json"
    marketplace.parent.mkdir(parents=True)
    marketplace.write_text(
        json.dumps(
            {
                "name": "personal",
                "interface": {"displayName": "Mine"},
                "plugins": [
                    {
                        "name": "orchestra",
                        "source": {"source": "local", "path": "./plugins/orchestra"},
                        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                        "category": "Developer Tools",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    calls: list[list[str]] = []

    def fake_runner(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return completed(args, stdout="installed")

    result = init_codex(source_root=source, runner=fake_runner)

    assert [item.action for item in result.files] == ["exists"]
    assert result.marketplace.action == "exists"
    assert (plugin_dir / "existing.txt").read_text(encoding="utf-8") == "existing"
    assert json.loads(marketplace.read_text(encoding="utf-8"))["interface"]["displayName"] == "Mine"
    assert calls == [["codex", "plugin", "add", "orchestra@personal"]]


def test_init_codex_force_overwrites_plugin_and_marketplace_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    home = tmp_path / "home"
    source.mkdir()
    _write_source_tree(
        source,
        """
default_role: builder
harness_configs:
  pi:
    harness: pi
    command: ["pi", "-p", "{prompt}"]
roles:
  builder:
    harness_config: pi
""".lstrip(),
    )
    plugin_dir = home / "plugins" / "orchestra"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "existing.txt").write_text("existing", encoding="utf-8")
    marketplace = home / ".agents" / "plugins" / "marketplace.json"
    marketplace.parent.mkdir(parents=True)
    marketplace.write_text(
        json.dumps(
            {
                "name": "personal",
                "interface": {"displayName": "Mine"},
                "plugins": [
                    {
                        "name": "orchestra",
                        "source": {"source": "local", "path": "./wrong"},
                        "policy": {"installation": "NOT_AVAILABLE", "authentication": "ON_USE"},
                        "category": "Other",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    calls: list[list[str]] = []

    def fake_runner(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return completed(args, stdout="installed")

    result = init_codex(source_root=source, force=True, copy=True, runner=fake_runner)

    assert [item.action for item in result.files] == ["updated"]
    assert [item.mode for item in result.files] == ["copy"]
    assert not plugin_dir.is_symlink()
    assert (plugin_dir / ".codex-plugin" / "plugin.json").exists()
    assert not (plugin_dir / "existing.txt").exists()
    assert result.marketplace.action == "updated"
    payload = json.loads(marketplace.read_text(encoding="utf-8"))
    assert payload["interface"]["displayName"] == "Mine"
    assert payload["plugins"][0]["source"]["path"] == "./plugins/orchestra"
    assert payload["plugins"][0]["policy"]["installation"] == "AVAILABLE"
    assert calls == [["codex", "plugin", "add", "orchestra@personal"]]


def test_cli_init_codex_uses_current_source_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    home = tmp_path / "home"
    source.mkdir()
    _write_source_tree(
        source,
        """
default_role: builder
harness_configs:
  pi:
    harness: pi
    command: ["pi", "-p", "{prompt}"]
roles:
  builder:
    harness_config: pi
""".lstrip(),
    )
    monkeypatch.chdir(source)
    monkeypatch.setenv("HOME", str(home))
    calls: list[list[str]] = []

    def fake_init_codex(
        *,
        force: bool = False,
        copy: bool = False,
    ) -> Any:
        calls.append(["force", str(force), "copy", str(copy)])
        return init_codex(
            force=force,
            copy=copy,
            runner=lambda args, **_kwargs: completed(args, stdout="installed"),
        )

    monkeypatch.setattr("orchestra.cli.init_codex", fake_init_codex)

    exit_code = main(["init", "codex"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "created:link:" in captured.out
    assert "created:json:" in captured.out
    assert "installed: codex plugin add orchestra@personal" in captured.out
    assert "installed\n" in captured.out
    assert calls == [["force", "False", "copy", "False"]]
    assert (home / "plugins" / "orchestra").is_symlink()
    assert (home / ".agents" / "plugins" / "marketplace.json").exists()


def test_init_codex_copy_mode_requires_canonical_source_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))

    monkeypatch.setattr(init_module, "_find_source_root", lambda source_root=None: None)
    calls: list[list[str]] = []

    def fake_runner(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return completed(args, stdout="installed")

    with pytest.raises(AppError, match="canonical codex source root not found"):
        init_codex(copy=True, runner=fake_runner)
    assert calls == []


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
    assert [item.action for item in result.opencode.files] == ["created", "created"]
    assert result.opencode.files[0].target == opencode_config / "plugins" / "orchestra.ts"
    assert result.opencode.files[1].target == opencode_config / "commands" / "orch.md"
    assert calls == [
        [
            "hermes",
            "plugins",
            "enable",
            "orchestra",
        ],
        [
            "hermes",
            "-p",
            "tori",
            "plugins",
            "enable",
            "orchestra",
        ],
    ]
    assert (pi_dir / "extensions" / "orchestra" / "index.ts").exists()
    assert (pi_dir / "orchestra" / "config.yaml").is_symlink()
    assert (hermes_home / "orchestra" / "config.yaml").is_symlink()
    assert (hermes_home / "profiles" / "tori" / "orchestra" / "config.yaml").is_symlink()


def test_init_pi_requires_canonical_source_root_when_no_source_root_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pi_dir = tmp_path / "pi-agent"
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(pi_dir))

    monkeypatch.setattr(init_module, "_find_source_root", lambda source_root=None: None)

    with pytest.raises(AppError, match="init source root not found"):
        init_pi()


def test_init_pi_copy_mode_requires_canonical_source_root_when_no_source_root_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pi_dir = tmp_path / "pi-agent"
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(pi_dir))

    monkeypatch.setattr(init_module, "_find_source_root", lambda source_root=None: None)

    with pytest.raises(AppError, match="init source root not found"):
        init_pi(copy=True)
