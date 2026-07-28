from __future__ import annotations

from pathlib import Path

import pytest

from orchestra.config import PromptConfig, RoleConfig
from orchestra.harnesses import HarnessRegistry, PiHarness, WorkerRequest
from orchestra.harnesses.common import (
    compact_summary,
    expand_command_template,
    render_worker_prompt,
)


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
    )


def test_registry_returns_registered_harness() -> None:
    registry = HarnessRegistry()
    harness = PiHarness()

    registry.register(harness)

    assert registry.get("pi") is harness


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        (
            "lmstudio/qwen3.6-35b-a3b-uncensored-heretic-native-mtp-preserved",
            [
                "pi",
                "--no-session",
                "--model",
                "lmstudio/qwen3.6-35b-a3b-uncensored-heretic-native-mtp-preserved",
                "-p",
            ],
        ),
        (None, ["pi", "--no-session", "-p"]),
    ],
)
def test_pi_harness_builds_command_without_shell_joining(
    worker_request: WorkerRequest,
    model: str | None,
    expected: list[str],
) -> None:
    harness = PiHarness()
    role = RoleConfig(
        harness="pi",
        model=model,
        prompt_addition="Focus on the assigned task.",
        command=["pi", "--no-session", "--model", "{model}", "-p", "{prompt}"],
    )

    command = harness.build_command(role, harness.build_prompt(worker_request, role))

    assert command[:-1] == expected
    assert "Goal: Investigate the current implementation." in command[-1]


def test_pi_harness_builds_scoped_prompt(worker_request: WorkerRequest) -> None:
    harness = PiHarness()
    role = RoleConfig(
        harness="pi",
        prompt_addition="Focus on the assigned task.",
        command=["pi", "-p", "{prompt}"],
    )

    prompt = harness.build_prompt(worker_request, role)

    assert "Role: worker" in prompt
    assert "Goal: Investigate the current implementation." in prompt
    assert "Role instructions: Focus on the assigned task." in prompt
    assert "Approved context: Read the repo and summarize what matters." in prompt
    assert "Out of scope: Do not edit files." in prompt
    assert "Acceptance target: Return a short status report." in prompt
    assert "Return format:" in prompt


def test_pi_harness_uses_configured_prompt_text(worker_request: WorkerRequest) -> None:
    harness = PiHarness()
    role = RoleConfig(harness="pi", command=["pi", "-p", "{prompt}"])
    request = WorkerRequest(
        role_name=worker_request.role_name,
        goal=worker_request.goal,
        timeout_seconds=worker_request.timeout_seconds,
        prompts=PromptConfig(
            default_return_format="Configured return.",
            worker_goal_label="Objective",
            worker_return_format_label="Respond with",
        ),
    )

    prompt = harness.build_prompt(request, role)

    assert "Objective: Investigate the current implementation." in prompt
    assert "Respond with: Configured return." in prompt


def test_pi_harness_uses_shared_prompt_and_command_helpers(worker_request: WorkerRequest) -> None:
    harness = PiHarness()
    role = RoleConfig(
        harness="pi",
        model="test-model",
        profile="test-profile",
        prompt_addition="Focus on the assigned task.",
        command=["pi", "--model", "{model}", "--profile", "{profile}", "-p", "{prompt}"],
    )

    prompt = harness.build_prompt(worker_request, role)
    command = harness.build_command(role, prompt)

    assert prompt == render_worker_prompt(worker_request, role)
    assert command == expand_command_template(role, prompt)


def test_compact_summary_normalizes_and_truncates_output() -> None:
    assert compact_summary("line one\nline two") == "line one line two"
    assert compact_summary("x" * 12, limit=10) == "xxxxxxx..."


def test_pi_harness_start_returns_process_wrapper(
    worker_request: WorkerRequest,
    python_executable: str,
    fixture_dir: Path,
) -> None:
    harness = PiHarness()
    role = RoleConfig(
        harness="pi",
        command=[
            python_executable,
            str(fixture_dir / "fake_worker.py"),
            "success",
            "--output",
            "hello",
        ],
    )

    worker = harness.start(worker_request, role)
    stdout, stderr = worker.process.communicate(timeout=5)

    assert worker.command[0] == python_executable
    assert worker.prompt.startswith("Role: worker")
    assert stdout.strip() == "hello"
    assert stderr.strip() == ""
    assert worker.process.returncode == 0
