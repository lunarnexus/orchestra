"""Per-dispatcher OS lifetime lock.

One flock per dispatcher process gives reconciliation a trustworthy liveness
signal without a supervisor or a heartbeat. The dispatcher holds the lock for
its whole life; when the process dies, the kernel releases it. A harness child
is launched with ``start_new_session=True`` and Python file descriptors are
close-on-exec, so the lock descriptor is never inherited by a child that could
keep abandoned work falsely marked live.

The lock file is created once and never unlinked or recreated while its token
may still be referenced by a running job, so its inode is stable for the whole
lifetime of that work.
"""

from __future__ import annotations

import fcntl
import os
from enum import Enum
from pathlib import Path
from typing import Self


class Liveness(Enum):
    """Result of probing one dispatcher's lifetime lock."""

    ALIVE = "alive"  # the lock is held: this dispatcher is running
    DEAD = "dead"  # the lock file exists but is unlocked: the dispatcher died
    MISSING = "missing"  # no lock file: the token is not a live dispatcher


class DispatcherLifetimeLock:
    """Holds one dispatcher's exclusive lifetime lock.

    Keep the instance referenced for the entire dispatch so the descriptor
    stays open and the lock stays held. Closing it (or process exit) releases
    the lock; reconciliation observes that release as dispatcher death.
    """

    def __init__(self, path: Path | str, token: str) -> None:
        self._path = Path(path)
        self.token = token
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Non-inheritable + close-on-exec: os.open without O_INHERIT, and the
        # resulting fd is marked FD_CLOEXEC by CPython, so exec'd children drop
        # it. The inode is stable: open the existing file, never unlink it.
        self._fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(self._fd, fcntl.LOCK_EX)

    @classmethod
    def create(cls, state_dir: Path | str, token: str) -> DispatcherLifetimeLock:
        return cls(Path(state_dir) / "dispatcher.locks" / f"{token}.lock", token)

    def close(self) -> None:
        if self._fd >= 0:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = -1

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def _lock_path(state_dir: Path | str, token: str) -> Path:
    return Path(state_dir) / "dispatcher.locks" / f"{token}.lock"


def probe(state_dir: Path | str, token: str) -> Liveness:
    """Probe one dispatcher token's liveness without disturbing a live lock.

    A nonblocking exclusive acquire succeeds only when no live process holds
    it, so a successful probe means death. Contention means the dispatcher is
    alive and its work must be left alone.
    """
    path = _lock_path(state_dir, token)
    if not path.exists():
        return Liveness.MISSING
    fd = os.open(path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return Liveness.ALIVE
    finally:
        # On the success path we momentarily held it; release immediately.
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    return Liveness.DEAD
