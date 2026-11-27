"""Core session runtime: fixed transport + one real evaluation/delivery path.

These are connected behavior tests over the real SQLite ``JobQueue`` and the
real ``Results``/reconcile modules. The runtime speaks the fixed JSON-line
protocol and drives one authoritative evaluation — snapshot, status, one
prepared report from Results, and native delivery acknowledged only after a real
native ``accepted`` result. No adapter bookkeeping, no LLM, no network.
"""

from __future__ import annotations

import io
import json
import shutil
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from orchestra import cli
from orchestra.artifacts import Response, append
from orchestra.queue import JobQueue
from orchestra.session import (
    TIMEOUT,
    ConnectionClosed,
    ProtocolError,
    SessionRuntime,
    decode_line,
    encode_line,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION = "pi:LIVE1"
REAL_PROMPTS: dict[str, str] = yaml.safe_load(
    (REPO_ROOT / "prompts.yaml").read_text(encoding="utf-8")
)


def _config_dir(tmp_path: Path) -> Path:
    d = tmp_path / "config"
    d.mkdir()
    shutil.copy(REPO_ROOT / "prompts.yaml", d / "prompts.yaml")
    (d / "config.yaml").write_text(
        f"state_dir: {tmp_path / 'state'}\nlog_dir: {tmp_path / 'logs'}\n"
        "default_timeout: 300\nsoft_timeout: 240\nturn_limit: 60\n"
        "concurrency:\n  global: 4\n  per_session: 2\n"
        "retention_days: 90\ndefault_mode: 'on'\n",
        encoding="utf-8",
    )
    (d / "harnesses.yaml").write_text(
        'pi:\n  harness: pi\n  command: ["pi"]\n', encoding="utf-8"
    )
    (d / "agent-catalog.yaml").write_text(
        "default_role: builder\nmodel_limits: {}\nroles:\n"
        "  builder:\n    enabled: manual\n    harness_config: pi\n"
        '    model: "m1"\n    env: {}\n    skills: []\n'
        "    dispatch_hint: Build.\n    auto_verify: false\n",
        encoding="utf-8",
    )
    (tmp_path / "state").mkdir()
    (tmp_path / "logs").mkdir()
    return d


class _RecordingSend:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def __call__(self, message: dict[str, Any]) -> None:
        self.sent.append(message)

    def by_kind(self, kind: str) -> list[dict[str, Any]]:
        return [m for m in self.sent if m.get("kind") == kind]


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _ListSource:
    """Frame source for tests: yields queued frames, a tick, or EOF."""

    def __init__(self, items: list[Any]) -> None:
        self.items = list(items)

    def poll(self, timeout: float | None) -> Any:
        if not self.items:
            return None
        head = self.items.pop(0)
        return TIMEOUT if head == "tick" else head


def _runtime(
    queue: JobQueue,
    tmp_path: Path,
    *,
    prompts: dict[str, str],
    send: _RecordingSend,
    clock: _FakeClock | None = None,
    session: str = SESSION,
) -> SessionRuntime:
    return SessionRuntime(
        queue=queue,
        parent_session=session,
        state_dir=tmp_path / "state",
        prompts=prompts,
        send=send,
        monotonic=clock or _FakeClock(),
    )


def _drain_run(
    queue: JobQueue, run_id: str, *, tmp_path: Path, parent: str = SESSION
) -> None:
    """Move every job of a run to a durable succeeded outcome with an artifact.

    The artifact is what lets the real Results module assemble a report from
    the terminal run — the evaluator must not be tested against a stub.
    """
    while True:
        job = queue.claim_next(global_limit=5, per_session_limit=5, run_id=run_id)
        if job is None:
            break
        append(
            tmp_path / "state",
            run_id,
            Response(
                job_id=job.job_id,
                timestamp=datetime.now(UTC).isoformat(),
                response=f"answer for {job.job_id}",
            ),
        )
        queue.complete_job(job.job_id, "succeeded")


def _seed_ready_run(
    queue: JobQueue,
    tmp_path: Path,
    run_id: str = "r1",
    *,
    parent: str = SESSION,
) -> None:
    queue.add_job(run_id=run_id, parent_session=parent, role="builder", model="m1")
    _drain_run(queue, run_id, tmp_path=tmp_path, parent=parent)


# --- protocol framing -----------------------------------------------------

def test_encode_line_is_single_json_frame() -> None:
    msg = {"kind": "status", "text": "Session jobs: 1 running."}
    line = encode_line(msg)
    assert line.count("\n") == 0
    assert json.loads(line) == msg


def test_decode_line_rejects_non_object_frames() -> None:
    with pytest.raises(ProtocolError):
        decode_line("[1, 2, 3]")
    with pytest.raises(ProtocolError):
        decode_line("not json")


# --- snapshot reads the real queue, never a parallel cache ----------------

def test_snapshot_request_reads_real_queue(tmp_path: Path) -> None:
    _config_dir(tmp_path)
    prompts = REAL_PROMPTS
    queue = JobQueue(tmp_path / "state" / "queue.db")
    queue.add_job(run_id="r1", parent_session=SESSION, role="builder", model="m1")
    queue.add_job(run_id="r1", parent_session=SESSION, role="builder", model="m1")
    queue.claim_next(global_limit=4, per_session_limit=2, dispatcher_token="t")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=prompts, send=send)

    reply = rt.handle(
        {"kind": "request", "id": "c1", "operation": "snapshot", "arguments": {}}
    )
    assert reply is not None

    assert reply["kind"] == "reply" and reply["id"] == "c1"
    snap = reply["result"]
    assert snap["parent_session"] == SESSION
    assert snap["counts"] == {"running": 1, "pending": 1, "terminal": 0}
    assert snap["active"] is True and snap["ready"] is False
    assert {j["run_id"] for j in snap["jobs"]} == {"r1"}
    queue.close()


