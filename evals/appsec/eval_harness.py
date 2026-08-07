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
    "clean-pass": Case(
        task="Review a fixed-key preference reader. Input is an already parsed trusted mapping; no external input or privileged sink is involved.",
        baseline_files={"prefs.py": "def theme(config):\n    return 'light'\n"},
        candidate_files={"prefs.py": "def theme(config):\n    return config.get('theme', 'light')\n", "test_prefs.py": "from prefs import theme\n\ndef test_theme():\n    assert theme({'theme': 'dark'}) == 'dark'\n"},
        expected_verdict="pass",
    ),
    "authorization-fail": Case(
        task="Review the document endpoint. A signed-in user may read only documents they own.",
        baseline_files={"docs.py": "def get_doc(store, user, doc_id):\n    doc = store[doc_id]\n    if doc['owner_id'] != user.id:\n        raise PermissionError\n    return doc\n"},
        candidate_files={"docs.py": "def get_doc(store, user, doc_id):\n    return store[doc_id]\n", "test_docs.py": "from docs import get_doc\n\ndef test_reads_doc():\n    assert get_doc({1: {'owner_id': 7}}, type('U', (), {'id': 7})(), 1)['owner_id'] == 7\n"},
        expected_verdict="fail", result_contains_any=(("owner", "authorization", "unauthorized"),),
        expected_resources=("resources/authorization-and-identity.md", "resources/finding-validation.md"), requires_semantic=True,
    ),
    "authorization-safe-pass": Case(
        task="Review tenant-scoped document lookup. The repository query enforces both tenant and object identity before returning data.",
        baseline_files={"docs.py": "def get_doc(repo, tenant_id, doc_id):\n    raise NotImplementedError\n"},
        candidate_files={"docs.py": "def get_doc(repo, tenant_id, doc_id):\n    return repo.find_one(tenant_id=tenant_id, id=doc_id)\n", "test_docs.py": "from docs import get_doc\n\nclass Repo:\n    def find_one(self, **filters):\n        assert filters == {'tenant_id': 't1', 'id': 2}\n        return {'id': 2}\n\ndef test_scoped():\n    assert get_doc(Repo(), 't1', 2) == {'id': 2}\n"},
        expected_verdict="pass", expected_resources=("resources/authorization-and-identity.md",), requires_semantic=True,
    ),
    "command-injection-fail": Case(
        task="Review archive extraction. Archive names come directly from an HTTP request and extraction must not permit command execution.",
        baseline_files={"archive.py": "import subprocess\n\ndef extract(name):\n    return subprocess.run(['tar', '-xf', name], check=True)\n"},
        candidate_files={"archive.py": "import subprocess\n\ndef extract(name):\n    return subprocess.run(f'tar -xf {name}', shell=True, check=True)\n", "test_archive.py": "from archive import extract\n"},
        expected_verdict="fail", result_contains_any=(("shell", "command", "execution"),),
        expected_resources=("resources/untrusted-input-and-sinks.md", "resources/finding-validation.md"), requires_semantic=True,
    ),
    "shell-safe-pass": Case(
        task="Review text rendering. The value is user-controlled; subprocess uses a fixed executable and fixed format with the value as a separate argument.",
        baseline_files={"render.py": "def render(value):\n    raise NotImplementedError\n"},
        candidate_files={"render.py": "import subprocess\n\ndef render(value):\n    return subprocess.run(['printf', '%s', value], check=True)\n", "test_render.py": "from render import render\n"},
        expected_verdict="pass", expected_resources=("resources/untrusted-input-and-sinks.md",),
    ),
    "path-traversal-fail": Case(
        task="Review download_file. The path segment comes from an unauthenticated request and downloads must remain under /srv/public.",
        baseline_files={"download.py": "from pathlib import Path\nROOT = Path('/srv/public')\n\ndef download_file(name):\n    path = (ROOT / name).resolve()\n    if ROOT not in path.parents:\n        raise ValueError('outside root')\n    return path.read_bytes()\n"},
        candidate_files={"download.py": "from pathlib import Path\nROOT = Path('/srv/public')\n\ndef download_file(name):\n    return (ROOT / name).read_bytes()\n", "test_download.py": "from download import download_file\n"},
        expected_verdict="fail", result_contains_any=(("traversal", "outside", "path"),),
        expected_resources=("resources/untrusted-input-and-sinks.md", "resources/finding-validation.md"),
    ),
    "ssrf-fail": Case(
        task="Review webhook preview. Any anonymous user controls the URL; the service has access to internal metadata endpoints.",
        baseline_files={"preview.py": "def preview(url):\n    raise NotImplementedError\n"},
        candidate_files={"preview.py": "import urllib.request\n\ndef preview(url):\n    return urllib.request.urlopen(url).read()\n", "test_preview.py": "from preview import preview\n"},
        expected_verdict="fail", result_contains_any=(("SSRF", "internal", "network"),),
        expected_resources=("resources/untrusted-input-and-sinks.md", "resources/finding-validation.md"),
    ),
    "secret-leak-fail": Case(
        task="Review authentication diagnostics. Authorization headers contain reusable credentials and must never be logged.",
        baseline_files={"auth.py": "def authenticate(headers, log):\n    return headers.get('Authorization') is not None\n"},
        candidate_files={"auth.py": "def authenticate(headers, log):\n    log.info('request headers=%r', headers)\n    return headers.get('Authorization') is not None\n", "test_auth.py": "from auth import authenticate\n"},
        expected_verdict="fail", result_contains_any=(("credential", "Authorization", "token"),),
        expected_resources=("resources/secrets-and-sensitive-data.md", "resources/finding-validation.md"),
    ),
    "dependency-integrity-fail": Case(
        task="Review plugin installation. The URL is administrator-supplied but the downloaded executable plugin must be authenticated before loading.",
        baseline_files={"plugins.py": "def install(url, expected_sha256):\n    raise NotImplementedError\n"},
        candidate_files={"plugins.py": "import urllib.request\n\ndef install(url, expected_sha256):\n    data = urllib.request.urlopen(url).read()\n    open('/tmp/plugin.py', 'wb').write(data)\n    return '/tmp/plugin.py'\n", "test_plugins.py": "from plugins import install\n"},
        expected_verdict="fail", result_contains_any=(("integrity", "hash", "authenticate"),),
        expected_resources=("resources/dependencies-and-integrity.md", "resources/finding-validation.md"),
    ),
    "agent-tool-boundary-fail": Case(
        task="Review tool dispatch. Tool names and arguments come from model output; policy permits only the read_file tool.",
        baseline_files={"tools.py": "def dispatch(call, tools):\n    if call['name'] != 'read_file':\n        raise PermissionError\n    return tools[call['name']](**call['args'])\n"},
        candidate_files={"tools.py": "def dispatch(call, tools):\n    return tools[call['name']](**call['args'])\n", "test_tools.py": "from tools import dispatch\n"},
        expected_verdict="fail", result_contains_any=(("tool", "model", "policy"),),
        expected_resources=("resources/agent-and-tool-boundaries.md", "resources/finding-validation.md"), requires_semantic=True,
    ),
    "prompt-data-safe-pass": Case(
        task="Review retrieval summarization. Retrieved text is untrusted data, but the model can only return text; it has no tools, credentials, memory writes, or privileged action path.",
        baseline_files={"summary.py": "def summarize(model, text):\n    raise NotImplementedError\n"},
        candidate_files={"summary.py": "def summarize(model, text):\n    return model.generate(system='Summarize the supplied document.', data=text)\n", "test_summary.py": "from summary import summarize\n"},
        expected_verdict="pass", expected_resources=("resources/agent-and-tool-boundaries.md",), requires_semantic=True,
    ),
    "memory-poisoning-fail": Case(
        task="Review agent memory. Any workspace document is untrusted; only validated user preferences may become persistent instructions used by later privileged tool runs.",
        baseline_files={"memory.py": "def remember(store, preference):\n    store['preferences'].append(preference)\n"},
        candidate_files={"memory.py": "def ingest_workspace(store, document):\n    store['instructions'].append(document)\n\ndef next_prompt(store):\n    return '\\n'.join(store['instructions'])\n", "test_memory.py": "from memory import ingest_workspace, next_prompt\n"},
        expected_verdict="fail", result_contains_any=(("memory", "poison", "persistent"),),
        expected_resources=("resources/agent-and-tool-boundaries.md", "resources/finding-validation.md"), requires_semantic=True,
    ),
    "inert-example-pass": Case(
        task="Review a documentation fixture containing the explicit inert value EXAMPLE_TOKEN. It is not accepted by any service and no runtime code reads the fixture.",
        baseline_files={"example.json": "{}\n"},
        candidate_files={"example.json": "{\"token\": \"EXAMPLE_TOKEN\"}\n"},
        expected_verdict="pass", expected_resources=("resources/secrets-and-sensitive-data.md",),
    ),
    "missing-target-blocked": Case(
        task="Perform a security review, but no base revision, diff, changed files, or implementation description is available.",
        baseline_files={"README.md": "fixture without candidate implementation\n"}, candidate_files={}, expected_verdict="blocked",
        result_contains_any=(("target", "diff", "revision"),), requires_diff=False,
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
        ["git", "config", "user.email", "appsec-evals@example.invalid"],
        cwd=workspace,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "AppSec Evals"], cwd=workspace, check=True)
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
    mode_pass = bool(re.search(r"^\s*Mode\s*:\s*appsec\s*$", result_text, re.I | re.M))
    readiness_pass = bool(
        re.search(
            r"^\s*Readiness\s*:\s*(security-ready|not security-ready|blocked)\s*$",
            result_text,
            re.I | re.M,
        )
    )
    contract_sections_pass = all(
        section in lowered
        for section in ("attack surface:", "findings:", "security evidence:", "residual risk:")
    )
    finding_evidence_pass = True
    if config["expected_verdict"] == "fail":
        finding_evidence_pass = bool(
            re.search(r"^\s*-\s*(HIGH|MEDIUM)\s+`[^`\n]+:\d+`", result_text, re.I | re.M)
        ) and any(token in lowered for token in ("remediation", "fix", "replace", "restore", "constrain", "validate"))
    handoff_pass = (
        mode_pass
        and readiness_pass
        and contract_sections_pass
        and finding_evidence_pass
        and result_pass
    )
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
        if not any(path.endswith("/skills/appsec/" + resource) for path in read_paths)
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
