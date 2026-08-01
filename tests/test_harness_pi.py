from __future__ import annotations

import os
from pathlib import Path

import pytest

from orchestra.config import PromptConfig, RoleConfig
from orchestra.harnesses import HarnessRegistry, PiHarness, WorkerRequest
from orchestra.harnesses.common import (
    ORCHESTRA_WORKER_ENV,
    compact_summary,
    expand_command_template,
    orchestra_can_dispatch,
    orchestra_worker_budget,
    render_worker_prompt,
    summary_was_truncated,
    worker_subprocess_env,
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


def test_pi_harness_injects_local_role_skill_before_goal(
    worker_request: WorkerRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill_dir = tmp_path / "skills" / "code-reviewer"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Code Reviewer\n\nReview the diff.", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    role = RoleConfig(
        harness="pi",
        skills=("code-reviewer",),
        command=["pi", "-p", "{prompt}"],
    )

    prompt = PiHarness().build_prompt(worker_request, role)

    assert "Role skill: code-reviewer" in prompt
    assert "# Code Reviewer" in prompt
    assert "Loaded from:" not in prompt
    assert prompt.index("Role skill: code-reviewer") < prompt.index("Goal:")


def test_pi_harness_falls_back_to_native_skill_instruction(
    worker_request: WorkerRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_skill_dir = tmp_path / "skills" / "security-reviewer"
    parent_skill_dir.mkdir(parents=True)
    (parent_skill_dir / "SKILL.md").write_text("# Security Reviewer", encoding="utf-8")
    child_dir = tmp_path / "child"
    child_dir.mkdir()
    monkeypatch.chdir(child_dir)
    role = RoleConfig(
        harness="pi",
        skills=("security-reviewer",),
        command=["pi", "-p", "{prompt}"],
    )

    prompt = PiHarness().build_prompt(worker_request, role)

    assert "Role skill: security-reviewer" in prompt
    assert "# Security Reviewer" not in prompt
    assert "Load the native skill named 'security-reviewer' before doing the task." in prompt


def test_pi_harness_uses_configured_default_return_format(worker_request: WorkerRequest) -> None:
    harness = PiHarness()
    role = RoleConfig(harness="pi", command=["pi", "-p", "{prompt}"])
    request = WorkerRequest(
        role_name=worker_request.role_name,
        goal=worker_request.goal,
        timeout_seconds=worker_request.timeout_seconds,
        prompts=PromptConfig(default_return_format="Configured return."),
    )

    prompt = harness.build_prompt(request, role)

    assert "Goal: Investigate the current implementation." in prompt
    assert "Return format: Configured return." in prompt


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


@pytest.mark.parametrize(
    ("current", "configured", "can_dispatch", "child"),
    [
        (None, None, True, "1"),
        ("0", None, True, "1"),
        ("1", None, False, "1"),
        ("2", None, True, "1"),
        ("3", None, True, "1"),
        (None, 2, True, "2"),
        ("0", 2, True, "2"),
        ("2", 2, True, "1"),
        ("3", 2, True, "2"),
    ],
)
def test_worker_subprocess_env_decrements_orchestra_worker_budget(
    monkeypatch: pytest.MonkeyPatch,
    current: str | None,
    configured: int | None,
    can_dispatch: bool,
    child: str,
) -> None:
    if current is None:
        monkeypatch.delenv(ORCHESTRA_WORKER_ENV, raising=False)
    else:
        monkeypatch.setenv(ORCHESTRA_WORKER_ENV, current)

    env = worker_subprocess_env(worker_budget=configured)

    assert orchestra_can_dispatch() is can_dispatch
    assert env[ORCHESTRA_WORKER_ENV] == child
    assert orchestra_worker_budget(env) == int(child)
    if current is not None:
        assert os.environ[ORCHESTRA_WORKER_ENV] == current


def test_compact_summary_normalizes_and_truncates_output() -> None:
    assert compact_summary("line one\nline two") == "line one line two"
    assert compact_summary("x" * 12, limit=10) == "xxxxxxx..."
    assert summary_was_truncated("x" * 12, limit=10) is True
    assert summary_was_truncated("line one", limit=10) is False


def test_worker_subprocess_env_applies_role_env_without_mutating_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ROLE_ONLY", "parent")

    env = worker_subprocess_env(role_env={"ROLE_ONLY": "role", "NEW_VALUE": "set"})

    assert env["ROLE_ONLY"] == "role"
    assert env["NEW_VALUE"] == "set"
    assert env[ORCHESTRA_WORKER_ENV] == "1"
    assert os.environ["ROLE_ONLY"] == "parent"


def test_worker_subprocess_env_preserves_orchestra_worker_budget_over_role_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ORCHESTRA_WORKER_ENV, raising=False)

    env = worker_subprocess_env(role_env={ORCHESTRA_WORKER_ENV: "99"})

    assert env[ORCHESTRA_WORKER_ENV] == "1"


def test_pi_harness_start_sets_orchestra_worker_env_budget(
    worker_request: WorkerRequest,
    python_executable: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ORCHESTRA_WORKER_ENV, raising=False)
    worker_request = WorkerRequest(
        role_name=worker_request.role_name,
        goal=worker_request.goal,
        approved_context=worker_request.approved_context,
        boundaries=worker_request.boundaries,
        acceptance_target=worker_request.acceptance_target,
        timeout_seconds=worker_request.timeout_seconds,
        log_path=worker_request.log_path,
        worker_budget=2,
    )
    harness = PiHarness()
    role = RoleConfig(
        harness="pi",
        command=[
            python_executable,
            "-c",
            "import os; print(os.environ.get('ORCHESTRA_WORKER'))",
        ],
    )

    worker = harness.start(worker_request, role)
    stdout, stderr = worker.process.communicate(timeout=5)

    assert stdout.strip() == "2"
    assert stderr.strip() == ""
    assert ORCHESTRA_WORKER_ENV not in os.environ


def test_pi_harness_start_passes_role_env(
    worker_request: WorkerRequest,
    python_executable: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ROLE_ENV_TEST", raising=False)
    role = RoleConfig(
        harness="pi",
        env={"ROLE_ENV_TEST": "configured"},
        command=[
            python_executable,
            "-c",
            "import os; print(os.environ.get('ROLE_ENV_TEST', 'missing'))",
        ],
    )

    worker = PiHarness().start(worker_request, role)
    stdout, stderr = worker.process.communicate(timeout=5)

    assert stdout.strip() == "configured"
    assert stderr.strip() == ""
    assert "ROLE_ENV_TEST" not in os.environ


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