# --- native identity binding (never from model/prompt args) ---------------

def test_foreign_identity_cannot_override_bound_owner(tmp_path: Path) -> None:
    _config_dir(tmp_path)
    prompts = REAL_PROMPTS
    queue = JobQueue(tmp_path / "state" / "queue.db")
    queue.add_job(run_id="mine", parent_session=SESSION, role="builder", model="m1")
    queue.add_job(run_id="steal", parent_session="pi:VICTIM", role="builder", model="m1")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=prompts, send=send)

    # A model-crafted request that tries to rebind the session is ignored: the
    # runtime reads ONLY the identity bound from native adapter args.
    reply = rt.handle(
        {
            "kind": "request",
            "id": "x",
            "operation": "snapshot",
            "arguments": {"parent_session": "pi:VICTIM"},
        }
    )
    assert reply is not None
    snap = reply["result"]
    assert snap["parent_session"] == SESSION
    assert {j["run_id"] for j in snap["jobs"]} == {"mine"}
    assert "steal" not in {j["run_id"] for j in snap["jobs"]}
    queue.close()


# --- unknown / malformed input never accepted as success ------------------

def test_unknown_operation_replies_error_not_success(tmp_path: Path) -> None:
    _config_dir(tmp_path)
    prompts = REAL_PROMPTS
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=prompts, send=send)

    reply = rt.handle(
        {"kind": "request", "id": "u", "operation": "totally-unknown", "arguments": {}}
    )
    assert reply is not None
    assert reply["kind"] == "reply" and reply["id"] == "u"
    assert "result" not in reply
    assert "not handled" in reply["error"]
    queue.close()


def test_dispatch_is_never_faked_as_success(tmp_path: Path) -> None:
    # dispatch is a real control operation now, but an unconfigured runtime must
    # report the real cause, never fake an accepted/successful submission.
    _config_dir(tmp_path)
    prompts = REAL_PROMPTS
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=prompts, send=send)

    reply = rt.handle(
        {"kind": "request", "id": "d", "operation": "dispatch", "arguments": {"goal": "x"}}
    )
    assert reply is not None
    assert "result" not in reply
    assert "not configured" in reply["error"]
    # A malformed dispatch is also a visible error, never a silent acceptance.
    assert rt.handle(
        {"kind": "request", "id": "e", "operation": "dispatch", "arguments": {"goal": "  "}}
    ) == {"kind": "reply", "id": "e", "error": "dispatch requires a non-empty goal"}
    queue.close()


def test_malformed_request_is_a_protocol_error(tmp_path: Path) -> None:
    _config_dir(tmp_path)
    prompts = REAL_PROMPTS
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=prompts, send=send)

    # A request with no id/operation violates the wire contract.
    with pytest.raises(ProtocolError):
        rt.handle({"kind": "request", "operation": "snapshot", "arguments": {}})
    # A request with a non-dict arguments is a malformed frame, not a valid read.
    with pytest.raises(ProtocolError):
        rt.handle({"kind": "request", "id": 1, "operation": "snapshot", "arguments": []})
    queue.close()


def test_unknown_kind_is_a_protocol_error(tmp_path: Path) -> None:
    _config_dir(tmp_path)
    prompts = REAL_PROMPTS
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=prompts, send=send)
    with pytest.raises(ProtocolError):
        rt.handle({"kind": "bogus", "id": 1})
    queue.close()


# --- report once after a real native receipt ------------------------------

