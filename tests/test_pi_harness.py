"""Tests for the Pi RPC harness plugin: real stub pi subprocess, no mocks.

The stub script speaks the Pi RPC protocol over stdin/stdout: it answers
``prompt`` events, emits assistant turns, honors a ``steer`` (wrap-up),
answers ``get_last_assistant_text``, settles, and writes a native session
transcript file so transcript lookup runs for real.
"""

from __future__ import annotations

import os
import signal
import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from orchestra.harness import Budgets, CommandJob, HarnessError, Outcome
from orchestra.pi_harness import BUDGET_SOFT_REASON, BUDGET_TURN_REASON, AgentPlan, PiHarness
from orchestra.queue import JobQueue

STUB_PI = r"""
import json, os, sys

sid = sys.argv[sys.argv.index("--session-id") + 1]
session_dir = os.environ.get("PI_CODING_AGENT_SESSION_DIR", "")
if session_dir:
    os.makedirs(session_dir, exist_ok=True)
    with open(os.path.join(session_dir, "2025-01-01T00-00-00-000Z_" + sid + ".jsonl"), "w") as f:
        f.write(json.dumps({"session_id": sid}) + "\n")
text = os.environ.get("STUB_TEXT", "stub ok")
stderr_text = os.environ.get("STUB_STDERR", "")
if stderr_text:
    sys.stderr.write(stderr_text)
    sys.stderr.flush()
wait_steer = os.environ.get("STUB_WAIT_STEER") == "1"
turns = int(os.environ.get("STUB_TURNS", "1"))
settled = False
steered = False


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    try:
        obj = json.loads(line)
    except ValueError:
        continue
    kind = obj.get("type")
    if kind == "prompt":
        send({"id": obj.get("id"), "type": "response", "success": True})
        for _ in range(turns):
            send({"type": "message", "message": {"role": "assistant"}})
        if not wait_steer:
            send({"type": "agent_settled"})
            settled = True
    elif kind == "steer" and not settled:
        steered = True
        send({"type": "message", "message": {"role": "assistant"}})
        send({"type": "agent_settled"})
        settled = True
    elif kind == "get_last_assistant_text":
        reply = "wrapped up" if steered else text
        send({"type": "response", "command": "get_last_assistant_text", "data": {"text": reply}})
"""


@pytest.fixture()
def stub_script(tmp_path: Path) -> Path:
    path = tmp_path / "stub_pi.py"
    path.write_text(STUB_PI, encoding="utf-8")
    return path


@pytest.fixture()
def sessions_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    directory = tmp_path / "sessions"
    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(directory))
    yield directory


def plan(stub_script: Path, **env: str) -> AgentPlan:
    return AgentPlan(command=("python3", str(stub_script)), model="m1", env=env)


