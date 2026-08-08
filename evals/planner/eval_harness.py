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

PLAN_VALIDATION = "resources/plan-validation.md"
DATASET_DIR = Path(__file__).with_name("datasets")


@dataclass(frozen=True)
class Case:
    id: str
    task: str
    files: dict[str, str]
    expected_verdict: str
    required_tokens: tuple[str, ...] = ()
    forbidden_tokens: tuple[str, ...] = ()
    expected_resources: tuple[str, ...] = ()
    requires_dispatch: bool = False
    requires_no_dispatch: bool = False
    requires_barrier_stop: bool = False
    requires_semantic: bool = False
    suite: str = "capability/dev"
    suite_type: str = "capability"
    benchmark_pattern: str = "custom"
    task_unit: str = "repository task"
    oracle: dict[str, Any] | None = None


def _load_cases(dataset_dir: Path = DATASET_DIR) -> dict[str, Case]:
    cases: dict[str, Case] = {}
    for path in sorted(dataset_dir.rglob("*.json")):
        data = json.loads(path.read_text())
        case = Case(
            id=data["id"],
            task=data["task"],
            files=dict(data["files"]),
            expected_verdict=data["expected_verdict"],
            required_tokens=tuple(data.get("required_tokens", ())),
            forbidden_tokens=tuple(data.get("forbidden_tokens", ())),
            expected_resources=tuple(data.get("expected_resources", ())),
            requires_dispatch=bool(data.get("requires_dispatch", False)),
            requires_no_dispatch=bool(data.get("requires_no_dispatch", False)),
            requires_barrier_stop=bool(data.get("requires_barrier_stop", False)),
            requires_semantic=bool(data.get("requires_semantic", False)),
            suite=data.get("suite", str(path.parent.relative_to(dataset_dir))),
            suite_type=data.get("suite_type", "capability"),
            benchmark_pattern=data.get("benchmark_pattern", "custom"),
            task_unit=data.get("task_unit", "repository task"),
            oracle=data.get("oracle", {}),
        )
        if case.id != path.stem:
            raise ValueError(f"case id {case.id!r} does not match file name {path.name!r}")
        cases[case.id] = case
    return cases


CASES = _load_cases()


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
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=workspace, text=True).strip()
    return {"files": files, "status": status, "commits": commits, "head": head}


def create_workspace(case_name: str, run_root: Path) -> Path:
    case = CASES[case_name]
    case_dir = run_root / case_name
    if case_dir.exists():
        shutil.rmtree(case_dir)
    workspace = case_dir / "workspace"
    hidden = case_dir / "hidden"
    workspace.mkdir(parents=True)
    hidden.mkdir()
    (workspace / ".gitignore").write_text("__pycache__/\n*.py[cod]\n.codegraph/\n")
    for relative, content in case.files.items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "config", "user.email", "planner-evals@example.invalid"], cwd=workspace, check=True
    )
    subprocess.run(["git", "config", "user.name", "Planner Evals"], cwd=workspace, check=True)
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=workspace, check=True)
    semantic_tool_available = False
    if case.requires_semantic and shutil.which("codegraph"):
        initialized = subprocess.run(
            ["codegraph", "init", str(workspace)], capture_output=True, text=True, timeout=120
        )
        semantic_tool_available = initialized.returncode == 0
    (case_dir / "task.md").write_text(case.task + "\n")
    (hidden / "grade_config.json").write_text(
        json.dumps(
            {
                "case": case_name,
                "suite": case.suite,
                "suite_type": case.suite_type,
                "benchmark_pattern": case.benchmark_pattern,
                "task_unit": case.task_unit,
                "oracle": case.oracle or {},
                "expected_verdict": case.expected_verdict,
                "required_tokens": case.required_tokens,
                "forbidden_tokens": case.forbidden_tokens,
                "expected_resources": case.expected_resources,
                "requires_dispatch": case.requires_dispatch,
                "requires_no_dispatch": case.requires_no_dispatch,
                "requires_barrier_stop": case.requires_barrier_stop,
                "requires_semantic": case.requires_semantic,
                "semantic_tool_available": semantic_tool_available,
                "expected_state": _workspace_state(workspace),
            },
            indent=2,
        )
        + "\n"
    )
    return case_dir


def _extract_verdict(text: str) -> str | None:
    match = re.search(
        r"^\s*\**\s*Verdict\s*\**\s*:\s*\**\s*(ready|blocked)\b",
        text,
        re.I | re.M,
    )
    return match.group(1).lower() if match else None


def grade_workspace(case_dir: Path) -> dict[str, Any]:
    config = json.loads((case_dir / "hidden" / "grade_config.json").read_text())
    workspace = case_dir / "workspace"
    result_text = (
        (case_dir / "result.txt").read_text() if (case_dir / "result.txt").exists() else ""
    )
    planning_artifact_text = "\n".join(
        (workspace / artifact).read_text(errors="replace")
        for artifact in ("PLAN.md", "RESEARCH.md", "ROADMAP.md")
        if (workspace / artifact).exists()
    )
    grade_text = result_text + "\n" + planning_artifact_text
    lowered = grade_text.lower()
    empty_result = not result_text.strip()
    if empty_result:
        return {
            "case": config["case"],
            "suite": config.get("suite"),
            "suite_type": config.get("suite_type"),
            "benchmark_pattern": config.get("benchmark_pattern"),
            "passed": False,
            "outcome_pass": None,
            "handoff_pass": None,
            "scope_pass": None,
            "policy_pass": None,
            "runtime_failure": True,
            "workspace_changed": _workspace_state(workspace) != config["expected_state"],
        }
    actual_verdict = _extract_verdict(grade_text)
    verdict_pass = actual_verdict == config["expected_verdict"]
    required_pass = all(token.lower() in lowered for token in config["required_tokens"])
    forbidden_pass = not any(token.lower() in lowered for token in config["forbidden_tokens"])
    mode_pass = bool(
        re.search(r"^\s*\**\s*Mode\s*\**\s*:\s*\**\s*plan\b", grade_text, re.I | re.M)
    )
    section_pass = all(
        re.search(rf"^\s*\**\s*{re.escape(label)}\s*\**\s*:", grade_text, re.I | re.M)
        for label in ("Research used", "Research still needed", "Open questions")
    )
    current_state = _workspace_state(workspace)
    workspace_changed = current_state != config["expected_state"]
    changed_files = sorted(set(current_state["files"]) ^ set(config["expected_state"]["files"]))
    changed_files.extend(
        sorted(
            path
            for path, digest in current_state["files"].items()
            if config["expected_state"]["files"].get(path) not in {None, digest}
        )
    )
    allowed_plan_artifacts = {"PLAN.md", "RESEARCH.md", "ROADMAP.md"}
    unexpected_changed_files = sorted(
        path for path in set(changed_files) if path not in allowed_plan_artifacts
    )
    handoff_pass = mode_pass and section_pass and required_pass and forbidden_pass
    outcome_pass = verdict_pass and required_pass and forbidden_pass
    vcs_changed = current_state["head"] != config["expected_state"]["head"]
    scope_pass = not unexpected_changed_files
    policy_pass = not unexpected_changed_files and not vcs_changed
    return {
        "case": config["case"],
        "suite": config.get("suite"),
        "suite_type": config.get("suite_type"),
        "benchmark_pattern": config.get("benchmark_pattern"),
        "passed": outcome_pass and handoff_pass and scope_pass and policy_pass,
        "outcome_pass": outcome_pass,
        "verdict_pass": verdict_pass,
        "expected_verdict": config["expected_verdict"],
        "actual_verdict": actual_verdict,
        "handoff_pass": handoff_pass,
        "required_pass": required_pass,
        "forbidden_pass": forbidden_pass,
        "scope_pass": scope_pass,
        "policy_pass": policy_pass,
        "runtime_failure": False,
        "workspace_changed": workspace_changed,
        "unexpected_changed_files": unexpected_changed_files,
        "vcs_changed": vcs_changed,
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
    if not trace_path.exists():
        return tools
    for line in trace_path.read_text(errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = item.get("message", {})
        if message.get("role") != "assistant":
            continue
        for part in message.get("content", []):
            if part.get("type") == "toolCall":
                tools.append(
                    {"name": str(part.get("name", "")), "arguments": part.get("arguments", {})}
                )
    return tools


def trace_summary(
    trace_path: Path,
    *,
    expected_resources: tuple[str, ...],
    requires_dispatch: bool,
    requires_no_dispatch: bool,
    requires_semantic: bool,
    semantic_tool_available: bool,
) -> dict[str, Any]:
    if not trace_path.exists():
        return {"available": False, "process_pass": None, "tool_count": None}
    tools = _tool_calls(trace_path)
    allowed_plan_artifacts = {"PLAN.md", "RESEARCH.md", "ROADMAP.md"}
    unexpected_write_tools = []
    for tool in [tool for tool in tools if tool["name"] in {"edit", "write"}]:
        raw_path = str(tool["arguments"].get("path", ""))
        if Path(raw_path).name not in allowed_plan_artifacts:
            unexpected_write_tools.append(tool)
    saw_write = bool(unexpected_write_tools)
    dispatch_count = sum(tool["name"] == "orch_dispatch" for tool in tools)
    saw_codegraph = any(tool["name"].startswith("codegraph") for tool in tools)
    saw_explore = any(tool["name"] == "codegraph_explore" for tool in tools)
    missing_resources: list[str] = []
    for resource in expected_resources:
        expected_suffix = "/" + resource.replace("\\", "/")
        if not any(
            tool["name"] == "read"
            and str(tool["arguments"].get("path", "")).replace("\\", "/").endswith(expected_suffix)
            for tool in tools
        ):
            missing_resources.append(resource)
    process_pass = not saw_write and not missing_resources
    if requires_dispatch:
        process_pass = process_pass and dispatch_count >= 1
    if requires_no_dispatch:
        process_pass = process_pass and dispatch_count == 0
    if requires_semantic and semantic_tool_available:
        process_pass = process_pass and saw_explore
    return {
        "available": True,
        "process_pass": process_pass,
        "tool_count": len(tools),
        "saw_write": saw_write,
        "dispatch_count": dispatch_count,
        "saw_codegraph": saw_codegraph,
        "saw_explore": saw_explore,
        "missing_resources": missing_resources,
    }


def suite_summary(run_root: Path) -> dict[str, Any]:
    grades = [json.loads(path.read_text()) for path in sorted(run_root.rglob("grade.json"))]
    durations = [g.get("duration_seconds") for g in grades if g.get("duration_seconds")]
    return {
        "total": len(grades),
        "passed": sum(g.get("passed") is True for g in grades),
        "outcome_passed": sum(g.get("outcome_pass") is True for g in grades),
        "handoff_passed": sum(g.get("handoff_pass") is True for g in grades),
        "process_passed": sum(g.get("process_pass") is True for g in grades),
        "process_failed": sum(g.get("process_pass") is False for g in grades),
        "process_unknown": sum(g.get("process_pass") is None for g in grades),
        "scope_passed": sum(g.get("scope_pass") is True for g in grades),
        "policy_passed": sum(g.get("policy_pass") is True for g in grades),
        "infrastructure_failures": sum(g.get("runtime_failure") is True for g in grades),
        "median_duration_seconds": sorted(durations)[len(durations) // 2] if durations else None,
        "suites": sorted({g.get("suite") for g in grades if g.get("suite")}),
        "suite_types": sorted({g.get("suite_type") for g in grades if g.get("suite_type")}),
    }