def test_report_delivered_once_and_acknowledged_after_native_accept(
    tmp_path: Path,
) -> None:
    _config_dir(tmp_path)
    prompts = REAL_PROMPTS
    queue = JobQueue(tmp_path / "state" / "queue.db")
    # Open the runtime BEFORE the run is terminal so it is not baselined away.
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=prompts, send=send)
    _seed_ready_run(queue, tmp_path, "r1")

    rt.request_evaluation()

    requests = send.by_kind("native_request")
    assert len(requests) == 1, "exactly one delivery request for the ready run"
    req = requests[0]
    assert req["operation"] == "deliver_report"
    assert req["arguments"]["report"]["run_ids"] == ["r1"]
    # The delivery carries the core-produced final report text, not just a
    # structured record the host would have to reassemble.
    text = req["arguments"]["text"]
    assert isinstance(text, str) and text.strip()
    assert "r1" in text and "answer for r1:1" in text
    # Not acknowledged until a real native receipt.
    assert queue.snapshot(SESSION).reported_run_ids == ()

    # A second evaluation before any receipt must NOT duplicate the request.
    rt.request_evaluation()
    assert len(send.by_kind("native_request")) == 1

    # A real native acceptance acknowledges the report through the queue.
    rt.handle({"kind": "native_result", "id": req["id"], "accepted": True})
    assert queue.snapshot(SESSION).reported_run_ids == ("r1",)
    assert rt.prepared_report is None

    # A later evaluation sees the run already reported: no new delivery.
    rt.request_evaluation()
    assert len(send.by_kind("native_request")) == 1
    queue.close()


def test_native_rejection_does_not_acknowledge_or_retry(tmp_path: Path) -> None:
    _config_dir(tmp_path)
    prompts = REAL_PROMPTS
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=prompts, send=send)
    _seed_ready_run(queue, tmp_path, "r1")
    rt.request_evaluation()
    req = send.by_kind("native_request")[0]

    rt.handle({"kind": "native_result", "id": req["id"], "accepted": False})

    # Rejection never advances reported membership and triggers no silent retry.
    assert queue.snapshot(SESSION).reported_run_ids == ()
    rt.request_evaluation()
    assert len(send.by_kind("native_request")) == 1
    queue.close()


# --- availability and compaction defer/release ----------------------------

def test_compaction_defers_then_release_delivers(tmp_path: Path) -> None:
    _config_dir(tmp_path)
    prompts = REAL_PROMPTS
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=prompts, send=send)

    rt.handle({"kind": "host_event", "event": "compaction_start", "details": {}})
    _seed_ready_run(queue, tmp_path, "r1")
    rt.request_evaluation()

    # Prepared but deferred while compacting: no native delivery request yet.
    assert rt.prepared_report is not None
    assert send.by_kind("native_request") == []

    rt.handle({"kind": "host_event", "event": "compaction_end", "details": {}})
    requests = send.by_kind("native_request")
    assert len(requests) == 1
    queue.close()


def test_unavailable_session_defers_delivery(tmp_path: Path) -> None:
    _config_dir(tmp_path)
    prompts = REAL_PROMPTS
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=prompts, send=send)
    rt.handle({"kind": "host_event", "event": "unavailable", "details": {}})
    _seed_ready_run(queue, tmp_path, "r1")
    rt.request_evaluation()
    assert send.by_kind("native_request") == []
    queue.close()


# --- admission blocks readiness (no premature report) ---------------------

def test_open_admission_blocks_report(tmp_path: Path) -> None:
    _config_dir(tmp_path)
    prompts = REAL_PROMPTS
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=prompts, send=send)
    _seed_ready_run(queue, tmp_path, "r1")
    # An in-flight submission keeps the session not-ready even though all
    # durable jobs are terminal.
    queue.begin_submission(SESSION, "req-1")
    assert queue.snapshot(SESSION).ready is False

    rt.request_evaluation()
    assert send.by_kind("native_request") == []

    queue.finish_submission(SESSION, "req-1")
    rt.request_evaluation()
    assert len(send.by_kind("native_request")) == 1
    queue.close()


# --- periodic backstop runs the SAME evaluator (controlled time) ----------

def test_periodic_tick_runs_same_evaluator_for_missing_event(tmp_path: Path) -> None:
    _config_dir(tmp_path)
    prompts = REAL_PROMPTS
    queue = JobQueue(tmp_path / "state" / "queue.db")
    clock = _FakeClock()
    send = _RecordingSend()
    queue.add_job(run_id="r1", parent_session=SESSION, role="builder", model="m1")
    queue.claim_next(global_limit=4, per_session_limit=2, dispatcher_token="t")
    rt = _runtime(queue, tmp_path, prompts=prompts, send=send, clock=clock)

    # First evaluation sees a running job: arms the active-work timer, no report.
    rt.request_evaluation()
    assert send.by_kind("native_request") == []
    assert rt.time_until_due() is not None

    # A completion event never arrives. Drain the run directly (no evaluator).
    append(
        tmp_path / "state",
        "r1",
        Response(
            job_id="r1:1",
            timestamp=datetime.now(UTC).isoformat(),
            response="late answer",
        ),
    )
    running = queue.list_jobs("r1")[0]
    queue.complete_job(running.job_id, "succeeded")

    # The timer fires within the backstop interval and invokes the SAME
    # evaluator, which now finds the run ready and requests delivery.
    clock.advance(9.0)
    due = rt.time_until_due()
    assert due is not None and due > 0
    assert send.by_kind("native_request") == []
    clock.advance(2.0)
    assert rt.time_until_due() == 0.0
    rt.on_tick()
    assert len(send.by_kind("native_request")) == 1
    queue.close()


