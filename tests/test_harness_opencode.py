from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orchestra.config import RoleConfig
from orchestra.harnesses import OpenCodeHarness, WorkerProcess, WorkerRequest
from orchestra.harnesses.common import (
    ORCHESTRA_DISPATCH_BUDGET_ENV,
    expand_command_template,
    render_worker_prompt,
)
from tests.helpers import default_prompt_config


@pytest.fixture
def worker_request(tmp_path: Path) -> WorkerRequest:
    return WorkerRequest(
        role_name="worker",
        goal="Investigate the current implementation.",
        approved_context="Read the repo and summarize what matters.",
        boundaries="Do not edit files.",
        acceptance_target="Return a short status report.",
        timeout_seconds=30,
        log_path=tmp_path / "logs" / "worker.jsonl",
        prompts=default_prompt_config(),
    )


def test_opencode_harness_name() -> None:
    assert OpenCodeHarness().name == "opencode"


def test_opencode_harness_builds_command_without_shell_joining(
    worker_request: WorkerRequest,
) -> None:
    harness = OpenCodeHarness()
    role = RoleConfig(
        harness="opencode",
        model="test-model/agent",
        prompt_addition="Focus on the assigned task.",
        command=[
            "opencode",
            "run",
            "--agent",
            "plan",
            "--model",
            "{model}",
            "{prompt}",
        ],
    )

    prompt = harness.build_prompt(worker_request, role)
    command = harness.build_command(role, prompt)

    assert command[:-1] == [
        "opencode",
        "run",
        "--agent",
        "plan",
        "--model",
        "test-model/agent",
    ]
    assert command[-1] == prompt


def test_opencode_harness_omits_model_flag_when_none(
    worker_request: WorkerRequest,
) -> None:
    harness = OpenCodeHarness()
    role = RoleConfig(
        harness="opencode",
        model=None,
        prompt_addition="",
        command=[
            "opencode",
            "run",
            "--agent",
            "plan",
            "--model",
            "{model}",
            "{prompt}",
        ],
    )

    prompt = harness.build_prompt(worker_request, role)
    command = harness.build_command(role, prompt)

    assert command[:-1] == ["opencode", "run", "--agent", "plan"]
    assert command[-1] == prompt
    assert "--model" not in command


def test_opencode_harness_builds_scoped_prompt(worker_request: WorkerRequest) -> None:
    harness = OpenCodeHarness()
    role = RoleConfig(
        harness="opencode",
        model="test-model/agent",
        prompt_addition="Focus on the assigned task.",
        command=["opencode", "run", "{prompt}"],
    )

    prompt = harness.build_prompt(worker_request, role)

    assert "Role: worker" in prompt
    assert "Goal: Investigate the current implementation." in prompt
    assert "Role instructions: Focus on the assigned task." in prompt
    assert "Approved context: Read the repo and summarize what matters." in prompt
    assert "Out of scope: Do not edit files." in prompt
    assert "Acceptance target: Return a short status report." in prompt


def test_opencode_harness_uses_shared_prompt_and_command_helpers(
    worker_request: WorkerRequest,
) -> None:
    harness = OpenCodeHarness()
    role = RoleConfig(
        harness="opencode",
        model="test-model/agent",
        prompt_addition="Focus on the assigned task.",
        command=["opencode", "run", "--model", "{model}", "{prompt}"],
    )

    prompt = harness.build_prompt(worker_request, role)
    command = harness.build_command(role, prompt)

    assert prompt == render_worker_prompt(worker_request, role)
    assert command == expand_command_template(role, prompt)


def test_opencode_harness_start_returns_process_wrapper(
    worker_request: WorkerRequest,
    python_executable: str,
    fixture_dir: Path,
) -> None:
    harness = OpenCodeHarness()
    role = RoleConfig(
        harness="opencode",
        command=[
            python_executable,
            str(fixture_dir / "fake_worker.py"),
            "success",
            "--output",
            "hello_opencode",
        ],
    )

    worker = harness.start(worker_request, role)
    stdout, stderr = worker.process.communicate(timeout=5)

    assert worker.command[0] == python_executable
    assert worker.prompt.startswith("Role: worker")
    assert stdout.strip() == "hello_opencode"
    assert stderr.strip() == ""
    assert worker.process.returncode == 0


@patch("orchestra.harnesses.opencode.subprocess.Popen")
def test_opencode_harness_start_passes_process_group_flag(
    mock_popen: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ORCHESTRA_DISPATCH_BUDGET_ENV, "1")
    harness = OpenCodeHarness(starter=mock_popen)
    role = RoleConfig(
        harness="opencode",
        env={"OPENCODE_ROLE_ENV": "configured"},
        command=["opencode", "run", "{prompt}"],
    )

    mock_process = MagicMock()
    mock_process.stdout.readline.return_value = ""
    mock_process.terminate.return_value = None
    mock_popen.return_value = mock_process

    worker_request = WorkerRequest(
        role_name="worker",
        goal="smoke",
        approved_context="",
        boundaries="",
        acceptance_target="",
        timeout_seconds=30,
        log_path=None,
        prompts=default_prompt_config(),
    )

    worker: WorkerProcess = harness.start(worker_request, role)

    mock_popen.assert_called_once()
    call_kwargs = mock_popen.call_args[1]
    assert "start_new_session" in call_kwargs
    assert call_kwargs["env"][ORCHESTRA_DISPATCH_BUDGET_ENV] == "1"
    assert call_kwargs["env"]["OPENCODE_ROLE_ENV"] == "configured"
    assert worker.command[-1] == worker.prompt


def test_opencode_harness_start_with_custom_starter(
    worker_request: WorkerRequest,
) -> None:
    fake_process = MagicMock()
    fake_process.stdout.readline.return_value = ""

    def fake_starter(
        args: list[str], **kwargs: object
    ) -> MagicMock:
        del args, kwargs
        return fake_process

    harness = OpenCodeHarness(starter=fake_starter)
    role = RoleConfig(
        harness="opencode",
        command=["opencode", "run", "{prompt}"],
    )

    worker: WorkerProcess = harness.start(worker_request, role)

    assert isinstance(worker, WorkerProcess)
    assert worker.process is fake_process
    assert worker.command[0] == "opencode"
    assert worker.command[1] == "run"
    assert worker.command[-1] == worker.prompt
