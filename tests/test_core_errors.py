"""Core owns its operational error contracts and help discoverability."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from orchestra import cli

REPO_ROOT = Path(__file__).resolve().parents[1]


def _config_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "config"
    directory.mkdir()
    shutil.copy(REPO_ROOT / "prompts.yaml", directory / "prompts.yaml")
    (directory / "config.yaml").write_text(
        f"state_dir: {tmp_path / 'state'}\n"
        f"log_dir: {tmp_path / 'logs'}\n"
        "default_timeout: 300\n"
        "soft_timeout: 240\n"
        "turn_limit: 60\n"
        "concurrency:\n"
        "  global: 4\n"
        "  per_session: 2\n"
        "retention_days: 90\n"
        "default_mode: 'on'\n",
        encoding="utf-8",
    )
    (directory / "harnesses.yaml").write_text(
        'pi:\n  harness: pi\n  command: ["pi"]\n', encoding="utf-8"
    )
    (directory / "agent-catalog.yaml").write_text(
        "default_role: builder\n"
        "model_limits: {}\n"
        "roles:\n"
        "  builder:\n"
        "    enabled: manual\n"
        "    harness_config: pi\n"
        '    model: "m1"\n'
        "    env: {}\n"
        "    skills: [orch-builder]\n"
        "    dispatch_hint: Build and report.\n"
        "    auto_verify: false\n",
        encoding="utf-8",
    )
    (tmp_path / "state").mkdir()
    (tmp_path / "logs").mkdir()
    return directory


@pytest.mark.parametrize("limit", ["0", "-3"])
def test_history_rejects_nonpositive_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    limit: str,
) -> None:
    directory = _config_dir(tmp_path)
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(directory))

    rc = cli.main(["history", "--session-id", "manual:demo", "--limit", limit])

    assert rc == 1
    assert "history limit must be a positive integer" in capsys.readouterr().err


def test_history_default_limit_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    directory = _config_dir(tmp_path)
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(directory))

    assert cli.main(["history", "--session-id", "manual:demo"]) == 0
    assert '"runs"' in capsys.readouterr().out


@pytest.mark.parametrize("goal", ["", "   "])
def test_dispatch_rejects_blank_goal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    goal: str,
) -> None:
    directory = _config_dir(tmp_path)
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(directory))
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(""))

    rc = cli.main(["dispatch", "--session-id", "manual:demo", "--goal", goal])

    assert rc == 1
    assert "non-empty goal" in capsys.readouterr().err


def test_help_advertises_task_label(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["help"]) == 0
    out = capsys.readouterr().out
    assert "--task-label" in out