def test_timer_disarms_when_no_work_outstanding(tmp_path: Path) -> None:
    _config_dir(tmp_path)
    prompts = REAL_PROMPTS
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=prompts, send=send)
    # Idle session (no jobs): no active work, so no backstop is armed.
    rt.request_evaluation()
    assert rt.time_until_due() is None
    queue.close()


# --- serve loop: accepts frames and ticks while idle, handles native_result -

def test_serve_handles_requests_events_and_ticks(tmp_path: Path) -> None:
    _config_dir(tmp_path)
    prompts = REAL_PROMPTS
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=prompts, send=send)
    _seed_ready_run(queue, tmp_path, "r1")

    frames = [
        encode_line(
            {"kind": "host_event", "event": "available", "details": {}}
        ),
        encode_line(
            {"kind": "request", "id": "c1", "operation": "snapshot", "arguments": {}}
        ),
        "tick",
    ]
    rt.serve(_ListSource(frames))

    assert rt.closed is True
    replies = send.by_kind("reply")
    assert any(r.get("id") == "c1" and "result" in r for r in replies)
    # The tick evaluation delivered the ready run.
    assert len(send.by_kind("native_request")) == 1


def test_serve_reports_protocol_error_without_crash(tmp_path: Path) -> None:
    _config_dir(tmp_path)
    prompts = REAL_PROMPTS
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=prompts, send=send)

    rt.serve(_ListSource(["not json", "42"]))

    errors = [r for r in send.by_kind("reply") if "error" in r]
    assert len(errors) == 2
    assert all("protocol error" in r["error"] for r in errors)


def test_connection_closed_after_stream_ends(tmp_path: Path) -> None:
    _config_dir(tmp_path)
    prompts = REAL_PROMPTS
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=prompts, send=send)
    rt.serve(_ListSource([]))
    assert rt.closed is True
    with pytest.raises(ConnectionClosed):
        rt.handle({"kind": "request", "id": 1, "operation": "snapshot", "arguments": {}})
    queue.close()


# --- package transport entry: internal __session over real stdio ----------

def test_session_transport_entry_serves_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _config_dir(tmp_path)
    monkeypatch.setenv("ORCHESTRA_CONFIG", str(tmp_path / "config"))
    queue = JobQueue(tmp_path / "state" / "queue.db")
    queue.add_job(run_id="r1", parent_session=SESSION, role="builder", model="m1")
    queue.close()

    frame = encode_line(
        {"kind": "request", "id": "c1", "operation": "snapshot", "arguments": {}}
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(frame + "\n"))

    assert cli.main(["__session", "--parent-session", SESSION]) == 0

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    # The opening evaluation emits a status frame before the reply arrives.
    reply = next(json.loads(line) for line in lines if json.loads(line).get("id") == "c1")
    assert reply["kind"] == "reply"
    assert reply["result"]["parent_session"] == SESSION
    assert reply["result"]["counts"]["pending"] == 1


# --- control operations: real replies and honest error relay --------------

def test_control_mode_valid_and_invalid(tmp_path: Path) -> None:
    _config_dir(tmp_path)
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=REAL_PROMPTS, send=send)

    ok = rt.handle(
        {"kind": "request", "id": "m1", "operation": "mode", "arguments": {"mode": "off"}}
    )
    assert ok is not None and ok["result"]["mode"] == "off"

    bad = rt.handle(
        {"kind": "request", "id": "m2", "operation": "mode", "arguments": {"mode": "maybe"}}
    )
    assert bad is not None and "result" not in bad
    assert "mode must be" in bad["error"]
    queue.close()


def test_control_errors_relay_actual_cause(tmp_path: Path) -> None:
    _config_dir(tmp_path)
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=REAL_PROMPTS, send=send)

    # stop without a run_id, roles/doctor without a config, history with a
    # non-integer limit: each surfaces the real core cause, never a fake success.
    stop = rt.handle({"kind": "request", "id": "s", "operation": "stop", "arguments": {}})
    assert stop is not None and "runId" in stop["error"]
    roles = rt.handle({"kind": "request", "id": "r", "operation": "roles", "arguments": {}})
    assert roles is not None and "no configuration" in roles["error"]
    hist = rt.handle(
        {"kind": "request", "id": "h", "operation": "history", "arguments": {"limit": "10"}}
    )
    assert hist is not None and "integer" in hist["error"]
    queue.close()


