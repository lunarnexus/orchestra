# ruff: noqa: E501
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from evals.verifier.eval_harness import (
    CASES,
    create_workspace,
    grade_workspace,
    parse_run_id,
    suite_summary,
    trace_summary,
)


def test_suite_covers_verifier_paths() -> None:
    assert set(CASES) == {
        "acceptance-pass",
        "behavior-fail",
        "missing-regression-fail",
        "ambiguous-blocker",
        "required-tool-blocker",
        "builder-claim-fail",
        "semantic-impact-fail",
        "baseline-failure-pass",
        "scope-creep-fail",
    }


def test_create_workspace_keeps_grader_hidden_and_candidate_visible(tmp_path: Path) -> None:
    case_dir = create_workspace("acceptance-pass", tmp_path)
    workspace = case_dir / "workspace"

    assert (workspace / "math_utils.py").is_file()
    assert subprocess.check_output(["git", "diff", "--name-only"], cwd=workspace, text=True).strip()
    assert not (workspace / "grade_config.json").exists()
    assert (case_dir / "hidden" / "grade_config.json").is_file()


def test_semantic_case_initializes_codegraph_when_available(tmp_path: Path) -> None:
    import shutil

    case_dir = create_workspace("semantic-impact-fail", tmp_path)
    config = json.loads((case_dir / "hidden" / "grade_config.json").read_text())

    assert config["semantic_tool_available"] is bool(shutil.which("codegraph"))
    if shutil.which("codegraph"):
        assert (case_dir / "workspace" / ".codegraph" / "codegraph.db").is_file()


def test_expected_verdict_and_unchanged_workspace_pass(tmp_path: Path) -> None:
    case_dir = create_workspace("ambiguous-blocker", tmp_path)
    (case_dir / "result.txt").write_text(
        "Mode: verify\nVerdict: blocked\nMissing checks:\n- rounding policy is undefined\n"
    )

    grade = grade_workspace(case_dir)

    assert grade["verdict_pass"] is True
    assert grade["policy_pass"] is True
    assert grade["passed"] is True


def test_markdown_heading_verdict_is_accepted(tmp_path: Path) -> None:
    case_dir = create_workspace("builder-claim-fail", tmp_path)
    (case_dir / "result.txt").write_text(
        "## Verdict: fail\n\nEvidence:\n- candidate test failed\n"
    )

    assert grade_workspace(case_dir)["verdict_pass"] is True


def test_bold_markdown_verdict_is_accepted(tmp_path: Path) -> None:
    case_dir = create_workspace("behavior-fail", tmp_path)
    for verdict_line in ("**Verdict:** fail", "Verdict: **fail**"):
        (case_dir / "result.txt").write_text(
            f"Mode: verify\n{verdict_line}\nEvidence:\n- slug behavior failed\n"
        )
        assert grade_workspace(case_dir)["verdict_pass"] is True


def test_wrong_verdict_fails(tmp_path: Path) -> None:
    case_dir = create_workspace("behavior-fail", tmp_path)
    (case_dir / "result.txt").write_text("Mode: verify\nVerdict: pass\n")

    grade = grade_workspace(case_dir)

    assert grade["verdict_pass"] is False
    assert grade["passed"] is False


def test_workspace_edit_fails_read_only_policy(tmp_path: Path) -> None:
    case_dir = create_workspace("acceptance-pass", tmp_path)
    (case_dir / "result.txt").write_text("Mode: verify\nVerdict: pass\n")
    (case_dir / "workspace" / "math_utils.py").write_text("def double(value):\n    return value * 3\n")

    grade = grade_workspace(case_dir)

    assert grade["policy_pass"] is False
    assert grade["passed"] is False


def test_required_result_evidence_is_graded(tmp_path: Path) -> None:
    case_dir = create_workspace("baseline-failure-pass", tmp_path)
    (case_dir / "result.txt").write_text("Mode: verify\nVerdict: pass\n")

    grade = grade_workspace(case_dir)

    assert grade["result_pass"] is False
    assert grade["passed"] is False


