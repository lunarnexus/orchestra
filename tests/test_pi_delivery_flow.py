"""Pi delivery-flow journeys: real extension + fake host + real core.

Two journeys prove the Pi host delivery pipeline end-to-end with a minimal
fake ExtensionAPI (sendUserMessage, message_end, session_start/shutdown,
sessionManager.getSessionId, registerTool) driving the real
extensions/pi/orchestra/index.ts loaded via the installed Pi extension loader.
All core commands (do, _await-run, _await-session-report, _dispatch-ack,
_mark-session-report-delivered, _progress-message, _tool-info, status) are
real subprocesses against an isolated SQLite config.

Limitations: this proves host-context delivery into the simulated Pi runtime,
not live-chat delivery or model consumption. The one-shot CLI path is subject
to the KNOWN_BUG one-shot-exit race and is not exercised here.
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

from orchestra.state import ACTIVE_STATUSES, STATUS_DONE, TERMINAL_STATUSES, StateStore
from tests.helpers import wait_for_condition

REPO_ROOT = Path(__file__).resolve().parents[1]
DRIVER_PATH = REPO_ROOT / "tests" / "pi_driver.mjs"
EXTENSION_PATH = REPO_ROOT / "extensions" / "pi" / "orchestra" / "index.ts"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="node executable not found",
)


def _find_pi_package() -> Path | None:
    """Locate the installed Pi coding-agent package."""
    pi_dir = Path(os.environ.get("PI_CODING_AGENT_DIR", "~/.pi/agent")).expanduser()
    current = pi_dir / "install" / "current-version"
    if not current.exists():
        return None
    version = current.read_text(encoding="utf-8").strip()
    if not version:
        return None
    pkg = (
        pi_dir / "install" / "releases" / version
        / "node_modules" / "@earendil-works" / "pi-coding-agent"
    )
    if not pkg.exists():
        return None
    return pkg


def _make_orchestra_shim(tmp_path: Path, python_executable: str) -> Path:
    """Create an executable 'orchestra' shim with selective failure injection.

    Forwards all normal operations to the real python -m orchestra. When a
    control file exists in $ORCHESTRA_CONFIG (e.g. .shim_fail_await with a
    count), the shim decrements the counter and exits 1 for that command.
    A persistent control file (.shim_fail_await_persistent) causes indefinite
    failure. Each invocation appends a trace line to .shim_trace_<cmd>.
    """
    shim_dir = tmp_path / "shim-bin"
    shim_dir.mkdir(exist_ok=True)
    shim = shim_dir / "orchestra"
    shim.write_text(
        f"""#!/bin/sh
CONFIG_DIR="${{ORCHESTRA_CONFIG:-}}"
if [ -n "$CONFIG_DIR" ]; then
  for arg in "$@"; do
    case "$arg" in
      _await-session-report)
        TRACE_FILE="$CONFIG_DIR/.shim_trace_await"
        if [ -f "$CONFIG_DIR/.shim_fail_await_persistent" ]; then
          echo "fail" >> "$TRACE_FILE"
          echo "shim: simulated _await-session-report failure (persistent)" >&2
          exit 1
        fi
        FAIL_FILE="$CONFIG_DIR/.shim_fail_await"
        if [ -f "$FAIL_FILE" ]; then
          COUNT=$(cat "$FAIL_FILE" 2>/dev/null || echo 0)
          if [ "$COUNT" -gt 0 ] 2>/dev/null; then
            echo $((COUNT - 1)) > "$FAIL_FILE"
            echo "fail" >> "$TRACE_FILE"
            echo "shim: simulated _await-session-report failure" >&2
            exit 1
          fi
          rm -f "$FAIL_FILE"
        fi
        echo "ok" >> "$TRACE_FILE"
        break
        ;;
      _mark-session-report-delivered)
        TRACE_FILE="$CONFIG_DIR/.shim_trace_mark"
        if [ -f "$CONFIG_DIR/.shim_fail_mark_persistent" ]; then
          echo "fail" >> "$TRACE_FILE"
          echo "shim: simulated _mark-session-report-delivered failure (persistent)" >&2
          exit 1
        fi
        FAIL_FILE="$CONFIG_DIR/.shim_fail_mark"
        if [ -f "$FAIL_FILE" ]; then
          COUNT=$(cat "$FAIL_FILE" 2>/dev/null || echo 0)
          if [ "$COUNT" -gt 0 ] 2>/dev/null; then
            echo $((COUNT - 1)) > "$FAIL_FILE"
            echo "fail" >> "$TRACE_FILE"
            echo "shim: simulated _mark-session-report-delivered failure" >&2
            exit 1
          fi
          rm -f "$FAIL_FILE"
        fi
        echo "ok" >> "$TRACE_FILE"
        break
        ;;
    esac
  done
