from __future__ import annotations

from pathlib import Path

import pytest

from orchestra.app import init_pi
from orchestra.cli import main


def _write_source_tree(root: Path, extension_text: str = "extension v1") -> None:
    extension = root / "extensions" / "pi" / "orchestra" / "index.ts"
    extension.parent.mkdir(parents=True)
    extension.write_text(extension_text, encoding="utf-8")
    (root / "config.yaml").write_text("state_dir: state\n", encoding="utf-8")
    (root / "prompts.yaml").write_text("{}\n", encoding="utf-8")
    (root / "agent-catalog.yaml").write_text(
        "harness_configs:\n"
        "  pi:\n"
        "    harness: pi\n"
        "    command:\n"
        "      - pi\n"
        "      - -p\n"
        "      - '{prompt}'\n"
        "roles:\n"
        "  worker:\n"
        "    harness_config: pi\n",
        encoding="utf-8",
    )


def test_init_pi_installs_global_extension_and_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    pi_dir = tmp_path / "pi-agent"
    source.mkdir()
    _write_source_tree(source)
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(pi_dir))

    result = init_pi(source_root=source)

    assert [item.action for item in result.files] == ["created", "created", "created", "created"]
    installed_extension = pi_dir / "extensions" / "orchestra" / "index.ts"
    assert installed_extension.read_text(encoding="utf-8") == "extension v1"
    assert (pi_dir / "orchestra" / "config.yaml").exists()
    assert (pi_dir / "orchestra" / "prompts.yaml").exists()
    assert (pi_dir / "orchestra" / "agent-catalog.yaml").exists()
    assert result.verification_command == 'pi --no-approve -p "/orch help"'


def test_init_pi_does_not_overwrite_without_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    pi_dir = tmp_path / "pi-agent"
    source.mkdir()
    _write_source_tree(source, extension_text="extension v2")
    target = pi_dir / "extensions" / "orchestra" / "index.ts"
    target.parent.mkdir(parents=True)
    target.write_text("existing", encoding="utf-8")
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(pi_dir))

    result = init_pi(source_root=source)

    assert result.files[0].action == "exists"
    assert target.read_text(encoding="utf-8") == "existing"


def test_init_pi_force_overwrites(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    pi_dir = tmp_path / "pi-agent"
    source.mkdir()
    _write_source_tree(source, extension_text="extension v3")
    target = pi_dir / "extensions" / "orchestra" / "index.ts"
    target.parent.mkdir(parents=True)
    target.write_text("existing", encoding="utf-8")
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(pi_dir))

    result = init_pi(source_root=source, force=True)

    assert result.files[0].action == "updated"
    assert target.read_text(encoding="utf-8") == "extension v3"


def test_cli_init_pi_uses_current_source_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    pi_dir = tmp_path / "pi-agent"
    source.mkdir()
    _write_source_tree(source)
    monkeypatch.chdir(source)
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(pi_dir))

    exit_code = main(["init", "pi"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "verify: pi --no-approve -p \"/orch help\"" in captured.out
    assert (pi_dir / "extensions" / "orchestra" / "index.ts").exists()
