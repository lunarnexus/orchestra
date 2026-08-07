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


@dataclass(frozen=True)
class Case:
    task: str
    baseline_files: dict[str, str]
    candidate_files: dict[str, str]
    expected_verdict: str
    result_contains: tuple[str, ...] = ()
    result_contains_any: tuple[tuple[str, ...], ...] = ()
    expected_resources: tuple[str, ...] = ()
    requires_semantic: bool = False
    requires_diff: bool = True


FINDING_VALIDATION = "resources/finding-validation.md"

CASES: dict[str, Case] = {
    "simple-pass": Case(
        task="Review the focused name-formatting addition. The project is a small local utility; judge current correctness, maintainability, scope, tests, and merge readiness without proposing speculative flexibility.",
        baseline_files={
            "format_name.py": "def trim(value):\n    return value.strip()\n",
            "test_format_name.py": "from format_name import trim\n\ndef test_trim():\n    assert trim(' Ada ') == 'Ada'\n",
            "AGENTS.md": "Keep utilities direct. Add abstraction only for multiple current consumers.\n",
        },
        candidate_files={
            "format_name.py": "def trim(value):\n    return value.strip()\n\ndef format_name(first, last):\n    return f'{first.strip()} {last.strip()}'\n",
            "test_format_name.py": "from format_name import format_name, trim\n\ndef test_trim():\n    assert trim(' Ada ') == 'Ada'\n\ndef test_format_name():\n    assert format_name(' Ada ', ' Lovelace ') == 'Ada Lovelace'\n",
        },
        expected_verdict="pass",
        expected_resources=("resources/test-quality.md",),
    ),
    "correctness-fail": Case(
        task="Review the discount calculation change for merge readiness. The total must subtract the discount from the subtotal.",
        baseline_files={
            "totals.py": "def total(subtotal):\n    return subtotal\n",
            "test_totals.py": "from totals import total\n\ndef test_total():\n    assert total(10) == 10\n",
        },
        candidate_files={
            "totals.py": "def total(subtotal, discount=0):\n    return subtotal + discount\n",
            "test_totals.py": "from totals import total\n\ndef test_total_without_discount():\n    assert total(10) == 10\n",
        },
        expected_verdict="fail",
        result_contains=("discount",),
        expected_resources=("resources/test-quality.md", FINDING_VALIDATION),
    ),
    "overengineering-fail": Case(
        task="Review a small MVP change that only needs `is_enabled(config)` to read the current `enabled` boolean. New framework machinery is not approved.",
        baseline_files={"flags.py": "def is_enabled(config):\n    return False\n", "test_flags.py": ""},
        candidate_files={
            "flags.py": "class FlagProvider:\n    def get(self, config):\n        raise NotImplementedError\n\nclass MappingFlagProvider(FlagProvider):\n    def get(self, config):\n        return bool(config.get('enabled', False))\n\nclass FlagRegistry:\n    def __init__(self):\n        self.providers = {'mapping': MappingFlagProvider()}\n\n    def resolve(self, name):\n        return self.providers[name]\n\n_registry = FlagRegistry()\n\ndef is_enabled(config):\n    return _registry.resolve('mapping').get(config)\n",
            "test_flags.py": "from flags import is_enabled\n\ndef test_enabled():\n    assert is_enabled({'enabled': True}) is True\n",
        },
        expected_verdict="fail",
        result_contains_any=(("scope", "abstraction", "complex"),),
        expected_resources=("resources/simplicity-and-scope.md", FINDING_VALIDATION),
    ),
    "justified-abstraction-pass": Case(
        task="Review the parser extraction. Two current production consumers need identical validated integer parsing; the project instruction prefers one shared helper for identical contracts.",
        baseline_files={
            "ports.py": "def parse_port(value):\n    return int(value)\n",
            "workers.py": "def parse_workers(value):\n    return int(value)\n",
            "AGENTS.md": "Share an existing helper when multiple current consumers have the same contract.\n",
        },
        candidate_files={
            "parsing.py": "def parse_positive_int(value):\n    parsed = int(value)\n    if parsed < 1:\n        raise ValueError('must be positive')\n    return parsed\n",
            "ports.py": "from parsing import parse_positive_int\n\ndef parse_port(value):\n    return parse_positive_int(value)\n",
            "workers.py": "from parsing import parse_positive_int\n\ndef parse_workers(value):\n    return parse_positive_int(value)\n",
            "test_parsing.py": "import pytest\nfrom ports import parse_port\nfrom workers import parse_workers\n\ndef test_consumers_share_positive_contract():\n    assert parse_port('80') == 80\n    assert parse_workers('2') == 2\n    for parser in (parse_port, parse_workers):\n        with pytest.raises(ValueError):\n            parser('0')\n",
        },
        expected_verdict="pass",
        expected_resources=(
            "resources/simplicity-and-scope.md",
            "resources/test-quality.md",
        ),
    ),
    "harmful-convention-fail": Case(
        task="Review the loader addition. AGENTS.md requires configuration errors to remain actionable even though one legacy helper silently returns None.",
        baseline_files={
            "loaders.py": "def legacy_load(path):\n    try:\n        return open(path).read()\n    except OSError:\n        return None\n",
            "AGENTS.md": "New configuration loaders must raise an actionable error with the path; do not copy legacy silent failure.\n",
        },
        candidate_files={
            "loaders.py": "def legacy_load(path):\n    try:\n        return open(path).read()\n    except OSError:\n        return None\n\ndef load_config(path):\n    try:\n        return open(path).read()\n    except OSError:\n        return None\n",
            "test_loaders.py": "from loaders import load_config\n\ndef test_missing_returns_none(tmp_path):\n    assert load_config(tmp_path / 'missing') is None\n",
        },
        expected_verdict="fail",
        result_contains_any=(("error", "silent", "actionable"),),
        expected_resources=(
            "resources/conventions-and-project-fit.md",
            "resources/test-quality.md",
            FINDING_VALIDATION,
        ),
    ),
    "project-fit-pass": Case(
        task="Review this small command lookup. Nearby legacy code uses one-letter names, but AGENTS.md requires intention-revealing names in new code. Do not demand consistency with a harmful legacy convention.",
        baseline_files={
            "legacy.py": "def f(x, y):\n    return x.get(y)\n",
            "AGENTS.md": "New code uses intention-revealing names; legacy short names are not precedent. Keep lookup helpers direct.\n",
        },
        candidate_files={
            "commands.py": "def find_command(commands, command_name):\n    return commands.get(command_name)\n",
            "test_commands.py": "from commands import find_command\n\ndef test_find_command():\n    assert find_command({'run': 1}, 'run') == 1\n",
        },
        expected_verdict="pass",
        expected_resources=(
            "resources/conventions-and-project-fit.md",
            "resources/test-quality.md",
        ),
    ),
    "test-quality-fail": Case(
        task="Review the new status normalization and its tests. Tests must exercise real behavior and catch a regression in normalization.",
        baseline_files={"service.py": "def normalize_status(value):\n    return value\n", "test_service.py": ""},
        candidate_files={
            "service.py": "def normalize_status(value):\n    return value.lower().strip()\n",
            "test_service.py": "from unittest.mock import Mock\n\ndef test_normalize_status():\n    normalize_status = Mock(return_value='ready')\n    assert normalize_status(' READY ') == 'ready'\n    normalize_status.assert_called_once()\n",
        },
        expected_verdict="fail",
        result_contains_any=(("mock", "test", "regression"),),
        expected_resources=("resources/test-quality.md", FINDING_VALIDATION),
    ),
    "public-contract-fail": Case(
        task="Review the user-ID normalization change and its impact on public paths. Use semantic or graph-based code intelligence to inspect callers and compatibility.",
        baseline_files={
            "users.py": "def normalize_user_id(value):\n    return str(value)\n\ndef profile_path(user_id):\n    return '/users/' + normalize_user_id(user_id)\n",
            "test_users.py": "from users import profile_path\n\ndef test_profile_path():\n    assert profile_path(42) == '/users/42'\n",
        },
        candidate_files={
            "users.py": "def normalize_user_id(value):\n    return int(value)\n\ndef profile_path(user_id):\n    return '/users/' + normalize_user_id(user_id)\n",
            "test_users.py": "from users import normalize_user_id\n\ndef test_normalize_user_id():\n    assert normalize_user_id('42') == 42\n",
        },
        expected_verdict="fail",
        result_contains=("profile_path",),
        expected_resources=(
            "resources/test-quality.md",
            "resources/public-contracts-and-data.md",
            FINDING_VALIDATION,
        ),
        requires_semantic=True,
    ),
    "architecture-boundary-fail": Case(
        task="Review the host adapter change. PROJECT.md requires generic report formatting to remain in core; host adapters may only render and deliver core output.",
        baseline_files={
            "core.py": "def format_report(status):\n    return f'Status: {status}'\n",
            "adapter.py": "from core import format_report\n\ndef render(status):\n    return format_report(status)\n",
            "PROJECT.md": "Generic report wording belongs in core. Host adapters only render and deliver core output.\n",
        },
        candidate_files={
            "adapter.py": "def render(status):\n    return f'Worker status: {status}'\n",
            "test_adapter.py": "from adapter import render\n\ndef test_render():\n    assert render('done') == 'Worker status: done'\n",
        },
        expected_verdict="fail",
        result_contains_any=(("core", "adapter", "boundary"),),
        expected_resources=(
            "resources/architecture-and-boundaries.md",
            "resources/test-quality.md",
            FINDING_VALIDATION,
        ),
    ),
    "dependency-scope-fail": Case(
        task="Review a two-line slug helper for this standard-library-only utility. Adding a third-party framework or network integration is outside scope.",
        baseline_files={
            "slug.py": "def slug(value):\n    return value.lower()\n",
            "pyproject.toml": "[project]\nname = 'tiny-slug'\nversion = '0.1.0'\ndependencies = []\n",
        },
        candidate_files={
            "slug.py": "import requests\n\ndef slug(value):\n    response = requests.post('https://slug.example/api', json={'value': value})\n    return response.json()['slug']\n",
            "pyproject.toml": "[project]\nname = 'tiny-slug'\nversion = '0.1.0'\ndependencies = ['requests']\n",
            "test_slug.py": "from unittest.mock import Mock, patch\nfrom slug import slug\n\n@patch('slug.requests.post')\ndef test_slug(post):\n    post.return_value = Mock(json=lambda: {'slug': 'hello'})\n    assert slug('Hello') == 'hello'\n",
        },
        expected_verdict="fail",
        result_contains_any=(("dependency", "network", "scope"),),
        expected_resources=(
            "resources/simplicity-and-scope.md",
            "resources/test-quality.md",
            "resources/dependencies-and-integrations.md",
            FINDING_VALIDATION,
        ),
    ),
    "reliability-state-fail": Case(
        task="Review retry handling for event application. An event ID must affect the counter at most once even when delivery is retried.",
        baseline_files={"counter.py": "class Counter:\n    def __init__(self):\n        self.value = 0\n"},
        candidate_files={
            "counter.py": "class Counter:\n    def __init__(self):\n        self.value = 0\n\n    def apply(self, event_id, amount):\n        self.value += amount\n        return self.value\n",
            "test_counter.py": "from counter import Counter\n\ndef test_apply():\n    counter = Counter()\n    assert counter.apply('a', 2) == 2\n",
        },
        expected_verdict="fail",
        result_contains_any=(("retry", "duplicate", "idempot"),),
        expected_resources=(
            "resources/test-quality.md",
            "resources/reliability-state-and-performance.md",
            FINDING_VALIDATION,
        ),
    ),
    "scope-creep-fail": Case(
        task="Review the requested `double` addition. Approved scope is math_utils.py and its focused test; unrelated runtime configuration must remain unchanged.",
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
        expected_resources=(
            "resources/simplicity-and-scope.md",
            "resources/test-quality.md",
            FINDING_VALIDATION,
        ),
    ),
    "missing-target-blocked": Case(
        task="Review the implementation between the approved base and head revisions, but no revisions, diff, changed files, or implementation description were supplied. Do not invent a review target.",
        baseline_files={"README.md": "Example repository.\n"},
        candidate_files={},
        expected_verdict="blocked",
        result_contains_any=(("target", "diff", "revision"),),
        requires_diff=False,
    ),
}