def test_result_evidence_accepts_equivalent_baseline_language(tmp_path: Path) -> None:
    case_dir = create_workspace("baseline-failure-pass", tmp_path)
    (case_dir / "result.txt").write_text(
        "Mode: verify\nVerdict: pass\nEvidence:\n- pre-existing test failure distinguished\n"
    )

    assert grade_workspace(case_dir)["result_pass"] is True


def test_actual_codegraph_call_passes_semantic_process_check(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        json.dumps(
            {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "name": "codegraph_explore",
                            "arguments": {"query": "trace profile_path impact"},
                        },
                        {"type": "toolCall", "name": "bash", "arguments": {"command": "pytest"}},
                    ],
                }
            }
        )
        + "\n"
    )

    summary = trace_summary(trace, requires_command=True, requires_semantic=True)

    assert summary["process_pass"] is True
    assert summary["saw_semantic"] is True
    assert summary["saw_codegraph"] is True
    assert summary["saw_explore"] is True


def test_codegraph_files_tracks_plugin_use_but_not_required_exploration(tmp_path: Path) -> None:
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
                        {"type": "toolCall", "name": "bash", "arguments": {"command": "pytest"}},
                    ],
                }
            }
        )
        + "\n"
    )

    summary = trace_summary(trace, requires_command=True, requires_semantic=True)

    assert summary["process_pass"] is False
    assert summary["saw_codegraph"] is True
    assert summary["saw_explore"] is False


def test_codegraph_text_in_tool_arguments_is_not_a_semantic_call(tmp_path: Path) -> None:
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
                            "arguments": {"command": "pytest /tmp/codegraph-regression"},
                        }
                    ],
                }
            }
        )
        + "\n"
    )

    summary = trace_summary(trace, requires_command=True, requires_semantic=True)

    assert summary["process_pass"] is False
    assert summary["saw_semantic"] is False
    assert summary["saw_codegraph"] is False


def test_missing_required_semantic_tool_call_fails_process(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        json.dumps(
            {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "toolCall", "name": "bash", "arguments": {"command": "pytest"}}
                    ],
                }
            }
        )
        + "\n"
    )

    summary = trace_summary(
        trace,
        requires_command=True,
        requires_semantic=True,
        semantic_tool_available=True,
    )

    assert summary["process_pass"] is False


def test_unavailable_semantic_tool_is_unknown(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        json.dumps(
            {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "toolCall", "name": "bash", "arguments": {"command": "pytest"}}
                    ],
                }
            }
        )
        + "\n"
    )

    summary = trace_summary(
        trace,
        requires_command=True,
        requires_semantic=True,
        semantic_tool_available=False,
    )

    assert summary["process_pass"] is None


def test_each_case_accepts_its_expected_verdict_and_evidence(tmp_path: Path) -> None:
    for case_id, case in CASES.items():
        case_dir = create_workspace(case_id, tmp_path)
        evidence_tokens = list(case.result_contains)
        evidence_tokens.extend(group[0] for group in case.result_contains_any)
        evidence = " ".join(evidence_tokens)
        (case_dir / "result.txt").write_text(
            f"Mode: verify\nVerdict: {case.expected_verdict}\nEvidence:\n- {evidence}\n"
        )
        assert grade_workspace(case_dir)["passed"] is True


def test_parse_run_id() -> None:
    assert parse_run_id("run_id: verify123\nrole: verifier\n") == "verify123"


def test_suite_summary_separates_dimensions(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    first = create_workspace("ambiguous-blocker", run_root)
    (first / "grade.json").write_text(
        json.dumps({"case": "ambiguous-blocker", "passed": True, "process_pass": None})
    )
    second = create_workspace("behavior-fail", run_root)
    (second / "grade.json").write_text(
        json.dumps({"case": "behavior-fail", "passed": False, "process_pass": False})
    )

    summary = suite_summary(run_root)

    assert summary == {
        "total": 2,
        "passed": 1,
        "failed": 1,
        "process_unknown": 1,
        "process_failed": 1,
        "cases": [
            {"case": "ambiguous-blocker", "passed": True, "process_pass": None},
            {"case": "behavior-fail", "passed": False, "process_pass": False},
        ],
    }
