from __future__ import annotations

import json
from pathlib import Path

from evals.builder.eval_harness import (
    CASES,
    EXPECTED_RESOURCES,
    TDD_TRACE_CASES,
    create_workspace,
    grade_resource_loading,
    grade_workspace,
    parse_run_id,
    suite_summary,
)

ORCHESTRA_ROOT = Path(__file__).resolve().parents[3]


def test_suite_has_one_case_for_each_builder_path() -> None:
    expected = {
        "feature-tdd",
        "bugfix-regression",
        "refactor-characterization",
        "systematic-debugging",
        "ambiguous-blocker",
        "dirty-file-safety",
        "test-unavailable-blocker",
        "spike",
        "dependency-change",
        "schema-migration",
        "security-sensitive",
        "concurrency-state",
        "external-integration",
        "performance-work",
        "flaky-test",
        "commit-handoff",
    }
    assert set(CASES) == expected


def test_all_hidden_verifiers_compile() -> None:
    for case in CASES.values():
        compile(case.verifier, "<hidden-builder-verifier>", "exec")


def test_create_workspace_does_not_materialize_hidden_verifier(tmp_path: Path) -> None:
    case_dir = create_workspace("feature-tdd", tmp_path)
    assert (case_dir / "workspace" / "app.py").is_file()
    assert not (case_dir / "workspace" / "verify.py").exists()
    assert not (case_dir / "hidden").exists()
    assert not list(case_dir.rglob("verify.py"))
    assert (case_dir / "task.md").is_file()


def test_grade_workspace_runs_hidden_verifier_without_leaving_it_in_run(tmp_path: Path) -> None:
    case_dir = create_workspace("ambiguous-blocker", tmp_path)
    result_file = case_dir / "result.txt"
    result_file.write_text("Blocker: missing rounding policy\n")
    grade = grade_workspace(case_dir)
    assert grade["functional_pass"] is True
    assert grade["result_pass"] is True
    assert grade["git_policy_pass"] is True
    assert grade["passed"] is True
    assert not list(case_dir.rglob("verify.py"))


def test_empty_result_is_runtime_failure_and_skips_behavioral_grading(tmp_path: Path) -> None:
    case_dir = create_workspace("feature-tdd", tmp_path)
    (case_dir / "result.txt").write_text("   \n")

    grade = grade_workspace(case_dir)

    assert grade["passed"] is False
    assert grade["process_pass"] is False
    assert grade["runtime_error"] == "empty worker result"
    assert grade["functional_pass"] is None
    assert grade["result_pass"] is None


def test_unauthorized_commit_fails_policy_grade(tmp_path: Path) -> None:
    case_dir = create_workspace("feature-tdd", tmp_path)
    workspace = case_dir / "workspace"
    (workspace / "extra.py").write_text("VALUE = 1\n")
    import subprocess

    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-qm", "unauthorized"], cwd=workspace, check=True)
    grade = grade_workspace(case_dir)
    assert grade["git_policy_pass"] is False
    assert grade["passed"] is False


def test_unexpected_untracked_artifact_fails_scope_grade(tmp_path: Path) -> None:
    case_dir = create_workspace("ambiguous-blocker", tmp_path)
    (case_dir / "result.txt").write_text("Blocker: missing rounding policy\n")
    (case_dir / "workspace" / "debug.log").write_text("temporary diagnostics\n")
    grade = grade_workspace(case_dir)
    assert grade["scope_policy_pass"] is False
    assert grade["unexpected_untracked"] == ["debug.log"]
    assert grade["passed"] is False


def test_ignored_runtime_cache_does_not_fail_scope_grade(tmp_path: Path) -> None:
    case_dir = create_workspace("ambiguous-blocker", tmp_path)
    (case_dir / "result.txt").write_text("Blocker: missing rounding policy\n")
    cache = case_dir / "workspace" / "__pycache__"
    cache.mkdir()
    (cache / "module.pyc").write_bytes(b"cache")
    grade = grade_workspace(case_dir)
    assert grade["scope_policy_pass"] is True


def test_bugfix_verifier_grades_behavior_not_test_names(tmp_path: Path) -> None:
    case_dir = create_workspace("bugfix-regression", tmp_path)
    workspace = case_dir / "workspace"
    (workspace / "ports.py").write_text(
        "def parse_port(value):\n"
        "    port = int(value)\n"
        "    if not 1 <= port <= 65535:\n"
        "        raise ValueError(port)\n"
        "    return port\n"
    )
    (workspace / "test_ports.py").write_text(
        "import pytest\nfrom ports import parse_port\n\n"
        "def test_bounds():\n"
        "    with pytest.raises(ValueError): parse_port('0')\n"
        "    with pytest.raises(ValueError): parse_port('65536')\n"
    )
    assert grade_workspace(case_dir)["functional_pass"] is True


