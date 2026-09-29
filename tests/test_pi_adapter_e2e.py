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


def _runtime_env(config_path: Path, _catalog_path: Path, pi_dir: Path) -> dict[str, str]:
    return {
        **os.environ,
        "ORCHESTRA_CONFIG": str(config_path.parent),
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
    result = _run_pi(env, session_id, "/orch off", "/orch on", mode="json")

    assert result.returncode == 0
    output = result.stdout + result.stderr
    assert "Orchestra tools hidden for this session. Run /orch on to enable them again." in output
    assert "Orchestra tools enabled for this session." in output
    assert "Orchestra orchestrator skill refreshed for this session." not in output
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
    assert len(command_events) == 2


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
        "/orch on                           Enable Orchestra tools"
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


def _configure_parent_context_roles(catalog_path: Path) -> None:
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    catalog["default_role"] = "worker"
    catalog["roles"] = {
        "worker": {"harness_config": "pi"},
        "builder": {"harness_config": "pi", "pass_parent_context": True},
    }
    catalog_path.write_text(yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8")


def _request_payloads(state_dir: Path) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for request_file in sorted((state_dir / "runs").glob("*/request.json")):
        try:
            payload = json.loads(request_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def _seed_pi_session(pi_dir: Path, session_id: str, cwd: Path) -> None:
    """Create a v3 Pi session file with recorded user/assistant messages."""
    encoded_cwd = str(cwd).lstrip("/").replace("/", "-")
    project_dir = pi_dir / "sessions" / f"--{encoded_cwd}--"
    project_dir.mkdir(parents=True, exist_ok=True)
    timestamp = "2026-01-01T00:00:00.000Z"
    lines = [
        {
            "type": "session",
            "version": 3,
            "id": session_id,
            "timestamp": timestamp,
            "cwd": str(cwd),
        },
        {
            "type": "message",
            "id": "seed-user-1",
            "parentId": None,
            "timestamp": timestamp,
            "message": {"role": "user", "content": "Remember the marker word zebrafish for later."},
        },
        {
            "type": "message",
            "id": "seed-assistant-1",
            "parentId": "seed-user-1",
            "timestamp": timestamp,
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Noted: zebrafish."}],
                "provider": "anthropic",
                "model": "claude-sonnet-4-5",
                "stopReason": "end_turn",
            },
        },
    ]
    session_file = project_dir / f"2026-01-01T00-00-00-000Z_{session_id}.jsonl"
    session_file.write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n",
        encoding="utf-8",
    )


def test_pi_extension_parent_context_artifact_for_opted_in_role(
    tmp_path: Path,
    runtime_files_factory: RuntimeFilesFactory,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    config_path, catalog_path, _ = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "adapter ok"],
    )
    _configure_parent_context_roles(catalog_path)
    pi_dir = tmp_path / "pi-agent"
    env = _runtime_env(config_path, catalog_path, pi_dir)
    pi_tmp_dir = tmp_path / "pi-tmp"
    pi_tmp_dir.mkdir()
    env["TMPDIR"] = str(pi_tmp_dir)

    install = _install_pi_extension(env)
    assert install.returncode == 0

    cwd = Path.cwd()
    seeded_session_id = f"orch-pctx-{uuid.uuid4().hex}"
    _seed_pi_session(pi_dir, seeded_session_id, cwd)
    dispatch = _run_pi(env, seeded_session_id, "/orch do --role builder parent context e2e goal")
    assert dispatch.returncode == 0
    output = dispatch.stdout + dispatch.stderr
    assert "orchestra dispatched:" in output

    payloads = [
        payload
        for payload in _request_payloads(tmp_path / "state")
        if payload.get("goal") == "parent context e2e goal"
    ]
    assert len(payloads) == 1
    artifact_raw = payloads[0].get("parent_context_artifact")
    assert isinstance(artifact_raw, str) and artifact_raw
    artifact_file = Path(artifact_raw)
    assert artifact_file.is_file()
    # Core copies the artifact into the run state directory as a private run-scoped file.
    assert artifact_file.parent.parent == tmp_path / "state" / "runs"
    assert artifact_file.name == "parent-context.jsonl"
    assert artifact_file.stat().st_mode & 0o777 == 0o600
    content = artifact_file.read_text(encoding="utf-8")
    # Recorded session history is captured from the Pi session manager.
    assert "zebrafish" in content

    # The adapter's staged source is transient: core's run artifact is the only
    # persistent parent-context file, so no tempdir snapshots remain after dispatch.
    leftovers = list(pi_tmp_dir.glob("orchestra-parent-context-*"))
    assert leftovers == []

    fresh_session_id = f"orch-pctx-{uuid.uuid4().hex}"
    fresh_dispatch = _run_pi(
        env, fresh_session_id, "/orch do --role builder fresh parent context goal"
    )
    assert fresh_dispatch.returncode == 0
    fresh_output = fresh_dispatch.stdout + fresh_dispatch.stderr
    assert "orchestra dispatched:" in fresh_output

    fresh_payloads = [
        payload
        for payload in _request_payloads(tmp_path / "state")
        if payload.get("goal") == "fresh parent context goal"
    ]
    assert len(fresh_payloads) == 1
    fresh_artifact_raw = fresh_payloads[0].get("parent_context_artifact")
    assert isinstance(fresh_artifact_raw, str) and fresh_artifact_raw
    fresh_content = Path(fresh_artifact_raw).read_text(encoding="utf-8")
    # Fresh sessions have no recorded messages; the dispatch request is captured.
    assert "fresh parent context goal" in fresh_content

    plain_session_id = f"orch-pctx-{uuid.uuid4().hex}"
    plain_dispatch = _run_pi(env, plain_session_id, "/orch do plain e2e goal")
    assert plain_dispatch.returncode == 0
    plain_output = plain_dispatch.stdout + plain_dispatch.stderr
    assert "orchestra dispatched:" in plain_output

    plain_payloads = [
        payload
        for payload in _request_payloads(tmp_path / "state")
        if payload.get("goal") == "plain e2e goal"
    ]
    assert len(plain_payloads) == 1
    # Non-opted-in default role keeps existing behavior: no parent context artifact.
    assert not plain_payloads[0].get("parent_context_artifact")
