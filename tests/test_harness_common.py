"""Focused tests for shared harness child-return parsing and prompt rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestra.config import RoleConfig, load_app_config
from orchestra.harnesses.base import WorkerRequest
from orchestra.harnesses.common import parse_child_return, render_worker_prompt

ROOT_PROMPTS = load_app_config(Path(__file__).resolve().parents[1] / "config.yaml").prompts


def _prompt_request(tmp_path: Path, **overrides: object) -> WorkerRequest:
    values: dict[str, object] = {
        "role_name": "worker",
        "goal": "Do the assigned work.",
        "additional_context": "Existing additional context.",
        "boundaries": "Stay in scope.",
        "acceptance_target": "Return a status report.",
        "timeout_seconds": 30,
        "log_path": tmp_path / "logs" / "worker.jsonl",
        "prompts": ROOT_PROMPTS,
    }
    values.update(overrides)
    return WorkerRequest(**values)  # type: ignore[arg-type]


def test_render_worker_prompt_includes_parent_context_artifact_line(
    tmp_path: Path,
) -> None:
    artifact = str(tmp_path / "parent-context.md")
    request = _prompt_request(tmp_path, parent_context_artifact=artifact)
    role = RoleConfig(harness="pi", command=["pi", "-p", "{prompt}"])

    prompt = render_worker_prompt(request, role)
    sections = prompt.split("\n\n")

    assert f"Parent context: Read {artifact} before starting." in sections
    # Rendered as its own section, separate from Additional context.
    assert "Additional context: Existing additional context." in sections
    combined_index = [i for i, s in enumerate(sections) if s.startswith("Parent context")]
    assert len(combined_index) == 1


def test_render_worker_prompt_without_parent_context_keeps_old_behavior(
    tmp_path: Path,
) -> None:
    request = _prompt_request(tmp_path)
    role = RoleConfig(harness="pi", command=["pi", "-p", "{prompt}"])

    prompt = render_worker_prompt(request, role)

    assert "Parent context" not in prompt
    sections = prompt.split("\n\n")
    assert "Additional context: Existing additional context." in sections


@pytest.mark.parametrize("value", ["none", "n/a", "na", "not applicable"])
def test_neutral_verdict_values_do_not_override_status_fallback(value: str) -> None:
    summary, verdict, _, _ = parse_child_return(f"Status: complete\nVerdict: {value}")

    assert summary is not None
    assert verdict == "complete"


@pytest.mark.parametrize("value", ["none", "n/a", "na", "not applicable"])
def test_status_fallback_survives_later_neutral_verdict(value: str) -> None:
    _, verdict, _, _ = parse_child_return(f"Status: failed\nVerdict: {value}")

    assert verdict == "failed"


@pytest.mark.parametrize("value", ["none", "n/a", "na", "not applicable"])
def test_status_fallback_survives_earlier_neutral_verdict(value: str) -> None:
    _, verdict, _, _ = parse_child_return(f"Verdict: {value}\nStatus: failed")

    assert verdict == "failed"


def test_neutral_verdict_without_status_is_absent() -> None:
    summary, verdict, _, _ = parse_child_return("Verdict: n/a")

    assert summary == "Verdict: n/a"
    assert verdict is None


def test_status_na_is_not_neutralized() -> None:
    summary, verdict, _, _ = parse_child_return("Status: n/a")

    assert summary == "Status: n/a"
    assert verdict == "n/a"


@pytest.mark.parametrize("value", ["none", "n/a", "na", "not applicable"])
def test_earlier_neutral_verdict_does_not_wipe_later_real_verdict(value: str) -> None:
    summary, verdict, _, _ = parse_child_return(
        f"Status: complete\nVerdict: {value}\nProgress: partial\nVerdict: blocked"
    )

    assert summary is not None
    assert verdict == "blocked"


@pytest.mark.parametrize(
    "value",
    [
        "none (no work)",
        "n/a (planning only, no code changes)",
        "na (docs review)",
        "not applicable (no code paths touched)",
    ],
)
def test_annotated_neutral_verdict_does_not_override_status_fallback(value: str) -> None:
    summary, verdict, _, _ = parse_child_return(f"Status: complete\nVerdict: {value}")

    assert summary is not None
    assert verdict == "complete"


def test_annotated_neutral_verdict_without_status_is_absent() -> None:
    summary, verdict, _, _ = parse_child_return("Verdict: n/a (planning only)")

    assert summary == "Verdict: n/a (planning only)"
    assert verdict is None


def test_non_neutral_annotation_is_not_swallowed() -> None:
    _, verdict, _, _ = parse_child_return("Status: complete\nVerdict: blocked (missing plan)")

    assert verdict == "blocked (missing plan)"


def test_real_verdict_still_captured() -> None:
    summary, verdict, blocker, _ = parse_child_return(
        "Status: complete\nVerdict: blocked\nBlockers: missing plan"
    )

    assert summary is not None
    assert verdict == "blocked"
    assert blocker == "missing plan"