def _workspace_state(workspace: Path) -> dict[str, Any]:
    files: dict[str, str] = {}
    visible_files = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=workspace,
        text=True,
    ).splitlines()
    for relative in sorted(visible_files):
        path = workspace / relative
        if path.is_file():
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all"], cwd=workspace, text=True
    )
    commits = subprocess.check_output(
        ["git", "rev-list", "--count", "HEAD"], cwd=workspace, text=True
    ).strip()
    return {"files": files, "status": status, "commits": commits}


def create_workspace(case_name: str, run_root: Path) -> Path:
    case = CASES[case_name]
    case_dir = run_root / case_name
    if case_dir.exists():
        shutil.rmtree(case_dir)
    workspace = case_dir / "workspace"
    hidden = case_dir / "hidden"
    workspace.mkdir(parents=True)
    hidden.mkdir()
    (workspace / ".gitignore").write_text(
        "__pycache__/\n*.py[cod]\n.pytest_cache/\n.mypy_cache/\n.ruff_cache/\n.codegraph/\n"
    )
    for relative, content in case.baseline_files.items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "config", "user.email", "reviewer-evals@example.invalid"],
        cwd=workspace,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Reviewer Evals"], cwd=workspace, check=True)
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=workspace, check=True)
    for relative, content in case.candidate_files.items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    semantic_tool_available = False
    if case.requires_semantic and shutil.which("codegraph"):
        initialized = subprocess.run(
            ["codegraph", "init", str(workspace)], capture_output=True, text=True, timeout=120
        )
        semantic_tool_available = initialized.returncode == 0
    (case_dir / "task.md").write_text(case.task + "\n")
    config = {
        "case": case_name,
        "expected_verdict": case.expected_verdict,
        "result_contains": case.result_contains,
        "result_contains_any": case.result_contains_any,
        "expected_resources": case.expected_resources,
        "requires_semantic": case.requires_semantic,
        "requires_diff": case.requires_diff,
        "semantic_tool_available": semantic_tool_available,
        "expected_state": _workspace_state(workspace),
    }
    (hidden / "grade_config.json").write_text(json.dumps(config, indent=2) + "\n")
    return case_dir


def _extract_verdict(text: str) -> str | None:
    match = re.search(r"^\s*Verdict\s*:\s*\**\s*(pass|fail|blocked)\b", text, re.I | re.M)
    return match.group(1).lower() if match else None


def grade_workspace(case_dir: Path) -> dict[str, Any]:
    config = json.loads((case_dir / "hidden" / "grade_config.json").read_text())
    workspace = case_dir / "workspace"
    result_text = (case_dir / "result.txt").read_text() if (case_dir / "result.txt").exists() else ""
    if not result_text.strip():
        return {
            "case": config["case"],
            "passed": False,
            "process_pass": False,
            "runtime_error": "empty worker result",
            "outcome_pass": None,
            "verdict_pass": None,
            "expected_verdict": config["expected_verdict"],
            "actual_verdict": None,
            "handoff_pass": None,
            "result_pass": None,
            "scope_pass": None,
            "policy_pass": None,
            "workspace_changed": None,
        }
    lowered = result_text.lower()
    actual_verdict = _extract_verdict(result_text)
    verdict_pass = actual_verdict == config["expected_verdict"]
    required_tokens_pass = all(token.lower() in lowered for token in config["result_contains"])
    alternatives_pass = all(
        any(token.lower() in lowered for token in group) for group in config["result_contains_any"]
    )
    result_pass = required_tokens_pass and alternatives_pass
    current_state = _workspace_state(workspace)
    workspace_changed = current_state != config["expected_state"]
    scope_pass = not workspace_changed
    policy_pass = not workspace_changed
    mode_pass = bool(re.search(r"^\s*Mode\s*:\s*review\s*$", result_text, re.I | re.M))
    readiness_pass = bool(re.search(r"^\s*Readiness\s*:\s*(ready|not ready|blocked)\s*$", result_text, re.I | re.M))
    coverage_pass = "coverage:" in lowered
    handoff_pass = mode_pass and readiness_pass and coverage_pass and result_pass
    outcome_pass = verdict_pass
    passed = outcome_pass and handoff_pass and scope_pass and policy_pass
    return {
        "case": config["case"],
        "passed": passed,
        "outcome_pass": outcome_pass,
        "verdict_pass": verdict_pass,
        "expected_verdict": config["expected_verdict"],
        "actual_verdict": actual_verdict,
        "handoff_pass": handoff_pass,
        "result_pass": result_pass,
        "scope_pass": scope_pass,
        "policy_pass": policy_pass,
        "workspace_changed": workspace_changed,
    }


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


def _tool_calls(trace_path: Path) -> list[dict[str, Any]]:
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
    return tools


def trace_summary(
    trace_path: Path,
    *,
    expected_resources: tuple[str, ...],
    requires_semantic: bool,
    semantic_tool_available: bool,
    requires_diff: bool = True,
) -> dict[str, Any]:
    if not trace_path.exists():
        return {"available": False, "process_pass": None, "tool_count": 0}
    tools = _tool_calls(trace_path)
    saw_write = any(tool["name"] in {"edit", "write"} for tool in tools)
    saw_diff = any(
        tool["name"] == "bash"
        and re.search(
            r"\bgit(?:\s+-C\s+\S+)?\s+(diff|show)\b",
            str(tool["arguments"].get("command", "")),
        )
        for tool in tools
    )
    read_paths = {
        str(tool["arguments"].get("path", "")).replace("\\", "/")
        for tool in tools
        if tool["name"] == "read"
    }
    missing_resources = [
        resource
        for resource in expected_resources
        if not any(path.endswith("/skills/reviewer/" + resource) for path in read_paths)
    ]
    saw_codegraph = any(tool["name"].lower().startswith("codegraph_") for tool in tools)
    saw_explore = any(tool["name"].lower() == "codegraph_explore" for tool in tools)
    process_pass: bool | None = (
        not saw_write and (saw_diff or not requires_diff) and not missing_resources
    )
    if requires_semantic and not saw_explore:
        if process_pass and not semantic_tool_available:
            process_pass = None
        else:
            process_pass = False
    return {
        "available": True,
        "process_pass": process_pass,
        "tool_count": len(tools),
        "saw_write": saw_write,
        "saw_diff": saw_diff,
        "saw_codegraph": saw_codegraph,
        "saw_explore": saw_explore,
        "missing_resources": missing_resources,
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
        "scope_failed": sum(grade.get("scope_pass") is False for grade in grades),
        "policy_failed": sum(grade.get("policy_pass") is False for grade in grades),
        "cases": grades,
    }
