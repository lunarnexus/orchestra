"""No-nested-dispatch regression: a marked Orchestra child can never dispatch.

Root cause of the HIGH regression: orchestra2 dropped the producer marker, the
Pi-extension consumer guard, and the core guard that the reference project kept
under ``ORCHESTRA_DISPATCH_BUDGET=1``. A launched subagent therefore inherited a
registering, dispatching Orchestra adapter, so a nested child could dispatch a
further subagent and overlap its parent/verifier/writer.

These tests prove the restored contract at every independent layer:

* core submit rejects a marked, malformed, or otherwise non-parent marker and
  persists no job (the single choke point every dispatch path funnels through,
  including the direct ``dispatch`` CLI and the hidden ``__session`` admission),
* the launched child process actually carries the reserved marker even when the
  role's own ``env`` tries to override it (set after role env), while the parent
  environment is left unchanged,
* an unmarked parent still dispatches and its configured auto-verify follow-up
  is queued normally.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from queue import Empty, Queue
from typing import Any

import pytest

from orchestra import cli
from orchestra.config import OrchestraConfig, load_orchestra_config
from orchestra.dispatch_guard import (
    ORCHESTRA_DISPATCH_BUDGET_ENV,
    mark_child_dispatch_env,
    orchestra_can_dispatch,
)
from orchestra.harness import Budgets, CommandJob
from orchestra.pi_harness import AgentPlan, PiHarness
from orchestra.queue import JobQueue
from orchestra.submit import Assignment, SubmitError, submit

REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION = "sess-main"

ROLES_YAML = """
default_role: builder
model_limits: {}
roles:
  builder:
    enabled: manual
    dispatch_hint: Return builder changes.
    harness_config: pi
    model: "m1"
    env: {}
    skills: []
    auto_verify: true
  verifier:
    enabled: auto
    dispatch_hint: Return verdict and evidence.
    harness_config: pi
    model: "m1"
    env: {}
    skills: []
    auto_verify: false
"""

CONFIG_YAML = """
state_dir: {state_dir}
log_dir: {state_dir}/logs
default_timeout: 300
soft_timeout: 240
turn_limit: 60
concurrency:
  global: 4
  per_session: 2
retention_days: 90
default_mode: 'on'
"""

HARNESSES_YAML = """
pi:
  harness: pi
  command: ["pi"]
"""

PROMPTS_YAML = """
delegation_guidance: delegate
dispatch_ack: ack
return_hint_all_succeeded: ok
return_hint_verification_disagreement: disagree
return_hint_budget_exhausted: budget
return_hint_hard_failure: failed
budget_intervention: budget
"""


@pytest.fixture()
def state_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "config"
    directory.mkdir()
    (directory / "agent-catalog.yaml").write_text(ROLES_YAML, encoding="utf-8")
    (directory / "config.yaml").write_text(
        CONFIG_YAML.format(state_dir=tmp_path / "state"), encoding="utf-8"
    )
    (directory / "harnesses.yaml").write_text(HARNESSES_YAML, encoding="utf-8")
    (directory / "prompts.yaml").write_text(PROMPTS_YAML, encoding="utf-8")
    return directory


@pytest.fixture()
def config(state_dir: Path) -> OrchestraConfig:
    return load_orchestra_config(state_dir)


@pytest.fixture()
def queue(tmp_path: Path) -> Iterator[JobQueue]:
    q = JobQueue(tmp_path / "state" / "queue.db")
    yield q
    q.close()


# -- core submit is the shared choke point for every dispatch path ----------


@pytest.mark.parametrize("marker", ["1", "2", "99", "banana", "abc123"])
def test_submit_rejects_non_parent_marker_and_persists_nothing(
    queue: JobQueue,
    config: OrchestraConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    marker: str,
) -> None:
    """A marked or malformed child submits nothing: rejected, zero jobs, no run dir."""
    monkeypatch.setenv(ORCHESTRA_DISPATCH_BUDGET_ENV, marker)
    with pytest.raises(SubmitError):
        submit(
            config.runtime.state_dir,
            queue,
            config,
            SESSION,
            [Assignment(goal="nested attempt", role="builder")],
        )
    assert queue.list_jobs() == ()
    # The parent-context artifact area for a fresh run must not be created.
    artifacts = tmp_path / "state" / "artifacts"
    assert not artifacts.exists() or list(artifacts.iterdir()) == []


def test_unmarked_parent_queues_builder_and_verifier(
    queue: JobQueue, config: OrchestraConfig
) -> None:
    """Positive control: an unmarked parent dispatches and its verifier follow-up queues."""
    submission = submit(
        config.runtime.state_dir,
        queue,
        config,
        SESSION,
        [Assignment(goal="top level", role="builder")],
    )
    assert [job.role for job in submission.jobs] == ["builder", "verifier"]


# -- the direct dispatch CLI is the same choke point, guarded ----------------


def _cli_config_dir(tmp_path: Path) -> Path:
    d = tmp_path / "cliconfig"
    d.mkdir()
    shutil.copy(REPO_ROOT / "prompts.yaml", d / "prompts.yaml")
    (d / "config.yaml").write_text(
        f"state_dir: {tmp_path / 'state'}\n"
        f"log_dir: {tmp_path / 'logs'}\n"
        "default_timeout: 300\nsoft_timeout: 240\nturn_limit: 60\n"
        "concurrency:\n  global: 4\n  per_session: 2\n"
        "retention_days: 90\ndefault_mode: 'on'\n",
        encoding="utf-8",
    )
    (d / "harnesses.yaml").write_text('pi:\n  harness: pi\n  command: ["pi"]\n', encoding="utf-8")
    (d / "agent-catalog.yaml").write_text(
        "default_role: builder\nmodel_limits: {}\nroles:\n"
        "  builder:\n    enabled: manual\n    harness_config: pi\n"
        '    model: "m1"\n    env: {}\n    skills: []\n'
        "    dispatch_hint: Build.\n    auto_verify: false\n",
        encoding="utf-8",
    )
    (tmp_path / "state").mkdir()
    (tmp_path / "logs").mkdir()
    return d


def test_cli_dispatch_rejects_marked_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(_cli_config_dir(tmp_path)))
    monkeypatch.setenv(ORCHESTRA_DISPATCH_BUDGET_ENV, "1")
    # The direct dispatch entry reads the parent context from stdin; supply an
    # empty stream so the guard is the only thing under test.
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    code = cli.main(["dispatch", "--session-id", SESSION, "--goal", "nested"])
    captured = capsys.readouterr()
    assert code != 0
    assert "ORCHESTRA_DISPATCH_BUDGET" in captured.err
    # No ack JSON printed, and no job was persisted.
    assert '"run_id"' not in captured.out
    q = JobQueue(tmp_path / "state" / "queue.db")
    try:
        assert q.list_jobs() == ()
    finally:
        q.close()


# -- the launched child process actually carries the reserved marker ---------

CHILD_ENV_STUB = r"""
import json, os, sys
sid = sys.argv[sys.argv.index("--session-id") + 1]
session_dir = os.environ.get("PI_CODING_AGENT_SESSION_DIR", "")
if session_dir:
    os.makedirs(session_dir, exist_ok=True)
    with open(os.path.join(session_dir, "2025-01-01T00-00-00-000Z_" + sid + ".jsonl"), "w") as f:
        f.write(json.dumps({"session_id": sid}) + "\n")
# The answer this stub returns is the marker value it actually observed.
observed = os.environ.get("ORCHESTRA_DISPATCH_BUDGET", "<unset>")
sentinel = os.environ.get("STUB_SENTINEL")
if sentinel:
    with open(sentinel, "w") as f:
        f.write(observed)


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    try:
        obj = json.loads(line)
    except ValueError:
        continue
    kind = obj.get("type")
    if kind == "prompt":
        send({"id": obj.get("id"), "type": "response", "success": True})
        send({"type": "message", "message": {"role": "assistant"}})
        send({"type": "agent_settled"})
    elif kind == "get_last_assistant_text":
        send({"type": "response", "command": "get_last_assistant_text",
              "data": {"text": observed}})
"""


@pytest.fixture()
def child_stub(tmp_path: Path) -> Path:
    path = tmp_path / "stub_pi.py"
    path.write_text(CHILD_ENV_STUB, encoding="utf-8")
    return path


@pytest.fixture()
def sessions_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "sessions"
    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(directory))
    return directory


def test_launched_child_carries_marker_over_role_env(
    child_stub: Path,
    sessions_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real launched child sees the reserved marker despite a role override.

    The marker is set AFTER the role env, so a role that tries to reopen
    dispatching (``ORCHESTRA_DISPATCH_BUDGET: "99"``) cannot, and the parent's
    own environment is left unchanged.
    """
    monkeypatch.delenv(ORCHESTRA_DISPATCH_BUDGET_ENV, raising=False)
    sentinel = tmp_path / "observed.txt"
    harness = PiHarness(
        {
            "j1": AgentPlan(
                command=("python3", str(child_stub)),
                model="m1",
                env={
                    "STUB_SENTINEL": str(sentinel),
                    # A role trying to (re)open dispatching must be overridden.
                    ORCHESTRA_DISPATCH_BUDGET_ENV: "99",
                },
            )
        },
        "budget!",
    )
    outcome = harness.execute(CommandJob("j1", ("prompt",)), Budgets())
    assert outcome.success
    # The launched child's ACTUAL environment carried the reserved marker.
    assert sentinel.read_text(encoding="utf-8") == "1"
    assert outcome.output == "1"
    # The parent's environment is untouched by the harness.
    assert os.environ.get(ORCHESTRA_DISPATCH_BUDGET_ENV) is None


def test_mark_child_dispatch_env_overrides_role_and_copies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared helper marks a copy, overrides role env, and never mutates base."""
    base = {"HOME": "/parent"}
    child = mark_child_dispatch_env(base, {ORCHESTRA_DISPATCH_BUDGET_ENV: "99", "ROLE": "x"})
    assert child[ORCHESTRA_DISPATCH_BUDGET_ENV] == "1"
    assert child["ROLE"] == "x"
    assert child["HOME"] == "/parent"
    # The parent/base mapping is never mutated.
    assert ORCHESTRA_DISPATCH_BUDGET_ENV not in base


def test_can_dispatch_marker_semantics() -> None:
    assert orchestra_can_dispatch({}) is True
    assert orchestra_can_dispatch({ORCHESTRA_DISPATCH_BUDGET_ENV: "0"}) is True
    assert orchestra_can_dispatch({ORCHESTRA_DISPATCH_BUDGET_ENV: "1"}) is False
    assert orchestra_can_dispatch({ORCHESTRA_DISPATCH_BUDGET_ENV: "2"}) is False
    assert orchestra_can_dispatch({ORCHESTRA_DISPATCH_BUDGET_ENV: "banana"}) is False
    # Absent/empty/whitespace means an unmarked parent (the restored convention).
    assert orchestra_can_dispatch({ORCHESTRA_DISPATCH_BUDGET_ENV: ""}) is True
    assert orchestra_can_dispatch({ORCHESTRA_DISPATCH_BUDGET_ENV: "   "}) is True


# -- the hidden __session process rejects a marked-child dispatch end-to-end ---


def _frame_reader(stream: Any, sink: Queue[dict[str, Any]]) -> None:
    """Parse newline-framed JSON from a child's stdout into a bounded queue."""
    for raw in stream:
        line = raw.strip()
        if not line:
            continue
        try:
            sink.put(json.loads(line))
        except ValueError:
            continue


def test_hidden_session_process_rejects_marked_child_dispatch(
    tmp_path: Path,
) -> None:
    """A real hidden ``__session`` child marked with the reserved budget returns
    the true core guard error over stdio and persists nothing.

    The autouse suite fixture clears ``ORCHESTRA_DISPATCH_BUDGET`` from the
    parent test process, so the marker is NOT inherited from the environment.
    The test injects it into the child process environment explicitly; the core
    submit choke point inside the child rejecting the dispatch (rather than
    acking a run) proves the flag actually propagated to the child despite the
    parent fixture, with no job rows and no run artifacts persisted.
    """
    # The autouse parent fixture guarantees the ambient marker is cleared in
    # this process, so any marker the child sees came only from its explicit env.
    assert os.environ.get(ORCHESTRA_DISPATCH_BUDGET_ENV) is None

    config_dir = _cli_config_dir(tmp_path)
    db = tmp_path / "state" / "queue.db"
    (tmp_path / "pi-sessions").mkdir()
    errfile = tmp_path / "session-stderr.txt"

    env = dict(os.environ)
    env["ORCHESTRA_CONFIG"] = str(config_dir)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["PI_CODING_AGENT_SESSION_DIR"] = str(tmp_path / "pi-sessions")
    # Inject the reserved marker into the CHILD only; the parent stays unmarked.
    env[ORCHESTRA_DISPATCH_BUDGET_ENV] = "1"

    with errfile.open("wb") as errhandle:
        proc = subprocess.Popen(
            [sys.executable, "-m", "orchestra", "__session", "--parent-session", SESSION],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errhandle,
            env=env,
            start_new_session=True,  # independent group, as the runtime launches it
        )

    frames: Queue[dict[str, Any]] = Queue()
    reader = threading.Thread(target=_frame_reader, args=(proc.stdout, frames), daemon=True)
    reader.start()

    reply: dict[str, Any] | None = None
    try:
        assert proc.stdin is not None
        request = {
            "kind": "request",
            "id": "d",
            "operation": "dispatch",
            "arguments": {"goal": "nested from a marked child"},
        }
        proc.stdin.write((json.dumps(request) + "\n").encode("utf-8"))
        proc.stdin.flush()

        # Bounded wait for the out-of-band dispatch reply on the shared stdout.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and reply is None:
            try:
                frame = frames.get(timeout=0.1)
            except Empty:
                if proc.poll() is not None:
                    break
                continue
            if frame.get("kind") == "reply" and frame.get("id") == "d" and "error" in frame:
                reply = frame

        assert reply is not None, (
            "no guard error reply reached the hidden __session child; stderr:\n"
            + errfile.read_text(encoding="utf-8", errors="replace")
        )
        message = str(reply["error"])
        # The reply is the real core guard cause, never a fabricated ack/success.
        assert "ORCHESTRA_DISPATCH_BUDGET" in message
        assert "disabled" in message
        assert "result" not in reply

        # The rejection persisted nothing: no job rows and no run artifacts.
        queue = JobQueue(db)
        try:
            assert queue.list_jobs() == ()
        finally:
            queue.close()
        artifacts = tmp_path / "state" / "artifacts"
        assert not artifacts.exists() or list(artifacts.iterdir()) == []
    finally:
        # Owner-scoped teardown: this test's own child group only.
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        for handle in (proc.stdin, proc.stdout):
            if handle is not None:
                handle.close()
        proc.wait(timeout=10)
