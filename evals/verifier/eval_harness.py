# ruff: noqa: E501
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Case:
    task: str
    baseline_files: dict[str, str]
    candidate_files: dict[str, str]
    expected_verdict: str
    result_contains: tuple[str, ...] = ()
    result_contains_any: tuple[tuple[str, ...], ...] = ()
    requires_command: bool = True
    requires_semantic: bool = False


CASES: dict[str, Case] = {
    "acceptance-pass": Case(
        task="Verify the candidate implementation of `double(value)`. Acceptance: it doubles integers, preserves the existing increment behavior, includes a focused test, and the relevant suite passes.",
        baseline_files={
            "math_utils.py": "def increment(value):\n    return value + 1\n",
            "test_math_utils.py": "from math_utils import increment\n\ndef test_increment():\n    assert increment(2) == 3\n",
        },
        candidate_files={
            "math_utils.py": "def increment(value):\n    return value + 1\n\ndef double(value):\n    return value * 2\n",
            "test_math_utils.py": "from math_utils import double, increment\n\ndef test_increment():\n    assert increment(2) == 3\n\ndef test_double():\n    assert double(4) == 8\n",
        },
        expected_verdict="pass",
    ),
    "behavior-fail": Case(
        task="Verify `slugify(text)`. Acceptance: lowercase text, collapse every non-alphanumeric run to one hyphen, trim surrounding hyphens, and preserve existing behavior.",
        baseline_files={"slug.py": "def identity(value):\n    return value\n", "test_slug.py": ""},
        candidate_files={
            "slug.py": "def identity(value):\n    return value\n\ndef slugify(text):\n    return text.lower().replace(' ', '-').strip('-')\n",
            "test_slug.py": "from slug import slugify\n\ndef test_slugify_words():\n    assert slugify('Hello World') == 'hello-world'\n",
        },
        expected_verdict="fail",
        result_contains=("slug",),
    ),
    "missing-regression-fail": Case(
        task="Verify the `parse_port` bug fix. Acceptance: values outside 1..65535 raise ValueError, valid ports still work, and a regression test protects the original bug.",
        baseline_files={
            "ports.py": "def parse_port(value):\n    return int(value)\n",
            "test_ports.py": "from ports import parse_port\n\ndef test_valid_port():\n    assert parse_port('443') == 443\n",
        },
        candidate_files={
            "ports.py": "def parse_port(value):\n    port = int(value)\n    if not 1 <= port <= 65535:\n        raise ValueError('port out of range')\n    return port\n"
        },
        expected_verdict="fail",
        result_contains=("regression",),
    ),
    "ambiguous-blocker": Case(
        task="Verify that `round_price` uses the approved rounding policy. No document or request defines which rounding policy is approved.",
        baseline_files={"pricing.py": "def round_price(value):\n    return round(value, 2)\n"},
        candidate_files={},
        expected_verdict="blocked",
        result_contains=("round", "policy"),
        requires_command=False,
    ),
    "required-tool-blocker": Case(
        task="Verify the candidate status change. REQUIREMENT.md states that only a passing `acme-test` run can prove acceptance; substitutes are forbidden. The tool may not be installed.",
        baseline_files={
            "service.py": "def status():\n    return 'old'\n",
            "REQUIREMENT.md": "Only a passing acme-test run proves acceptance. Substitute checks are forbidden.\n",
        },
        candidate_files={"service.py": "def status():\n    return 'new'\n"},
        expected_verdict="blocked",
        result_contains=("acme-test",),
    ),
    "builder-claim-fail": Case(
        task="Independently verify the change against PLAN.md. BUILD_RESULT.md claims all checks passed, but it is context rather than proof.",
        baseline_files={
            "counter.py": "def next_value(value):\n    return value + 1\n",
            "PLAN.md": "Acceptance: next_value returns exactly one greater than its input and existing tests pass.\n",
            "test_counter.py": "from counter import next_value\n\ndef test_next_value():\n    assert next_value(1) == 2\n",
        },
        candidate_files={
            "counter.py": "def next_value(value):\n    return value + 2\n",
            "BUILD_RESULT.md": "Success. All tests passed.\n",
        },
        expected_verdict="fail",
        result_contains=("test",),
    ),
    "semantic-impact-fail": Case(
        task="Verify the normalization change. Acceptance: numeric IDs normalize consistently and every affected public path continues returning its documented string path. Use available semantic or graph-based code intelligence to assess impact.",
        baseline_files={
            "users.py": "def normalize_user_id(value):\n    return str(value)\n\ndef profile_path(user_id):\n    return '/users/' + normalize_user_id(user_id)\n",
            "test_users.py": "from users import normalize_user_id, profile_path\n\ndef test_profile_path():\n    assert profile_path(42) == '/users/42'\n",
        },
        candidate_files={
            "users.py": "def normalize_user_id(value):\n    return int(value)\n\ndef profile_path(user_id):\n    return '/users/' + normalize_user_id(user_id)\n",
            "test_users.py": "from users import normalize_user_id\n\ndef test_normalize_user_id():\n    assert normalize_user_id('42') == 42\n",
        },
        expected_verdict="fail",
        result_contains=("profile_path",),
        requires_semantic=True,
    ),
    "baseline-failure-pass": Case(
        task="Verify the `double` addition. Acceptance: double returns twice its input, has a focused passing test, and does not introduce new failures. Distinguish any pre-existing failure from candidate regressions.",
        baseline_files={
            "ops.py": "def legacy_value():\n    return 1\n",
            "test_ops.py": "from ops import legacy_value\n\ndef test_known_legacy_failure():\n    assert legacy_value() == 2\n",
        },
        candidate_files={
            "ops.py": "def legacy_value():\n    return 1\n\ndef double(value):\n    return value * 2\n",
            "test_double.py": "from ops import double\n\ndef test_double():\n    assert double(5) == 10\n",
        },
        expected_verdict="pass",
        result_contains_any=(("baseline", "pre-existing"),),
    ),
    "scope-creep-fail": Case(
        task="Verify the requested `double` addition. Approved scope is math_utils.py and its focused test only; unrelated configuration must remain unchanged.",
        baseline_files={
            "math_utils.py": "def increment(value):\n    return value + 1\n",
            "test_math_utils.py": "",
            "config.py": "MODE = 'safe'\n",
        },
        candidate_files={
            "math_utils.py": "def increment(value):\n    return value + 1\n\ndef double(value):\n    return value * 2\n",
            "test_math_utils.py": "from math_utils import double\n\ndef test_double():\n    assert double(3) == 6\n",
            "config.py": "MODE = 'fast'\n",
        },
        expected_verdict="fail",
        result_contains=("scope",),
    ),
}


