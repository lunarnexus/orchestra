"""Tests for the Pi RPC harness plugin: real stub pi subprocess, no mocks.

The stub script speaks the Pi RPC protocol over stdin/stdout: it answers
``prompt`` events, emits assistant turns, honors a ``steer`` (wrap-up),
answers ``get_last_assistant_text``, settles, and writes a native session
transcript file so transcript lookup runs for real.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from orchestra.harness import Budgets, CommandJob, HarnessError
from orchestra.pi_harness import BUDGET_SOFT_REASON, BUDGET_TURN_REASON, AgentPlan, PiHarness

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
        _record_notes(config, submission, harness)
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
