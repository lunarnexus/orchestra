"""Connected execution tests: real dispatch → independent worker → persisted
outcome → native delivery acknowledged. Plus parent-kill survival, launch
failure authoritative transition, and admission-release → evaluation.

Boundaries:
- Real JobQueue/SQLite (durable state proven by SQL reads).
- Real independent worker subprocess (__run).
- Controlled Pi RPC stub (no live model, no network).
- No live Pi, no host extension, no real credentials.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from orchestra.artifacts import Response, append
from orchestra.queue import JobQueue
from orchestra.session import (
    KIND_NATIVE_REQUEST,
    KIND_NATIVE_RESULT,
    KIND_REPLY,
    KIND_REQUEST,
    SessionRuntime,
    encode_line,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION = "pi:EXEC1"


def _config_dir(tmp_path: Path, *, delay: float = 0.3) -> Path:
    d = tmp_path / "config"
    d.mkdir()
    shutil.copy(REPO_ROOT / "prompts.yaml", d / "prompts.yaml")
    (d / "config.yaml").write_text(
        f"state_dir: {tmp_path / 'state'}\nlog_dir: {tmp_path / 'logs'}\n"
        "default_timeout: 60\nsoft_timeout: 50\nturn_limit: 20\n"
        "concurrency:\n  global: 4\n  per_session: 2\n"
        "retention_days: 90\ndefault_mode: 'on'\n",
        encoding="utf-8",
    )
    fake_pi = tmp_path / "fake-pi"
    fake_pi.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys,time\n"
        f"delay=float(os.environ.get('FAKE_PI_DELAY','{delay}'))\n"
        "for raw in sys.stdin:\n"
        "    raw=raw.strip()\n"
        "    if not raw: continue\n"
        "    m=json.loads(raw)\n"
        "    if m.get('type')=='prompt':\n"
        "        time.sleep(delay)\n"
        "        sys.stdout.write(json.dumps({'id':m.get('id','prompt-1'),"
        "'type':'response','success':True})+chr(10))\n"
        "        sys.stdout.write(json.dumps({'type':'agent_settled','aborted':False})+chr(10))\n"
        "        sys.stdout.flush()\n"
        "    elif m.get('type')=='get_last_assistant_text':\n"
        "        sys.stdout.write(json.dumps({'id':m.get('id'),"
        "'type':'response','command':'get_last_assistant_text',"
        "'data':{'text':'exec done'}})+chr(10))\n"
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
        "    dispatch_hint: Build.\n    auto_verify: false\n"
        "    parent_context: true\n",
        encoding="utf-8",
    )
    (tmp_path / "state").mkdir()
    (tmp_path / "logs").mkdir()
    return d


def _env(config: Path, tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["ORCHESTRA_CONFIG"] = str(config)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    (tmp_path / "pi-sessions").mkdir(exist_ok=True)
    env["PI_CODING_AGENT_SESSION_DIR"] = str(tmp_path / "pi-sessions")
    return env


def _queue_status(db: Path, run_id: str) -> str | None:
    if not db.exists():
        return None
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT status FROM jobs WHERE run_id = ? ORDER BY sequence LIMIT 1",
        (run_id,),
    ).fetchone()
    conn.close()
    return None if row is None else str(row[0])


def _all_statuses(db: Path, run_id: str) -> list[str]:
    if not db.exists():
        return []
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT status FROM jobs WHERE run_id = ? ORDER BY sequence", (run_id,)
    ).fetchall()
    conn.close()
    return [str(r[0]) for r in rows]


def _wait_for(cond: Any, timeout: float = 30.0, interval: float = 0.1) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(interval)
    return bool(cond())


class _RecordingSend:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def __call__(self, message: dict[str, Any]) -> None:
        with self._lock:
            self.sent.append(message)

    def by_kind(self, kind: str) -> list[dict[str, Any]]:
        with self._lock:
            return [m for m in self.sent if m.get("kind") == kind]

    def find(self, kind: str, operation: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            for m in self.sent:
                if m.get("kind") == kind and (
                    operation is None or m.get("operation") == operation
                ):
                    return m
        return None


# ---------------------------------------------------------------------------
# Test 1: Normal dispatch → worker → persisted outcome → deliver_report → ack
# ---------------------------------------------------------------------------


def test_full_dispatch_delivery_journey(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real dispatch → native context → __run worker → succeeded → delivery → ack."""
    config_dir = _config_dir(tmp_path, delay=0.5)
    db = tmp_path / "state" / "queue.db"

    # In-process runtime with real queue.
    from orchestra.config import load_orchestra_config

    monkeypatch.setenv("ORCHESTRA_CONFIG", str(config_dir))
    monkeypatch.setenv("PYTHONPATH", str(REPO_ROOT / "src"))
    pi_sessions = tmp_path / "pi-sessions"
    pi_sessions.mkdir(exist_ok=True)
    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(pi_sessions))

    config = load_orchestra_config()
    queue = JobQueue(db)
    recorder = _RecordingSend()
    runtime = SessionRuntime(
        queue=queue,
        parent_session=SESSION,
        state_dir=config.runtime.state_dir,
        prompts=config.prompts,
        send=recorder,
        mode="on",
        interval=1.0,  # short backstop for test
        config=config,
    )

    try:
        # 1) Send dispatch request.
        dispatch_msg = {
            "kind": KIND_REQUEST,
            "id": 1,
            "operation": "dispatch",
            "arguments": {"goal": "do the thing"},
        }
        reply = runtime.handle(dispatch_msg)
        assert reply is None, "dispatch reply is out-of-band"

        # 2) The context request should arrive (role has parent_context: true).
        ctx_req = _wait_for(lambda: recorder.find(KIND_NATIVE_REQUEST, "get_parent_context") is not None, timeout=10)
        assert ctx_req, "native context request must arrive"
        ctx_frame = recorder.find(KIND_NATIVE_REQUEST, "get_parent_context")
        assert ctx_frame is not None

        # 3) Resolve context with native_result.
        runtime.handle({
            "kind": KIND_NATIVE_RESULT,
            "id": ctx_frame["id"],
            "accepted": True,
            "data": {"text": "parent context from test"},
        })

        # 4) Wait for the dispatch ack (out-of-band reply with run_id).
        ack_ok = _wait_for(
            lambda: any(
                m.get("kind") == KIND_REPLY and m.get("id") == 1 and "result" in m
                for m in recorder.sent
            ),
            timeout=20,
        )
        assert ack_ok, f"dispatch ack must arrive; sent so far: {recorder.sent}"
        ack = next(
            m for m in recorder.sent
            if m.get("kind") == KIND_REPLY and m.get("id") == 1 and "result" in m
        )
        run_id = ack["result"]["run_id"]
        assert run_id, "ack must contain run_id"

        # 5) Worker subprocess runs; wait for terminal outcome.
        terminal_ok = _wait_for(
            lambda: _queue_status(db, run_id) in {"succeeded", "failed", "skipped"},
            timeout=30,
        )
        assert terminal_ok, (
            f"job must reach terminal; got: {_queue_status(db, run_id)}"
        )
        assert _queue_status(db, run_id) == "succeeded"

        # 6) Evaluator assembles report and requests delivery.
        deliver_ok = _wait_for(
            lambda: recorder.find(KIND_NATIVE_REQUEST, "deliver_report") is not None,
            timeout=15,
        )
        assert deliver_ok, f"deliver_report must be emitted; sent: {recorder.by_kind(KIND_NATIVE_REQUEST)}"
        deliver_frame = recorder.find(KIND_NATIVE_REQUEST, "deliver_report")
        assert deliver_frame is not None
        # The deliver_report must carry core-produced text with run_id.
        text = deliver_frame["arguments"]["text"]
        assert run_id in text, "report text must include the run id"

        # 7) Accept delivery → acknowledged.
        runtime.handle({
            "kind": KIND_NATIVE_RESULT,
            "id": deliver_frame["id"],
            "accepted": True,
        })

        # 8) Verify reported membership.
        snap = queue.snapshot(SESSION)
        assert run_id in snap.reported_run_ids, "run must be in reported membership"
        assert not snap.ready, "run already reported, no further report expected"

        # 9) No duplicate delivery.
        time.sleep(1.5)  # one backstop cycle
        deliver_frames = [
            m for m in recorder.sent
            if m.get("kind") == KIND_NATIVE_REQUEST
            and m.get("operation") == "deliver_report"
        ]
        assert len(deliver_frames) == 1, "exactly one delivery request"
    finally:
        runtime.close()
        queue.close()


