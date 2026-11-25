"""The shared read-only role-list operation used by host plugins."""

from __future__ import annotations

import json
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
        "    auto_verify: false\n"
        "  verifier:\n"
        "    enabled: auto\n"
        "    harness_config: pi\n"
        '    model: "m1"\n'
        "    env: {}\n"
        "    skills: []\n"
        "    dispatch_hint: Verify and report.\n"
        "    auto_verify: false\n",
        encoding="utf-8",
    )
    (tmp_path / "state").mkdir()
    (tmp_path / "logs").mkdir()
    return directory


def test_roles_lists_catalog_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    directory = _config_dir(tmp_path)
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(directory))
    catalog_before = (directory / "agent-catalog.yaml").read_text(encoding="utf-8")

    assert cli.main(["roles"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["default_role"] == "builder"
    by_name = {role["name"]: role for role in payload["roles"]}
    assert set(by_name) == {"builder", "verifier"}
    assert by_name["builder"]["enabled"] == "manual"
    assert by_name["builder"]["model"] == "m1"
    assert by_name["builder"]["skills"] == ["orch-builder"]
    assert by_name["builder"]["dispatch_hint"] == "Build and report."
    assert by_name["verifier"]["enabled"] == "auto"
    # Read-only: the operation reports the catalog and changes nothing.
    assert (directory / "agent-catalog.yaml").read_text(encoding="utf-8") == catalog_before