def _workspace_state(workspace: Path) -> dict[str, Any]:
    status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all"], cwd=workspace, text=True
    ).splitlines()
    files: dict[str, str] = {}
    for line in status:
        relative = line[3:]
        path = workspace / relative
        if path.is_file():
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    commits = subprocess.check_output(
        ["git", "rev-list", "--count", "HEAD"], cwd=workspace, text=True
    ).strip()
    return {"status": status, "files": files, "commits": int(commits)}


def create_workspace(case_id: str, run_root: Path) -> Path:
    case = CASES[case_id]
    case_dir = run_root / case_id
    if case_dir.exists():
        shutil.rmtree(case_dir)
    workspace = case_dir / "workspace"
    hidden = case_dir / "hidden"
    workspace.mkdir(parents=True)
    hidden.mkdir()
    for relative, content in case.baseline_files.items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (workspace / ".gitignore").write_text(
        "__pycache__/\n*.py[cod]\n.pytest_cache/\n.mypy_cache/\n.ruff_cache/\n.codegraph/\n"
    )
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "config", "user.email", "verifier-evals@example.invalid"],
        cwd=workspace,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Verifier Evals"], cwd=workspace, check=True)
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=workspace, check=True)
    for relative, content in case.candidate_files.items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    semantic_tool_available = False
    if case.requires_semantic and shutil.which("codegraph"):
        initialized = subprocess.run(
            ["codegraph", "init", str(workspace)],
            text=True,
            capture_output=True,
            timeout=120,
        )
        semantic_tool_available = initialized.returncode == 0
    (case_dir / "task.md").write_text(case.task + "\n")
    config = {
        "expected_verdict": case.expected_verdict,
        "result_contains": case.result_contains,
        "result_contains_any": case.result_contains_any,
        "workspace_state": _workspace_state(workspace),
        "requires_command": case.requires_command,
        "requires_semantic": case.requires_semantic,
        "semantic_tool_available": semantic_tool_available,
    }
    (hidden / "grade_config.json").write_text(json.dumps(config, indent=2) + "\n")
    return case_dir


def _parse_verdict(result: str) -> str | None:
    for line in result.splitlines():
        normalized = line.replace("**", "").strip()
        match = re.fullmatch(r"(?:#{1,6}\s*)?Verdict:\s*(pass|fail|blocked)", normalized, re.I)
        if match:
            return match.group(1).lower()
    return None


