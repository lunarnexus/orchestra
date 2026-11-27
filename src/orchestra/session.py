"""Core session runtime for one attached native (Pi) session.

One ``SessionRuntime`` is bound to one runtime session. It speaks newline-framed
JSON over a stdio pair using the fixed message kinds of the transport contract
and is the core runtime for the attached session — not a user-facing CLI,
global daemon, socket service, or replacement job queue.

Responsibilities held here (all decisions about Orchestra state live in core,
not the adapter):

* Run exactly one evaluation path. Every relevant event — a host event, a
  native result, or the periodic backstop — wakes the same ``evaluate`` pass:
  reconcile confirmed-dead dispatchers within the existing safe scope, read the
  authoritative queue ``snapshot``, render status, assemble at most one prepared
  session report from ``Results`` when the snapshot is ready, and request native
  delivery when the native session is available.
* Coalesce bursts: at most one evaluation runs with one queued follow-up.
* Run a single active-work timer while work is outstanding and stop it when no
  work is outstanding or the connection closes. It invokes the same ``evaluate``;
  it never wakes the model and never retries a report on its own.
* Track native availability and compaction. A report is prepared in core and
  delivered only while the native session is available; compaction defers it.
* Acknowledge a report through the queue only after a real native ``accepted``
  result — native acceptance means the host queued the report, not that the
  model consumed it.

Security invariants:

* The owning parent session is bound once from native adapter arguments when the
  runtime is created and is never accepted from request/model/prompt arguments.
  A request carrying its own ``parent_session`` cannot rebind it or read another
  session's state.
* Snapshot/status reads never claim, complete, reconcile, or acknowledge a job;
  reconciliation and acknowledgement only run on a real dead-dispatcher loss or a
  real native receipt.

Closing the connection stops only this observation loop and its timer. It never
touches independently-launched execution, which keeps its own process group and
outlives this connection.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path
from typing import Any

from orchestra import reconcile, results
from orchestra.config import OrchestraConfig
from orchestra.queue import JobQueue
from orchestra.status import render_running_meter, render_status
from orchestra.status import status as status_query
from orchestra.submit import SubmitError

# Fixed transport message kinds (the contract; not extensible here).
KIND_REQUEST = "request"
KIND_HOST_EVENT = "host_event"
KIND_NATIVE_RESULT = "native_result"
KIND_REPLY = "reply"
KIND_STATUS = "status"
KIND_NATIVE_REQUEST = "native_request"

# The single active-work backstop interval (seconds). Only while work is
# outstanding; catches events that never arrived by calling the same evaluator.
ACTIVE_WORK_INTERVAL = 10.0

# Operations the core session runtime answers directly from the authoritative
# queue snapshot. Read operations never mutate state; control operations reuse
# the existing core operations (cli helpers / queue API) without copying an
# action catalog. Execution (dispatch) launches independent workers.
READ_OPERATIONS = frozenset({"snapshot", "status"})
CONTROL_OPERATIONS = frozenset(
    {"dispatch", "history", "stop", "roles", "help", "doctor", "initial-mode", "mode"}
)

# Native context capture: the operation name the runtime asks the host to
# perform, and how long an admission thread waits for the blocking native
# result before failing the submission loudly (never a fake capture).
NATIVE_CONTEXT_OPERATION = "get_parent_context"
NATIVE_CONTEXT_TIMEOUT = 120.0

# How long ``close`` waits for the connection's OWN admission threads to stop
# touching the queue before giving up (bounded teardown; never waits on the
# independent execution those threads launched, which is never joined).
ADMISSION_JOIN_TIMEOUT = 10.0


class ConnectionClosed(RuntimeError):
    """Raised when an operation is attempted on a runtime whose stream ended."""


class ProtocolError(ValueError):
    """A frame violated the fixed wire contract (bad shape or unknown kind)."""


def encode_line(message: Mapping[str, Any]) -> str:
    """Serialize one message to a single newline-free JSON frame."""
    text = json.dumps(message, separators=(",", ":"))
    if "\n" in text or "\r" in text:
        # json never emits raw newlines, but guard the framing contract anyway.
        raise ValueError("frame must not contain newline characters")
    return text


def decode_line(line: str) -> dict[str, Any]:
    """Parse one JSON frame into an object; reject non-object frames."""
    try:
        obj = json.loads(line)
    except json.JSONDecodeError as exc:  # pragma: no cover - passthrough detail
        raise ProtocolError(f"frame is not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        # Transport frame shape is external input; a non-object frame is a
        # malformed value on the wire, not a caller type error.
        raise ProtocolError("frame must be a JSON object")
    return obj


# Returned by a frame source's ``poll`` when no input arrived before its
# timeout (the timer is due). ``None`` from poll means the stream reached EOF.
class _Timeout:
    """Sentinel: ``poll`` timed out with no input; the loop should run the tick."""


TIMEOUT = _Timeout()


class _StdinSource:
    """Production frame source: byte-buffered, burst-safe line reader.

    Two JSON frames can arrive in a single OS write. A selector watching the
    fd only fires once for that write, so a naive ``selector + readline``
    reads the first line and then blocks until the *next* write — silently
    losing the already-buffered second frame until unrelated traffic arrives.
    To never drop a buffered frame or add a per-message sleep, this source
    reads raw bytes with ``os.read`` into its own buffer and hands back one
    complete newline-framed line per ``poll`` call; buffered frames are
    returned immediately without touching the selector again.
    """

    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self._buf = b""
        self._eof = False
        self._fd: int | None = None
        self._readline = getattr(stream, "readline", None)
        fileno = getattr(stream, "fileno", None)
        if fileno is not None:
            try:
                self._fd = fileno()
            except (OSError, ValueError):
                self._fd = None

    def _take_line(self) -> str | None:
        """Pop one complete buffered line (without its newline), or None."""
        index = self._buf.find(b"\n")
        if index < 0:
            return None
        raw, self._buf = self._buf[:index], self._buf[index + 1 :]
        return raw.decode("utf-8", errors="replace")

    def poll(self, timeout: float | None) -> str | None | _Timeout:
        """Return the next raw line, ``TIMEOUT`` on no-input, or None at EOF.

        ``timeout=None`` blocks until a complete frame or EOF. A finite timeout
        lets the loop wake for the periodic backstop without a thread. A frame
        already in the buffer is returned immediately (no selector wait).
        """
        if self._fd is None:
            # Non-seekable test double (e.g. StringIO): readline is already
            # frame-complete, so no raw buffering is needed.
            line = self._readline() if self._readline is not None else ""
            return line if line else None
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            line = self._take_line()
            if line is not None:
                return line
            if self._eof:
                return None
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return TIMEOUT
            # Poll the fd for readability with the remaining budget.
            try:
                ready = _readable(self._fd, remaining)
            except OSError:
                self._eof = True
                continue
            if not ready:
                return None if deadline is None else TIMEOUT
            try:
                chunk = os.read(self._fd, 65536)
            except OSError:
                self._eof = True
                continue
            if not chunk:
                self._eof = True
                continue
            self._buf += chunk

    def close(self) -> None:
        return None


def _readable(fd: int, timeout: float | None) -> bool:
    """True when ``fd`` is readable within ``timeout`` (None blocks)."""
    readable, _, _ = select.select([fd], [], [], timeout)
    return bool(readable)


class SessionRuntime:
    """One core session runtime bound to a single native runtime session.

    ``parent_session`` must come from native adapter arguments (the identity the
    host adapter captured at native ``session_start``), never from model output
    or request arguments.
    """

    def __init__(
        self,
        *,
        queue: JobQueue,
        parent_session: str,
        state_dir: Path | str,
        prompts: Mapping[str, str],
        send: Callable[[dict[str, Any]], None],
        mode: str = "on",
        monotonic: Callable[[], float] = time.monotonic,
        interval: float = ACTIVE_WORK_INTERVAL,
        config: OrchestraConfig | None = None,
    ) -> None:
        if not parent_session:
            raise ValueError("parent_session must be bound from native adapter args")
        self._queue = queue
        self._parent_session = parent_session
        self._state_dir = Path(state_dir)
        self._prompts = prompts
        self._send_fn = send
        self._mode = mode
        self._monotonic = monotonic
        self._interval = interval
        self._config = config
        self._closed = False

        # Serializes every outbound frame: the serve loop and any dispatch
        # admission thread share one connection stdout, so no two frames interleave.
        self._send_lock = threading.Lock()

        # Serializes evaluation state transitions: the serve loop, any dispatch
        # admission thread, and any worker-observer thread wake the same
        # evaluator. The lock guards the coherent snapshot -> prepared/report ->
        # delivery decision region as well as _evaluating/_followup, so at most
        # one thread runs evaluate() and a concurrent native receipt cannot mutate
        # report state half-way through the snapshot decision (no duplicate
        # re-prepare of an acknowledged run).
        self._eval_lock = threading.RLock()

        # In-flight native parent-context captures (admission threads waiting
        # off the event loop for a blocking native result), keyed by request id.
        self._pending_context: dict[Any, dict[str, Any]] = {}
        self._ctx_seq = 0
        # References to launched execution workers so they are never GC'd while
        # running; workers outlive this connection (each in its own process group).
        self._workers: list[subprocess.Popen[bytes]] = []
        # The connection's OWN admission threads (Submit + launch + ack + one
        # evaluation). ``close`` joins these so none touches the queue after
        # close returns. Tracked separately from observer threads because an
        # observer's lifetime is tied to independent execution, which ``close``
        # must never wait on or kill.
        self._admission_threads: list[threading.Thread] = []
        # Worker-observer threads: they reap an independent execution process
        # (``proc.wait``) so joining them would wait on execution. ``close``
        # leaves them alone; their post-exit wake is guarded by ``_closed``.
        self._observer_threads: list[threading.Thread] = []

        # Availability of the native session for delivery, plus compaction state.
        self._native_available = True
        self._compacting = False

        # At most one prepared report awaiting native delivery.
        self._prepared: dict[str, Any] | None = None
        self._delivery_request_id: str | None = None
        self._delivery_failed = False

        # Evaluation coalescing and the single active-work timer.
        self._evaluating = False
        self._followup = False
        self._next_due: float | None = None
        self._native_seq = 0

        # Bind the queue-owned session state (idempotent terminal baseline).
        self._queue.open_session(self._parent_session)

    # -- identity ----------------------------------------------------------

    @property
    def parent_session(self) -> str:
        return self._parent_session

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def native_available(self) -> bool:
        return self._native_available and not self._compacting

    @property
    def prepared_report(self) -> dict[str, Any] | None:
        """The single report prepared but not yet natively acknowledged (if any)."""
        return self._prepared

    # -- outbound framing --------------------------------------------------

    def _emit(self, message: dict[str, Any]) -> None:
        """Send one frame, serialized against every other outbound frame.

        The serve loop and dispatch admission threads share one connection
        stdout; the lock keeps each JSON line whole and never interleaves two
        frames (no global stdout redirection that would race wire sends).
        """
        with self._send_lock:
            self._send_fn(message)

    def _reply(self, req_id: Any, result: Any) -> dict[str, Any]:
        return {"kind": KIND_REPLY, "id": req_id, "result": result}

    def _error(self, req_id: Any, message: str) -> dict[str, Any]:
        return {"kind": KIND_REPLY, "id": req_id, "error": message}

    # -- message handling --------------------------------------------------

    def handle(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        """Handle one inbound message; return an inline reply frame or None.

        Requests reply inline (result or error). Host events and native results
        drive evaluation/delivery as side effects and return None (their effect
        is emitted through ``send``), never a false success.
        """
        with self._eval_lock:
            if self._closed:
                raise ConnectionClosed("session runtime is closed")
            if not isinstance(message, dict):
                raise ProtocolError("frame must be a JSON object")
            kind = message.get("kind")
            if kind == KIND_REQUEST:
                return self._handle_request(message)
            if kind == KIND_HOST_EVENT:
                self._handle_host_event(message)
                return None
            if kind == KIND_NATIVE_RESULT:
                self._handle_native_result(message)
                return None
            raise ProtocolError(f"unknown message kind {kind!r}")

    def _handle_request(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        req_id = message.get("id")
        if not isinstance(req_id, (str, int)):
            raise ProtocolError("request id must be a string or integer")
        operation = message.get("operation")
        if not isinstance(operation, str) or not operation:
            raise ProtocolError("request operation must be a non-empty string")
        arguments = message.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ProtocolError("request arguments must be an object")
        # Identity is taken ONLY from the bound session, never from arguments.
        if operation in READ_OPERATIONS:
            return self._reply(req_id, self._read_operation(operation, arguments))
        if operation in CONTROL_OPERATIONS:
            return self._handle_control(req_id, operation, arguments)
        # Unknown operations are never accepted as success.
        return self._error(
            req_id, f"operation {operation!r} is not handled by the session runtime"
        )

    def _read_operation(self, operation: str, arguments: Mapping[str, Any]) -> Any:
        # Status/snapshot render from the authoritative queue snapshot; every
        # other read reuses the existing core query. No parallel logic lives here.
        if operation == "snapshot":
            snap = self._queue.snapshot(self._parent_session)
            return {
                "parent_session": snap.parent_session,
                "counts": snap.counts,
                "active": snap.active,
                "ready": snap.ready,
                "ready_run_ids": list(snap.ready_run_ids),
                "open_admissions": list(snap.open_admissions),
                "reported_run_ids": list(snap.reported_run_ids),
                "jobs": [
                    {
                        "job_id": job.job_id,
                        "run_id": job.run_id,
                        "role": job.role,
                        "status": str(job.status),
                    }
                    for job in snap.jobs
                ],
            }
        if operation == "status":
            data = status_query(self._queue, self._parent_session)
            return {"text": render_status(data, self._mode)}
        # Unreachable: _handle_request routes only READ_OPERATIONS here.
        raise ProtocolError(f"operation {operation!r} is not handled")  # pragma: no cover

    # -- control operations ------------------------------------------------

    def _require_config(self) -> OrchestraConfig:
        if self._config is None:
            raise RuntimeError("this session runtime has no configuration for the operation")
        return self._config

    def _handle_control(
        self, req_id: Any, operation: str, arguments: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        """Route a control operation; the reply may be inline or out-of-band.

        ``dispatch`` admits the request and returns ``None`` (its reply is sent
        once Submit durably accepts or definitively fails). Every other control
        operation reuses an existing core operation synchronously. A core error
        is relayed verbatim as an error reply — never replaced by a success.
        """
        if operation == "dispatch":
            return self._handle_dispatch(req_id, arguments)
        try:
            if operation == "history":
                return self._reply(req_id, self._op_history(arguments))
            if operation == "stop":
                return self._reply(req_id, self._op_stop(arguments))
            if operation == "roles":
                return self._reply(req_id, self._op_roles())
            if operation == "help":
                from orchestra import cli

                return self._reply(req_id, {"text": cli.HELP_TEXT})
            if operation == "doctor":
                return self._reply(req_id, self._op_doctor())
            if operation == "initial-mode":
                mode = self._require_config().runtime.default_mode
                return self._reply(req_id, {"mode": mode, "text": mode})
            if operation == "mode":
                return self._reply(req_id, self._op_mode(arguments))
        except Exception as exc:  # noqa: BLE001 - relay the real core error, never fake success
            return self._error(req_id, str(exc))
        return self._error(  # pragma: no cover - CONTROL_OPERATIONS is exhaustive
            req_id, f"operation {operation!r} is not handled by the session runtime"
        )

    def _op_history(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        from orchestra import cli

        limit = arguments.get("limit")
        if limit is not None and not isinstance(limit, int):
            raise ValueError("history limit must be an integer")
        entries, unresolved = cli.history_runs(
            self._queue, self._state_dir, self._parent_session, limit
        )
        lines = ["Recent runs:"] if entries else ["No completed runs yet."]
        for entry in entries:
            lines.append(
                f"  run {entry['run_id']} — {entry['succeeded']} succeeded, "
                f"{entry['failed']} failed, {entry['skipped']} skipped"
            )
        return {"runs": entries, "unresolved": unresolved, "text": "\n".join(lines) + "\n"}

    def _op_stop(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        from orchestra import cli

        # Frozen wire: the stop request argument is ``runId`` (camelCase), matching
        # the public tool field. The structured result keys stay core-owned.
        run_id = arguments.get("runId")
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("stop requires a runId")
        result = cli.control_stop(self._queue, self._state_dir, self._parent_session, run_id)
        # Cancellation changes durable state; wake the shared evaluator.
        self.request_evaluation()
        status = "stopped" if result["stopped"] else "stop requested"
        return {**result, "text": f"Run {run_id}: {status}.\n"}

    def _op_roles(self) -> dict[str, Any]:
        from orchestra import cli

        config = self._require_config()
        catalog = cli.roles_catalog(config)
        lines = [f"Default role: {config.catalog.default_role}", "Roles:"]
        for name, role in config.catalog.roles.items():
            lines.append(f"  {name} ({role.enabled}) model {role.model}")
        return {**catalog, "text": "\n".join(lines) + "\n"}

    def _op_doctor(self) -> dict[str, Any]:
        from orchestra import cli

        lines, problems = cli.doctor_report(self._require_config())
        text = "\n".join(lines + [f"problem: {p}" for p in problems]) + "\n"
        return {"text": text, "problems": problems, "ok": not problems}

    def _op_mode(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        mode = arguments.get("mode")
        if mode not in ("on", "off"):
            raise ValueError("mode must be 'on' or 'off'")
        self._mode = mode
        # A mode change must reach the live widget through the SAME evaluator so
        # the status frame's mode_text updates immediately (no separate render
        # path and no cached mode string).
        self.request_evaluation()
        return {"mode": mode, "text": f"Orchestra: {mode}\n"}

    def _native_session_ids(self, snap: Any) -> list[str]:
        """Native Pi session handles for current owned jobs (baseline excluded).

        Derived from the SAME plugin session-id function used to launch Pi, so
        there is no duplicated ``orchestra-worker-`` prefix anywhere, and only
        for jobs whose role's configured harness is Pi. These are transient
        transport handles for the native renderer: nothing is cached here and no
        queue row or cost data is copied. A runtime with no configuration has no
        harness mapping and emits an empty list (injected no-config tests).
        """
        if self._config is None:
            return []
        from orchestra.pi_harness import worker_session_id

        harnesses = self._config.harnesses
        roles = self._config.catalog.roles
        baseline = snap.baseline_run_ids
        ids: list[str] = []
        seen: set[str] = set()
        for job in snap.jobs:
            if job.run_id in baseline:
                continue  # attachment baseline is never re-surfaced
            role = roles.get(job.role)
            if role is None:
                continue
            harness = harnesses.get(role.harness_config)
            if harness is None or harness.harness != "pi":
                continue
            session_id = worker_session_id(job.job_id)
            if session_id not in seen:
                seen.add(session_id)
                ids.append(session_id)
        return ids

    # -- dispatch (Submit + independent worker) ----------------------------

    def _handle_dispatch(
        self, req_id: Any, arguments: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        """Validate, admit before launching, then accept on a worker thread.

        Admission is opened on the event-loop thread before anything crosses
        into the queue, so readiness stays false while the submission is
        being accepted. Submit runs off the loop so a configured role's native
        parent-context capture can block for the host result without stalling
        the loop; execution is then launched as an independent worker.
        """
        goal = arguments.get("goal")
        if not isinstance(goal, str) or not goal.strip():
            return self._error(req_id, "dispatch requires a non-empty goal")
        role = arguments.get("role")
        if role is not None and not isinstance(role, str):
            return self._error(req_id, "dispatch role must be a string")
        # Public dispatch fields are exactly goal, role?, taskLabel?, additionalContext?.
        # ``taskLabel`` is the single canonical label field (no ``task_label`` alias);
        # a supplied value is kept literally (including empty/whitespace) and only an
        # absent value omits it. A wrong supplied type is the real core error, never a
        # truthiness-coerced label. Argument types are validated before any capability
        # check so an invalid field is reported by its actual cause.
        task_label = arguments.get("taskLabel")
        if task_label is not None and not isinstance(task_label, str):
            return self._error(req_id, "dispatch taskLabel must be a string")
        additional_context = arguments.get("additionalContext")
        if additional_context is not None and not isinstance(additional_context, str):
            return self._error(req_id, "dispatch additionalContext must be a string")
        if self._config is None:
            return self._error(req_id, "dispatch is not configured for this session runtime")
        if isinstance(additional_context, str) and additional_context.strip():
            goal = f"{goal}\n\nAdditional context:\n{additional_context}"
        request_id = str(req_id)
        try:
            self._queue.begin_submission(self._parent_session, request_id)
        except Exception as exc:  # noqa: BLE001 - admission failure is relayed as the real cause
            return self._error(req_id, f"dispatch admission failed: {exc}")
        self.request_evaluation()
        thread = threading.Thread(
            target=self._run_dispatch,
            args=(req_id, request_id, goal, role, task_label),
            daemon=True,
        )
        self._admission_threads.append(thread)
        thread.start()
        return None  # reply is delivered out-of-band on acceptance or failure

    def _run_dispatch(
        self,
        req_id: Any,
        request_id: str,
        goal: str,
        role: str | None,
        task_label: Any,
    ) -> None:
        from orchestra.submit import Assignment, submit

        config = self._require_config()
        try:
            submission = submit(
                self._state_dir,
                self._queue,
                config,
                self._parent_session,
                [Assignment(goal=goal, role=role)],
                context_provider=self._request_native_context,
            )
        except Exception as exc:  # noqa: BLE001 - definite submission failure relays the real cause
            # No job rows exist: release the admission and relay the cause.
            self._emit(self._error(req_id, str(exc)))
            self._queue.finish_submission(self._parent_session, request_id)
            self.request_evaluation()
            return
        # Launch execution while the admission is still open. A worker that
        # completes during launch cannot flip readiness true — and so cannot
        # have its report delivered — before the acceptance reply below is
        # emitted, because the open admission keeps the session non-ready.
        launch_error: Exception | None = None
        try:
            self._launch_worker(submission)
        except Exception as exc:  # noqa: BLE001 - launch failure is the real cause, surfaced
            launch_error = exc
            # Jobs are durable but no dispatcher will ever claim them: fail them
            # authoritatively and record a real Response with the launch cause.
            self._record_launch_failure(submission, exc)
        # Emit the reply (ack or launch-failure error) while the admission is
        # still open, then close it and run exactly one evaluation on this same
        # path. Doing so after the reply guarantees the caller receives the ack
        # before any assembled report can be delivered.
        if launch_error is None:
            self._emit(self._reply(req_id, self._dispatch_ack(submission, task_label)))
        else:
            self._emit(self._error(req_id, f"execution launch failed: {launch_error}"))
        self._queue.finish_submission(self._parent_session, request_id)
        self.request_evaluation()

    def _record_launch_failure(self, submission: Any, exc: Exception) -> None:
        """Fail unstarted jobs and record one real Response per failed row.

        A definite launch failure leaves durable job rows no dispatcher will
        ever claim. ``fail_unstarted`` marks them failed and skips dependents;
        writing a Response through the shared dispatcher record keeps the run
        assembleable and reportable with the real launch cause, so Results never
        errors on a failed job with no response and the failed accepted jobs and
        their skipped dependencies stay inspectable.
        """
        from orchestra.dispatcher import _record

        try:
            failed = self._queue.fail_unstarted(submission.run_id, self._parent_session)
        except Exception:  # noqa: BLE001 - best-effort; the error reply relays the cause
            return
        reason = f"failed: execution launch failed: {exc}"
        for job in failed:
            if job.status == "failed":
                _record(self._state_dir, submission.run_id, job.job_id, reason, "")

    def _launch_worker(self, submission: Any) -> None:
        """Launch the independent dispatcher worker for an accepted run.

        The worker runs in its own process group with stdout/stderr detached, so
        it survives this connection's death and a broken connection reader can
        never stop or corrupt it. The prepared execution plan ({run_id,
        payloads}) is passed on stdin as JSON data — never shell text — and the
        worker drives the existing dispatcher path to a durable outcome.

        A dedicated one-way notification pipe (worker -> connection) carries a
        minimal wake trigger for each real execution lifecycle event so progress
        reaches the SAME evaluator without waiting for the periodic backstop or a
        host event. The pipe is one-way and the worker never reads it, so the
        connection closing cannot back-pressure or stop execution.
        """
        plan = {
            "run_id": submission.run_id,
            "payloads": {
                job_id: list(argv) for job_id, argv in submission.payloads.items()
            },
        }
        read_fd, write_fd = os.pipe()
        try:
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "orchestra",
                    "__run",
                    "--run-id",
                    submission.run_id,
                    "--notify-fd",
                    str(write_fd),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                pass_fds=(write_fd,),
            )
        except Exception:
            # Launch failed: close both local ends so the fd does not leak, then
            # let the real cause surface to the caller's launch-failure path.
            with suppress(OSError):
                os.close(read_fd)
            with suppress(OSError):
                os.close(write_fd)
            raise
        # The connection holds ONLY the read end; close the local write copy so
        # the observer observes EOF the moment the worker itself exits/closes.
        with suppress(OSError):
            os.close(write_fd)
        assert proc.stdin is not None
        proc.stdin.write((encode_line(plan) + "\n").encode("utf-8"))
        proc.stdin.close()
        self._workers.append(proc)
        # Core-owned observer: wake the shared evaluator on each real progress
        # event, then reap the worker's exit and wake once more for the terminal
        # outcome — the same single evaluator every other event uses.
        observer = threading.Thread(
            target=self._observe_worker,
            args=(proc, read_fd),
            daemon=True,
        )
        self._observer_threads.append(observer)
        observer.start()

    def _observe_worker(
        self, proc: subprocess.Popen[bytes], read_fd: int
    ) -> None:
        """Wake the evaluator on each worker progress event, then reap its exit.

        Each line read from the notification channel is a minimal wake trigger
        (the event as a trigger only): the observer copies none of its contents
        into core state and instead wakes the SAME evaluator, which re-reads the
        authoritative queue. A read error simply means the channel closed (the
        worker exited or its write end broke) — never fatal here. After the
        channel closes, reap the worker's exit and wake once more so the final
        outcome is evaluated even if it exited before sending a line.
        """
        channel: Any = None
        with suppress(Exception):  # a closed/broken channel is expected on exit
            channel = os.fdopen(read_fd, "r")
            for _trigger in channel:
                if not self._closed:
                    self.request_evaluation()
        if channel is not None:
            with suppress(Exception):
                channel.close()
        else:
            with suppress(OSError):
                os.close(read_fd)
        with suppress(Exception):  # reaping never aborts the observer
            proc.wait()
        if not self._closed:
            self.request_evaluation()

    def _dispatch_ack(self, submission: Any, task_label: Any) -> dict[str, Any]:
        """Assemble the complete core-owned dispatch acknowledgement."""
        from orchestra.status import render_session_counts

        session_status = render_session_counts(status_query(self._queue, self._parent_session))
        ack_text = self._prompts["dispatch_ack"]
        role = submission.jobs[0].role if submission.jobs else ""
        identifiers = [f"Run: {submission.run_id}"]
        if role:
            identifiers.append(f"Role: {role}")
        if submission.jobs:
            jobs = ", ".join(
                f"#{job.sequence} {job.job_id} ({job.role})" for job in submission.jobs
            )
            identifiers.append(f"Jobs: {jobs}")
        lines = [ack_text, " · ".join(identifiers), session_status]
        if isinstance(task_label, str) and task_label:
            lines.append(f"Task label: {task_label}")
        if self._mode == "off":
            lines.append("Orchestra is in mode 'off'.")
        result: dict[str, Any] = {
            "run_id": submission.run_id,
            "role": role,
            "ack": ack_text,
            "jobs": [
                {"job_id": job.job_id, "sequence": job.sequence, "role": job.role}
                for job in submission.jobs
            ],
            "session_status": session_status,
            "text": "\n\n".join(lines),
        }
        # The structured field preserves the supplied label literally (even an
        # empty/whitespace string); only an absent label (None) omits it.
        if task_label is not None:
            result["task_label"] = task_label
        return result

    def _request_native_context(self) -> str:
        """Ask the host for parent context and block (off-loop) for the result.

        Invoked by Submit on an admission thread only when a resolved role
        opts in via configuration. The capture is requested by CORE (the host
        knows how to read context, not which role needs it); a rejection or
        timeout fails loudly — never a fake capture.
        """
        with self._eval_lock:
            if self._closed:
                raise ConnectionClosed("session runtime is closed")
            self._ctx_seq += 1
            req_id = f"context-{self._ctx_seq}"
            event = threading.Event()
            holder: dict[str, Any] = {"event": event, "text": None}
            self._pending_context[req_id] = holder
        self._emit(
            {
                "kind": KIND_NATIVE_REQUEST,
                "id": req_id,
                "operation": NATIVE_CONTEXT_OPERATION,
                "arguments": {},
            }
        )
        if not event.wait(NATIVE_CONTEXT_TIMEOUT):
            self._pending_context.pop(req_id, None)
            raise SubmitError(f"native {NATIVE_CONTEXT_OPERATION} timed out")
        text = holder["text"]
        if not isinstance(text, str):
            # A rejection or a malformed result payload (data.text not a string)
            # leaves the captured text unset; fail loudly, never a fake capture.
            raise SubmitError(f"native {NATIVE_CONTEXT_OPERATION} was rejected")
        return text

    def _handle_host_event(self, message: Mapping[str, Any]) -> None:
        event = message.get("event")
        if not isinstance(event, str) or not event:
            raise ProtocolError("host_event must carry a non-empty event name")
        if not isinstance(message.get("details", {}), dict):
            raise ProtocolError("host_event details must be an object")
        if event in ("available", "agent_start", "session_start"):
            self._native_available = True
        elif event in ("unavailable", "session_end", "session_switch"):
            self._native_available = False
        elif event == "compaction_start":
            self._compacting = True
        elif event in ("compaction_end", "compaction"):
            self._compacting = False
        # Any host event can reveal new durable state; wake the shared evaluator.
        self.request_evaluation()

    def _handle_native_result(self, message: Mapping[str, Any]) -> None:
        req_id = message.get("id")
        accepted = message.get("accepted")
        if not isinstance(req_id, (str, int)):
            raise ProtocolError("native_result must carry an id")
        if not isinstance(accepted, bool):
            raise ProtocolError("native_result accepted must be a boolean")
        if req_id in self._pending_context:
            # A blocking native parent-context capture (get_parent_context) that
            # an admission thread is waiting on. Resolve it by hand OUTSIDE the
            # evaluation lock: setting the event never waits, and the waiting
            # admission is off the event loop, so no lock is ever held across
            # the external native wait. An accepted result with data.text
            # populates the capture; a rejection or malformed payload leaves it
            # unset so the waiter fails loudly.
            holder = self._pending_context.pop(req_id)
            if accepted:
                data = message.get("data")
                if isinstance(data, dict) and isinstance(data.get("text"), str):
                    holder["text"] = data["text"]
            holder["event"].set()
            return
        # The delivery receipt mutates the same prepared/report state the
        # evaluator does (from any admission/observer thread), so guard it with
        # the single existing evaluation lock rather than a second tracker. No
        # external wait happens inside this section, so the lock is never held
        # across a native result. request_evaluation runs after release so the
        # non-reentrant lock is never re-acquired.
        acknowledged = False
        with self._eval_lock:
            if req_id == self._delivery_request_id:
                acknowledged = True
                if accepted:
                    # Native acceptance is a real host queueing: advance the
                    # queue-owned reported membership now, then clear the
                    # prepared report so a later pass does not re-deliver.
                    run_ids = tuple((self._prepared or {}).get("run_ids", ()))
                    self._queue.acknowledge_report(self._parent_session, run_ids)
                    self._prepared = None
                    self._delivery_request_id = None
                    self._delivery_failed = False
                else:
                    # A rejection is visible and never advances membership. No
                    # retry loop is introduced; the report stays prepared-but-
                    # unsent so it remains inspectable and explicit host action
                    # can recover.
                    self._delivery_request_id = None
                    self._delivery_failed = True
        if acknowledged:
            self.request_evaluation()

    # -- evaluation --------------------------------------------------------

    def request_evaluation(self) -> None:
        """Wake the shared evaluator, coalescing a single queued follow-up.

        At most one evaluation runs at a time; a request that arrives while one
        is in progress schedules exactly one follow-up pass after it finishes.
        Protected by ``_eval_lock`` so admission and observer threads cannot
        race on evaluation state or run evaluate() concurrently. A closed
        runtime never evaluates: an observer waking after ``close`` returns
        without querying a queue the owner may already have closed.
        """
        with self._eval_lock:
            if self._closed:
                return
            if self._evaluating:
                self._followup = True
                return
            self._evaluating = True
        try:
            while True:
                self.evaluate()
                with self._eval_lock:
                    if not self._followup:
                        break
                    self._followup = False
        finally:
            with self._eval_lock:
                self._evaluating = False

    def evaluate(self) -> None:
        """Run one evaluation pass over the authoritative queue state.

        Reconcile confirmed-dead dispatchers in the existing safe scope, take
        the queue snapshot, emit status, prepare at most one report when ready,
        and request native delivery when available. Pure snapshot reads never
        reconcile or acknowledge; reconciliation and acknowledgement here run
        only on a real dead-dispatcher loss or a real native receipt. A closed
        runtime evaluates nothing: the first action is a queue read, so the
        closed check must precede it, never after.
        """
        if self._closed:
            return
        reconcile.reconcile_abandoned(
            self._queue, self._state_dir, parent_session=self._parent_session
        )

        # Take the authoritative snapshot AND make the prepared/delivery decision
        # as ONE section under the existing evaluation lock. The native delivery
        # receipt mutates the same prepared/report state under this same lock, so
        # it can never interleave between the snapshot and the prepared-state
        # decision: a stale "ready" snapshot cannot re-prepare a run the receipt
        # already acknowledged and cleared. No external wait happens inside this
        # section (assembly and emit are in-process), so the lock is never held
        # across a native wait, and job execution stays independent/parallel.
        with self._eval_lock:
            snap = self._queue.snapshot(self._parent_session)

            # Status, readiness selection, and Results all derive from this ONE
            # snapshot: pass it to status so the meter is the same consistent read
            # that chose the ready runs, and on to assembly for the idle check.
            data = status_query(self._queue, self._parent_session, snapshot=snap)
            self._emit(
                {
                    "kind": KIND_STATUS,
                    "text": render_running_meter(data),
                    "native_session_ids": self._native_session_ids(snap),
                    "mode_text": f"(Orchestra: {self._mode})",
                }
            )

            if self._prepared is None and snap.ready and not self._delivery_failed:
                try:
                    self._prepared = self._assemble(snap.ready_run_ids, snap)
                except Exception:  # noqa: BLE001 - assembly failure is visible, never a crash
                    self._delivery_failed = True

            if (
                self._prepared is not None
                and self._delivery_request_id is None
                and not self._delivery_failed
                and self.native_available
            ):
                self._request_delivery()

            self._arm_timer(snap)

    def _assemble(
        self, run_ids: tuple[str, ...], snap: Any
    ) -> dict[str, Any]:
        ret = results.assemble_session(
            self._queue,
            self._state_dir,
            self._prompts,
            self._parent_session,
            run_ids,
            snapshot=snap,
        )
        return {
            "run_ids": list(ret.run_ids),
            "category": ret.category,
            "hint": ret.hint,
            "note": ret.note,
            "text": results.render_report_text(ret),
            "jobs": [asdict(job) for job in ret.jobs],
        }

    def _request_delivery(self) -> None:
        assert self._prepared is not None  # set by caller
        self._native_seq += 1
        req_id = f"deliver-{self._native_seq}"
        self._delivery_request_id = req_id
        self._emit(
            {
                "kind": KIND_NATIVE_REQUEST,
                "id": req_id,
                "operation": "deliver_report",
                "arguments": {"text": self._prepared["text"], "report": self._prepared},
            }
        )

    # -- periodic backstop -------------------------------------------------

    def _arm_timer(self, snap: Any) -> None:
        """Schedule the next backstop only while active work is outstanding."""
        # A prepared-but-failed delivery is not outstanding: it stays for
        # inspection but never becomes a silent retry loop.
        outstanding = snap.active or (
            self._prepared is not None and not self._delivery_failed
        )
        if outstanding:
            self._next_due = self._monotonic() + self._interval
        else:
            self._next_due = None

    def time_until_due(self) -> float | None:
        """Seconds until the next backstop, or None when none is scheduled."""
        if self._next_due is None:
            return None
        return max(0.0, self._next_due - self._monotonic())

    def on_tick(self) -> None:
        """Handle a timer tick: run the same evaluator and re-arm if needed."""
        # The tick is only delivered when a due was armed; run the shared pass.
        self._next_due = None
        if not self._closed:
            self.request_evaluation()

    # -- serve loop --------------------------------------------------------

    def serve(self, source: Any) -> None:
        """Read framed messages until the stream ends, running the evaluator.

        ``source`` is a frame source exposing ``poll(timeout)`` returning a line,
        ``TIMEOUT`` (no input yet), or ``None`` (EOF). The loop keeps accepting
        frames (requests, host events, native results) while idle and wakes for
        the periodic backstop while work is outstanding. Closing stops only this
        loop and its timer; it never touches independently-launched execution.
        """
        poll = source.poll
        try:
            while not self._closed:
                timeout = self._poll_timeout()
                outcome = poll(timeout)
                if outcome is None:
                    break  # EOF: the connection stream closed
                if isinstance(outcome, _Timeout):
                    self.on_tick()
                    continue
                self._dispatch_line(outcome)
        finally:
            # Proper teardown: stop the timer, release any parked context
            # waiter, and join the connection's own admission threads so a
            # caller may close the queue immediately after serve returns.
            self.close()

    def _poll_timeout(self) -> float | None:
        due = self.time_until_due()
        if due is None:
            return None  # idle: block for the next frame
        return due

    def _dispatch_line(self, line: str) -> None:
        if not line.strip():
            return
        try:
            message = decode_line(line)
            reply = self.handle(message)
        except ProtocolError as exc:
            self._emit({"kind": KIND_REPLY, "id": None, "error": f"protocol error: {exc}"})
            return
        except ConnectionClosed:
            raise
        if reply is not None:
            self._emit(reply)

    def close(self) -> None:
        """Close the runtime loop and timer (never touches running execution).

        Lifecycle guarantee: after ``close`` returns, no thread this runtime
        owns touches the queue again, so the owner may then ``queue.close()``
        safely. It (1) stops the timer and marks the runtime closed so no
        later evaluation runs, (2) releases any admission thread blocked on a
        native context capture so it fails its submission promptly and its join
        below cannot hang, and (3) joins the connection's OWN admission threads
        so their final ``finish_submission``/evaluation complete before the
        queue is closed. It never joins or signals an independently-launched
        execution worker or its observer — those keep their own process groups
        and outlive this connection; their post-exit wake is a no-op once
        ``_closed`` is set.
        """
        self._closed = True
        self._next_due = None
        # Release native-context waiters first: an admission thread parked on
        # ``event.wait`` would otherwise hold its join until the 120s capture
        # timeout. A released waiter finds no text and fails its submission
        # loudly (never a fake capture), then its ``request_evaluation`` is a
        # no-op because ``_closed`` is already set.
        for holder in list(self._pending_context.values()):
            holder["event"].set()
        self._pending_context.clear()
        # Join this connection's own admission threads (bounded) so none is
        # mid-queue-touch when the owner closes the queue. Observers and worker
        # processes are intentionally NOT joined: waiting on them would wait on
        # independent execution, which this contract must never do.
        for thread in list(self._admission_threads):
            if thread is not threading.current_thread():
                thread.join(timeout=ADMISSION_JOIN_TIMEOUT)
        # Prune finished threads so a long-lived session does not grow the list.
        self._admission_threads = [
            thread for thread in self._admission_threads if thread.is_alive()
        ]