fi
exec {python_executable} -m orchestra "$@"
""",
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return shim_dir


def _set_shim_failure(config_dir: Path, name: str, count: int) -> None:
    """Write a shim failure-injection control file."""
    (config_dir / name).write_text(str(count), encoding="utf-8")


def _set_shim_failure_persistent(config_dir: Path, name: str) -> None:
    """Write a shim persistent-failure control file (always fails, no decrement)."""
    (config_dir / name).write_text("1", encoding="utf-8")


def _trace_quiescent(
    trace_file: Path, *, stable_for: float = 2.0, timeout: float = 30.0
) -> int:
    """Wait until trace file stops growing for stable_for seconds.

    Returns the final line count (0 if no lines appeared within timeout).
    """
    deadline = time.monotonic() + timeout
    last_count = 0
    last_change = time.monotonic()
    while time.monotonic() < deadline:
        if trace_file.exists():
            count = len(trace_file.read_text(encoding="utf-8").splitlines())
            if count > last_count:
                last_count = count
                last_change = time.monotonic()
        if last_count > 0 and (time.monotonic() - last_change) >= stable_for:
            return last_count
        time.sleep(0.2)
    return last_count


def _driver_env(
    tmp_path: Path,
    config_path: Path,
    python_executable: str,
    pi_pkg: Path,
) -> dict[str, str]:
    """Build the driver environment: stripped ORCHESTRA_* vars + required vars."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("ORCHESTRA_")}
    env["ORCHESTRA_CONFIG"] = str(config_path.parent)
    env["ORCH_PI_PKG"] = str(pi_pkg)
    env["ORCH_EXT_PATH"] = str(EXTENSION_PATH)
    shim_dir = _make_orchestra_shim(tmp_path, python_executable)
    env["PATH"] = f"{shim_dir}{os.pathsep}{env.get('PATH', '/usr/bin:/bin')}"
    return env


