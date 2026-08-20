from __future__ import annotations

from pathlib import Path

import yaml


def test_builder_skill_caps_repeated_test_debugging() -> None:
    skill = Path("skills/builder/SKILL.md").read_text(encoding="utf-8")

    assert "run the exact focused check once after each patch" in skill
    assert "same focused command fails twice" in skill
    assert "do not repeatedly run unchanged broad suites" in skill


def test_orchestrator_skill_scopes_verifier_failure_fixers() -> None:
    skill = Path("skills/orchestrator/SKILL.md").read_text(encoding="utf-8")

    assert "dispatch one narrow fixer" in skill
    assert "exact failing evidence" in skill
    assert "same focused check fails twice" in skill


def test_default_catalog_reviewer_remains_read_only_without_duplicate_tests() -> None:
    catalog = yaml.safe_load(
        Path("src/orchestra/assets/agent-catalog.yaml").read_text(encoding="utf-8")
    )

    reviewer_prompt = catalog["roles"]["reviewer"]["prompt_addition"]
    assert "Stay read-only" in reviewer_prompt
    assert "Do not run tests unless" in reviewer_prompt


def test_roadmap_tracks_command_deduplication_wishlist() -> None:
    roadmap = Path("ROADMAP.md").read_text(encoding="utf-8")

    assert "Command de-duplication guard for subagent tool use" in roadmap
    assert "Pi, Hermes, OpenCode" in roadmap
