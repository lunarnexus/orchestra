"""Pi dispatch transport, transcript timeout, reload, and compaction recovery.

Tests use the real extension/core with a simulated host boundary and real
supervision for timeout recovery. Live-host verification is separate.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

from orchestra.state import (
    STATUS_DONE,
    STATUS_INCOMPLETE,
    TERMINAL_STATUSES,
    StateStore,
)
from tests.helpers import wait_for_condition
from tests.test_pi_delivery_flow import (
    DriverClient,
    _cleanup_active_runs,
    _driver_env,
    _find_pi_package,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DRIVER_PATH = REPO_ROOT / "tests" / "pi_driver.mjs"
EXTENSION_PATH = REPO_ROOT / "extensions" / "pi" / "orchestra" / "index.ts"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node executable not found",
)


def _session_id() -> str:
    return f"pi-edge-{uuid.uuid4().hex[:12]}"


def _make_corrupting_shim(tmp_path: Path, python_executable: str) -> Path:
    """Create an 'orchestra' shim that corrupts `do` output after core accepts.

    The shim lets the real `orchestra do` command run (so the core dispatch
    succeeds and the supervisor is spawned), but replaces the stdout with
    garbage so the extension cannot parse the dispatch payload.
    A control file (.shim_corrupt_do) gates the corruption.
    """
    shim_dir = tmp_path / "shim-corrupt"
    shim_dir.mkdir(exist_ok=True)
    shim = shim_dir / "orchestra"
    shim.write_text(
        f"""#!/bin/sh
CONFIG_DIR="${{ORCHESTRA_CONFIG:-}}"
if [ -n "$CONFIG_DIR" ] && [ -f "$CONFIG_DIR/.shim_corrupt_do" ]; then
  for arg in "$@"; do
    if [ "$arg" = "do" ]; then
      # Run the real command to let core accept the dispatch.
      {python_executable} -m orchestra "$@" > /dev/null 2>&1
      # Emit corrupted output instead of the real JSON.
      echo "CORRUPTED_TRANSPORT_RESPONSE"
      exit 0
    fi
  done
fi
exec {python_executable} -m orchestra "$@"
""",
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return shim_dir


class _BoundedDriverReader:
    """Thread-based JSON-line reader with bounded deadline waits."""

    def __init__(self, process: subprocess.Popen[str]) -> None:
        self._process = process
        self._lock = threading.Lock()
        self._events: list[dict[str, Any]] = []
        self._waiters: list[threading.Event] = []
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        assert self._process.stdout is not None
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def _read_loop(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            with self._lock:
                self._events.append(payload)
                for w in self._waiters:
                    w.set()

    def wait_for_event(
        self, kind: str | tuple[str, ...], *, timeout: float = 30.0
    ) -> dict[str, Any] | None:
        wanted = {kind} if isinstance(kind, str) else set(kind)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                for i, ev in enumerate(self._events):
                    if ev.get("kind") in wanted:
                        self._events.pop(i)
                        return ev
            waiter = threading.Event()
            with self._lock:
                self._waiters.append(waiter)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            waiter.wait(timeout=remaining)
            with self._lock:
                if waiter in self._waiters:
                    self._waiters.remove(waiter)
        return None

    def send(self, cmd: dict[str, Any]) -> None:
        assert self._process.stdin is not None
        self._process.stdin.write(json.dumps(cmd) + "\n")
        self._process.stdin.flush()

    def stop(self) -> None:
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._process is not None:
            try:
                self._process.kill()
                self._process.wait(timeout=5.0)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Test 1: Malformed dispatch transport response
# ---------------------------------------------------------------------------


def test_pi_malformed_dispatch_response_run_continues(
    tmp_path: Path,
    runtime_files_factory: Any,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    """Corrupted dispatch response: run is accepted by core but extension cannot parse it.

    The extension reports acceptance with an unknown run id, does not redispatch,
    and recovers the session report through actual chat confirmation.
    """
    pi_pkg = _find_pi_package()
    if pi_pkg is None:
        pytest.skip("Pi coding-agent package not found at ~/.pi/agent/install")

    config_path, _, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "worker ok"],
    )
    store = StateStore(db_path)
    sid = _session_id()
    session_key = f"pi:{sid}"

    # Build a driver env that uses the corrupting shim.
    env = _driver_env(tmp_path, config_path, python_executable, pi_pkg)
    corrupt_shim_dir = _make_corrupting_shim(tmp_path, python_executable)
    env["PATH"] = f"{corrupt_shim_dir}{os.pathsep}{env.get('PATH', '/usr/bin:/bin')}"
    # Enable corruption.
    (config_path.parent / ".shim_corrupt_do").write_text("1", encoding="utf-8")

    process: subprocess.Popen[str] | None = None
    reader: _BoundedDriverReader | None = None
    run_id: str | None = None
    try:
        process = subprocess.Popen(
            ["node", str(DRIVER_PATH)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            cwd=str(REPO_ROOT),
            text=True,
        )
        reader = _BoundedDriverReader(process)
        reader.start()

        # Wait for ready.
        ready = reader.wait_for_event("ready", timeout=15.0)
        assert ready is not None, "driver did not emit ready"

        # Session start.
        reader.send({"cmd": "session_start", "id": sid})
        time.sleep(0.5)

        # Dispatch: the core accepts the run, but the response is corrupted.
        reader.send({"cmd": "dispatch", "goal": "malformed transport test"})
        # The driver emits "ack" when the dispatch tool resolves, or "error"
        # when the extension's dispatch path throws (parseDispatchPayload
        # JSON.parse on the corrupted stdout). Wait for either, bounded.
        result = reader.wait_for_event(("ack", "error"), timeout=30.0)
        assert result is not None, "no dispatch result event (ack or error) received"

        # However, the core DID accept the dispatch: a run exists in the DB.
        runs = store.list_runs(session_key)
        assert len(runs) == 1, f"expected 1 run in core, got {len(runs)}"
        run_id = runs[0].run_id
        record = store.get_run(run_id)
        assert record.orchestrator_session_id == session_key

        # The run eventually completes (supervisor is running).
        assert wait_for_condition(
            lambda: store.get_run(run_id).status in TERMINAL_STATUSES, timeout=30
        )
        final = store.get_run(run_id)
        assert final.status == STATUS_DONE
        assert "worker ok" in (final.result_summary or "")

        # The tool result text (either the ack payload or the error message)
        # carries a recoverable run reference.
        if result["kind"] == "ack":
            result_text = result["result"]["text"]
        else:
            result_text = result.get("message", "")

        assert result["kind"] == "ack"
        assert result["result"]["isError"] is False
        assert "accepted" in result_text and "do not redispatch" in result_text
        assert len(store.list_runs(session_key)) == 1
        followup = reader.wait_for_event("followup", timeout=15.0)
        assert followup is not None, "accepted run's report was not recovered"
        assert run_id in followup["message"] and "worker ok" in followup["message"]
        assert store.get_run(run_id).reported_at is None
        reader.send({"cmd": "message_end", "text": followup["message"]})
        assert wait_for_condition(lambda: store.get_run(run_id).reported_at is not None, timeout=15)
        assert not store.list_pending_report_runs(session_key)
    finally:
        if reader is not None:
            # Graceful shutdown: session_shutdown (kills watchers) then quit.
            try:
                reader.send({"cmd": "session_shutdown"})
                time.sleep(0.5)
                reader.send({"cmd": "quit"})
                if process is not None and not process.wait(timeout=5.0):
                    process.kill()
                    process.wait(timeout=5.0)
            except Exception:
                if process is not None:
                    try:
                        process.kill()
                        process.wait(timeout=5.0)
                    except Exception:
                        pass
            reader.stop()
        if run_id is not None:
            _cleanup_active_runs(db_path, session_key, config_path.parent, python_executable)


# ---------------------------------------------------------------------------
# Test 2: Pi transcript-only timeout incomplete recovery (real supervisor)
# ---------------------------------------------------------------------------


def test_pi_transcript_timeout_incomplete_recovery(
    tmp_path: Path,
    runtime_files_factory: Any,
    python_executable: str,
    fake_worker_script: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real supervisor: worker times out, transcript-only recovery yields INCOMPLETE.

    The worker sleeps beyond the timeout. A pre-placed Pi transcript in
    native format contains an incomplete result. The real supervisor
    (detached process) kills the worker, reads the transcript, and marks
    the run INCOMPLETE with the recovered text. This exercises the full
    core terminal/artifact/report path without mocking the supervisor.
    """
    session_dir = tmp_path / "pi-sessions"
    session_dir.mkdir()
    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(session_dir))

    # Use a bare sleep that produces NO stdout on SIGTERM (unlike fake_worker.py
    # which prints "terminated"). This ensures the transcript is the only source
    # of recovered text.
    sleep_worker = tmp_path / "silent_sleep.py"
    sleep_worker.write_text(
        "import time\ntime.sleep(120)\n", encoding="utf-8"
    )
    config_path, _, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(sleep_worker)],
    )

    env = {k: v for k, v in os.environ.items() if not k.startswith("ORCHESTRA_")}
    env["PI_CODING_AGENT_SESSION_DIR"] = str(session_dir)
    result = subprocess.run(
        [
            python_executable, "-m", "orchestra",
            "--config", str(config_path.parent),
            "do",
            "--session-id", "pi:transcript-timeout",
            "--goal", "timeout transcript recovery",
            "--timeout", "2",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    run_id = next(
        line.split(": ", 1)[1]
        for line in result.stdout.splitlines()
        if line.startswith("run_id:")
    )

    # Create the Pi transcript file in native format. The worker_session_id
    # is "orchestra-worker-{run_id}". The transcript must contain an
    # assistant message with the incomplete handoff text.
    worker_session_id = f"orchestra-worker-{run_id}"
    handoff_text = (
        "ORCHESTRA_STATUS: incomplete\n"
        "ORCHESTRA_STOP_REASON: budget_exceeded\n\n"
        "Status: incomplete\n"
        "Verdict: n/a\n"
        "Material evidence:\n"
        "- transcript recovery test"
    )
    transcript_path = session_dir / f"2026-01-01T00-00-00-000Z_{worker_session_id}.jsonl"
    transcript_lines = [
        json.dumps({
            "type": "session", "version": 3, "id": worker_session_id,
            "timestamp": "2026-01-01T00:00:00.000Z", "cwd": "/tmp",
        }),
        json.dumps({
            "type": "message", "id": "msg-1", "parentId": None,
            "timestamp": "2026-01-01T00:00:01.000Z",
            "message": {"role": "user", "content": "Do the work."},
        }),
        json.dumps({
            "type": "message", "id": "msg-2", "parentId": "msg-1",
            "timestamp": "2026-01-01T00:00:02.000Z",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": handoff_text}],
                "provider": "test", "model": "test-model",
                "stopReason": "end_turn",
                "usage": {"input": 100, "output": 50, "reasoning": 0,
                          "cacheRead": 0, "cacheWrite": 0,
                          "cost": {"total": 0.001}},
            },
        }),
    ]
    transcript_path.write_text("\n".join(transcript_lines) + "\n", encoding="utf-8")

    store = StateStore(db_path)
    assert wait_for_condition(
        lambda: store.get_run(run_id).status in TERMINAL_STATUSES, timeout=30
    ), f"run {run_id} did not reach terminal state"

    record = store.get_run(run_id)
    assert record.status == STATUS_INCOMPLETE, (
        f"expected INCOMPLETE, got {record.status}; "
        f"error_text={record.error_text!r}; blocker={record.blocker_text!r}"
    )
    assert record.result_summary is not None
    assert "transcript recovery test" in record.result_summary
    assert record.blocker_text == "Worker budget exceeded; redispatch from continuation handoff"
    # Token accounting from the transcript.
    assert record.input_tokens == 100
    assert record.output_tokens == 50


# ---------------------------------------------------------------------------
# Test 3: Reload pending report recovery
# ---------------------------------------------------------------------------


def test_pi_reload_recovery_pending_report_redelivered(
    tmp_path: Path,
    runtime_files_factory: Any,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    """After reload (shutdown + fresh session_start), pending report is redelivered.

    Phase 1: dispatch → run completes → report delivered (followUp) → not confirmed → shutdown.
    Phase 2: fresh session_start (simulating /reload).
    The pending report is redelivered without marking it before chat confirmation.
    """
    pi_pkg = _find_pi_package()
    if pi_pkg is None:
        pytest.skip("Pi coding-agent package not found at ~/.pi/agent/install")

    config_path, _, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "reload recovery ok"],
    )
    store = StateStore(db_path)
    sid = _session_id()
    session_key = f"pi:{sid}"
    driver = DriverClient(tmp_path, config_path, python_executable, pi_pkg)
    run_id: str | None = None
    try:
        driver.start()

        # Phase 1: dispatch, get report, do NOT confirm, shutdown.
        driver.send_command({"cmd": "session_start", "id": sid}, wait_kind=None)
        time.sleep(0.5)

        ack = driver.send_command(
            {"cmd": "dispatch", "goal": "reload recovery test"},
            wait_kind="ack",
            timeout=30.0,
        )
        assert ack is not None, f"no ack; stderr: {driver.stderr_content()}"
        assert not ack["result"]["isError"]

        runs = store.list_runs(session_key)
        assert len(runs) == 1
        run_id = runs[0].run_id

        # Wait for completion.
        assert wait_for_condition(
            lambda: store.get_run(run_id).status in TERMINAL_STATUSES, timeout=30
        )

        # Get the followUp report (pending, unconfirmed).
        followup = driver._wait_for_event("followup", timeout=30.0)
        assert followup is not None, f"no followup; stderr: {driver.stderr_content()}"
        report_text = followup["message"]
        assert run_id in report_text

        # Shutdown: drops the pending report locally; run stays unreported.
        driver.send_command({"cmd": "session_shutdown"}, wait_kind=None)
        time.sleep(0.5)
        assert store.get_run(run_id).reported_at is None

        # Phase 2: fresh session_start (simulating /reload).
        driver.send_command({"cmd": "session_start", "id": sid}, wait_kind=None)
        time.sleep(0.5)

        # Recovery reads the report without consuming it.
        redelivery = driver._wait_for_event("followup", timeout=5.0)
        assert redelivery is not None, (
            "pending report was not redelivered after reload"
        )
        assert run_id in redelivery["message"]
        assert store.get_run(run_id).reported_at is None
        driver.send({"cmd": "message_end", "text": redelivery["message"]})
        assert wait_for_condition(lambda: store.get_run(run_id).reported_at is not None, timeout=15)
        assert not store.list_pending_report_runs(session_key)
    finally:
        driver.stop()
        _cleanup_active_runs(db_path, session_key, config_path.parent, python_executable)


