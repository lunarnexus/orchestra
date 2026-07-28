from __future__ import annotations

from pathlib import Path

import pytest

from orchestra.config import RoleConfig
from orchestra.harnesses import HarnessRegistry, PiHarness, WorkerRequest


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
