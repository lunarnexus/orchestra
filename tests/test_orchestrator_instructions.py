"""Tests for the orchestrator-instructions core session operation.

Covers: mode gate (off → empty), no-skills (→ empty), resolved content,
missing skill file (loud failure), and no mutation of dispatchable job state.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from orchestra.queue import JobQueue
from orchestra.session import SessionRuntime

REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION = "pi:ORCH_TEST"


def _config_dir(tmp_path: Path, *, orchestrator_skills: str = "[orch-orchestrator]", mode: str = "on") -> Path:
    d = tmp_path / "config"
    d.mkdir()
    shutil.copy(REPO_ROOT / "prompts.yaml", d / "prompts.yaml")
    (d / "config.yaml").write_text(
        f"state_dir: {tmp_path / 'state'}\nlog_dir: {tmp_path / 'logs'}\n"
        "default_timeout: 300\nsoft_timeout: 240\nturn_limit: 60\n"
        "concurrency:\n  global: 4\n  per_session: 2\n"
        f"retention_days: 90\ndefault_mode: '{mode}'\n",
        encoding="utf-8",
    )
    (d / "harnesses.yaml").write_text(
        'pi:\n  harness: pi\n  command: ["pi"]\n', encoding="utf-8"
    )
    (d / "agent-catalog.yaml").write_text(
        "default_role: builder\nmodel_limits: {}\nroles:\n"
        f"  orchestrator:\n    skills: {orchestrator_skills}\n"
        "  builder:\n    enabled: manual\n    harness_config: pi\n"
        '    model: "m1"\n    env: {}\n    skills: []\n'
        "    dispatch_hint: Build.\n    auto_verify: false\n",
        encoding="utf-8",
    )
    (tmp_path / "state").mkdir()
    (tmp_path / "logs").mkdir()
    # Create a skills dir with the referenced skill file.
    skill_dir = d / "skills" / "orch-orchestrator"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Orchestrator Skill\nDo things.", encoding="utf-8")
    return d


def _make_runtime(
    tmp_path: Path, *, config_dir: Path | None = None, mode: str = "on"
) -> tuple[SessionRuntime, list[dict[str, Any]]]:
    from orchestra.config import load_orchestra_config

    if config_dir is None:
        config_dir = _config_dir(tmp_path, mode=mode)
    config = load_orchestra_config(config_dir)
    queue = JobQueue(config.runtime.state_dir / "queue.db")
    sent: list[dict[str, Any]] = []
    runtime = SessionRuntime(
        queue=queue,
        parent_session=SESSION,
        state_dir=config.runtime.state_dir,
        prompts=config.prompts,
        send=lambda m: sent.append(m),
        mode=mode,
        config=config,
    )
    return runtime, sent


class TestOrchestratorInstructions:
    def test_returns_instructions_when_mode_on(self, tmp_path: Path) -> None:
        runtime, _ = _make_runtime(tmp_path)
        reply = runtime.handle({
            "kind": "request", "id": 1, "operation": "orchestrator-instructions", "arguments": {},
        })
        assert reply is not None
        assert reply["kind"] == "reply"
        assert reply["id"] == 1
        result = reply["result"]
        assert "Orchestrator Skill" in result["instructions"]

    def test_returns_empty_when_mode_off(self, tmp_path: Path) -> None:
        runtime, _ = _make_runtime(tmp_path, mode="off")
        reply = runtime.handle({
            "kind": "request", "id": 2, "operation": "orchestrator-instructions", "arguments": {},
        })
        assert reply is not None
        assert reply["result"]["instructions"] == ""

    def test_returns_empty_when_no_orchestrator_skills(self, tmp_path: Path) -> None:
        cfg = _config_dir(tmp_path, orchestrator_skills="[]")
        runtime, _ = _make_runtime(tmp_path, config_dir=cfg)
        reply = runtime.handle({
            "kind": "request", "id": 3, "operation": "orchestrator-instructions", "arguments": {},
        })
        assert reply is not None
        assert reply["result"]["instructions"] == ""

    def test_missing_skill_file_fails_loudly(self, tmp_path: Path) -> None:
        cfg = _config_dir(tmp_path)
        # Remove the skill file to trigger the error.
        (cfg / "skills" / "orch-orchestrator" / "SKILL.md").unlink()
        runtime, _ = _make_runtime(tmp_path, config_dir=cfg)
        reply = runtime.handle({
            "kind": "request", "id": 4, "operation": "orchestrator-instructions", "arguments": {},
        })
        assert reply is not None
        assert "error" in reply
        assert "not found" in reply["error"]

    def test_multiple_skills_resolved_in_order(self, tmp_path: Path) -> None:
        cfg = _config_dir(tmp_path, orchestrator_skills="[alpha, beta]")
        # Create skill files
        for name, content in [("alpha", "ALPHA"), ("beta", "BETA")]:
            d = cfg / "skills" / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(content, encoding="utf-8")
        runtime, _ = _make_runtime(tmp_path, config_dir=cfg)
        reply = runtime.handle({
            "kind": "request", "id": 5, "operation": "orchestrator-instructions", "arguments": {},
        })
        assert reply is not None
        instructions = reply["result"]["instructions"]
        assert instructions.index("ALPHA") < instructions.index("BETA")

    def test_no_mutation_of_job_state(self, tmp_path: Path) -> None:
        runtime, _ = _make_runtime(tmp_path)
        # Snapshot before
        snap_before = runtime._queue.snapshot(SESSION)
        # Call the operation
        runtime.handle({
            "kind": "request", "id": 6, "operation": "orchestrator-instructions", "arguments": {},
        })
        # Snapshot after — no jobs created or changed
        snap_after = runtime._queue.snapshot(SESSION)
        assert len(snap_before.jobs) == len(snap_after.jobs)

    def test_orchestrator_role_not_dispatchable(self, tmp_path: Path) -> None:
        """Dispatching to 'orchestrator' role fails as unknown role."""
        from orchestra.config import load_orchestra_config
        from orchestra.submit import Assignment, SubmitError, submit

        cfg = _config_dir(tmp_path)
        config = load_orchestra_config(cfg)
        queue = JobQueue(cfg.parent / "state" / "queue.db")
        with pytest.raises(SubmitError, match="unknown role"):
            submit(
                cfg.parent / "state",
                queue,
                config,
                "test:session",
                [Assignment(goal="do stuff", role="orchestrator")],
            )
