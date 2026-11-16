"""Shell command harness plugin for Orchestra 2.

Runs an external command as argv (never shell syntax) in its own process
group via ``start_new_session=True``. ``terminate`` kills the whole group;
``request_wrap_up`` is a no-op because commands cannot cooperate. The hard
timeout is enforced inside ``execute``: on expiry the process group is
killed and the outcome reports failure. ``soft_timeout`` and ``turn_limit``
have no meaning for commands and are ignored.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time

from orchestra.harness import Budgets, CommandJob, Handle, HarnessError, Outcome


class ShellHandle:
    """Execution state for one running shell command."""

    def __init__(self) -> None:
        self.job_id: str | None = None
        self.process: subprocess.Popen[str] | None = None
        self.terminated = False

    @property
    def pgid(self) -> int | None:
        """Process group id once the command has started, else None."""
        if self.process is None or self.process.pid is None:
            return None
        return self.process.pid  # start_new_session makes pgid equal to pid


class ShellHarness:
    """Harness plugin for external command jobs."""

    def execute(
        self,
        job: CommandJob,
        budgets: Budgets,
        handle: Handle | None = None,
    ) -> Outcome:
        """Run the command, capturing stdout/stderr, enforcing the hard timeout."""
        if not isinstance(handle, ShellHandle):
            handle = ShellHandle()
        assert isinstance(handle, ShellHandle)
        shell_handle = handle

        if not job.argv:
            raise HarnessError(f"job {job.job_id!r} has an empty command")
        shell_handle.job_id = job.job_id
        started_at = time.time()
        try:
            process: subprocess.Popen[str] = subprocess.Popen(
                job.argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
        except OSError as exc:
            raise HarnessError(
                f"failed to launch command for job {job.job_id!r}: "
                f"{job.argv[0]!r}: {exc}"
            ) from exc
        shell_handle.process = process

        terminated = False
        deadline = (
            time.monotonic() + budgets.hard_timeout
            if budgets.hard_timeout is not None
            else None
        )
        output = ""
        error = ""
        while True:
            remaining = None if deadline is None else max(deadline - time.monotonic(), 0)
            try:
                output, error = process.communicate(timeout=remaining)
                break
            except subprocess.TimeoutExpired:
                self.terminate(shell_handle)
                terminated = True
                output, error = process.communicate()
                break

        terminated = terminated or shell_handle.terminated
        finished_at = time.time()
        exit_status: int | None = (
            process.returncode if process.returncode is not None and not terminated else None
        )
        success = process.returncode == 0 and not terminated
        return Outcome(
            success=success,
            exit_status=exit_status,
            output=output,
            error=error,
            started_at=started_at,
            finished_at=finished_at,
            terminated=terminated,
            transcript=None,
        )

    def new_handle(self) -> Handle:
        """Return a fresh handle the dispatcher can pass to execute."""
        return ShellHandle()

    def request_wrap_up(self, handle: Handle) -> None:
        """No-op: shell commands cannot cooperatively wrap up."""
        assert isinstance(handle, ShellHandle)

    def terminate(self, handle: Handle) -> None:
        """Kill the command's whole process group."""
        if not isinstance(handle, ShellHandle):
            raise HarnessError("terminate expects a ShellHandle from this harness")
        pgid = handle.pgid
        if pgid is None:
            raise HarnessError("cannot terminate a command that has not started")
        handle.terminated = True
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # already gone
        except PermissionError:
            # macOS quirk: killpg on a group whose leader is an unreaped
            # zombie reports EPERM instead of ESRCH; the group is gone.
            pass
