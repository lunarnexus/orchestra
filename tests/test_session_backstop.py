"""Regression: the active-work backstop must wake the real idle core session.

Gap under test (source-owned race): ``SessionRuntime.serve`` computes its poll
timeout from ``_poll_timeout()`` *before* reading the source. The dispatch
admission thread arms ``_next_due`` (via ``evaluate`` -> ``_arm_timer``) only
after it has forked the worker and emitted the acknowledgement. If the serve
loop re-enters ``source.poll(timeout=None)`` before that arming — which is the
common case because the loop loops back within microseconds while Submit still
forks a subprocess — the loop blocks in a *no-timeout* ``select`` forever. The
thread later sets ``_next_due`` but cannot wake the already-blocked poll, so the
periodic backstop never fires until an unrelated inbound frame arrives.

This test reproduces the race end to end with a REAL OS pipe feeding a REAL
``_StdinSource`` + ``serve`` loop (not a fake poll double), a REAL launched
worker subprocess running a controlled never-responding fake-pi (so the job
stays running, the owned worker stays alive, and no completion/observer event
ever fires), and the TEST ``interval`` constructor parameter (0.15s).

Guarantee: after the dispatch acknowledgement and the job reaches running, with
NO further inbound frames during an idle window, the runtime must emit repeated
core status/evaluation pushes (>= 3 ticks beyond the initial progress) while the
owned worker is still alive and no completion/delivery occurs.

Boundaries: real JobQueue/SQLite, real worker process group, controlled fake-pi.
No live model, no host extension, no network, no real credentials.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from orchestra.config import load_orchestra_config
from orchestra.queue import JobQueue
from orchestra.session import (
    KIND_NATIVE_REQUEST,
    KIND_REPLY,
    KIND_REQUEST,
    KIND_STATUS,
    SessionRuntime,
    _StdinSource,
    encode_line,
)
from orchestra.terminate import launch_start_time, terminate_group

REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION = "pi:BACKSTOP1"

# TEST backstop interval (constructor parameter). Short so >= 3 ticks fit in a
# bounded idle window. Owner may raise the production default; the test sets it.
INTERVAL = 0.15
# Idle window: long enough that a working timer emits many ticks (>= 3 needed).
IDLE_WINDOW = 1.5


class _Recorder:
    """Thread-safe frame sink with per-frame monotonic timestamps."""

    def __init__(self) -> None:
        self.frames: list[tuple[float, dict[str, Any]]] = []
        self._lock = threading.Lock()

    def __call__(self, message: dict[str, Any]) -> None:
        with self._lock:
            self.frames.append((time.monotonic(), message))

    def count(self, kind: str) -> int:
        with self._lock:
            return sum(1 for _, m in self.frames if m.get("kind") == kind)

    def has(self, kind: str, **fields: Any) -> bool:
        with self._lock:
            for _, m in self.frames:
                if m.get("kind") != kind:
                    continue
                if all(m.get(k) == v for k, v in fields.items()):
                    return True
            return False

    def first(self, kind: str, **fields: Any) -> dict[str, Any] | None:
        with self._lock:
            for _, m in self.frames:
                if m.get("kind") == kind and all(m.get(k) == v for k, v in fields.items()):
                    return m
            return None


def _write_config(tmp_path: Path) -> Path:
    """Minimal config: a callable role with parent_context OFF and a fake-pi
    harness that accepts a prompt then NEVER responds (job stays running)."""
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
    # A fake Pi RPC that reads a prompt, writes a launch marker (so the test can
    # prove the harness group is alive), then blocks forever WITHOUT answering.
    # The dispatcher keeps the job "running" and the worker process group alive
    # for the whole idle window; no terminal outcome is ever produced.
    fake_pi = tmp_path / "fake-pi-hold"
    fake_pi.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys,time\n"
        "marker=os.environ['FAKE_PI_MARKER']\n"
        "for raw in sys.stdin:\n"
        "    raw=raw.strip()\n"
        "    if not raw: continue\n"
        "    m=json.loads(raw)\n"
        "    if m.get('type')=='prompt':\n"
        "        open(marker,'w').write(str(os.getpid())+chr(10)+str(os.getpgid(0))+chr(10))\n"
        "        sys.stdout.flush()\n"
        "        time.sleep(3600)  # never respond: job stays running\n",
        encoding="utf-8",
    )
    fake_pi.chmod(0o755)
    (d / "harnesses.yaml").write_text(
        f'pi:\n  harness: pi\n  command: ["{fake_pi}"]\n', encoding="utf-8"
    )
    # Role opts OUT of parent-context capture so submit launches without any
    # native request; auto_verify off so no follow-up job is queued.
    (d / "agent-catalog.yaml").write_text(
        "default_role: builder\nmodel_limits: {}\nroles:\n"
        "  builder:\n    enabled: manual\n    harness_config: pi\n"
        '    model: "m1"\n    env: {}\n    skills: []\n'
        "    dispatch_hint: Build.\n    auto_verify: false\n"
        "    parent_context: false\n",
        encoding="utf-8"
    )
    (tmp_path / "state").mkdir()
    (tmp_path / "logs").mkdir()
    return d


def _wait_for(cond: Any, timeout: float, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(interval)
    return bool(cond())


def test_backstop_wakes_idle_core_while_work_outstanding(tmp_path: Path, monkeypatch: Any) -> None:
    config_dir = _write_config(tmp_path)
    marker = tmp_path / "worker-alive.marker"
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(config_dir))
    monkeypatch.setenv("PYTHONPATH", str(REPO_ROOT / "src"))
    pi_sessions = tmp_path / "pi-sessions"
    pi_sessions.mkdir(exist_ok=True)
    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(pi_sessions))
    monkeypatch.setenv("FAKE_PI_MARKER", str(marker))

    config = load_orchestra_config()
    state_dir = config.runtime.state_dir
    queue = JobQueue(state_dir / "queue.db")
    recorder = _Recorder()

    runtime = SessionRuntime(
        queue=queue,
        parent_session=SESSION,
        state_dir=state_dir,
        prompts=config.prompts,
        send=recorder,
        mode="on",
        interval=INTERVAL,  # TEST constructor parameter
        config=config,
    )

    # REAL OS pipe feeding a REAL _StdinSource (a fake poll double would hide the
    # select(timeout=None) block that this race is about).
    read_fd, write_fd = os.pipe()
    source_stream = os.fdopen(read_fd, "rb", buffering=0)
    serve_thread = threading.Thread(target=runtime.serve, args=(_StdinSource(source_stream),), daemon=True)
    serve_thread.start()

    worker_pgid: int | None = None
    try:
        # 1) One dispatch request over the real pipe (the ONLY inbound frame).
        dispatch = {"kind": KIND_REQUEST, "id": 1, "operation": "dispatch", "arguments": {"goal": "hold open"}}
        os.write(write_fd, (encode_line(dispatch) + "\n").encode("utf-8"))

        # 2) Real out-of-band acknowledgement with a run id.
        ack_ok = _wait_for(
            lambda: "result" in (recorder.first(KIND_REPLY, id=1) or {}),
            timeout=12.0,
        )
        ack_frame = recorder.first(KIND_REPLY, id=1)
        assert ack_ok and ack_frame is not None and "result" in ack_frame, (
            f"dispatch ack must arrive; frames={[m for _, m in recorder.frames]}"
        )
        run_id = str(ack_frame["result"]["run_id"])
        assert run_id

        # 3) The owned worker is genuinely running with a registered process
        #    group (process manifest / creation identity present), and stays alive.
        def _running() -> bool:
            job = next((j for j in queue.snapshot(SESSION).jobs if j.run_id == run_id), None)
            return job is not None and job.status == "running" and job.child_pgid is not None

        running_ok = _wait_for(_running, timeout=12.0)
        job = next((j for j in queue.snapshot(SESSION).jobs if j.run_id == run_id), None)
        assert running_ok and job is not None, (
            f"job must be running with a registered group; got {job}"
        )
        assert job.child_pgid is not None and job.child_start is not None
        worker_pgid = int(job.child_pgid)

        # The fake-pi process wrote its alive marker, proving the owned worker
        # group is alive (not just claimed in the queue).
        alive_ok = _wait_for(lambda: marker.exists(), timeout=12.0)
        assert alive_ok, "controlled fake-pi worker must be alive during the window"

        # 4) Idle window: send NO further inbound frames from here. The serve
        #    loop has already re-entered poll after the single dispatch frame.
        #    Let any ack-path evaluation settle, then take the baseline tick count.
        time.sleep(0.3)
        baseline = recorder.count(KIND_STATUS)
        assert baseline >= 1, "initial progress (>=1 running-meter status) must appear"
        window_start = time.monotonic()

        time.sleep(IDLE_WINDOW)

        ticks_during_idle = recorder.count(KIND_STATUS) - baseline
        window_end = time.monotonic()

        # 5) The owned worker must STILL be running (no completion), and no
        #    native delivery / context request may have fired (no prompt answer).
        job = next((j for j in queue.snapshot(SESSION).jobs if j.run_id == run_id), None)
        assert job is not None and job.status == "running", (
            f"owned worker must still be running through the idle window; got {job.status if job else None}"
        )
        assert not recorder.has(KIND_NATIVE_REQUEST, operation="deliver_report"), (
            "no report delivery may occur while the job is still running"
        )

        # GUARANTEE: the backstop must repeatedly wake the idle core session.
        # With a working timer at INTERVAL this yields ~IDLE_WINDOW/INTERVAL
        # ticks; the race yields 0 because the blocked poll(None) never wakes.
        assert ticks_during_idle >= 3, (
            "the periodic backstop must wake the idle core session while work is "
            f"outstanding: expected >=3 status/evaluation pushes during a "
            f"{IDLE_WINDOW}s idle window (interval={INTERVAL}s) with no inbound "
            f"frames, got {ticks_during_idle}. "
            f"baseline_status={baseline}, window={window_start:.3f}..{window_end:.3f}, "
            f"worker_status={job.status}, run={run_id}"
        )
    finally:
        # Owner-only teardown, runs even on assertion failure.
        runtime.close()
        # Unblock a blocked poll(None): closing the write half yields EOF on the
        # read half, the selector returns readable, os.read returns b'', loop ends.
        try:
            os.close(write_fd)
        except OSError:
            pass
        serve_thread.join(timeout=5.0)
        with contextlib.suppress(OSError):
            source_stream.close()

        # Kill the launched worker process group (__run dispatcher, its own
        # session) and the controlled fake-pi group via the recorded identity.
        for proc in list(getattr(runtime, "_workers", [])):
            pg = proc.pid
            start = launch_start_time(pg)
            terminate_group(pg, start, grace=2.0, kill_grace=2.0)
            with contextlib.suppress(Exception):
                proc.wait(timeout=3.0)
        if worker_pgid is not None:
            # The fake-pi is launched in its OWN session by the harness, so it is
            # not in the worker group; terminate it by its recorded identity.
            job = next((j for j in queue.snapshot(SESSION).jobs if True), None)
            start = job.child_start if job is not None else None
            terminate_group(worker_pgid, start, grace=2.0, kill_grace=2.0)

        queue.close()
