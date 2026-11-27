"""Slice 0: independent dispatcher survival across session-connection death.

Real boundaries: the real ``JobQueue``/SQLite, the real dispatcher, and the new
core ``__session`` connection process all run as OS subprocesses with their own
process groups. The only controlled boundary is a scripted ``pi`` harness RPC
stub (no live Pi, no model, no network), matching the existing connected tests.

The property under test is the runtime's central independence claim from the
session-process proposal: a session-connection/host death must not stop
healthy, already-running execution. This exercises the two mechanisms the plan
names explicitly — independent process groups and a connection/output pipe that
is not a worker lifetime dependency — and asserts the queue reaches a durable
terminal outcome after the connection process is killed.
"""

from __future__ import annotations

import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION = "pi:SURVIVE"


def _config_dir(tmp_path: Path) -> Path:
    d = tmp_path / "config"
    d.mkdir()
    shutil.copy(REPO_ROOT / "prompts.yaml", d / "prompts.yaml")
    (d / "config.yaml").write_text(
        f"state_dir: {tmp_path / 'state'}\nlog_dir: {tmp_path / 'logs'}\n"
        "default_timeout: 60\nsoft_timeout: 40\nturn_limit: 20\n"
        "concurrency:\n  global: 4\n  per_session: 2\n"
        "retention_days: 90\ndefault_mode: 'on'\n",
        encoding="utf-8",
    )
    # The controlled harness: a scripted pi RPC stub that holds execution open
    # long enough for the connection process to be killed mid-run.
    fake_pi = tmp_path / "fake-pi"
    fake_pi.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys,time\n"
        "delay=float(os.environ.get('FAKE_PI_DELAY','1.5'))\n"
        "last=''\n"
        "for raw in sys.stdin:\n"
        "    raw=raw.strip()\n"
        "    if not raw: continue\n"
        "    m=json.loads(raw)\n"
        "    if m.get('type')=='prompt':\n"
        "        time.sleep(delay)\n"
        "        sys.stdout.write(json.dumps({'id':'prompt-1','type':'response','success':True})+chr(10))\n"
        "        sys.stdout.write(json.dumps({'type':'agent_settled','aborted':False})+chr(10))\n"
        "        sys.stdout.flush()\n"
        "    elif m.get('type')=='get_last_assistant_text':\n"
        "        sys.stdout.write(json.dumps({'id':m.get('id'),'type':'response',"
        "'command':'get_last_assistant_text','data':{'text':'survived'}})+chr(10))\n"
        "        sys.stdout.flush()\n",
        encoding="utf-8",
    )
    fake_pi.chmod(0o755)
    (d / "harnesses.yaml").write_text(
        f'pi:\n  harness: pi\n  command: ["{fake_pi}"]\n', encoding="utf-8"
    )
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


def _env(config: Path, tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["ORCHESTRA_CONFIG"] = str(config)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["FAKE_PI_DELAY"] = "1.5"
    env["PI_CODING_AGENT_SESSION_DIR"] = str(tmp_path / "pi-sessions")
    (tmp_path / "pi-sessions").mkdir(exist_ok=True)
    return env


def _pgid(pid: int) -> int:
    return os.getpgid(pid)


def _descendant_procs(pid: int) -> set[int]:
    """Direct children of ``pid`` via ``ps`` (no psutil coupling required)."""
    out = subprocess.run(
        ["ps", "-o", "pid=", "-o", "ppid=", "-ax"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    kids: set[int] = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == str(pid):
            try:
                kids.add(int(parts[0]))
            except ValueError:
                pass
    return kids


def _queue_status(db: Path, job_id_like: str) -> str | None:
    if not db.exists():
        return None
    row = sqlite3.connect(db).execute(
        "SELECT status FROM jobs WHERE job_id LIKE ? ORDER BY created_at", (job_id_like,)
    ).fetchone()
    return None if row is None else str(row[0])


def test_dispatcher_survives_connection_death(tmp_path: Path) -> None:
    config = _config_dir(tmp_path)
    env = _env(config, tmp_path)
    env["FAKE_PI_DELAY"] = "3.0"  # generous in-flight window for the kill
    db = tmp_path / "state" / "queue.db"

    # (1) Real dispatcher subprocess: submits, runs a controlled real harness
    # worker, and finalizes the queue. stdout is a pipe (the connection-side).
    dispatcher = subprocess.Popen(
        [
            sys.executable, "-m", "orchestra", "dispatch",
            "--session-id", SESSION, "--goal", "survive the connection",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,  # independent process group, as the runtime uses
    )

    connection: subprocess.Popen[bytes] | None = None
    pids: set[int] = {dispatcher.pid}
    try:
        # Wait for the job row to appear and be claimed (running), so the
        # connection death is observed while real execution is genuinely in flight.
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline and _queue_status(db, "%") != "running":
            if dispatcher.poll() is not None:
                err = dispatcher.stderr.read().decode(errors="replace") if dispatcher.stderr else ""
                raise AssertionError(f"dispatcher exited early: {err}")
            time.sleep(0.05)
        assert _queue_status(db, "%") == "running", "execution must be in flight first"

        # Collect the launched execution group(s) so independence is provable.
        worker_pgids: set[int] = set()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not worker_pgids:
            for child in _descendant_procs(dispatcher.pid):
                worker_pgids.add(_pgid(child))
            time.sleep(0.05)
        assert worker_pgids, "a real harness worker execution group must be running"

        # (2) Attach the NEW core session connection process in its own group.
        connection = subprocess.Popen(
            [
                sys.executable, "-m", "orchestra", "__session",
                "--parent-session", SESSION,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=True,
        )
        pids.add(connection.pid)

        # Explicit independence: the connection and dispatcher are separate
        # process groups, and the running worker's execution group is not the
        # connection's group, so a group signal on the connection cannot reach it.
        conn_pgid = _pgid(connection.pid)
        disp_pgid = _pgid(dispatcher.pid)
        assert conn_pgid != disp_pgid, "connection and dispatcher are separate groups"
        assert conn_pgid not in worker_pgids, "worker execution group is not the connection group"

        # (3) Kill the session-connection process while execution is running.
        os.killpg(conn_pgid, signal.SIGKILL)
        connection.wait(timeout=10)
        assert connection.returncode is not None
        assert _queue_status(db, "%") == "running", (
            "killing the connection must not have finalized the running job"
        )

        # Disconnect-safe stdio: break the dispatcher's connection-side stdout
        # pipe (a broken output pipe must not stop healthy execution/finalization).
        assert dispatcher.stdout is not None
        dispatcher.stdout.close()

        # (4) Execution reaches a durable terminal outcome on its own.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and _queue_status(db, "%") not in {
            "succeeded", "failed", "skipped",
        }:
            time.sleep(0.05)
        assert _queue_status(db, "%") == "succeeded", "execution survived connection death"

        # The dispatcher exits on its own after the broken-pipe return attempt.
        try:
            dispatcher.wait(timeout=20)
        except subprocess.TimeoutExpired:  # pragma: no cover - flake guard
            pytest.fail("dispatcher did not exit after connection death")
    finally:
        for pid in pids:
            try:
                os.killpg(_pgid(pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
