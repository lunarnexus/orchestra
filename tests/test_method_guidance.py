from __future__ import annotations

from pathlib import Path

import yaml


def test_builder_skill_caps_repeated_test_debugging() -> None:
    skill = Path("skills/builder/SKILL.md").read_text(encoding="utf-8")

    assert "run the exact focused check once after each patch" in skill
    assert "same focused command fails twice" in skill
    assert "Use a single-test or test-filter command in the build loop" in skill
    assert "run a suite command once" in skill


def test_verifier_reuses_builder_command_evidence() -> None:
    skill = Path("skills/verifier/SKILL.md").read_text(encoding="utf-8")

    assert "Do not rerun a builder command" in skill
    assert "Evidence reused" in skill
    assert "An artifact-only repair runs no commands" in skill


def test_orchestrator_skill_scopes_verifier_failure_fixers() -> None:
    skill = Path("skills/orchestrator/SKILL.md").read_text(encoding="utf-8")

    assert "dispatch one narrow fixer" in skill
    assert "exact failing evidence" in skill
    assert "same focused check fails twice" in skill


def test_default_catalog_reviewer_remains_read_only_without_duplicate_tests() -> None:
    catalog = yaml.safe_load(Path("agent-catalog.yaml").read_text(encoding="utf-8"))

    reviewer_prompt = catalog["roles"]["reviewer"]["prompt_addition"]
    assert "Stay read-only" in reviewer_prompt
    assert "Run no test commands" in reviewer_prompt


def test_orchestrator_artifact_repairs_do_not_run_commands() -> None:
    skill = Path("skills/orchestrator/SKILL.md").read_text(encoding="utf-8")

    assert "Do not dispatch another subagent only to copy returned evidence" in skill
    assert "artifact-only repair" in skill
    assert "runs no commands" in skill


def test_orchestrator_delegates_package_installation_to_builder() -> None:
    orchestrator_skill = Path("skills/orchestrator/SKILL.md").read_text(encoding="utf-8")
    builder_skill = Path("skills/builder/SKILL.md").read_text(encoding="utf-8")
    prompts = Path("prompts.yaml").read_text(encoding="utf-8")

    assert "pip install" in orchestrator_skill
    assert "npm install" in orchestrator_skill
    assert "dispatch a builder" in orchestrator_skill
    assert "does not run the install command itself" in orchestrator_skill
    assert "Builder owns implementation setup commands" in builder_skill
    assert "package installation, dependency setup" in prompts


def test_default_return_format_tracks_reused_evidence() -> None:
    prompts = Path("prompts.yaml").read_text(encoding="utf-8")

    assert "Evidence reused:" in prompts
    assert "<artifact path and exact command evidence" in prompts


def test_roadmap_tracks_command_deduplication_wishlist() -> None:
    roadmap = Path("ROADMAP.md").read_text(encoding="utf-8")

    assert "Command de-duplication guard for subagent tool use" in roadmap
    assert "Pi, Hermes, OpenCode" in roadmap