def test_control_stop_accepts_run_id_wire_argument(tmp_path: Path) -> None:
    # The frozen stop wire argument is ``runId``; an owned, already-terminal run
    # returns immediately (no bounded wait) proving the argument is read.
    _config_dir(tmp_path)
    queue = JobQueue(tmp_path / "state" / "queue.db")
    _seed_ready_run(queue, tmp_path, "r1")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=REAL_PROMPTS, send=send)

    reply = rt.handle(
        {"kind": "request", "id": "s", "operation": "stop", "arguments": {"runId": "r1"}}
    )
    assert reply is not None and reply["result"]["run_id"] == "r1"
    assert reply["result"]["already_finished"] is True
    queue.close()


def test_control_help_is_core_owned_text(tmp_path: Path) -> None:
    _config_dir(tmp_path)
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=REAL_PROMPTS, send=send)
    help_reply = rt.handle(
        {"kind": "request", "id": "hp", "operation": "help", "arguments": {}}
    )
    assert help_reply is not None
    assert "Orchestra" in help_reply["result"]["text"]
    queue.close()


# --- native parent-context capture: resolve/pop by matching pending id ------

def test_native_context_capture_resolves_on_accepted(tmp_path: Path) -> None:
    _config_dir(tmp_path)
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=REAL_PROMPTS, send=send)

    event = threading.Event()
    holder: dict[str, Any] = {"event": event, "text": None}
    rt._pending_context["context-1"] = holder

    rt.handle(
        {"kind": "native_result", "id": "context-1", "accepted": True, "data": {"text": "CTX"}}
    )

    assert event.is_set(), "the waiting admission is woken"
    assert holder["text"] == "CTX", "data.text is resolved into the capture"
    assert "context-1" not in rt._pending_context, "the pending holder is popped"
    queue.close()


def test_native_context_capture_rejection_leaves_text_unset(tmp_path: Path) -> None:
    _config_dir(tmp_path)
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=REAL_PROMPTS, send=send)

    event = threading.Event()
    holder: dict[str, Any] = {"event": event, "text": None}
    rt._pending_context["context-9"] = holder

    # A rejection (or an accepted result with malformed data) never fabricates a
    # capture; the waiter is woken with text left unset so Submit fails loudly.
    rt.handle({"kind": "native_result", "id": "context-9", "accepted": False})

    assert event.is_set()
    assert holder["text"] is None
    assert "context-9" not in rt._pending_context
    queue.close()


def test_native_context_concurrent_admissions_serialize_under_eval_lock(
    tmp_path: Path,
) -> None:
    """Two concurrent _request_native_context calls serialize under _eval_lock.

    Proves: (1) ID allocation and holder registration are atomic (no interleaved
    _ctx_seq race), (2) the lock is released BEFORE emit/Event.wait so the native
    event loop can resolve both without deadlock, (3) both threads receive their
    correct distinct text without timeout. Failure-safe thread cleanup: if the
    test fails, threads are joined and the runtime closed.
    """
    _config_dir(tmp_path)
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=REAL_PROMPTS, send=send)

    results: list[str] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def _admit() -> None:
        try:
            barrier.wait(timeout=5)
            text = rt._request_native_context()
            results.append(text)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    # Hold the eval lock so neither thread can complete registration.
    acquired = rt._eval_lock.acquire()
    assert acquired

    threads = [threading.Thread(target=_admit, daemon=True) for _ in range(2)]
    for t in threads:
        t.start()

    # Both threads block on the lock (barrier releases them but they cannot
    # acquire _eval_lock). Give them time to attempt and park.
    time.sleep(0.1)
    # No native_request emitted yet (registration is blocked).
    assert send.by_kind("native_request") == []

    # Release the lock: one thread proceeds, registers, emits, releases;
    # then the other registers and emits.
    rt._eval_lock.release()

    # Give the threads time to emit their native_request frames.
    time.sleep(0.1)

    try:
        native_reqs = send.by_kind("native_request")
        assert len(native_reqs) == 2, f"expected 2 native_request frames, got {len(native_reqs)}"

        ids = [r["id"] for r in native_reqs]
        assert len(set(ids)) == 2, f"IDs must be unique, got {ids}"

        # Resolve each native_result with distinct text (on main thread,
        # simulating the native loop delivering results).
        text_by_id = {ids[0]: "CONTEXT_A", ids[1]: "CONTEXT_B"}
        for req_id, text in text_by_id.items():
            rt.handle(
                {"kind": "native_result", "id": req_id, "accepted": True, "data": {"text": text}}
            )

        for t in threads:
            t.join(timeout=5)
        assert not any(t.is_alive() for t in threads), "threads must finish after resolution"

        assert errors == [], f"unexpected errors: {errors}"
        assert sorted(results) == ["CONTEXT_A", "CONTEXT_B"], (
            f"each thread must receive exactly its own resolved text, got {results}"
        )
    finally:
        rt.close()
        queue.close()