# ---------------------------------------------------------------------------
# Test 1b: A very fast worker must never deliver its report before the caller
# receives the dispatch acknowledgement. The admission stays open until the
# acceptance reply is emitted, so readiness cannot flip true (and no report can
# be delivered) until the ack frame has left the runtime. Deterministic: the
# launch is replaced by a synchronous completion of the controlled rows plus
# the completion event a real worker observer would raise.
# ---------------------------------------------------------------------------


def test_dispatch_ack_precedes_fast_worker_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A worker that finishes during launch must not deliver before the ack."""
    config_dir = _config_dir(tmp_path)
    from orchestra.config import load_orchestra_config

    monkeypatch.setenv("ORCHESTRA_CONFIG", str(config_dir))
    monkeypatch.setenv("PYTHONPATH", str(REPO_ROOT / "src"))
    pi_sessions = tmp_path / "pi-sessions"
    pi_sessions.mkdir(exist_ok=True)
    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(pi_sessions))

    config = load_orchestra_config()
    db = tmp_path / "state" / "queue.db"
    state_dir = config.runtime.state_dir
    queue = JobQueue(db)
    recorder = _RecordingSend()

    runtime = SessionRuntime(
        queue=queue,
        parent_session=SESSION,
        state_dir=state_dir,
        prompts=config.prompts,
        send=recorder,
        mode="on",
        interval=1.0,
        config=config,
    )

    # A worker that completes its controlled rows synchronously — as fast as
    # possible, finishing during launch — then fires the completion event the
    # real worker-observer thread raises on subprocess exit.
    def _fast_launch(submission: Any) -> None:
        while True:
            job = queue.claim_next(
                global_limit=4, per_session_limit=2, run_id=submission.run_id
            )
            if job is None:
                break
            append(
                state_dir,
                submission.run_id,
                Response(
                    job_id=job.job_id,
                    timestamp=datetime.now(UTC).isoformat(),
                    response="fast worker done",
                ),
            )
            queue.complete_job(job.job_id, "succeeded")
        runtime.request_evaluation()

    monkeypatch.setattr(SessionRuntime, "_launch_worker", staticmethod(_fast_launch))

    try:
        reply = runtime.handle(
            {
                "kind": KIND_REQUEST,
                "id": 1,
                "operation": "dispatch",
                "arguments": {"goal": "finish instantly"},
            }
        )
        assert reply is None

        ctx_found = _wait_for(
            lambda: recorder.find(KIND_NATIVE_REQUEST, "get_parent_context") is not None,
            timeout=10,
        )
        assert ctx_found, "native context request must arrive"
        ctx_frame = recorder.find(KIND_NATIVE_REQUEST, "get_parent_context")
        assert ctx_frame is not None
        runtime.handle(
            {
                "kind": KIND_NATIVE_RESULT,
                "id": ctx_frame["id"],
                "accepted": True,
                "data": {"text": "ctx"},
            }
        )

        # Both the ack and the (eventual) delivery must appear.
        both_ok = _wait_for(
            lambda: any(
                m.get("kind") == KIND_REPLY and m.get("id") == 1 and "result" in m
                for m in recorder.sent
            )
            and recorder.find(KIND_NATIVE_REQUEST, "deliver_report") is not None,
            timeout=15,
        )
        assert both_ok, f"ack and report must both arrive; sent: {recorder.sent}"

        ack_index = next(
            i
            for i, m in enumerate(recorder.sent)
            if m.get("kind") == KIND_REPLY and m.get("id") == 1 and "result" in m
        )
        report_index = next(
            i
            for i, m in enumerate(recorder.sent)
            if m.get("kind") == KIND_NATIVE_REQUEST
            and m.get("operation") == "deliver_report"
        )
        assert ack_index < report_index, (
            "dispatch ack must precede the report: the caller must receive the "
            f"ack before any report is delivered (ack@{ack_index}, report@{report_index})"
        )
    finally:
        runtime.close()
        queue.close()


# ---------------------------------------------------------------------------
# Test 2: Parent-kill survival (kill __session PARENT that launched worker)
# ---------------------------------------------------------------------------


def test_parent_kill_survival(tmp_path: Path) -> None:
    """Kill the __session PARENT process; the launched worker survives to success."""
    config_dir = _config_dir(tmp_path, delay=3.0)
    db = tmp_path / "state" / "queue.db"
    env = _env(config_dir, tmp_path)
    env["FAKE_PI_DELAY"] = "3.0"

    # Launch the real __session as a subprocess.
    session_proc = subprocess.Popen(
        [sys.executable, "-m", "orchestra", "__session", "--parent-session", SESSION],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,
    )

    try:
        assert session_proc.stdin is not None
        assert session_proc.stdout is not None

        # Send dispatch request.
        req = {"kind": "request", "id": 1, "operation": "dispatch", "arguments": {"goal": "survive"}}
        session_proc.stdin.write((encode_line(req) + "\n").encode("utf-8"))
        session_proc.stdin.flush()

        # Read frames from stdout until we see the native context request.
        run_id = _read_until_dispatch_ack(session_proc)
        assert run_id, "must get run_id from dispatch ack"

        # Wait for the worker to be running (harness holds for 3s).
        running_ok = _wait_for(
            lambda: _queue_status(db, run_id) == "running", timeout=10
        )
        assert running_ok, f"worker must be running; status: {_queue_status(db, run_id)}"

        # Prove overlap: the session parent is alive AND the job is running.
        assert session_proc.poll() is None, "session must be alive when job is running"

        # Kill the __session PARENT process group.
        pgid = os.getpgid(session_proc.pid)
        os.killpg(pgid, signal.SIGKILL)
        session_proc.wait(timeout=5)

        # Verify session is dead but job is STILL running (not finalized by kill).
        assert _queue_status(db, run_id) == "running", (
            "killing session must not finalize the running job"
        )

        # Wait for the worker to complete independently.
        terminal_ok = _wait_for(
            lambda: _queue_status(db, run_id) in {"succeeded", "failed", "skipped"},
            timeout=30,
        )
        assert terminal_ok, "worker must reach terminal after parent kill"
        assert _queue_status(db, run_id) == "succeeded", (
            f"worker must succeed independently; got {_queue_status(db, run_id)}"
        )
    finally:
        try:
            os.killpg(os.getpgid(session_proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def _read_until_dispatch_ack(proc: subprocess.Popen[bytes]) -> str | None:
    """Read JSON frames from stdout until the dispatch reply with run_id arrives."""
    assert proc.stdout is not None
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        import json
        try:
            frame = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        # If it's a native context request, accept it.
        if frame.get("kind") == "native_request" and frame.get("operation") == "get_parent_context":
            assert proc.stdin is not None
            resp = {"kind": "native_result", "id": frame["id"], "accepted": True, "data": {"text": "ctx"}}
            proc.stdin.write((encode_line(resp) + "\n").encode("utf-8"))
            proc.stdin.flush()
            continue
        # Dispatch reply carries the ack.
        if frame.get("kind") == "reply" and frame.get("id") == 1:
            result = frame.get("result")
            if isinstance(result, dict):
                return str(result.get("run_id", ""))
    return None


# ---------------------------------------------------------------------------
# Test 3: Launch failure → fail_unstarted authoritative transition
# ---------------------------------------------------------------------------


def test_launch_failure_fails_unstarted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Popen launch failure must fail unstarted jobs, not leave them pending."""
    config_dir = _config_dir(tmp_path)
    from orchestra.config import load_orchestra_config

    monkeypatch.setenv("ORCHESTRA_CONFIG", str(config_dir))
    monkeypatch.setenv("PYTHONPATH", str(REPO_ROOT / "src"))
    pi_sessions = tmp_path / "pi-sessions"
    pi_sessions.mkdir(exist_ok=True)
    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(pi_sessions))

    config = load_orchestra_config()
    db = tmp_path / "state" / "queue.db"
    queue = JobQueue(db)
    recorder = _RecordingSend()

    runtime = SessionRuntime(
        queue=queue,
        parent_session=SESSION,
        state_dir=config.runtime.state_dir,
        prompts=config.prompts,
        send=recorder,
        mode="on",
        interval=1.0,
        config=config,
    )

    # Monkeypatch Popen to raise (simulates binary missing / fork failure).

    def _failing_popen(*args: Any, **kwargs: Any) -> Any:
        raise OSError("injected launch failure")

    monkeypatch.setattr(subprocess, "Popen", _failing_popen)

    try:
        dispatch_msg = {
            "kind": KIND_REQUEST,
            "id": 1,
            "operation": "dispatch",
            "arguments": {"goal": "will fail to launch"},
        }
        reply = runtime.handle(dispatch_msg)
        assert reply is None  # out-of-band

        # Resolve the native context request.
        ctx_found = _wait_for(
            lambda: recorder.find(KIND_NATIVE_REQUEST, "get_parent_context") is not None,
            timeout=10,
        )
        assert ctx_found
        ctx_frame = recorder.find(KIND_NATIVE_REQUEST, "get_parent_context")
        assert ctx_frame is not None
        runtime.handle({
            "kind": KIND_NATIVE_RESULT,
            "id": ctx_frame["id"],
            "accepted": True,
            "data": {"text": "ctx"},
        })

        # Wait for the error reply (launch failure).
        error_ok = _wait_for(
            lambda: any(
                m.get("kind") == KIND_REPLY and m.get("id") == 1 and "error" in m
                for m in recorder.sent
            ),
            timeout=10,
        )
        assert error_ok, f"must get error reply; sent: {recorder.sent}"

        # Wait for the evaluator to reconcile.
        time.sleep(1.0)

        # Jobs must be failed (not stuck pending).
        snap = queue.snapshot(SESSION)
        for job in snap.jobs:
            assert job.status == "failed", (
                f"job {job.job_id} must be failed after launch failure, got {job.status}"
            )
        # The error reply must mention "launch".
        err_msg = next(
            m for m in recorder.sent
            if m.get("kind") == KIND_REPLY and m.get("id") == 1 and "error" in m
        )
        assert "launch" in err_msg["error"].lower()

        # The accepted-but-unlaunched jobs must still assemble an inspectable
        # report carrying the real launch cause (a real Response record was
        # written for the failed rows), not a "failed but no response" gap.
        deliver_ok = _wait_for(
            lambda: recorder.find(KIND_NATIVE_REQUEST, "deliver_report") is not None,
            timeout=10,
        )
        assert deliver_ok, (
            "a definite launch failure must still produce a reportable return; "
            f"sent: {recorder.by_kind(KIND_NATIVE_REQUEST)}"
        )
        deliver_frame = recorder.find(KIND_NATIVE_REQUEST, "deliver_report")
        assert deliver_frame is not None
        text = deliver_frame["arguments"]["text"].lower()
        assert "launch" in text, (
            f"report must carry the real launch-failure cause; got: {text}"
        )

        # The native receipt of that failure report must be acknowledged.
        runtime.handle(
            {
                "kind": KIND_NATIVE_RESULT,
                "id": deliver_frame["id"],
                "accepted": True,
            }
        )
        snap = queue.snapshot(SESSION)
        reported = set(snap.reported_run_ids)
        run_id = snap.jobs[0].run_id
        assert run_id in reported, (
            f"failure-report receipt must acknowledge the run; reported={reported}"
        )
        assert not snap.ready, "acknowledged failure run must not re-report"
    finally:
        runtime.close()
        queue.close()


