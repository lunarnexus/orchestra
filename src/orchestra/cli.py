"""Minimal core command entry for harness plugins.

One thin, generic entry point covering the operations every host plugin
needs: dispatch (submit + run + assemble, printing one JSON acknowledgement
line, then one JSON return line), status, history, stop, help, doctor, and
the configured initial session mode. All wording here is host-neutral; the
host adapters add no wording of their own.

Line protocol for ``dispatch`` (JSONL on stdout):
  {"type": "ack", "run_id": ..., "role": ..., "ack": ..., "jobs": [...], "session_status": ...}
  {"type": "event", "session_id": ..., "run_id": ..., "job_id": ..., "status": ...}  (0 or more, mid-run)
  {"type": "return", "run_id": ..., "return": {...} | null, "stopped": bool}

The ``event`` lines are generic lifecycle transitions emitted while jobs run,
between the acknowledgement and the final return; a host must treat them as
neither the ack nor the return.

Errors go to stderr as plain text and exit nonzero: failures are loud.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from orchestra.config import OrchestraConfig, load_orchestra_config
from orchestra.dispatcher import JobEvent
from orchestra.dispatcher import run as run_dispatcher
from orchestra.lifetime import DispatcherLifetimeLock
from orchestra.pi_harness import AgentPlan, PiHarness, worker_session_id
from orchestra.queue import Job, JobQueue
from orchestra.reconcile import ReconcileReport, reconcile_abandoned
from orchestra.results import assemble, assemble_session
from orchestra.status import render_session_counts, render_status
from orchestra.status import status as status_query
from orchestra.submit import Assignment, Submission, submit

QUEUE_FILENAME = "queue.db"
STOP_DIRNAME = "stops"
SKILLS_DIRNAME = "skills"
STOP_POLL_SECONDS = 15.0
STOP_POLL_INTERVAL = 0.25

def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = {
        **MANAGEMENT_HANDLERS,
        "dispatch": _cmd_dispatch,
        "__run": _cmd_run,
        "session-return": _cmd_session_return,
        "initial-mode": _cmd_initial_mode,
        "tool-info": _cmd_tool_info,
        "__session": _cmd_session,
    }[args.command]
    try:
        handler(args)
    except Exception as exc:  # noqa: BLE001 - the CLI boundary reports loudly
        print(f"orchestra error: {exc}", file=sys.stderr)
        return 1
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orchestra", description="Orchestra 2 core operations")
    subparsers = parser.add_subparsers(dest="command", required=True)
    dispatch = subparsers.add_parser("dispatch", help="submit an assignment and run it to completion")
    dispatch.add_argument("--session-id", required=True)
    dispatch.add_argument("--goal", required=True)
    dispatch.add_argument("--role")
    dispatch.add_argument("--task-label")
    status = subparsers.add_parser("status", help="query session and global job status")
    status.add_argument("--session-id", required=True)
    status.add_argument("--mode", default="on", choices=("on", "off"))
    history = subparsers.add_parser("history", help="completed runs for a session")
    history.add_argument("--session-id", required=True)
    history.add_argument("--limit", type=int, default=10)
    stop = subparsers.add_parser("stop", help="cancel an active run owned by the session")
    stop.add_argument("--session-id", required=True)
    stop.add_argument("--run-id", required=True)
    subparsers.add_parser("roles", help="list the configured roles (read-only)")
    session_return = subparsers.add_parser(
        "session-return",
        help="assemble one consolidated return across completed runs of a session",
    )
    session_return.add_argument("--session-id", required=True)
    session_return.add_argument("--run-id", action="append", required=True)
    subparsers.add_parser("help", help="show Orchestra help")
    subparsers.add_parser("doctor", help="check Orchestra setup and report findings")
    subparsers.add_parser("initial-mode", help="print the configured initial session mode")
    subparsers.add_parser("tool-info", help="emit core tool metadata JSON for host registration")
    # Internal transport entry: the core session connection loop for one attached
    # native session. Hidden from help; it is not a user-facing command. The
    # owning session identity is bound from native adapter arguments and is
    # never accepted from model/request arguments.
    session = subparsers.add_parser(
        "__session",
        help=argparse.SUPPRESS,
        description="internal core session connection over newline-framed JSON stdio",
    )
    session.add_argument("--parent-session", required=True, dest="parent_session")
    # Internal independent execution worker: runs the dispatcher phase for one
    # already-submitted run from a prepared payload plan read on stdin. Hidden
    # from help; launched by the session runtime in its own process group so
    # execution outlives the connection. Prompts arrive as stdin data, not argv.
    run = subparsers.add_parser(
        "__run",
        help=argparse.SUPPRESS,
        description="internal independent dispatcher worker for one submitted run",
    )
    run.add_argument("--run-id", required=True, dest="run_id")
    # Optional worker->connection notification channel: an already-open write fd
    # (inherited via pass_fds) the worker writes a minimal lifecycle wake trigger
    # to. Hidden from help; supplied only by the core session runtime.
    run.add_argument("--notify-fd", dest="notify_fd", type=int, default=None)
    return parser


def _load(args: argparse.Namespace) -> OrchestraConfig:
    return load_orchestra_config()


def _queue(config: OrchestraConfig) -> JobQueue:
    return JobQueue(Path(config.runtime.state_dir) / QUEUE_FILENAME)


def _unresolved(report: ReconcileReport) -> list[dict[str, str]]:
    """Generic blocker view of the work one reconciliation pass could not resolve.

    A retained job stays running because its dispatcher loss is unconfirmed
    (no lifetime lock) or its execution identity is unverified, so it must not
    be finalized on a guess. Each entry carries the job id and the reason the
    report recorded, so a caller surfaces a truthful blocker instead of
    silently discarding the report. The shape is host-neutral and additive.
    """
    return [{"job_id": entry.job_id, "reason": entry.detail} for entry in report.retained]


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------


def _cmd_dispatch(args: argparse.Namespace) -> None:
    config = _load(args)
    parent_context = sys.stdin.read()
    queue = _queue(config)
    assignment = Assignment(
        goal=args.goal,
        role=args.role,
    )
    submission = submit(
        Path(config.runtime.state_dir),
        queue,
        config,
        args.session_id,
        [assignment],
        context_provider=lambda: parent_context,
    )
    ack = config.prompts["dispatch_ack"]
    # Snapshot the session's active jobs now that this submission (and any
    # queued follow-ups) is in the queue but before the dispatcher claims work.
    # A read-only queue query — no extra status subprocess and no reconcile.
    session_status = render_session_counts(status_query(queue, args.session_id))
    ack_payload: dict[str, object] = {
        "type": "ack",
        "run_id": submission.run_id,
        "role": _role_of(submission),
        "ack": ack,
        "jobs": [
            {
                "job_id": job.job_id,
                "sequence": job.sequence,
                "role": job.role,
                "worker_session_id": worker_session_id(job.job_id),
            }
            for job in submission.jobs
        ],
        "session_status": session_status,
    }
    if getattr(args, "task_label", None) is not None:
        ack_payload["task_label"] = args.task_label
    print(
        json.dumps(ack_payload, separators=(",", ":")),
        flush=True,
    )
    # A per-dispatcher OS lifetime lock, acquired inside ``_run_execution``
    # and held for the whole run, is what reconciliation trusts to detect
    # dispatcher death. Forward each dispatcher lifecycle transition as a typed
    # intermediate JSONL message on the SAME stdout stream as the ack/return;
    # a lock keeps concurrent worker events complete, single-line records.
    stream_lock = threading.Lock()

    def on_event(event: JobEvent) -> None:
        with stream_lock:
            print(
                json.dumps(
                    {
                        "type": "event",
                        "session_id": event.session_id,
                        "run_id": event.run_id,
                        "job_id": event.job_id,
                        "status": event.status,
                    },
                    separators=(",", ":"),
                ),
                flush=True,
            )

    stop_event = _stop_event(config, submission.run_id)
    harness = _run_execution(
        config,
        queue,
        submission.run_id,
        submission.jobs,
        submission.payloads,
        on_event=on_event,
        stop_event=stop_event,
    )
    _record_notes(config, submission.run_id, submission.jobs, harness)
    if getattr(stop_event, "stop_requested", False):
        print(
            json.dumps(
                {"type": "return", "run_id": submission.run_id, "return": None, "stopped": True}
            ),
            flush=True,
        )
        return
    assembled = assemble(queue, config.runtime.state_dir, config.prompts, submission.run_id)
    print(
        json.dumps(
            {
                "type": "return",
                "run_id": submission.run_id,
                "stopped": False,
                "return": {
                    "run_id": assembled.run_id,
                    "category": assembled.category,
                    "hint": assembled.hint,
                    "note": assembled.note,
                    "jobs": [asdict(job) for job in assembled.jobs],
                },
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


def _role_of(submission: Submission) -> str:
    return submission.jobs[0].role if submission.jobs else "worker"


def _worker_notifier(notify_fd: int | None) -> Callable[[JobEvent], None] | None:
    """Build a worker->connection wake notifier writing to an inherited fd.

    Returns ``None`` when no notification fd was supplied (e.g. a standalone
    ``__run``), so execution is identical to before. When supplied, one minimal
    line is written per dispatcher :class:`JobEvent`: the event is a wake trigger
    only (the connection re-reads authoritative queue state), never a copy of
    core state. A closed reader (the connection is gone) surfaces as a write or
    flush error, which is swallowed here so a lost reader can NEVER stop healthy
    execution or its durable finalization.
    """
    if notify_fd is None or notify_fd < 0:
        return None
    try:
        channel = os.fdopen(notify_fd, "w")
    except (OSError, ValueError):
        # The inherited fd is unusable: run without notifications rather than
        # aborting a healthy execution over a missing wake channel.
        return None
    stream_lock = threading.Lock()

    def notify(event: JobEvent) -> None:
        try:
            with stream_lock:
                channel.write(
                    json.dumps(
                        {
                            "run_id": event.run_id,
                            "job_id": event.job_id,
                            "status": event.status,
                        },
                        separators=(",", ":"),
                    )
                    + "\n"
                )
                channel.flush()
        except (OSError, ValueError):
            # A closed/broken reader never affects execution or durable record.
            return

    return notify


def _cmd_run(args: argparse.Namespace) -> None:
    """Independent dispatcher worker for one already-submitted run.

    Launched by the core session runtime in its own process group so accepted
    execution outlives the connection that admitted it. The prepared execution
    plan ({run_id, payloads}) arrives on stdin as JSON data (never shell text),
    the run's job rows are already durable, and outcomes are recorded through
    the same dispatcher path. Its own stdout/stderr are detached from the
    connection, so a broken connection reader never stops or corrupts it.
    """
    raw = sys.stdin.read()
    plan = json.loads(raw) if raw.strip() else {}
    payloads = {
        str(job_id): [str(token) for token in argv]
        for job_id, argv in dict(plan.get("payloads", {})).items()
    }
    config = _load(args)
    queue = _queue(config)
    jobs = queue.list_jobs(args.run_id)
    stop_event = _stop_event(config, args.run_id)
    notify = _worker_notifier(getattr(args, "notify_fd", None))
    harness = _run_execution(
        config,
        queue,
        args.run_id,
        jobs,
        payloads,
        stop_event=stop_event,
        on_event=notify,
    )
    _record_notes(config, args.run_id, jobs, harness)


def _cmd_session(args: argparse.Namespace) -> None:
    """Serve the core session runtime over newline-framed JSON stdio.

    Internal transport only. The bound session is the native runtime identity
    passed by the host adapter, never a model argument. The runtime opens the
    queue-owned session, runs the single evaluator on every event and the
    periodic backstop, and requests native delivery of at most one prepared
    report. Closing stops this connection and its timer only; independently-
    launched execution (each in its own process group) runs to a durable outcome.
    """
    from orchestra.session import SessionRuntime, encode_line
    from orchestra.session import _StdinSource as FrameSource

    config = _load(args)
    queue = _queue(config)
    try:
        # The runtime serializes every outbound frame internally (its serve
        # loop and any dispatch admission thread share one stdout), so this
        # callback only performs the write.
        def send(message: dict[str, object]) -> None:
            sys.stdout.write(encode_line(message) + "\n")
            sys.stdout.flush()

        runtime = SessionRuntime(
            queue=queue,
            parent_session=args.parent_session,
            state_dir=config.runtime.state_dir,
            prompts=config.prompts,
            send=send,
            mode=config.runtime.default_mode,
            config=config,
        )
        runtime.serve(FrameSource(sys.stdin))
    finally:
        queue.close()


def _cmd_session_return(args: argparse.Namespace) -> None:
    """Print one consolidated return JSON line for explicit completed runs.

    Core blocks loudly when the session still has outstanding jobs; host
    plugins call this after every dispatched run of the session has drained
    and inject the single return instead of per-run returns.
    """
    config = _load(args)
    queue = _queue(config)
    # Reconcile abandoned execution first so a dead dispatcher cannot keep the
    # consolidated session return permanently blocked by a stale running row.
    report = reconcile_abandoned(queue, config.runtime.state_dir, parent_session=args.session_id)
    unresolved = _unresolved(report)
    if unresolved:
        # A job retained as unresolved is genuinely still running, so assembly
        # must stay blocked; report the recorded reason through the error path
        # rather than a generic outstanding-count message.
        raise ValueError(
            "session return is blocked by unresolved work: "
            + "; ".join(f"{entry['job_id']}: {entry['reason']}" for entry in unresolved)
        )
    assembled = assemble_session(
        queue,
        config.runtime.state_dir,
        config.prompts,
        args.session_id,
        args.run_id,
    )
    print(
        json.dumps(
            {
                "type": "return",
                "session_id": assembled.parent_session,
                "run_ids": list(assembled.run_ids),
                "stopped": False,
                "return": {
                    "parent_session": assembled.parent_session,
                    "run_ids": list(assembled.run_ids),
                    "category": assembled.category,
                    "hint": assembled.hint,
                    "note": assembled.note,
                    "jobs": [asdict(job) for job in assembled.jobs],
                },
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


class _StopEvent(threading.Event):
    """Event plus a flag distinguishing a requested stop from process exit."""

    stop_requested: bool = False


def _stop_event(config: OrchestraConfig, run_id: str) -> _StopEvent:
    stop_event = _StopEvent()
    sentinel = Path(config.runtime.state_dir) / STOP_DIRNAME / run_id

    def watch() -> None:
        while not stop_event.is_set():
            if sentinel.exists():
                stop_event.stop_requested = True
                stop_event.set()
                return
            time.sleep(STOP_POLL_INTERVAL)

    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    return stop_event


def _harness_for(config: OrchestraConfig, submission: Submission) -> PiHarness:
    return _harness_for_jobs(config, submission.jobs)


def _harness_for_jobs(config: OrchestraConfig, jobs: Sequence[Job]) -> PiHarness:
    plans: dict[str, AgentPlan] = {}
    skills_dir = Path(config.config_dir) / SKILLS_DIRNAME
    for job in jobs:
        role = config.catalog.roles.get(job.role)
        if role is None:
            continue
        harness_config = config.harnesses.get(role.harness_config)
        if harness_config is None or harness_config.harness != "pi":
            continue
        resolved: list[str] = []
        missing: list[str] = []
        for skill in role.skills:
            path = skills_dir / skill / "SKILL.md"
            if path.is_file():
                resolved.append(str(path))
            else:
                missing.append(skill)
        plans[job.job_id] = AgentPlan(
            command=harness_config.command,
            model=job.model,
            env=role.env,
            skill_paths=tuple(resolved),
            missing_skills=tuple(missing),
        )
    return PiHarness(plans, config.prompts["budget_intervention"])


def _run_execution(
    config: OrchestraConfig,
    queue: JobQueue,
    run_id: str,
    jobs: Sequence[Job],
    payloads: Mapping[str, Sequence[str]],
    *,
    on_event: Callable[[JobEvent], None] | None = None,
    stop_event: threading.Event | None = None,
) -> PiHarness:
    """Run one already-submitted run to a durable terminal outcome.

    Shared by the inline ``dispatch`` command and the independent ``__run``
    worker so both drive the SAME dispatcher execution path — claim, harness
    execution, outcome recording, dependency release — with no second
    scheduler. A fresh per-dispatcher OS lifetime lock, acquired before
    claiming and held for the whole run, is what reconciliation trusts to
    detect dispatcher death; the child harness drops the descriptor
    (close-on-exec), so an orphaned child never keeps abandoned work live.
    Returns the harness so the caller can record post-execution notes.
    """
    harness = _harness_for_jobs(config, jobs)
    dispatcher_token = uuid.uuid4().hex
    runtime = config.runtime
    with DispatcherLifetimeLock.create(runtime.state_dir, dispatcher_token):
        run_dispatcher(
            queue,
            runtime.state_dir,
            harness,
            run_id,
            global_limit=runtime.concurrency.global_limit,
            per_session_limit=runtime.concurrency.per_session_limit,
            model_limits={
                name: limit.concurrency
                for name, limit in config.catalog.model_limits.items()
            },
            payloads=dict(payloads),
            stop_event=stop_event,
            on_event=on_event,
            dispatcher_token=dispatcher_token,
        )
    return harness


def _record_notes(
    config: OrchestraConfig, run_id: str, jobs: Sequence[Job], harness: PiHarness
) -> None:
    """Append final Response records linking the native session transcript.

    The dispatcher already recorded each job's returned answer and its real
    diagnostic reason (including a budget wrap-up) at completion, before the
    queue released dependents. This pass adds only what the harness learns
    after execution and the dispatcher never had: the subagent's native
    session transcript. It never rewrites the response text, so the recorded
    answer and reason stay exactly as the dispatcher persisted them.
    """
    from orchestra.artifacts import Response, append, recall

    state = Path(config.runtime.state_dir)
    for job in jobs:
        note = harness.note_for(job.job_id)
        records = [
            record
            for record in recall(state, run_id)
            if isinstance(record, Response) and record.job_id == job.job_id
        ]
        if not records:
            continue
        original = records[-1]
        if note.transcript is None or note.transcript == original.transcript:
            continue
        append(
            state,
            run_id,
            Response(
                job_id=job.job_id,
                timestamp=_now(),
                response=original.response,
                transcript=note.transcript,
            ),
        )


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# status / history / stop
# ---------------------------------------------------------------------------


def _cmd_status(args: argparse.Namespace) -> None:
    config = _load(args)
    queue = _queue(config)
    # Reconcile abandoned execution from confirmed-dead dispatchers before
    # reading, so status and the host footer never show a stale running job.
    # This is the shared recovery path the Pi prompt-start refresh reuses.
    report = reconcile_abandoned(queue, config.runtime.state_dir)
    unresolved = _unresolved(report)
    data = status_query(queue, args.session_id)
    rendered = render_status(data, args.mode)
    if unresolved:
        # Work that stays running on an unconfirmed loss must be readable too,
        # so the footer shows why a running job has not reached a terminal state.
        rendered += "Unresolved (needs attention):\n" + "".join(
            f"  {entry['job_id']}: {entry['reason']}\n" for entry in unresolved
        )
    print(
        json.dumps(
            {
                "rendered": rendered,
                "unresolved": unresolved,
                "data": {
                    "session_jobs": [asdict(entry) for entry in data.session_jobs],
                    "global_running": data.global_running,
                    "global_pending": data.global_pending,
                    "last_completed": asdict(data.last_completed) if data.last_completed else None,
                },
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


def history_runs(
    queue: JobQueue, state_dir: Path | str, parent_session: str, limit: int | None
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    """Return the session's completed runs (newest first, capped) + unresolved.

    Reused by the CLI ``history`` command and the core session runtime so the
    run tally, terminal classification, and reconcile-before-read behavior
    live in one place. Terminality comes from the queue-owned
    :attr:`Job.is_terminal`, never a copied status set.
    """
    if limit is not None and limit < 1:
        raise ValueError("history limit must be a positive integer")
    report = reconcile_abandoned(queue, state_dir, parent_session=parent_session)
    unresolved = _unresolved(report)
    runs: dict[str, list[Job]] = {}
    # Owned-session terminal jobs come from the one authoritative snapshot; the
    # queue already scopes to parent_session and is_terminal classifies them.
    for job in queue.snapshot(parent_session).jobs:
        if not job.is_terminal:
            continue
        runs.setdefault(job.run_id, []).append(job)
    entries: list[dict[str, object]] = []
    for run_id, run_jobs in runs.items():
        finished = [job.finished_at for job in run_jobs if job.finished_at]
        if not finished:
            continue
        entries.append(
            {
                "run_id": run_id,
                "finished_at": max(finished),
                "succeeded": sum(1 for job in run_jobs if job.status == "succeeded"),
                "failed": sum(1 for job in run_jobs if job.status == "failed"),
                "skipped": sum(1 for job in run_jobs if job.status == "skipped"),
            }
        )
    entries.sort(key=lambda entry: str(entry["finished_at"]), reverse=True)
    return (entries if limit is None else entries[:limit]), unresolved


def _cmd_history(args: argparse.Namespace) -> None:
    config = _load(args)
    queue = _queue(config)
    entries, unresolved = history_runs(queue, config.runtime.state_dir, args.session_id, args.limit)
    print(
        json.dumps(
            {"runs": entries, "unresolved": unresolved},
            separators=(",", ":"),
        ),
        flush=True,
    )


def control_stop(
    queue: JobQueue, state_dir: Path | str, parent_session: str, run_id: str
) -> dict[str, object]:
    """Cancel one run owned by ``parent_session``; return the stop result dict.

    Ownership and terminality come from the queue API: ``owned_run_jobs``
    rejects an unknown or foreign run, and :attr:`Job.is_terminal` decides
    completion — no copied status sets or ad-hoc ownership filters. Cancels
    through the shared reconciliation first (a dead dispatcher never observes
    the sentinel), then signals a live dispatcher via the cooperative sentinel
    and waits a bounded interval for the durable terminal outcome.
    """
    jobs = queue.owned_run_jobs(parent_session, run_id)
    if all(job.is_terminal for job in jobs):
        return {"run_id": run_id, "stopped": True, "already_finished": True, "unresolved": []}
    report = reconcile_abandoned(queue, state_dir, run_id=run_id)
    unresolved = _unresolved(report)
    sentinel = Path(state_dir) / STOP_DIRNAME / run_id
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("stop\n", encoding="utf-8")
    deadline = time.monotonic() + STOP_POLL_SECONDS
    while time.monotonic() < deadline:
        jobs = queue.owned_run_jobs(parent_session, run_id)
        if all(job.is_terminal for job in jobs):
            break
        time.sleep(STOP_POLL_INTERVAL)
    terminal = all(job.is_terminal for job in queue.owned_run_jobs(parent_session, run_id))
    return {
        "run_id": run_id,
        "stopped": terminal,
        "already_finished": False,
        "unresolved": unresolved,
    }


def _cmd_stop(args: argparse.Namespace) -> None:
    config = _load(args)
    queue = _queue(config)
    result = control_stop(queue, config.runtime.state_dir, args.session_id, args.run_id)
    print(json.dumps(result, separators=(",", ":")), flush=True)


# ---------------------------------------------------------------------------
# help / doctor / initial-mode
# ---------------------------------------------------------------------------
HELP_TEXT = """Orchestra 2 — submit work, track it, get one return.

