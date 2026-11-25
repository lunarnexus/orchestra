"""Bounded termination of one recorded execution group.

This is the single termination path shared by cancellation, hard timeout, and
dispatcher-loss reconciliation. It never walks a process tree: a job's own
launch pid is also its process-group id (both harnesses launch with
``start_new_session=True``), so the group is terminated directly. Identity is
verified before any signal so a recycled PID is never signaled, and execution
is confirmed gone before the caller finalizes work.

Termination is kept deliberately separate from queue/database finalization:
this module only touches processes and reports what happened.
"""

from __future__ import annotations

import os
import signal
import time
from dataclasses import dataclass
from enum import Enum

import psutil

# create_time is read from the same platform source at launch and at
# reconciliation, so only a tiny tolerance guards float representation.
_START_TOLERANCE = 0.001


class Termination(str, Enum):
    """Outcome of one bounded termination attempt."""

    GONE = "gone"  # execution is confirmed no longer running
    UNVERIFIED = "unverified"  # identity could not be proven; nothing was signaled
    FAILED = "failed"  # still running after bounded SIGTERM then SIGKILL


@dataclass(frozen=True)
class TerminationResult:
    outcome: Termination
    pgid: int
    detail: str = ""


def launch_start_time(pid: int) -> float | None:
    """Read one process's creation identity for PID-reuse detection.

    Returns None when the identity cannot be read, so a caller records that
    the execution is unregistered rather than guessing.
    """
    try:
        return psutil.Process(pid).create_time()
    except (psutil.Error, OSError):
        return None


def _group_empty(pgid: int) -> bool:
    """Return True when no live member remains in the process group.

    Uses signal-0 as a group-existence probe: ESRCH means no process carries
    this pgid.  macOS EPERM with signal 0 means the group leader is an
    unreaped zombie with no other live members — effectively gone.
    """
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        # macOS: group leader is a zombie not yet reaped; no live members
        # remain to carry work forward.
        return True
    return False


def _identity(pgid: int, expected_start: float) -> str:
    """Classify the group leader identity against a recorded start time.

    Returns ``owned`` (match), ``gone`` (slot empty), ``recycled`` (different
    process now holds the slot), or ``inaccessible`` (cannot read).
    """
    try:
        proc = psutil.Process(pgid)
    except psutil.NoSuchProcess:
        return "gone"
    except psutil.AccessDenied:
        return "inaccessible"
    if proc.status() == psutil.STATUS_ZOMBIE:
        return "gone"  # already dead, awaiting reap by init
    if abs(proc.create_time() - expected_start) > _START_TOLERANCE:
        return "recycled"
    return "owned"


def _signal_group(pgid: int, sig: int) -> None:
    """Signal the group, tolerating an already-gone or zombie leader.

    Confirmation is left to :func:`_wait_gone`, so a swallow here never means
    "definitely gone" on its own.
    """
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        # macOS reports EPERM (not ESRCH) for a group whose leader is an
        # unreaped zombie; the group is gone.
        pass


def _wait_gone(pgid: int, timeout: float) -> bool:
    """Poll until no live member remains in the process group.

    Group membership — not just the leader slot — determines whether
    execution is still alive.  A SIGTERM that exits the leader while a
    same-group child survives does not constitute termination until the
    entire group is confirmed empty.
    """
    deadline = time.monotonic() + timeout
    while True:
        if _group_empty(pgid):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def terminate_group(
    pgid: int,
    expected_start: float | None = None,
    *,
    grace: float = 5.0,
    kill_grace: float = 5.0,
) -> TerminationResult:
    """Terminate one recorded execution group and confirm it is gone.

    Verifies recorded identity first (``expected_start`` from psutil
    create_time); on any mismatch or inaccessibility it signals nothing and
    returns UNVERIFIED.  Otherwise it sends SIGTERM to the group, waits a
    bounded ``grace``, escalates to SIGKILL, and confirms no live group
    member remains.

    Reconciliation passes the recorded start token; live cancellation passes
    None because it terminates its own known child.
    """
    if expected_start is None:
        # Own-child caller: identity is inherent from having spawned the
        # process.  Only check whether the group has live work remaining.
        if _group_empty(pgid):
            return TerminationResult(Termination.GONE, pgid, "already gone")
        # Group has live members we own — fall through to terminate.
    else:
        # Identity-verified path (reconciliation): never signal a recycled slot.
        kind = _identity(pgid, expected_start)
        if kind == "gone":
            if _group_empty(pgid):
                return TerminationResult(Termination.GONE, pgid, "already gone")
            # Leader exited but group members survive: no ownership proof.
            return TerminationResult(
                Termination.UNVERIFIED, pgid, "group members survive leader"
            )
        if kind in ("recycled", "inaccessible"):
            return TerminationResult(Termination.UNVERIFIED, pgid, kind)
        # kind == "owned": proceed to signal.

    _signal_group(pgid, signal.SIGTERM)
    if _wait_gone(pgid, grace):
        return TerminationResult(Termination.GONE, pgid, "terminated")

    _signal_group(pgid, signal.SIGKILL)
    if _wait_gone(pgid, kill_grace):
        return TerminationResult(Termination.GONE, pgid, "killed")

    return TerminationResult(Termination.FAILED, pgid, "still running after SIGKILL")