# --- dispatch argument contract: single canonical taskLabel + real errors ---

def test_dispatch_argument_types_are_validated_loudly(tmp_path: Path) -> None:
    _config_dir(tmp_path)
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=REAL_PROMPTS, send=send)

    bad_label = rt.handle(
        {"kind": "request", "id": "1", "operation": "dispatch",
         "arguments": {"goal": "x", "taskLabel": 5}}
    )
    assert bad_label is not None and "taskLabel must be a string" in bad_label["error"]

    bad_ctx = rt.handle(
        {"kind": "request", "id": "2", "operation": "dispatch",
         "arguments": {"goal": "x", "additionalContext": []}}
    )
    assert bad_ctx is not None and "additionalContext must be a string" in bad_ctx["error"]
    queue.close()


def test_dispatch_ack_preserves_literal_task_label(tmp_path: Path) -> None:
    _config_dir(tmp_path)
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=REAL_PROMPTS, send=send)
    submission = SimpleNamespace(run_id="run-abc", jobs=[])

    labelled = rt._dispatch_ack(submission, "Ship it")
    assert labelled["task_label"] == "Ship it"
    assert "Task label: Ship it" in labelled["text"]

    # An empty supplied label is preserved literally in the data, but a blank
    # label line is not added to the human-readable acknowledgement text.
    empty = rt._dispatch_ack(submission, "")
    assert empty["task_label"] == ""
    assert "Task label:" not in empty["text"]

    # Only an absent label (None) omits the field entirely.
    absent = rt._dispatch_ack(submission, None)
    assert "task_label" not in absent
    queue.close()


def test_dispatch_ack_text_carries_run_role_job_identifiers(tmp_path: Path) -> None:
    """The native translator can send .text verbatim: it names the real run id,
    resolved role, and job ids, so no semantic assembly happens host-side."""
    _config_dir(tmp_path)
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=REAL_PROMPTS, send=send)
    job = SimpleNamespace(job_id="run-xyz:0", sequence=0, role="builder")
    submission = SimpleNamespace(run_id="run-xyz", jobs=[job])

    ack = rt._dispatch_ack(submission, None)
    text = ack["text"]
    assert "run-xyz" in text, "real run id is visible in the acknowledgement text"
    assert "builder" in text, "resolved role is visible in the acknowledgement text"
    assert "run-xyz:0" in text, "real job id is visible in the acknowledgement text"
    queue.close()


def test_status_push_is_running_only_meter(tmp_path: Path) -> None:
    """The live status push is the compact running-only role meter, never the
    verbose detailed status and never pending roles."""
    _config_dir(tmp_path)
    queue = JobQueue(tmp_path / "state" / "queue.db")
    queue.add_job(run_id="r1", parent_session=SESSION, role="builder", model="m1")
    queue.add_job(run_id="r1", parent_session=SESSION, role="verifier", model="m1")
    queue.claim_next(global_limit=4, per_session_limit=2, dispatcher_token="t")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=REAL_PROMPTS, send=send)

    rt.evaluate()
    frames = send.by_kind("status")
    assert frames, "evaluation emits a status push"
    text = frames[-1]["text"]
    assert text == "Orchestra: running builder×1"
    assert "verifier" not in text, "pending roles are excluded from the meter"
    assert "This session" not in text, "the verbose detailed status is not the widget"
    queue.close()


# --- status frame native transport fields ----------------------------------


def _config_runtime(
    queue: JobQueue,
    tmp_path: Path,
    *,
    send: _RecordingSend,
    session: str = SESSION,
) -> SessionRuntime:
    """A runtime carrying real config so the native transport fields resolve."""
    from orchestra.config import load_orchestra_config

    config = load_orchestra_config(tmp_path / "config")
    return SessionRuntime(
        queue=queue,
        parent_session=session,
        state_dir=config.runtime.state_dir,
        prompts=config.prompts,
        send=send,
        monotonic=_FakeClock(),
        config=config,
    )


def test_status_frame_carries_native_ids_and_mode_text(tmp_path: Path) -> None:
    """The status frame adds native_session_ids (Pi worker session ids from the
    SAME launcher helper) and a core-formatted mode_text, and the running meter
    text is unchanged."""
    from orchestra.pi_harness import worker_session_id

    _config_dir(tmp_path)
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _config_runtime(queue, tmp_path, send=send)
    # A new owned job (added AFTER open) is not attachment baseline and its
    # role's configured harness is pi.
    job = queue.add_job(run_id="r1", parent_session=SESSION, role="builder", model="m1")

    rt.evaluate()
    frame = send.by_kind("status")[-1]
    # text running meter is unchanged (pending job -> no running meter).
    assert frame["text"] == "Orchestra: no running jobs"
    # The native handle is exactly the shared launcher helper's value, not a
    # locally re-derived string prefix.
    assert frame["native_session_ids"] == [worker_session_id(job.job_id)]
    assert worker_session_id(job.job_id) == "orchestra-worker-r1-1"
    assert frame["mode_text"] == "(Orchestra: on)"
    rt.close()
    queue.close()


