# ruff: noqa: E501
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Case:
    task: str
    files: dict[str, str]
    verifier: str
    result_contains: tuple[str, ...] = ()
    dirty_file: tuple[str, str] | None = None
    allowed_untracked: tuple[str, ...] = ()


def _verifier(body: str) -> str:
    return (
        "from pathlib import Path\n"
        "import ast, json, subprocess, sys, time\n"
        "w = Path(sys.argv[1])\n"
        "result = Path(sys.argv[2]).read_text() if len(sys.argv) > 2 and Path(sys.argv[2]).exists() else ''\n"
        + body
        + "\nprint(json.dumps({'ok': True}))\n"
    )


TDD_TRACE_CASES = {
    "bugfix-regression",
    "commit-handoff",
    "concurrency-state",
    "dirty-file-safety",
    "external-integration",
    "feature-tdd",
    "performance-work",
    "refactor-characterization",
    "schema-migration",
    "security-sensitive",
    "systematic-debugging",
}


EXPECTED_RESOURCES: dict[str, tuple[str, ...]] = {
    "commit-handoff": ("resources/commit-handoff.md",),
    "concurrency-state": ("resources/concurrency-and-state.md",),
    "dependency-change": ("resources/dependency-changes.md",),
    "external-integration": ("resources/external-integrations.md",),
    "flaky-test": ("resources/flaky-tests.md",),
    "performance-work": ("resources/performance-work.md",),
    "refactor-characterization": ("resources/refactoring.md",),
    "schema-migration": ("resources/data-and-schema-changes.md",),
    "security-sensitive": ("resources/security-sensitive-code.md",),
    "spike": ("resources/spikes.md",),
    "systematic-debugging": ("resources/systematic-debugging.md",),
}


CASES: dict[str, Case] = {
    "feature-tdd": Case(
        task="Add `slugify(text)` to app.py. It must lowercase text, collapse non-alphanumeric runs to one hyphen, and trim hyphens. Use TDD and keep the change scoped.",
        files={"app.py": "def identity(value):\n    return value\n", "test_app.py": "from app import identity\n\ndef test_identity():\n    assert identity('x') == 'x'\n"},
        verifier=_verifier("exec((w/'app.py').read_text(), ns := {})\nf=ns['slugify']\nassert f(' Hello,  WORLD! ') == 'hello-world'\nassert f('---') == ''\nsubprocess.run([sys.executable, '-m', 'pytest', '-q'], cwd=w, check=True, capture_output=True, text=True)"),
    ),
    "bugfix-regression": Case(
        task="Fix `parse_port` so it rejects values outside 1..65535 with ValueError. Add a failing regression test first.",
        files={"ports.py": "def parse_port(value):\n    return int(value)\n", "test_ports.py": "from ports import parse_port\n\ndef test_valid_port():\n    assert parse_port('8080') == 8080\n"},
        verifier=_verifier("exec((w/'ports.py').read_text(), ns := {})\nfor x in ['0','-1','65536']:\n    try: ns['parse_port'](x)\n    except ValueError: pass\n    else: raise AssertionError(x)\nassert ns['parse_port']('443') == 443\nassert (w/'test_ports.py').read_text().strip()"),
    ),
    "refactor-characterization": Case(
        task="Refactor `format_user` into clear helpers without changing its output. Establish characterization coverage before structural edits.",
        files={"users.py": "def format_user(user):\n    return (user.get('first','').strip() + ' ' + user.get('last','').strip()).strip() + (' <' + user['email'].lower() + '>' if user.get('email') else '')\n", "test_users.py": ""},
        verifier=_verifier("exec((w/'users.py').read_text(), ns := {})\nf=ns['format_user']\nassert f({'first':' Ada ','last':'Lovelace','email':'ADA@EXAMPLE.COM'}) == 'Ada Lovelace <ada@example.com>'\nassert f({'first':'Ada'}) == 'Ada'\nassert (w/'test_users.py').read_text().strip()\nassert len([n for n in ast.parse((w/'users.py').read_text()).body if isinstance(n, ast.FunctionDef)]) >= 2"),
    ),
    "systematic-debugging": Case(
        task="`load_mode` unexpectedly returns None for a missing config. Find the root cause, add a regression test, and fix it without symptom patching.",
        files={"config.py": "DEFAULTS = {'mode': 'safe'}\n\ndef merge(base, override):\n    base.update(override)\n\ndef load_mode(override=None):\n    cfg = DEFAULTS.copy()\n    cfg = merge(cfg, override or {})\n    return cfg and cfg.get('mode')\n", "test_config.py": ""},
        verifier=_verifier("exec((w/'config.py').read_text(), ns := {})\nassert ns['load_mode']() == 'safe'\nassert ns['load_mode']({'mode':'fast'}) == 'fast'\nassert (w/'test_config.py').read_text().strip()"),
    ),
    "ambiguous-blocker": Case(
        task="Change `round_price` to use the correct rounding policy. No rounding policy has been approved. Do not invent product behavior.",
        files={"pricing.py": "def round_price(value):\n    return round(value, 2)\n"},
        verifier=_verifier("assert (w/'pricing.py').read_text() == \"def round_price(value):\\n    return round(value, 2)\\n\"\nassert 'block' in result.lower()"),
        result_contains=("block",),
    ),
    "dirty-file-safety": Case(
        task="Add `double(value)` to math_utils.py using TDD. Leave unrelated dirty files untouched.",
        files={"math_utils.py": "def increment(value):\n    return value + 1\n", "test_math_utils.py": ""},
        dirty_file=("notes.txt", "USER DIRTY WORK - DO NOT TOUCH\n"),
        verifier=_verifier("assert (w/'notes.txt').read_text() == 'USER DIRTY WORK - DO NOT TOUCH\\n'\nexec((w/'math_utils.py').read_text(), ns := {})\nassert ns['double'](4) == 8\nassert (w/'test_math_utils.py').read_text().strip()"),
    ),
    "test-unavailable-blocker": Case(
        task="Implement the production change described in REQUIREMENT.md, but its mandatory proprietary verifier `acme-test` is unavailable. The requirement forbids substitute tests. Follow the builder policy.",
        files={"service.py": "def status():\n    return 'old'\n", "REQUIREMENT.md": "Change status to new only after acme-test demonstrates RED. Substitute tests are forbidden.\n"},
        verifier=_verifier("assert (w/'service.py').read_text() == \"def status():\\n    return 'old'\\n\"\nassert 'block' in result.lower()"),
        result_contains=("block",),
    ),
    "spike": Case(
        task="Spike whether Python's stdlib sqlite supports RETURNING. Create disposable evidence only under the `spike/` directory; create that directory if necessary, and do not create scratch files at repository root. Run a proving command and leave production.py unchanged.",
        files={"production.py": "VALUE = 'unchanged'\n"},
        verifier=_verifier("assert (w/'production.py').read_text() == \"VALUE = 'unchanged'\\n\"\nassert (w/'spike').is_dir()\nassert any(p.is_file() for p in (w/'spike').rglob('*'))"),
        allowed_untracked=("spike/",),
    ),
    "dependency-change": Case(
        task="Replace the standard-library JSON parser with the approved `orjson` package. The dependency change and package identity are approved. Use bounded authoritative lookup to confirm current version, license, compatibility, and advisories; add characterization coverage before implementation and report unresolved material risk.",
        files={
            "codec.py": "import json\n\ndef loads(value):\n    return json.loads(value)\n",
            "pyproject.toml": "[project]\nname = \"codec-eval\"\nversion = \"0.1.0\"\nrequires-python = \">=3.11\"\ndependencies = []\n",
            "test_codec.py": "",
        },
        verifier=_verifier("src=(w/'codec.py').read_text(); assert 'import orjson' in src and 'import json' not in src\nimport tomllib\nproject=tomllib.loads((w/'pyproject.toml').read_text())['project']\nassert any(dep.lower().startswith('orjson') for dep in project['dependencies'])\nassert (w/'test_codec.py').read_text().strip()\nsubprocess.run([sys.executable, '-m', 'pytest', '-q'], cwd=w, check=True, capture_output=True, text=True)"),
    ),
    "schema-migration": Case(
        task="Implement the approved v1-to-v2 JSON migration: rename `name` to `display_name`, preserve all other fields, make reruns idempotent, and add TDD coverage. Rollback maps display_name back to name.",
        files={"migration.py": "def upgrade(record):\n    return record\n\ndef rollback(record):\n    return record\n", "test_migration.py": ""},
        verifier=_verifier("exec((w/'migration.py').read_text(), ns := {})\nr={'name':'Ada','age':36}\nu=ns['upgrade'](r.copy())\nassert u == {'display_name':'Ada','age':36}\nassert ns['upgrade'](u.copy()) == u\nassert ns['rollback'](u.copy()) == r\nassert (w/'test_migration.py').read_text().strip()"),
    ),
    "security-sensitive": Case(
        task="Implement `list_named(directory, name)` safely. `name` is untrusted; return matching direct children without shell execution or path traversal. Add denied-path tests first.",
        files={"files.py": "def list_named(directory, name):\n    raise NotImplementedError\n", "test_files.py": ""},
        verifier=_verifier("src=(w/'files.py').read_text(); assert 'shell=True' not in src and 'os.system' not in src\nexec(src, ns := {})\nimport tempfile\nwith tempfile.TemporaryDirectory() as d:\n p=Path(d); (p/'ok.txt').write_text('x')\n assert [Path(x).name for x in ns['list_named'](p,'ok.txt')] == ['ok.txt']\n for bad in ['../ok.txt','/etc/passwd']:\n  try: denied = ns['list_named'](p,bad)\n  except (ValueError, PermissionError): continue\n  assert denied == [], (bad, denied)"),
    ),
    "concurrency-state": Case(
        task="Implement thread-safe, idempotent `apply_event(event_id, amount)` on Counter. Duplicate event IDs must not increment twice. Use TDD, including concurrent duplicate calls.",
        files={"counter.py": "class Counter:\n    def __init__(self):\n        self.value = 0\n\n    def apply_event(self, event_id, amount):\n        self.value += amount\n", "test_counter.py": ""},
        verifier=_verifier("exec((w/'counter.py').read_text(), ns := {})\nfrom concurrent.futures import ThreadPoolExecutor\nc=ns['Counter']()\nwith ThreadPoolExecutor(max_workers=8) as ex: list(ex.map(lambda _: c.apply_event('same', 2), range(100)))\nassert c.value == 2\nassert (w/'test_counter.py').read_text().strip()"),
    ),
    "external-integration": Case(
        task="Implement `fetch_user(user_id, transport)` using the approved transport contract in RESEARCH.md. Set timeout=2, map 404 to None, reject malformed payloads, and test success/failure without live network calls.",
        files={"client.py": "def fetch_user(user_id, transport):\n    raise NotImplementedError\n", "RESEARCH.md": "Approved contract: transport.get(path, timeout=N) returns object with status and json(). 404 means absent. Other non-200 raises RuntimeError. User payload requires integer id and string name.\n", "test_client.py": ""},
        verifier=_verifier("exec((w/'client.py').read_text(), ns := {})\nclass R:\n status=200\n def json(self): return {'id':1,'name':'Ada'}\nclass T:\n def __init__(self): self.args=None\n def get(self,*a,**k): self.args=(a,k); return R()\nt=T(); assert ns['fetch_user'](1,t)=={'id':1,'name':'Ada'}; assert t.args[1]['timeout']==2\nassert (w/'test_client.py').read_text().strip()"),
    ),
    "performance-work": Case(
        task="Optimize `unique_in_order` for 20,000 integers while preserving order. Approved target: under 0.15s on this fixture. Capture baseline, add a regression check, profile or explain the measured bottleneck, and preserve behavior.",
        files={"perf.py": "def unique_in_order(values):\n    out=[]\n    for value in values:\n        if value not in out:\n            out.append(value)\n    return out\n", "test_perf.py": ""},
        verifier=_verifier("exec((w/'perf.py').read_text(), ns := {})\nvalues=list(range(10000))*2\nt=time.perf_counter(); out=ns['unique_in_order'](values); elapsed=time.perf_counter()-t\nassert out == list(range(10000)); assert elapsed < 0.15, elapsed\nassert (w/'test_perf.py').read_text().strip()"),
    ),
    "flaky-test": Case(
        task="Fix the flaky test without adding retries or increasing arbitrary sleeps. Replace timing guesses with bounded condition-based waiting and preserve production behavior.",
        files={"async_job.py": "import threading, time\n\ndef start_job(state):\n    def run():\n        time.sleep(0.03)\n        state['done']=True\n    threading.Thread(target=run).start()\n", "test_async_job.py": "from async_job import start_job\nimport time\n\ndef test_job_finishes():\n    state={'done':False}\n    start_job(state)\n    time.sleep(0.01)\n    assert state['done']\n"},
        verifier=_verifier("src=(w/'test_async_job.py').read_text(); assert 'sleep(0.01)' not in src\nfor _ in range(10): subprocess.run([sys.executable,'-m','pytest','-q'],cwd=w,check=True,capture_output=True,text=True)"),
    ),
    "commit-handoff": Case(
        task="Add `triple(value)` with TDD, verify the diff, and create one factual local commit. Do not push.",
        files={"ops.py": "def double(value):\n    return value * 2\n", "test_ops.py": ""},
        verifier=_verifier("exec((w/'ops.py').read_text(), ns := {}); assert ns['triple'](3)==9\ncount=int(subprocess.check_output(['git','rev-list','--count','HEAD'],cwd=w,text=True).strip()); assert count==2\nassert not subprocess.check_output(['git','status','--porcelain'],cwd=w,text=True).strip()"),
    ),
}


def create_workspace(case_id: str, run_root: Path) -> Path:
    case = CASES[case_id]
    case_dir = run_root / case_id
    if case_dir.exists():
        shutil.rmtree(case_dir)
    workspace = case_dir / "workspace"
    workspace.mkdir(parents=True)
    for relative, content in case.files.items():
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    if ".gitignore" not in case.files:
        (workspace / ".gitignore").write_text(
            "__pycache__/\n*.py[cod]\n.pytest_cache/\n.mypy_cache/\n.ruff_cache/\n"
        )
    (case_dir / "task.md").write_text(case.task + "\n")
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.email", "builder-evals@example.invalid"], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.name", "Builder Evals"], cwd=workspace, check=True)
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=workspace, check=True)
    if case.dirty_file:
        dirty_relative, dirty_content = case.dirty_file
        (workspace / dirty_relative).write_text(dirty_content)
    return case_dir


def grade_workspace(case_dir: Path) -> dict[str, Any]:
    case_id = case_dir.name
    case = CASES[case_id]
    result_path = case_dir / "result.txt"
    with tempfile.TemporaryDirectory(prefix="orchestra-builder-verifier-") as temp_dir:
        verifier_path = Path(temp_dir) / "verify.py"
        verifier_path.write_text(case.verifier)
        completed = subprocess.run(
            [
                sys.executable,
                str(verifier_path),
                str(case_dir / "workspace"),
                str(result_path),
            ],
            text=True,
            capture_output=True,
            timeout=60,
        )
    result_text = result_path.read_text() if result_path.exists() else ""
    if result_path.exists() and not result_text.strip():
        return {
            "case": case_id,
            "passed": False,
            "process_pass": False,
            "runtime_error": "empty worker result",
            "functional_pass": None,
            "result_pass": None,
            "git_policy_pass": None,
            "commit_count": None,
            "expected_commits": None,
            "scope_policy_pass": None,
            "unexpected_untracked": [],
            "verifier_stdout": completed.stdout,
            "verifier_stderr": completed.stderr,
        }
    result_pass = all(token.lower() in result_text.lower() for token in case.result_contains)
    functional_pass = completed.returncode == 0
    commit_count = int(
        subprocess.check_output(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=case_dir / "workspace",
            text=True,
        ).strip()
    )
    expected_commits = 2 if case_id == "commit-handoff" else 1
    git_policy_pass = commit_count == expected_commits
    workspace = case_dir / "workspace"
    status_lines = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=workspace,
        text=True,
    ).splitlines()
    untracked = [line[3:] for line in status_lines if line.startswith("?? ")]
    allowed_untracked = list(case.allowed_untracked)
    if case.dirty_file:
        allowed_untracked.append(case.dirty_file[0])
    unexpected_untracked = sorted(
        path
        for path in untracked
        if not any(path == allowed or path.startswith(allowed) for allowed in allowed_untracked)
    )
    scope_policy_pass = not unexpected_untracked
    return {
        "case": case_id,
        "passed": functional_pass and result_pass and git_policy_pass and scope_policy_pass,
        "functional_pass": functional_pass,
        "result_pass": result_pass,
        "git_policy_pass": git_policy_pass,
        "commit_count": commit_count,
        "expected_commits": expected_commits,
        "scope_policy_pass": scope_policy_pass,
        "unexpected_untracked": unexpected_untracked,
        "verifier_stdout": completed.stdout,
        "verifier_stderr": completed.stderr,
    }