class DriverClient:
    """Manages the pi_driver.mjs subprocess and its JSON-line protocol."""

    def __init__(
        self, tmp_path: Path, config_path: Path, python_executable: str, pi_pkg: Path
    ) -> None:
        self._tmp_path = tmp_path
        self._config_path = config_path
        self._python_executable = python_executable
        self._pi_pkg = pi_pkg
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._events: list[dict[str, Any]] = []
        self._event_waiters: list[threading.Event] = []
        self._reader_thread: threading.Thread | None = None
        self._session_active = False

    def start(self) -> None:
        env = _driver_env(self._tmp_path, self._config_path, self._python_executable, self._pi_pkg)
        self._process = subprocess.Popen(
            ["node", str(DRIVER_PATH)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=str(REPO_ROOT),
            text=True,
        )
        assert self._process.stdout is not None
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()
        # Wait for ready
        event = self._wait_for_event("ready", timeout=15.0)
        if event is None:
            self._diagnose_and_kill()
            raise TimeoutError("driver did not emit ready within 15s")

    def _read_loop(self) -> None:
        assert self._process is not None and self._process.stdout is not None
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
                for waiter in self._event_waiters:
                    waiter.set()

    def _wait_for_event(self, kind: str, *, timeout: float = 30.0) -> dict[str, Any] | None:
        """Wait for an event of the given kind. Returns the event or None on timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                for i, ev in enumerate(self._events):
                    if ev.get("kind") == kind:
                        self._events.pop(i)
                        return ev
            waiter = threading.Event()
            with self._lock:
                self._event_waiters.append(waiter)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            waiter.wait(timeout=remaining)
            with self._lock:
                if waiter in self._event_waiters:
                    self._event_waiters.remove(waiter)
        return None

    def send(self, cmd: dict[str, Any]) -> None:
        assert self._process is not None and self._process.stdin is not None
        line = json.dumps(cmd) + "\n"
        self._process.stdin.write(line)
        self._process.stdin.flush()

    def send_command(
        self, cmd: dict[str, Any], *, wait_kind: str | None = None, timeout: float = 30.0
    ) -> dict[str, Any] | None:
        self.send(cmd)
        if cmd.get("cmd") == "session_start":
            self._session_active = True
        elif cmd.get("cmd") == "session_shutdown":
            self._session_active = False
        if wait_kind is None:
            return None
        return self._wait_for_event(wait_kind, timeout=timeout)

    def stderr_content(self) -> str:
        if self._process is None or self._process.stderr is None:
            return ""
        try:
            return self._process.stderr.read() or ""
        except Exception:
            return ""

    def _diagnose_and_kill(self) -> None:
        if self._process is not None:
            try:
                self._process.kill()
                self._process.wait(timeout=5)
            except Exception:
                pass

    def stop(self) -> None:
        """Fire session_shutdown (kills watchers) then quit; kill if needed."""
        if self._process is None:
            return
        try:
            if self._session_active:
                self.send({"cmd": "session_shutdown"})
                time.sleep(1.0)  # bounded wait for SIGTERMed watchers to exit
            self.send({"cmd": "quit"})
            if not self._process.wait(timeout=5.0):
                self._process.kill()
                self._process.wait(timeout=5.0)
        except Exception:
            try:
                self._process.kill()
            except Exception:
                pass
        self._process = None


def _session_id() -> str:
    return f"pi-delivery-{uuid.uuid4().hex[:12]}"


def test_pi_delivery_journey_a(
    tmp_path: Path,
    runtime_files_factory: Any,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    """Journey A: dispatch → followUp → unrelated echo (no mark) → matching echo → mark."""
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
    driver = DriverClient(tmp_path, config_path, python_executable, pi_pkg)
    run_id: str | None = None
    try:
        driver.start()

        # Session start
        driver.send_command({"cmd": "session_start", "id": sid}, wait_kind=None)
        time.sleep(0.5)  # allow async session_start handler to settle

        # Dispatch
        ack = driver.send_command(
            {"cmd": "dispatch", "goal": "delivery journey a"},
            wait_kind="ack",
            timeout=30.0,
        )
        assert ack is not None, f"no ack received; stderr: {driver.stderr_content()}"
        assert not ack["result"]["isError"], f"dispatch failed: {ack['result']['text']}"
        assert "orchestra dispatched:" in ack["result"]["text"]

        # The run belongs to the runtime originating session.
        runs = store.list_runs(session_key)
        assert len(runs) == 1
        run_id = runs[0].run_id
        record = store.get_run(run_id)
        assert record.orchestrator_session_id == session_key
        assert record.role == "worker"

        # Deterministic completion: real supervisor runs the controlled fake worker.
        assert wait_for_condition(
            lambda: store.get_run(run_id).status in TERMINAL_STATUSES, timeout=30
        )
        record = store.get_run(run_id)
        assert record.status == STATUS_DONE
        assert "worker ok" in (record.result_summary or "")

        # Wait for the followUp report injection.
        followup = driver._wait_for_event("followup", timeout=30.0)
        assert followup is not None, f"no followup received; stderr: {driver.stderr_content()}"
        report_text = followup["message"]
        assert run_id in report_text
        assert "success" in report_text
        assert followup["options"].get("deliverAs") == "followUp"

        # Report stays unreported before matching echo.
        assert store.get_run(run_id).reported_at is None

        # Unrelated message_end must NOT mark.
        driver.send({"cmd": "message_end", "text": "unrelated user message"})
        time.sleep(1.0)
        assert store.get_run(run_id).reported_at is None

        # Matching echo marks delivered.
        driver.send({"cmd": "message_end", "text": report_text})
        assert wait_for_condition(
            lambda: store.get_run(run_id).reported_at is not None, timeout=15
        )

        # Pending report disappears; capacity released.
        assert not any(r.run_id == run_id for r in store.list_pending_report_runs(session_key))
        assert store.count_active_runs(session_key) == 0

        # Worker and supervisor terminated.
        final_record = store.get_run(run_id)
        assert final_record.supervisor_pid is not None, "supervisor_pid was never recorded"
        assert final_record.process_id is not None, "worker process_id was never recorded"
        assert wait_for_condition(
            lambda: not _process_alive(final_record.supervisor_pid), timeout=15
        )
        assert wait_for_condition(
            lambda: not _process_alive(final_record.process_id), timeout=15
        )
    finally:
        driver.stop()
        _cleanup_active_runs(db_path, session_key, config_path.parent, python_executable)


def test_pi_delivery_journey_b(
    tmp_path: Path,
    runtime_files_factory: Any,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    """Journey B: unconfirmed followUp → shutdown → fresh dispatch → consolidated report."""
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
    driver = DriverClient(tmp_path, config_path, python_executable, pi_pkg)
    run_id_1: str | None = None
    run_id_2: str | None = None
    try:
        driver.start()

        # --- Phase 1: dispatch, get unconfirmed report, shutdown ---
        driver.send_command({"cmd": "session_start", "id": sid}, wait_kind=None)
        time.sleep(0.5)

        ack1 = driver.send_command(
            {"cmd": "dispatch", "goal": "delivery journey b first"},
            wait_kind="ack",
            timeout=30.0,
        )
        assert ack1 is not None, f"no ack1; stderr: {driver.stderr_content()}"
        assert not ack1["result"]["isError"]

        runs = store.list_runs(session_key)
        assert len(runs) == 1
        run_id_1 = runs[0].run_id
        assert wait_for_condition(
            lambda: store.get_run(run_id_1).status in TERMINAL_STATUSES, timeout=30
        )

        # Get the followUp report for run_1.
        followup1 = driver._wait_for_event("followup", timeout=30.0)
        assert followup1 is not None, f"no followup1; stderr: {driver.stderr_content()}"
        report1 = followup1["message"]
        assert run_id_1 in report1

        # Unrelated echo: no mark.
        driver.send({"cmd": "message_end", "text": "unrelated message b"})
        time.sleep(1.0)
        assert store.get_run(run_id_1).reported_at is None

        # Shutdown: drops the pending report locally; run stays unreported in DB.
        driver.send_command({"cmd": "session_shutdown"}, wait_kind=None)
        time.sleep(0.5)
        assert store.get_run(run_id_1).reported_at is None

        # --- Phase 2: fresh session_start + dispatch → consolidated report ---
        driver.send_command({"cmd": "session_start", "id": sid}, wait_kind=None)
        time.sleep(0.5)

        ack2 = driver.send_command(
            {"cmd": "dispatch", "goal": "delivery journey b second"},
            wait_kind="ack",
            timeout=30.0,
        )
        assert ack2 is not None, f"no ack2; stderr: {driver.stderr_content()}"
        assert not ack2["result"]["isError"]

        runs = store.list_runs(session_key)
        assert len(runs) == 2
        run_id_2 = next(r.run_id for r in runs if r.run_id != run_id_1)
        assert wait_for_condition(
            lambda: store.get_run(run_id_2).status in TERMINAL_STATUSES, timeout=30
        )

        # The consolidated report contains BOTH run ids.
        followup2 = driver._wait_for_event("followup", timeout=30.0)
        assert followup2 is not None, f"no followup2; stderr: {driver.stderr_content()}"
        report2 = followup2["message"]
        assert run_id_1 in report2
        assert run_id_2 in report2

        # Matching echo marks both delivered.
        driver.send({"cmd": "message_end", "text": report2})
        assert wait_for_condition(
            lambda: store.get_run(run_id_1).reported_at is not None
            and store.get_run(run_id_2).reported_at is not None,
            timeout=15,
        )

        # Pending empty; capacity released.
        assert not store.list_pending_report_runs(session_key)
        assert store.count_active_runs(session_key) == 0
    finally:
        driver.stop()
        _cleanup_active_runs(db_path, session_key, config_path.parent, python_executable)


def test_pi_progress_completion_emits_host_notify(
    tmp_path: Path,
    runtime_files_factory: Any,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    """Progress completion emits a host notify event, not a model user-message."""
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
    driver = DriverClient(tmp_path, config_path, python_executable, pi_pkg)
    run_id: str | None = None
    try:
        driver.start()
        driver.send_command({"cmd": "session_start", "id": sid}, wait_kind=None)
        time.sleep(0.5)

        ack = driver.send_command(
            {"cmd": "dispatch", "goal": "progress notify test"},
            wait_kind="ack",
            timeout=30.0,
        )
        assert ack is not None, f"no ack; stderr: {driver.stderr_content()}"
        assert not ack["result"]["isError"]

        runs = store.list_runs(session_key)
        assert len(runs) == 1
        run_id = runs[0].run_id

        # Wait for the run to complete.
        assert wait_for_condition(
            lambda: store.get_run(run_id).status in TERMINAL_STATUSES, timeout=30
        )

        # Assert a host notify event was received (progress notification).
        notify = driver._wait_for_event("notify", timeout=15.0)
        assert notify is not None, f"no notify event; stderr: {driver.stderr_content()}"
        assert notify["message"], "notify message is empty"
        # The progress notification contains the run id and terminal status.
        assert run_id in notify["message"]
        assert "done" in notify["message"]

        # The report followup is a separate event kind (model user-message).
        followup = driver._wait_for_event("followup", timeout=30.0)
        assert followup is not None, f"no followup; stderr: {driver.stderr_content()}"
        # The notify message differs from the followup message.
        assert notify["message"] != followup["message"]
    finally:
        driver.stop()
        _cleanup_active_runs(db_path, session_key, config_path.parent, python_executable)


def test_pi_report_watcher_transient_failure_recovers(
    tmp_path: Path,
    runtime_files_factory: Any,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    """Transient _await-session-report failure recovers; report delivered and marked."""
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
    driver = DriverClient(tmp_path, config_path, python_executable, pi_pkg)
    run_id: str | None = None
    try:
        driver.start()
        driver.send_command({"cmd": "session_start", "id": sid}, wait_kind=None)
        time.sleep(0.5)

        # Inject one failure for _await-session-report.
        _set_shim_failure(config_path.parent, ".shim_fail_await", 1)

        ack = driver.send_command(
            {"cmd": "dispatch", "goal": "transient failure recovery"},
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

        # The report watcher fails once, then recovers on retry.
        followup = driver._wait_for_event("followup", timeout=30.0)
        assert followup is not None, (
            f"no followup after retry; stderr: {driver.stderr_content()}"
        )
        report_text = followup["message"]
        assert run_id in report_text

        # Trace evidence: fault was actually injected and recovery succeeded.
        trace_file = config_path.parent / ".shim_trace_await"
        assert trace_file.exists(), "no shim trace evidence of _await-session-report invocation"
        trace_lines = trace_file.read_text(encoding="utf-8").splitlines()
        assert any("fail" in line for line in trace_lines), (
            f"no fault injection in trace: {trace_lines}"
        )
        assert any("ok" in line for line in trace_lines), (
            f"no successful retry in trace: {trace_lines}"
        )

        # Mark delivered.
        driver.send({"cmd": "message_end", "text": report_text})
        assert wait_for_condition(
            lambda: store.get_run(run_id).reported_at is not None, timeout=15
        )
        assert not store.list_pending_report_runs(session_key)
    finally:
        driver.stop()
        _cleanup_active_runs(db_path, session_key, config_path.parent, python_executable)


def test_pi_report_watcher_exhaustion_leaves_pending(
    tmp_path: Path,
    runtime_files_factory: Any,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    """Exhausted _await-session-report failures stop retrying; durable pending intact."""
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
    driver = DriverClient(tmp_path, config_path, python_executable, pi_pkg)
    run_id: str | None = None
    try:
        driver.start()
        driver.send_command({"cmd": "session_start", "id": sid}, wait_kind=None)
        time.sleep(0.5)

        # Inject persistent failure for _await-session-report.
        _set_shim_failure_persistent(config_path.parent, ".shim_fail_await_persistent")

        ack = driver.send_command(
            {"cmd": "dispatch", "goal": "exhaustion test"},
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

        # Observe bounded quiescence: trace stops growing (watcher stopped retrying).
        trace_file = config_path.parent / ".shim_trace_await"
        attempts = _trace_quiescent(trace_file, stable_for=2.0, timeout=30.0)
        assert attempts > 0, "no _await-session-report attempts observed in trace"

        # All trace entries are failures (persistent injection, no success).
        trace_lines = trace_file.read_text(encoding="utf-8").splitlines()
        assert all("fail" in line for line in trace_lines), (
            f"unexpected success in persistent-failure trace: {trace_lines}"
        )

        # No followup should have been received.
        followup = driver._wait_for_event("followup", timeout=2.0)
        assert followup is None, f"unexpected followup after exhaustion: {followup}"

        # Durable pending intact: run is still unreported.
        assert store.get_run(run_id).reported_at is None
        pending = store.list_pending_report_runs(session_key)
        assert any(r.run_id == run_id for r in pending)
    finally:
        driver.stop()
        _cleanup_active_runs(db_path, session_key, config_path.parent, python_executable)


def test_pi_mark_failure_redelivers_and_succeeds(
    tmp_path: Path,
    runtime_files_factory: Any,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    """Failed _mark-session-report-delivered leaves pending; retry redelivers and mark succeeds."""
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
    driver = DriverClient(tmp_path, config_path, python_executable, pi_pkg)
    run_id: str | None = None
    try:
        driver.start()
        driver.send_command({"cmd": "session_start", "id": sid}, wait_kind=None)
        time.sleep(0.5)

        # Inject one failure for _mark-session-report-delivered.
        _set_shim_failure(config_path.parent, ".shim_fail_mark", 1)

        ack = driver.send_command(
            {"cmd": "dispatch", "goal": "mark failure redelivery"},
            wait_kind="ack",
            timeout=30.0,
        )
        assert ack is not None, f"no ack; stderr: {driver.stderr_content()}"
        assert not ack["result"]["isError"]

        runs = store.list_runs(session_key)
        assert len(runs) == 1
        run_id = runs[0].run_id

        # Wait for run to complete and report to be delivered.
        assert wait_for_condition(
            lambda: store.get_run(run_id).status in TERMINAL_STATUSES, timeout=30
        )
        followup1 = driver._wait_for_event("followup", timeout=30.0)
        assert followup1 is not None, f"no followup1; stderr: {driver.stderr_content()}"
        report_text = followup1["message"]
        assert run_id in report_text

        # Fire message_end: first mark fails, triggering redelivery.
        driver.send({"cmd": "message_end", "text": report_text})

        # The first mark fails; the retry re-delivers the report.
        followup2 = driver._wait_for_event("followup", timeout=15.0)
        assert followup2 is not None, (
            f"no redelivery followup; stderr: {driver.stderr_content()}"
        )
        assert run_id in followup2["message"]

        # Fire message_end again: this time the mark succeeds.
        driver.send({"cmd": "message_end", "text": followup2["message"]})
        assert wait_for_condition(
            lambda: store.get_run(run_id).reported_at is not None, timeout=15
        )
        assert not store.list_pending_report_runs(session_key)
    finally:
        driver.stop()
        _cleanup_active_runs(db_path, session_key, config_path.parent, python_executable)


def test_pi_stale_callbacks_cannot_inject_unrelated_session(
    tmp_path: Path,
    runtime_files_factory: Any,
    python_executable: str,
    fake_worker_script: Path,
) -> None:
    """Session shutdown/switch: stale callbacks cannot inject into unrelated session."""
    pi_pkg = _find_pi_package()
    if pi_pkg is None:
        pytest.skip("Pi coding-agent package not found at ~/.pi/agent/install")

    config_path, _, db_path = runtime_files_factory(
        tmp_path,
        [python_executable, str(fake_worker_script), "success", "--output", "worker ok"],
    )
    store = StateStore(db_path)
    sid_a = _session_id()
    sid_b = _session_id()
    session_key_a = f"pi:{sid_a}"
    driver = DriverClient(tmp_path, config_path, python_executable, pi_pkg)
    run_id: str | None = None
    try:
        driver.start()

        # Phase 1: dispatch in session A, get report, do not confirm.
        driver.send_command({"cmd": "session_start", "id": sid_a}, wait_kind=None)
        time.sleep(0.5)

        ack = driver.send_command(
            {"cmd": "dispatch", "goal": "stale callback test"},
            wait_kind="ack",
            timeout=30.0,
        )
        assert ack is not None, f"no ack; stderr: {driver.stderr_content()}"
        assert not ack["result"]["isError"]

        runs = store.list_runs(session_key_a)
        assert len(runs) == 1
        run_id = runs[0].run_id

        assert wait_for_condition(
            lambda: store.get_run(run_id).status in TERMINAL_STATUSES, timeout=30
        )

        # Get the followup report for session A (pending, unconfirmed).
        followup = driver._wait_for_event("followup", timeout=30.0)
        assert followup is not None, f"no followup; stderr: {driver.stderr_content()}"
        report_text = followup["message"]
        assert run_id in report_text

        # Shutdown session A: drops the pending report locally.
        driver.send_command({"cmd": "session_shutdown"}, wait_kind=None)
        time.sleep(0.5)
        assert store.get_run(run_id).reported_at is None

        # Phase 2: start unrelated session B.
        driver.send_command({"cmd": "session_start", "id": sid_b}, wait_kind=None)
        time.sleep(0.5)

        # Wait for any stale callbacks to fire.
        time.sleep(2.0)

        # No new followup should have been injected into session B.
        stale_followup = driver._wait_for_event("followup", timeout=2.0)
        assert stale_followup is None, (
            f"stale followup leaked into session B: {stale_followup}"
        )

        # The run from A is still unreported (durable pending intact).
        assert store.get_run(run_id).reported_at is None
    finally:
        driver.stop()
        _cleanup_active_runs(db_path, session_key_a, config_path.parent, python_executable)


def _process_alive(process_id: int | None) -> bool:
    if process_id is None:
        return False
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _cleanup_active_runs(
    db_path: Path,
    session_key: str,
    config_dir: Path,
    python_executable: str,
) -> None:
    """Owner-scoped core stop for any still-active runs (bounded test cleanup)."""
    store = StateStore(db_path)
    active = [r for r in store.list_runs(session_key) if r.status in ACTIVE_STATUSES]
    env = {**os.environ, "ORCHESTRA_CONFIG": str(config_dir)}
    for run in active:
        try:
            subprocess.run(
                [
                    python_executable, "-m", "orchestra", "stop",
                    "--session-id", session_key, "--run-id", run.run_id,
                ],
                env=env,
                capture_output=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass
