"""Connected dispatcher-loss reconciliation through real SQLite + processes.

These tests inject real deaths (SIGKILL of a live "dispatcher" subprocess that
holds the lifetime lock) and prove reconciliation terminates surviving owned
execution and persists truthful outcomes, while never touching a live
dispatcher's work.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import psutil

from orchestra import lifetime, reconcile
from orchestra.lifetime import DispatcherLifetimeLock
from orchestra.queue import JobQueue

REPO_SRC = Path(__file__).resolve().parents[1] / "src"

# A fake dispatcher: holds a lifetime lock, claims one job with its token,
# launches a surviving child, registers its execution, then blocks until
# killed. Writes its child pid to ``child`` so the test can observe survival.
_FAKE_DISPATCHER = f"""
import os, sys, time
sys.path.insert(0, {str(REPO_SRC)!r})
from orchestra.queue import JobQueue
from orchestra.lifetime import DispatcherLifetimeLock

state_dir = sys.argv[1]; token = sys.argv[2]
queue = JobQueue(os.path.join(state_dir, "queue.db"))
job = queue.add_job(run_id="r1", parent_session="s1", role="shell", model="sh")
dep = queue.add_job(run_id="r1", parent_session="s1", role="shell", model="sh",
                    prerequisites=[job.job_id])
with DispatcherLifetimeLock.create(state_dir, token):
    claimed = queue.claim_next(global_limit=1, per_session_limit=1,
                               dispatcher_token=token)
    child = __import__("subprocess").Popen([sys.executable, "-c",
        "import time; time.sleep(120)"], start_new_session=True)
    start = __import__("psutil").Process(child.pid).create_time()
    queue.register_execution(claimed.job_id, pgid=child.pid, child_start=start)
    with open(os.path.join(state_dir, "child"), "w") as fh:
        fh.write(str(child.pid))
    print("READY", flush=True)
    time.sleep(120)  # hold the lock until killed
"""


def _wait_for(pred: Callable[[], object], timeout: float = 15.0, interval: float = 0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(interval)
    return False


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _spawn_dispatcher(tmp_path: Path, token: str) -> subprocess.Popen[str]:
    proc = subprocess.Popen(
        [sys.executable, "-c", _FAKE_DISPATCHER, str(tmp_path), token],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    line = proc.stdout.readline().strip()  # blocks until the child is registered
    assert line == "READY", f"fake dispatcher not ready: {line!r}"
    return proc


def _child_pgid(tmp_path: Path) -> int:
    return int((tmp_path / "child").read_text())


def test_dispatcher_death_finalizes_and_terminates_surviving_child(
    tmp_path: Path,
) -> None:
    queue = JobQueue(tmp_path / "queue.db")  # open before dispatch creates rows
    dispatcher = _spawn_dispatcher(tmp_path, "tok-dead")
    try:
        # The dispatcher registered a running job and a surviving child group.
        assert _wait_for(lambda: queue.running_jobs(dispatcher_token="tok-dead"))
        child_pgid = _child_pgid(tmp_path)
        assert _group_alive(child_pgid)

        # Inject the dispatcher's death and prove it actually happened.
        dispatcher.kill()
        assert dispatcher.wait(timeout=10) != 0
        assert not psutil.pid_exists(dispatcher.pid)
        # Its child outlives it (reparented, own process group).
        assert _group_alive(child_pgid)

        report = reconcile.reconcile_abandoned(queue, tmp_path, grace=2.0)

        running = queue.get_job("r1:1")
        assert running.status == "failed"
        assert report.action_of("r1:1") == "terminated-finalized"
        # The registered execution group was actually terminated.
        assert _wait_for(lambda: not _group_alive(child_pgid))
        # The dependent was released through the existing failure path.
        assert queue.get_job("r1:2").status == "skipped"
    finally:
        if _group_alive(_child_pgid(tmp_path)):
            os.killpg(_child_pgid(tmp_path), signal.SIGKILL)
        queue.close()


def test_child_death_before_reconcile_finalizes_as_gone(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "queue.db")
    dispatcher = _spawn_dispatcher(tmp_path, "tok-child")
    child_pgid = _child_pgid(tmp_path)
    try:
        assert _wait_for(lambda: queue.running_jobs(dispatcher_token="tok-child"))
        # Kill the dispatcher AND its child together: both die, injected.
        dispatcher.kill()
        dispatcher.wait(timeout=10)
        os.killpg(child_pgid, signal.SIGKILL)
        assert _wait_for(lambda: not _group_alive(child_pgid))

        report = reconcile.reconcile_abandoned(queue, tmp_path, grace=2.0)

        assert queue.get_job("r1:1").status == "failed"
        assert report.action_of("r1:1") == "terminated-finalized"
    finally:
        queue.close()


def test_live_dispatcher_work_is_left_untouched(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "queue.db")
    dispatcher = _spawn_dispatcher(tmp_path, "tok-live")
    child_pgid = _child_pgid(tmp_path)
    try:
        assert _wait_for(lambda: queue.running_jobs(dispatcher_token="tok-live"))
        # The dispatcher is alive: its lock is held, so reconcile leaves it.
        report = reconcile.reconcile_abandoned(queue, tmp_path, grace=2.0)

        assert queue.get_job("r1:1").status == "running"
        assert report.action_of("r1:1") is None  # not even reported
        assert _group_alive(child_pgid)  # foreign/live work untouched
    finally:
        dispatcher.kill()
        dispatcher.wait(timeout=10)
        if _group_alive(child_pgid):
            os.killpg(child_pgid, signal.SIGKILL)
        queue.close()


def test_recycled_identity_is_retained_not_signaled(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "queue.db")
    dispatcher = _spawn_dispatcher(tmp_path, "tok-recycled")
    child_pgid = _child_pgid(tmp_path)
    try:
        assert _wait_for(lambda: queue.running_jobs(dispatcher_token="tok-recycled"))
        # Simulate PID reuse: the group is alive but the recorded creation
        # identity no longer matches. Reconcile must not signal and must retain.
        with queue._transaction():  # test-only identity corruption
            queue._conn.execute(
                "UPDATE jobs SET child_start = child_start - 3600 WHERE job_id='r1:1'"
            )
        dispatcher.kill()
        dispatcher.wait(timeout=10)

        report = reconcile.reconcile_abandoned(queue, tmp_path, grace=2.0)

        assert queue.get_job("r1:1").status == "running"  # never falsely finalized
        assert report.action_of("r1:1") == "retained-unverified"
        assert _group_alive(child_pgid)  # never signaled
    finally:
        if _group_alive(child_pgid):
            os.killpg(child_pgid, signal.SIGKILL)
        queue.close()


def test_missing_lock_retains_unconfirmed_loss(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "queue.db")
    job = queue.add_job(run_id="r3", parent_session="s1", role="shell", model="sh")
    # Claimed by a dispatcher and execution registered, but the dispatcher's
    # lifetime lock file never exists (the token is not a live dispatcher).
    # Absence of the lock is NOT proof of death, so reconcile must retain and
    # report instead of finalizing or signaling on an unproven loss.
    queue.claim_next(global_limit=1, per_session_limit=1, dispatcher_token="tok-nolock")
    queue.register_execution(job.job_id, pgid=2**31 - 1, child_start=time.time())
    assert lifetime.probe(tmp_path, "tok-nolock") is lifetime.Liveness.MISSING

    report = reconcile.reconcile_abandoned(queue, tmp_path, grace=1.0)

    assert queue.get_job(job.job_id).status == "running"
    assert report.action_of(job.job_id) == "retained-missing"
    queue.close()


def test_dead_dispatcher_with_no_registered_group_is_retained(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "queue.db")
    job = queue.add_job(run_id="r4", parent_session="s1", role="shell", model="sh")
    queue.claim_next(global_limit=1, per_session_limit=1, dispatcher_token="tok-nogroup")
    # The dispatcher died after releasing its held lock: the lock file exists but
    # is unlocked, so the loss is confirmed DEAD. With no execution group
    # recorded, the accepted spawn-before-registration limitation must be
    # retained and reported, never finalized as if the unfinished work were
    # proven absent.
    lock = DispatcherLifetimeLock.create(tmp_path, "tok-nogroup")
    lock.close()
    assert lifetime.probe(tmp_path, "tok-nogroup") is lifetime.Liveness.DEAD
    assert queue.get_job(job.job_id).child_pgid is None

    report = reconcile.reconcile_abandoned(queue, tmp_path, grace=1.0)

    assert queue.get_job(job.job_id).status == "running"
    assert report.action_of(job.job_id) == "retained-unverified"
    queue.close()


def test_token_without_lock_is_retained_not_finalized(tmp_path: Path) -> None:
    queue = JobQueue(tmp_path / "queue.db")
    job = queue.add_job(run_id="r2", parent_session="s1", role="shell", model="sh")
    # A token that never held a lock: no lock file exists, so the dispatcher's
    # death cannot be confirmed. Under the safe contract an unconfirmed loss is
    # retained and reported, not finalized as unregistered work.
    queue.claim_next(global_limit=1, per_session_limit=1, dispatcher_token="tok-nowin")
    assert queue.get_job(job.job_id).child_pgid is None

    report = reconcile.reconcile_abandoned(queue, tmp_path, grace=1.0)

    assert queue.get_job(job.job_id).status == "running"
    assert report.action_of(job.job_id) == "retained-missing"
    queue.close()
