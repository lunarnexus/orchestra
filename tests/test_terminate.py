"""Shared bounded termination of a recorded execution group.

Covers the one helper cancellation, hard timeout, and reconciliation share:
verify recorded identity, SIGTERM, bounded wait, SIGKILL, confirm gone.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Callable

import psutil

from orchestra.terminate import Termination, terminate_group


def _wait(cond: Callable[[], bool], timeout: float = 10.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(interval)
    return False


def _spawn(argv: list[str]) -> subprocess.Popen[str]:
    return subprocess.Popen(argv, start_new_session=True, text=True)


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False  # macOS: group leader is an unreaped zombie -> gone
    return True


def test_gone_result_when_leader_already_exited() -> None:
    proc = _spawn(["/bin/sleep", "5"])
    pgid = proc.pid
    created = psutil.Process(pgid).create_time()
    proc.terminate()
    proc.wait()
    assert _wait(lambda: not _group_alive(pgid))
    result = terminate_group(pgid, created)
    assert result.outcome is Termination.GONE


def test_term_stops_a_terminate_friendly_group_and_confirms_gone() -> None:
    proc = _spawn(["/bin/sleep", "60"])
    pgid = proc.pid
    created = psutil.Process(pgid).create_time()
    try:
        result = terminate_group(pgid, created)
        assert result.outcome is Termination.GONE
        assert _wait(lambda: not _group_alive(pgid))
    finally:
        if _group_alive(pgid):
            os.killpg(pgid, signal.SIGKILL)
        proc.wait()


def test_refuses_to_signal_recycled_identity_without_signaling() -> None:
    # A live foreign group whose recorded start token does not match must be
    # left completely untouched: never signal a reused PID.
    proc = _spawn(["/bin/sleep", "60"])
    pgid = proc.pid
    try:
        wrong_start = psutil.Process(pgid).create_time() - 3600.0
        result = terminate_group(pgid, wrong_start)
        assert result.outcome is Termination.UNVERIFIED
        # The foreign process is still alive and was never signaled.
        assert proc.poll() is None
    finally:
        proc.terminate()
        proc.wait()


def test_escalates_to_kill_for_term_ignoring_group() -> None:
    # A child that traps SIGTERM must still be terminated by the bounded
    # SIGKILL escalation, and the group confirmed gone.
    child = (
        "import signal, time;"
        "signal.signal(signal.SIGTERM, lambda *_: None);"
        "time.sleep(120)"
    )
    proc = _spawn(["/bin/sh", "-c", child])
    pgid = proc.pid
    created = psutil.Process(pgid).create_time()
    # Ensure the trap is installed before terminating.
    assert _wait(lambda: psutil.Process(pgid).status() == psutil.STATUS_SLEEPING)
    result = terminate_group(pgid, created, grace=0.5, kill_grace=5.0)
    assert result.outcome is Termination.GONE
    assert _wait(lambda: not _group_alive(pgid))
    proc.wait()


def test_surviving_group_child_not_false_gone() -> None:
    """Leader exits on SIGTERM but a same-group child ignores it: must NOT
    report GONE until all group members are gone (via SIGKILL escalation)."""
    # sh (group leader) dies on SIGTERM (default action), but spawns a Python
    # child in the same group that ignores SIGTERM.
    script = (
        "python3 -c 'import signal,time;"
        "signal.signal(signal.SIGTERM,lambda *_:None);"
        "time.sleep(120)' & "
        "wait"
    )
    proc = _spawn(["/bin/sh", "-c", script])
    pgid = proc.pid
    created = psutil.Process(pgid).create_time()
    # Give the child time to install its signal handler.
    assert _wait(lambda: _group_alive(pgid))
    time.sleep(0.3)
    try:
        result = terminate_group(pgid, created, grace=1.0, kill_grace=5.0)
        assert result.outcome is Termination.GONE, (
            f"expected GONE after SIGKILL of surviving child, got {result.outcome}"
        )
        # Group must actually be empty.
        assert not _group_alive(pgid)
    finally:
        if _group_alive(pgid):
            os.killpg(pgid, signal.SIGKILL)
        proc.wait()


def test_leader_gone_with_surviving_member_is_unverified_not_gone() -> None:
    """Reconciliation identity path: the original group leader is gone but a
    same-group member survives, so the group's ownership is unprovable.  Must
    return UNVERIFIED and signal nothing: never kill a group whose leader slot
    is empty/recycled, and never falsely report GONE while members persist."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        pidfile = os.path.join(td, "child.pid")
        # sh (group leader) backgrounds a same-group child, records its pid,
        # then exits so the leader slot frees while the child keeps running.
        script = (
            "python3 -c 'import time;time.sleep(120)' & "
            f"echo $! > {pidfile}; exit 0"
        )
        proc = _spawn(["/bin/sh", "-c", script])
        pgid = proc.pid
        created = psutil.Process(pgid).create_time()
        try:
            assert proc.wait(timeout=10) == 0  # reap the exited leader
            # A same-group child still carries the pgid: group is alive.
            assert _wait(
                lambda: os.path.exists(pidfile) and os.path.getsize(pidfile) > 0
                and _group_alive(pgid)
            )
            with open(pidfile) as fh:
                child_pid = int(fh.read().strip())
            result = terminate_group(pgid, created)
            assert result.outcome is Termination.UNVERIFIED, (
                f"leader gone + surviving member must be UNVERIFIED, "
                f"got {result.outcome}"
            )
            # Identity safety: the surviving member was never signaled.
            child = psutil.Process(child_pid)
            assert child.is_running()
            assert child.status() != psutil.STATUS_ZOMBIE
        finally:
            if _group_alive(pgid):
                os.killpg(pgid, signal.SIGKILL)


def test_none_identity_path_returns_gone_for_exited_process() -> None:
    """expected_start=None (own-child callers) with already-exited process
    must return GONE promptly, not stall full grace/kill_grace then FAILED."""
    proc = _spawn(["/bin/sleep", "0.01"])
    pgid = proc.pid
    proc.wait()  # Reap the child so it is fully gone.
    # Use a short bounded grace so the test is fast even if buggy.
    start = time.monotonic()
    result = terminate_group(pgid, grace=0.4, kill_grace=0.4)
    elapsed = time.monotonic() - start
    assert result.outcome is Termination.GONE, (
        f"already-exited process should be GONE, got {result.outcome}"
    )
    # Must not have waited full grace + kill_grace (would be 0.8s+).
    assert elapsed < 0.3, f"None-path stalled {elapsed:.2f}s for an exited process"
