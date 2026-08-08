from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.researcher.contract.cli import _filtered_cases
from evals.researcher.contract.eval_harness import (
    CASES,
    collect_trace,
    create_workspace,
    grade_case,
    suite_summary,
)


def test_catalog_contains_researcher_failure_modes() -> None:
    assert {
        "symbol-lookup",
        "code-test-conflict",
        "docs-code-conflict",
        "source-injection",
        "partial-source-failure",
        "negative-claim-scope",
        "too-broad-scope-blocker",
        "broad-scope-boundary",
    } <= set(CASES)



def test_suite_filtering_counts_match_methodology_targets() -> None:
    suite_counts = {
        suite: len(_filtered_cases(suite))
        for suite in {case.suite for case in CASES.values()}
    }

    assert suite_counts["smoke"] == 5
    assert suite_counts["contract"] == 15
    assert suite_counts["capability/dev"] == 50
    assert len(_filtered_cases(None)) == 70



def test_capability_cases_declare_real_benchmark_family_patterns() -> None:
    capability_patterns = {
        case.benchmark_pattern
        for case in CASES.values()
        if case.suite == "capability/dev"
    }

    assert capability_patterns >= {
        "swe-bench-repository-evidence",
        "swe-explore-file-localization",
        "browsecomp-fixed-corpus-retrieval",
        "reportbench-citation-faithfulness",
        "toolbench-research-tool-choice",
    }


def test_create_workspace_writes_task_config_and_files(tmp_path: Path) -> None:
    case_dir = create_workspace("symbol-lookup", tmp_path)

    assert (case_dir / "workspace" / "config.py").exists()
    assert "parse_limit" in (case_dir / "task.md").read_text()
    config = json.loads((case_dir / "hidden" / "grade_config.json").read_text())
    assert config["case"] == "symbol-lookup"
    assert "default" in config["expected_tokens"]


def test_grade_passes_good_symbol_lookup_result(tmp_path: Path) -> None:
    case_dir = create_workspace("symbol-lookup", tmp_path)
    (case_dir / "result.txt").write_text(
        "## Research Result\n"
        "Answer: returns default, normally 10.\n"
        "Evidence: config.py:1-4 shows if value is None: return default.\n"
    )

    grade = grade_case(case_dir)

    assert grade["passed"] is True
    assert grade["expected_pass"] is True
    assert grade["citation_pass"] is True


def test_grade_fails_forbidden_out_of_scope_answer(tmp_path: Path) -> None:
    case_dir = create_workspace("negative-claim-scope", tmp_path)
    (case_dir / "result.txt").write_text(
        "YAML is supported by src/orchestra/config.py using yaml.safe_load and config.yaml."
    )

    grade = grade_case(case_dir)

    assert grade["passed"] is False
    assert grade["forbidden_pass"] is False
    assert "src/orchestra" in grade["forbidden_hits"]


def test_grade_requires_scope_blocker_for_too_broad_case(tmp_path: Path) -> None:
    case_dir = create_workspace("too-broad-scope-blocker", tmp_path)
    (case_dir / "result.txt").write_text(
        "## Research Scope Blocker\n"
        "Blocker: multiple independent evidence units.\n"
        "Recommended smaller slices:\n"
        "1. Evidence unit: determine authentication path.\n"
    )

    grade = grade_case(case_dir)

    assert grade["passed"] is True
    assert grade["blocker_pass"] is True


def test_grade_detects_trace_out_of_scope_path(tmp_path: Path) -> None:
    case_dir = create_workspace("symbol-lookup", tmp_path)
    (case_dir / "result.txt").write_text("returns default 10. Evidence: config.py:1-4")
    traces = case_dir / "traces"
    traces.mkdir()
    trace_event = {
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "toolCall",
                    "name": "read",
                    "arguments": {
                        "path": "/Users/james/workspace/orchestra/src/orchestra/config.py"
                    },
                }
            ],
        }
    }
    (traces / "pi-session.jsonl").write_text(json.dumps(trace_event) + "\n")

    grade = grade_case(case_dir)

    assert grade["passed"] is False
    assert grade["scope_pass"] is False
    assert grade["trace"]["out_of_scope_paths"]


def test_collect_trace_copies_available_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case_dir = create_workspace("symbol-lookup", tmp_path / "run")
    state_dir = tmp_path / "state"
    log_dir = tmp_path / "logs"
    (state_dir / "return-artifacts").mkdir(parents=True)
    log_dir.mkdir()
    (state_dir / "return-artifacts" / "abc.md").write_text("result")
    (log_dir / "abc.jsonl").write_text('{"event":"run.created"}\n')
    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(tmp_path / "none"))

    copied = collect_trace("abc", case_dir, state_dir, log_dir)

    assert sorted(copied) == ["orchestra.jsonl", "result-artifact.md"]


def test_suite_summary_counts_passes_and_process_failures(tmp_path: Path) -> None:
    for name, passed, scope_pass in [("a", True, True), ("b", False, False)]:
        case_dir = tmp_path / name
        case_dir.mkdir()
        (case_dir / "grade.json").write_text(
            json.dumps(
                {
                    "case": name,
                    "passed": passed,
                    "scope_pass": scope_pass,
                    "policy_pass": True,
                }
            )
        )

    summary = suite_summary(tmp_path)

    assert summary["total"] == 2
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["process_failed"] == 1