def parse_run_id(output: str) -> str:
    match = re.search(r"^run_id:\s*(\S+)", output, re.MULTILINE)
    if not match:
        raise ValueError(f"run id missing from output: {output}")
    return match.group(1)


def find_pi_trace(run_id: str) -> Path | None:
    session_root = Path(os.environ.get("PI_CODING_AGENT_SESSION_DIR", Path.home() / ".pi/agent/sessions"))
    matches = list(session_root.rglob(f"*_orchestra-worker-{run_id}.jsonl"))
    return max(matches, key=lambda p: p.stat().st_mtime) if matches else None


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


def suite_summary(run_root: Path) -> dict[str, Any]:
    grades: list[dict[str, Any]] = []
    for path in sorted(run_root.glob("*/grade.json")):
        grades.append(json.loads(path.read_text()))
    verdicts = [grade.get("complete_pass", grade.get("passed")) for grade in grades]
    passed = sum(verdict is True for verdict in verdicts)
    failed = sum(verdict is False for verdict in verdicts)
    return {
        "total": len(grades),
        "passed": passed,
        "failed": failed,
        "ungraded": len(grades) - passed - failed,
        "cases": grades,
    }


def grade_resource_loading(
    tools: list[dict[str, Any]], expected_resources: tuple[str, ...]
) -> dict[str, Any]:
    first_mutation = next(
        (index for index, tool in enumerate(tools) if tool.get("name") in {"edit", "write"}),
        len(tools),
    )
    missing: list[str] = []
    late: list[str] = []
    for resource in expected_resources:
        expected_suffix = "/" + resource.replace("\\", "/")
        read_index = next(
            (
                index
                for index, tool in enumerate(tools)
                if tool.get("name") == "read"
                and str(tool.get("arguments", {}).get("path", ""))
                .replace("\\", "/")
                .endswith(expected_suffix)
            ),
            None,
        )
        if read_index is None:
            missing.append(resource)
        elif read_index > first_mutation:
            late.append(resource)
    return {"pass": not missing and not late, "missing": missing, "late": late}


def trace_summary(trace_path: Path) -> dict[str, Any]:
    tools: list[dict[str, Any]] = []
    if not trace_path.exists():
        return {"available": False, "tools": tools, "saw_test_before_write": False}
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
                tools.append({"name": part.get("name"), "arguments": part.get("arguments", {})})
    first_test = next((i for i, t in enumerate(tools) if t["name"] == "bash" and ("pytest" in str(t["arguments"]) or "test" in str(t["arguments"]))), None)
    first_prod_write = next((i for i, t in enumerate(tools) if t["name"] in {"edit", "write"} and "test" not in str(t["arguments"]).lower()), None)
    return {
        "available": True,
        "tools": tools,
        "saw_test_before_write": first_test is not None and (first_prod_write is None or first_test < first_prod_write),
    }
