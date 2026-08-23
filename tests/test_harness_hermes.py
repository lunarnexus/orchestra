from __future__ import annotations

from pathlib import Path

import pytest

from orchestra.config import RoleConfig, load_app_config
from orchestra.harnesses import WorkerRequest
from orchestra.harnesses.common import ORCHESTRA_DISPATCH_BUDGET_ENV
from orchestra.harnesses.hermes import HermesHarness

ROOT_PROMPTS = load_app_config(Path(__file__).resolve().parents[1] / "config.yaml").prompts


def _worker_request(tmp_path: Path) -> WorkerRequest:
    return WorkerRequest(
        role_name="worker",
        goal="Inspect the Hermes harness.",
        approved_context="Use fake command tests only.",
        boundaries="Do not call live Hermes.",
        acceptance_target="Return concise result.",
        timeout_seconds=30,
        log_path=tmp_path / "worker.jsonl",
        prompts=ROOT_PROMPTS,
    )


def test_hermes_harness_builds_oneshot_command_with_prompt(
    tmp_path: Path,
) -> None:
    request = _worker_request(tmp_path)
    role = RoleConfig(
        harness="hermes",
        profile="worker-profile",
        model="gpt-5.5",
        prompt_addition="Act as focused one-shot worker.",
        command=[
            "hermes",
            "--profile",
            "{profile}",
            "--model",
            "{model}",
            "-z",
            "{prompt}",
        ],
    )

    harness = HermesHarness()
    prompt = harness.build_prompt(request, role)
    command = harness.build_command(role, prompt)

    assert command[:-1] == [
        "hermes",
        "--profile",
        "worker-profile",
        "--model",
        "gpt-5.5",
        "-z",
    ]
    assert command[-1] == prompt
    assert "Goal: Inspect the Hermes harness." in prompt
    assert "Role instructions: Act as focused one-shot worker." in prompt


def test_hermes_harness_drops_unset_optional_model_and_profile(
    tmp_path: Path,
) -> None:
    request = WorkerRequest(
        role_name="worker",
        goal="Run minimal Hermes worker.",
        timeout_seconds=30,
        log_path=tmp_path / "worker.jsonl",
        prompts=ROOT_PROMPTS,
    )
    role = RoleConfig(
        harness="hermes",
        command=[
            "hermes",
            "--profile",
            "{profile}",
            "--model",
            "{model}",
            "-z",
            "{prompt}",
        ],
    )

    harness = HermesHarness()
    command = harness.build_command(role, harness.build_prompt(request, role))

    assert command[:2] == ["hermes", "-z"]
    assert "--profile" not in command
    assert "--model" not in command


def test_hermes_harness_start_sets_orchestra_dispatch_budget_env_counter(
    tmp_path: Path,
    python_executable: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ORCHESTRA_DISPATCH_BUDGET_ENV, raising=False)
    harness = HermesHarness()
    role = RoleConfig(
        harness="hermes",
        command=[
            python_executable,
            "-c",
            "import os; print(os.environ.get('ORCHESTRA_DISPATCH_BUDGET'))",
        ],
    )

    worker = harness.start(_worker_request(tmp_path), role)
    stdout, stderr = worker.process.communicate(timeout=5)

    assert stdout.strip() == "1"
    assert stderr.strip() == ""


def test_hermes_harness_start_uses_configured_fake_command(
    tmp_path: Path,
    python_executable: str,
    fixture_dir: Path,
) -> None:
    harness = HermesHarness()
    role = RoleConfig(
        harness="hermes",
        command=[
            python_executable,
            str(fixture_dir / "fake_worker.py"),
            "success",
            "--output",
            "hermes worker done",
        ],
    )

    worker = harness.start(_worker_request(tmp_path), role)
    stdout, stderr = worker.process.communicate(timeout=5)

    assert worker.command[0] == python_executable
    assert worker.prompt.startswith("Role: worker")
    assert stdout.strip() == "hermes worker done"
    assert stderr.strip() == ""
    assert worker.process.returncode == 0