Dispatch:
  dispatch --session-id ID --goal TEXT [--role ROLE] [--task-label LABEL]
    Submits the assignment through Submit, runs every queued job to a
    terminal state, and prints one acknowledgement JSON line, then one
    return JSON line with the assembled result for the session.
    Parent context text arrives on stdin; it is captured only for roles
    configured with parent context.

Session operations:
  status --session-id ID --mode MODE    Active jobs for the session, global counts, last completed run.
  history --session-id ID [--limit N]   The last N completed runs for the session, newest first.
  stop --session-id ID --run-id RUN     Cancel an active run owned by the session.
  roles                                 List configured roles, models, and skills (read-only).
  session-return --session-id ID --run-id RUN [--run-id RUN ...]
    Assembles one consolidated return across the explicitly listed completed
    runs of the session. Assembly is blocked loudly while any job of the
    session is still outstanding; jobs from unlisted runs are not included.
    Host plugins call this after every dispatched run of the session has
    drained and deliver the single consolidated return.

Setup:
  doctor                                Validate configuration, catalog, prompts, and harnesses.
  initial-mode                          Print the configured initial session mode.

Roles, models, harnesses, budgets, and skills come from configuration; see
the project README for the YAML layout.
"""


def roles_catalog(config: OrchestraConfig) -> dict[str, object]:
    """The configured role catalog as a host-neutral mapping. Read-only."""
    catalog = config.catalog
    return {
        "default_role": catalog.default_role,
        "roles": [
            {
                "name": name,
                "enabled": role.enabled,
                "model": role.model,
                "harness_config": role.harness_config,
                "auto_verify": role.auto_verify,
                "parent_context": role.parent_context,
                "skills": list(role.skills),
                "dispatch_hint": role.dispatch_hint,
            }
            for name, role in catalog.roles.items()
        ],
    }


def _cmd_roles(args: argparse.Namespace) -> None:
    """Print the configured role catalog. Read-only: nothing is mutated."""
    config = _load(args)
    print(json.dumps(roles_catalog(config), separators=(",", ":")), flush=True)


def _cmd_help(args: argparse.Namespace) -> None:
    print(HELP_TEXT, end="")


def _cmd_initial_mode(args: argparse.Namespace) -> None:
    config = _load(args)
    print(config.runtime.default_mode)


def doctor_report(config: OrchestraConfig) -> tuple[list[str], list[str]]:
    """Run the doctor checks and return (report lines, problems).

    The same checks back the CLI ``doctor`` command and the core session
    runtime's ``doctor`` operation, so diagnostics stay core-owned in one
    place. Pure reporting: the caller decides whether to exit nonzero.
    """
    lines: list[str] = []
    problems: list[str] = []
    lines.append("Orchestra doctor")
    lines.append(f"config: ok (loaded from {config.config_dir})")
    catalog = config.catalog
    lines.append(
        f"catalog: ok (default role {catalog.default_role}; "
        f"roles: {', '.join(catalog.roles)})"
    )
    for name, role in catalog.roles.items():
        if role.harness_config not in config.harnesses:
            problems.append(f"role {name!r} references unknown harness config {role.harness_config!r}")
    for name, harness in config.harnesses.items():
        executable = harness.command[0]
        found = shutil.which(executable) is not None or Path(executable).is_file()
        detail = "ok" if found else "NOT FOUND on PATH"
        lines.append(f"harness {name}: {detail} ({' '.join(harness.command)})")
        if not found:
            problems.append(f"harness {name!r} executable {executable!r} not found")
    lines.append(f"prompts: ok ({len(config.prompts)} keys)")
    state_dir = Path(config.runtime.state_dir)
    log_dir = Path(config.runtime.log_dir)
    for label, path in (("state dir", state_dir), ("log dir", log_dir)):
        try:
            path.mkdir(parents=True, exist_ok=True)
            lines.append(f"{label}: ok ({path})")
        except OSError as exc:
            problems.append(f"{label} {path} unavailable: {exc}")
    skills_dir = Path(config.config_dir) / SKILLS_DIRNAME
    configured = {skill for role in catalog.roles.values() for skill in role.skills}
    configured.update(catalog.orchestrator_skills)
    if not configured:
        lines.append("skills: no role skills configured")
    else:
        for skill in sorted(configured):
            found = (skills_dir / skill / "SKILL.md").is_file()
            lines.append(f"skill {skill}: {'ok' if found else 'MISSING'}")
            if not found:
                problems.append(f"skill {skill!r} not found under {skills_dir}")
    return lines, problems


def _cmd_doctor(args: argparse.Namespace) -> None:
    config = _load(args)
    lines, problems = doctor_report(config)
    for line in lines:
        print(line)
    if problems:
        for problem in problems:
            print(f"problem: {problem}")
        raise SystemExit(1)
    print("doctor: all checks passed")


# ---------------------------------------------------------------------------
# tool-info
# ---------------------------------------------------------------------------


# Model-callable management operations: the CLI subcommands hosts expose as
# tools. One mapping reused for CLI routing (see ``main``) and the tool-info
# actions projection; not a copy of every CLI command.
MANAGEMENT_HANDLERS: dict[str, Callable[[argparse.Namespace], None]] = {
    "status": _cmd_status,
    "history": _cmd_history,
    "stop": _cmd_stop,
    "roles": _cmd_roles,
    "help": _cmd_help,
    "doctor": _cmd_doctor,
}


def _cmd_tool_info(args: argparse.Namespace) -> None:
    """Emit core tool metadata as one JSON object for host registration.

    Dispatch description integrates a factual operation explanation with the
    configured delegation_guidance prompt entry.
    """
    config = _load(args)
    delegation = config.prompts["delegation_guidance"]
    role_names = sorted(
        {"default"}
        | {name for name, role in config.catalog.roles.items() if role.enabled == "manual"}
    )
    role_description = (
        f"Select a role: {', '.join(role_names)}. "
        f"Omit the role or use default for the catalog default ({config.catalog.default_role})."
    )
    dispatch_desc = (
        "Submit an assignment to a configured subagent role and run it to "
        "completion. Returns an acknowledgement line immediately, then one "
        "consolidated return when every dispatched job finishes.\n\n"
        + delegation
    )
    print(
        json.dumps(
            {
                "dispatch": {
                    "label": "Dispatch",
                    "description": dispatch_desc,
                    "params": {
                        "goal": "The assignment text for the subagent.",
                        "additionalContext": "Supplementary context text for the assignment.",
                        "role": role_description,
                        "taskLabel": "Short display label for this dispatch (optional).",
                    },
                },
                "status": {
                    "label": "Status",
                    "description": (
                        "Only use this tool when the user explicitly asks for an "
                        "Orchestra status, history, control, diagnostic, or help "
                        "action. Do not call it to monitor, poll, or wait on "
                        "dispatched work; returns arrive to this session "
                        "automatically. "
                        "Query session and global job status, list recent history, "
                        "cancel an active run, show help, run diagnostics, or "
                        "list configured roles (read-only)."
                    ),
                    "params": {
                        "action": "Operation to perform.",
                        "limit": "Maximum number of history entries to return.",
                        "runId": "Run identifier for stop actions.",
                    },
                },
                "command": {
                    "description": (
                        "Orchestra orchestration: dispatch work to subagents, "
                        "track active runs, retrieve consolidated returns."
                    ),
                },
                "actions": list(MANAGEMENT_HANDLERS),
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
