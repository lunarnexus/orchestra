# ruff: noqa: E501

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from evals.appsec.cli import parse_run_id
from evals.appsec.eval_harness import (
    CASES,
    create_workspace,
    grade_workspace,
    suite_summary,
    trace_summary,
)


def test_appsec_resource_triggers_are_concrete_and_bounded() -> None:
    skill = (Path(__file__).parents[3] / "skills" / "appsec" / "SKILL.md").read_text()

    assert "attacker capability" in skill
    assert "trust boundary" in skill
    assert "active exploitation" in skill


def test_suite_covers_appsec_judgment_and_resources() -> None:
    assert set(CASES) == {
        "clean-pass",
        "authorization-fail",
        "authorization-safe-pass",
        "command-injection-fail",
        "shell-safe-pass",
        "path-traversal-fail",
        "ssrf-fail",
        "secret-leak-fail",
        "dependency-integrity-fail",
        "agent-tool-boundary-fail",
        "prompt-data-safe-pass",
        "memory-poisoning-fail",
        "inert-example-pass",
        "missing-target-blocked",
    }
    resources = {resource for case in CASES.values() for resource in case.expected_resources}
    assert resources == {
        "resources/authorization-and-identity.md",
        "resources/untrusted-input-and-sinks.md",
        "resources/secrets-and-sensitive-data.md",
        "resources/dependencies-and-integrity.md",
        "resources/agent-and-tool-boundaries.md",
        "resources/finding-validation.md",
    }
    assert sum(case.expected_verdict == "pass" for case in CASES.values()) >= 5
    assert sum(case.expected_verdict == "fail" for case in CASES.values()) >= 7
    assert sum(case.requires_semantic for case in CASES.values()) >= 3


def test_create_workspace_hides_grader_and_exposes_candidate_diff(tmp_path: Path) -> None:
    case_dir = create_workspace("authorization-fail", tmp_path)
    workspace = case_dir / "workspace"

    assert (case_dir / "hidden" / "grade_config.json").is_file()
    assert not (workspace / "hidden").exists()
    assert subprocess.check_output(
        ["git", "diff", "--name-only"], cwd=workspace, text=True
    ).strip()


def test_all_cases_preserve_hidden_config_outside_workspace(tmp_path: Path) -> None:
    for name in CASES:
        case_dir = create_workspace(name, tmp_path)
        assert (case_dir / "hidden" / "grade_config.json").is_file()
        assert not (case_dir / "workspace" / "grade_config.json").exists()


def test_expected_verdict_and_read_only_workspace_pass(tmp_path: Path) -> None:
    case_dir = create_workspace("authorization-fail", tmp_path)
    (case_dir / "result.txt").write_text(
        "Mode: appsec\nVerdict: fail\nIntent: preserve document ownership\nAttack surface:\n"
        "- document lookup and owner check\nFindings:\n"
        "- HIGH `docs.py:2` — owner authorization removed — restore ownership check\n"
        "Security evidence:\n- direct object lookup\nResidual risk:\n- none identified\n"
        "Readiness: not security-ready\n"
    )

    grade = grade_workspace(case_dir)

    assert grade["outcome_pass"] is True
    assert grade["scope_pass"] is True
    assert grade["policy_pass"] is True
    assert grade["handoff_pass"] is True
    assert grade["passed"] is True


def test_fail_verdict_requires_security_contract_and_finding_evidence(tmp_path: Path) -> None:
    case_dir = create_workspace("authorization-fail", tmp_path)
    (case_dir / "result.txt").write_text(
        "Mode: appsec\nVerdict: fail\nAttack surface:\n- document lookup\n"
        "Readiness: not security-ready\nowner authorization\n"
    )

    grade = grade_workspace(case_dir)

    assert grade["outcome_pass"] is True
    assert grade["handoff_pass"] is False


def test_wrong_verdict_fails(tmp_path: Path) -> None:
    case_dir = create_workspace("authorization-fail", tmp_path)
    (case_dir / "result.txt").write_text("Mode: review\nVerdict: pass\nReadiness: ready\n")

    grade = grade_workspace(case_dir)

    assert grade["outcome_pass"] is False
    assert grade["passed"] is False


def test_ignored_runtime_artifacts_do_not_fail_scope(tmp_path: Path) -> None:
    case_dir = create_workspace("clean-pass", tmp_path)
    cache = case_dir / "workspace" / "__pycache__"
    cache.mkdir()
    (cache / "format_name.pyc").write_bytes(b"runtime cache")
    (case_dir / "result.txt").write_text(
        "Mode: review\nVerdict: pass\nCoverage:\n- files\nReadiness: ready\n"
    )

    grade = grade_workspace(case_dir)

    assert grade["scope_pass"] is True
    assert grade["policy_pass"] is True


def test_workspace_mutation_fails_scope_and_policy(tmp_path: Path) -> None:
    case_dir = create_workspace("clean-pass", tmp_path)
    (case_dir / "workspace" / "format_name.py").write_text("BROKEN = True\n")
    (case_dir / "result.txt").write_text("Mode: review\nVerdict: pass\nReadiness: ready\n")

    grade = grade_workspace(case_dir)

    assert grade["scope_pass"] is False
    assert grade["policy_pass"] is False


def test_missing_required_evidence_token_fails_handoff(tmp_path: Path) -> None:
    case_dir = create_workspace("command-injection-fail", tmp_path)
    (case_dir / "result.txt").write_text(
        "Mode: review\nVerdict: fail\nCoverage:\n- files\n"
        "Findings:\n- MEDIUM — `service.py:2` — unclear issue\nReadiness: not ready\n"
    )

    grade = grade_workspace(case_dir)

    assert grade["handoff_pass"] is False


def test_trace_requires_expected_resource_reads(tmp_path: Path) -> None:
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
                            "arguments": {"path": "/repo/skills/appsec/resources/test-quality.md"},
                        },
                        {
                            "type": "toolCall",
                            "name": "bash",
                            "arguments": {"command": "git diff -- src.py test_src.py"},
                        },
                    ],
                }
            }
        )
        + "\n"
    )

    summary = trace_summary(
        trace,
        expected_resources=("resources/test-quality.md",),
        requires_semantic=False,
        semantic_tool_available=False,
    )

    assert summary["process_pass"] is True
    assert summary["saw_diff"] is True
    assert summary["missing_resources"] == []


def test_trace_recognizes_git_c_diff_form(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        json.dumps(
            {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "name": "bash",
                            "arguments": {"command": "git -C /tmp/workspace diff --stat"},
                        }
                    ],
                }
            }
        )
        + "\n"
    )

    summary = trace_summary(
        trace,
        expected_resources=(),
        requires_semantic=False,
        semantic_tool_available=False,
    )

    assert summary["saw_diff"] is True
    assert summary["process_pass"] is True


def test_trace_detects_missing_resource_and_write(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        json.dumps(
            {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "toolCall", "name": "write", "arguments": {"path": "src.py"}},
                        {
                            "type": "toolCall",
                            "name": "bash",
                            "arguments": {"command": "git diff"},
                        },
                    ],
                }
            }
        )
        + "\n"
    )

    summary = trace_summary(
        trace,
        expected_resources=("resources/finding-validation.md",),
        requires_semantic=False,
        semantic_tool_available=False,
    )

    assert summary["process_pass"] is False
    assert summary["saw_write"] is True
    assert summary["missing_resources"] == ["resources/finding-validation.md"]


def test_semantic_case_requires_actual_explore_call(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        json.dumps(
            {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "name": "codegraph_files",
                            "arguments": {"path": "/tmp/workspace"},
                        },
                        {
                            "type": "toolCall",
                            "name": "bash",
                            "arguments": {"command": "git diff /tmp/codegraph-review"},
                        },
                    ],
                }
            }
        )
        + "\n"
    )

    summary = trace_summary(
        trace,
        expected_resources=(),
        requires_semantic=True,
        semantic_tool_available=True,
    )

    assert summary["saw_codegraph"] is True
    assert summary["saw_explore"] is False
    assert summary["process_pass"] is False


def test_unavailable_semantic_tool_is_unknown_when_other_process_passes(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        json.dumps(
            {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "name": "bash",
                            "arguments": {"command": "git diff"},
                        }
                    ],
                }
            }
        )
        + "\n"
    )

    summary = trace_summary(
        trace,
        expected_resources=(),
        requires_semantic=True,
        semantic_tool_available=False,
    )

    assert summary["process_pass"] is None


def test_parse_run_id() -> None:
    assert parse_run_id("run_id: review123\nrole: appsec\n") == "review123"


def test_suite_summary_separates_dimensions(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    first = create_workspace("clean-pass", run_root)
    (first / "grade.json").write_text(
        json.dumps(
            {
                "case": "clean-pass",
                "passed": True,
                "process_pass": True,
                "scope_pass": True,
                "policy_pass": True,
            }
        )
    )
    second = create_workspace("authorization-fail", run_root)
    (second / "grade.json").write_text(
        json.dumps(
            {
                "case": "authorization-fail",
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