# ---------------------------------------------------------------------------
# Test 4: Compaction lifecycle — deferred report and confirmation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("finish_command", ["compaction_end", "compaction_failed"])
def test_pi_compaction_retry_delivers_report(
    finish_command: str,
    tmp_path: Path,
    runtime_files_factory: Any,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    """A report ready during compaction waits for the real lifecycle completion.

    Success and failure both resume delivery; an accepted report is not resent
    while its matching message_end confirmation is outstanding.
    """
    pi_pkg = _find_pi_package()
    if pi_pkg is None:
        pytest.skip("Pi coding-agent package not found at ~/.pi/agent/install")

    config_path, _, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "compaction retry ok"],
    )
    store = StateStore(db_path)
    sid = _session_id()
    session_key = f"pi:{sid}"
    driver = DriverClient(tmp_path, config_path, python_executable, pi_pkg)
    run_id: str | None = None
    try:
        driver.start()
        driver.send_command({"cmd": "session_start", "id": sid}, wait_kind=None)
        time.sleep(0.5)

        # Inject compaction: session_before_compact fires, sendUserMessage rejected.
        driver.send_command({"cmd": "compaction_reject", "count": 1}, wait_kind="ack")

        ack = driver.send_command(
            {"cmd": "dispatch", "goal": "compaction retry test"},
            wait_kind="ack",
            timeout=30.0,
        )
        assert ack is not None, f"no ack; stderr: {driver.stderr_content()}"
        assert not ack["result"]["isError"]

        runs = store.list_runs(session_key)
        assert len(runs) == 1
        run_id = runs[0].run_id

        # Wait for run to complete.
        assert wait_for_condition(
            lambda: store.get_run(run_id).status in TERMINAL_STATUSES, timeout=30
        )

        # Delivery must not be attempted while compaction is active.
        assert driver._wait_for_event("followup", timeout=1.0) is None
        assert driver._wait_for_event("rejected", timeout=0.2) is None
        assert store.get_run(run_id).reported_at is None

        driver.send_command({"cmd": finish_command}, wait_kind="ack")

        # The retry succeeds: followup event emitted.
        followup = driver._wait_for_event("followup", timeout=10.0)
        assert followup is not None, (
            f"no followup after compaction retry; stderr: {driver.stderr_content()}"
        )
        report_text = followup["message"]
        assert run_id in report_text

        # A second compaction before the chat echo must not resend accepted text.
        driver.send_command({"cmd": "compaction_reject", "count": 1}, wait_kind="ack")
        driver.send_command({"cmd": finish_command}, wait_kind="ack")
        count = driver.send_command({"cmd": "delivery_count"}, wait_kind="delivery_count")
        assert count is not None and count["count"] == 1
        assert store.get_run(run_id).reported_at is None

        # Matching echo marks delivered.
        driver.send({"cmd": "message_end", "text": report_text})
        assert wait_for_condition(
            lambda: store.get_run(run_id).reported_at is not None, timeout=15
        )
        assert not store.list_pending_report_runs(session_key)
    finally:
        driver.stop()
        _cleanup_active_runs(db_path, session_key, config_path.parent, python_executable)