def test_status_frame_excludes_attachment_baseline(tmp_path: Path) -> None:
    """A run already terminal when the session opened is baseline and is never
    surfaced as a native handle."""
    _config_dir(tmp_path)
    queue = JobQueue(tmp_path / "state" / "queue.db")
    job = queue.add_job(run_id="old", parent_session=SESSION, role="builder", model="m1")
    running = queue.claim_next(global_limit=4, per_session_limit=2, run_id="old")
    assert running is not None
    queue.complete_job(job.job_id, "succeeded")
    send = _RecordingSend()
    # open_session baselines the terminal run 'old' before the runtime starts.
    rt = _config_runtime(queue, tmp_path, send=send)

    rt.evaluate()
    frame = send.by_kind("status")[-1]
    assert frame["native_session_ids"] == [], "baseline run is not re-surfaced"
    rt.close()
    queue.close()


def test_status_frame_native_ids_empty_without_config(tmp_path: Path) -> None:
    """An injected no-config runtime has no harness mapping and emits an empty
    native list, while still carrying a mode_text."""
    _config_dir(tmp_path)
    queue = JobQueue(tmp_path / "state" / "queue.db")
    queue.add_job(run_id="r1", parent_session=SESSION, role="builder", model="m1")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=REAL_PROMPTS, send=send)  # no config

    rt.evaluate()
    frame = send.by_kind("status")[-1]
    assert frame["native_session_ids"] == []
    assert frame["mode_text"] == "(Orchestra: on)"
    rt.close()
    queue.close()


def test_mode_control_reemits_status_with_updated_mode_text(tmp_path: Path) -> None:
    """A mode change wakes the SAME evaluator so a new status frame carries the
    updated core-formatted mode_text (no separate render path)."""
    _config_dir(tmp_path)
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _config_runtime(queue, tmp_path, send=send)
    before = len(send.by_kind("status"))

    reply = rt.handle(
        {"kind": "request", "id": "m1", "operation": "mode", "arguments": {"mode": "off"}}
    )
    assert reply is not None and reply["result"]["mode"] == "off"

    frames = send.by_kind("status")
    assert len(frames) > before, "mode change must emit a fresh status frame"
    assert frames[-1]["mode_text"] == "(Orchestra: off)"
    rt.close()
    queue.close()


# --- single core synchronization: report state guarded by one lock ---------


