from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
import yaml

from tests.helpers import wait_for_condition
from tests.types import RuntimeFilesFactory

pytestmark = pytest.mark.skipif(
    shutil.which("pi") is None or shutil.which("orchestra") is None,
    reason="pi or orchestra executable not found",
)


def _configure_builder_role(catalog_path: Path) -> None:
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    catalog["default_role"] = "builder"
    catalog["roles"] = {"builder": {"harness_config": "pi"}}
    catalog_path.write_text(yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8")


def _runtime_env(config_path: Path, catalog_path: Path, pi_dir: Path) -> dict[str, str]:
    return {
        **os.environ,
        "ORCHESTRA_CONFIG": str(config_path),
        "ORCHESTRA_AGENT_CATALOG": str(catalog_path),
        "PI_CODING_AGENT_DIR": str(pi_dir),
    }


def _install_pi_extension(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["orchestra", "init", "pi", "--force"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=Path(__file__).resolve().parents[1],
        timeout=30,
    )


def _run_pi(
    env: dict[str, str],
    session_id: str,
    *messages: str,
    mode: str = "text",
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "pi",
            "--mode",
            mode,
            "--no-approve",
            "--session-id",
            session_id,
            *messages,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _json_events(output: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def test_pi_extension_host_on_refreshes_skill_each_time(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, _ = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "adapter ok"],
    )
    _configure_builder_role(catalog_path)
    pi_dir = tmp_path / "pi-agent"
    env = _runtime_env(config_path, catalog_path, pi_dir)

    install = _install_pi_extension(env)
    assert install.returncode == 0
    assert 'verify: pi --no-approve -p "/orch doctor"' in install.stdout
    assert (pi_dir / "extensions" / "orchestra" / "index.ts").exists()

    session_id = f"orch-host-on-{uuid.uuid4().hex}"
    result = _run_pi(env, session_id, "/orch off", "/orch on", "/orch on", mode="json")

    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert "Orchestra tools hidden for this session. Run /orch on to enable them again." in output
    assert 'Orchestra tools enabled for this session. Run "/orch on" again to load the orchestrator skill.' in output
    assert output.count("Orchestra orchestrator skill refreshed for this session.") == 1
    assert "already loaded" not in output

    events = _json_events(output)
    command_events = [
        event
        for event in events
        if event.get("type") == "entry_appended"
        and isinstance((entry := event.get("entry")), dict)
        and isinstance((data := entry.get("data")), dict)
        and data.get("text") in {"/orch off", "/orch on"}
    ]
    assert len(command_events) == 3


def test_pi_extension_host_command_path(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, _ = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "adapter ok"],
    )
    _configure_builder_role(catalog_path)
    pi_dir = tmp_path / "pi-agent"
    env = _runtime_env(config_path, catalog_path, pi_dir)

    install = _install_pi_extension(env)
    assert install.returncode == 0

    session_id = f"orch-host-e2e-{uuid.uuid4().hex}"

    help_result = _run_pi(env, session_id, "/orch help")
    assert help_result.returncode == 0
    help_output = help_result.stdout + help_result.stderr
    assert "Orchestra commands:" in help_output
    assert (
        "/orch on                           Enable Orchestra tools or load the orchestrator skill"
        in help_output
    )
    assert "/orch off                          Hide Orchestra tools for this session" in help_output
    assert "/orch roles" in help_output
    assert "Configured roles" not in help_output
    assert "Default: builder" not in help_output
    assert "D builder  pi" not in help_output

    doctor = _run_pi(env, session_id, "/orch doctor")
    assert doctor.returncode == 0
    assert "config: ok" in doctor.stdout or "config: ok" in doctor.stderr

    dispatch = _run_pi(env, session_id, '/orch do --task-label "adapter task" adapter e2e worker')
    assert dispatch.returncode == 0
    assert "orchestra dispatched:" in dispatch.stdout or "orchestra dispatched:" in dispatch.stderr

    def history_contains_result() -> bool:
        result = _run_pi(env, session_id, "/orch history 10")
        output = result.stdout + result.stderr
        return "adapter ok" in output and "adapter task" in output

    history_ready = wait_for_condition(history_contains_result, timeout=8)
    assert history_ready