def _wait_process(handle: object, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        process = getattr(handle, "process", None)
        if process is not None and process.poll() is None:
            time.sleep(0.1)  # let the stub reach its wait loop
            return
        time.sleep(0.01)
    pytest.fail("pi process never started")


@pytest.mark.parametrize("wrap_up", [False, True])
def test_agent_response_reaches_assembled_return(
    tmp_path: Path, stub_script: Path, sessions_dir: Path, wrap_up: bool
) -> None:
    from orchestra.cli import _record_notes
    from orchestra.config import load_orchestra_config
    from orchestra.dispatcher import run
    from orchestra.queue import JobQueue
    from orchestra.results import assemble
    from orchestra.submit import Assignment, submit

    config = load_orchestra_config(Path(__file__).resolve().parents[1])
    config = replace(
        config,
        runtime=replace(config.runtime, state_dir=tmp_path, turn_limit=2),
    )
    answer = "Quiet branches sway\nMorning settles on the pond\nLight rests on the leaves"
    with JobQueue(tmp_path / "queue.db") as queue:
        submission = submit(
            tmp_path, queue, config, "test:haiku",
            [Assignment(goal="Write a haiku", role="researcher")],
        )
        job_id = submission.jobs[0].job_id
        env = {"STUB_TEXT": answer}
        if wrap_up:
            env.update(STUB_WAIT_STEER="1", STUB_TURNS="2")
        harness = PiHarness({job_id: plan(stub_script, **env)}, "budget!")
        run(
            queue, tmp_path, harness, submission.run_id,
            global_limit=1, per_session_limit=1, payloads=submission.payloads,
        )
        _record_notes(config, submission.run_id, submission.jobs, harness)
        result = assemble(queue, tmp_path, config.prompts, submission.run_id)
        if wrap_up:
            assert result.jobs[0].status == "failed"
            assert result.category == "budget_exhausted"
            assert "wrapped up" in result.jobs[0].summary
            assert BUDGET_TURN_REASON in result.jobs[0].summary
        else:
            assert result.jobs[0].status == "succeeded"
            assert result.jobs[0].summary == answer
        assert Path(result.jobs[0].artifact_paths[0]).is_file()


def test_budget_reason_persisted_before_dependent_without_cli_notes(
    tmp_path: Path, stub_script: Path, sessions_dir: Path
) -> None:
    """A real Pi wrap-up records the budget reason in core, before the CLI pass.

    Regression for the budget-reason ownership route: the dispatcher must
    persist the wrap-up reason into the run record at completion, before the
    queue releases (here skips) the verifier dependent and before guidance
    categorizes, so the late ``_record_notes`` CLI step is not what makes a
    budget run report as ``budget_exhausted``. Uses the controlled RPC stub
    only; no live pi, model, or global session.
    """
    from orchestra.config import load_orchestra_config
    from orchestra.dispatcher import recorded_reasons, run
    from orchestra.guidance import BUDGET_EXHAUSTED, derive_return_category
    from orchestra.queue import JobQueue
    from orchestra.submit import Assignment, submit

    config = load_orchestra_config(Path(__file__).resolve().parents[1])
    config = replace(
        config,
        runtime=replace(config.runtime, state_dir=tmp_path, turn_limit=2),
    )
    with JobQueue(tmp_path / "queue.db") as queue:
        submission = submit(
            tmp_path, queue, config, "test:budget",
            [Assignment(goal="build it", role="builder")],
            context_provider=lambda: "orchestrator context",
        )
        builder, verifier = queue.list_jobs(submission.run_id)
        harness = PiHarness(
            {builder.job_id: plan(stub_script, STUB_WAIT_STEER="1", STUB_TURNS="2")},
            "budget!",
        )
        # Deliberately NO _record_notes call: only the dispatcher runs.
        run(
            queue, tmp_path, harness, submission.run_id,
            global_limit=1, per_session_limit=1, payloads=dict(submission.payloads),
        )
        assert queue.get_job(builder.job_id).status == "failed"
        assert queue.get_job(verifier.job_id).status == "skipped"
        # The budget reason is already in the dispatcher-recorded answer, so
        # guidance categorizes budget_exhausted without the CLI note pass.
        reasons = recorded_reasons(tmp_path, submission.run_id)
        assert BUDGET_TURN_REASON in reasons[builder.job_id]
        assert derive_return_category(queue, submission.run_id, reasons) == BUDGET_EXHAUSTED


def test_success_path_and_output(stub_script: Path, sessions_dir: Path) -> None:
    harness = PiHarness({"j1": plan(stub_script, STUB_TEXT="did the work")}, "budget!")
    outcome = harness.execute(CommandJob("j1", ("the assignment prompt",)), Budgets())
    assert outcome.success
    assert outcome.output == "did the work"
    assert outcome.error == ""
    assert not outcome.terminated
    assert outcome.started_at <= outcome.finished_at


def test_transcript_lookup_and_note(stub_script: Path, sessions_dir: Path) -> None:
    harness = PiHarness({"j1": plan(stub_script)}, "budget!")
    outcome = harness.execute(CommandJob("j1", ("prompt",)), Budgets())
    assert outcome.success
    assert outcome.transcript is not None
    assert outcome.transcript.endswith("_orchestra-worker-j1.jsonl")
    assert Path(str(outcome.transcript)).is_file()
    note = harness.note_for("j1")
    assert note.transcript == outcome.transcript
    assert note.reason is None


def test_turn_limit_sends_one_wrap_up_steer(stub_script: Path, sessions_dir: Path) -> None:
    harness = PiHarness({"j1": plan(stub_script, STUB_WAIT_STEER="1", STUB_TURNS="2")}, "budget!")
    outcome = harness.execute(CommandJob("j1", ("prompt",)), Budgets(turn_limit=2))
    assert not outcome.success
    assert outcome.output == "wrapped up"
    assert harness.note_for("j1").reason == BUDGET_TURN_REASON


def test_soft_timeout_sends_wrap_up_steer(stub_script: Path, sessions_dir: Path) -> None:
    harness = PiHarness({"j1": plan(stub_script, STUB_WAIT_STEER="1")}, "budget!")
    outcome = harness.execute(CommandJob("j1", ("prompt",)), Budgets(soft_timeout=1))
    assert not outcome.success
    assert outcome.output == "wrapped up"
    assert harness.note_for("j1").reason == BUDGET_SOFT_REASON


def test_missing_skills_fail_fast(stub_script: Path, sessions_dir: Path) -> None:
    missing = AgentPlan(
        command=("python3", str(stub_script)),
        model="m1",
        missing_skills=("orch-builder",),
    )
    harness = PiHarness({"j1": missing}, "budget!")
    outcome = harness.execute(CommandJob("j1", ("prompt",)), Budgets())
    assert not outcome.success
    assert harness.note_for("j1").reason == "missing skills: orch-builder"


def test_benign_pi_startup_notice_is_dropped_from_stderr(
    stub_script: Path, sessions_dir: Path
) -> None:
    """Pi's benign 'creating a new session with that id' notice is not a failure.

    Regression: the notice printed to stderr on a first worker dispatch rode
    into the captured stderr (and, via the old dispatcher concatenation, the
    delivered answer). The harness drops only that known informational notice
    and keeps all other stderr plus the stdout answer.
    """
    benign = (
        "Warning: No project session found with id "
        "'orchestra-worker-c1d73535da484378a34e79746455510b-1'; "
        "creating a new session with that id.\n"
    )
    real = "real: some diagnostic warning\n"
    harness = PiHarness(
        {"j1": plan(stub_script, STUB_TEXT="the answer", STUB_STDERR=benign + real)},
        "budget!",
    )
    outcome = harness.execute(CommandJob("j1", ("prompt",)), Budgets())
    assert outcome.success
    # The stdout answer is unaffected.
    assert outcome.output == "the answer"
    # The benign Pi startup notice is dropped; real stderr is retained.
    assert "No project session found" not in outcome.error
    assert "creating a new session with that id" not in outcome.error
    assert "real: some diagnostic warning" in outcome.error


def test_terminate_kills_process_group(stub_script: Path, sessions_dir: Path) -> None:
    harness = PiHarness({"j1": plan(stub_script, STUB_WAIT_STEER="1")}, "budget!")
    handle = harness.new_handle()
    results: list[object] = []

    def run() -> None:
        results.append(harness.execute(CommandJob("j1", ("prompt",)), Budgets(), handle))

    thread = threading.Thread(target=run)
    thread.start()
    try:
        _wait_process(handle)
        harness.terminate(handle)
        thread.join(timeout=10)
    finally:
        if thread.is_alive():
            harness.terminate(handle)
            thread.join(timeout=5)
    assert not thread.is_alive()
    outcome = results[0]
    assert not outcome.success  # type: ignore[attr-defined]
    assert outcome.terminated  # type: ignore[attr-defined]
    process = getattr(handle, "process", None)
    assert process is not None
    deadline = time.monotonic() + 5
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert process.poll() is not None


def test_execute_leaves_no_live_subprocess_or_reader_threads(
    stub_script: Path, sessions_dir: Path
) -> None:
    """After execute() returns, the stub subprocess is dead and pump threads ended."""
    for env, budgets in (({}, Budgets()), ({"STUB_WAIT_STEER": "1"}, Budgets(soft_timeout=1))):
        harness = PiHarness({"j1": plan(stub_script, **env)}, "budget!")
        handle = harness.new_handle()
        before = set(threading.enumerate())
        outcome = harness.execute(CommandJob("j1", ("prompt",)), budgets, handle)
        assert outcome.success != bool(env)
        process = getattr(handle, "process", None)
        assert process is not None
        deadline = time.monotonic() + 5
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert process.poll() is not None
        readers = [
            t
            for t in set(threading.enumerate()) - before
            if t is not threading.current_thread()
        ]
        for thread in readers:
            thread.join(timeout=5)
        assert not any(thread.is_alive() for thread in readers)


def test_prompt_placeholder_template_is_rejected(stub_script: Path, sessions_dir: Path) -> None:
    bad = AgentPlan(command=("pi", "--mode", "rpc", "-p", "{prompt}"), model="m1")
    harness = PiHarness({"j1": bad}, "budget!")
    with pytest.raises(HarnessError, match="prompt"):
        harness.execute(CommandJob("j1", ("prompt",)), Budgets())


def test_unknown_job_delegates_to_shell(tmp_path: Path, stub_script: Path, sessions_dir: Path) -> None:
    harness = PiHarness({}, "budget!")
    outcome = harness.execute(CommandJob("j2", ("/bin/echo", "hello")), Budgets())
    assert outcome.success
    assert outcome.output == "hello\n"
    assert outcome.transcript is None


# --- Item 7: a child that dies without its settle sentinel ------------------
#
# The settle-emitting stub above always reached ``agent_settled``, so nothing
# proved the failure paths for a child that never settles. These stubs answer
# the prompt and then, per ``STUB_NO_SETTLE``: ``exit`` leaves the process
# without ever settling; ``hang`` stays alive without settling, so a
# dispatcher-configured hard timeout (not the test's own teardown) must end it.

STUB_NO_SETTLE = r"""
import json, os, sys, time

mode = os.environ.get("STUB_NO_SETTLE", "exit")


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    try:
        obj = json.loads(line)
    except ValueError:
        continue
    if obj.get("type") == "prompt":
        send({"id": obj.get("id"), "type": "response", "success": True})
        if mode == "hang":
            # Stay alive without ever settling; ignores all further stdin.
            time.sleep(300)
        else:
            # Leave the process without a settle event, carrying the requested
            # exit code (default 7) so a nonzero crash and a clean code-0 exit
            # are both reproducible.
            os._exit(int(os.environ.get("STUB_EXIT_CODE", "7")))
"""


@pytest.fixture()
def no_settle_script(tmp_path: Path) -> Path:
    path = tmp_path / "stub_no_settle.py"
    path.write_text(STUB_NO_SETTLE, encoding="utf-8")
    return path


def _no_settle_plan(script: Path, mode: str, exit_code: int | None = None) -> AgentPlan:
    env = {"STUB_NO_SETTLE": mode}
    if exit_code is not None:
        env["STUB_EXIT_CODE"] = str(exit_code)
    return AgentPlan(command=("python3", str(script)), model="m1", env=env)


def _pgid_alive(pgid: int) -> bool:
    """True when the process group still has live work (signal-0 group probe)."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # live member under an unreaped zombie leader (macOS)
    return True


def _wait_running_child(queue: JobQueue, job_id: str, timeout: float = 10.0) -> int:
    """Poll until the job is running on a live registered group; return its pgid.

    Proves the controlled child actually launched and stayed alive, using a
    bounded poll instead of an assumed sleep. Fails if no live running group
    ever appears.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = queue.get_job(job_id)
        if job.child_pgid is not None and job.status == "running" and _pgid_alive(job.child_pgid):
            return job.child_pgid
        time.sleep(0.01)
    pytest.fail("child never launched a live running execution group")


def test_child_exiting_without_settle_yields_failed_outcome(
    no_settle_script: Path, sessions_dir: Path
) -> None:
    """A Pi child that exits without ``agent_settled`` yields a failed Outcome.

    Regression for the gap where the stub always emitted its settle sentinel:
    the real RPC harness must report a controlled child that leaves after its
    prompt response and never settles as a failure, with no live child left.
    """
    harness = PiHarness({"j1": _no_settle_plan(no_settle_script, "exit")}, "budget!")
    handle = harness.new_handle()
    outcome = harness.execute(CommandJob("j1", ("prompt",)), Budgets(), handle)

    assert not outcome.success  # never settled, so never a success
    assert outcome.output == ""  # never reached get_last_assistant_text
    # Reported as the observed unexpected self-exit, not a budget/rejected
    # reason and not a hard-timeout/cancellation Orchestra never requested.
    reason = harness.note_for("j1").reason
    assert reason is not None
    assert "without completing" in reason
    assert "7" in reason

    # Owner-scoped: the launched child is dead once execute() returns.
    process = getattr(handle, "process", None)
    assert process is not None
    deadline = time.monotonic() + 5
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert process.poll() is not None


def test_child_exiting_without_settle_persists_failed_job(
    tmp_path: Path, no_settle_script: Path, sessions_dir: Path
) -> None:
    """A no-settle child fails durably through the real dispatcher + SQLite.

    Connects the no-settle boundary to core: the queue reaches a terminal
    ``failed`` status and the run record keeps a failure reason, so the
    originating session is handed a real failure, not a stuck job. The precise
    unexpected-exit wording is pinned by
    :func:`test_self_exit_persists_precise_unexpected_exit_reason`.
    """
    from orchestra.config import load_orchestra_config
    from orchestra.dispatcher import recorded_reasons, run
    from orchestra.submit import Assignment, submit

    config = load_orchestra_config(Path(__file__).resolve().parents[1])
    config = replace(config, runtime=replace(config.runtime, state_dir=tmp_path))
    with JobQueue(tmp_path / "queue.db") as queue:
        submission = submit(
            tmp_path, queue, config, "test:no-settle",
            [Assignment(goal="do the work", role="builder")],
        )
        job_id = submission.jobs[0].job_id
        harness = PiHarness(
            {job_id: _no_settle_plan(no_settle_script, "exit")}, "budget!"
        )
        run(
            queue, tmp_path, harness, submission.run_id,
            global_limit=1, per_session_limit=1, payloads=submission.payloads,
        )
        assert queue.get_job(job_id).status == "failed"
        reason = recorded_reasons(tmp_path, submission.run_id)[job_id]
        # A real persisted failure with a reason, not a false success marker.
        assert reason.startswith("failed:")
        assert reason != "succeeded"

def test_hard_timeout_terminates_live_hanging_child_not_teardown(
    tmp_path: Path, no_settle_script: Path, sessions_dir: Path
) -> None:
    """A short hard timeout ends a live-hanging Pi child and persists failure.

    The controlled child stays alive without settling (an injected hang that
    would outlive the test) and the dispatcher's hard timeout — a TEST INPUT
    well below the hang and below the soft timeout / turn limit, so neither
    can be the terminator — must end the actual execution. The test never
    calls ``terminate``, so the only way the run ends and the live group dies
    is the timeout. Item 1 owns the connected idle-parent return journey; this
    covers the harness/dispatcher hard-timeout death path only.
    """
    from orchestra.config import load_orchestra_config
    from orchestra.dispatcher import recorded_reasons, run
    from orchestra.submit import Assignment, submit

    config = load_orchestra_config(Path(__file__).resolve().parents[1])
    config = replace(
        config,
        runtime=replace(
            config.runtime,
            state_dir=tmp_path,
            default_timeout=2,  # hard timeout (TEST INPUT): fires first
            soft_timeout=600,  # far later: cannot be the terminator
            turn_limit=1000,  # child emits no turns: cannot be the terminator
        ),
    )
    captured: list[int] = []
    terminated_by_timeout = False
    with JobQueue(tmp_path / "queue.db") as queue:
        submission = submit(
            tmp_path, queue, config, "test:hang",
            [Assignment(goal="hang forever", role="builder")],
        )
        job_id = submission.jobs[0].job_id
        harness = PiHarness(
            {job_id: _no_settle_plan(no_settle_script, "hang")}, "budget!"
        )
        worker = threading.Thread(
            target=run,
            args=(queue, tmp_path, harness, submission.run_id),
            kwargs={
                "global_limit": 1,
                "per_session_limit": 1,
                "payloads": submission.payloads,
            },
        )
        started = time.monotonic()
        worker.start()
        try:
            # Prove the injected live hang really existed before any timeout.
            pgid = _wait_running_child(queue, job_id)
            captured.append(pgid)
            # No teardown here: the run must end on its own via the timeout.
            # Bounded wait — if the timeout never fired, run() blocks on the
            # 300s hang and this join fails.
            worker.join(timeout=30)
            elapsed = time.monotonic() - started
            # Decisive, captured BEFORE any cleanup: the live group was already
            # gone when run() returned, so the timeout (not teardown) killed it.
            terminated_by_timeout = not _pgid_alive(pgid)
        finally:
            # Failure-safe, owner-scoped cleanup only if the timeout FAILED.
            if captured and _pgid_alive(captured[0]):
                try:
                    os.killpg(captured[0], signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if worker.is_alive():
                worker.join(timeout=5)

        assert not worker.is_alive(), "run() hung: hard timeout never fired"
        assert terminated_by_timeout, "live group survived: timeout did not terminate it"
        # The run returned on its own, having waited out the hard deadline,
        # yet far below both the hang duration and the soft timeout.
        assert elapsed >= 2.0
        assert elapsed < 60
        assert queue.get_job(job_id).status == "failed"
        reason = recorded_reasons(tmp_path, submission.run_id)[job_id]
        assert reason == "failed: terminated (hard timeout or cancellation)"


# --- Unexpected process exit vs Orchestra-requested termination -------------
#
# The no-settle finally used to flag the handle terminated unconditionally, so
# a child that exited on its own (crash or clean exit without settling) was
# reported as "hard timeout or cancellation" even though Orchestra never asked
# for it. These tests pin the corrected distinction: a self-exit reports the
# observed code as an unexpected exit, while a genuine Orchestra terminate
# (timeout/cancellation) still reports the existing termination reason.


def test_self_exit_without_settle_is_unexpected_exit_not_termination(
    no_settle_script: Path, sessions_dir: Path
) -> None:
    """A child that exits itself without settling reports its observed code.

    The harness must NOT mark the outcome terminated (Orchestra never asked),
    must record the observed nonzero exit code as the cause, and must not
    collapse it into the hard-timeout/cancellation wording.
    """
    harness = PiHarness({"j1": _no_settle_plan(no_settle_script, "exit", 7)}, "budget!")
    outcome = harness.execute(CommandJob("j1", ("prompt",)), Budgets())
    assert not outcome.success
    assert not outcome.terminated  # Orchestra never requested termination
    assert outcome.exit_status == 7  # the observed self-exit code is captured
    reason = harness.note_for("j1").reason
    assert reason is not None
    assert "7" in reason
    assert "without completing" in reason
    # The decisive regression: not mislabeled as a hard timeout/cancellation.
    from orchestra.dispatcher import _failure_reason

    assert "terminated (hard timeout" not in _failure_reason(outcome)


def test_clean_exit_without_settle_reports_observed_zero_code(
    no_settle_script: Path, sessions_dir: Path
) -> None:
    """A clean code-0 exit that never settles is still an incomplete run.

    A zero status is not a success: it is reported as an unexpected exit that
    completed nothing, carrying the observed code 0 and never as termination.
    """
    harness = PiHarness({"j1": _no_settle_plan(no_settle_script, "exit", 0)}, "budget!")
    outcome = harness.execute(CommandJob("j1", ("prompt",)), Budgets())
    assert not outcome.success
    assert not outcome.terminated
    assert outcome.exit_status == 0
    reason = harness.note_for("j1").reason
    assert reason is not None
    assert "without completing" in reason
    assert "terminated (hard timeout" not in reason


def test_self_exit_persists_precise_unexpected_exit_reason(
    tmp_path: Path, no_settle_script: Path, sessions_dir: Path
) -> None:
    """A self-exiting no-settle child persists the observed code, not timeout.

    Connected through the real dispatcher + SQLite: the persisted reason names
    the unexpected exit with the child's own exit code and explicitly not the
    hard-timeout/cancellation wording Orchestra would use for a terminate it
    requested. This is the misleading-reason regression under real persistence.
    """
    from orchestra.config import load_orchestra_config
    from orchestra.dispatcher import recorded_reasons, run
    from orchestra.submit import Assignment, submit

    config = load_orchestra_config(Path(__file__).resolve().parents[1])
    config = replace(config, runtime=replace(config.runtime, state_dir=tmp_path))
    with JobQueue(tmp_path / "queue.db") as queue:
        submission = submit(
            tmp_path, queue, config, "test:unexpected",
            [Assignment(goal="do the work", role="builder")],
        )
        job_id = submission.jobs[0].job_id
        harness = PiHarness(
            {job_id: _no_settle_plan(no_settle_script, "exit", 7)}, "budget!"
        )
        run(
            queue, tmp_path, harness, submission.run_id,
            global_limit=1, per_session_limit=1, payloads=submission.payloads,
        )
        assert queue.get_job(job_id).status == "failed"
        reason = recorded_reasons(tmp_path, submission.run_id)[job_id]
        assert reason.startswith("failed:")
        assert "without completing" in reason
        assert "7" in reason
        assert "terminated (hard timeout or cancellation)" not in reason


def test_orchestra_terminate_still_reports_termination_not_unexpected_exit(
    stub_script: Path, sessions_dir: Path
) -> None:
    """An Orchestra-requested terminate keeps the existing termination reason.

    Distinct from an unsolicited child exit: when the caller ends a live child
    via terminate (the timeout/cancellation path), the outcome stays terminated
    and the recorded reason stays the termination wording, never the new
    unexpected-exit cause.
    """
    from orchestra.dispatcher import _failure_reason

    harness = PiHarness({"j1": plan(stub_script, STUB_WAIT_STEER="1")}, "budget!")
    handle = harness.new_handle()
    results: list[Outcome] = []

    def worker() -> None:
        results.append(harness.execute(CommandJob("j1", ("prompt",)), Budgets(), handle))

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        _wait_process(handle)
        harness.terminate(handle)
        thread.join(timeout=10)
    finally:
        if thread.is_alive():
            harness.terminate(handle)
            thread.join(timeout=5)
    assert not thread.is_alive()
    outcome = results[0]
    assert outcome.terminated
    assert harness.note_for("j1").reason is None  # no unexpected-exit cause
    assert _failure_reason(outcome) == "failed: terminated (hard timeout or cancellation)"