# ---------------------------------------------------------------------------
# Test 4: Failed role → admission released → shared evaluation path
# ---------------------------------------------------------------------------


def test_failed_role_releases_admission_and_evaluates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dispatch for an unknown role releases admission and wakes evaluation."""
    config_dir = _config_dir(tmp_path)
    from orchestra.config import load_orchestra_config

    monkeypatch.setenv("ORCHESTRA_CONFIG", str(config_dir))
    monkeypatch.setenv("PYTHONPATH", str(REPO_ROOT / "src"))
    pi_sessions = tmp_path / "pi-sessions"
    pi_sessions.mkdir(exist_ok=True)
    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(pi_sessions))

    config = load_orchestra_config()
    db = tmp_path / "state" / "queue.db"
    queue = JobQueue(db)
    recorder = _RecordingSend()

    runtime = SessionRuntime(
        queue=queue,
        parent_session=SESSION,
        state_dir=config.runtime.state_dir,
        prompts=config.prompts,
        send=recorder,
        mode="on",
        interval=1.0,
        config=config,
    )

    try:
        # Submit a job directly (simulating a prior accepted run already terminal).
        run_id_for_existing = "existing-run"
        queue.add_job(
            run_id=run_id_for_existing,
            parent_session=SESSION,
            role="builder",
            model="m1",
        )
        # Claim and complete it so it becomes terminal.
        job = queue.claim_next(global_limit=4, per_session_limit=2, run_id=run_id_for_existing)
        assert job is not None
        queue.complete_job(job.job_id, "succeeded")

        # Write minimal artifacts so assemble_session can recall the run.
        artifacts_dir = tmp_path / "state" / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        artifact = artifacts_dir / f"{run_id_for_existing}.jsonl"
        import json as _json
        task_rec = {"record_type": "task", "job_id": job.job_id, "timestamp": "2024-01-01T00:00:00Z", "prompt": "prior task", "role": "builder"}
        resp_rec = {"record_type": "response", "job_id": job.job_id, "timestamp": "2024-01-01T00:01:00Z", "response": "prior done"}
        artifact.write_text(_json.dumps(task_rec) + "\n" + _json.dumps(resp_rec) + "\n", encoding="utf-8")

        # Now dispatch with an invalid role → Submit will fail.
        dispatch_msg = {
            "kind": KIND_REQUEST,
            "id": 2,
            "operation": "dispatch",
            "arguments": {"goal": "bad role", "role": "nonexistent-role"},
        }
        reply = runtime.handle(dispatch_msg)
        assert reply is None  # out-of-band

        # The dispatch thread will fail and release the admission.
        # Wait for the error reply.
        error_ok = _wait_for(
            lambda: any(
                m.get("kind") == KIND_REPLY and m.get("id") == 2 and "error" in m
                for m in recorder.sent
            ),
            timeout=10,
        )
        assert error_ok, f"must get error for invalid role; sent: {recorder.sent}"

        # After evaluation, the existing-run should be ready (terminal + not reported).
        snap_ok = _wait_for(
            lambda: queue.snapshot(SESSION).ready,
            timeout=5,
        )
        assert snap_ok, "session must become ready after failed dispatch releases admission"
        snap = queue.snapshot(SESSION)
        assert "existing-run" in snap.ready_run_ids
        # No open admissions remain.
        assert snap.open_admissions == ()
    finally:
        runtime.close()
        queue.close()


# ---------------------------------------------------------------------------
# Test 5: real worker execution-PROGRESS push wakes the SAME evaluator with a
# running-only status BEFORE the periodic backstop or any manual host event,
# and strictly before the final report — with the running overlap recorded.
# ---------------------------------------------------------------------------


def _status_texts(recorder: _RecordingSend) -> list[str]:
    return [m["text"] for m in recorder.by_kind("status")]


def _is_running_meter(text: str) -> bool:
    return text.startswith("Orchestra: running ") and "no running jobs" not in text


def test_worker_progress_push_wakes_evaluator_before_backstop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A genuine dispatcher JobEvent (running) reaches the connection over the
    core-worker notification channel and wakes the shared evaluator, WITHOUT any
    host event or the 10s backstop.

    The connection interval is set absurdly high so the periodic backstop can
    never fire during the run, and no host event is ever sent — the only wake
    that can push a running-only meter while a job is running is the worker's
    real progress event. The overlap is recorded: the first running meter is
    observed while the durable queue still shows the job running, and strictly
    before the final report request.
    """
    config_dir = _config_dir(tmp_path, delay=4.0)  # long RUNNING window
    db = tmp_path / "state" / "queue.db"
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(config_dir))
    monkeypatch.setenv("PYTHONPATH", str(REPO_ROOT / "src"))
    pi_sessions = tmp_path / "pi-sessions"
    pi_sessions.mkdir(exist_ok=True)
    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(pi_sessions))

    from orchestra.config import load_orchestra_config

    config = load_orchestra_config()
    queue = JobQueue(db)
    recorder = _RecordingSend()
    runtime = SessionRuntime(
        queue=queue,
        parent_session=SESSION,
        state_dir=config.runtime.state_dir,
        prompts=config.prompts,
        send=recorder,
        mode="on",
        interval=3600.0,  # backstop effectively disabled for the test window
        config=config,
    )
    try:
        reply = runtime.handle(
            {
                "kind": KIND_REQUEST,
                "id": 1,
                "operation": "dispatch",
                "arguments": {"goal": "show real progress"},
            }
        )
        assert reply is None

        assert _wait_for(
            lambda: recorder.find(KIND_NATIVE_REQUEST, "get_parent_context"), timeout=10
        )
        ctx = recorder.find(KIND_NATIVE_REQUEST, "get_parent_context")
        assert ctx is not None
        runtime.handle(
            {
                "kind": KIND_NATIVE_RESULT,
                "id": ctx["id"],
                "accepted": True,
                "data": {"text": "parent context"},
            }
        )

        ack_ok = _wait_for(
            lambda: any(
                m.get("kind") == KIND_REPLY and m.get("id") == 1 and "result" in m
                for m in recorder.sent
            ),
            timeout=20,
        )
        assert ack_ok, f"dispatch ack must arrive; got: {recorder.sent}"
        ack = next(
            m
            for m in recorder.sent
            if m.get("kind") == KIND_REPLY and m.get("id") == 1 and "result" in m
        )
        run_id = ack["result"]["run_id"]

        # Record the running OVERLAP: capture the exact instant a running-only
        # meter is observed AND the durable queue still reports the job running.
        overlap: dict[str, Any] = {}

        def saw_running_overlap() -> bool:
            texts = _status_texts(recorder)
            running_push = any(_is_running_meter(t) for t in texts)
            durable_running = _queue_status(db, run_id) == "running"
            if running_push and durable_running and not overlap:
                overlap["push_index"] = next(
                    i
                    for i, m in enumerate(recorder.sent)
                    if m.get("kind") == "status" and _is_running_meter(m.get("text", ""))
                )
                overlap["durable"] = _all_statuses(db, run_id)
            return running_push and durable_running

        assert _wait_for(saw_running_overlap, timeout=25), (
            "a running-only status push driven by the worker progress event "
            f"must arrive while the job is still running; statuses: {_status_texts(recorder)}; "
            f"durable: {_all_statuses(db, run_id)}"
        )

        # The running push must come BEFORE the final report request.
        deliver_ok = _wait_for(
            lambda: recorder.find(KIND_NATIVE_REQUEST, "deliver_report") is not None,
            timeout=30,
        )
        assert deliver_ok, "the run must eventually produce a final report"
        deliver_index = next(
            i
            for i, m in enumerate(recorder.sent)
            if m.get("kind") == KIND_NATIVE_REQUEST
            and m.get("operation") == "deliver_report"
        )
        assert overlap["push_index"] < deliver_index, (
            "the real running status push must precede the final report; "
            f"running@{overlap['push_index']} report@{deliver_index}"
        )
        # Overlap was genuinely recorded (a row was running when the push landed).
        assert "running" in overlap["durable"]
    finally:
        runtime.close()
        queue.close()