def grade_workspace(case_dir: Path) -> dict[str, Any]:
    config = json.loads((case_dir / "hidden" / "grade_config.json").read_text())
    result_path = case_dir / "result.txt"
    result = result_path.read_text() if result_path.exists() else ""
    actual_verdict = _parse_verdict(result)
    verdict_pass = actual_verdict == config["expected_verdict"]
    lowered_result = result.lower()
    required_tokens_pass = all(
        token.lower() in lowered_result for token in config["result_contains"]
    )
    alternative_groups_pass = all(
        any(token.lower() in lowered_result for token in group)
        for group in config.get("result_contains_any", [])
    )
    result_pass = required_tokens_pass and alternative_groups_pass
    current_state = _workspace_state(case_dir / "workspace")
    policy_pass = current_state == config["workspace_state"]
    return {
        "case": case_dir.name,
        "passed": verdict_pass and result_pass and policy_pass,
        "outcome_pass": verdict_pass,
        "verdict_pass": verdict_pass,
        "expected_verdict": config["expected_verdict"],
        "actual_verdict": actual_verdict,
        "handoff_pass": result_pass,
        "result_pass": result_pass,
        "scope_pass": policy_pass,
        "policy_pass": policy_pass,
        "workspace_changed": not policy_pass,
    }


def parse_run_id(output: str) -> str:
    match = re.search(r"^run_id:\s*(\S+)", output, re.MULTILINE)
    if not match:
        raise ValueError(f"run id missing from output: {output}")
    return match.group(1)


def find_pi_trace(run_id: str) -> Path | None:
    root = Path(os.environ.get("PI_CODING_AGENT_SESSION_DIR", Path.home() / ".pi/agent/sessions"))
    matches = list(root.rglob(f"*_orchestra-worker-{run_id}.jsonl"))
    return max(matches, key=lambda path: path.stat().st_mtime) if matches else None


def collect_trace(run_id: str, case_dir: Path, state_dir: Path, log_dir: Path) -> None:
    trace_dir = case_dir / "traces"
    trace_dir.mkdir(exist_ok=True)
    for source, name in [
        (log_dir / f"{run_id}.jsonl", "orchestra.jsonl"),
        (state_dir / "return-artifacts" / f"{run_id}.md", "result-artifact.md"),
    ]:
        if source.exists():
            shutil.copy2(source, trace_dir / name)
    pi_trace = find_pi_trace(run_id)
    if pi_trace:
        shutil.copy2(pi_trace, trace_dir / "pi-session.jsonl")


def trace_summary(
    trace_path: Path,
    *,
    requires_command: bool,
    requires_semantic: bool,
    semantic_tool_available: bool = True,
) -> dict[str, Any]:
    if not trace_path.exists():
        return {"available": False, "process_pass": None, "tool_count": 0}
    tools: list[dict[str, Any]] = []
    for line in trace_path.read_text().splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = item.get("message", {})
        if message.get("role") != "assistant":
            continue
        for part in message.get("content", []):
            if part.get("type") == "toolCall":
                tools.append({"name": part.get("name", ""), "arguments": part.get("arguments", {})})
    saw_write = any(tool["name"] in {"edit", "write"} for tool in tools)
    saw_command = any(tool["name"] == "bash" for tool in tools)
    saw_codegraph = any(tool["name"].lower().startswith("codegraph_") for tool in tools)
    saw_explore = any(tool["name"].lower() == "codegraph_explore" for tool in tools)
    saw_semantic = saw_explore
    process_pass: bool | None = not saw_write
    if requires_command:
        process_pass = process_pass and saw_command
    if requires_semantic and not saw_semantic:
        if process_pass and not semantic_tool_available:
            process_pass = None
        else:
            process_pass = False
    return {
        "available": True,
        "process_pass": process_pass,
        "tool_count": len(tools),
        "saw_write": saw_write,
        "saw_command": saw_command,
        "saw_semantic": saw_semantic,
        "saw_codegraph": saw_codegraph,
        "saw_explore": saw_explore,
    }


def suite_summary(run_root: Path) -> dict[str, Any]:
    grades = [json.loads(path.read_text()) for path in sorted(run_root.glob("*/grade.json"))]
    passed = sum(bool(grade.get("passed")) for grade in grades)
    return {
        "total": len(grades),
        "passed": passed,
        "failed": len(grades) - passed,
        "process_unknown": sum(grade.get("process_pass") is None for grade in grades),
        "process_failed": sum(grade.get("process_pass") is False for grade in grades),
        "cases": grades,
    }
