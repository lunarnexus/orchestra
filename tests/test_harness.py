"""Tests for the harness contract and shell command plugin.

All tests run real processes with real data; no mocks.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from orchestra.harness import Budgets, CommandJob, Harness, HarnessError, Outcome
from orchestra.shell import ShellHandle, ShellHarness


@pytest.fixture()
def harness() -> ShellHarness:
    return ShellHarness()


def _wait_started(handle: ShellHandle, timeout: float = 5.0) -> None:
    """Block until the command has actually spawned its process group."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if handle.pgid is not None:
            return
        time.sleep(0.01)
    pytest.fail("command never started")


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_group_gone(pgid: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _group_alive(pgid):
            return
        time.sleep(0.05)
    pytest.fail(f"process group {pgid} still alive after kill")


def test_real_command_exit_code_and_output(harness: ShellHarness) -> None:
    outcome = harness.execute(
        CommandJob("j1", ("/bin/echo", "hello orchestra")), Budgets()
    )
    assert outcome.success
    assert outcome.exit_status == 0
    assert outcome.output == "hello orchestra\n"
    assert outcome.error == ""
    assert outcome.started_at <= outcome.finished_at
    assert outcome.transcript is None


def test_printf_and_multiline_output(harness: ShellHarness) -> None:
    outcome = harness.execute(
        CommandJob("j2", ("/usr/bin/printf", "a\nb\n")), Budgets()
    )
    assert outcome.success
    assert outcome.output == "a\nb\n"


def test_failing_command_captured_as_failure(harness: ShellHarness) -> None:
    outcome = harness.execute(
        CommandJob("j3", ("/bin/sh", "-c", "echo out; echo err >&2; exit 7")), Budgets()
    )
    assert not outcome.success
    assert outcome.exit_status == 7
    assert outcome.output == "out\n"
    assert outcome.error == "err\n"
    assert not outcome.terminated


def test_stderr_only_failure(harness: ShellHarness) -> None:
    outcome = harness.execute(
        CommandJob("j4", ("/bin/sh", "-c", "echo bad >&2; exit 1")), Budgets()
    )
    assert not outcome.success
    assert outcome.exit_status == 1
    assert outcome.output == ""
    assert outcome.error == "bad\n"


def test_hard_timeout_kills_whole_process_group(harness: ShellHarness) -> None:
    # Parent spawns a child that spawns a grandchild; all share the group.
    runaway = (
        "/usr/bin/python3",
        "-c",
        (
            "import subprocess\n"
            "subprocess.Popen(['/bin/sh', '-c', 'sleep 300'])\n"
            "import time\n"
            "time.sleep(300)\n"
        ),
    )
    handle = ShellHandle()
    outcome = harness.execute(
        CommandJob("j5", runaway), Budgets(hard_timeout=1), handle
    )
    assert not outcome.success
    assert outcome.terminated
    assert outcome.exit_status is None
    pgid = handle.pgid
    assert pgid is not None
    _wait_group_gone(pgid)
    with pytest.raises(ProcessLookupError):
        os.killpg(pgid, 0)
    assert outcome.finished_at - outcome.started_at < 30


def test_terminate_cancels_running_job(harness: ShellHarness) -> None:
    handle = ShellHandle()
    results: list[Outcome] = []

    def run() -> None:
        results.append(
            harness.execute(CommandJob("j6", ("/bin/sleep", "60")), Budgets(), handle)
        )

    thread = threading.Thread(target=run)
    thread.start()
    try:
        _wait_started(handle)
        harness.terminate(handle)
        thread.join(timeout=10)
    finally:
        if thread.is_alive():
            harness.terminate(handle)
            thread.join(timeout=5)
    assert not thread.is_alive()
    outcome = results[0]
    assert not outcome.success
    assert outcome.terminated
    assert outcome.exit_status is None
    pgid = handle.pgid
    assert pgid is not None
    _wait_group_gone(pgid)


def test_request_wrap_up_is_documented_no_op(harness: ShellHarness) -> None:
    handle = ShellHandle()
    outcome_box: list[Outcome] = []

    def run() -> None:
        outcome_box.append(
            harness.execute(CommandJob("j7", ("/bin/sleep", "1")), Budgets(), handle)
        )

    thread = threading.Thread(target=run)
    thread.start()
    try:
        _wait_started(handle)
        harness.request_wrap_up(handle)  # no-op; must not raise or disturb the job
        thread.join(timeout=10)
    finally:
        if thread.is_alive():
            harness.terminate(handle)
            thread.join(timeout=5)
    assert outcome_box[0].success
    assert not outcome_box[0].terminated


def test_command_not_found_is_loud(harness: ShellHarness) -> None:
    with pytest.raises(HarnessError, match="no-such-command-xyz"):
        harness.execute(CommandJob("j8", ("no-such-command-xyz",)), Budgets())


def test_empty_argv_is_loud(harness: ShellHarness) -> None:
    with pytest.raises(HarnessError, match="empty command"):
        harness.execute(CommandJob("j9", ()), Budgets())


def test_large_output_captured_without_truncation(tmp_path: Path) -> None:
    payload_file = tmp_path / "payload.bin"
    payload = ("x" * 99 + "\n") * 1000  # ~100KB
    payload_file.write_text(payload, encoding="utf-8")
    outcome = ShellHarness().execute(
        CommandJob("j10", ("/usr/bin/python3", "-c", "import sys;sys.stdout.write(open(sys.argv[1]).read())", str(payload_file))),
        Budgets(),
    )
    assert outcome.success
    assert outcome.output == payload
    assert len(outcome.output.encode()) == len(payload.encode())


def test_turn_limit_is_unused_for_commands(harness: ShellHarness) -> None:
    outcome = harness.execute(
        CommandJob("j11", ("/bin/echo", "done")),
        Budgets(soft_timeout=1, hard_timeout=30, turn_limit=3),
    )
    assert outcome.success
    assert outcome.exit_status == 0
    assert outcome.output == "done\n"


def test_no_hard_timeout_runs_to_completion(harness: ShellHarness) -> None:
    outcome = harness.execute(
        CommandJob("j12", ("/bin/sleep", "0.2")), Budgets()
    )
    assert outcome.success
    assert outcome.exit_status == 0


def test_contract_shape() -> None:
    assert isinstance(ShellHarness(), Harness)
    assert isinstance(ShellHandle(), object)


@pytest.fixture()
def _cleanup_zombies() -> Iterator[None]:
    yield
