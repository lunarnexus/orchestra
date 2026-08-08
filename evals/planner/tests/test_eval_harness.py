from __future__ import annotations

import json
import subprocess
from pathlib import Path

from evals.planner.cli import parse_run_id
from evals.planner.eval_harness import (
    CASES,
    create_workspace,
    grade_workspace,
    suite_summary,
    trace_summary,
)


def test_planner_skill_and_resources_encode_research_contract() -> None:
    root = Path(__file__).parents[3]
    skill = (root / "skills" / "planner" / "SKILL.md").read_text()
    validation = (root / "skills" / "planner" / "resources" / "plan-validation.md").read_text()

    assert "answerable evidence unit" in skill
    assert "Use Researchers to save context" in skill
    assert "Do not delegate planning" in skill
    assert "After assigning a fact to Researcher" in skill
    assert "only a successful Researcher result can unblock" in skill
    assert "Do not claim persistent worker context" in skill
    assert "Research contract" in validation
    assert "Research scope and answer shape" in validation
    assert "Research classification" in validation


def test_suite_covers_planner_contract_and_resources() -> None:
    assert len(CASES) >= 70
    suite_names = {case.suite for case in CASES.values()}
    suite_counts = {
        suite: sum(case.suite == suite for case in CASES.values()) for suite in suite_names
    }
    assert suite_counts["smoke"] == 5
    assert suite_counts["contract"] == 15
    assert suite_counts["capability/dev"] == 50
    resources = {resource for case in CASES.values() for resource in case.expected_resources}
    assert resources >= {
        "resources/scope-and-decisions.md",
        "resources/slices-and-dependencies.md",
        "resources/tests-and-verification.md",
        "resources/architecture-and-integrations.md",
        "resources/refactors-migrations-and-rollbacks.md",
        "resources/plan-validation.md",
    }
    verdicts = {case.expected_verdict for case in CASES.values()}
    assert verdicts == {"ready", "blocked"}
    assert sum(case.requires_dispatch for case in CASES.values()) >= 1
    assert sum(case.requires_no_dispatch for case in CASES.values()) >= 50


def test_create_workspace_hides_grader_and_preserves_baseline(tmp_path: Path) -> None:
    case_dir = create_workspace("swebench-regression-pagination", tmp_path)

    assert (case_dir / "workspace" / "pagination.py").exists()
    assert (case_dir / "hidden" / "grade_config.json").exists()
    assert "expected_verdict" in (case_dir / "hidden" / "grade_config.json").read_text()
    assert not (case_dir / "workspace" / "hidden").exists()

    status = __import__("subprocess").check_output(
        ["git", "status", "--porcelain"], cwd=case_dir / "workspace", text=True
    )
    assert status == ""


def test_ready_plan_with_required_sections_passes(tmp_path: Path) -> None:
    case_dir = create_workspace("swebench-regression-pagination", tmp_path)
    (case_dir / "result.txt").write_text(
        "Mode: plan\nVerdict: ready\nArtifacts:\n- PLAN.md proposed\n"
        "Plan summary:\n- Slice count: 1\n"
        "Research used:\n- Existing `pagination.py` and `test_pagination.py` are sufficient\n"
        "Research still needed:\n- none\n"
        "Open questions:\n- none\n"
        "Next action:\n- approve plan\n"
        "FAIL_TO_PASS: page 2 boundary\nPASS_TO_PASS: page 1 and empty regressions\n"
        "Task Breakdown:\n"
        "- [ ] Slice 1 — sequential — fix page 2 pagination\n"
        "  Scope: `pagination.py`, `test_pagination.py`\n"
        "  Stop when: function and test exist\n"
        "  Verify: python3 -m pytest test_names.py\n"
        "  Risk: P2 — utility behavior\n"
        "  Gates: verifier, reviewer\n"
    )

    grade = grade_workspace(case_dir)

    assert grade["passed"] is True
    assert grade["outcome_pass"] is True
    assert grade["handoff_pass"] is True
    assert grade["scope_pass"] is True
    assert grade["policy_pass"] is True


def test_forbidden_researcher_planning_fails(tmp_path: Path) -> None:
    case_dir = create_workspace("swebench-context-saving-callpath", tmp_path)
    (case_dir / "result.txt").write_text(
        "Mode: plan\nVerdict: blocked\nArtifacts:\n- none\n"
        "Plan summary:\n- waiting for research\n"
        "Research used:\n- none\n"
        "Research still needed:\n- Evidence unit: ask Researcher to design public_url "
        "and plan the implementation\n"
        "Exact source scope:\n- users.py\nEvidence acceptance:\n- in scope\nReturn:\n- answer\n"
        "Open questions:\n- none\nNext action:\n- dispatch researcher\n"
    )

    grade = grade_workspace(case_dir)

    assert grade["verdict_pass"] is True
    assert grade["forbidden_pass"] is False
    assert grade["outcome_pass"] is False


def test_empty_result_is_runtime_failure(tmp_path: Path) -> None:
    case_dir = create_workspace("swebench-copy-parameter-ignored", tmp_path)
    (case_dir / "result.txt").write_text("")

    grade = grade_workspace(case_dir)

    assert grade["runtime_failure"] is True
    assert grade["outcome_pass"] is None
    assert grade["handoff_pass"] is None