def test_security_verifier_accepts_safe_no_match_denial(tmp_path: Path) -> None:
    case_dir = create_workspace("security-sensitive", tmp_path)
    workspace = case_dir / "workspace"
    (workspace / "files.py").write_text(
        "from pathlib import Path\n\n"
        "def list_named(directory, name):\n"
        "    return [p for p in Path(directory).iterdir() if p.name == name]\n"
    )
    (workspace / "test_files.py").write_text("def test_denial(): pass\n")
    assert grade_workspace(case_dir)["functional_pass"] is True


def test_resource_loading_grade_requires_all_resources_before_mutation() -> None:
    expected = (
        "resources/security-sensitive-code.md",
        "resources/concurrency-and-state.md",
    )
    tools = [
        {"name": "read", "arguments": {"path": f"/portable/builder/{path}"}}
        for path in expected
    ]
    tools.append({"name": "edit", "arguments": {"path": "/workspace/files.py"}})

    assert grade_resource_loading(tools, expected) == {
        "pass": True,
        "missing": [],
        "late": [],
    }


def test_resource_loading_grade_rejects_missing_and_late_resources() -> None:
    expected = ("resources/security-sensitive-code.md", "resources/concurrency-and-state.md")
    tools = [
        {"name": "read", "arguments": {"path": "/builder/resources/security-sensitive-code.md"}},
        {"name": "write", "arguments": {"path": "/workspace/test_app.py"}},
        {"name": "read", "arguments": {"path": "/builder/resources/concurrency-and-state.md"}},
    ]

    assert grade_resource_loading(tools, expected) == {
        "pass": False,
        "missing": [],
        "late": ["resources/concurrency-and-state.md"],
    }
    assert grade_resource_loading(tools[:2], expected) == {
        "pass": False,
        "missing": ["resources/concurrency-and-state.md"],
        "late": [],
    }


def test_only_conditional_methods_require_resource_reads() -> None:
    assert "feature-tdd" not in EXPECTED_RESOURCES
    assert "dirty-file-safety" not in EXPECTED_RESOURCES
    assert "test-unavailable-blocker" not in EXPECTED_RESOURCES
    assert "bugfix-regression" not in EXPECTED_RESOURCES
    assert EXPECTED_RESOURCES["flaky-test"] == ("resources/flaky-tests.md",)
    assert EXPECTED_RESOURCES["security-sensitive"] == (
        "resources/security-sensitive-code.md",
    )
    assert "feature-tdd" in TDD_TRACE_CASES
    assert "test-unavailable-blocker" not in TDD_TRACE_CASES


def test_dependency_case_tests_approved_bounded_implementation() -> None:
    case = CASES["dependency-change"]
    assert "approved `orjson`" in case.task
    assert "bounded authoritative lookup" in case.task
    assert "pyproject.toml" in case.files
    assert "test_codec.py" in case.files
    assert case.result_contains == ()


def test_spike_task_names_required_scratch_directory() -> None:
    assert "under the `spike/` directory" in CASES["spike"].task
    assert "do not create scratch files at repository root" in CASES["spike"].task.lower()


def test_builder_method_gate_and_stop_conditions_are_explicit() -> None:
    skill_root = ORCHESTRA_ROOT / "skills" / "builder"
    skill = (skill_root / "SKILL.md").read_text()
    dependency = (skill_root / "resources" / "dependency-changes.md").read_text()
    spikes = (skill_root / "resources" / "spikes.md").read_text()

    assert "Applicable resources define the current method and are mandatory" in skill
    assert "unclear root cause, uncertain reproduction, unexpected failure" in skill
    assert "read-only orientation" in skill.lower()
    assert "before the first related" in skill.lower()
    assert "Test observable behavior and contracts" in skill
    assert "Derive expected values independently" in skill
    assert "keep tests deterministic" in skill.lower()
    assert "Resolve small factual gaps from authoritative sources" in dependency
    assert "substantive comparison or an unapproved decision" in dependency
    assert "Use the assigned scratch path exactly" in spikes
    assert "return a blocker instead of inventing one" in spikes


def test_parse_run_id() -> None:
    output = "run_id: abc123\nstatus: queued\nrole: builder\n"
    assert parse_run_id(output) == "abc123"


def test_suite_summary_counts_passes(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    first = create_workspace("ambiguous-blocker", run_root)
    (first / "result.txt").write_text("Blocker: missing rounding policy\n")
    (first / "grade.json").write_text(json.dumps(grade_workspace(first)))
    second = create_workspace("feature-tdd", run_root)
    (second / "grade.json").write_text(json.dumps({"case": "feature-tdd", "passed": False}))
    summary = suite_summary(run_root)
    assert summary["total"] == 2
    assert summary["passed"] == 1
    assert summary["failed"] == 1