# ---------------------------------------------------------------------------
# Test 6: Worker survival — a CLOSED notification reader (the connection is
# gone) must never stop healthy execution or its durable finalization.
# ---------------------------------------------------------------------------


def test_worker_survives_closed_notify_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The worker keeps running and durably finalizes even when its wake-channel
    reader is closed. Every notify write hits a broken pipe; the dispatcher and
    the notifier both swallow it, so execution and durable record are unaffected.
    """
    config_dir = _config_dir(tmp_path, delay=2.0)
    db = tmp_path / "state" / "queue.db"
    env = _env(config_dir, tmp_path)

    from orchestra.config import load_orchestra_config
    from orchestra.submit import Assignment, submit

    monkeypatch.setenv("ORCHESTRA_CONFIG", str(config_dir))
    monkeypatch.setenv("PYTHONPATH", str(REPO_ROOT / "src"))
    pi_sessions = tmp_path / "pi-sessions"
    pi_sessions.mkdir(exist_ok=True)
    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(pi_sessions))

    config = load_orchestra_config()
    queue = JobQueue(db)
    # Durably accept a run through the real Submit path (builder row + payload).
    submission = submit(
        config.runtime.state_dir,
        queue,
        config,
        SESSION,
        [Assignment(goal="survive a closed reader")],
        context_provider=lambda: "parent context",
    )
    run_id = submission.run_id
    plan = {
        "run_id": run_id,
        "payloads": {jid: list(argv) for jid, argv in submission.payloads.items()},
    }

    read_fd, write_fd = os.pipe()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "orchestra",
            "__run",
            "--run-id",
            run_id,
            "--notify-fd",
            str(write_fd),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        start_new_session=True,
        pass_fds=(write_fd,),
    )
    os.close(write_fd)
    # Close the reader IMMEDIATELY: the "connection" is gone before the worker
    # can emit a single progress event. All wake writes must be harmlessly lost.
    os.close(read_fd)

    try:
        assert proc.stdin is not None
        proc.stdin.write((json.dumps(plan) + "\n").encode("utf-8"))
        proc.stdin.close()

        # The worker must reach a durable terminal outcome despite the dead reader.
        terminal_ok = _wait_for(
            lambda: _queue_status(db, run_id) in {"succeeded", "failed", "skipped"},
            timeout=40,
        )
        assert terminal_ok, (
            f"execution must finalize despite a closed reader; "
            f"status: {_queue_status(db, run_id)}"
        )
        assert _queue_status(db, run_id) == "succeeded", (
            f"healthy execution must succeed despite the closed reader; "
            f"got {_queue_status(db, run_id)}"
        )
        # The worker must exit cleanly (a broken wake pipe never crashes it).
        assert proc.wait(timeout=20) == 0, "worker must exit 0 with a dead reader"
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        queue.close()