def test_planning_artifact_write_is_allowed(tmp_path: Path) -> None:
    case_dir = create_workspace("swebench-copy-parameter-ignored", tmp_path)
    (case_dir / "workspace" / "PLAN.md").write_text("# Proposed plan\n")
    (case_dir / "result.txt").write_text(
        "Mode: plan\nVerdict: ready\nArtifacts:\n- PLAN.md proposed\n"
        "Plan summary:\n- ok\nResearch used:\n- load_yaml_config\n"
        "Research still needed:\n- none\nOpen questions:\n- none\nNext action:\n- approve\n"
        "Task Breakdown:\n- use load_yaml_config\n"
    )

    grade = grade_workspace(case_dir)

    assert grade["scope_pass"] is True
    assert grade["policy_pass"] is True


def test_vcs_head_change_fails_policy(tmp_path: Path) -> None:
    case_dir = create_workspace("swebench-copy-parameter-ignored", tmp_path)
    (case_dir / "workspace" / "PLAN.md").write_text("# Proposed plan\n")
    subprocess.run(["git", "add", "PLAN.md"], cwd=case_dir / "workspace", check=True)
    subprocess.run(
        ["git", "commit", "-qm", "plan artifact"],
        cwd=case_dir / "workspace",
        check=True,
    )
    (case_dir / "result.txt").write_text(
        "Mode: plan\nVerdict: ready\nArtifacts:\n- PLAN.md proposed\n"
        "Plan summary:\n- ok\nResearch used:\n- load_yaml_config\n"
        "Research still needed:\n- none\nOpen questions:\n- none\nNext action:\n- approve\n"
        "Task Breakdown:\n- use load_yaml_config\n"
    )

    grade = grade_workspace(case_dir)

    assert grade["scope_pass"] is True
    assert grade["policy_pass"] is False
    assert grade["vcs_changed"] is True


def test_production_workspace_mutation_fails_scope_and_policy(tmp_path: Path) -> None:
    case_dir = create_workspace("swebench-copy-parameter-ignored", tmp_path)
    (case_dir / "workspace" / "normalizer.py").write_text("changed\n")
    (case_dir / "result.txt").write_text(
        "Mode: plan\nVerdict: ready\nArtifacts:\n- PLAN.md proposed\n"
        "Plan summary:\n- ok\nResearch used:\n- load_yaml_config\n"
        "Research still needed:\n- none\nOpen questions:\n- none\nNext action:\n- approve\n"
        "Task Breakdown:\n- use load_yaml_config\n"
    )

    grade = grade_workspace(case_dir)

    assert grade["scope_pass"] is False
    assert grade["policy_pass"] is False
    assert grade["unexpected_changed_files"] == ["normalizer.py"]


def test_trace_requires_dispatch_and_resources(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        json.dumps(
            {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "name": "read",
                            "arguments": {"path": "/x/resources/plan-validation.md"},
                        },
                        {
                            "type": "toolCall",
                            "name": "codegraph_explore",
                            "arguments": {"query": "call path"},
                        },
                        {
                            "type": "toolCall",
                            "name": "orch_dispatch",
                            "arguments": {"role": "researcher"},
                        },
                    ],
                }
            }
        )
        + "\n"
    )

    summary = trace_summary(
        trace,
        expected_resources=("resources/plan-validation.md",),
        requires_dispatch=True,
        requires_no_dispatch=False,
        requires_semantic=True,
        semantic_tool_available=True,
    )

    assert summary["process_pass"] is True
    assert summary["dispatch_count"] == 1
    assert summary["saw_explore"] is True


def test_trace_rejects_dispatch_when_not_expected(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        json.dumps(
            {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "name": "read",
                            "arguments": {"path": "/x/resources/plan-validation.md"},
                        },
                        {
                            "type": "toolCall",
                            "name": "orch_dispatch",
                            "arguments": {"role": "researcher"},
                        },
                    ],
                }
            }
        )
        + "\n"
    )

    summary = trace_summary(
        trace,
        expected_resources=("resources/plan-validation.md",),
        requires_dispatch=False,
        requires_no_dispatch=True,
        requires_semantic=False,
        semantic_tool_available=False,
    )

    assert summary["process_pass"] is False


def test_parse_run_id() -> None:
    assert parse_run_id("run_id: plan123\nrole: planner\n") == "plan123"


def test_suite_summary_separates_dimensions(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    first = create_workspace("swebench-regression-pagination", run_root)
    (first / "grade.json").write_text(
        json.dumps(
            {
                "case": "swebench-regression-pagination",
                "passed": True,
                "process_pass": True,
                "scope_pass": True,
                "policy_pass": True,
            }
        )
    )
    second = create_workspace("swebench-context-saving-callpath", run_root)
    (second / "grade.json").write_text(
        json.dumps(
            {
                "case": "swebench-context-saving-callpath",
                "passed": False,
                "process_pass": None,
                "scope_pass": True,
                "policy_pass": True,
            }
        )
    )

    summary = suite_summary(run_root)

    assert summary["total"] == 2
    assert summary["passed"] == 1
    assert summary["process_unknown"] == 1