def test_delivery_ack_serialized_behind_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A native delivery receipt must not touch report state while the evaluator
    is inside its prepared-state section: both share the ONE evaluation lock,
    not an independent tracker. Proven deterministically by holding the lock in
    the evaluator (a blocked delivery request) and observing the receipt
    thread cannot enter its critical section until the lock is released — not a
    timing guess (the receipt is asserted to remain blocked, then to proceed).
    """
    _config_dir(tmp_path)
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=REAL_PROMPTS, send=send)
    _seed_ready_run(queue, tmp_path, "r1")

    gate = threading.Event()
    release = threading.Event()
    original = rt._request_delivery

    def held_delivery() -> None:
        # Called inside the evaluator's report-state critical section.
        gate.set()
        assert release.wait(5.0), "test released the held lock"
        original()

    monkeypatch.setattr(rt, "_request_delivery", held_delivery)

    evaluator = threading.Thread(target=rt.request_evaluation, daemon=True)
    evaluator.start()
    assert gate.wait(5.0), "evaluator reached the delivery step under the lock"

    entered = threading.Event()
    finished = threading.Event()

    def receipt() -> None:
        entered.set()
        rt.handle({"kind": "native_result", "id": "deliver-999", "accepted": True})
        finished.set()

    handler = threading.Thread(target=receipt, daemon=True)
    handler.start()
    assert entered.wait(5.0)
    # The receipt cannot complete while the evaluator holds the shared lock.
    assert not finished.wait(0.25), "delivery receipt blocked behind evaluation"

    release.set()
    handler.join(5.0)
    evaluator.join(5.0)
    assert finished.is_set() and not evaluator.is_alive()
    # The exact in-flight delivery id, not a fabricated one, was requested once.
    assert len(send.by_kind("native_request")) == 1
    queue.close()


def test_concurrent_receipt_and_new_admission_yields_single_report(
    tmp_path: Path,
) -> None:
    """Controlled overlap: the single delivery receipt for a ready run races a
    newly opened admission and a follow-up evaluation. The durable end state is
    asserted, not a timing: exactly one delivery request, r1 acknowledged once
    (exactly-once reported membership), and the prepared report cleared. With
    the shared lock, a follow-up evaluation cannot observe a half-cleared
    prepared report and re-deliver the same run.
    """
    _config_dir(tmp_path)
    for _iteration in range(5):
        queue = JobQueue(tmp_path / f"state{_iteration}" / "queue.db")
        send = _RecordingSend()
        rt = _runtime(queue, tmp_path / f"state{_iteration}", prompts=REAL_PROMPTS, send=send)
        _seed_ready_run(queue, tmp_path / f"state{_iteration}", "r1")
        rt.request_evaluation()
        req = send.by_kind("native_request")[0]

        barrier = threading.Barrier(2)

        def receipt(
            wait_at: threading.Barrier = barrier,
            runtime: SessionRuntime = rt,
            delivery_id: object = req["id"],
        ) -> None:
            wait_at.wait(5.0)
            runtime.handle({"kind": "native_result", "id": delivery_id, "accepted": True})

        def admission_and_eval(
            wait_at: threading.Barrier = barrier,
            runtime: SessionRuntime = rt,
            job_queue: JobQueue = queue,
        ) -> None:
            wait_at.wait(5.0)
            job_queue.begin_submission(SESSION, "req-new")
            runtime.request_evaluation()
            job_queue.finish_submission(SESSION, "req-new")
            runtime.request_evaluation()

        threads = [
            threading.Thread(target=receipt, daemon=True),
            threading.Thread(target=admission_and_eval, daemon=True),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5.0)

        assert all(not t.is_alive() for t in threads), "no thread deadlocked"
        # The single ready run is acknowledged once and never re-delivered.
        assert send.by_kind("native_request") and len(send.by_kind("native_request")) == 1
        assert queue.snapshot(SESSION).reported_run_ids == ("r1",)
        assert rt.prepared_report is None
        queue.close()


def test_snapshot_and_ack_cannot_reprepare_acknowledged_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A native ack landing between evaluate()'s snapshot and its prepared-state
    decision must not let a stale 'ready' snapshot re-prepare a run the receipt
    already acknowledged/cleared (duplicate report).

    Deterministic: the snapshot read for the SECOND evaluate pass acknowledges
    the in-flight report from a SEPARATE thread. With the coherent snapshot+report
    lock, the ack cannot mutate report state inside that window, so the stale
    ready snapshot never re-prepares the acknowledged run. Without the shared
    snapshot/decision lock the ack interleaves (prepared cleared, membership
    advanced) while the stale snapshot still lists the run ready -> a second
    deliver_report frame (asserted NOT to happen).
    """
    _config_dir(tmp_path)
    queue = JobQueue(tmp_path / "state" / "queue.db")
    send = _RecordingSend()
    rt = _runtime(queue, tmp_path, prompts=REAL_PROMPTS, send=send)
    _seed_ready_run(queue, tmp_path, "r1")

    # Pass 1: the shared evaluator prepares r1 and requests its single delivery.
    rt.request_evaluation()
    delivery_id = send.by_kind("native_request")[0]["id"]

    orig_snapshot = queue.snapshot
    state: dict[str, Any] = {"calls": 0, "fired": False, "thread": None}

    def wrapped_snapshot(parent: str) -> Any:
        snap = orig_snapshot(parent)
        state["calls"] += 1
        if state["calls"] >= 2 and not state["fired"]:
            state["fired"] = True
            # Acknowledge the in-flight report from another thread exactly while
            # the evaluator is between its snapshot and its prepared decision.
            # In the fixed code this thread is blocked behind the evaluator lock
            # for the whole snapshot->decision window, so the ack cannot mutate
            # report state half-way through the snapshot decision.
            def _ack() -> None:
                rt.handle(
                    {"kind": "native_result", "id": delivery_id, "accepted": True}
                )

            ack_thread = threading.Thread(target=_ack, daemon=True)
            ack_thread.start()
            state["thread"] = ack_thread
            # Bounded window for a racing ack to land: in the fixed path it stays
            # blocked until the evaluator releases; in the buggy path it lands now
            # (clearing the prepared report before the decision).
            time.sleep(0.3)
        return snap

    monkeypatch.setattr(queue, "snapshot", wrapped_snapshot)

    # Pass 2: wake the evaluator again so its snapshot races the acknowledgement.
    rt.request_evaluation()
    # Evaluation returned (lock released); let the blocked ack complete and any
    # follow-up evaluation run to a quiesced durable end state.
    if state["thread"] is not None:
        state["thread"].join(3.0)
        assert not state["thread"].is_alive(), "acknowledgement must not deadlock"
    rt.request_evaluation()

    deliveries = [
        m
        for m in send.by_kind("native_request")
        if m.get("operation") == "deliver_report"
    ]
    assert len(deliveries) == 1, (
        "an acknowledged run must never be re-prepared/re-delivered; "
        f"got {len(deliveries)} deliveries"
    )
    assert queue.snapshot(SESSION).reported_run_ids == ("r1",)
    assert rt.prepared_report is None
    queue.close()
